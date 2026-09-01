/**
 * CSV and GeoJSON export of a selected portfolio.
 *
 * §15.5 Phase 6 requires these to "produce valid CSV and GeoJSON verified by parse", so
 * both are written to be parseable by something other than the code that wrote them, and
 * `tests/exporters.test.ts` parses them back rather than string-matching.
 *
 * **Every exported row carries its confidence tier and evidence grain.** §17: no modeled
 * value ships without its uncertainty. A CSV that left them behind would be the easiest
 * possible way for a caveat to get lost - the file outlives the page that made it.
 */

import { type Tier, TIER_LABELS } from "./vocabulary";

export interface PortfolioRow {
  readonly h3_index: string;
  readonly latitude: number;
  readonly longitude: number;
  readonly rank: number;
  readonly demand_bev: number;
  readonly equity_population: number;
  readonly population: number;
  readonly uncertainty_score: number;
  readonly confidence_tier: Tier;
  readonly dominant_evidence_grain: string;
  readonly sub_state_anchored_share: number;
  readonly existing_dcfc_ports: number;
  readonly km_to_nearest_dcfc_site: number;
}

/**
 * Provenance written into every export, so a file separated from this page still says what
 * it is and what it is not. Wording is fixed by §11.5 and D3.
 */
export const EXPORT_PROVENANCE = [
  "VoltGap ranked candidate portfolio.",
  "A ranking, not a claim of optimality: no ground truth for optimal siting exists.",
  "Produced by the interactive greedy approximation, not the published analytical frontier.",
  "No approximation bound is claimed for the interactive solver.",
  "Every row carries its confidence tier; tier A means sub-state anchored, NOT observed.",
] as const;

const CSV_COLUMNS: readonly (keyof PortfolioRow)[] = [
  "rank",
  "h3_index",
  "latitude",
  "longitude",
  "demand_bev",
  "equity_population",
  "population",
  "uncertainty_score",
  "confidence_tier",
  "dominant_evidence_grain",
  "sub_state_anchored_share",
  "existing_dcfc_ports",
  "km_to_nearest_dcfc_site",
];

/** RFC 4180 quoting: double the quotes, wrap anything containing a delimiter. */
function csvCell(value: unknown): string {
  const text = value === null || value === undefined ? "" : String(value);
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function toCsv(rows: readonly PortfolioRow[]): string {
  const preamble = EXPORT_PROVENANCE.map((line) => `# ${line}`).join("\n");
  const header = CSV_COLUMNS.join(",");
  const body = rows
    .map((row) => CSV_COLUMNS.map((column) => csvCell(row[column])).join(","))
    .join("\n");
  return `${preamble}\n${header}\n${body}\n`;
}

export interface PortfolioGeoJson {
  readonly type: "FeatureCollection";
  readonly properties: Record<string, unknown>;
  readonly features: readonly {
    readonly type: "Feature";
    readonly geometry: { readonly type: "Point"; readonly coordinates: [number, number] };
    readonly properties: Record<string, unknown>;
  }[];
}

export function toGeoJson(rows: readonly PortfolioRow[]): PortfolioGeoJson {
  return {
    type: "FeatureCollection",
    properties: {
      generator: "VoltGap",
      provenance: [...EXPORT_PROVENANCE],
      tier_labels: TIER_LABELS,
    },
    features: rows.map((row) => ({
      type: "Feature" as const,
      // GeoJSON is [longitude, latitude]. Reversing these is the classic silent error:
      // the file parses, and every point lands in the wrong hemisphere.
      geometry: { type: "Point" as const, coordinates: [row.longitude, row.latitude] },
      properties: {
        rank: row.rank,
        h3_index: row.h3_index,
        demand_bev: row.demand_bev,
        equity_population: row.equity_population,
        population: row.population,
        uncertainty_score: row.uncertainty_score,
        confidence_tier: row.confidence_tier,
        confidence_tier_label: TIER_LABELS[row.confidence_tier],
        dominant_evidence_grain: row.dominant_evidence_grain,
        sub_state_anchored_share: row.sub_state_anchored_share,
        existing_dcfc_ports: row.existing_dcfc_ports,
        km_to_nearest_dcfc_site: row.km_to_nearest_dcfc_site,
      },
    })),
  };
}

export function downloadBlob(name: string, mime: string, body: string): void {
  const url = URL.createObjectURL(new Blob([body], { type: mime }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  URL.revokeObjectURL(url);
}
