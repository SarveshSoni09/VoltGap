"""Geography identification: what kind of area a source is actually keyed by.

CLAUDE.md section 7.5.1 (amendment A4) requires the source geography to be **declared
explicitly per source and never inferred from column naming**, because the distinction
that matters most is invisible in a column header:

* a **USPS ZIP Code** is a mail-delivery route collection, not an area at all;
* a **Census ZCTA** is an approximating *area* built from census blocks.

They are not interchangeable and must never be silently equated. A column called
``ZIP`` may hold either.

Domain rule G13 is the other reason this module exists: county names collide across
states. Both Minnesota and Illinois have a Cook County, and their county codes are
even the same three digits (031) — only the state prefix separates 17031 from 27031.
Joining on name, or on a bare county code, silently merges them.
"""

from __future__ import annotations

import csv
import functools
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path

from pipeline.config.settings import PATHS

COUNTY_REFERENCE = PATHS.root / "data" / "cache" / "raw" / "national_county2020.txt"
COUNTY_REFERENCE_URL = (
    "https://www2.census.gov/geo/docs/reference/codes2020/national_county2020.txt"
)


class SourceGeography(StrEnum):
    """The geography a source is keyed by. Declared, never inferred."""

    USPS_ZIP = "usps_zip"
    ZCTA = "zcta"
    COUNTY = "county"
    TRACT = "tract"
    STATE = "state"


class EvidenceGrain(StrEnum):
    """The finest observed registration evidence supporting a tract value (7.4.1)."""

    NATIVE_TRACT = "native_tract"
    ZIP_ANCHORED = "zip_anchored"
    COUNTY_ANCHORED = "county_anchored"
    STATE_TOTAL_ONLY = "state_total_only"


class EstimateMethod(StrEnum):
    """What was done to produce a tract value (7.4.1). Never collapsed with grain."""

    DIRECTLY_OBSERVED = "directly_observed"
    CROSSWALKED = "crosswalked"
    MODELED = "modeled"
    MODELED_HIGH_UNCERTAINTY = "modeled_high_uncertainty"


# The grain a source geography can support once allocated to tracts. Note that
# USPS_ZIP and ZCTA both land on ZIP_ANCHORED and never on NATIVE_TRACT: a tract value
# derived from either is anchored to observed data but is not itself observed.
GRAIN_FOR_SOURCE: Mapping[SourceGeography, EvidenceGrain] = {
    SourceGeography.TRACT: EvidenceGrain.NATIVE_TRACT,
    SourceGeography.USPS_ZIP: EvidenceGrain.ZIP_ANCHORED,
    SourceGeography.ZCTA: EvidenceGrain.ZIP_ANCHORED,
    SourceGeography.COUNTY: EvidenceGrain.COUNTY_ANCHORED,
    SourceGeography.STATE: EvidenceGrain.STATE_TOTAL_ONLY,
}


class GeographyError(ValueError):
    """A geography could not be resolved. Never resolved by guessing."""


def evidence_grain_for(source: SourceGeography) -> EvidenceGrain:
    return GRAIN_FOR_SOURCE[source]


def estimate_method_for(source: SourceGeography,
                        target: SourceGeography = SourceGeography.TRACT) -> EstimateMethod:
    """``directly_observed`` only when the source reports the target geography itself.

    This is the rule that stops a ZIP- or county-derived tract value being labelled
    directly observed, which CLAUDE.md 7.4.1 forbids and the Phase 1 gate tests.
    """
    return (EstimateMethod.DIRECTLY_OBSERVED if source == target
            else EstimateMethod.CROSSWALKED)


@functools.lru_cache(maxsize=1)
def county_fips_lookup(path: Path | None = None) -> dict[tuple[str, str], str]:
    """``(state postal code, county name) -> 5-digit county FIPS``.

    Keyed by state *and* name precisely because names are not unique (G13).
    """
    reference = path or COUNTY_REFERENCE
    if not reference.exists():
        raise GeographyError(
            f"county FIPS reference missing at {reference}. Fetch it from "
            f"{COUNTY_REFERENCE_URL}; no county join may proceed without it, and "
            "names must never be used as a join key (domain rule G13)."
        )
    lookup: dict[tuple[str, str], str] = {}
    with reference.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="|"):
            state = (row.get("STATE") or "").strip()
            name = (row.get("COUNTYNAME") or "").strip()
            statefp = (row.get("STATEFP") or "").strip()
            countyfp = (row.get("COUNTYFP") or "").strip()
            if state and name and statefp and countyfp:
                lookup[(state, name)] = f"{statefp}{countyfp}"
    if not lookup:
        raise GeographyError(f"{reference} parsed to zero counties")
    return lookup


def resolve_county_fips(state: str, county_name: str,
                        lookup: Mapping[tuple[str, str], str] | None = None) -> str:
    """Resolve a county to FIPS. Raises rather than guessing (G13)."""
    table = lookup if lookup is not None else county_fips_lookup()
    key = (state.strip().upper(), county_name.strip())
    if key in table:
        return table[key]
    # Accept a missing "County" suffix, which several state DMV exports omit, but
    # never accept a name without its state.
    suffixed = (key[0], f"{key[1]} County")
    if suffixed in table:
        return table[suffixed]
    raise GeographyError(
        f"no county FIPS for {county_name!r} in {state!r}. County names collide "
        "across states (G13), so the join must resolve exactly or fail."
    )


def normalise_zip(value: str) -> str:
    """Five-digit ZIP text, preserving leading zeros. Does NOT convert to a ZCTA."""
    digits = "".join(c for c in str(value) if c.isdigit())
    if len(digits) < 5:
        raise GeographyError(f"{value!r} is not a 5-digit ZIP code")
    return digits[:5]
