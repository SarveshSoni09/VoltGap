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
