/**
 * The national cell surface, as the views consume it.
 *
 * Columnar: the worker decodes the artifact and hands back typed arrays, and nothing here
 * allocates 53,208 objects. Loaded once and cached in module scope, because every view
 * wants the same thing and re-fetching per navigation would be 3 MB of pointless traffic.
 */

import { type ColumnSpec, ColumnTable, loadTable } from "./table";
import type { Tier } from "../vocabulary";

export const HEX_SPEC: ColumnSpec = {
  columns: [
    "h3_index", "state_fips", "latitude", "longitude", "demand_bev", "population",
    "households", "equity_population", "uncertainty_score", "confidence_tier",
    "sub_state_anchored_share", "dominant_evidence_grain", "station_count",
    "dcfc_ports", "l2_ports", "km_to_nearest_dcfc_site", "km_to_nearest_public_site",
    "passes_road_filter",
  ],
  stringColumns: ["h3_index", "state_fips", "confidence_tier", "dominant_evidence_grain"],
  boolColumns: ["passes_road_filter"],
};

let cache: Promise<ColumnTable> | null = null;

export function loadHexTable(): Promise<ColumnTable> {
  cache ??= loadTable("hex6_national.parquet", HEX_SPEC);
  return cache;
}

/** One cell, materialised. For selections, never for a loop over the whole surface. */
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
  readonly passes_road_filter: boolean;
}

export function hexRow(table: ColumnTable, index: number): HexRow {
  const tier = table.strs("confidence_tier")[index] ?? "C";
  return {
    h3_index: table.strs("h3_index")[index] ?? "",
    state_fips: table.strs("state_fips")[index] ?? "",
    latitude: table.nums("latitude")[index] ?? 0,
    longitude: table.nums("longitude")[index] ?? 0,
    demand_bev: table.nums("demand_bev")[index] ?? 0,
    population: table.nums("population")[index] ?? 0,
    households: table.nums("households")[index] ?? 0,
    equity_population: table.nums("equity_population")[index] ?? 0,
    uncertainty_score: table.nums("uncertainty_score")[index] ?? 0,
    confidence_tier: (tier === "A" || tier === "B" || tier === "C" ? tier : "C") as Tier,
    sub_state_anchored_share: table.nums("sub_state_anchored_share")[index] ?? 0,
    dominant_evidence_grain: table.strs("dominant_evidence_grain")[index] ?? "",
    station_count: table.nums("station_count")[index] ?? 0,
    dcfc_ports: table.nums("dcfc_ports")[index] ?? 0,
    l2_ports: table.nums("l2_ports")[index] ?? 0,
    km_to_nearest_dcfc_site: table.nums("km_to_nearest_dcfc_site")[index] ?? 0,
    km_to_nearest_public_site: table.nums("km_to_nearest_public_site")[index] ?? 0,
    passes_road_filter: table.bools("passes_road_filter")[index] === 1,
  };
}

/**
 * §11.1: every aggregate reports the share of underlying demand that is sub-state anchored
 * versus modeled, with the evidence-grain breakdown beneath it.
 */
export interface EvidenceSummary {
  readonly demandTotal: number;
  readonly subStateAnchoredShare: number;
  readonly byGrain: Readonly<Record<string, number>>;
  readonly byTier: Readonly<Record<Tier, number>>;
}

export function summarise(table: ColumnTable, indices?: readonly number[]): EvidenceSummary {
  const demand = table.nums("demand_bev");
  const anchoredShare = table.nums("sub_state_anchored_share");
  const grains = table.strs("dominant_evidence_grain");
  const tiers = table.strs("confidence_tier");

  let demandTotal = 0;
  let anchored = 0;
  const byGrain: Record<string, number> = {};
  const byTier: Record<Tier, number> = { A: 0, B: 0, C: 0 };
  const count = indices ? indices.length : table.length;
  for (let k = 0; k < count; k += 1) {
    const i = indices ? (indices[k] ?? 0) : k;
    const value = demand[i] ?? 0;
    demandTotal += value;
    anchored += value * (anchoredShare[i] ?? 0);
    const grain = grains[i] ?? "";
    byGrain[grain] = (byGrain[grain] ?? 0) + value;
    const tier = (tiers[i] ?? "C") as Tier;
    if (tier in byTier) byTier[tier] += value;
  }
  return {
    demandTotal,
    subStateAnchoredShare: demandTotal > 0 ? anchored / demandTotal : 0,
    byGrain,
    byTier,
  };
}
