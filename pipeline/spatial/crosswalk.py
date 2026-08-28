"""Weighted allocation of registration counts between geographies.

CLAUDE.md section 7.5.1 (amendment A4): moving counts between geographies is a
**modelling and data-integration step with measurable error, not a one-to-one
lookup**. Every path through this module therefore:

1. names the source geography explicitly (never inferred from a column header);
2. names the crosswalk source and its vintage;
3. uses weighted allocation wherever the source does not nest inside the target;
4. preserves the transformation on every resulting row, via ``evidence_grain`` and
   ``estimate_method``;
5. leaves allocation *error measurement* to Phase 3, which has Washington's native
   tract data as the natural holdout for a round-trip test.

**A USPS ZIP Code is not a Census ZCTA.** Allocating a USPS-ZIP-keyed count to tracts
therefore takes two declared steps, not one: an approximate identity from USPS ZIP to
the like-numbered ZCTA, then a weighted split from ZCTA to tract. Both steps are
recorded on the output so neither can be mistaken for an exact lookup.

**Weight basis.** The shipped basis is land area, from the Census 2020 ZCTA-to-tract
relationship file, which is free and needs no registration. Land area is the *weakest
defensible* basis: it assumes population is uniform within a ZCTA, which section 7.6
says is badly wrong in large rural areas. It is used because it is the only free,
unauthenticated national weight available in Phase 1, it is declared on every row as
``allocation_weight_basis``, and Phase 3 measures the resulting error and may replace
it. See ``docs/LIMITATIONS.md``.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from pipeline.config.settings import PATHS
from pipeline.spatial.geography import (
    GeographyError,
    SourceGeography,
    estimate_method_for,
    evidence_grain_for,
    normalise_zip,
)

ZCTA_TRACT_RELATIONSHIP = PATHS.root / "data" / "cache" / "raw" / "zcta_tract_rel2020.txt"
ZCTA_TRACT_RELATIONSHIP_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/"
    "tab20_zcta520_tract20_natl.txt"
)
CROSSWALK_SOURCE = "census_zcta520_tract20_rel2020"
CROSSWALK_VINTAGE = "2020"


class WeightBasis(StrEnum):
    """What the allocation weights represent. Always recorded on the output."""

    LAND_AREA = "land_area"
    POPULATION = "population"
    HOUSING_UNITS = "housing_units"
    ADDRESS_COUNT = "address_count"


@dataclass(frozen=True)
class AllocationLink:
    """One weighted edge from a source geography to a target tract."""

    source_geography_type: str
    source_geography_id: str
    tract_geoid: str
    weight: float
    weight_basis: str


@dataclass(frozen=True)
class AllocatedValue:
    """A count allocated onto a tract, carrying its full transformation provenance."""

    tract_geoid: str
    value: float
    source_geography_type: str
    source_geography_id: str
    evidence_grain: str
    estimate_method: str
    crosswalk_source: str
    crosswalk_vintage: str
    allocation_weight_basis: str
    allocation_weight: float

    def to_dict(self) -> dict[str, object]:
        return {
            "tract_geoid": self.tract_geoid,
            "value": self.value,
            "source_geography_type": self.source_geography_type,
            "source_geography_id": self.source_geography_id,
            "evidence_grain": self.evidence_grain,
            "estimate_method": self.estimate_method,
            "crosswalk_source": self.crosswalk_source,
            "crosswalk_vintage": self.crosswalk_vintage,
            "allocation_weight_basis": self.allocation_weight_basis,
            "allocation_weight": round(self.allocation_weight, 9),
        }


def load_zcta_tract_links(
    path: Path | None = None,
    basis: WeightBasis = WeightBasis.LAND_AREA,
) -> dict[str, list[AllocationLink]]:
    """Build normalised ZCTA -> tract weights from the Census relationship file.

    Rows whose ZCTA is blank are tract-only records (a tract intersecting no ZCTA) and
    carry no ZCTA to allocate from; they are skipped, which loses nothing.
    """
    reference = path or ZCTA_TRACT_RELATIONSHIP
    if not reference.exists():
        raise GeographyError(
            f"ZCTA-to-tract crosswalk missing at {reference}. Fetch it from "
            f"{ZCTA_TRACT_RELATIONSHIP_URL}. No ZIP-keyed source may be allocated to "
            "tracts without a named, versioned crosswalk (CLAUDE.md 7.5.1)."
        )
    raw: dict[str, list[tuple[str, float]]] = {}
    with reference.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="|"):
            zcta = (row.get("GEOID_ZCTA5_20") or "").strip()
            tract = (row.get("GEOID_TRACT_20") or "").strip()
            if not zcta or not tract:
                continue
            try:
                area = float(row.get("AREALAND_PART") or 0.0)
            except ValueError:  # pragma: no cover - defensive
                area = 0.0
            raw.setdefault(zcta, []).append((tract, area))

    links: dict[str, list[AllocationLink]] = {}
    for zcta, parts in raw.items():
        total = sum(area for _, area in parts)
        if total <= 0:
            # Zero land area across every part: fall back to an equal split rather
            # than dropping the ZCTA, and the basis still says what happened.
            share = 1.0 / len(parts)
            weights = [(tract, share) for tract, _ in parts]
        else:
            weights = [(tract, area / total) for tract, area in parts]
        links[zcta] = [
            AllocationLink(SourceGeography.ZCTA.value, zcta, tract, weight, basis.value)
            for tract, weight in sorted(weights)
        ]
    return links


def zip_to_zcta(zip_code: str, known_zctas: Mapping[str, object]) -> str:
    """Approximate a USPS ZIP Code by the like-numbered ZCTA.

    This is an **approximation, not an identity**. A USPS ZIP Code is a collection of
    mail-delivery routes; a ZCTA is an area built from census blocks. Many ZIPs have a
    same-numbered ZCTA, but point ZIPs (single large recipients) and PO-Box-only ZIPs
    have none, and the boundaries never match exactly. The step is isolated here so it
    is visible, and it raises rather than silently returning nothing.
    """
    code = normalise_zip(zip_code)
    if code not in known_zctas:
        raise GeographyError(
            f"USPS ZIP {code} has no like-numbered ZCTA. It is probably a point or "
            "PO-Box ZIP with no areal equivalent; it cannot be allocated to tracts "
            "and must be reported as unallocatable rather than dropped."
        )
    return code


def allocate(
    source_geography: SourceGeography,
    source_id: str,
    value: float,
    links: Mapping[str, Sequence[AllocationLink]],
    crosswalk_source: str = CROSSWALK_SOURCE,
    crosswalk_vintage: str = CROSSWALK_VINTAGE,
) -> list[AllocatedValue]:
    """Allocate one value onto tracts, stamping full provenance on every output row.

    A tract-keyed source is passed through unweighted and is the only case that earns
    ``directly_observed``. Everything else is ``crosswalked``.
    """
    grain = evidence_grain_for(source_geography)
    method = estimate_method_for(source_geography)

    if source_geography is SourceGeography.TRACT:
        return [
            AllocatedValue(
                tract_geoid=source_id, value=value,
                source_geography_type=source_geography.value, source_geography_id=source_id,
                evidence_grain=grain.value, estimate_method=method.value,
                crosswalk_source="none", crosswalk_vintage="not applicable",
                allocation_weight_basis="none", allocation_weight=1.0,
            )
        ]

    key = zip_to_zcta(source_id, links) if source_geography in (
        SourceGeography.USPS_ZIP, SourceGeography.ZCTA) else source_id
    edges = links.get(key)
    if not edges:
        raise GeographyError(f"no crosswalk edges for {source_geography.value} {source_id}")

    return [
        AllocatedValue(
            tract_geoid=edge.tract_geoid,
            value=value * edge.weight,
            source_geography_type=source_geography.value,
            source_geography_id=source_id,
            evidence_grain=grain.value,
            estimate_method=method.value,
            crosswalk_source=crosswalk_source,
            crosswalk_vintage=crosswalk_vintage,
            allocation_weight_basis=edge.weight_basis,
            allocation_weight=edge.weight,
        )
        for edge in edges
    ]


def allocate_many(
    records: Iterable[tuple[SourceGeography, str, float]],
    links: Mapping[str, Sequence[AllocationLink]],
) -> tuple[list[AllocatedValue], list[tuple[str, str]]]:
    """Allocate many records, returning (allocated, unallocatable).

    Unallocatable records are RETURNED, never dropped: a ZIP with no areal equivalent
    is a reportable fact, not something to make disappear (directive D8).
    """
    allocated: list[AllocatedValue] = []
    unallocatable: list[tuple[str, str]] = []
    for geography, source_id, value in records:
        try:
            allocated.extend(allocate(geography, source_id, value, links))
        except GeographyError as exc:
            unallocatable.append((source_id, str(exc)))
    return allocated, unallocatable


def conservation_error(allocated: Sequence[AllocatedValue], expected_total: float) -> float:
    """Allocation must conserve mass. Returns the absolute difference."""
    return abs(sum(a.value for a in allocated) - expected_total)


def zcta_state_index(path: Path | None = None) -> dict[str, frozenset[str]]:
    """ZCTA -> the set of state FIPS codes it intersects.

    Needed because a state DMV export can carry an **out-of-state mailing ZIP Code**.
    Oregon's export, for example, contains ZIPs 00907 (Puerto Rico), 01742
    (Massachusetts) and 10010 (Manhattan), each holding a handful of vehicles. Matching
    those to their like-numbered ZCTA pulls the households of a distant area into the
    state's panel: for Oregon that was 3.5 million households, 62% of the state's
    matched exposure, attached to ZIPs holding 378 vehicles between them.

    A ZCTA's state membership is read from the tract GEOIDs it intersects, whose first
    two digits are the state FIPS. 137 of 33,791 ZCTAs genuinely span more than one
    state, so membership is a set rather than a single value.
    """
    reference = path or ZCTA_TRACT_RELATIONSHIP
    if not reference.exists():
        raise GeographyError(
            f"ZCTA-to-tract crosswalk missing at {reference}. Without it an "
            "out-of-state mailing ZIP cannot be told from a local one, and the "
            "difference is large enough to change every published estimate."
        )
    states: dict[str, set[str]] = {}
    with reference.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="|"):
            zcta = (row.get("GEOID_ZCTA5_20") or "").strip()
            tract = (row.get("GEOID_TRACT_20") or "").strip()
            if zcta and len(tract) == 11:
                states.setdefault(zcta, set()).add(tract[:2])
    if not states:
        raise GeographyError(f"{reference} parsed to zero ZCTA-state links")
    return {zcta: frozenset(codes) for zcta, codes in states.items()}
