"""Declarative probe specifications: what to fetch, and how to measure what comes back.

Every entry here was verified to resolve during Phase 0 discovery; nothing is assumed.
Sources that turned out to be unreachable or key-gated are still listed, because
recording an explicit failure is the point (directive D8: degrade explicitly, never
substitute a plausible default silently).

Probes are deliberately *bounded*. Where a source is enormous (the Atlas EV Hub state
files reach 1.3 GB, the national AFDC charging-units export is 111 MB) the probe takes
a Range-limited or state-scoped slice, so re-running Phase 0 costs almost nothing and
the recorded fixtures stay small enough to version.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pipeline.config.settings import PATHS

AFDC_BASE = "https://developer.nlr.gov/api/alt-fuel-stations/v1"
AFDC_REGISTRATION_PAGE = "https://afdc.energy.gov/vehicle-registration"
ATLAS_BASE = "https://www.atlasevhub.com/public/dmv"
CENPOP_BASE = "https://www2.census.gov/geo/docs/reference/cenpop2020"
CENPOP_2010_BASE = "https://www2.census.gov/geo/docs/reference/cenpop2010"
ACS_SUMMARY_BASE = (
    "https://www2.census.gov/programs-surveys/acs/summary_file/2023/table-based-SF/data/5YRData"
)

# 64 KiB is enough to capture a CSV header plus several hundred data rows, which is
# all a schema/missingness probe needs from a multi-hundred-megabyte file.
#
# The Range header is still sent as a courtesy, but it is NOT what bounds the
# transfer: several of these hosts advertise byte ranges and then ignore the header,
# answering 200 with the entire file (the Atlas EV Hub New York export is 1.3 GB).
# The real bound is max_bytes, applied by the fetcher while streaming.
SAMPLE_BYTES = 65536
PROBE_BYTES = 1024
RANGE_64K = {"Range": f"bytes=0-{SAMPLE_BYTES - 1}"}
RANGE_1K = {"Range": f"bytes=0-{PROBE_BYTES - 1}"}
USER_AGENT = {"User-Agent": "VoltGap-Phase0-Probe (+https://github.com/voltgap)"}

# Atlas EV Hub state files. Granularity confirmed by reading each file's header row.
# 11 states publish ZIP Code, 3 publish County.
ATLAS_STATES: tuple[tuple[str, str, str], ...] = (
    ("CO", "CO_EV_Registrations_03", "zip"),
    ("CT", "CT_EV_Registrations_12", "zip"),
    ("ME", "ME_EV_Registrations_01", "zip"),
    ("MN", "MN_EV_Registrations_01", "zip"),
    ("MT", "MT_EV_Registrations_01", "county"),
    ("NC", "NC_EV_Registrations", "zip"),
    ("NJ", "NJ_EV_Registrations_12", "zip"),
    ("NM", "NM_EV_Registrations_07_2026", "zip"),
    ("NY", "NY_EV_Registrations_03", "zip"),
    ("OR", "OR_EV_Registrations_02", "zip"),
    ("TN", "TN_EV_Registrations_01", "county"),
    ("TX", "TX_EV_Registrations_03", "zip"),
    ("VA", "VA_EV_Registrations_07_2026", "county"),
    ("VT", "VT_EV_Registrations_01", "zip"),
)

AFDC_REGISTRATION_YEARS: tuple[int, ...] = (2016, 2017, 2018, 2019, 2020, 2021, 2022,
                                            2023, 2024, 2025)


@dataclass(frozen=True)
class ProbeSpec:
    """One bounded observation of one source."""

    source_id: str
    # rest_json | remote_csv | remote_html_table | availability | local_csv | local_geojson
    kind: str
    url: str = ""
    params: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    record_path: tuple[str, ...] = ()
    max_rows: int | None = None
    delimiter: str = ","
    local_path: Path | None = None
    max_bytes: int | None = None
    needs_api_key: str = ""  # ApiKeys attribute sent as an api_key query parameter
    needs_bearer: str = ""   # ApiKeys attribute sent as an Authorization Bearer header
    vintage_pointer: tuple[str, ...] = ()  # key path into a JSON body holding the vintage
    note: str = ""


def _afdc() -> list[ProbeSpec]:
    return [
        ProbeSpec(
            source_id="afdc_stations",
            kind="rest_json",
            url=f"{AFDC_BASE}.json",
            params={"fuel_type": "ELEC", "country": "US", "limit": "200"},
            record_path=("fuel_stations",),
            needs_api_key="nrel",
            note="Station-grain records (domain rule G1: a row is a site of one "
                 "network's presence, never a capacity count).",
        ),
        ProbeSpec(
            source_id="afdc_last_updated",
            kind="rest_json",
            url=f"{AFDC_BASE}/last-updated.json",
            needs_api_key="nrel",
            vintage_pointer=("last_updated",),
            note="Establishes the vintage of the current AFDC snapshot.",
        ),
        ProbeSpec(
            source_id="afdc_charging_units",
            kind="nested_json_units",
            url=f"{AFDC_BASE}.json",
            params={"fuel_type": "ELEC", "state": "MN", "limit": "all"},
            needs_api_key="nrel",
            note="One row per charging unit, from the PRIMARY JSON representation "
                 "(amendment A23). Minnesota-scoped bounded sample. The CSV export is "
                 "the documented fallback and exposes five connector standards against "
                 "eight here, with station-level rather than unit-level EVSE counts.",
        ),
        ProbeSpec(
            source_id="afdc_charging_units_csv_fallback",
            kind="remote_csv",
            url=f"{AFDC_BASE}/ev-charging-units.csv",
            params={"fuel_type": "ELEC", "state": "MN", "limit": "all"},
            needs_api_key="nrel",
            note="The documented CSV fallback representation, probed so its schema "
                 "and limitations stay verified rather than assumed.",
        ),
    ]


def _afdc_registrations() -> list[ProbeSpec]:
    return [
        ProbeSpec(
            source_id=f"afdc_state_ev_registrations_{year}",
            kind="remote_html_table",
            url=AFDC_REGISTRATION_PAGE,
            params={"year": str(year)},
            headers=dict(USER_AGENT),
            note=f"State-level EV registration stock, {year} vintage. Counts are "
                 "rounded to the nearest 100. Includes a 'United States' total row "
                 "that must be excluded before aggregation (domain rule G8).",
        )
        for year in AFDC_REGISTRATION_YEARS
    ]


def _atlas() -> list[ProbeSpec]:
    return [
        ProbeSpec(
            source_id=f"atlas_ev_registrations_{code.lower()}",
            kind="remote_csv",
            url=f"{ATLAS_BASE}/{slug}.csv",
            headers={**RANGE_64K, **USER_AGENT},
            max_bytes=SAMPLE_BYTES,
            note=f"{code} DMV EV registrations at {grain} granularity. Vehicle-grain "
                 "rows carrying Registration Date and a DMV Snapshot series, so "
                 "sub-state historical vintages are reconstructable.",
        )
        for code, slug, grain in ATLAS_STATES
    ]


def _census() -> list[ProbeSpec]:
    return [
        ProbeSpec(
            source_id="census_acs_api",
            kind="rest_json",
            url="https://api.census.gov/data/2023/acs/acs5",
            params={"get": "NAME,B25003_001E", "for": "state:27"},
            needs_api_key="census",
            note="API path. Now returns a 'Missing Key' HTML page without a key; the "
                 "keyless bulk summary file is the primary retrieval path instead.",
        ),
        ProbeSpec(
            source_id="census_acs_bulk",
            kind="remote_csv",
            url=f"{ACS_SUMMARY_BASE}/acsdt5y2023-b25003.dat",
            headers=dict(RANGE_64K),
            max_bytes=SAMPLE_BYTES,
            delimiter="|",
            note="ACS 2023 5-year table-based summary file, pipe-delimited, no key "
                 "required. B25003 (housing tenure) probed as the representative table.",
        ),
        ProbeSpec(
            source_id="census_tiger_tracts",
            kind="availability",
            url="https://www2.census.gov/geo/tiger/TIGER2023/TRACT/tl_2023_27_tract.zip",
            headers=dict(RANGE_1K),
            max_bytes=PROBE_BYTES,
            note="TIGER/Line tract geometry, per state. Minnesota probed.",
        ),
        ProbeSpec(
            source_id="census_tiger_blocks",
            kind="availability",
            url="https://www2.census.gov/geo/tiger/TIGER2023/TABBLOCK20/"
                "tl_2023_27_tabblock20.zip",
            headers=dict(RANGE_1K),
            max_bytes=PROBE_BYTES,
            note="TIGER/Line 2020 blocks with INTPTLAT/INTPTLON internal points. "
                 "Required for genuine block-grain allocation because the Census "
                 "publishes no PREBUILT block-grain population-weighted centroid "
                 "file. The block inputs themselves exist: this geometry plus P.L. "
                 "94-171 block population counts.",
        ),
        ProbeSpec(
            source_id="census_tiger_prisecroads",
            kind="availability",
            url="https://www2.census.gov/geo/tiger/TIGER2024/PRISECROADS/"
                "tl_2024_53_prisecroads.zip",
            headers=dict(RANGE_1K),
            max_bytes=PROBE_BYTES,
            note="TIGER/Line primary (MTFCC S1100) and secondary (S1200) roads, per "
                 "state. Washington probed. The Core source for the CLAUDE.md section "
                 "7.8 candidate road-proximity filter.",
        ),
        ProbeSpec(
            source_id="census_cenpop_tract",
            kind="remote_csv",
            url=f"{CENPOP_BASE}/tract/CenPop2020_Mean_TR27.txt",
            note="Population-weighted tract centroids, Minnesota.",
        ),
        ProbeSpec(
            source_id="census_cenpop_blockgroup",
            kind="remote_csv",
            url=f"{CENPOP_BASE}/blkgrp/CenPop2020_Mean_BG27.txt",
            note="Population-weighted block-group centroids, Minnesota. The finest "
                 "ready-made population-weighted centroid the Census Bureau publishes.",
        ),
        ProbeSpec(
            source_id="census_cenpop_blockgroup_2010",
            kind="remote_csv",
            url=f"{CENPOP_2010_BASE}/blkgrp/CenPop2010_Mean_BG27.txt",
            params={"product": "cenpop2010_blkgrp"},
            note="Population-weighted block-group centroids on 2010 census geography, "
                 "Minnesota. Retrieved for Phase 5: every rolling origin resolves to an "
                 "ACS release published on 2010 tract boundaries. The inert 'product' "
                 "parameter defeats a Census firewall rule that rejects the bare URL "
                 "for Oklahoma; it is a request parameter rather than an inline query "
                 "because httpx replaces a URL's query when params are supplied.",
        ),
        ProbeSpec(
            source_id="census_cenpop_block",
            kind="availability",
            url=f"{CENPOP_BASE}/block/CenPop2020_Mean_BLK27.txt",
            note="Probed to establish absence. Expected to 404: CenPop2020 publishes "
                 "county, tract and block group only.",
        ),
        ProbeSpec(
            source_id="census_pl94171_blocks",
            kind="availability",
            url="https://www2.census.gov/programs-surveys/decennial/2020/data/"
                "01-Redistricting_File--PL_94-171/Minnesota/mn2020.pl.zip",
            headers=dict(RANGE_1K),
            max_bytes=PROBE_BYTES,
            note="2020 P.L. 94-171 block population, keyless bulk. Supplies the "
                 "population weights that CenPop does not publish at block level.",
        ),
    ]


def _energy_and_grid() -> list[ProbeSpec]:
    return [
        ProbeSpec(
            source_id="nrel_home_charging",
            kind="availability",
            url="https://data.nlr.gov/system/files/278/"
                "1734741167-NREL_county_EV_home_charging_access.xlsx",
            headers=dict(RANGE_1K),
            max_bytes=PROBE_BYTES,
            note="County EV home charging access shares from the 2030 National "
                 "Charging Network study. Parametric over EV share of stock, not a "
                 "dated present-day observation.",
        ),
        ProbeSpec(
            source_id="eia_prices_api",
            kind="rest_json",
            url="https://api.eia.gov/v2/electricity/retail-sales/data/",
            params={"frequency": "monthly", "data[0]": "price", "length": "1"},
            needs_api_key="eia",
            note="Requires a free key; there is no demo credential.",
        ),
        ProbeSpec(
            source_id="eia_prices_bulk",
            kind="availability",
            url="https://www.eia.gov/electricity/data/state/avgprice_annual.xlsx",
            headers=dict(RANGE_1K),
            max_bytes=PROBE_BYTES,
            note="Keyless bulk fallback for state average electricity price.",
        ),
        ProbeSpec(
            source_id="egrid",
            kind="availability",
            url="https://www.epa.gov/system/files/documents/2025-06/egrid2023_data_rev2.xlsx",
            headers=dict(RANGE_1K),
            max_bytes=PROBE_BYTES,
            note="eGRID2023 rev2. No model in CLAUDE.md section 7 consumes it.",
        ),
        ProbeSpec(
            source_id="hifld_transmission_service",
            kind="rest_json",
            url="https://services1.arcgis.com/Hp6G80Pky0om7QvQ/arcgis/rest/services/"
                "Electric_Power_Transmission_Lines/FeatureServer/0",
            params={"f": "json"},
            note="Live HIFLD transmission line service metadata.",
        ),
        ProbeSpec(
            source_id="hifld_substations",
            kind="rest_json",
            url="https://services.arcgis.com/G4S1dGvn7PIgYd6Y/ArcGIS/rest/services/"
                "HIFLD_electric_power_substations/FeatureServer/0",
            params={"f": "json"},
            note="Best candidate found for HIFLD substations. Holds only 128 features, "
                 "far short of a national layer; recorded as degraded evidence.",
        ),
        ProbeSpec(
            source_id="hifld_transmission_count",
            kind="rest_json",
            url="https://services1.arcgis.com/Hp6G80Pky0om7QvQ/arcgis/rest/services/"
                "Electric_Power_Transmission_Lines/FeatureServer/0/query",
            params={"where": "1=1", "returnCountOnly": "true", "f": "json"},
            note="Feature count for the live HIFLD transmission service, to compare "
                 "against the 94,216 features in the delivered seed GeoJSON.",
        ),
        ProbeSpec(
            source_id="hifld_substations_count",
            kind="rest_json",
            url="https://services.arcgis.com/G4S1dGvn7PIgYd6Y/ArcGIS/rest/services/"
                "HIFLD_electric_power_substations/FeatureServer/0/query",
            params={"where": "1=1", "returnCountOnly": "true", "f": "json"},
            note="Feature count. A national substation layer holds tens of thousands "
                 "of features; this one does not, which is the evidence for recording "
                 "substation data as degraded.",
        ),
        ProbeSpec(
            source_id="cejst_archive",
            kind="remote_csv",
            url="https://web.archive.org/web/2024/https://static-data-screeningtool."
                "geoplatform.gov/data-versions/2.0/data/score/downloadable/"
                "2.0-communities.csv",
            headers=dict(RANGE_64K),
            max_bytes=SAMPLE_BYTES,
            note="CEJST v2.0 via the Internet Archive. The live host no longer "
                 "resolves in DNS. Archived policy framework, no longer in force.",
        ),
        ProbeSpec(
            source_id="fhwa_traffic",
            kind="availability",
            url="https://www.fhwa.dot.gov/policyinformation/hpms.cfm",
            note="HPMS landing page. Traffic is a backtest feature (validation tier).",
        ),
    ]


def _crosswalks() -> list[ProbeSpec]:
    """Geographic crosswalks used to move registration counts between geographies."""
    return [
        ProbeSpec(
            source_id="hud_usps_zip_tract",
            kind="rest_json",
            url="https://www.huduser.gov/hudapi/public/usps",
            params={"type": "1", "query": "98101"},
            record_path=("data", "results"),
            needs_bearer="hud",
            note="HUD USER USPS ZIP-to-tract crosswalk. Bearer authentication; the "
                 "token is redacted before any cache write. res_ratio is the "
                 "residential-address weight preferred for allocating registrations.",
        ),
        ProbeSpec(
            source_id="census_zcta_tract_landarea",
            kind="remote_csv",
            url="https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/"
                "tab20_zcta520_tract20_natl.txt",
            headers=dict(RANGE_64K),
            max_bytes=SAMPLE_BYTES,
            delimiter="|",
            note="Land-area ZCTA-to-tract crosswalk, the documented degraded fallback "
                 "for ZIP-to-tract allocation.",
        ),
    ]


def _states() -> list[ProbeSpec]:
    return [
        ProbeSpec(
            source_id="wa_ev_population",
            kind="rest_json",
            url="https://data.wa.gov/resource/f6w7-q2d2.json",
            params={"$limit": "200"},
            note="Washington DOL EV population. Vehicle-grain with a 2020 census tract "
                 "field: the only tract-granularity registration source found.",
        ),
        ProbeSpec(
            source_id="wa_ev_population_meta",
            kind="rest_json",
            url="https://data.wa.gov/api/views/f6w7-q2d2.json",
            note="Socrata metadata: license, column list, last update.",
        ),
    ]


def _seed_files() -> list[ProbeSpec]:
    csvs = {
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
    specs = [
        ProbeSpec(source_id=sid, kind="local_csv", local_path=PATHS.seed / name)
        for sid, name in sorted(csvs.items())
    ]
    specs.append(
        ProbeSpec(
            source_id="seed_hifld_transmission_lines",
            kind="local_geojson",
            local_path=PATHS.seed / "Electric__Power_Transmission_Lines.geojson",
            max_rows=200,
            note="Streamed property sample only. Never parsed as one GeoJSON object (G12).",
        )
    )
    return specs


def all_specs() -> tuple[ProbeSpec, ...]:
    """Every Phase 0 probe, in a stable order."""
    specs: list[ProbeSpec] = []
    for group in (_afdc, _afdc_registrations, _atlas, _census, _energy_and_grid,
                  _crosswalks, _states, _seed_files):
        specs.extend(group())
    return tuple(sorted(specs, key=lambda s: s.source_id))
