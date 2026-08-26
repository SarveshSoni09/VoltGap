"""Access model: DCFC and Level 2 access gaps, with threshold sensitivity.

CLAUDE.md 7.5. Four rules govern this module and each is enforced in code:

1. **Population-weighted points, never tract geometric centroids.** In large rural
   tracts the population often occupies one corner, so a geometric centroid can sit
   tens of kilometres from every resident.
2. **DCFC and Level 2 are computed and reported separately.** They answer different
   questions and their thresholds differ.
3. **The metric is named for what it measures.** A DCFC-only measure is a **DCFC
   access gap**, never a "charging desert" (copy-lint: allow) - that word would
   imply Level 2 was considered, and it was not.
4. **A single threshold never ships without its sensitivity curve.** Choosing 16.1 km
   is a reporting decision, not a finding, and presenting it alone would disguise one
   as the other.

Distances are straight-line (§7.5), so a reported gap is a **lower bound**: real travel
distance is never shorter than great-circle distance, so the population genuinely
beyond a drive threshold is at least as large as reported here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from pipeline.spatial.allocation import PopulationPoint
from pipeline.spatial.distance import nearest_site_distances

THRESHOLDS_CONFIG = Path(__file__).resolve().parents[1] / "config" / "thresholds.yml"
METRES_PER_KM = 1000.0


class AccessConfigError(ValueError):
    """The access configuration is missing or malformed."""


@dataclass(frozen=True)
class AccessThresholds:
    """Configured thresholds. No magic numbers in Python (CLAUDE.md 2)."""

    dcfc_gap_km: float
    l2_gap_km: float
    sensitivity_km: tuple[float, ...]
    dcfc_levels: frozenset[str]
    l2_levels: frozenset[str]
    operational_status_codes: frozenset[str]
    public_access_codes: frozenset[str]


def load_thresholds(path: Path | None = None) -> AccessThresholds:
    source = path or THRESHOLDS_CONFIG
    if not source.exists():
        raise AccessConfigError(f"thresholds configuration missing at {source}")
    document = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    access = document.get("access")
    supply = document.get("supply")
    if not access or not supply:
        raise AccessConfigError(f"{source} must declare both 'access' and 'supply'")
    sweep = access["sensitivity_km"]
    start, stop, step = float(sweep["start"]), float(sweep["stop"]), float(sweep["step"])
    if step <= 0 or stop <= start:
        raise AccessConfigError(f"{source}: sensitivity range is empty or non-advancing")
    values: list[float] = []
    current = start
    while current <= stop + 1e-9:
        values.append(round(current, 6))
        current += step
    return AccessThresholds(
        dcfc_gap_km=float(access["dcfc_gap_km"]),
        l2_gap_km=float(access["l2_gap_km"]),
        sensitivity_km=tuple(values),
        dcfc_levels=frozenset(str(x) for x in supply["dcfc_levels"]),
        l2_levels=frozenset(str(x) for x in supply["l2_levels"]),
        operational_status_codes=frozenset(str(x) for x in supply["operational_status_codes"]),
        public_access_codes=frozenset(str(x) for x in supply["public_access_codes"]),
    )


@dataclass(frozen=True)
class AccessResult:
    """Access measured for one supply class, at one threshold, plus its full curve."""

    supply_class: str
    threshold_km: float
    population_total: int
    population_in_gap: int
    points_total: int
    points_in_gap: int
    sites_considered: int
    median_distance_km: float
    sensitivity_curve: tuple[tuple[float, int], ...]

    @property
    def share_in_gap(self) -> float:
        return self.population_in_gap / self.population_total if self.population_total else 0.0

    @property
    def metric_name(self) -> str:
        """Named for what it measures, never as a desert.  copy-lint: allow"""
        return f"{self.supply_class} access gap"

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_name": self.metric_name,
            "supply_class": self.supply_class,
            "threshold_km": self.threshold_km,
            "population_total": self.population_total,
            "population_in_gap": self.population_in_gap,
            "share_in_gap": round(self.share_in_gap, 6),
            "points_total": self.points_total,
            "points_in_gap": self.points_in_gap,
            "sites_considered": self.sites_considered,
            "median_distance_km": round(self.median_distance_km, 4),
            "sensitivity_curve": [
                {"threshold_km": km, "population_in_gap": pop}
                for km, pop in self.sensitivity_curve
            ],
            "distance_basis": "straight_line_haversine",
            "interpretation": (
                "Straight-line distance understates real travel distance, so this "
                "population is a LOWER BOUND on the population genuinely beyond the "
                "threshold by road."
            ),
        }


def qualifying_sites(
    sites: Sequence[Mapping[str, Any]],
    levels: frozenset[str],
    thresholds: AccessThresholds,
) -> list[Mapping[str, Any]]:
    """Public operational sites offering at least one port at the required level.

    Applies domain rules G2 (status) and G3 (access). Charging level is read from the
    site's own level breakdown, never inferred from a connector name (CLAUDE.md 7.1.2).
    """
    selected = []
    for site in sites:
        if str(site.get("status_code", "")) not in thresholds.operational_status_codes:
            continue
        if str(site.get("access_code", "")) not in thresholds.public_access_codes:
            continue
        ports = site.get("ports_by_level") or {}
        if any(int(ports.get(level, 0) or 0) > 0 for level in levels):
            selected.append(site)
    return selected


def compute_access(
    population_points: Sequence[PopulationPoint],
    sites: Sequence[Mapping[str, Any]],
    thresholds: AccessThresholds,
    supply_class: str = "DCFC",
) -> AccessResult:
    """Measure the access gap for one supply class, with its sensitivity curve.

    ``sites`` must already be filtered to the relevant level by
    :func:`qualifying_sites`; this function does not re-derive eligibility, so the
    caller's choice of supply class is explicit and auditable.
    """
    levels = (thresholds.dcfc_levels if supply_class == "DCFC" else thresholds.l2_levels)
    threshold_km = (thresholds.dcfc_gap_km if supply_class == "DCFC"
                    else thresholds.l2_gap_km)
    _ = levels  # eligibility already applied by the caller; kept for signature clarity

    result = nearest_site_distances(
        [p.latitude for p in population_points],
        [p.longitude for p in population_points],
        [float(s["latitude"]) for s in sites],
        [float(s["longitude"]) for s in sites],
    )
    distances_km = [m / METRES_PER_KM for m in result.distances_m]
    populations = [p.population for p in population_points]
    total_population = sum(populations)

    curve: list[tuple[float, int]] = []
    for km in thresholds.sensitivity_km:
        curve.append((km, sum(pop for pop, d in zip(populations, distances_km, strict=True)
                              if d > km)))

    in_gap = sum(pop for pop, d in zip(populations, distances_km, strict=True)
                 if d > threshold_km)
    points_in_gap = sum(1 for d in distances_km if d > threshold_km)
    finite = sorted(d for d in distances_km if d != float("inf"))
    median = finite[len(finite) // 2] if finite else float("inf")

    return AccessResult(
        supply_class=supply_class,
        threshold_km=threshold_km,
        population_total=total_population,
        population_in_gap=in_gap,
        points_total=len(population_points),
        points_in_gap=points_in_gap,
        sites_considered=len(sites),
        median_distance_km=median,
        sensitivity_curve=tuple(curve),
    )
