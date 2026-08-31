"""The TIGER/Line road source and the road-proximity candidate filter."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from pipeline.model.road_method_comparison import vertex_road_distances
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
from pipeline.spatial.distance import (
    REFINEMENT_CAP_KM,
    PolylineIndex,
    nearest_site_distances,
)
from pipeline.spatial.h3_grid import cell_centroid, cells_for_points
from pipeline.spatial.road_proximity import (
    DEFAULT_ROAD_PROXIMITY_KM,
    SENSITIVITY_KM,
    measure_road_distances,
)


def road_through(*points: tuple[float, float]) -> PolylineIndex:
    """One polyline through the given points."""
    return PolylineIndex.from_polylines([list(points)])

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


# --- distance: nearest POINT on a road, not nearest vertex --------------------------

def test_the_threshold_and_the_sweep_are_the_pre_registered_ones() -> None:
    assert DEFAULT_ROAD_PROXIMITY_KM == 5.0
    assert SENSITIVITY_KM == (1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 20.0)


def test_a_long_segment_is_not_reduced_to_its_endpoints() -> None:
    """THE regression fixture. A two-vertex road ~76 km long, and a candidate cell whose
    centroid sits 2.2 km from its middle. Nearest-vertex distance says ~38 km, which
    excludes the cell from the 5 km filter; the true distance to the road is 2.2 km and
    the cell qualifies. Any implementation that quietly reduces to endpoint or vertex
    distance fails here by more than 10x, and excludes a cell it should admit.

    The road is positioned relative to the CELL CENTROID, not to an arbitrary point,
    because the filter measures from centroids and an H3 res-6 centroid can sit over
    3 km from any point in its own cell.
    """
    cell = cells_for_points([47.02], [-121.5])[0]
    latitude, longitude = cell_centroid(cell)

    # One straight road, 0.02 degrees of latitude south of the centroid (~2.22 km),
    # running half a degree of longitude either side of it (~38 km each way).
    west = (latitude - 0.02, longitude - 0.5)
    east = (latitude - 0.02, longitude + 0.5)
    roads = road_through(west, east)
    assert roads.segments == 1
    assert roads.longest_segment_km > 70.0

    to_segment = roads.nearest_km([latitude], [longitude])[0]
    to_nearest_vertex = nearest_site_distances(
        [latitude], [longitude], [west[0], east[0]], [west[1], east[1]]
    ).distances_m[0] / 1000.0

    assert to_segment == pytest.approx(2.22, abs=0.05)
    assert to_nearest_vertex > 35.0
    assert to_nearest_vertex / to_segment > 10.0

    # The consequence that matters: the filter admits the cell rather than excluding it.
    assert measure_road_distances([cell], roads).within(cell)
    assert not vertex_road_distances([cell], roads).within(cell)


def test_the_segment_distance_never_exceeds_the_vertex_distance() -> None:
    """A vertex IS a point on the segment, so the nearest point can only be closer.
    Asserted over a spread of offsets rather than at one convenient location."""
    roads = road_through((47.0, -122.0), (47.0, -121.0))
    for delta_lat in (0.0, 0.01, 0.05, 0.2, 0.6):
        for delta_lon in (-0.6, -0.2, 0.0, 0.3, 0.7):
            lat, lon = 47.0 + delta_lat, -121.5 + delta_lon
            segment = roads.nearest_km([lat], [lon])[0]
            vertex = nearest_site_distances(
                [lat], [lon], [47.0, 47.0], [-122.0, -121.0]).distances_m[0] / 1000.0
            assert segment <= vertex + 1e-9, (delta_lat, delta_lon)


def test_a_point_on_the_road_is_at_zero_distance() -> None:
    roads = road_through((47.0, -122.0), (47.0, -121.0))
    assert roads.nearest_km([47.0], [-121.5])[0] == pytest.approx(0.0, abs=1e-6)


def test_segments_are_never_formed_between_two_different_roads() -> None:
    """Two parallel roads far apart. Joining the end of one to the start of the next
    would invent a connecting segment passing right by the query point."""
    apart = PolylineIndex.from_polylines(
        [[(47.0, -122.0), (47.0, -121.9)], [(46.0, -121.9), (46.0, -122.0)]])
    together = PolylineIndex.from_polylines(
        [[(47.0, -122.0), (47.0, -121.9), (46.0, -121.9), (46.0, -122.0)]])
    assert apart.segments == 2
    assert together.segments == 3
    midway = (46.5, -121.95)
    assert apart.nearest_km([midway[0]], [midway[1]])[0] > 50.0
    # The connecting segment runs down the -121.9 meridian, 3.8 km away.
    assert together.nearest_km([midway[0]], [midway[1]])[0] < 5.0


def test_a_zero_length_segment_is_its_own_nearest_point() -> None:
    """A duplicated vertex must not divide by zero."""
    roads = PolylineIndex.from_polylines([[(47.0, -122.0), (47.0, -122.0)]])
    assert roads.segments == 1
    assert roads.nearest_km([47.0], [-122.0])[0] == pytest.approx(0.0, abs=1e-9)


def test_a_single_vertex_road_has_no_segments_and_still_measures() -> None:
    roads = PolylineIndex.from_polylines([[(47.0, -122.0)]])
    assert roads.segments == 0
    assert roads.nearest_km([47.0], [-122.0])[0] == pytest.approx(0.0, abs=1e-9)


def test_offsets_that_do_not_account_for_every_vertex_are_refused() -> None:
    with pytest.raises(ValueError, match="CSR-style"):
        PolylineIndex([1.0, 2.0], [1.0, 2.0], [0, 1])


def test_mismatched_coordinate_arrays_are_refused() -> None:
    with pytest.raises(ValueError, match="same length"):
        PolylineIndex([1.0, 2.0], [1.0], [0, 2])


def test_mismatched_query_arrays_are_refused() -> None:
    with pytest.raises(ValueError, match="same length"):
        road_through((47.0, -122.0), (47.0, -121.0)).nearest_km([1.0, 2.0], [1.0])


def test_a_threshold_beyond_the_refinement_cap_is_refused_not_answered() -> None:
    """Beyond the cap the unrefined vertex distance is reported, so a threshold that
    far out would be answered with the very method this correction replaced."""
    roads = road_through((47.0, -122.0), (47.0, -121.0))
    with pytest.raises(ValueError, match="exceeds the refinement cap"):
        roads.assert_refinement_covers(REFINEMENT_CAP_KM + 0.1)
    roads.assert_refinement_covers(REFINEMENT_CAP_KM)


def test_the_refinement_is_not_skipped_just_because_vertices_are_far() -> None:
    """The cap must gate on provable distance, not on vertex distance. This point is
    38 km from both endpoints and 2.2 km from the road; gating on vertex distance
    would skip refinement exactly where it is needed."""
    roads = road_through((47.0, -122.0), (47.0, -121.0))
    assert roads.longest_segment_km > REFINEMENT_CAP_KM
    assert roads.nearest_km([47.02], [-121.5])[0] < 3.0


def test_with_no_roads_at_all_every_cell_is_infinitely_far() -> None:
    """D8: "there is no road anywhere" is the strongest exclusion, not missing data."""
    cells = cells_for_points([SEATTLE[0]], [SEATTLE[1]])
    result = measure_road_distances(cells, PolylineIndex.from_polylines([]))
    assert result.distances_km[cells[0]] == float("inf")
    assert not result.within(cells[0])


def test_measuring_no_cells_returns_nothing_rather_than_failing() -> None:
    assert measure_road_distances([], road_through((1.0, 1.0), (1.0, 2.0))
                                  ).distances_km == {}


def test_a_distant_cell_is_beyond_the_threshold() -> None:
    cells = cells_for_points([SEATTLE[0], SPOKANE[0]], [SEATTLE[1], SPOKANE[1]])
    roads = PolylineIndex.from_polylines([[SEATTLE]])
    result = measure_road_distances(cells, roads)
    assert result.within(cells[0])
    assert not result.within(cells[1])
    assert result.distances_km[cells[1]] > 100.0


def test_the_sensitivity_curve_is_monotone_in_the_threshold() -> None:
    cells = cells_for_points([SEATTLE[0], SPOKANE[0]], [SEATTLE[1], SPOKANE[1]])
    result = measure_road_distances(cells, PolylineIndex.from_polylines([[SEATTLE]]))
    curve = result.sensitivity(cells)
    values = [curve[f"{t:g}"] for t in SENSITIVITY_KM]
    assert values == sorted(values)


def test_an_explicit_threshold_overrides_the_default() -> None:
    cells = cells_for_points([SPOKANE[0]], [SPOKANE[1]])
    result = measure_road_distances(cells, PolylineIndex.from_polylines([[SEATTLE]]))
    assert not result.within(cells[0])
    assert result.within(cells[0], threshold_km=1000.0)


def test_the_shipped_summary_names_the_method_and_the_road_classes() -> None:
    """Item 5 of the correction: the artifact must not imply all roads are covered."""
    cells = cells_for_points([SEATTLE[0], SPOKANE[0]], [SEATTLE[1], SPOKANE[1]])
    result = measure_road_distances(cells, PolylineIndex.from_polylines([[SEATTLE]]))
    payload = result.to_dict(cells)
    assert payload["cells_measured"] == 2
    assert payload["cells_within_threshold"] == 1
    assert payload["threshold_km"] == 5.0
    curve = payload["sensitivity_cells_within_threshold_by_km"]
    assert isinstance(curve, dict)
    assert set(curve) == {"1", "2", "3", "5", "8", "12", "20"}
    method = str(payload["distance_method"])
    assert "nearest POINT" in method and "VERTEX" in method
    network = str(payload["road_network"])
    assert "S1100" in network and "S1200" in network
    assert "NOT all roads" in network


def test_the_real_washington_geometry_carries_segments_not_just_vertices() -> None:
    roads = read_road_vertices("53")
    geometry = roads.index()
    assert geometry.vertices == 376007
    # 3,006 features, so 3,006 fewer segments than vertices.
    assert geometry.segments == 376007 - 3006 == roads.segments
    assert geometry.longest_segment_km == pytest.approx(3.377, abs=0.01)
    assert roads.to_dict()["segments"] == 373001


def test_querying_no_points_returns_nothing_rather_than_failing() -> None:
    assert len(road_through((47.0, -122.0), (47.0, -121.0)).nearest_km([], [])) == 0


def test_an_isolated_vertex_with_no_segment_still_reports_its_own_distance() -> None:
    """A single-vertex road contributes a vertex but no segment. When it is the only
    thing near the query point, the segment refinement finds nothing to refine and the
    vertex distance stands, rather than the search failing or falling through to a
    distant road."""
    lonely = (47.0, -122.0)
    far = [(20.0, -100.0), (20.0, -99.0), (20.0, -98.0)]
    roads = PolylineIndex.from_polylines([[lonely], far])
    assert roads.vertices == 4
    assert roads.segments == 2

    at_the_vertex = roads.nearest_km([lonely[0]], [lonely[1]])[0]
    assert at_the_vertex == pytest.approx(0.0, abs=1e-9)

    nearby = roads.nearest_km([lonely[0] + 0.01], [lonely[1]])[0]
    assert nearby == pytest.approx(1.11, abs=0.02)
