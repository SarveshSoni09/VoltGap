"""The national H3 grid and population-weighted tract-to-cell allocation."""

from __future__ import annotations

import pytest

from pipeline.spatial.h3_grid import (
    RESOLUTION_METRO,
    RESOLUTION_NATIONAL,
    GridError,
    PopulationPoint,
    allocate_to_cells,
    block_group_source,
    cell_area_km2,
    cell_centroid,
    cells_for_points,
    conservation_error,
    load_population_points,
    tract_cell_weights,
)

SEATTLE = (47.6062, -122.3321)
SPOKANE = (47.6588, -117.4260)


def point(tract: str, population: float, latlon: tuple[float, float],
          block_group: str = "1") -> PopulationPoint:
    return PopulationPoint(tract, block_group, population, latlon[0], latlon[1])


def test_the_national_unit_is_resolution_six() -> None:
    """CLAUDE.md §2 fixes it; resolution 8 is the metro unit."""
    assert RESOLUTION_NATIONAL == 6
    assert RESOLUTION_METRO == 8


def test_a_res_six_cell_is_about_thirty_six_square_kilometres() -> None:
    cell = cells_for_points([SEATTLE[0]], [SEATTLE[1]])[0]
    assert 20.0 < cell_area_km2(cell) < 60.0
    latitude, longitude = cell_centroid(cell)
    assert abs(latitude - SEATTLE[0]) < 0.2
    assert abs(longitude - SEATTLE[1]) < 0.2


def test_points_far_apart_land_in_different_cells() -> None:
    cells = cells_for_points([SEATTLE[0], SPOKANE[0]], [SEATTLE[1], SPOKANE[1]])
    assert cells[0] != cells[1]


def test_mismatched_coordinate_sequences_are_refused() -> None:
    with pytest.raises(GridError, match="same length"):
        cells_for_points([1.0, 2.0], [1.0])


def test_the_block_group_source_id_matches_what_phase_2_cached() -> None:
    assert block_group_source("53").source_id == "cenpop_bg_53"


# --- weighting -----------------------------------------------------------------------

def test_a_tract_is_split_across_cells_by_population_not_by_area() -> None:
    """§7.6: area weighting assumes uniform population, which is badly wrong in large
    rural tracts."""
    weights = tract_cell_weights([
        point("53033000100", 900.0, SEATTLE),
        point("53033000100", 100.0, SPOKANE, "2"),
    ])
    entry = weights["53033000100"]
    entry.assert_normalised()
    assert len(entry.weights) == 2
    assert max(entry.weights.values()) == pytest.approx(0.9)
    assert min(entry.weights.values()) == pytest.approx(0.1)
    assert entry.population == 1000.0


def test_block_groups_in_the_same_cell_are_summed() -> None:
    weights = tract_cell_weights([
        point("53033000100", 300.0, SEATTLE),
        point("53033000100", 700.0, SEATTLE, "2"),
    ])
    assert list(weights["53033000100"].weights.values()) == [pytest.approx(1.0)]


def test_a_tract_with_no_population_is_split_evenly_and_says_so() -> None:
    """An unpopulated tract carries no demand, but pretending it was population-weighted
    would be a small lie in a provenance field."""
    weights = tract_cell_weights([
        point("53033000100", 0.0, SEATTLE),
        point("53033000100", 0.0, SPOKANE, "2"),
    ])
    entry = weights["53033000100"]
    assert entry.population == 0.0
    assert sorted(entry.weights.values()) == [pytest.approx(0.5), pytest.approx(0.5)]
    entry.assert_normalised()


def test_weights_that_do_not_conserve_mass_are_refused() -> None:
    from pipeline.spatial.h3_grid import TractCellWeights

    with pytest.raises(GridError, match=r"sum to"):
        TractCellWeights("53033000100", {"a": 0.5, "b": 0.2}, 10.0).assert_normalised()


# --- allocation ----------------------------------------------------------------------

def test_allocation_conserves_mass() -> None:
    weights = tract_cell_weights([
        point("53033000100", 900.0, SEATTLE),
        point("53033000100", 100.0, SPOKANE, "2"),
        point("53033000200", 50.0, SEATTLE),
    ])
    values = {"53033000100": 100.0, "53033000200": 40.0}
    cells, unallocated = allocate_to_cells(values, weights)
    assert conservation_error(values, cells, unallocated) == pytest.approx(0.0)
    assert unallocated == {}
    assert sum(cells.values()) == pytest.approx(140.0)


def test_a_tract_with_no_weights_is_returned_not_dropped() -> None:
    """D8: a reportable gap, not something to make disappear."""
    weights = tract_cell_weights([point("53033000100", 10.0, SEATTLE)])
    cells, unallocated = allocate_to_cells(
        {"53033000100": 5.0, "53999999999": 7.0}, weights)
    assert unallocated == {"53999999999": 7.0}
    assert conservation_error({"53033000100": 5.0, "53999999999": 7.0},
                              cells, unallocated) == pytest.approx(0.0)


# --- the real cached data ------------------------------------------------------------

def test_washington_block_groups_load_from_the_cache() -> None:
    points = load_population_points("53")
    assert len(points) == 5311
    assert sum(p.population for p in points) == pytest.approx(7_705_281.0)
    assert all(len(p.tract_geoid) == 11 for p in points)


def test_a_large_share_of_real_tracts_span_more_than_one_cell() -> None:
    """Which is exactly why a tract centroid would have been the wrong assignment."""
    weights = tract_cell_weights(load_population_points("53"))
    spanning = sum(1 for w in weights.values() if len(w.weights) > 1)
    assert spanning / len(weights) > 0.3
    for entry in weights.values():
        entry.assert_normalised()


def test_a_state_with_no_population_points_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pipeline.sources.base import SourceVintage, StagedTable

    def empty(self, fetcher=None):  # type: ignore[no-untyped-def]
        return StagedTable("cenpop_bg_99", ("STATEFP",), [],
                           SourceVintage("cenpop_bg_99", None, ""), 0)

    monkeypatch.setattr("pipeline.sources.base.DelimitedSource.load", empty)
    with pytest.raises(GridError, match="no block-group population points"):
        load_population_points("99")


def test_malformed_rows_are_skipped_without_failing_the_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pipeline.sources.base import SourceVintage, StagedTable

    rows = [
        {"STATEFP": "53", "COUNTYFP": "033", "TRACTCE": "000100", "BLKGRPCE": "1",
         "POPULATION": "100", "LATITUDE": "+47.6", "LONGITUDE": "-122.3"},
        {"STATEFP": "5", "COUNTYFP": "033", "TRACTCE": "000100", "BLKGRPCE": "1",
         "POPULATION": "100", "LATITUDE": "+47.6", "LONGITUDE": "-122.3"},
        {"STATEFP": "53", "COUNTYFP": "033", "TRACTCE": "000200", "BLKGRPCE": "1",
         "POPULATION": "x", "LATITUDE": "+47.6", "LONGITUDE": "-122.3"},
    ]

    def staged(self, fetcher=None):  # type: ignore[no-untyped-def]
        return StagedTable("cenpop_bg_53", tuple(rows[0]), rows,
                           SourceVintage("cenpop_bg_53", None, ""), len(rows))

    monkeypatch.setattr("pipeline.sources.base.DelimitedSource.load", staged)
    points = load_population_points("53")
    assert len(points) == 1
    assert points[0].tract_geoid == "53033000100"


# --- decennial vintages of the population-weight product ------------------------------

def test_an_undeclared_census_vintage_is_refused_rather_than_guessed() -> None:
    """Phase 5 needs 2010 weights for its 2010-geography origins. Constructing a URL for
    a vintage nobody declared would 404 at retrieval time, far from the mistake."""
    from pipeline.spatial.h3_grid import CENPOP_VINTAGES, GridError, block_group_source

    with pytest.raises(GridError, match="no population-weighted centroid product"):
        block_group_source("53", "2000")
    assert sorted(CENPOP_VINTAGES) == ["2010", "2020"]


def test_the_2020_source_id_is_unchanged_so_the_phase_2_cache_still_replays() -> None:
    from pipeline.spatial.h3_grid import block_group_source

    source = block_group_source("53")
    assert source.source_id == "cenpop_bg_53"
    assert source.endpoint.endswith("cenpop2020/blkgrp/CenPop2020_Mean_BG53.txt")
    assert source.params == {}


def test_the_2010_edition_takes_its_own_id_and_carries_the_waf_parameter() -> None:
    """The Census firewall rejects the bare 2010 block-group URL for Oklahoma while
    serving every other state. The parameter defeats it, and it must be a PARAMETER
    rather than an inline query string because httpx replaces a URL's query when params
    are supplied - an inline one would be silently stripped."""
    from pipeline.spatial.h3_grid import block_group_source

    source = block_group_source("40", "2010")
    assert source.source_id == "cenpop_bg_2010_40"
    assert source.endpoint.endswith("cenpop2010/blkgrp/CenPop2010_Mean_BG40.txt")
    assert source.params == {"product": "cenpop2010_blkgrp"}
    assert "?" not in source.endpoint
