"""Live integration: Census ACS API and bulk summary file (`CENSUS_API_KEY`).

Phase 0 recorded "the Census ACS API now requires a key". These tests establish that
claim empirically for the exact production endpoint the pipeline uses, rather than
carrying it forward on assertion, and reconcile the API against the bulk path.
"""

from __future__ import annotations

import httpx
import pytest

from pipeline.config.settings import ApiKeys
from tests.live.conftest import CENSUS_ACS, TEST_TRACT, require

pytestmark = pytest.mark.live

VARIABLES = "NAME,B25003_001E,B25003_002E,B25003_003E"
QUERY = {"get": VARIABLES, "for": f"tract:{TEST_TRACT['tract']}",
         "in": f"state:{TEST_TRACT['state']} county:{TEST_TRACT['county']}"}
GEO_ID = f"1400000US{TEST_TRACT['state']}{TEST_TRACT['county']}{TEST_TRACT['tract']}"
BULK = ("https://www2.census.gov/programs-surveys/acs/summary_file/2023/"
        "table-based-SF/data/5YRData/acsdt5y2023-b25003.dat")

# Phase 3's planned ACS feature set (CLAUDE.md 7.3). Verified to exist NOW rather than
# discovered missing during fitting.
PHASE_3_TABLES = {
    "B19013": "median household income",
    "B25003": "housing tenure",
    "B25024": "units in structure",
    "B25044": "vehicles available",
    "B08303": "travel time to work",
    "B08301": "means of transportation to work",
    "B15003": "educational attainment",
    "B01003": "total population",
}


def test_the_keyless_request_is_refused_and_how(client: httpx.Client) -> None:
    """The refusal is the trap: HTTP 200 with an HTML page, not a 4xx."""
    response = client.get(CENSUS_ACS, params=QUERY)
    content_type = response.headers.get("content-type", "")
    assert "json" not in content_type, (
        "if this now returns JSON, the keyless path works and the contract must be "
        "corrected to say so"
    )
    assert "Missing Key" in response.text
    assert response.status_code == 200, (
        "recorded deliberately: the API answers 200 with an HTML error page, so an "
        "adapter checking only the status code would treat this as success"
    )


def test_the_authenticated_request_succeeds(client: httpx.Client, keys: ApiKeys) -> None:
    require(bool(keys.census), "CENSUS_API_KEY")
    response = client.get(CENSUS_ACS, params={**QUERY, "key": keys.census})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    payload = response.json()
    assert payload[0][:4] == ["NAME", "B25003_001E", "B25003_002E", "B25003_003E"]
    assert payload[1][-3:] == [TEST_TRACT["state"], TEST_TRACT["county"],
                               TEST_TRACT["tract"]]


def test_an_invalid_key_is_refused(client: httpx.Client) -> None:
    response = client.get(CENSUS_ACS, params={**QUERY, "key": "not-a-real-key"})
    assert "json" not in response.headers.get("content-type", "")


def test_the_api_and_the_bulk_file_agree_for_the_same_tract_and_vintage(
    client: httpx.Client, keys: ApiKeys
) -> None:
    """Two independent routes to one number. They must not disagree."""
    require(bool(keys.census), "CENSUS_API_KEY")
    api = client.get(CENSUS_ACS, params={**QUERY, "key": keys.census}).json()
    api_values = dict(zip(api[0], api[1], strict=True))

    header: list[str] | None = None
    found: dict[str, str] | None = None
    buffer = ""
    with httpx.stream("GET", BULK, timeout=300, follow_redirects=True) as stream:
        assert stream.status_code == 200
        for chunk in stream.iter_text():
            buffer += chunk
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                if header is None:
                    header = line.strip().split("|")
                    continue
                parts = line.strip().split("|")
                if parts and parts[0] == GEO_ID:
                    found = dict(zip(header, parts, strict=False))
                    break
            if found:
                break

    assert found is not None, f"{GEO_ID} not present in the bulk file"
    # The two routes name the same variable differently: B25003_001E vs B25003_E001.
    for index in ("001", "002", "003"):
        assert api_values[f"B25003_{index}E"] == found[f"B25003_E{index}"], (
            f"API and bulk disagree on B25003 estimate {index}"
        )


def test_every_acs_table_phase_3_plans_to_use_exists_in_this_vintage(
    client: httpx.Client, keys: ApiKeys
) -> None:
    """Discover a missing variable now, not during Phase 3 model fitting."""
    require(bool(keys.census), "CENSUS_API_KEY")
    catalogue = client.get(
        "https://api.census.gov/data/2023/acs/acs5/groups.json", timeout=120
    ).json()
    available = {group["name"] for group in catalogue["groups"]}
    missing = sorted(t for t in PHASE_3_TABLES if t not in available)
    assert not missing, f"planned ACS tables absent from the 2023 5-year release: {missing}"


def test_the_historical_vintages_phase_5_needs_also_exist(client: httpx.Client) -> None:
    """Directive D1: a 2020 origin must use the contemporaneous ACS release."""
    for year in (2019, 2020, 2021, 2022):
        response = client.get(
            f"https://api.census.gov/data/{year}/acs/acs5/groups.json", timeout=120
        )
        assert response.status_code == 200, f"ACS {year} 5-year release unreachable"
        available = {group["name"] for group in response.json()["groups"]}
        missing = sorted(t for t in PHASE_3_TABLES if t not in available)
        assert not missing, f"ACS {year} is missing {missing}"
