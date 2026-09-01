"""Cross-objective robustness: scoring a portfolio on objectives it never optimised for.

§10.3. "The optimiser wins on its own objective" is circular and is not a finding. What
is informative is either cross-objective robustness or an exposed tradeoff, and both are
results. Several tests here exist to keep a tradeoff from being smoothed away.
"""

from __future__ import annotations

import pytest

from pipeline.model.hexes import HexCell
from pipeline.model.siting import greedy_select
from pipeline.validation.robustness import (
    BASELINE_NAMES,
    OBJECTIVE_NAMES,
    OBJECTIVES,
    PortfolioScore,
    RobustnessResult,
    baseline_portfolios,
    evaluate,
    score_portfolio,
)
from tests.unit.test_siting import candidates_from, hexcell


def cells(n: int = 6) -> list[HexCell]:
    return [hexcell(i, demand=100.0 * (i + 1), equity=10.0 * (n - i),
                    population=1000.0 * (i + 1)) for i in range(n)]


def test_the_six_objectives_are_the_ones_the_specification_names() -> None:
    assert OBJECTIVE_NAMES == (
        "population_served", "demand_covered", "equity_coverage",
        "accessibility_improvement", "estimated_utilisation", "cost_efficiency")
    assert {o.name for o in OBJECTIVES} == set(OBJECTIVE_NAMES)


def test_the_four_baselines_are_the_ones_the_specification_names() -> None:
    assert BASELINE_NAMES == (
        "population_weighted", "demand_only", "existing_network_proximity", "random")


def test_every_objective_ships_its_definition_not_just_its_name() -> None:
    """A reader must be able to check what was measured rather than trust a label."""
    for objective in OBJECTIVES:
        assert objective.definition and objective.units
    equity = next(o for o in OBJECTIVES if o.name == "equity_coverage")
    assert "NOT a composite index" in equity.definition
    utilisation = next(o for o in OBJECTIVES if o.name == "estimated_utilisation")
    assert "NOT a queueing result" in utilisation.definition


def test_a_portfolio_is_scored_on_all_six_objectives() -> None:
    candidates = candidates_from(cells())
    scores = score_portfolio([c.h3_index for c in candidates.candidates[:2]], candidates)
    assert set(scores) == set(OBJECTIVE_NAMES)


def test_an_empty_portfolio_scores_zero_rather_than_dividing_by_zero() -> None:
    candidates = candidates_from(cells())
    scores = score_portfolio([], candidates)
    assert scores["estimated_utilisation"] == 0.0
    assert scores["cost_efficiency"] == 0.0
    assert scores["demand_covered"] == 0.0


def test_accessibility_improvement_counts_only_cells_with_no_existing_dcfc() -> None:
    """The part of coverage that changes access rather than reinforcing it."""
    served = [hexcell(i, demand=100.0 * (i + 1), population=1000.0,
                      dcfc=5.0 if i == 0 else 0.0) for i in range(6)]
    candidates = candidates_from(served, saturation=1e9)
    everything = [c.h3_index for c in candidates.candidates]
    scores = score_portfolio(everything, candidates)
    assert scores["accessibility_improvement"] < scores["demand_covered"]


def test_the_four_baselines_each_select_up_to_the_budget() -> None:
    candidates = candidates_from(cells())
    portfolios = baseline_portfolios(candidates, budget=3, seed=1)
    assert set(portfolios) == set(BASELINE_NAMES)
    for name, selected in portfolios.items():
        assert len(selected) == 3, name


def test_the_random_baseline_is_seeded_so_it_reproduces() -> None:
    candidates = candidates_from(cells())
    assert (baseline_portfolios(candidates, 3, 7)["random"]
            == baseline_portfolios(candidates, 3, 7)["random"])


def test_the_demand_baseline_takes_the_highest_demand_cells() -> None:
    candidates = candidates_from(cells())
    chosen = baseline_portfolios(candidates, 2, 1)["demand_only"]
    by_index = {c.h3_index: c for c in candidates.candidates}
    best = sorted((c.demand for c in candidates.candidates), reverse=True)[:2]
    assert sorted((by_index[c].demand for c in chosen), reverse=True) == best


def test_evaluating_scores_the_optimised_portfolios_and_all_four_baselines() -> None:
    candidates = candidates_from(cells())
    greedy = greedy_select(candidates, 3).selected
    result = evaluate("fixture", candidates, 3, {"greedy_demand": greedy}, seed=1)
    names = {p.name for p in result.portfolios}
    assert "greedy_demand" in names
    assert {f"baseline_{b}" for b in BASELINE_NAMES} <= names
    for portfolio in result.portfolios:
        assert set(portfolio.scores) == set(OBJECTIVE_NAMES)


def result_with(**scores: dict[str, float]) -> RobustnessResult:
    return RobustnessResult(
        label="f", budget=3,
        portfolios=tuple(
            PortfolioScore(name=name, optimised_for=name, sites=3, scores=values)
            for name, values in scores.items()))


def base(**overrides: float) -> dict[str, float]:
    return {**{o: 100.0 for o in OBJECTIVE_NAMES}, **overrides}


def test_a_tradeoff_is_reported_rather_than_hidden() -> None:
    """§10.3: a portfolio strong on one measure and weak on another is a RESULT."""
    result = result_with(
        demand_first=base(equity_coverage=10.0),
        equity_first=base(demand_covered=10.0))
    assert result.tradeoffs("demand_first") == ["equity_coverage"]
    assert result.tradeoffs("equity_first") == ["demand_covered"]
    payload = result.to_dict()
    tradeoffs = payload["tradeoffs_where_below_95_percent_of_best"]
    assert isinstance(tradeoffs, dict)
    assert tradeoffs["demand_first"] == ["equity_coverage"]


def test_a_genuinely_robust_portfolio_reports_no_tradeoffs() -> None:
    result = result_with(a=base(), b=base(demand_covered=50.0))
    assert result.tradeoffs("a") == []


def test_relative_scoring_is_against_the_best_portfolio_on_that_objective() -> None:
    result = result_with(a=base(demand_covered=50.0), b=base(demand_covered=100.0))
    assert result.relative("a", "demand_covered") == pytest.approx(0.5)
    assert result.relative("b", "demand_covered") == pytest.approx(1.0)
    assert result.best_on("demand_covered") == "b"


def test_an_objective_nobody_scores_on_does_not_divide_by_zero() -> None:
    result = result_with(a=base(cost_efficiency=0.0), b=base(cost_efficiency=0.0))
    assert result.relative("a", "cost_efficiency") == 1.0


def test_the_published_record_refuses_the_optimality_reading() -> None:
    payload = result_with(a=base()).to_dict()
    interpretation = str(payload["interpretation"])
    assert "NOT proof of siting correctness" in interpretation
    assert "circular" in interpretation
    assert "objective_definitions" in payload
