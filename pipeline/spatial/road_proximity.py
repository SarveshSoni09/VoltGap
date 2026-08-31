"""Road-proximity distance for H3 candidate cells.

CLAUDE.md §7.8: siting candidates must be "within a configured distance of the road
network". The threshold, the road classes and the distance method were pre-registered in
``docs/evidence/P4-0_road_filter_preregistration.md`` **before** any candidate set was
recomputed, so none of them could be chosen after seeing which value gave a convenient
answer.

The measurement reuses the same haversine ball tree Phase 2 uses for access distance
rather than adding a second spatial index: the operation is identical - nearest point from
a query location to a set of fixtures - and two implementations of it would be two places
for it to be wrong.

**Distance is measured to road VERTICES, not to the nearest point on a road segment.** A
long straight segment between two distant vertices could pass close to a cell whose
centroid is far from either endpoint. TIGER road geometries are densely vertexed - 3,006
Washington features carry 376,007 vertices, about 125 each - so the error is small, but it
is an approximation and it is recorded as assumption **A-4.6** rather than described as
exact.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pipeline.spatial.distance import nearest_site_distances
from pipeline.spatial.h3_grid import cell_centroid

#: Pre-registered before any result was recomputed. An H3 res-6 centroid sits up to
#: ~3,320 m from its own boundary, so a threshold below that would exclude cells whose
#: nearest arterial lies immediately outside them.
DEFAULT_ROAD_PROXIMITY_KM = 5.0

#: The range the shipped sensitivity curve is computed across, so the threshold is
#: visible as a choice rather than presented as a finding.
SENSITIVITY_KM: tuple[float, ...] = (1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 20.0)


@dataclass(frozen=True)
class RoadDistances:
    """Distance from each cell's centroid to the nearest included road vertex."""

    distances_km: Mapping[str, float]
    road_vertices: int
    threshold_km: float

    def within(self, cell: str, threshold_km: float | None = None) -> bool:
        limit = self.threshold_km if threshold_km is None else threshold_km
        return self.distances_km.get(cell, float("inf")) <= limit

    def sensitivity(
        self, cells: Sequence[str], thresholds: Sequence[float] = SENSITIVITY_KM
    ) -> dict[str, int]:
        """How many of these cells qualify at each threshold in the swept range."""
        return {f"{t:g}": sum(1 for c in cells if self.within(c, t))
                for t in thresholds}

    def to_dict(self, cells: Sequence[str]) -> dict[str, object]:
        qualifying = [c for c in cells if self.within(c)]
        return {
            "threshold_km": self.threshold_km,
            "road_vertices": self.road_vertices,
            "cells_measured": len(cells),
            "cells_within_threshold": len(qualifying),
            "sensitivity_cells_within_threshold_by_km": self.sensitivity(cells),
            "distance_method": (
                "haversine from the cell centroid to the nearest road VERTEX, not to "
                "the nearest point on a segment (assumption A-4.6)"
            ),
        }


def measure_road_distances(
    cells: Sequence[str],
    road_latitudes: Sequence[float],
    road_longitudes: Sequence[float],
    threshold_km: float = DEFAULT_ROAD_PROXIMITY_KM,
) -> RoadDistances:
    """Nearest included-class road vertex for every cell, in kilometres.

    With no road vertices at all every cell reports infinite distance rather than being
    quietly passed through. That is directive D8: "there is no road anywhere" is the
    strongest possible exclusion, not missing data, and the caller decides what to do
    about it rather than the measurement deciding silently.
    """
    if not cells:
        return RoadDistances({}, len(road_latitudes), threshold_km)
    centroids = [cell_centroid(cell) for cell in cells]
    result = nearest_site_distances(
        [lat for lat, _ in centroids], [lon for _, lon in centroids],
        road_latitudes, road_longitudes,
    )
    return RoadDistances(
        distances_km={cell: metres / 1000.0
                      for cell, metres in zip(cells, result.distances_m, strict=True)},
        road_vertices=len(road_latitudes),
        threshold_km=threshold_km,
    )
