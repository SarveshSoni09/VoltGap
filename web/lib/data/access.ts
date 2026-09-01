/**
 * Block-group access points, and the live threshold arithmetic.
 *
 * The per-point distances ship rather than a precomputed curve, so the threshold control
 * is genuinely live: the browser recomputes the affected population at whatever value the
 * user picks instead of interpolating between server-chosen points.
 */

import { asNumber, asString, readArtifact, type Row } from "./parquet";

export interface AccessPoint {
  readonly population: number;
  readonly km_to_nearest_dcfc_site: number;
  readonly km_to_nearest_l2_site: number;
  readonly income_share_under_35k: number;
  readonly state_fips: string;
}

const COLUMNS = [
  "population", "km_to_nearest_dcfc_site", "km_to_nearest_l2_site",
  "income_share_under_35k", "state_fips",
] as const;

let cache: Promise<AccessPoint[]> | null = null;

export function loadAccessPoints(): Promise<AccessPoint[]> {
  cache ??= readArtifact("access_points.parquet", COLUMNS).then((rows) =>
    rows.map(
      (row: Row): AccessPoint => ({
        population: asNumber(row.population),
        km_to_nearest_dcfc_site: asNumber(row.km_to_nearest_dcfc_site),
        km_to_nearest_l2_site: asNumber(row.km_to_nearest_l2_site),
        income_share_under_35k: asNumber(row.income_share_under_35k),
        state_fips: asString(row.state_fips),
      }),
    ),
  );
  return cache;
}

export interface GapSummary {
  readonly population: number;
  readonly share: number;
  readonly points: number;
  readonly equityPopulation: number;
}

/** Population beyond the threshold. The same arithmetic the pipeline publishes. */
export function gapAtThreshold(
  points: readonly AccessPoint[],
  thresholdKm: number,
  column: "km_to_nearest_dcfc_site" | "km_to_nearest_l2_site" = "km_to_nearest_dcfc_site",
): GapSummary {
  let population = 0;
  let total = 0;
  let count = 0;
  let equity = 0;
  for (const point of points) {
    total += point.population;
    if (point[column] > thresholdKm) {
      population += point.population;
      equity += point.population * point.income_share_under_35k;
      count += 1;
    }
  }
  return {
    population,
    share: total > 0 ? population / total : 0,
    points: count,
    equityPopulation: equity,
  };
}
