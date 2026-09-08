/**
 * Why a candidate area ranked highly, assembled only from that area's own model output.
 *
 * A ranked table without explanation is a black box. These reasons are derived from
 * published values and thresholds: nothing is invented, and an area only gets a reason
 * that its own data supports, so two rows rarely read the same.
 *
 * **What these are not.** They explain what the model saw, not that a site is buildable,
 * permitted, available, or the right choice. No causal or feasibility language.
 */

import type { HexRow } from "./data/hexes";

export interface Reason {
  readonly text: string;
  /** Sorted first so the strongest evidence leads. */
  readonly weight: number;
}

export interface Cohort {
  /** Sorted values for each dimension, so an area's standing can be located in them. */
  readonly demand: number[];
  readonly equity: number[];
  readonly distance: number[];
}

const sorted = (xs: number[]) => [...xs].filter(Number.isFinite).sort((a, b) => a - b);

export function cohortOf(rows: readonly HexRow[]): Cohort {
  return {
    demand: sorted(rows.map((r) => r.demand_bev)),
    equity: sorted(rows.map((r) => r.equity_population)),
    distance: sorted(rows.map((r) => r.km_to_nearest_dcfc_site)),
  };
}

/** Where this value sits among its peers, 0 (lowest) to 1 (highest). */
function percentile(values: readonly number[], value: number): number {
  if (values.length === 0 || !Number.isFinite(value)) return 0;
  let low = 0;
  let high = values.length;
  while (low < high) {
    const mid = (low + high) >> 1;
    if ((values[mid] ?? 0) < value) low = mid + 1;
    else high = mid;
  }
  return low / values.length;
}

/**
 * Reasons this area stands out, **most distinctive first**.
 *
 * Ordering by a fixed importance would make every row lead with the same sentence, which
 * tells a reader nothing about why THIS area was picked over the next one. Instead each
 * reason is ranked by how unusual the area is on that dimension relative to the other
 * eligible areas, so the lead reason is the one that actually distinguishes it.
 */
export function reasonsFor(row: HexRow, cohort: Cohort): string[] {
  const reasons: Reason[] = [];

  const demandRank = percentile(cohort.demand, row.demand_bev);
  if (demandRank >= 0.6) {
    reasons.push({
      text: demandRank >= 0.9
        ? "Among the highest estimated EV demand in the state"
        : "Above-average estimated EV demand",
      weight: demandRank,
    });
  }

  if (row.dcfc_ports === 0) {
    // Common among candidates, so it leads only when nothing else distinguishes the area.
    reasons.push({ text: "No public fast charging here today", weight: 0.55 });
  } else if (row.demand_bev / row.dcfc_ports > 500) {
    reasons.push({ text: "Existing fast charging is thin for the demand", weight: 0.72 });
  }

  const distanceRank = percentile(cohort.distance, row.km_to_nearest_dcfc_site);
  if (distanceRank >= 0.7 && Number.isFinite(row.km_to_nearest_dcfc_site)) {
    reasons.push({
      text: `Nearest fast charging is ${row.km_to_nearest_dcfc_site.toFixed(0)} km away`,
      weight: distanceRank,
    });
  }

  const equityRank = percentile(cohort.equity, row.equity_population);
  if (equityRank >= 0.6) {
    reasons.push({
      text: equityRank >= 0.9
        ? "Reaches one of the largest underserved populations here"
        : "Reaches an above-average underserved population",
      weight: equityRank,
    });
  }

  if (row.confidence_tier === "A") {
    reasons.push({
      text: "Local registration data supports the estimate",
      weight: 0.4,
    });
  }

  return reasons.sort((a, b) => b.weight - a.weight).map((r) => r.text);
}

/** The one-line version for the table, so a reader sees the gist without expanding. */
export function headlineReason(row: HexRow, cohort: Cohort): string {
  return reasonsFor(row, cohort)[0] ?? "Meets the screening criteria";
}

/**
 * A human-readable name for an area.
 *
 * Prefers the county the pipeline attributes the area to. Falls back to a stable
 * "Area NN" rather than inventing a place name - the H3 centroid is not an address and
 * must never be presented as one.
 */
export function areaName(row: HexRow, rank: number): string {
  return placeName(row.county_name, row.state_code) ?? `Area ${String(rank).padStart(2, "0")}`;
}

/**
 * The one place identity the whole product uses, so a table row and a map tooltip name the
 * same cell the same way.
 *
 * Returns null rather than a guess when the pipeline could not attribute a county. No city
 * is inferred: an H3 centroid is not an address, and "Seattle area" would be an invention
 * unless a place dataset supported it. That limitation is recorded in the Phase 6 report.
 */
export function placeName(county: string, state: string): string | null {
  if (!county || !state) return null;
  return `${county}, ${state}`;
}

/** How a grouped area is described when it spans more than one county. */
export function groupedPlaceName(
  county: string, state: string, counties: number,
): string | null {
  const base = placeName(county, state);
  if (base === null) return null;
  if (counties <= 1) return base;
  return `${base} and ${counties - 1} nearby ${counties === 2 ? "county" : "counties"}`;
}
