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
  readonly demand_bev: number;
  readonly population: number;
  readonly equity_population: number;
  readonly dcfc_ports: number;
  readonly km_to_nearest_dcfc_site: number;
  readonly sub_state_anchored_share: number;
  readonly uncertainty_score: number;
}

/**
 * Roll native cells up to `resolution`. Returns the input unchanged when it is already
 * native, so the caller never pays for a no-op.
 */
export function aggregate(
  cells: readonly NativeCell[],
  resolution: number,
): AggregatedCell[] {
  if (resolution >= NATIVE_RESOLUTION) {
    return cells.map((c) => ({ ...c, children: 1 }));
  }
  const groups = new Map<string, {
    demand: number; population: number; equity: number; ports: number;
    distanceWeighted: number; anchoredWeighted: number; uncertaintyWeighted: number;
    children: number;
  }>();

  for (const cell of cells) {
    const parent = cellToParent(cell.h3_index, resolution);
    let g = groups.get(parent);
    if (g === undefined) {
      g = {
        demand: 0, population: 0, equity: 0, ports: 0,
        distanceWeighted: 0, anchoredWeighted: 0, uncertaintyWeighted: 0, children: 0,
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
  }

  const out: AggregatedCell[] = [];
  for (const [h3_index, g] of groups) {
    out.push({
      h3_index,
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
