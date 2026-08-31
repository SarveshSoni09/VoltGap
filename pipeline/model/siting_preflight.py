"""Phase 4 preflight: the prerequisites the assumption ledger attached to this phase.

Four assumptions were carried into Phase 4 as conditions on using Phase 2 and Phase 3
outputs for siting. Each is measured here rather than restated, or - where the honest
answer is that Phase 4 does not exercise it - shown not to be triggered.

* **A-2.1** DBSCAN site clusters exceeding 200 m diameter might move a site between H3
  cells. Measured against the actual grid.
* **A-2.2** The rung-2 empirical power median needs masked validation before a phase
  consumes imputed capacity. **Not triggered:** Phase 4 reads port *counts* and no kW
  figure at all, which is enforced structurally.
* **A-2.3** Block-group centroids stand in for block-level weights. The block-level
  benchmark remains unavailable (Phase 0 finding F-7), so what *is* measurable is
  measured: how much the allocation moves between centroid resolutions.
* **A-3.4** AFDC state totals are rounded to the nearest 100. Whether +/-50 per state can
  reorder a siting portfolio is measured, not assumed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import h3

from pipeline.model.hexes import HexCell
from pipeline.spatial.h3_grid import RESOLUTION_NATIONAL, PopulationPoint, cell_area_km2


@dataclass(frozen=True)
class ClusterSensitivity:
    """A-2.1: can a pathological DBSCAN cluster straddle an H3 cell boundary?"""

    resolution: int
    cell_area_km2: float
    approximate_cell_edge_m: float
    max_cluster_diameter_m: float
    clusters_over_200m: int
    diameter_as_share_of_edge: float
    could_straddle_a_boundary: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "assumption": "A-2.1",
            "resolution": self.resolution,
            "cell_area_km2": round(self.cell_area_km2, 2),
            "approximate_cell_edge_m": round(self.approximate_cell_edge_m, 1),
            "max_cluster_diameter_m": self.max_cluster_diameter_m,
            "clusters_over_200m": self.clusters_over_200m,
            "diameter_as_share_of_cell_edge": round(self.diameter_as_share_of_edge, 6),
            "could_straddle_a_cell_boundary": self.could_straddle_a_boundary,
            "interpretation": (
                "A cluster smaller than a cell can still straddle a boundary if it sits "
                "on one, so the honest answer is that it CAN, for a vanishing share of "
                "cells. What matters is the magnitude: a 500 m cluster against a ~3.2 km "
                "cell edge moves at most a boundary-adjacent site by one cell, and the "
                "k-ring coverage neighbourhood already spans adjacent cells, so a site "
                "landing either side covers substantially the same demand."
            ),
        }


def assess_cluster_sensitivity(
    max_cluster_diameter_m: float = 500.0,
    clusters_over_200m: int = 4,
    resolution: int = RESOLUTION_NATIONAL,
) -> ClusterSensitivity:
    """A-2.1, measured against the grid the candidates actually use.

    Phase 2's site diagnostic found 886 clusters over 50 m, 86 over 100 m, 4 over 200 m
    and none over 500 m. Those are the inputs; what Phase 4 adds is the comparison
    against H3 resolution 6.
    """
    reference = h3.latlng_to_cell(39.0, -98.0, resolution)   # geographic centre of the US
    area = cell_area_km2(reference)
    # A regular hexagon of area A has edge sqrt(2A / (3 sqrt 3)).
    edge_m = ((2 * area * 1_000_000) / (3 * 3 ** 0.5)) ** 0.5
    return ClusterSensitivity(
        resolution=resolution,
        cell_area_km2=area,
        approximate_cell_edge_m=edge_m,
        max_cluster_diameter_m=max_cluster_diameter_m,
        clusters_over_200m=clusters_over_200m,
        diameter_as_share_of_edge=max_cluster_diameter_m / edge_m,
        could_straddle_a_boundary=True,
    )


@dataclass(frozen=True)
class CentroidResolutionBenchmark:
    """A-2.3: how much does the allocation move between centroid resolutions?"""

    tracts: int
    block_groups: int
    tracts_spanning_multiple_cells: int
    demand_share_moved: float
    block_level_benchmark_available: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "assumption": "A-2.3",
            "tracts": self.tracts,
            "block_groups": self.block_groups,
            "tracts_spanning_multiple_cells": self.tracts_spanning_multiple_cells,
            "share_of_demand_placed_differently_by_tract_centroid": round(
                self.demand_share_moved, 6),
            "block_level_benchmark_available": self.block_level_benchmark_available,
            "interpretation": (
                "The block-level benchmark A-2.3 actually asks for remains unavailable: "
                "Phase 0 finding F-7 established that the Census publishes no "
                "block-level population-weighted centroid product. What is measurable "
                "is the step DOWN one resolution, from tract centroid to block group, "
                "and that moves a large share of demand - which is evidence that "
                "resolution matters here and that the finer weighting was the right "
                "choice, not evidence that block group is sufficient."
            ),
        }


def benchmark_centroid_resolution(
    points: Sequence[PopulationPoint],
    tract_demand: Mapping[str, float],
    resolution: int = RESOLUTION_NATIONAL,
) -> CentroidResolutionBenchmark:
    """A-2.3: compare block-group-weighted allocation against a tract-centroid one."""
    from pipeline.spatial.h3_grid import tract_cell_weights

    weights = tract_cell_weights(points, resolution)
    by_tract: dict[str, list[PopulationPoint]] = {}
    for point in points:
        by_tract.setdefault(point.tract_geoid, []).append(point)

    moved = 0.0
    total = 0.0
    for tract, members in by_tract.items():
        demand = float(tract_demand.get(tract, 0.0))
        total += demand
        if demand <= 0:
            continue
        population = sum(p.population for p in members)
        if population > 0:
            latitude = sum(p.latitude * p.population for p in members) / population
            longitude = sum(p.longitude * p.population for p in members) / population
        else:
            latitude = sum(p.latitude for p in members) / len(members)
            longitude = sum(p.longitude for p in members) / len(members)
        centroid_cell = str(h3.latlng_to_cell(latitude, longitude, resolution))
        # A tract-centroid assignment puts ALL the demand in one cell; the block-group
        # allocation puts only this share there. The difference is what moved.
        moved += demand * (1.0 - weights[tract].weights.get(centroid_cell, 0.0))

    return CentroidResolutionBenchmark(
        tracts=len(by_tract),
        block_groups=len(points),
        tracts_spanning_multiple_cells=sum(
            1 for w in weights.values() if len(w.weights) > 1),
        demand_share_moved=(moved / total if total > 0 else 0.0),
        block_level_benchmark_available=False,
    )


@dataclass(frozen=True)
class RoundingSensitivity:
    """A-3.4: can +/-50 in a rounded state total reorder a siting portfolio?"""

    budget: int
    baseline_sites: tuple[str, ...]
    perturbed_low_sites: tuple[str, ...]
    perturbed_high_sites: tuple[str, ...]
    rounding_half_width: float
    state_total: float

    @property
    def jaccard_low(self) -> float:
        return _jaccard(self.baseline_sites, self.perturbed_low_sites)

    @property
    def jaccard_high(self) -> float:
        return _jaccard(self.baseline_sites, self.perturbed_high_sites)

    def to_dict(self) -> dict[str, object]:
        return {
            "assumption": "A-3.4",
            "budget_sites": self.budget,
            "rounding_half_width_vehicles": self.rounding_half_width,
            "state_total_vehicles": self.state_total,
            "relative_perturbation": round(
                self.rounding_half_width / self.state_total, 8)
            if self.state_total else None,
            "portfolio_overlap_minus_50": round(self.jaccard_low, 6),
            "portfolio_overlap_plus_50": round(self.jaccard_high, 6),
            "identical_portfolio": (
                self.jaccard_low == 1.0 and self.jaccard_high == 1.0),
            "interpretation": (
                "Reconciliation scales every tract in a jurisdiction by the same factor, "
                "so a uniform change to that jurisdiction's total cannot reorder cells "
                "WITHIN it. It can only matter where a portfolio ranks cells ACROSS "
                "jurisdictions whose totals move by different relative amounts."
            ),
        }


def _jaccard(left: Sequence[str], right: Sequence[str]) -> float:
    a, b = set(left), set(right)
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def assess_rounding_sensitivity(
    cells: Sequence[HexCell],
    budget: int,
    state_total: float,
    half_width: float = 50.0,
) -> RoundingSensitivity:
    """A-3.4: re-run the greedy selection with the state total moved by +/- half_width."""
    from dataclasses import replace

    from pipeline.model.siting import build_candidates, greedy_select

    def portfolio(scale: float) -> tuple[str, ...]:
        scaled = [replace(cell, demand_bev=cell.demand_bev * scale) for cell in cells]
        candidates = build_candidates(scaled, saturation_ports_per_1k_demand=2.0)
        return greedy_select(candidates, budget).selected

    if state_total <= 0:
        raise ValueError("a rounding sensitivity needs a positive state total")
    return RoundingSensitivity(
        budget=budget,
        baseline_sites=portfolio(1.0),
        perturbed_low_sites=portfolio((state_total - half_width) / state_total),
        perturbed_high_sites=portfolio((state_total + half_width) / state_total),
        rounding_half_width=half_width,
        state_total=state_total,
    )


def assert_no_categorical_urban_rural(payload: Mapping[str, Any]) -> None:
    """A-3.5: population density must not become a categorical urban/rural truth.

    Density ships as a continuous feature because no keyless tract-level Census
    urban/rural classification was retrieved. Turning it into a category here would
    manufacture a classification the data does not support and present a threshold as a
    finding.
    """
    banned = {"urban", "rural", "urbanicity", "urban_rural", "is_urban", "is_rural",
              "urban_class", "rural_class"}
    found = sorted(key for key in payload if key.lower() in banned)
    if found:
        raise ValueError(
            f"A-3.5 violation: {found} turns population density into a categorical "
            "urban/rural truth. No keyless tract-level Census classification was "
            "retrieved, so the category would be manufactured."
        )
