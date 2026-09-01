/**
 * The browser solver must agree with the accepted Phase 4 Python implementation.
 *
 * Expected values in `fixtures/greedy_cases.json` were produced by `greedy_select` in
 * `pipeline/model/siting.py` - the code Phase 4's gate accepted - not written by hand. If
 * these ever disagree, the Python one is right and this port is wrong.
 *
 * The fixtures deliberately include ADJACENT cells whose k-ring-1 coverage overlaps,
 * because overlapping coverage is the only thing that exercises marginal gain. A fixture of
 * isolated cells would pass for a solver that ignored coverage entirely.
 */

import { describe, expect, it } from "vitest";

import cases from "./fixtures/greedy_cases.json";
import { type Candidate, type Coverage, greedySelect } from "../lib/optimizer/greedy";

interface Case {
  name: string;
  budget: number;
  weights: { demand: number; equity: number };
  candidates: Candidate[];
  coverage: Record<string, string[]>;
  expected: { selected: string[]; demand_covered: number; equity_covered: number };
}

const toCoverage = (raw: Record<string, string[]>): Coverage =>
  new Map(Object.entries(raw));

describe("greedy solver, against the accepted Python implementation", () => {
  for (const testCase of cases as Case[]) {
    it(`matches Python on ${testCase.name}`, () => {
      const result = greedySelect(
        testCase.candidates,
        toCoverage(testCase.coverage),
        testCase.budget,
        testCase.weights,
      );
      expect(result.selected).toEqual(testCase.expected.selected);
      expect(result.demandCovered).toBeCloseTo(testCase.expected.demand_covered, 6);
      expect(result.equityCovered).toBeCloseTo(testCase.expected.equity_covered, 6);
    });
  }

  it("exercises overlapping coverage, or it proves nothing", () => {
    const overlapping = (cases as Case[]).some((c) =>
      Object.values(c.coverage).some((cells) => cells.length > 1),
    );
    expect(overlapping).toBe(true);
  });

  it("refuses an empty candidate set rather than returning an empty portfolio", () => {
    expect(() => greedySelect([], new Map(), 5, { demand: 1, equity: 0 })).toThrow(
      /no candidates/,
    );
  });

  it("is deterministic across runs", () => {
    const first = cases[0] as Case;
    const run = () =>
      greedySelect(
        first.candidates,
        toCoverage(first.coverage),
        first.budget,
        first.weights,
      ).selected;
    expect(run()).toEqual(run());
  });

  it("does not depend on the order candidates arrive in", () => {
    const first = cases[0] as Case;
    const reversed = [...first.candidates].reverse();
    const a = greedySelect(
      first.candidates,
      toCoverage(first.coverage),
      first.budget,
      first.weights,
    );
    const b = greedySelect(
      reversed,
      toCoverage(first.coverage),
      first.budget,
      first.weights,
    );
    expect(b.selected).toEqual(a.selected);
  });

  it("never exceeds the budget", () => {
    for (const testCase of cases as Case[]) {
      const result = greedySelect(
        testCase.candidates,
        toCoverage(testCase.coverage),
        testCase.budget,
        testCase.weights,
      );
      const spent = result.selected.reduce((total, index) => {
        const candidate = testCase.candidates.find((c) => c.h3_index === index);
        return total + (candidate?.cost ?? 0);
      }, 0);
      expect(spent).toBeLessThanOrEqual(testCase.budget);
    }
  });
});
