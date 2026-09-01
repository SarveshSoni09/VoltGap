/**
 * The Studio's candidate construction and its performance budget, on real state data.
 *
 * Texas is the largest of the six frontier states, so it is the one the §11.3 2-second
 * re-solve budget has to survive. The fixture is the real published artifact, not a
 * synthetic set sized to make the number look good.
 */

import { describe, expect, it } from "vitest";

import texas from "./fixtures/texas_cells.json";
import type { HexRow } from "../lib/data/hexes";
import { buildCandidates } from "../lib/optimizer/candidates";
import { greedySelect } from "../lib/optimizer/greedy";

const rows = texas as unknown as HexRow[];

describe("candidate construction follows Phase 4's rules", () => {
  it("uses the real published Texas surface", () => {
    expect(rows.length).toBe(3532);
  });

  it("applies the road filter the pipeline precomputed", () => {
    const set = buildCandidates(rows);
    expect(set.excluded.beyond_primary_secondary_road_network).toBeGreaterThan(0);
    for (const candidate of set.candidates) {
      const row = rows.find((r) => r.h3_index === candidate.h3_index);
      expect(row?.passes_road_filter).toBe(true);
    }
  });

  it("excludes uninhabited cells before anything else, first match wins", () => {
    const set = buildCandidates(rows);
    const total =
      set.candidates.length +
      Object.values(set.excluded).reduce((a, b) => a + b, 0);
    expect(total).toBe(rows.length);
  });

  it("excludes saturated cells at the Phase 4 threshold", () => {
    const set = buildCandidates(rows);
    for (const candidate of set.candidates) {
      if (candidate.demand > 0) {
        expect((candidate.existing_dcfc_ports * 1000) / candidate.demand).toBeLessThan(2);
      }
    }
  });

  it("has no substation filter, because no national dataset exists", () => {
    const set = buildCandidates(rows);
    expect(Object.keys(set.excluded)).not.toContain("beyond_substation");
    expect(Object.keys(set.excluded).sort()).toEqual([
      "already_saturated",
      "beyond_primary_secondary_road_network",
      "uninhabited",
    ]);
  });

  it("builds coverage only over cells that survived filtering", () => {
    const set = buildCandidates(rows);
    const present = new Set(set.candidates.map((c) => c.h3_index));
    for (const [, covered] of set.coverage) {
      for (const cell of covered) expect(present.has(cell)).toBe(true);
    }
  });
});

describe("performance budget (§11.3: state-level re-solve <= 2 s)", () => {
  it("solves the largest frontier state well inside the budget", () => {
    const set = buildCandidates(rows);
    const started = performance.now();
    const result = greedySelect(set.candidates, set.coverage, 50, {
      demand: 0.6,
      equity: 0.4,
    });
    const elapsed = performance.now() - started;
    expect(result.selected.length).toBeGreaterThan(0);
    expect(elapsed).toBeLessThan(2000);
  });

  it("stays inside the budget across the whole budget slider range", () => {
    const set = buildCandidates(rows);
    let worst = 0;
    for (const budget of [1, 10, 25, 50, 100]) {
      const started = performance.now();
      greedySelect(set.candidates, set.coverage, budget, { demand: 0.6, equity: 0.4 });
      worst = Math.max(worst, performance.now() - started);
    }
    expect(worst).toBeLessThan(2000);
  });
});

describe("every selected cell carries its confidence", () => {
  it("never yields a candidate without an evidence grain and uncertainty", () => {
    const set = buildCandidates(rows);
    for (const candidate of set.candidates) {
      expect(candidate.dominant_evidence_grain).toBeTruthy();
      expect(Number.isFinite(candidate.uncertainty_score)).toBe(true);
      expect(Number.isFinite(candidate.sub_state_anchored_share)).toBe(true);
    }
  });
});
