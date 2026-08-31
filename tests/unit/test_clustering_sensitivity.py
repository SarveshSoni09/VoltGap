"""A-2.1: whether station clustering changes candidate construction.

The assumption was previously argued from cell geometry — a DBSCAN cluster spans at most
~500 m against a ~3,834 m H3 edge — which external review rejected, correctly. A ratio
establishes that clusters are small relative to cells; it establishes nothing about
whether a cluster straddling a boundary flips a saturation classification. These tests
exercise the measurement that replaced the argument.
"""

from __future__ import annotations

import pytest

from pipeline.model.clustering_sensitivity import (
    CONDITIONS,
    ConditionResult,
    compare_conditions,
)
from pipeline.model.hexes import HexSupply
from tests.unit.test_siting import hexcell, roads_covering

BASELINE = CONDITIONS[0][0]


def test_the_shipped_path_is_the_baseline_and_the_alternatives_bound_it() -> None:
    assert CONDITIONS[0] == ("shipped_no_clustering", None)
    assert [name for name, _ in CONDITIONS] == [
        "shipped_no_clustering", "dbscan_eps_50m", "dbscan_eps_200m"]
    assert [eps for _, eps in CONDITIONS] == [None, 50.0, 200.0]


def test_identical_supply_under_every_condition_is_measured_as_no_effect() -> None:
    cells = [hexcell(i, demand=100.0 * (i + 1), equity=10.0 * (i + 1))
             for i in range(6)]
    supply = {cells[0].h3_index: HexSupply(station_count=1, dcfc_ports=2.0)}
    results = compare_conditions(
        cells, {name: supply for name, _ in CONDITIONS}, roads_covering(cells),
        saturation_ports_per_1k_demand=10.0)
    assert len(results) == 3
    for result in results:
        assert result.candidate_jaccard == 1.0
        assert result.saturation_changes == 0
        assert result.demand_delta == 0.0
        assert result.equity_delta == 0.0
        assert not result.material


def test_clustering_that_moves_ports_across_a_boundary_is_reported_as_material() -> None:
    """The whole point: a saturation flip must be counted, not argued away."""
    cells = [hexcell(i, demand=100.0, equity=10.0) for i in range(6)]
    shipped = {cells[0].h3_index: HexSupply(station_count=1, dcfc_ports=50.0)}
    clustered = {cells[1].h3_index: HexSupply(station_count=1, dcfc_ports=50.0)}
    results = compare_conditions(
        cells,
        {BASELINE: shipped, "dbscan_eps_50m": clustered, "dbscan_eps_200m": clustered},
        roads_covering(cells), saturation_ports_per_1k_demand=10.0)
    by_name = {r.condition: r for r in results}
    assert not by_name[BASELINE].material
    moved = by_name["dbscan_eps_50m"]
    assert moved.saturation_changes == 2
    assert moved.candidate_jaccard < 1.0
    assert moved.material


def test_a_condition_that_was_not_measured_is_absent_rather_than_assumed_equal() -> None:
    cells = [hexcell(i, demand=100.0) for i in range(6)]
    results = compare_conditions(
        cells, {BASELINE: {}}, roads_covering(cells),
        saturation_ports_per_1k_demand=10.0)
    assert [r.condition for r in results] == [BASELINE]


def test_the_baseline_must_be_supplied_because_deltas_are_measured_against_it() -> None:
    cells = [hexcell(0, demand=100.0)]
    with pytest.raises(ValueError, match="baseline condition"):
        compare_conditions(cells, {"dbscan_eps_50m": {}}, roads_covering(cells), 10.0)


def test_comparing_portfolios_needs_at_least_one_budget() -> None:
    cells = [hexcell(0, demand=100.0)]
    with pytest.raises(ValueError, match="at least one budget"):
        compare_conditions(cells, {BASELINE: {}}, roads_covering(cells), 10.0,
                           budgets=())


def test_a_single_budget_is_enough_and_names_the_objective_budget() -> None:
    cells = [hexcell(i, demand=100.0 * (i + 1)) for i in range(6)]
    results = compare_conditions(
        cells, {BASELINE: {}}, roads_covering(cells), 10.0, budgets=(3,))
    assert list(results[0].portfolio_overlap) == [3]
    assert results[0].portfolio_overlap[3] == 1.0


def test_a_cell_with_no_demand_is_never_called_saturated() -> None:
    """Dividing ports by zero demand is undefined, not infinite saturation."""
    cells = [hexcell(0, demand=0.0, population=500.0)]
    supply = {cells[0].h3_index: HexSupply(station_count=1, dcfc_ports=99.0)}
    results = compare_conditions(
        cells, {BASELINE: supply}, roads_covering(cells), 10.0, budgets=(1,))
    assert results[0].saturation_changes == 0
    assert results[0].candidates == 1


def test_a_state_with_no_candidates_at_all_raises_rather_than_scoring_zero() -> None:
    """An empty candidate set is a broken input, not a sensitivity result of 0."""
    from pipeline.model.siting import SitingError

    cells = [hexcell(0, demand=100.0, population=0.0)]
    with pytest.raises(SitingError, match="no candidates"):
        compare_conditions(cells, {BASELINE: {}}, roads_covering(cells), 10.0,
                           budgets=(1,))


def test_the_published_record_carries_every_measurement_and_the_verdict() -> None:
    result = ConditionResult(
        condition="dbscan_eps_200m", eps_m=200.0, candidates=1425,
        candidate_jaccard=0.999173, saturation_changes=2,
        portfolio_overlap={5: 1.0, 20: 1.0}, demand_delta=0.0, equity_delta=0.0)
    payload = result.to_dict()
    assert payload["dbscan_eps_m"] == 200.0
    assert payload["cells_whose_saturation_classification_changes"] == 2
    assert payload["candidate_set_jaccard"] == 0.999173
    assert payload["portfolio_overlap_by_budget"] == {"5": 1.0, "20": 1.0}
    assert payload["material"] is True


@pytest.mark.parametrize(
    ("overlap", "demand", "equity", "expected"),
    [({5: 1.0}, 0.0, 0.0, False), ({5: 0.5}, 0.0, 0.0, True),
     ({5: 1.0}, 1.0, 0.0, True), ({5: 1.0}, 0.0, 1.0, True)],
)
def test_materiality_triggers_on_any_measured_difference(
    overlap: dict[int, float], demand: float, equity: float, expected: bool
) -> None:
    result = ConditionResult(
        condition="c", eps_m=50.0, candidates=1, candidate_jaccard=1.0,
        saturation_changes=0, portfolio_overlap=overlap,
        demand_delta=demand, equity_delta=equity)
    assert result.material is expected
