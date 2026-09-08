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

import { cellToParent } from "h3-js";

import { type ColumnSpec, ColumnTable, loadTable } from "./table";

export const ACCESS_SPEC: ColumnSpec = {
  columns: [
    "h3_index", "state_fips", "population", "km_to_nearest_dcfc_site",
    "km_to_nearest_l2_site", "income_share_under_35k",
  ],
  stringColumns: ["h3_index", "state_fips"],
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

/**
 * Population beyond the threshold. The same arithmetic the pipeline publishes.
 *
 * `stateFips` narrows BOTH the numerator and the denominator, so the share it reports is
 * "this share of the selected state's people", never a state count over a national total.
 * That is the whole reason the filter lives in here rather than being applied to the
 * result: a ratio whose two halves describe different geographies is a wrong number, not
 * a presentation choice.
 */
export function gapAtThreshold(
  table: ColumnTable,
  thresholdKm: number,
  column: "km_to_nearest_dcfc_site" | "km_to_nearest_l2_site" = "km_to_nearest_dcfc_site",
  stateFips?: string,
): GapSummary {
  const population = table.nums("population");
  const distance = table.nums(column);
  const income = table.nums("income_share_under_35k");
  const states = table.strs("state_fips");
  let inGap = 0;
  let total = 0;
  let count = 0;
  let equity = 0;
  for (let i = 0; i < table.length; i += 1) {
    if (stateFips !== undefined && states[i] !== stateFips) continue;
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


/**
 * The gap geography, rolled up to H3 cells from the SAME points and the SAME threshold the
 * summary statistics use.
 *
 * That shared derivation is the point. Before this, the page had no map at all: the
 * threshold drove the numbers and there was nothing spatial to respond to it. Deriving
 * both from one pass here makes it impossible for the map and the figures to disagree, and
 * `tests/access.test.ts` asserts the map's population equals the summary's exactly.
 */
export interface GapCell {
  readonly h3_index: string;
  /** Population in this cell that is beyond the threshold. */
  readonly population: number;
  /**
   * Distance among the points beyond the threshold, population-weighted.
   *
   * Falls back to the plain mean where the cell holds no population: 230 of the 20,781
   * cells beyond 16.1 km nationally are uninhabited block groups. A weighted mean over
   * zero weight is undefined, and reporting it as 0 km would say the opposite of what is
   * true about a place with no charging near it.
   */
  readonly km: number;
  /** Of `population`, how many are in lower-income households. */
  readonly equity: number;
  readonly points: number;
  /** For the state summary and the hand-off to the Studio. */
  readonly state_fips: string;
}

export function gapCells(
  table: ColumnTable,
  thresholdKm: number,
  column: "km_to_nearest_dcfc_site" | "km_to_nearest_l2_site" = "km_to_nearest_dcfc_site",
  stateFips?: string,
): GapCell[] {
  const cells = table.strs("h3_index");
  const population = table.nums("population");
  const distance = table.nums(column);
  const income = table.nums("income_share_under_35k");
  const states = table.strs("state_fips");

  const groups = new Map<
    string,
    { pop: number; wkm: number; km: number; eq: number; n: number; state: string }>();
  for (let i = 0; i < table.length; i += 1) {
    if (stateFips !== undefined && states[i] !== stateFips) continue;
    if ((distance[i] ?? 0) <= thresholdKm) continue;
    const cell = cells[i] ?? "";
    let g = groups.get(cell);
    if (g === undefined) {
      g = { pop: 0, wkm: 0, km: 0, eq: 0, n: 0, state: states[i] ?? "" };
      groups.set(cell, g);
    }
    const people = population[i] ?? 0;
    g.pop += people;
    g.wkm += (distance[i] ?? 0) * people;
    g.km += distance[i] ?? 0;
    g.eq += people * (income[i] ?? 0);
    g.n += 1;
  }

  const out: GapCell[] = [];
  for (const [h3_index, g] of groups) {
    out.push({
      h3_index,
      population: g.pop,
      km: g.pop > 0 ? g.wkm / g.pop : g.km / g.n,
      equity: g.eq,
      points: g.n,
      state_fips: g.state,
    });
  }
  return out;
}


/**
 * Roll gap cells up for display, exactly as the national view rolls up its surface.
 *
 * 20,781 resolution-6 cells beyond 16.1 km read as scattered specks at national zoom
 * the reader can see that a gap exists but not where it is. Grouping makes the shape of
 * the gap legible, and the same conservation rule applies: population and affected
 * lower-income population are summed, distance is population-weighted, and nothing is
 * created or destroyed. `tests/access.test.ts` asserts it.
 */
export function aggregateGaps(
  cells: readonly GapCell[], resolution: number,
): GapCell[] {
  if (resolution >= 6) return [...cells];
  const groups = new Map<
    string, { pop: number; wkm: number; km: number; eq: number; n: number; state: string }
  >();
  for (const cell of cells) {
    const parent = cellToParent(cell.h3_index, resolution);
    let g = groups.get(parent);
    if (g === undefined) {
      g = { pop: 0, wkm: 0, km: 0, eq: 0, n: 0, state: cell.state_fips };
      groups.set(parent, g);
    }
    g.pop += cell.population;
    g.wkm += cell.km * cell.population;
    g.km += cell.km * cell.points;
    g.eq += cell.equity;
    g.n += cell.points;
  }
  const out: GapCell[] = [];
  for (const [h3_index, g] of groups) {
    out.push({
      h3_index,
      population: g.pop,
      km: g.pop > 0 ? g.wkm / g.pop : g.km / g.n,
      equity: g.eq,
      points: g.n,
      state_fips: g.state,
    });
  }
  return out;
}
