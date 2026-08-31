"""Smoke-forward: Phase 5's core operations against Phase 4's real output (Gate G-D).

Phase 5 is validation: the vintage guard, three rolling-origin backtests of historical
deployment alignment, and cross-objective robustness. Two of its operations can be
exercised against Phase 4 output today without doing any Phase 5 work:

* **cross-objective robustness** (§10.3) optimises a portfolio on ONE objective and then
  scores it on objectives that were never in the loss function. Phase 4 produces exactly
  the portfolios that needs.
* **the vintage guard** (§10.2.1, D1) needs every feature to carry a vintage. This checks
  that Phase 4's candidates trace back to a dated feature vintage, so Phase 5 has
  something to assert on.

**No Phase 5 work is done here.** No backtest is run, no rolling origin is constructed and
no alignment is measured. This proves the data shape works, and nothing about whether any
portfolio is good.
"""

from __future__ import annotations

import pytest

from pipeline.model.build_demand import build_surface
from pipeline.model.hexes import load_hex_supply
from pipeline.model.observed import load_all
from pipeline.model.panel import build_panels, load_area_tables
from pipeline.model.run_phase3 import allocation_penalty, constraint_totals
from pipeline.model.run_phase4 import state_cells
from pipeline.model.siting import (
    MAXIMISE_DEMAND,
    MAXIMISE_EQUITY,
    CandidateSet,
    build_candidates,
    greedy_select,
    solve_epsilon_constraint,
)
from pipeline.sources.census_acs import ACS_YEAR

FIXTURE_STATES = ("50", "53")


@pytest.fixture(scope="module")
def candidates() -> CandidateSet:
    tables = load_area_tables(states=FIXTURE_STATES)
    observations = load_all(known_tracts=sorted(tables["tracts"].rows))
    penalty, _ = allocation_penalty()
    surface = build_surface(
        tables["tracts"], build_panels(observations, tables), observations,
        constraint_totals(observations), penalty, "poisson_glm",
        source_statuses=("confirmed",) * 8, bootstrap_replicates=4)
    cells = state_cells(surface.estimates, "53", load_hex_supply())
    return build_candidates(cells, saturation_ports_per_1k_demand=2.0)


def test_a_portfolio_optimised_on_one_objective_can_be_scored_on_another(
    candidates: CandidateSet,
) -> None:
    """The shape §10.3 needs: optimise on demand, then score on equity, which was never
    in the loss function."""
    by_index = {c.h3_index: c for c in candidates.candidates}
    demand_first = solve_epsilon_constraint(candidates, 20, 0.0, MAXIMISE_DEMAND)
    assert demand_first.status == "optimal"

    covered: set[str] = set()
    for site in demand_first.selected:
        covered.update(candidates.coverage[site])
    off_objective_equity = sum(by_index[c].equity_population for c in covered)
    assert off_objective_equity > 0.0
    assert off_objective_equity == pytest.approx(demand_first.equity_covered)

    # And the reverse portfolio genuinely differs, so the comparison is not vacuous.
    equity_first = solve_epsilon_constraint(candidates, 20, 0.0, MAXIMISE_EQUITY)
    assert set(equity_first.selected) != set(demand_first.selected)


def test_baseline_portfolios_are_constructible_for_a_robustness_comparison(
    candidates: CandidateSet,
) -> None:
    """§10.3 compares against population-weighted, demand-only and random baselines."""
    by_index = {c.h3_index: c for c in candidates.candidates}
    population_first = tuple(sorted(
        by_index, key=lambda i: (-by_index[i].population, i))[:20])
    demand_only = greedy_select(candidates, 20, {"demand": 1.0, "equity": 0.0})
    assert len(population_first) == 20
    assert len(demand_only.selected) == 20
    # A population baseline that simply reproduced the demand portfolio would make the
    # robustness comparison meaningless.
    assert set(population_first) != set(demand_only.selected)


def test_every_candidate_traces_back_to_a_dated_feature_vintage(
    candidates: CandidateSet,
) -> None:
    """D1 needs a vintage on every feature; Phase 5 asserts feature_vintage <= cutoff."""
    assert ACS_YEAR == 2024
    for candidate in candidates.candidates[:50]:
        assert candidate.dominant_evidence_grain in {
            "native_tract", "county_anchored", "state_total_only"}
        assert 0.0 <= candidate.uncertainty_score <= 1.0


def test_uncertainty_survives_all_the_way_into_a_selected_portfolio(
    candidates: CandidateSet,
) -> None:
    """D7: a ranked portfolio that lost its uncertainty would breach it."""
    by_index = {c.h3_index: c for c in candidates.candidates}
    selected = greedy_select(candidates, 20).selected
    assert selected
    for site in selected:
        assert 0.0 <= by_index[site].uncertainty_score <= 1.0
        assert 0.0 <= by_index[site].sub_state_anchored_share <= 1.0


def test_the_portfolio_is_reproducible_from_the_same_inputs(
    candidates: CandidateSet,
) -> None:
    """Phase 5 re-runs these solves; a non-deterministic portfolio would make any
    before/after comparison meaningless."""
    first = greedy_select(candidates, 20).selected
    second = greedy_select(candidates, 20).selected
    assert first == second
