"""Site resolution: spatial clustering of station coordinates into physical sites.

CLAUDE.md section 6.1 requires ``site_id`` to be derived by spatial clustering
(DBSCAN, eps ~ 50 m) and **not** by rounding coordinates, because rounding creates
arbitrary grid-boundary splits: two stations 5 m apart can land either side of a
rounding boundary and be recorded as different sites, while two stations 140 m apart
can round together.

Domain rule G4 is the reason this matters. Exact coordinate duplicates in AFDC are
usually **co-located multi-network infrastructure, not duplicate records** — a site
where two or three networks each operate their own stalls. They must be aggregated
into one site for coverage and have their ports summed for capacity, never deleted.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from sklearn.cluster import DBSCAN

EARTH_RADIUS_M = 6_371_008.8  # IUGG mean Earth radius
DEFAULT_EPS_M = 50.0
DEFAULT_MIN_SAMPLES = 1  # every station belongs to a site, even a solitary one


@dataclass(frozen=True)
class SiteAssignment:
    """One station's resolved site."""

    station_id: str
    site_id: str
    site_latitude: float
    site_longitude: float
    site_station_count: int


def _haversine_eps(eps_m: float) -> float:
    """DBSCAN with the haversine metric measures angular distance in radians."""
    return eps_m / EARTH_RADIUS_M


def cluster_sites(
    station_ids: Sequence[str],
    latitudes: Sequence[float],
    longitudes: Sequence[float],
    eps_m: float = DEFAULT_EPS_M,
    min_samples: int = DEFAULT_MIN_SAMPLES,
) -> list[SiteAssignment]:
    """Cluster stations into sites.

    Stations with a missing or out-of-range coordinate cannot be clustered and are
    each given their own singleton site rather than being dropped or snapped to a
    default location (directive D8: degrade explicitly, never substitute silently).
    """
    if not (len(station_ids) == len(latitudes) == len(longitudes)):
        raise ValueError("station_ids, latitudes and longitudes must be the same length")
    if not station_ids:
        return []

    usable: list[int] = []
    unusable: list[int] = []
    for index, (lat, lon) in enumerate(zip(latitudes, longitudes, strict=True)):
        if (
            lat is None or lon is None
            or not math.isfinite(float(lat)) or not math.isfinite(float(lon))
            or not (-90.0 <= float(lat) <= 90.0) or not (-180.0 <= float(lon) <= 180.0)
        ):
            unusable.append(index)
        else:
            usable.append(index)

    labels = np.full(len(station_ids), -1, dtype=np.int64)
    if usable:
        radians = np.radians(
            np.array([[float(latitudes[i]), float(longitudes[i])] for i in usable])
        )
        model = DBSCAN(
            eps=_haversine_eps(eps_m),
            min_samples=min_samples,
            metric="haversine",
            algorithm="ball_tree",
        ).fit(radians)
        labels[usable] = model.labels_

    # Cluster centroids, and singleton sites for anything unclusterable.
    members: dict[int, list[int]] = {}
    unusable_set = set(unusable)
    for index in range(len(station_ids)):
        label = int(labels[index])
        if index in unusable_set or label < 0:
            continue
        members.setdefault(label, []).append(index)

    assignments: list[SiteAssignment] = []
    for label, indices in members.items():
        lat = sum(float(latitudes[i]) for i in indices) / len(indices)
        lon = sum(float(longitudes[i]) for i in indices) / len(indices)
        site_id = f"site_{label:07d}"
        for i in indices:
            assignments.append(
                SiteAssignment(str(station_ids[i]), site_id, lat, lon, len(indices))
            )

    for i in unusable:
        assignments.append(
            SiteAssignment(str(station_ids[i]), f"site_nogeo_{station_ids[i]}",
                           float("nan"), float("nan"), 1)
        )

    assignments.sort(key=lambda a: a.station_id)
    return assignments


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres. Used by tests and by the distance module."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))
