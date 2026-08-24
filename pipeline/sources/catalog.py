"""The Phase 1 source catalogue: full retrieval, as opposed to Phase 0's bounded probes.

Phase 0's ``pipeline/discovery/registry.py`` deliberately fetches bounded samples so
that re-running source verification is cheap. Phase 1 needs whole sources, so the
retrieval definitions live here rather than being overloaded onto the probe specs.

Every entry names a source id that exists in ``SOURCES.yml``; a test asserts that.
Where Phase 0 measured a source's schema hash, the same hash must come back here, so a
silent upstream schema change fails the build rather than the model.
"""

from __future__ import annotations

from pathlib import Path

from pipeline.config.settings import PATHS
from pipeline.discovery.registry import (
    AFDC_BASE,
    AFDC_REGISTRATION_PAGE,
    AFDC_REGISTRATION_YEARS,
    ATLAS_BASE,
    ATLAS_STATES,
    CENPOP_BASE,
    USER_AGENT,
)
from pipeline.sources.base import (
    DelimitedSource,
    HtmlTableSource,
    JsonRecordsSource,
    NestedUnitsSource,
    Source,
)

# Raw filename -> canonical id, mirroring pipeline/discovery/seed_inventory.py.
# Raw names are preserved exactly as delivered; only the ids are shell-clean.
SEED_SOURCES: dict[str, str] = {
    "seed_afdc_stations_national_20241211": "alt_fuel_stations (Dec 11 2024).csv",
    "seed_afdc_stations_mn_20241210": "alt_fuel_stations (Dec 10 2024).csv",
    "seed_state_ev_registrations": "EV_Registration_Counts_by_State.csv",
    "seed_mn_county_ev_registrations": "County_EV_Registrations_Summary.csv",
    "seed_il_county_ev_monthly_panel": "county_ev_counts.csv",
    "seed_il_stations": "IL_StationsData.csv",
    "seed_mn_stations_simplified": "Simplified_EV_Charging_Stations.csv",
    "seed_iea_global_ev_2024": "IEA Global EV Data 2024.csv",
    "seed_ev_model_launch": "ev_launch_data.csv",
}

# The two-state fixture required by CLAUDE.md section 14. Minnesota and Illinois are
# the two states the delivered seed data covers at sub-state grain.
FIXTURE_STATES: tuple[str, ...] = ("MN", "IL")


def seed_sources() -> dict[str, Source]:
    """The ten frozen fixtures. Their expectations never drift with the live source."""
    return {
        source_id: DelimitedSource(source_id, path=PATHS.seed / filename)
        for source_id, filename in SEED_SOURCES.items()
    }


def afdc_sources(state: str | None = None) -> dict[str, Source]:
    """AFDC station and charging-unit retrieval.

    The JSON endpoint is used for charging units rather than the CSV export because
    Phase 1 measurement established that only the JSON carries a genuine unit-level
    ``port_count`` and the full eight-connector taxonomy; the CSV exposes five
    connector columns and station-level EVSE totals only. Both are the same source;
    this is a retrieval-path choice, not a different dataset.
    """
    params = {"fuel_type": "ELEC", "country": "US", "limit": "all"}
    if state:
        params = {**params, "state": state}
    return {
        "afdc_stations": JsonRecordsSource(
            "afdc_stations", f"{AFDC_BASE}.json", ("fuel_stations",), params
        ),
        "afdc_charging_units": NestedUnitsSource(
            "afdc_charging_units", f"{AFDC_BASE}.json", params
        ),
    }


def afdc_registration_sources() -> dict[str, Source]:
    """Ten annual state EV registration vintages, 2016 through 2025.

    Each page carries a published 'United States' total row. The adapter ingests it
    unchanged; domain rule G8 removes it in the intermediate layer (amendment A15).
    """
    return {
        f"afdc_state_ev_registrations_{year}": HtmlTableSource(
            f"afdc_state_ev_registrations_{year}",
            AFDC_REGISTRATION_PAGE,
            params={"year": str(year)},
            headers=dict(USER_AGENT),
            vintage=str(year),
        )
        for year in AFDC_REGISTRATION_YEARS
    }


def atlas_sources(states: tuple[str, ...] | None = None) -> dict[str, Source]:
    """Atlas EV Hub state DMV registrations: 11 states at ZIP grain, 3 at county."""
    # None means "every state"; an empty tuple means "none", which is not the same.
    wanted = {code for code, _, _ in ATLAS_STATES} if states is None else set(states)
    return {
        f"atlas_ev_registrations_{code.lower()}": DelimitedSource(
            f"atlas_ev_registrations_{code.lower()}",
            endpoint=f"{ATLAS_BASE}/{slug}.csv",
            headers=dict(USER_AGENT),
        )
        for code, slug, _grain in ATLAS_STATES
        if code in wanted
    }


def washington_source() -> dict[str, Source]:
    """The only natively tract-grain registration source found in Phase 0."""
    return {
        "wa_ev_population": JsonRecordsSource(
            "wa_ev_population",
            "https://data.wa.gov/resource/f6w7-q2d2.json",
            params={"$limit": "500000"},
        )
    }


def census_sources(state_fips: str = "27") -> dict[str, Source]:
    """Population-weighted centroids. CenPop publishes no block level (Phase 0 F-7)."""
    return {
        "census_cenpop_tract": DelimitedSource(
            "census_cenpop_tract",
            endpoint=f"{CENPOP_BASE}/tract/CenPop2020_Mean_TR{state_fips}.txt",
        ),
        "census_cenpop_blockgroup": DelimitedSource(
            "census_cenpop_blockgroup",
            endpoint=f"{CENPOP_BASE}/blkgrp/CenPop2020_Mean_BG{state_fips}.txt",
        ),
    }


def all_sources(state: str | None = None,
                atlas_states: tuple[str, ...] | None = None) -> dict[str, Source]:
    """Every Phase 1 source, keyed by the id it carries in SOURCES.yml."""
    catalogue: dict[str, Source] = {}
    catalogue.update(seed_sources())
    catalogue.update(afdc_sources(state))
    catalogue.update(afdc_registration_sources())
    catalogue.update(atlas_sources(atlas_states))
    catalogue.update(washington_source())
    catalogue.update(census_sources())
    return catalogue


def local_json_source(source_id: str, path: Path) -> Source:
    """Load a cached national AFDC pull from disk instead of the network."""
    if source_id == "afdc_charging_units":
        return NestedUnitsSource(source_id, "", path=path)
    return JsonRecordsSource(source_id, "", ("fuel_stations",), path=path)
