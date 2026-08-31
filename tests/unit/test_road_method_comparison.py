"""What changed when nearest-vertex distance was replaced by nearest-point distance.

External review identified the vertex measurement as a correctness defect: a LineString's
nearest vertex is not generally its nearest point, so the measurement overestimates and
can falsely exclude a cell from a hard candidate filter. These tests exercise the
comparison that quantifies the change rather than asserting it was small.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

import pytest

from pipeline.model.hexes import HexCell, HexSupply
from pipeline.model.road_method_comparison import (
    MethodComparison,
    compare_distance_methods,
    vertex_road_distances,
)
from pipeline.spatial.distance import PolylineIndex
from pipeline.spatial.h3_grid import cell_centroid
from pipeline.spatial.road_proximity import RoadDistances, measure_road_distances
from tests.unit.test_siting import hexcell


def road_beside(cells: list[HexCell], offset_deg: float = 0.02,
                span_deg: float = 0.5) -> PolylineIndex:
    """One long straight road `offset_deg` from the first cell's centroid, plus a stub
    vertex on the last cell.

    The stub matters: without it the vertex method excludes *every* cell and there is no
    portfolio to compare against. With it, the vertex method admits exactly the stub cell
    while the corrected method admits everything the long segment passes — which is the
    asymmetry under test.
    """
    latitude, longitude = cell_centroid(cells[0].h3_index)
    return PolylineIndex.from_polylines([
        [(latitude - offset_deg, longitude - span_deg),
         (latitude - offset_deg, longitude + span_deg)],
        [cell_centroid(cells[-1].h3_index)],
    ])


def test_the_superseded_method_is_reproduced_only_to_be_compared_against() -> None:
    """It must still behave as the old method did, or the comparison is meaningless."""
    cells = [hexcell(i, demand=100.0) for i in range(3)]
    roads = road_beside(cells)
    index = [c.h3_index for c in cells]
    vertex = vertex_road_distances(index, roads)
    # The first cell is beside the middle of the long segment: near the road, far from
    # every vertex of it. The superseded method reports the far number.
    assert vertex.distances_km[index[0]] > 35.0
    assert not vertex.within(index[0])
    # The last cell carries the stub vertex, so the old method does admit that one.
    assert vertex.within(index[-1])


def test_measuring_no_cells_returns_nothing_rather_than_failing() -> None:
    roads = PolylineIndex.from_polylines([[(47.0, -122.0), (47.0, -121.0)]])
    assert vertex_road_distances([], roads).distances_km == {}


def test_the_correction_admits_a_cell_the_vertex_method_wrongly_excluded() -> None:
    """The whole point of the correction, measured end to end."""
    cells = [hexcell(i, demand=100.0 * (i + 1)) for i in range(6)]
    result = compare_distance_methods("fixture", cells, road_beside(cells), 2.0,
                                      budgets=(1, 2, 3))
    assert result.candidates_segment > result.candidates_vertex
    assert result.cells_that_change_side_of_the_threshold > 0
    assert result.candidate_jaccard < 1.0
    assert result.material


def test_the_distance_error_is_never_negative() -> None:
    """A vertex IS a point on the segment, so the nearest point can only be closer.
    A negative error would mean the corrected method is worse, which is impossible."""
    cells = [hexcell(i, demand=100.0) for i in range(6)]
    result = compare_distance_methods("fixture", cells, road_beside(cells), 2.0,
                                      budgets=(1, 2, 3))
    assert result.error_mean_km >= 0.0
    assert result.error_median_km >= 0.0
    assert result.error_max_km >= result.error_p99_km >= 0.0


def test_a_road_through_every_centroid_changes_nothing_and_says_so() -> None:
    cells = [hexcell(i, demand=100.0 * (i + 1)) for i in range(6)]
    through = PolylineIndex.from_polylines(
        [[cell_centroid(c.h3_index)] for c in cells])
    result = compare_distance_methods("fixture", cells, through, 2.0, budgets=(1, 2, 3))
    assert result.error_max_km == pytest.approx(0.0, abs=1e-9)
    assert result.cells_that_change_side_of_the_threshold == 0
    assert result.candidate_jaccard == 1.0
    assert result.demand_delta == 0.0
    assert result.equity_delta == 0.0
    assert not result.material


def test_supply_is_carried_through_so_saturation_still_applies() -> None:
    cells = [hexcell(i, demand=100.0) for i in range(6)]
    cells[0] = type(cells[0])(**{**cells[0].__dict__,
                                 "supply": HexSupply(station_count=1, dcfc_ports=99.0)})
    result = compare_distance_methods("fixture", cells, road_beside(cells, 0.001), 2.0,
                                      budgets=(1, 2, 3))
    assert result.candidates_segment < len(cells)


def test_comparing_portfolios_needs_at_least_one_budget() -> None:
    cells = [hexcell(0, demand=100.0)]
    with pytest.raises(ValueError, match="at least one budget"):
        compare_distance_methods("fixture", cells, road_beside(cells), 2.0, budgets=())


def test_the_published_record_names_both_methods_and_the_verdict() -> None:
    result = MethodComparison(
        state="Washington", cells=870, error_mean_km=0.0008, error_median_km=0.0002,
        error_p99_km=0.0121, error_max_km=0.0591, cells_overstated_by_over_100m=0,
        cells_that_change_side_of_the_threshold=0, candidates_vertex=674,
        candidates_segment=674, candidate_jaccard=1.0,
        portfolio_overlap={5: 1.0, 20: 1.0, 50: 1.0},
        demand_delta=0.0, equity_delta=0.0)
    payload = result.to_dict()
    assert payload["candidates_nearest_vertex"] == 674
    assert payload["candidates_nearest_point_on_segment"] == 674
    assert payload["material"] is False
    error = payload["distance_error_km"]
    assert isinstance(error, dict)
    assert error["max"] == 0.0591
    assert "never negative" in str(error["definition"])


def test_materiality_triggers_on_a_changed_portfolio_alone() -> None:
    result = MethodComparison(
        state="s", cells=1, error_mean_km=0.0, error_median_km=0.0, error_p99_km=0.0,
        error_max_km=0.0, cells_overstated_by_over_100m=0,
        cells_that_change_side_of_the_threshold=0, candidates_vertex=1,
        candidates_segment=1, candidate_jaccard=1.0, portfolio_overlap={5: 0.5},
        demand_delta=0.0, equity_delta=0.0)
    assert result.material


def test_two_empty_sets_are_identical_rather_than_a_division_by_zero() -> None:
    """Tested on the helper directly: the public path cannot reach it, because
    `build_candidates` and `greedy_select` both raise before an empty set gets here.
    The guard exists so a future caller does not divide by zero instead."""
    from pipeline.model.road_method_comparison import _jaccard

    assert _jaccard([], []) == 1.0
    assert _jaccard(["a"], []) == 0.0
    assert _jaccard(["a", "b"], ["b", "c"]) == pytest.approx(1 / 3)


def test_a_segment_distance_greater_than_its_vertex_distance_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Impossible by construction — a vertex lies on the segment — so if it ever
    happens the geometry is broken and the comparison must not publish a number."""
    import pipeline.model.road_method_comparison as module

    cells = [hexcell(i, demand=100.0) for i in range(3)]
    roads = road_beside(cells)
    def inflated(index: Sequence[str], geometry: PolylineIndex,
                 threshold_km: float) -> RoadDistances:
        result = measure_road_distances(index, geometry, threshold_km)
        return replace(result, distances_km={
            k: v + 1000.0 for k, v in result.distances_km.items()})

    monkeypatch.setattr(module, "measure_road_distances", inflated)
    with pytest.raises(ValueError, match="impossible"):
        compare_distance_methods("fixture", cells, roads, 2.0, budgets=(1, 2, 3))
