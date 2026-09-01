"""A-4.8: does the tangent-plane step pick the point the sphere would pick?

Road distance is measured to the nearest **point on** a segment (§7.8). Finding that point
needs an argmin along the segment, and ``PolylineIndex`` finds it by projecting into a
tangent plane centred on the query point. The distance finally *reported* is then measured
with haversine on the sphere, so the published number is always a genuine great-circle
distance to a real location on a road — and therefore a rigorous upper bound on the true
minimum, whatever the projection did.

What the projection **can** do is pick a slightly different point than the exact spherical
calculation would, which would make the reported distance a little larger than the true
minimum. That is assumption **A-4.8**, and this module measures it rather than asserting
it is negligible.

**The reference.** Both methods parameterise the same curve: linear interpolation in
(latitude, longitude) between the segment's endpoints, ``lerp(A, B, t)`` for t in [0, 1].
The only thing under test is which ``t`` gets chosen. So the reference minimises the true
haversine distance along that same curve directly, by golden-section search on t — the
distance from a fixed point to points along the curve is unimodal in t, which is what makes
the search exact to convergence. No projection is involved anywhere in the reference.

The error is then ``reported - reference``, which cannot be negative: the reported value is
the haversine distance at one particular t, and the reference is the minimum over all t.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from pipeline.spatial.distance import PolylineIndex, _closest_point_on_segments

#: Golden-section iterations. Each shrinks the bracket by ~0.382, so 80 iterations take a
#: unit interval below 1e-16 — the search is exact to double precision long before this.
GOLDEN_ITERATIONS = 80
_INVERSE_PHI = (math.sqrt(5.0) - 1.0) / 2.0

EARTH_RADIUS_KM = 6371.0088

#: Below this, "reported minus exact" is floating-point representation, not geometry. The
#: reported distance comes from a vectorised numpy haversine and the reference from the
#: scalar ``math`` one; they disagree in the last unit in the last place, which shows up as
#: differences around 1e-13 km — **0.1 nanometres** — with both values identical to every
#: printed digit. A tolerance tighter than this would report float noise as a defect.
FLOAT_NOISE_KM = 1e-9


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = (math.sin(dp / 2.0) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2)
    return 2.0 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, max(0.0, a))))


def exact_distance_to_segment_km(
    lat: float, lon: float,
    a_lat: float, a_lon: float, b_lat: float, b_lon: float,
) -> tuple[float, float]:
    """Minimum haversine distance to the segment, and the ``t`` that achieves it.

    Golden-section search on t, with no projection anywhere. This is the reference the
    tangent-plane pick is judged against.
    """
    def at(t: float) -> float:
        return haversine_km(lat, lon, a_lat + t * (b_lat - a_lat),
                            a_lon + t * (b_lon - a_lon))

    low, high = 0.0, 1.0
    c = high - _INVERSE_PHI * (high - low)
    d = low + _INVERSE_PHI * (high - low)
    fc, fd = at(c), at(d)
    for _ in range(GOLDEN_ITERATIONS):
        if fc < fd:
            high, d, fd = d, c, fc
            c = high - _INVERSE_PHI * (high - low)
            fc = at(c)
        else:
            low, c, fc = c, d, fd
            d = low + _INVERSE_PHI * (high - low)
            fd = at(d)
    best_t = (low + high) / 2.0
    # The interior optimum can lie outside [0, 1] for a segment that points away, so the
    # endpoints are checked explicitly rather than trusted to the bracket.
    candidates = [(at(0.0), 0.0), (at(1.0), 1.0), (at(best_t), best_t)]
    distance, t = min(candidates)
    return distance, t


@dataclass(frozen=True)
class GeometryValidation:
    """A-4.8, measured on real road geometry."""

    label: str
    comparisons: int
    error_mean_km: float
    error_p99_km: float
    error_max_km: float
    #: Counted only beyond ``FLOAT_NOISE_KM``. A genuine negative would mean the
    #: reference found a *larger* minimum than the reported distance, which is
    #: impossible: the reported value is the haversine distance at one t on the curve,
    #: and the reference is the minimum over every t on the same curve.
    negative_errors: int
    reclassifications_at_threshold: int
    threshold_km: float

    @property
    def resolved(self) -> bool:
        """No negative error, and no cell changes side of the filter threshold."""
        return self.negative_errors == 0 and self.reclassifications_at_threshold == 0

    def to_dict(self) -> dict[str, object]:
        return {
            "assumption": "A-4.8",
            "label": self.label,
            "question": (
                "does the tangent-plane argmin pick the same point on a segment that an "
                "exact spherical calculation would?"),
            "method": (
                "both parameterise the SAME curve, lerp(A, B, t) in (lat, lon); the "
                "reference minimises true haversine over t by golden-section search with "
                "no projection anywhere, so only the choice of t is under test"),
            "comparisons": self.comparisons,
            "error_km": {
                "definition": (
                    "reported distance minus exact minimum along the same segment; "
                    "cannot be negative, because the reported value is the haversine "
                    "distance at one t and the reference is the minimum over all t"),
                "mean": self.error_mean_km,
                "p99": self.error_p99_km,
                "max": self.error_max_km,
            },
            "error_max_millimetres": round(self.error_max_km * 1_000_000.0, 3),
            "negative_errors": self.negative_errors,
            "negative_error_tolerance_km": FLOAT_NOISE_KM,
            "negative_error_tolerance_note": (
                "differences below 1e-9 km are last-ULP disagreement between the "
                "vectorised and scalar haversine implementations, not geometry"),
            "filter_threshold_km": self.threshold_km,
            "cells_reclassified_at_the_threshold":
                self.reclassifications_at_threshold,
            "resolved": self.resolved,
        }


def validate_tangent_plane_pick(
    label: str,
    query_lat: Sequence[float],
    query_lon: Sequence[float],
    roads: PolylineIndex,
    threshold_km: float,
    segments_per_query: int = 12,
) -> GeometryValidation:
    """Compare the tangent-plane pick against the exact spherical minimum.

    For each query point the nearest few segments are checked, not merely the nearest
    one: the projection could in principle promote a different segment to the front, so
    the comparison has to consider the ones that could compete.
    """
    if len(query_lat) != len(query_lon):
        raise ValueError("query latitude and longitude must be the same length")
    if not roads.segments:
        raise ValueError("A-4.8 cannot be validated against a road set with no segments")

    reported = roads.nearest_km(query_lat, query_lon)
    errors: list[float] = []
    reclassified = 0
    for i, (lat, lon) in enumerate(zip(query_lat, query_lon, strict=True)):
        starts = _nearest_segment_starts(roads, lat, lon, segments_per_query)
        exact = min(
            exact_distance_to_segment_km(
                lat, lon, float(roads.lat[s]), float(roads.lon[s]),
                float(roads.lat[s + 1]), float(roads.lon[s + 1]))[0]
            for s in starts
        )
        errors.append(float(reported[i]) - exact)
        if (float(reported[i]) <= threshold_km) != (exact <= threshold_km):
            reclassified += 1

    array = np.array(errors)
    return GeometryValidation(
        label=label, comparisons=len(errors),
        error_mean_km=float(array.mean()),
        error_p99_km=float(np.percentile(array, 99)),
        error_max_km=float(array.max()),
        negative_errors=int((array < -FLOAT_NOISE_KM).sum()),
        reclassifications_at_threshold=reclassified,
        threshold_km=threshold_km,
    )


def _nearest_segment_starts(
    roads: PolylineIndex, lat: float, lon: float, count: int
) -> list[int]:
    """The start indices of the `count` segments whose planar pick is closest."""
    starts = roads.segment_start
    close_lat, close_lon = _closest_point_on_segments(
        lat, lon, roads.lat[starts], roads.lon[starts],
        roads.lat[starts + 1], roads.lon[starts + 1])
    planar = np.hypot((close_lon - lon) * np.cos(np.radians(lat)), close_lat - lat)
    take = min(count, planar.size)
    return [int(starts[j]) for j in np.argpartition(planar, take - 1)[:take]]
