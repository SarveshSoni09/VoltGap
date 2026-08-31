"""Candidate filtering, the epsilon-constraint frontier, and the greedy solver."""

from __future__ import annotations

from typing import cast

import pytest

from pipeline.model.hexes import HexCell, HexSupply
from pipeline.model.siting import (
    MAXIMISE_DEMAND,
    MAXIMISE_EQUITY,
    CandidateSet,
    ExclusionReason,
    GreedyShortfall,
    SitingError,
    SolveStatus,
    build_candidates,
    build_frontier,
    coverage_sets,
    epsilon_levels,
    greedy_select,
    measure_greedy_shortfall,
    solve_epsilon_constraint,
)
from pipeline.model.uncertainty import COMPONENT_NAMES
from pipeline.spatial.distance import PolylineIndex
from pipeline.spatial.h3_grid import cells_for_points
from pipeline.spatial.road_proximity import RoadDistances, measure_road_distances

# Six well-separated points, so each lands in its own res-6 cell with no shared k-ring.
POINTS = [(47.6, -122.3), (40.7, -74.0), (34.0, -118.2), (41.8, -87.6),
          (29.7, -95.3), (25.7, -80.1)]


def cell_at(index: int) -> str:
    return cells_for_points([POINTS[index][0]], [POINTS[index][1]])[0]


def hexcell(index: int, demand: float, equity: float = 0.0,
            population: float = 1000.0, dcfc: float = 0.0) -> HexCell:
    return HexCell(
        h3_index=cell_at(index), resolution=6, latitude=POINTS[index][0],
        longitude=POINTS[index][1], area_km2=36.0, demand_bev=demand,
        population=population, households=population / 2.5, equity_population=equity,
        tracts_contributing=1, largest_tract_share=1.0, uncertainty_score=0.2,
        uncertainty_components=dict.fromkeys(COMPONENT_NAMES, 0.2),
        evidence_grain_share={"native_tract": 1.0}, confidence_tier_share={"A": 1.0},
        value_provenance_share={"modeled_reconciled": 1.0},
        supply=HexSupply(station_count=1 if dcfc else 0, dcfc_ports=dcfc),
    )


def roads_covering(cells: list[HexCell], km: float = 5.0) -> RoadDistances:
    """A road vertex at every cell centroid: the filter passes everything.

    Tests that are about the solver should not silently become tests about the road
    filter, so the road input is explicit and trivially satisfied unless a test says
    otherwise.
    """
    return measure_road_distances(
        [c.h3_index for c in cells],
        PolylineIndex.from_polylines([[(c.latitude, c.longitude)] for c in cells]), km)


def candidates_from(cells: list[HexCell], saturation: float = 2.0,
                    roads: RoadDistances | None = None) -> CandidateSet:
    return build_candidates(cells, saturation,
                            roads if roads is not None else roads_covering(cells))


# --- candidate filtering --------------------------------------------------------------

def test_there_is_no_substation_filter() -> None:
    """§7.9: Phase 0 found no authoritative national substation dataset, so Core siting
    functions without one and no cell is excluded for lacking grid data."""
    payload = candidates_from([hexcell(0, 100.0)]).to_dict()
    assert payload["no_mandatory_substation_filter"] is True
    assert set(ExclusionReason) == {ExclusionReason.UNINHABITED,
                                    ExclusionReason.BEYOND_PRIMARY_SECONDARY_ROADS,
                                    ExclusionReason.ALREADY_SATURATED}


def test_a_cell_beyond_the_road_network_is_excluded_by_name() -> None:
    """CLAUDE.md §7.8's actual filter, restored. Resident population is NOT a substitute
    for road proximity and is no longer presented as one."""
    cells = [hexcell(0, 100.0), hexcell(1, 100.0)]
    # A road only near the first cell.
    roads = measure_road_distances(
        [c.h3_index for c in cells],
        PolylineIndex.from_polylines([[(cells[0].latitude, cells[0].longitude)]]), 5.0)
    result = build_candidates(cells, 2.0, roads)
    assert [c.h3_index for c in result.candidates] == [cell_at(0)]
    assert result.excluded == {"beyond_primary_secondary_road_network": 1}
    road = cast(dict[str, object], result.to_dict()["road_network_filter"])
    assert road["threshold_km"] == 5.0


def test_candidate_construction_without_roads_raises_rather_than_dropping_the_filter(
) -> None:
    """D8: passing every cell through would silently drop the §7.8 constraint."""
    with pytest.raises(SitingError, match="needs road distances"):
        build_candidates([hexcell(0, 100.0)], 2.0)


def test_degraded_mode_admits_cells_but_says_so_loudly() -> None:
    result = build_candidates([hexcell(0, 100.0)], 2.0, allow_missing_roads=True)
    assert len(result.candidates) == 1
    assert result.admitted_without_road_filter == 1
    payload = result.to_dict()
    assert "DEGRADED" in str(payload["road_network_filter"])
    assert payload["cells_admitted_without_road_filter"] == 1


def test_the_road_threshold_sensitivity_curve_ships_with_the_result() -> None:
    """So the threshold is visible as a choice rather than presented as a finding."""
    cells = [hexcell(i, 100.0) for i in range(3)]
    roads = measure_road_distances(
        [c.h3_index for c in cells],
        PolylineIndex.from_polylines([[(cells[0].latitude, cells[0].longitude)]]), 5.0)
    curve = cast(dict[str, int], roads.to_dict([c.h3_index for c in cells])[
        "sensitivity_cells_within_threshold_by_km"])
    assert set(curve) == {"1", "2", "3", "5", "8", "12", "20"}
    assert curve["1"] <= curve["20"]


def test_an_uninhabited_cell_is_excluded_by_name() -> None:
    """Standing in for the road-network filter, which has no dataset (D8)."""
    result = candidates_from([hexcell(0, 100.0), hexcell(1, 5.0, population=0.0)])
    assert len(result.candidates) == 1
    assert result.excluded == {"uninhabited": 1}
    assert "road_network_filter" in result.to_dict()


def test_a_saturated_cell_is_excluded_by_name() -> None:
    result = candidates_from([hexcell(0, 100.0, dcfc=0.0),
                              hexcell(1, 100.0, dcfc=50.0)])
    assert [c.h3_index for c in result.candidates] == [cell_at(0)]
    assert result.excluded == {"already_saturated": 1}


def test_a_zero_demand_cell_is_never_saturated() -> None:
    """Nothing divided by nothing is not "already served"; it is a blank slate."""
    result = candidates_from([hexcell(0, 0.0, dcfc=99.0)])
    assert len(result.candidates) == 1


def test_a_candidate_carries_its_demand_evidence_forward() -> None:
    """D7: uncertainty and provenance must not vanish at the siting layer."""
    candidate = candidates_from([hexcell(0, 100.0, equity=250.0)]).candidates[0]
    assert candidate.uncertainty_score == pytest.approx(0.2)
    assert candidate.sub_state_anchored_share == pytest.approx(1.0)
    assert candidate.dominant_evidence_grain == "native_tract"
    payload = candidate.to_dict()
    assert payload["uncertainty_score"] == pytest.approx(0.2)
    assert payload["cost_units"] == 1.0


def test_coverage_extends_to_the_k_ring_and_stays_inside_the_known_set() -> None:
    cells = [cell_at(0), cell_at(1)]
    coverage = coverage_sets(cells, k=1)
    assert coverage[cells[0]] == (cells[0],)
    neighbours = coverage_sets([cells[0], *__import__("h3").grid_disk(cells[0], 1)], 1)
    assert len(neighbours[cells[0]]) == 7


# --- the exact solve -------------------------------------------------------------------

def test_the_exact_solve_picks_the_highest_demand_within_budget() -> None:
    cells = [hexcell(0, 100.0), hexcell(1, 50.0), hexcell(2, 10.0)]
    point = solve_epsilon_constraint(candidates_from(cells), budget=2, epsilon=0.0)
    assert point.status == SolveStatus.OPTIMAL.value
    assert point.demand_covered == pytest.approx(150.0)
    assert len(point.selected) == 2
    assert point.optimality_gap == 0.0
    assert point.to_dict()["sites_selected"] == 2


def test_the_epsilon_constraint_actually_binds() -> None:
    """The whole point: forcing equity coverage changes which cells are chosen."""
    cells = [hexcell(0, 100.0, equity=0.0), hexcell(1, 10.0, equity=900.0)]
    free = solve_epsilon_constraint(candidates_from(cells), 1, 0.0)
    forced = solve_epsilon_constraint(candidates_from(cells), 1, 500.0)
    assert free.demand_covered == pytest.approx(100.0)
    assert forced.demand_covered == pytest.approx(10.0)
    assert forced.equity_covered == pytest.approx(900.0)


def test_an_unreachable_epsilon_is_reported_infeasible_not_silently_relaxed() -> None:
    cells = [hexcell(0, 100.0, equity=10.0)]
    point = solve_epsilon_constraint(candidates_from(cells), 1, 10_000.0)
    assert point.status == SolveStatus.INFEASIBLE.value
    assert point.selected == ()
    assert point.optimality_gap is None


def test_the_reverse_objective_optimises_the_other_axis() -> None:
    """§7.8 requires reversing the objectives as a check on the frontier."""
    cells = [hexcell(0, 100.0, equity=1.0), hexcell(1, 1.0, equity=100.0)]
    demand_first = solve_epsilon_constraint(
        candidates_from(cells), 1, 0.0, MAXIMISE_DEMAND)
    equity_first = solve_epsilon_constraint(
        candidates_from(cells), 1, 0.0, MAXIMISE_EQUITY)
    assert demand_first.selected != equity_first.selected
    assert demand_first.demand_covered > equity_first.demand_covered
    assert equity_first.equity_covered > demand_first.equity_covered


def test_a_zero_budget_covers_nothing() -> None:
    point = solve_epsilon_constraint(candidates_from([hexcell(0, 100.0)]), 0, 0.0)
    assert point.selected == ()
    assert point.demand_covered == pytest.approx(0.0)


def test_a_negative_budget_and_an_unknown_sense_are_refused() -> None:
    cells = candidates_from([hexcell(0, 100.0)])
    with pytest.raises(SitingError, match="non-negative"):
        solve_epsilon_constraint(cells, -1, 0.0)
    with pytest.raises(SitingError, match="unknown objective sense"):
        solve_epsilon_constraint(cells, 1, 0.0, "invented")


def test_siting_among_no_candidates_is_refused() -> None:
    empty = CandidateSet((), {}, {}, 1)
    with pytest.raises(SitingError, match="no candidates"):
        solve_epsilon_constraint(empty, 1, 0.0)
    with pytest.raises(SitingError, match="no candidates"):
        greedy_select(empty, 1)


# --- the sweep --------------------------------------------------------------------------

def test_the_sweep_spans_the_achievable_range_not_the_theoretical_total() -> None:
    """Sweeping fractions of the TOTAL leaves most points infeasible."""
    cells = [hexcell(i, 100.0 - i, equity=100.0) for i in range(6)]
    candidates = candidates_from(cells)
    levels = epsilon_levels(candidates, budget=2, count=4)
    assert len(levels) == 4
    assert levels[0] == 0.0
    # The ceiling is what two sites can actually reach, not all six cells' equity.
    assert max(levels) < sum(c.equity_population for c in candidates.candidates)


def test_a_sweep_needs_at_least_two_levels() -> None:
    with pytest.raises(SitingError, match="at least two levels"):
        epsilon_levels(candidates_from([hexcell(0, 1.0)]), 1, count=1)


def test_every_frontier_point_is_feasible_across_the_swept_range() -> None:
    cells = [hexcell(i, 100.0 - 10 * i, equity=10.0 * i) for i in range(6)]
    points = build_frontier(candidates_from(cells), budget=3)
    assert len(points) == 8
    assert all(p.status == SolveStatus.OPTIMAL.value for p in points), (
        [p.status for p in points])
    # Demand must not increase as the equity floor rises: that is the tradeoff.
    demands = [p.demand_covered for p in points]
    assert demands == sorted(demands, reverse=True)


# --- greedy ------------------------------------------------------------------------------

def test_greedy_takes_the_largest_marginal_gain_first() -> None:
    cells = [hexcell(0, 10.0), hexcell(1, 100.0), hexcell(2, 50.0)]
    result = greedy_select(candidates_from(cells), 2)
    assert result.selected == (cell_at(1), cell_at(2))
    assert result.demand_covered == pytest.approx(150.0)


def test_greedy_is_deterministic_regardless_of_input_order() -> None:
    """Ties break on the cell index, not on dictionary order."""
    forward = greedy_select(candidates_from(
        [hexcell(i, 100.0) for i in range(4)]), 2)
    backward = greedy_select(candidates_from(
        [hexcell(i, 100.0) for i in reversed(range(4))]), 2)
    assert forward.selected == backward.selected


def test_greedy_never_claims_an_approximation_bound() -> None:
    """§7.8 and amendment A11: no formal bound unless it provably applies."""
    payload = greedy_select(candidates_from([hexcell(0, 10.0)]), 1).to_dict()
    assert payload["approximation_bound_claimed"] is None


def test_greedy_honours_the_weights_it_is_given() -> None:
    cells = [hexcell(0, 100.0, equity=0.0), hexcell(1, 1.0, equity=900.0)]
    demand_only = greedy_select(candidates_from(cells), 1,
                                {"demand": 1.0, "equity": 0.0})
    equity_only = greedy_select(candidates_from(cells), 1,
                                {"demand": 0.0, "equity": 1.0})
    assert demand_only.selected == (cell_at(0),)
    assert equity_only.selected == (cell_at(1),)


def test_greedy_stops_when_nothing_adds_value() -> None:
    cells = [hexcell(0, 0.0), hexcell(1, 0.0)]
    assert greedy_select(candidates_from(cells), 5).selected == ()


def test_greedy_stops_at_the_budget() -> None:
    cells = [hexcell(i, 100.0 - i) for i in range(6)]
    assert len(greedy_select(candidates_from(cells), 3).selected) == 3


# --- greedy shortfall against optimal CBC, kept distinct from CBC's own gap ----------

def test_the_greedy_shortfall_is_measured_against_an_exact_solve() -> None:
    cells = [hexcell(i, 100.0 - 10 * i) for i in range(6)]
    shortfall = measure_greedy_shortfall(candidates_from(cells), 3, "fixture")
    assert shortfall.exact_status == SolveStatus.OPTIMAL.value
    assert shortfall.greedy_objective <= shortfall.exact_objective + 1e-9
    assert 0.0 <= shortfall.shortfall < 1.0
    assert shortfall.to_dict()["label"] == "fixture"


def test_a_shortfall_against_a_zero_objective_is_zero_not_a_division_error() -> None:
    assert GreedyShortfall(1, 0.0, 0.0, "optimal").shortfall == 0.0


def test_the_greedy_shortfall_is_never_called_an_optimality_gap() -> None:
    """Two different quantities. CBC's optimality gap is the distance between its own
    bound and its own incumbent, a property of the SOLVE. The greedy shortfall is how
    much objective a heuristic left on the table. Publishing both as "the gap" would
    invite a reader to think the browser solver carries a solver-style guarantee, and
    §7.8 with amendment A11 is explicit that it carries none."""
    cells = [hexcell(i, 100.0 - 10 * i) for i in range(6)]
    payload = measure_greedy_shortfall(candidates_from(cells), 3, "fixture").to_dict()
    assert "greedy_objective_shortfall_vs_optimal_cbc" in payload
    assert "optimal_cbc_objective" in payload
    assert not any("optimality_gap" in key for key in payload)
    assert "NOT a solver optimality gap" in str(payload["measures"])

    point = build_frontier(candidates_from(cells), 3)[0].to_dict()
    assert "cbc_optimality_gap" in point
    assert "cbc_status" in point
    assert not any(key.startswith("greedy") for key in point)
