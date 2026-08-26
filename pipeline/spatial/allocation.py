"""Population-weighted allocation of tract quantities to target cells.

CLAUDE.md 7.6: allocate using **block-level population weights, not area weights**.
Area-weighted apportionment assumes uniform population within a tract, which is badly
wrong in large rural tracts, where the population often occupies one corner while the
tract itself spans hundreds of square kilometres.

This module deliberately does not know what a target cell is. It allocates from a
source geography to whatever target the caller assigns each population point to — an
H3 cell, a county, a distance band. That keeps the population weighting testable
against a hand-computed fixture without dragging in a gridding dependency.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any


class AllocationError(ValueError):
    """Allocation could not proceed. Never resolved by guessing a weight."""


@dataclass(frozen=True)
class PopulationPoint:
    """One population-weighted point inside a source geography."""

    point_id: str
    source_geoid: str
    population: int
    latitude: float
    longitude: float


@dataclass(frozen=True)
class AllocatedQuantity:
    """A source quantity allocated onto a target cell, with its weight preserved."""

    target_id: str
    source_geoid: str
    value: float
    weight: float
    weight_basis: str
    population: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id, "source_geoid": self.source_geoid,
            "value": self.value, "weight": round(self.weight, 9),
            "weight_basis": self.weight_basis, "population": self.population,
        }


def population_weights(points: Sequence[PopulationPoint]) -> dict[str, float]:
    """Normalised weights within one source geography, keyed by point id.

    A geography whose points all report zero population cannot be population-weighted.
    That is reported by raising, not papered over with an equal split, because an equal
    split would silently reintroduce the uniform-density assumption this module exists
    to avoid.
    """
    total = sum(p.population for p in points)
    if total <= 0:
        raise AllocationError(
            f"source geography {points[0].source_geoid if points else '?'} has zero "
            "total population across its points; it cannot be population-weighted. "
            "Report it as unallocatable rather than substituting an equal split."
        )
    return {p.point_id: p.population / total for p in points}


def allocate_by_population(
    source_geoid: str,
    value: float,
    points: Sequence[PopulationPoint],
    target_of: Mapping[str, str],
) -> list[AllocatedQuantity]:
    """Split ``value`` across target cells in proportion to point population.

    ``target_of`` maps each point id to its target cell. Points sharing a target are
    combined, so a tract contributing three population points to one hex yields one
    allocation row for that hex.
    """
    if not points:
        raise AllocationError(f"source geography {source_geoid} has no population points")
    weights = population_weights(points)
    combined: dict[str, tuple[float, int]] = {}
    for point in points:
        target = target_of.get(point.point_id)
        if target is None:
            raise AllocationError(
                f"population point {point.point_id} has no target cell; assigning it "
                "to a default would fabricate a location"
            )
        weight, population = combined.get(target, (0.0, 0))
        combined[target] = (weight + weights[point.point_id], population + point.population)
    return [
        AllocatedQuantity(target_id=target, source_geoid=source_geoid,
                          value=value * weight, weight=weight,
                          weight_basis="population", population=population)
        for target, (weight, population) in sorted(combined.items())
    ]


def allocate_many(
    quantities: Iterable[tuple[str, float]],
    points_by_geoid: Mapping[str, Sequence[PopulationPoint]],
    target_of: Mapping[str, str],
) -> tuple[list[AllocatedQuantity], list[tuple[str, str]]]:
    """Allocate many source quantities, returning (allocated, unallocatable).

    Unallocatable sources are returned rather than dropped (directive D8).
    """
    allocated: list[AllocatedQuantity] = []
    unallocatable: list[tuple[str, str]] = []
    for geoid, value in quantities:
        points = points_by_geoid.get(geoid, ())
        try:
            allocated.extend(allocate_by_population(geoid, value, points, target_of))
        except AllocationError as exc:
            unallocatable.append((geoid, str(exc)))
    return allocated, unallocatable


def conservation_error(allocated: Sequence[AllocatedQuantity], expected: float) -> float:
    """Allocation must conserve mass."""
    return abs(sum(a.value for a in allocated) - expected)
