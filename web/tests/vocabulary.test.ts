/**
 * The language constraints, checked as behaviour rather than trusted to review.
 *
 * The copy lint catches prohibited phrases anywhere in the repository. These tests check
 * the other half: that the required caveats are actually *present* and correct. A lint
 * cannot tell that a caveat is missing.
 */

import { describe, expect, it } from "vitest";

import { toGeoJson, EXPORT_PROVENANCE, type PortfolioRow } from "../lib/exporters";
import { freshness, type Manifest } from "../lib/data/manifest";
import { CELL_ALPHA, TIER_OPACITY, cellColor } from "../lib/scales";
import {
  CEJST_NOTE,
  DEPLOYMENT_ALIGNMENT_NOTE,
  GRID_PROXIMITY_NOTE,
  INTERACTIVE_SOLVER_NOTE,
  NOT_OPTIMALITY_NOTE,
  TIER_DESCRIPTIONS,
  TIER_LABELS,
  TIER_LABELS_PLAIN,
  VALIDATION_TERMS,
} from "../lib/vocabulary";

describe("tier vocabulary (§11.5, amendment A3)", () => {
  it("labels tier A 'sub-state anchored', never 'observed'", () => {
    expect(TIER_LABELS.A).toBe("sub-state anchored");
    for (const label of Object.values(TIER_LABELS)) {
      expect(label).not.toMatch(/\bobserved\b/i);
    }
  });

  it("explains in the tier A description why it is not 'observed'", () => {
    expect(TIER_DESCRIPTIONS.A).toMatch(/not directly observed|anchored, not directly/i);
    expect(TIER_DESCRIPTIONS.A).toMatch(/ZIP|county/);
  });

  it("no longer hides low-reliability areas by fading them out", () => {
    // Encoding reliability as transparency made an unreliable estimate look like the
    // 78.8% of the country that has no cell at all. Colour now carries the metric and
    // only the metric; reliability is reported separately.
    const opaque = cellColor(0.5);
    const faint = cellColor(0.0);
    expect(opaque[3]).toBe(CELL_ALPHA);
    expect(faint[3]).toBe(CELL_ALPHA);
  });

  it("keeps the tier opacities defined, because the tiers themselves are unchanged", () => {
    expect(TIER_OPACITY.A).toBeGreaterThan(TIER_OPACITY.B);
    expect(TIER_OPACITY.B).toBeGreaterThan(TIER_OPACITY.C);
  });

  it("offers a plain label for each tier without overstating it", () => {
    expect(TIER_LABELS_PLAIN.A).toBe("Higher reliability");
    // "Higher" must not become "observed" in the plain wording either.
    for (const label of Object.values(TIER_LABELS_PLAIN)) {
      expect(label).not.toMatch(/\bobserved\b/i);
      expect(label).not.toMatch(/\bconfirmed\b/i);
    }
  });
});

describe("the three D3 validation terms stay distinct", () => {
  it("names all three with different methods", () => {
    const names = Object.values(VALIDATION_TERMS).map((t) => t.name);
    expect(new Set(names).size).toBe(3);
    const methods = Object.values(VALIDATION_TERMS).map((t) => t.method);
    expect(new Set(methods).size).toBe(3);
  });

  // Naming both terms in one line is the point: the test asserts they stay distinct,
  // which requires mentioning both.
  it("keeps 'historical deployment alignment' apart from model validation", () => {  // copy-lint: allow
    expect(VALIDATION_TERMS.deploymentAlignment.name).toBe(
      "Historical deployment alignment",
    );
    expect(VALIDATION_TERMS.demandModel.name).toBe("Demand model validation");
    expect(VALIDATION_TERMS.deploymentAlignment.evaluates).not.toEqual(
      VALIDATION_TERMS.demandModel.evaluates,
    );
  });
});

describe("required caveats are present, which a lint cannot check", () => {
  it("states no approximation bound for the interactive solver", () => {
    expect(INTERACTIVE_SOLVER_NOTE).toMatch(/approximation/i);
    expect(INTERACTIVE_SOLVER_NOTE).not.toMatch(/guarantee|bound of|at least/i);
  });

  it("denies optimality rather than staying silent about it", () => {
    expect(NOT_OPTIMALITY_NOTE).toMatch(/no ground truth/i);
    expect(NOT_OPTIMALITY_NOTE).toMatch(/not.*optimality|nothing.*validated/i);
  });

  it("says what deployment alignment does NOT establish", () => {
    expect(DEPLOYMENT_ALIGNMENT_NOTE).toMatch(/does not establish/i);
    expect(DEPLOYMENT_ALIGNMENT_NOTE).toMatch(/optimal/i);
    expect(DEPLOYMENT_ALIGNMENT_NOTE).toMatch(/causally|should have followed/i);
  });

  it("marks CEJST archived and dates the revocation", () => {
    expect(CEJST_NOTE).toMatch(/archived/i);
    expect(CEJST_NOTE).toMatch(/20 January 2025/);
    expect(CEJST_NOTE).not.toMatch(/compliance/i);
  });

  it("keeps grid language to proximity, never feasibility", () => {
    expect(GRID_PROXIMITY_NOTE).toMatch(/proxy/i);
    expect(GRID_PROXIMITY_NOTE).not.toMatch(/feasib|ready|available capacity/i);
  });
});

describe("exports carry their caveats out of the application", () => {
  const row: PortfolioRow = {
    h3_index: "8628308", latitude: 47, longitude: -122, rank: 1, demand_bev: 1,
    equity_population: 1, population: 1, uncertainty_score: 0.1, confidence_tier: "A",
    dominant_evidence_grain: "native_tract", sub_state_anchored_share: 1,
    existing_dcfc_ports: 0, km_to_nearest_dcfc_site: 1,
  };

  it("names optimality and the missing bound in the provenance", () => {
    const text = EXPORT_PROVENANCE.join(" ");
    expect(text).toMatch(/not a claim of optimality/i);
    expect(text).toMatch(/no approximation bound/i);
  });

  it("puts the tier on the exported feature, not just in the table", () => {
    const feature = toGeoJson([row]).features[0];
    expect(feature?.properties.confidence_tier).toBe("A");
    expect(feature?.properties.confidence_tier_label).toBe("sub-state anchored");
  });
});

describe("freshness indicator (§13.3)", () => {
  const manifest = (computedAt: string): Manifest => ({
    computed_at: computedAt, stale_after_days: 14, artifacts: {},
    source_vintages: {}, pipeline_phases: {}, notes: {},
  });

  it("reports the build age inside the threshold, not a refresh", () => {
    const state = freshness(manifest("2026-09-01T00:00:00Z"), new Date("2026-09-03T00:00:00Z"));
    expect(state.stale).toBe(false);
    expect(state.message).toMatch(/artifacts built 2 days ago/i);
  });

  it("says so plainly past the threshold, rather than showing a stale number", () => {
    const state = freshness(manifest("2026-07-01T00:00:00Z"), new Date("2026-09-01T00:00:00Z"));
    expect(state.stale).toBe(true);
    expect(state.message).toMatch(/62 days ago/);
    expect(state.message).toMatch(/freshness threshold/i);
  });

  it("never claims a scheduled refresh, because this release has none", () => {
    // The earlier copy said "The scheduled refresh may have stopped" past the threshold,
    // which asserted an automation that does not exist and would have become a false
    // statement on the fourteenth day after publication. Asserted absent at both ends of
    // the threshold so it cannot come back in either branch.
    for (const [built, now] of [
      ["2026-09-01T00:00:00Z", "2026-09-03T00:00:00Z"],
      ["2026-07-01T00:00:00Z", "2026-09-01T00:00:00Z"],
    ] as const) {
      const message = freshness(manifest(built), new Date(now)).message;
      expect(message).not.toMatch(/scheduled refresh/i);
      expect(message).not.toMatch(/refreshed/i);
      // computed_at is when the artifacts were BUILT; the sources are older, and the
      // message must not let a reader conflate the two.
      expect(message).toMatch(/sources carry their own, older vintages/i);
    }
  });

  it("takes the threshold from the manifest, so page and pipeline cannot disagree", () => {
    const strict = { ...manifest("2026-08-25T00:00:00Z"), stale_after_days: 3 };
    expect(freshness(strict, new Date("2026-09-01T00:00:00Z")).stale).toBe(true);
  });
});
