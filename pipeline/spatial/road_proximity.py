"""Distance from H3 candidate cells to the TIGER/Line primary and secondary road network.

CLAUDE.md §7.8 requires siting candidates to be "within a configured distance of the road
network". The threshold, the road classes and the distance method were pre-registered in
``docs/evidence/P4-0_road_filter_preregistration.md`` **before** any candidate set was
recomputed, so none of them could be chosen after seeing which value gave a convenient
answer.

**What this measures, precisely.** Proximity to TIGER/Line 2024 **primary (MTFCC S1100)
and secondary (S1200) roads** — arterials. It is not proximity to *all* roads: local
streets (S1400) are deliberately excluded, because at 38.2 km² per cell nearly every
inhabited cell contains one and the filter would become a near no-op. Every name in the
code, the artifact and the documentation says primary-and-secondary for that reason.

**Distance is to the nearest point on a road, not to the nearest vertex.** A vertex
measurement overestimates: a cell beside the middle of a long straight segment is close to
the road and far from both of its endpoints. In the synthetic regression fixture the
overestimate is **17x** (2.22 km true against 37.98 km by vertex), and on real TIGER
geometry the error is bounded by half the longest segment — up to 2.96 km against a 5 km
filter threshold. That is large enough to falsely exclude candidates, so the nearest point
on each segment is computed. See ``pipeline.spatial.distance.PolylineIndex``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pipeline.spatial.distance import PolylineIndex
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
    road_segments: int = 0

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
            "road_network": (
                "TIGER/Line 2024 PRIMARY (MTFCC S1100) and SECONDARY (S1200) roads "
                "only. NOT all roads: local streets (S1400) are excluded by design."
            ),
            "road_vertices": self.road_vertices,
            "road_segments": self.road_segments,
            "cells_measured": len(cells),
            "cells_within_threshold": len(qualifying),
            "sensitivity_cells_within_threshold_by_km": self.sensitivity(cells),
            "distance_method": (
                "great-circle distance from the cell centroid to the nearest POINT on "
                "the nearest road segment. The nearest point along each segment is "
                "located in a local tangent plane, then its distance is measured with "
                "haversine, so the reported value is a true geodesic distance to a real "
                "location on a road. Nearest-VERTEX distance was used in the first "
                "Phase 4 submission and is wrong: it overestimates by up to half a "
                "segment length (2.96 km on this data, 17x in the regression fixture)."
            ),
        }


def measure_road_distances(
    cells: Sequence[str],
    roads: PolylineIndex,
    threshold_km: float = DEFAULT_ROAD_PROXIMITY_KM,
) -> RoadDistances:
    """Distance from each cell centroid to the nearest point on a primary/secondary road.

    With no roads at all every cell reports infinite distance rather than being quietly
    passed through. That is directive D8: "there is no road anywhere" is the strongest
    possible exclusion, not missing data, and the caller decides what to do about it
    rather than the measurement deciding silently.
    """
    if not cells:
        return RoadDistances({}, roads.vertices, threshold_km, roads.segments)
    for swept in (*SENSITIVITY_KM, threshold_km):
        roads.assert_refinement_covers(swept)
    centroids = [cell_centroid(cell) for cell in cells]
    distances = roads.nearest_km([lat for lat, _ in centroids],
                                 [lon for _, lon in centroids])
    return RoadDistances(
        distances_km={cell: float(km)
                      for cell, km in zip(cells, distances, strict=True)},
        road_vertices=roads.vertices,
        threshold_km=threshold_km,
        road_segments=roads.segments,
    )
