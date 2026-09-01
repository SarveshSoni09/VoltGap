/**
 * Block-group access points, and the live threshold arithmetic.
 *
 * The per-point distances ship rather than a precomputed curve, so the threshold control
 * is genuinely live: the browser recomputes the affected population at whatever value the
 * user picks instead of interpolating between server-chosen points.
 *
 * Columnar, and decoded in a worker. 239,780 points is where materialising row objects
 * would hurt most - the sensitivity curve sweeps every point once per threshold, and it
 * does that over typed arrays.
 */

import { type ColumnSpec, ColumnTable, loadTable } from "./table";

export const ACCESS_SPEC: ColumnSpec = {
  columns: [
    "population", "km_to_nearest_dcfc_site", "km_to_nearest_l2_site",
    "income_share_under_35k",
  ],
  stringColumns: [],
  boolColumns: [],
};

let cache: Promise<ColumnTable> | null = null;

export function loadAccessTable(): Promise<ColumnTable> {
  cache ??= loadTable("access_points.parquet", ACCESS_SPEC);
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
  table: ColumnTable,
  thresholdKm: number,
  column: "km_to_nearest_dcfc_site" | "km_to_nearest_l2_site" = "km_to_nearest_dcfc_site",
): GapSummary {
  const population = table.nums("population");
  const distance = table.nums(column);
  const income = table.nums("income_share_under_35k");
  let inGap = 0;
  let total = 0;
  let count = 0;
  let equity = 0;
  for (let i = 0; i < table.length; i += 1) {
    const people = population[i] ?? 0;
    total += people;
    if ((distance[i] ?? 0) > thresholdKm) {
      inGap += people;
      equity += people * (income[i] ?? 0);
      count += 1;
    }
  }
  return {
    population: inGap,
    share: total > 0 ? inGap / total : 0,
    points: count,
    equityPopulation: equity,
  };
}
