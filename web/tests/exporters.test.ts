/**
 * Exports are "verified by parse" (§15.5 Phase 6), so these tests parse the output rather
 * than matching strings. A string assertion would pass on a file no tool could read.
 */

import { describe, expect, it } from "vitest";

import {
  EXPORT_PROVENANCE,
  type PortfolioRow,
  toCsv,
  toGeoJson,
} from "../lib/exporters";
import { TIER_LABELS } from "../lib/vocabulary";

const rows: PortfolioRow[] = [
  {
    h3_index: "862830827ffffff",
    latitude: 47.6062,
    longitude: -122.3321,
    rank: 1,
    demand_bev: 1234.5678,
    equity_population: 210.25,
    population: 8400,
    uncertainty_score: 0.1234,
    confidence_tier: "A",
    dominant_evidence_grain: "native_tract",
    sub_state_anchored_share: 1,
    existing_dcfc_ports: 4,
    km_to_nearest_dcfc_site: 2.5,
  },
  {
    h3_index: "8628308affffff0",
    latitude: 29.7604,
    longitude: -95.3698,
    rank: 2,
    demand_bev: 900,
    equity_population: 88,
    population: 5100,
    uncertainty_score: 0.42,
    confidence_tier: "C",
    dominant_evidence_grain: "state_total_only",
    sub_state_anchored_share: 0,
    existing_dcfc_ports: 0,
    km_to_nearest_dcfc_site: 41.2,
  },
];

/** A deliberately independent CSV reader, so the test does not trust the writer's rules. */
function parseCsv(text: string): { comments: string[]; rows: Record<string, string>[] } {
  const lines = text.split("\n").filter((line) => line.length > 0);
  const comments = lines.filter((line) => line.startsWith("#"));
  const data = lines.filter((line) => !line.startsWith("#"));
  const header = splitCsvLine(data[0] ?? "");
  return {
    comments,
    rows: data.slice(1).map((line) => {
      const cells = splitCsvLine(line);
      return Object.fromEntries(header.map((name, i) => [name, cells[i] ?? ""]));
    }),
  };
}

function splitCsvLine(line: string): string[] {
  const cells: string[] = [];
  let current = "";
  let quoted = false;
  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];
    if (quoted) {
      if (char === '"' && line[i + 1] === '"') {
        current += '"';
        i += 1;
      } else if (char === '"') {
        quoted = false;
      } else {
        current += char;
      }
    } else if (char === '"') {
      quoted = true;
    } else if (char === ",") {
      cells.push(current);
      current = "";
    } else {
      current += char;
    }
  }
  cells.push(current);
  return cells;
}

describe("CSV export", () => {
  it("parses back to the rows that went in", () => {
    const parsed = parseCsv(toCsv(rows));
    expect(parsed.rows).toHaveLength(2);
    expect(parsed.rows[0]?.h3_index).toBe("862830827ffffff");
    expect(Number(parsed.rows[0]?.demand_bev)).toBeCloseTo(1234.5678, 4);
    expect(Number(parsed.rows[1]?.latitude)).toBeCloseTo(29.7604, 4);
  });

  it("carries the confidence tier on every row", () => {
    const parsed = parseCsv(toCsv(rows));
    for (const row of parsed.rows) {
      expect(row.confidence_tier).toMatch(/^[ABC]$/);
      expect(row.dominant_evidence_grain).toBeTruthy();
    }
  });

  it("carries the provenance, so a file separated from the page still says what it is", () => {
    const parsed = parseCsv(toCsv(rows));
    expect(parsed.comments.length).toBe(EXPORT_PROVENANCE.length);
    const text = parsed.comments.join(" ");
    expect(text).toMatch(/not a claim of optimality/i);
    expect(text).toMatch(/No approximation bound/i);
    expect(text).toMatch(/sub-state anchored, NOT observed/i);
  });

  it("quotes a value containing a comma rather than corrupting the row", () => {
    const awkward: PortfolioRow[] = [
      { ...rows[0]!, dominant_evidence_grain: 'county, allocated "down"' },
    ];
    const parsed = parseCsv(toCsv(awkward));
    expect(parsed.rows).toHaveLength(1);
    expect(parsed.rows[0]?.dominant_evidence_grain).toBe('county, allocated "down"');
  });

  it("survives a round trip through JSON.parse of its own header count", () => {
    const parsed = parseCsv(toCsv(rows));
    const header = Object.keys(parsed.rows[0] ?? {});
    expect(header).toContain("uncertainty_score");
    expect(header).toContain("sub_state_anchored_share");
  });
});

describe("GeoJSON export", () => {
  it("parses as JSON and is a FeatureCollection", () => {
    const parsed = JSON.parse(JSON.stringify(toGeoJson(rows)));
    expect(parsed.type).toBe("FeatureCollection");
    expect(parsed.features).toHaveLength(2);
  });

  it("orders coordinates longitude-first, as the format requires", () => {
    const parsed = toGeoJson(rows);
    // Seattle: longitude is about -122, latitude about 47. Reversed, the point would
    // land in the Indian Ocean and the file would still parse.
    expect(parsed.features[0]?.geometry.coordinates[0]).toBeCloseTo(-122.3321, 4);
    expect(parsed.features[0]?.geometry.coordinates[1]).toBeCloseTo(47.6062, 4);
  });

  it("carries the confidence tier and its label on every feature", () => {
    for (const feature of toGeoJson(rows).features) {
      const tier = feature.properties.confidence_tier as keyof typeof TIER_LABELS;
      expect(TIER_LABELS[tier]).toBeTruthy();
      expect(feature.properties.confidence_tier_label).toBe(TIER_LABELS[tier]);
    }
  });

  it("never labels tier A 'observed'", () => {
    const text = JSON.stringify(toGeoJson(rows));
    expect(text).toContain("sub-state anchored");
    expect(text).not.toMatch(/"observed"/);
  });

  it("carries the provenance in the collection properties", () => {
    const parsed = toGeoJson(rows);
    expect(parsed.properties.provenance).toEqual([...EXPORT_PROVENANCE]);
  });
});
