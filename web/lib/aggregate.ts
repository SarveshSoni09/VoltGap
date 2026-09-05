/**
 * Presentation-only aggregation for the national view.
 *
 * At national zoom a resolution-6 cell is a couple of pixels, so 53,208 of them read as
 * scattered dots rather than as the geography they describe. This rolls them up to a
 * coarser H3 resolution **for display only**.
 *
 * **The analytical surface is untouched.** Nothing here writes back, nothing feeds the
 * solver, and the published artifact stays at resolution 6. `cellToParent` is exact
 * containment - every resolution-6 cell has exactly one parent at any coarser resolution -
 * so summing an additive quantity over children conserves it exactly. `tests/aggregate.test.ts`
 * asserts that on the real national surface.
 *
 * **Not every quantity is additive, and the ones that are not are marked.** Demand,
 * population and port counts sum. A distance does not: the distance from a large area to
 * the nearest charger is not the sum of its parts, so it is reported as a
 * population-weighted mean and is a display summary, not an analytical value.
 */

import { cellToParent } from "h3-js";

import type { Tier } from "./vocabulary";

/** Native analytical resolution. Never aggregated away from for anything but drawing. */
export const NATIVE_RESOLUTION = 6;

/**
 * Display resolution by zoom. Chosen so a cell stays a few pixels across: at zoom 3-4 the
 * whole country is ~1000 px wide, where resolution 4 cells (~1,770 km²) read as regions
 * and resolution 6 cells (~36 km²) read as noise.
 */
export function displayResolution(zoom: number): number {
  // Resolution 4 (~1,770 km² per cell), not 3 (~12,400 km²), at national zoom. A parent
  // is drawn if ANY child has population, so an over-coarse grouping paints a large
  // hexagon for one small town and makes the country look uniformly covered — when in
  // fact 78.8% of the landmass has no cell at all. Resolution 4 groups enough to read as
  // geography while leaving the genuine gaps visible.
  if (zoom < 5) return 4;
  if (zoom < 7) return 5;
  return NATIVE_RESOLUTION;
}

export interface AggregatedCell {
  readonly h3_index: string;
  /** The county contributing the most demand here, so an aggregated cell is still
   *  identifiable. A grouped area can span several; this names the dominant one. */
  readonly county_name: string;
  readonly state_code: string;
  /** FIPS of the dominant county's state, for links that need one. */
  readonly state_fips: string;
  /** How many counties the grouped area touches, so the label is not oversold. */
  readonly counties: number;
  /**
   * The published tier, carried straight through for a single cell.
   *
   * `null` once cells are grouped for display: §7.4.2's tier is defined for one estimate,
   * and picking a winner among several would be a new classification rule invented in the
   * interface. Grouped areas report their sub-state-anchored share instead, which is a
   * quantity the pipeline actually publishes.
   */
  readonly confidence_tier: Tier | null;
  /** Additive. Conserved exactly against the native surface. */
  readonly demand_bev: number;
  readonly population: number;
  readonly equity_population: number;
  readonly dcfc_ports: number;
  /** Population-weighted mean. A display summary, not an analytical distance. */
  readonly km_to_nearest_dcfc_site: number;
  /** Share of this area's demand resting on observed sub-state evidence. */
  readonly sub_state_anchored_share: number;
  /** Demand-weighted mean of the children's uncertainty scores. */
  readonly uncertainty_score: number;
  readonly children: number;
}

export interface NativeCell {
  readonly h3_index: string;
  readonly county_name: string;
  readonly state_code: string;
  readonly state_fips: string;
  /** §7.4.2's tier, as the pipeline published it. Never re-derived in the browser. */
  readonly confidence_tier: Tier;
  readonly demand_bev: number;
  readonly population: number;
  readonly equity_population: number;
  readonly dcfc_ports: number;
  readonly km_to_nearest_dcfc_site: number;
  readonly sub_state_anchored_share: number;
  readonly uncertainty_score: number;
}

/**
 * Roll native cells up to `resolution`.
 *
 * Native resolution goes through the same grouping rather than short-circuiting, because
 * the published surface's grain is **(h3_index, state_fips)**, not h3_index: a cell
 * straddling a state line is published once per state, each row carrying that state's
 * share. 296 of 52,912 national cells are split this way. One hexagon on screen must give
 * one answer, so the state parts are summed exactly as the display roll-up sums children,
 * and the same conservation tests cover both paths.
 */
export function aggregate(
  cells: readonly NativeCell[],
  resolution: number,
): AggregatedCell[] {
  const groups = new Map<string, {
    demand: number; population: number; equity: number; ports: number;
    distanceWeighted: number; anchoredWeighted: number; uncertaintyWeighted: number;
    children: number; counties: Map<string, number>; tiers: Set<Tier>;
  }>();

  for (const cell of cells) {
    const parent =
      resolution >= NATIVE_RESOLUTION
        ? cell.h3_index
        : cellToParent(cell.h3_index, resolution);
    let g = groups.get(parent);
    if (g === undefined) {
      g = {
        demand: 0, population: 0, equity: 0, ports: 0,
        distanceWeighted: 0, anchoredWeighted: 0, uncertaintyWeighted: 0, children: 0,
        counties: new Map(), tiers: new Set(),
      };
      groups.set(parent, g);
    }
    g.demand += cell.demand_bev;
    g.population += cell.population;
    g.equity += cell.equity_population;
    g.ports += cell.dcfc_ports;
    // Distance is weighted by population: an empty cell's distance should not drag the
    // summary of a populated area. Non-finite distances (no charger anywhere) are skipped
    // rather than poisoning the mean with Infinity.
    if (Number.isFinite(cell.km_to_nearest_dcfc_site)) {
      g.distanceWeighted += cell.km_to_nearest_dcfc_site * cell.population;
    }
    g.anchoredWeighted += cell.sub_state_anchored_share * cell.demand_bev;
    g.uncertaintyWeighted += cell.uncertainty_score * cell.demand_bev;
    g.children += 1;
    g.tiers.add(cell.confidence_tier);
    if (cell.county_name) {
      const key = `${cell.county_name}|${cell.state_code}|${cell.state_fips}`;
      // Weighted by demand, so the label names where the value actually is.
      g.counties.set(key, (g.counties.get(key) ?? 0) + cell.demand_bev);
    }
  }

  const out: AggregatedCell[] = [];
  for (const [h3_index, g] of groups) {
    const ranked = [...g.counties.entries()].sort((a, b) => b[1] - a[1]);
    const [dominant] = ranked;
    const [county = "", state = "", fips = ""] = dominant ? dominant[0].split("|") : [];
    out.push({
      h3_index,
      county_name: county,
      state_code: state,
      state_fips: fips,
      counties: ranked.length,
      // One published estimate underneath means one published tier to report. Where the
      // parts disagree there is no published tier for the group, and none is invented.
      confidence_tier: g.tiers.size === 1 ? [...g.tiers][0] ?? null : null,
      demand_bev: g.demand,
      population: g.population,
      equity_population: g.equity,
      dcfc_ports: g.ports,
      km_to_nearest_dcfc_site: g.population > 0 ? g.distanceWeighted / g.population : 0,
      sub_state_anchored_share: g.demand > 0 ? g.anchoredWeighted / g.demand : 0,
      uncertainty_score: g.demand > 0 ? g.uncertaintyWeighted / g.demand : 0,
      children: g.children,
    });
  }
  return out;
}
