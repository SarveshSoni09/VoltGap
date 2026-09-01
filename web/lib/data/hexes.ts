/**
 * The national cell surface, as the views consume it.
 *
 * Loaded once and cached in module scope: it is 53,208 rows and every view wants the same
 * thing, so re-fetching per navigation would be 2.79 MB of pointless traffic.
 */

import { asNumber, asString, readArtifact, type Row } from "./parquet";
import type { Tier } from "../vocabulary";

export interface HexRow {
  readonly h3_index: string;
  readonly state_fips: string;
  readonly latitude: number;
  readonly longitude: number;
  readonly demand_bev: number;
  readonly population: number;
  readonly households: number;
  readonly equity_population: number;
  readonly uncertainty_score: number;
  readonly confidence_tier: Tier;
  readonly sub_state_anchored_share: number;
  readonly dominant_evidence_grain: string;
  readonly station_count: number;
  readonly dcfc_ports: number;
  readonly l2_ports: number;
  readonly km_to_nearest_dcfc_site: number;
  readonly km_to_nearest_public_site: number;
  /** Phase 4's road filter, precomputed by the pipeline. See lib/optimizer/candidates.ts. */
  readonly passes_road_filter: boolean;
}

const COLUMNS = [
  "h3_index", "state_fips", "latitude", "longitude", "demand_bev", "population",
  "households", "equity_population", "uncertainty_score", "confidence_tier",
  "sub_state_anchored_share", "dominant_evidence_grain", "station_count",
  "dcfc_ports", "l2_ports", "km_to_nearest_dcfc_site", "km_to_nearest_public_site",
  "passes_road_filter",
] as const;

let cache: Promise<HexRow[]> | null = null;

export function loadHexes(): Promise<HexRow[]> {
  cache ??= readArtifact("hex6_national.parquet", COLUMNS).then((rows) =>
    rows.map(toHexRow),
  );
  return cache;
}

function toHexRow(row: Row): HexRow {
  const tier = asString(row.confidence_tier);
  return {
    h3_index: asString(row.h3_index),
    state_fips: asString(row.state_fips),
    latitude: asNumber(row.latitude),
    longitude: asNumber(row.longitude),
    demand_bev: asNumber(row.demand_bev),
    population: asNumber(row.population),
    households: asNumber(row.households),
    equity_population: asNumber(row.equity_population),
    uncertainty_score: asNumber(row.uncertainty_score),
    confidence_tier: (tier === "A" || tier === "B" || tier === "C" ? tier : "C") as Tier,
    sub_state_anchored_share: asNumber(row.sub_state_anchored_share),
    dominant_evidence_grain: asString(row.dominant_evidence_grain),
    station_count: asNumber(row.station_count),
    dcfc_ports: asNumber(row.dcfc_ports),
    l2_ports: asNumber(row.l2_ports),
    km_to_nearest_dcfc_site: asNumber(row.km_to_nearest_dcfc_site),
    km_to_nearest_public_site: asNumber(row.km_to_nearest_public_site),
    passes_road_filter: row.passes_road_filter === true,
  };
}

/**
 * The §11.1 requirement: every aggregate reports the share of underlying demand that is
 * sub-state anchored versus modeled, with the evidence-grain breakdown beneath it.
 */
export interface EvidenceSummary {
  readonly demandTotal: number;
  readonly subStateAnchoredShare: number;
  readonly byGrain: Readonly<Record<string, number>>;
  readonly byTier: Readonly<Record<Tier, number>>;
}

export function summarise(rows: readonly HexRow[]): EvidenceSummary {
  let demandTotal = 0;
  let anchored = 0;
  const byGrain: Record<string, number> = {};
  const byTier: Record<Tier, number> = { A: 0, B: 0, C: 0 };
  for (const row of rows) {
    demandTotal += row.demand_bev;
    anchored += row.demand_bev * row.sub_state_anchored_share;
    byGrain[row.dominant_evidence_grain] =
      (byGrain[row.dominant_evidence_grain] ?? 0) + row.demand_bev;
    byTier[row.confidence_tier] += row.demand_bev;
  }
  return {
    demandTotal,
    subStateAnchoredShare: demandTotal > 0 ? anchored / demandTotal : 0,
    byGrain,
    byTier,
  };
}
