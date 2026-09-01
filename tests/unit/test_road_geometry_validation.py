"""A-4.8: whether the tangent-plane argmin picks the point the sphere would pick.

The reported road distance is always a haversine distance to a real point on a road, so
it is a rigorous upper bound on the truth whatever the projection does. What the
projection could do is pick a slightly *different* point, making the reported distance a
little larger than the true minimum. These tests exercise the measurement of that.
"""

from __future__ import annotations

import pytest

from pipeline.spatial.distance import PolylineIndex
from pipeline.validation.road_geometry import (
    FLOAT_NOISE_KM,
    GeometryValidation,
    exact_distance_to_segment_km,
    haversine_km,
    validate_tangent_plane_pick,
)

# --- the reference itself must be right before it can judge anything ------------------

def test_the_reference_finds_the_midpoint_of_a_long_segment() -> None:
    """The case the whole road correction exists for. The nearest point is the middle,
    t = 0.5, and the distance is the perpendicular offset — not the endpoint distance."""
    distance, t = exact_distance_to_segment_km(47.02, -121.5, 47.0, -122.0, 47.0, -121.0)
    assert t == pytest.approx(0.5, abs=1e-6)
    assert distance == pytest.approx(2.2239, abs=0.001)
    endpoint = haversine_km(47.02, -121.5, 47.0, -122.0)
    assert endpoint > 37.0


def test_the_reference_clamps_to_an_endpoint_when_the_optimum_lies_outside() -> None:
    """A segment pointing away: the unconstrained minimum is off the end, so the answer
    must be the endpoint, not an extrapolation along the line."""
    distance, t = exact_distance_to_segment_km(47.0, -123.0, 47.0, -122.0, 47.0, -121.0)
    assert t == pytest.approx(0.0, abs=1e-6)
    assert distance == pytest.approx(haversine_km(47.0, -123.0, 47.0, -122.0), abs=1e-9)

    distance, t = exact_distance_to_segment_km(47.0, -120.0, 47.0, -122.0, 47.0, -121.0)
    assert t == pytest.approx(1.0, abs=1e-6)
    assert distance == pytest.approx(haversine_km(47.0, -120.0, 47.0, -121.0), abs=1e-9)


def test_a_point_on_the_segment_is_at_zero_distance() -> None:
    distance, _ = exact_distance_to_segment_km(47.0, -121.5, 47.0, -122.0, 47.0, -121.0)
    assert distance == pytest.approx(0.0, abs=1e-9)


def test_the_reference_handles_a_zero_length_segment() -> None:
    distance, _ = exact_distance_to_segment_km(47.1, -122.0, 47.0, -122.0, 47.0, -122.0)
    assert distance == pytest.approx(haversine_km(47.1, -122.0, 47.0, -122.0), abs=1e-9)


def test_haversine_agrees_with_a_known_separation() -> None:
    """One degree of latitude is about 111.19 km anywhere on the sphere."""
    assert haversine_km(47.0, -122.0, 48.0, -122.0) == pytest.approx(111.19, abs=0.02)
    assert haversine_km(47.0, -122.0, 47.0, -122.0) == 0.0


# --- the validation ---------------------------------------------------------------

def test_the_tangent_plane_pick_matches_the_sphere_to_within_millimetres() -> None:
    """A-4.8 on a long segment, which is where a projection has the most room to be
    wrong. Millimetres against a 5 km threshold."""
    roads = PolylineIndex.from_polylines([[(47.0, -122.0), (47.0, -121.0)]])
    result = validate_tangent_plane_pick(
        "fixture", [47.02, 47.05, 46.9], [-121.5, -121.7, -121.2], roads, 5.0)
    assert result.comparisons == 3
    assert result.error_max_km < 0.001
    assert result.negative_errors == 0
    assert result.reclassifications_at_threshold == 0
    assert result.resolved


def test_the_error_can_never_be_negative_beyond_float_noise() -> None:
    """The reported value is the distance at one t; the reference is the minimum over
    every t on the same curve. Reported < reference is arithmetically impossible."""
    roads = PolylineIndex.from_polylines([
        [(47.0, -122.0), (47.1, -121.5), (47.0, -121.0)],
        [(46.5, -122.5), (46.6, -122.0)]])
    result = validate_tangent_plane_pick(
        "fixture", [47.05, 46.55, 47.2], [-121.6, -122.2, -121.4], roads, 5.0)
    assert result.error_mean_km >= -FLOAT_NOISE_KM
    assert result.negative_errors == 0


def test_the_tolerance_is_looser_than_float_noise_and_far_tighter_than_geometry() -> None:
    """1e-9 km is a micrometre: far above last-ULP disagreement between the vectorised
    and scalar haversine (~1e-13 km), and far below anything geometrically meaningful."""
    assert FLOAT_NOISE_KM == 1e-9


def test_more_segments_per_query_does_not_change_the_verdict() -> None:
    """The shortlist must not be what makes the answer look good."""
    roads = PolylineIndex.from_polylines([
        [(47.0, -122.0), (47.1, -121.5), (47.0, -121.0)],
        [(46.9, -122.1), (46.95, -121.6)]])
    lat, lon = [47.02, 46.92], [-121.6, -121.9]
    few = validate_tangent_plane_pick("f", lat, lon, roads, 5.0, segments_per_query=1)
    many = validate_tangent_plane_pick("f", lat, lon, roads, 5.0, segments_per_query=99)
    assert many.error_max_km <= few.error_max_km + FLOAT_NOISE_KM
    assert many.resolved


def test_mismatched_query_arrays_are_refused() -> None:
    roads = PolylineIndex.from_polylines([[(47.0, -122.0), (47.0, -121.0)]])
    with pytest.raises(ValueError, match="same length"):
        validate_tangent_plane_pick("f", [1.0, 2.0], [1.0], roads, 5.0)


def test_a_road_set_with_no_segments_cannot_validate_anything() -> None:
    """Silently returning "no error" from a set with nothing to measure would be a
    passing result that means nothing."""
    roads = PolylineIndex.from_polylines([[(47.0, -122.0)]])
    with pytest.raises(ValueError, match="no segments"):
        validate_tangent_plane_pick("f", [47.0], [-122.0], roads, 5.0)


def adversarial() -> tuple[PolylineIndex, float, float]:
    """The worst case for the projection I could construct inside the regime the method
    is actually used in: a 6-degree-span segment at 78 degrees north, where a tangent
    plane distorts most, with the query point ~15 km away. Searched over latitude, span,
    offset and tilt. Even here the error is under 10 cm."""
    roads = PolylineIndex.from_polylines([[(78.0, -3.0), (78.5, 3.0)]])
    return roads, 78.4, 0.0


def test_even_an_adversarial_projection_case_errs_by_under_ten_centimetres() -> None:
    roads, lat, lon = adversarial()
    result = validate_tangent_plane_pick("adversarial", [lat], [lon], roads, 5.0)
    assert 0.0 < result.error_max_km < 0.0001
    assert result.negative_errors == 0
    # 15 km away, so it is nowhere near the 5 km threshold either way.
    assert result.reclassifications_at_threshold == 0
    assert result.resolved


def test_a_reclassification_is_counted_rather_than_smoothed_over() -> None:
    """With the threshold placed between the two answers, the exact minimum falls on one
    side and the reported distance on the other. That must be counted, not smoothed
    over — it is the only way this validation could ever report a real problem."""
    roads, lat, lon = adversarial()
    reported = float(roads.nearest_km([lat], [lon])[0])
    exact, _ = exact_distance_to_segment_km(lat, lon, 78.0, -3.0, 78.5, 3.0)
    assert exact < reported

    between = (exact + reported) / 2.0
    result = validate_tangent_plane_pick("f", [lat], [lon], roads, between)
    assert result.reclassifications_at_threshold == 1
    assert not result.resolved

    # And at the shipped threshold, the same point reclassifies nothing.
    assert validate_tangent_plane_pick("f", [lat], [lon], roads, 5.0).resolved


def test_the_published_record_states_the_question_and_the_verdict() -> None:
    result = GeometryValidation(
        label="Montana", comparisons=200, error_mean_km=1.81e-7,
        error_p99_km=1.414e-6, error_max_km=1.7539e-5, negative_errors=0,
        reclassifications_at_threshold=0, threshold_km=5.0)
    payload = result.to_dict()
    assert payload["assumption"] == "A-4.8"
    assert payload["error_max_millimetres"] == 17.539
    assert payload["resolved"] is True
    assert "golden-section" in str(payload["method"])
    assert "no projection anywhere" in str(payload["method"])
    assert payload["negative_error_tolerance_km"] == FLOAT_NOISE_KM


def test_a_negative_error_marks_the_assumption_unresolved() -> None:
    result = GeometryValidation(
        label="broken", comparisons=10, error_mean_km=0.0, error_p99_km=0.0,
        error_max_km=0.0, negative_errors=1, reclassifications_at_threshold=0,
        threshold_km=5.0)
    assert not result.resolved
    assert result.to_dict()["resolved"] is False
