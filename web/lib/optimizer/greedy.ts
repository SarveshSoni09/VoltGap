/**
 * The interactive greedy solver, ported from the accepted Phase 4 implementation.
 *
 * This is a **faithful port**, not a reinterpretation: `pipeline/model/siting.py`'s
 * `greedy_select` is the reference, and `tests/greedy.test.ts` checks this against fixtures
 * whose expected values were produced by that Python function. If the two ever disagree,
 * the Python one is right.
 *
 * The exact algorithm, stated so §7.8's requirement to define it precisely is met by code:
 *
 * 1. start with nothing selected and no cell covered;
 * 2. for each unselected candidate, compute the weighted value of the cells it would
 *    newly cover;
 * 3. take the candidate with the highest marginal gain per unit cost, breaking ties on the
 *    cell index so the result is deterministic;
 * 4. mark its coverage; repeat until the budget is exhausted or nothing adds value.
 *
 * **No approximation bound is claimed, here or in the interface.** With a single
 * objective, uniform costs and no further constraint this would be cardinality-constrained
 * maximum coverage, where the Nemhauser-Wolsey-Fisher guarantee applies. That is not this
 * problem: the surface exposes objective weights and constraint toggles, making it a
 * weighted multi-objective selection under additional constraints, and the guarantee does
 * not carry over (amendment A11).
 */

export interface Candidate {
  readonly h3_index: string;
  readonly demand: number;
  readonly equity_population: number;
  readonly population: number;
  readonly uncertainty_score: number;
  readonly sub_state_anchored_share: number;
  readonly dominant_evidence_grain: string;
  readonly existing_dcfc_ports: number;
  readonly cost: number;
}

export interface Weights {
  readonly demand: number;
  readonly equity: number;
}

export interface GreedyResult {
  readonly selected: readonly string[];
  readonly demandCovered: number;
  readonly equityCovered: number;
  readonly populationCovered: number;
  readonly weights: Weights;
  readonly elapsedMs: number;
}

/**
 * Coverage: which cells each candidate serves. Built once per candidate set and reused
 * across slider moves, because rebuilding it per solve is what would break the 2 s budget.
 */
export type Coverage = ReadonlyMap<string, readonly string[]>;

export function greedySelect(
  candidates: readonly Candidate[],
  coverage: Coverage,
  budget: number,
  weights: Weights,
): GreedyResult {
  const started = performance.now();
  if (candidates.length === 0) {
    throw new Error("no candidates to site among");
  }
  // Sorted once: the Python reference iterates `sorted(by_index)` for deterministic tie
  // breaking, and a differently ordered scan would silently pick a different portfolio.
  const ordered = [...candidates].sort((a, b) =>
    a.h3_index < b.h3_index ? -1 : a.h3_index > b.h3_index ? 1 : 0,
  );
  const byIndex = new Map(ordered.map((c) => [c.h3_index, c]));

  const value = (index: string): number => {
    const candidate = byIndex.get(index);
    if (candidate === undefined) return 0;
    return (
      weights.demand * candidate.demand + weights.equity * candidate.equity_population
    );
  };

  const selected: string[] = [];
  const selectedSet = new Set<string>();
  const covered = new Set<string>();
  let spent = 0;

  while (selected.length < ordered.length) {
    let bestIndex: string | null = null;
    let bestGain = 0;
    for (const candidate of ordered) {
      if (selectedSet.has(candidate.h3_index)) continue;
      if (spent + candidate.cost > budget) continue;
      let gain = 0;
      for (const cell of coverage.get(candidate.h3_index) ?? []) {
        if (!covered.has(cell)) gain += value(cell);
      }
      const perCost = candidate.cost > 0 ? gain / candidate.cost : gain;
      if (perCost > bestGain) {
        bestIndex = candidate.h3_index;
        bestGain = perCost;
      }
    }
    if (bestIndex === null) break;
    selected.push(bestIndex);
    selectedSet.add(bestIndex);
    for (const cell of coverage.get(bestIndex) ?? []) covered.add(cell);
    spent += byIndex.get(bestIndex)?.cost ?? 0;
  }

  let demandCovered = 0;
  let equityCovered = 0;
  let populationCovered = 0;
  for (const cell of covered) {
    const candidate = byIndex.get(cell);
    if (candidate === undefined) continue;
    demandCovered += candidate.demand;
    equityCovered += candidate.equity_population;
    populationCovered += candidate.population;
  }

  return {
    selected,
    demandCovered,
    equityCovered,
    populationCovered,
    weights,
    elapsedMs: performance.now() - started,
  };
}
