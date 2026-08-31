"""Distance computation for access metrics.

Core ships **network-free straight-line distance** with the limitation stated
(CLAUDE.md 7.5). Drive-time isochrones are Extension tier E3. A straight-line distance
always understates real travel distance, so an access gap measured this way is a
**lower bound** on the true gap: the population actually beyond a drive-distance
threshold is at least as large as reported here, never smaller.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from sklearn.neighbors import BallTree

from pipeline.spatial.clustering import EARTH_RADIUS_M


@dataclass(frozen=True)
class NearestResult:
    """Nearest-site distance for each query point, in metres."""

    distances_m: tuple[float, ...]
    indices: tuple[int, ...]

    def __len__(self) -> int:
        return len(self.distances_m)


def nearest_site_distances(
    query_lat: Sequence[float],
    query_lon: Sequence[float],
    site_lat: Sequence[float],
    site_lon: Sequence[float],
) -> NearestResult:
    """Great-circle distance from each query point to the nearest site.

    Uses a ball tree on the haversine metric, which is exact for great-circle distance
    rather than an equirectangular approximation. With no sites at all, every point is
    reported at infinite distance rather than being dropped: "there is no charger
    anywhere" is the strongest possible access gap, not missing data (directive D8).
    """
    if len(query_lat) != len(query_lon):
        raise ValueError("query latitude and longitude must be the same length")
    if len(site_lat) != len(site_lon):
        raise ValueError("site latitude and longitude must be the same length")
    if not query_lat:
        return NearestResult((), ())
    if not site_lat:
        return NearestResult(tuple([float("inf")] * len(query_lat)),
                             tuple([-1] * len(query_lat)))

    sites = np.radians(np.column_stack([np.asarray(site_lat, dtype=float),
                                        np.asarray(site_lon, dtype=float)]))
    queries = np.radians(np.column_stack([np.asarray(query_lat, dtype=float),
                                          np.asarray(query_lon, dtype=float)]))
    tree = BallTree(sites, metric="haversine")
    radians, indices = tree.query(queries, k=1)
    metres = radians[:, 0] * EARTH_RADIUS_M
    return NearestResult(tuple(float(m) for m in metres),
                         tuple(int(i) for i in indices[:, 0]))


# --- Point-to-polyline distance -------------------------------------------------------
#
# Nearest-VERTEX distance is not nearest-POINT distance. A point beside the middle of a
# long straight segment is close to the road and far from either endpoint, so a vertex
# measurement overestimates. The overestimate is bounded by half the segment length —
# up to 2.96 km against the measured 5.928 km longest TIGER segment — which is large
# enough against a 5 km filter threshold to change candidate membership. So it is
# computed properly rather than bounded and waved through.
#
# What is returned is the great-circle distance to an actual point ON a road. The
# nearest point along each segment is found in a local tangent plane; the distance to
# that point is then measured with the same haversine formula used everywhere else. So
# the result is a genuine geodesic distance to a real location, never greater than the
# nearest-vertex distance (vertices are the t=0 and t=1 cases of the same segment), and
# a rigorous upper bound on the true minimum distance to the road network.

#: How far out the exact refinement is worth doing. Refinement is skipped only when the
#: true distance is *provably* beyond this, which needs the vertex distance to exceed it
#: by more than the longest segment — because a point beside the middle of a long segment
#: is near the road while being far from every vertex. Gating on the vertex distance
#: alone would skip refinement exactly where it matters most.
REFINEMENT_CAP_KM = 30.0

_KM_PER_RADIAN = EARTH_RADIUS_M / 1000.0


def _haversine_km(
    lat1: np.ndarray, lon1: np.ndarray, lat2: np.ndarray, lon2: np.ndarray
) -> np.ndarray:
    """Great-circle distance in kilometres between paired coordinate arrays."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp, dl = p2 - p1, np.radians(lon2 - lon1)
    a = np.sin(dp / 2.0) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2.0) ** 2
    km = 2.0 * _KM_PER_RADIAN * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))
    return np.asarray(km, dtype=float)


def _closest_point_on_segments(
    lat: float, lon: float,
    a_lat: np.ndarray, a_lon: np.ndarray, b_lat: np.ndarray, b_lon: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """The point on each segment nearest to (lat, lon), as (latitudes, longitudes).

    Projected into a tangent plane centred on the query point, where a segment is a
    straight line and the nearest point is the clamped scalar projection. Over the
    tens of kilometres this is used across, the projection's distortion moves the
    chosen point negligibly — and any error it does introduce affects only *which*
    point is picked, never the distance finally reported for it, which is measured on
    the sphere.
    """
    scale = np.cos(np.radians(lat))
    ax, ay = (a_lon - lon) * scale, a_lat - lat
    bx, by = (b_lon - lon) * scale, b_lat - lat
    dx, dy = bx - ax, by - ay
    length_squared = dx * dx + dy * dy
    # A zero-length segment is its own nearest point; t=0 selects endpoint A.
    safe = np.where(length_squared > 0.0, length_squared, 1.0)
    t = np.clip(-(ax * dx + ay * dy) / safe, 0.0, 1.0)
    t = np.where(length_squared > 0.0, t, 0.0)
    return a_lat + t * (b_lat - a_lat), a_lon + t * (b_lon - a_lon)


class PolylineIndex:
    """Nearest distance from query points to a set of polylines, in kilometres.

    Built from CSR-style arrays: vertex coordinates plus per-polyline start offsets, so
    a segment is only ever formed between two vertices of the *same* polyline. Joining
    the last vertex of one road to the first of the next would invent a road that does
    not exist.
    """

    def __init__(
        self, lat: Sequence[float] | np.ndarray, lon: Sequence[float] | np.ndarray,
        offsets: Sequence[int] | np.ndarray,
    ) -> None:
        self.lat = np.asarray(lat, dtype=float)
        self.lon = np.asarray(lon, dtype=float)
        if self.lat.shape != self.lon.shape:
            raise ValueError("latitude and longitude must be the same length")
        offsets_array = np.asarray(offsets, dtype=np.int64)
        if offsets_array.size < 1 or offsets_array[-1] != self.lat.size:
            raise ValueError(
                "offsets must be CSR-style and end at the vertex count: "
                f"got {offsets_array[-1] if offsets_array.size else None} "
                f"for {self.lat.size} vertices"
            )
        # A vertex starts a segment when the next vertex belongs to the same polyline.
        starts = np.ones(self.lat.size, dtype=bool)
        if self.lat.size:
            starts[offsets_array[1:] - 1] = False
        self.segment_start = np.flatnonzero(starts)
        self.segment_lengths_km = (
            _haversine_km(self.lat[self.segment_start], self.lon[self.segment_start],
                          self.lat[self.segment_start + 1], self.lon[self.segment_start + 1])
            if self.segment_start.size else np.empty(0)
        )
        self.longest_segment_km = (
            float(self.segment_lengths_km.max()) if self.segment_lengths_km.size else 0.0)
        self._tree = (
            BallTree(np.radians(np.column_stack([self.lat, self.lon])), metric="haversine")
            if self.lat.size else None)

    @classmethod
    def from_polylines(
        cls, polylines: Sequence[Sequence[tuple[float, float]]]
    ) -> PolylineIndex:
        """Build from an explicit list of coordinate runs. Used by tests and fixtures."""
        lat: list[float] = []
        lon: list[float] = []
        offsets = [0]
        for line in polylines:
            for point_lat, point_lon in line:
                lat.append(point_lat)
                lon.append(point_lon)
            offsets.append(len(lat))
        return cls(lat, lon, offsets)

    @property
    def vertices(self) -> int:
        return int(self.lat.size)

    @property
    def segments(self) -> int:
        return int(self.segment_start.size)

    def assert_refinement_covers(self, threshold_km: float) -> None:
        """Check the skip-refinement shortcut cannot affect a threshold this large.

        Refinement is skipped only where the true distance provably exceeds
        ``REFINEMENT_CAP_KM``, so any threshold at or below that is unaffected.
        """
        if threshold_km > REFINEMENT_CAP_KM:
            raise ValueError(
                f"threshold {threshold_km} km exceeds the refinement cap "
                f"({REFINEMENT_CAP_KM} km); beyond the cap the unrefined vertex "
                "distance is reported, so raise the cap rather than report it."
            )

    def nearest_km(
        self, query_lat: Sequence[float], query_lon: Sequence[float]
    ) -> np.ndarray:
        """Great-circle distance to the nearest point on the nearest polyline."""
        if len(query_lat) != len(query_lon):
            raise ValueError("query latitude and longitude must be the same length")
        if not len(query_lat):
            return np.empty(0)
        if self._tree is None:
            return np.full(len(query_lat), np.inf)

        queries = np.radians(np.column_stack([np.asarray(query_lat, dtype=float),
                                              np.asarray(query_lon, dtype=float)]))
        vertex_km = np.asarray(
            self._tree.query(queries, k=1)[0][:, 0] * _KM_PER_RADIAN, dtype=float)
        best: np.ndarray = vertex_km.copy()
        if not self.segment_start.size:
            return best

        # True distance is at least the vertex distance minus the longest segment, so
        # this is the weakest test that provably puts a point beyond the cap.
        skip_beyond = REFINEMENT_CAP_KM + self.longest_segment_km
        for i in range(len(best)):
            if vertex_km[i] > skip_beyond:
                continue
            # Any segment that beats the vertex distance must have an endpoint within
            # the vertex distance plus its own length, so this radius cannot miss one.
            # It always contains at least the nearest vertex itself, so `near` is never
            # empty here and there is no empty case to guard.
            radius = (vertex_km[i] + self.longest_segment_km) / _KM_PER_RADIAN
            near = self._tree.query_radius(queries[i:i + 1], r=radius)[0]
            # A gathered vertex identifies the segment it starts and the one it ends.
            wanted = np.union1d(near, near - 1)
            segments = self.segment_start[
                np.isin(self.segment_start, wanted, assume_unique=True)]
            if not segments.size:
                continue
            close_lat, close_lon = _closest_point_on_segments(
                float(query_lat[i]), float(query_lon[i]),
                self.lat[segments], self.lon[segments],
                self.lat[segments + 1], self.lon[segments + 1])
            distances = _haversine_km(
                np.full(close_lat.shape, float(query_lat[i])),
                np.full(close_lon.shape, float(query_lon[i])), close_lat, close_lon)
            best[i] = min(best[i], float(distances.min()))
        return best
