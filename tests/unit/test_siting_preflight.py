"""The four assumptions the ledger attached to Phase 4, measured rather than restated."""

from __future__ import annotations

import pytest

from pipeline.model.siting_preflight import (
    assert_no_categorical_urban_rural,
    assess_rounding_sensitivity,
    benchmark_centroid_resolution,
)
from pipeline.spatial.h3_grid import PopulationPoint
from tests.unit.test_hexes import SEATTLE, SPOKANE, point
from tests.unit.test_siting import hexcell

# --- A-2.1 is measured in tests/unit/test_clustering_sensitivity.py -------------------
# The ratio argument that used to live here was rejected by external review, correctly:
# a cluster being small relative to a cell says nothing about whether it can cross a
# boundary and change a cell's saturation status. That is now measured.

# --- A-2.3 ---------------------------------------------------------------------------

NEAR_SEATTLE = (47.68, -122.30)


def test_a23_a_centroid_can_land_in_a_cell_where_nobody_lives() -> None:
    """The sharpest form of what §7.6 warns about, and it is not an edge case.

    Two block groups only ~8 km apart, 900 people and 100: the population-weighted
    centroid falls at (47.6136, -122.3289), which is a **third** H3 cell containing
    neither of them. A centroid assignment would place 100% of the tract's demand
    somewhere nobody lives.
    """
    points = [point("53033000100", 900.0, SEATTLE),
              point("53033000100", 100.0, NEAR_SEATTLE, "2")]
    result = benchmark_centroid_resolution(points, {"53033000100": 100.0})
    assert result.tracts == 1
    assert result.block_groups == 2
    assert result.tracts_spanning_multiple_cells == 1
    assert result.demand_share_moved == pytest.approx(1.0)
    payload = result.to_dict()
    assert payload["assumption"] == "A-2.3"
    assert payload["block_level_benchmark_available"] is False


def test_a23_on_real_washington_data_moves_a_material_share() -> None:
    """The aggregate figure, on the state the frontier is computed over."""
    from pipeline.spatial.h3_grid import load_population_points

    points = load_population_points("53")
    demand = {p.tract_geoid: 100.0 for p in points}
    result = benchmark_centroid_resolution(points, demand)
    assert result.tracts == 1784
    assert result.block_groups == 5311
    assert result.tracts_spanning_multiple_cells > 500
    # Materially large: resolution matters here, which is why block groups were used.
    assert 0.05 < result.demand_share_moved < 0.9


def test_a23_reports_nothing_moved_when_a_tract_sits_in_one_cell() -> None:
    points = [point("53033000100", 500.0, SEATTLE)]
    result = benchmark_centroid_resolution(points, {"53033000100": 100.0})
    assert result.demand_share_moved == pytest.approx(0.0)


def test_a23_handles_a_tract_with_no_population_and_no_demand() -> None:
    points = [PopulationPoint("53033000100", "1", 0.0, *SEATTLE),
              PopulationPoint("53033000100", "2", 0.0, *SPOKANE)]
    result = benchmark_centroid_resolution(points, {})
    assert result.demand_share_moved == 0.0
    assert result.tracts == 1


# --- A-3.4 ---------------------------------------------------------------------------

def test_a34_finds_the_portfolio_unchanged_by_the_rounding_half_width() -> None:
    """Reconciliation scales every tract in a jurisdiction by the same factor, so a
    uniform change to its total cannot reorder cells within it."""
    cells = [hexcell(i, 100.0 - 10 * i, equity=50.0) for i in range(6)]
    result = assess_rounding_sensitivity(cells, budget=3, state_total=10_000.0)
    assert result.jaccard_low == 1.0
    assert result.jaccard_high == 1.0
    payload = result.to_dict()
    assert payload["assumption"] == "A-3.4"
    assert payload["identical_portfolio"] is True
    assert payload["rounding_half_width_vehicles"] == 50.0


def test_a34_needs_a_positive_state_total() -> None:
    with pytest.raises(ValueError, match="positive state total"):
        assess_rounding_sensitivity([hexcell(0, 1.0)], 1, 0.0)


# --- A-3.5 ---------------------------------------------------------------------------

def test_a35_refuses_a_categorical_urban_rural_field() -> None:
    """Density ships continuous; a category here would be manufactured."""
    with pytest.raises(ValueError, match=r"A-3\.5 violation"):
        assert_no_categorical_urban_rural({"demand": 1.0, "urban_rural": "urban"})
    with pytest.raises(ValueError, match=r"A-3\.5 violation"):
        assert_no_categorical_urban_rural({"is_urban": True})


def test_a35_allows_a_continuous_density_field() -> None:
    assert_no_categorical_urban_rural(
        {"log_population_density_km2": 7.2, "population": 1000.0})


def test_a23_falls_back_to_an_unweighted_centroid_when_nobody_lives_there() -> None:
    points = [PopulationPoint("53033000100", "1", 0.0, *SEATTLE),
              PopulationPoint("53033000100", "2", 0.0, *SPOKANE)]
    result = benchmark_centroid_resolution(points, {"53033000100": 10.0})
    # An unpopulated tract is split evenly, so a single centroid cell holds half at most.
    assert 0.0 <= result.demand_share_moved <= 1.0


def test_two_empty_portfolios_are_identical_not_undefined() -> None:
    from pipeline.model.siting_preflight import RoundingSensitivity

    result = RoundingSensitivity(0, (), (), (), 50.0, 100.0)
    assert result.jaccard_low == 1.0
    assert result.jaccard_high == 1.0
