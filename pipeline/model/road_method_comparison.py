"""Nearest road VERTEX against nearest point ON a road: what the correction changed.

The first Phase 4 road filter measured distance to the nearest TIGER **vertex**. External
review identified that as a correctness defect, and it is one: a LineString's nearest
vertex is not generally its nearest point, so the measurement **overestimates** distance
and can falsely exclude a cell from a hard candidate filter. The error is bounded by half
the segment length — up to **2.96 km** on this data against a **5.0 km** threshold.

This module measures what actually changed rather than asserting it was small. Per state:
the distribution of the distance error, how many cells changed side of the threshold, the
candidate-set Jaccard, portfolio overlap at each budget, and the demand and equity
objective deltas.

The vertex method is reproduced here **only** to be compared against. It is not available
to the pipeline and nothing else imports it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from pipeline.model.hexes import HexCell
from pipeline.model.siting import CandidateSet, build_candidates, greedy_select
from pipeline.spatial.distance import PolylineIndex, nearest_site_distances
from pipeline.spatial.h3_grid import cell_centroid
from pipeline.spatial.road_proximity import (
    DEFAULT_ROAD_PROXIMITY_KM,
    RoadDistances,
    measure_road_distances,
)


def vertex_road_distances(
    cells: Sequence[str], roads: PolylineIndex,
    threshold_km: float = DEFAULT_ROAD_PROXIMITY_KM,
) -> RoadDistances:
    """The **superseded** nearest-vertex measurement, kept only for comparison.

    Do not use this for anything else. It is wrong in the way this module documents.
    """
    if not cells:
        return RoadDistances({}, roads.vertices, threshold_km, roads.segments)
    centroids = [cell_centroid(cell) for cell in cells]
    result = nearest_site_distances(
        [lat for lat, _ in centroids], [lon for _, lon in centroids],
        roads.lat.tolist(), roads.lon.tolist())
    return RoadDistances(
        distances_km={cell: metres / 1000.0
                      for cell, metres in zip(cells, result.distances_m, strict=True)},
        road_vertices=roads.vertices, threshold_km=threshold_km,
        road_segments=roads.segments)


def _jaccard(left: Sequence[str], right: Sequence[str]) -> float:
    a, b = set(left), set(right)
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def _objectives(selected: Sequence[str], candidates: CandidateSet) -> tuple[float, float]:
    by_index = {c.h3_index: c for c in candidates.candidates}
    covered: set[str] = set()
    for site in selected:
        covered.update(candidates.coverage[site])
    return (sum(by_index[c].demand for c in covered),
            sum(by_index[c].equity_population for c in covered))


@dataclass(frozen=True)
class MethodComparison:
    """One state, nearest-vertex against nearest-point-on-segment."""

    state: str
    cells: int
    #: vertex distance minus segment distance, in km. Never negative: the nearest point
    #: on a segment is at least as close as its nearest vertex, which is a point on it.
    error_mean_km: float
    error_median_km: float
    error_p99_km: float
    error_max_km: float
    cells_overstated_by_over_100m: int
    cells_that_change_side_of_the_threshold: int
    candidates_vertex: int
    candidates_segment: int
    candidate_jaccard: float
    portfolio_overlap: Mapping[int, float]
    demand_delta: float
    equity_delta: float

    @property
    def material(self) -> bool:
        return (self.cells_that_change_side_of_the_threshold > 0
                or self.candidate_jaccard < 1.0
                or any(v < 1.0 for v in self.portfolio_overlap.values()))

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "cells": self.cells,
            "distance_error_km": {
                "definition": (
                    "nearest-VERTEX distance minus nearest-POINT-ON-SEGMENT distance; "
                    "never negative, because a vertex is itself a point on the segment"),
                "mean": round(self.error_mean_km, 6),
                "median": round(self.error_median_km, 6),
                "p99": round(self.error_p99_km, 6),
                "max": round(self.error_max_km, 6),
            },
            "cells_overstated_by_over_100m": self.cells_overstated_by_over_100m,
            "cells_that_change_side_of_the_threshold":
                self.cells_that_change_side_of_the_threshold,
            "candidates_nearest_vertex": self.candidates_vertex,
            "candidates_nearest_point_on_segment": self.candidates_segment,
            "candidate_set_jaccard": round(self.candidate_jaccard, 6),
            "portfolio_overlap_by_budget": {
                str(k): round(v, 6) for k, v in sorted(self.portfolio_overlap.items())},
            "demand_objective_delta": round(self.demand_delta, 6),
            "equity_objective_delta": round(self.equity_delta, 6),
            "material": self.material,
        }


def compare_distance_methods(
    state: str,
    cells: Sequence[HexCell],
    roads: PolylineIndex,
    saturation_ports_per_1k_demand: float,
    budgets: Sequence[int] = (5, 20, 50),
    threshold_km: float = DEFAULT_ROAD_PROXIMITY_KM,
) -> MethodComparison:
    """Score the corrected distance method against the superseded vertex method."""
    if not budgets:
        raise ValueError("at least one budget is needed to compare portfolios")
    index = [c.h3_index for c in cells]
    vertex = vertex_road_distances(index, roads, threshold_km)
    segment = measure_road_distances(index, roads, threshold_km)

    error = np.array([vertex.distances_km[c] - segment.distances_km[c] for c in index])
    if (error < -1e-9).any():
        raise ValueError(
            "a segment distance exceeded its vertex distance, which is impossible: a "
            "vertex lies on the segment, so the nearest point can only be closer")
    changed = sum(1 for c in index if vertex.within(c) != segment.within(c))

    vertex_set = build_candidates(cells, saturation_ports_per_1k_demand, vertex)
    segment_set = build_candidates(cells, saturation_ports_per_1k_demand, segment)
    portfolios = {b: (greedy_select(vertex_set, b).selected,
                      greedy_select(segment_set, b).selected) for b in budgets}
    objective_budget = budgets[len(budgets) // 2]
    before = _objectives(portfolios[objective_budget][0], vertex_set)
    after = _objectives(portfolios[objective_budget][1], segment_set)

    return MethodComparison(
        state=state, cells=len(cells),
        error_mean_km=float(error.mean()), error_median_km=float(np.median(error)),
        error_p99_km=float(np.percentile(error, 99)), error_max_km=float(error.max()),
        cells_overstated_by_over_100m=int((error > 0.1).sum()),
        cells_that_change_side_of_the_threshold=changed,
        candidates_vertex=len(vertex_set.candidates),
        candidates_segment=len(segment_set.candidates),
        candidate_jaccard=_jaccard([c.h3_index for c in vertex_set.candidates],
                                   [c.h3_index for c in segment_set.candidates]),
        portfolio_overlap={b: _jaccard(*portfolios[b]) for b in budgets},
        demand_delta=after[0] - before[0], equity_delta=after[1] - before[1],
    )
