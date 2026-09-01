/**
 * Turning the published cell surface into a candidate set, using Phase 4's rules.
 *
 * The filters are Phase 4's and are applied here in the same fixed order, with each cell
 * counted under the FIRST reason that applies, so the browser's candidate universe matches
 * the one the accepted pipeline reasoned about:
 *
 * 1. **uninhabited** - no resident population;
 * 2. **beyond the primary/secondary road network** - precomputed in the artifact, because
 *    the road geometry is a 380k-vertex dataset per state that has no business in a
 *    browser. A cell is admitted here only if the pipeline already judged it near an
 *    arterial;
 * 3. **already saturated** - existing public operational DCFC ports per 1,000 BEV of
 *    demand at or above the threshold.
 *
 * **There is no substation-proximity filter**, because Phase 0 located no authoritative
 * national dataset and §7.9 requires Core siting to function without one.
 */

import { latLngToCell, gridDisk, cellToLatLng } from "h3-js";

import type { HexRow } from "../data/hexes";
import type { Candidate, Coverage } from "./greedy";

export const SATURATION_PORTS_PER_1K = 2.0;
export const COVERAGE_K = 1;

export interface CandidateSet {
  readonly candidates: Candidate[];
  readonly coverage: Coverage;
  readonly excluded: Readonly<Record<string, number>>;
}

export function buildCandidates(
  rows: readonly HexRow[],
  saturationPortsPer1k: number = SATURATION_PORTS_PER_1K,
  k: number = COVERAGE_K,
): CandidateSet {
  const excluded: Record<string, number> = {};
  const drop = (reason: string) => {
    excluded[reason] = (excluded[reason] ?? 0) + 1;
  };

  const kept: Candidate[] = [];
  for (const row of rows) {
    if (row.population < 1) {
      drop("uninhabited");
      continue;
    }
    if (!row.passes_road_filter) {
      drop("beyond_primary_secondary_road_network");
      continue;
    }
    if (row.demand_bev > 0) {
      const portsPer1k = (row.dcfc_ports * 1000) / row.demand_bev;
      if (portsPer1k >= saturationPortsPer1k) {
        drop("already_saturated");
        continue;
      }
    }
    kept.push({
      h3_index: row.h3_index,
      demand: row.demand_bev,
      equity_population: row.equity_population,
      population: row.population,
      uncertainty_score: row.uncertainty_score,
      sub_state_anchored_share: row.sub_state_anchored_share,
      dominant_evidence_grain: row.dominant_evidence_grain,
      existing_dcfc_ports: row.dcfc_ports,
      cost: 1,
    });
  }

  const present = new Set(kept.map((c) => c.h3_index));
  const coverage = new Map<string, string[]>();
  for (const candidate of kept) {
    coverage.set(
      candidate.h3_index,
      gridDisk(candidate.h3_index, k).filter((cell) => present.has(cell)),
    );
  }
  return { candidates: kept, coverage, excluded };
}

export { latLngToCell, cellToLatLng };
