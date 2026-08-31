"""The TIGER/Line road source and the road-proximity candidate filter."""

from __future__ import annotations

import struct
from pathlib import Path
from typing import cast

import pytest

from pipeline.sources.tiger_roads import (
    INCLUDED_MTFCC,
    PRIMARY_ROAD,
    SECONDARY_ROAD,
    TIGER_YEAR,
    RoadSourceError,
    parse_wkb_linestring,
    read_road_vertices,
    roads_path,
    roads_url,
)
from pipeline.spatial.road_proximity import (
    DEFAULT_ROAD_PROXIMITY_KM,
    SENSITIVITY_KM,
    measure_road_distances,
)

SEATTLE = (47.6062, -122.3321)
SPOKANE = (47.6588, -117.4260)


def wkb_linestring(points: list[tuple[float, float]], order: int = 1,
                   geometry_type: int = 2, claimed: int | None = None) -> bytes:
    body = struct.pack("<BII", order, geometry_type,
                       len(points) if claimed is None else claimed)
    for latitude, longitude in points:
        body += struct.pack("<dd", longitude, latitude)
    return body


# --- the contract --------------------------------------------------------------------

def test_the_source_names_its_vintage_and_endpoint() -> None:
    assert TIGER_YEAR == 2024
    assert roads_url("53").endswith("tl_2024_53_prisecroads.zip")
    assert "TIGER2024/PRISECROADS" in roads_url("53")
    assert roads_path("53").name == "tl_2024_53_prisecroads.zip"


def test_only_primary_and_secondary_roads_are_included() -> None:
    """Pre-registered. Including local streets would make the filter a near no-op at
    38 km² per cell rather than the siting constraint §7.8 asks for."""
    assert INCLUDED_MTFCC == {PRIMARY_ROAD, SECONDARY_ROAD} == {"S1100", "S1200"}
    assert "S1400" not in INCLUDED_MTFCC


# --- WKB parsing ---------------------------------------------------------------------

def test_a_linestring_yields_every_vertex_as_lat_lon() -> None:
    points = [SEATTLE, SPOKANE]
    assert list(parse_wkb_linestring(wkb_linestring(points))) == points


def test_a_truncated_payload_is_refused() -> None:
    with pytest.raises(RoadSourceError, match="too short"):
        parse_wkb_linestring(b"\x01\x02")


def test_big_endian_is_refused_rather_than_guessed() -> None:
    """Guessing would misplace every road while looking perfectly plausible."""
    with pytest.raises(RoadSourceError, match="not little-endian"):
        parse_wkb_linestring(wkb_linestring([SEATTLE], order=0))


def test_a_non_linestring_geometry_is_refused() -> None:
    with pytest.raises(RoadSourceError, match="not LineString"):
        parse_wkb_linestring(wkb_linestring([SEATTLE], geometry_type=3))


def test_a_point_count_that_does_not_match_the_payload_is_refused() -> None:
    with pytest.raises(RoadSourceError, match="claims 5 points"):
        parse_wkb_linestring(wkb_linestring([SEATTLE], claimed=5))


# --- reading the real cached artifact -------------------------------------------------

def test_washington_roads_read_from_the_cache() -> None:
    roads = read_road_vertices("53")
    assert roads.vintage == "2024"
    assert roads.features == 3006
    assert len(roads) == 376007
    payload = roads.to_dict()
    assert payload["road_classes_included"] == ["S1100", "S1200"]
    assert payload["vertices"] == 376007


def test_restricting_the_classes_excludes_the_rest_by_name() -> None:
    roads = read_road_vertices("53", included=("S1100",))
    assert roads.features < 3006
    assert roads.excluded_classes["S1200"] > 0


def test_a_missing_artifact_raises_rather_than_dropping_the_filter(
    tmp_path: Path,
) -> None:
    """D8: candidate filtering must not proceed by passing every cell through."""
    with pytest.raises(RoadSourceError, match="must not proceed without the road"):
        read_road_vertices("53", cache_root=tmp_path)


def test_a_class_with_no_matching_features_raises(tmp_path: Path) -> None:
    with pytest.raises(RoadSourceError, match="not plausible"):
        read_road_vertices("53", included=("S9999",))


# --- distance -------------------------------------------------------------------------

def test_the_threshold_and_the_sweep_are_the_pre_registered_ones() -> None:
    assert DEFAULT_ROAD_PROXIMITY_KM == 5.0
    assert SENSITIVITY_KM == (1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 20.0)


def test_a_cell_containing_a_road_vertex_is_at_effectively_zero_distance() -> None:
    from pipeline.spatial.h3_grid import cell_centroid, cells_for_points

    cell = cells_for_points([SEATTLE[0]], [SEATTLE[1]])[0]
    latitude, longitude = cell_centroid(cell)
    result = measure_road_distances([cell], [latitude], [longitude])
    assert result.distances_km[cell] == pytest.approx(0.0, abs=1e-6)
    assert result.within(cell)


def test_a_distant_cell_is_beyond_the_threshold() -> None:
    from pipeline.spatial.h3_grid import cells_for_points

    cells = cells_for_points([SEATTLE[0], SPOKANE[0]], [SEATTLE[1], SPOKANE[1]])
    result = measure_road_distances(cells, [SEATTLE[0]], [SEATTLE[1]])
    assert result.within(cells[0])
    assert not result.within(cells[1])
    assert result.distances_km[cells[1]] > 100.0


def test_with_no_roads_at_all_every_cell_is_infinitely_far() -> None:
    """D8: "there is no road anywhere" is the strongest exclusion, not missing data."""
    from pipeline.spatial.h3_grid import cells_for_points

    cells = cells_for_points([SEATTLE[0]], [SEATTLE[1]])
    result = measure_road_distances(cells, [], [])
    assert result.distances_km[cells[0]] == float("inf")
    assert not result.within(cells[0])


def test_measuring_no_cells_returns_nothing_rather_than_failing() -> None:
    assert measure_road_distances([], [1.0], [1.0]).distances_km == {}


def test_the_sensitivity_curve_is_monotone_in_the_threshold() -> None:
    from pipeline.spatial.h3_grid import cells_for_points

    cells = cells_for_points([SEATTLE[0], SPOKANE[0]], [SEATTLE[1], SPOKANE[1]])
    result = measure_road_distances(cells, [SEATTLE[0]], [SEATTLE[1]])
    curve = result.sensitivity(cells)
    values = [curve[f"{t:g}"] for t in SENSITIVITY_KM]
    assert values == sorted(values)


def test_an_explicit_threshold_overrides_the_default() -> None:
    from pipeline.spatial.h3_grid import cells_for_points

    cells = cells_for_points([SPOKANE[0]], [SPOKANE[1]])
    result = measure_road_distances(cells, [SEATTLE[0]], [SEATTLE[1]])
    assert not result.within(cells[0])
    assert result.within(cells[0], threshold_km=1000.0)


def test_the_shipped_summary_reports_the_method_and_the_whole_curve() -> None:
    from pipeline.spatial.h3_grid import cells_for_points

    cells = cells_for_points([SEATTLE[0], SPOKANE[0]], [SEATTLE[1], SPOKANE[1]])
    result = measure_road_distances(cells, [SEATTLE[0]], [SEATTLE[1]])
    payload = result.to_dict(cells)
    assert payload["cells_measured"] == 2
    assert payload["cells_within_threshold"] == 1
    assert payload["threshold_km"] == 5.0
    assert payload["road_vertices"] == 1
    curve = cast(dict[str, int], payload["sensitivity_cells_within_threshold_by_km"])
    assert set(curve) == {"1", "2", "3", "5", "8", "12", "20"}
    assert "VERTEX" in str(payload["distance_method"])


def test_a_feature_with_no_geometry_is_counted_out_rather_than_skipped_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pyogrio.raw

    def fake_read(_source: str, **_kwargs: object) -> tuple[
        object, object, list[bytes | None], list[list[str]]]:
        return None, None, [wkb_linestring([SEATTLE]), None], [["S1100", "S1100"]]

    monkeypatch.setattr(pyogrio.raw, "read", fake_read)
    roads = read_road_vertices("53")
    assert roads.features == 1
    assert roads.excluded_classes["missing_geometry"] == 1


def test_the_shipped_threshold_matches_the_documented_configuration() -> None:
    """CLAUDE.md §3 puts every configurable analytic threshold in `thresholds.yml` and
    forbids magic numbers elsewhere. The siting constants are declared in Python for
    typing; this test is what stops the two drifting apart silently."""
    import yaml

    from pipeline.model.access import THRESHOLDS_CONFIG
    from pipeline.model.run_phase4 import SATURATION_PORTS_PER_1K

    siting = yaml.safe_load(THRESHOLDS_CONFIG.read_text(encoding="utf-8"))["siting"]
    assert siting["road_proximity_km"] == DEFAULT_ROAD_PROXIMITY_KM
    assert tuple(siting["road_proximity_sensitivity_km"]) == SENSITIVITY_KM
    assert siting["saturation_dcfc_ports_per_1k_demand"] == SATURATION_PORTS_PER_1K
