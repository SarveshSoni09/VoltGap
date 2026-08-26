"""Live integration: AFDC / NLR (`NREL_API_KEY`).

Phase 0 measured the shared DEMO_KEY at 10 requests per window. These tests exercise
the *production credential path* instead, plus the authentication failure modes and the
JSON-primary / CSV-fallback reconciliation the source contract now claims.
"""

from __future__ import annotations

import csv
import io

import httpx
import pytest

from pipeline.config.settings import ApiKeys
from tests.live.conftest import AFDC_BASE, SMALL_STATE, require

pytestmark = pytest.mark.live

BOUNDED = {"fuel_type": "ELEC", "state": SMALL_STATE, "limit": "all"}


# --- authentication -----------------------------------------------------------------

def test_a_valid_key_is_accepted(client: httpx.Client, keys: ApiKeys) -> None:
    require(not keys.nrel_is_demo, "NREL_API_KEY")
    response = client.get(f"{AFDC_BASE}.json",
                          params={**BOUNDED, "limit": "1", "api_key": keys.nrel})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert "total_results" in body and "fuel_stations" in body
    assert body["total_results"] > 0


def test_a_personal_key_lifts_the_demo_rate_limit(
    client: httpx.Client, keys: ApiKeys
) -> None:
    """DEMO_KEY is 10 per window; a personal key must be materially higher."""
    require(not keys.nrel_is_demo, "NREL_API_KEY")
    response = client.get(f"{AFDC_BASE}.json",
                          params={**BOUNDED, "limit": "1", "api_key": keys.nrel})
    limit = response.headers.get("x-ratelimit-limit")
    assert limit is not None, "the API should advertise a rate limit"
    assert int(limit) > 10, f"expected more than the DEMO_KEY allowance, got {limit}"


def test_a_missing_key_is_refused_with_a_named_error(client: httpx.Client) -> None:
    response = client.get(f"{AFDC_BASE}.json", params={**BOUNDED, "limit": "1"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "API_KEY_MISSING"


def test_an_invalid_key_is_refused_distinctly_from_a_missing_one(
    client: httpx.Client,
) -> None:
    """A deliberately fake in-memory value. `.env` is never touched."""
    response = client.get(f"{AFDC_BASE}.json",
                          params={**BOUNDED, "limit": "1", "api_key": "not-a-real-key"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "API_KEY_INVALID"


def test_an_invalid_key_does_not_appear_in_the_error_body(client: httpx.Client) -> None:
    response = client.get(f"{AFDC_BASE}.json",
                          params={**BOUNDED, "limit": "1", "api_key": "not-a-real-key"})
    assert "not-a-real-key" not in response.text


# --- primary representation -----------------------------------------------------------

def test_the_json_primary_still_carries_the_structure_the_canonical_model_needs(
    client: httpx.Client, keys: ApiKeys
) -> None:
    require(not keys.nrel_is_demo, "NREL_API_KEY")
    stations = client.get(f"{AFDC_BASE}.json",
                          params={**BOUNDED, "api_key": keys.nrel}).json()["fuel_stations"]
    assert stations
    units = [u for s in stations for u in (s.get("ev_charging_units") or [])]
    assert units, "the primary representation must expose nested charging units"
    assert set(units[0]) == {"charging_level", "connectors", "funding_sources",
                             "network", "port_count"}
    assert all("port_count" in u for u in units), "unit-level port_count is why JSON is primary"
    assert {str(u["charging_level"]) for u in units} <= {"1", "2", "dc_fast", "legacy"}


def test_no_charging_unit_identifier_has_appeared_upstream(
    client: httpx.Client, keys: ApiKeys
) -> None:
    """If AFDC ever adds one, the synthetic-key decision must be revisited (6.1.1)."""
    require(not keys.nrel_is_demo, "NREL_API_KEY")
    stations = client.get(f"{AFDC_BASE}.json",
                          params={**BOUNDED, "api_key": keys.nrel}).json()["fuel_stations"]
    units = [u for s in stations for u in (s.get("ev_charging_units") or [])]
    identifiers = {k for u in units for k in u
                   if k.lower() in {"id", "unit_id", "evse_id", "uuid", "serial"}}
    assert not identifiers, (
        f"an identifier appeared upstream: {identifiers}. The canonical model's "
        "synthetic per-snapshot key assumption must be re-evaluated"
    )


def test_the_station_schema_still_matches_the_contract(
    client: httpx.Client, keys: ApiKeys
) -> None:
    require(not keys.nrel_is_demo, "NREL_API_KEY")
    stations = client.get(f"{AFDC_BASE}.json",
                          params={**BOUNDED, "api_key": keys.nrel}).json()["fuel_stations"]
    required = {"id", "status_code", "access_code", "latitude", "longitude", "open_date",
                "ev_network", "ev_level1_evse_num", "ev_level2_evse_num",
                "ev_dc_fast_num", "ev_connector_types", "state", "zip", "facility_type"}
    assert required <= set(stations[0]), f"missing {required - set(stations[0])}"
    assert {str(s["status_code"]) for s in stations} <= {"E", "T", "P"}, "domain rule G2"
    assert {str(s["access_code"]) for s in stations} <= {"public", "private"}, "G3"
    identifiers = [s["id"] for s in stations]
    assert len(identifiers) == len(set(identifiers)), "station id must be unique"


# --- pagination -------------------------------------------------------------------------

def test_pagination_does_not_drop_or_duplicate_across_page_boundaries(
    client: httpx.Client, keys: ApiKeys
) -> None:
    require(not keys.nrel_is_demo, "NREL_API_KEY")
    base = {**BOUNDED, "api_key": keys.nrel}
    full = client.get(f"{AFDC_BASE}.json", params=base).json()
    page_1 = client.get(f"{AFDC_BASE}.json",
                        params={**base, "limit": "10", "offset": "0"}).json()
    page_2 = client.get(f"{AFDC_BASE}.json",
                        params={**base, "limit": "10", "offset": "10"}).json()

    all_ids = [s["id"] for s in full["fuel_stations"]]
    ids_1 = [s["id"] for s in page_1["fuel_stations"]]
    ids_2 = [s["id"] for s in page_2["fuel_stations"]]

    assert len(all_ids) == full["total_results"], "limit=all must return every record"
    assert len(all_ids) == len(set(all_ids)), "no duplicates in the full set"
    assert not set(ids_1) & set(ids_2), "pages must not overlap"
    assert set(ids_1 + ids_2) <= set(all_ids), "paged records must be a subset of the whole"
    assert page_1["total_results"] == full["total_results"]


# --- fallback and reconciliation ----------------------------------------------------------

def test_the_csv_fallback_representation_is_still_reachable_and_parses(
    client: httpx.Client, keys: ApiKeys
) -> None:
    require(not keys.nrel_is_demo, "NREL_API_KEY")
    response = client.get(f"{AFDC_BASE}/ev-charging-units.csv",
                          params={**BOUNDED, "api_key": keys.nrel})
    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert rows, "the fallback must parse to rows"
    assert "Snapshot Date" in rows[0]


def test_the_fallbacks_documented_limitation_still_holds(
    client: httpx.Client, keys: ApiKeys
) -> None:
    """The contract claims the CSV drops the NEMA standards. Verify, do not assume."""
    require(not keys.nrel_is_demo, "NREL_API_KEY")
    response = client.get(f"{AFDC_BASE}/ev-charging-units.csv",
                          params={**BOUNDED, "api_key": keys.nrel})
    columns = list(csv.DictReader(io.StringIO(response.text)).fieldnames or [])
    connector_columns = [c for c in columns if "Connector Count" in c]
    assert len(connector_columns) == 5
    assert not [c for c in columns if "NEMA" in c.upper()], (
        "the CSV fallback is documented as exposing no NEMA columns"
    )


def test_json_and_csv_agree_on_charging_unit_count_for_one_state(
    client: httpx.Client, keys: ApiKeys
) -> None:
    """Three independent routes to the same quantity must agree."""
    require(not keys.nrel_is_demo, "NREL_API_KEY")
    params = {**BOUNDED, "api_key": keys.nrel}
    payload = client.get(f"{AFDC_BASE}.json", params=params).json()
    json_units = sum(len(s.get("ev_charging_units") or [])
                     for s in payload["fuel_stations"])
    envelope = payload["station_counts"]["fuels"]["ELEC"]["total"]
    csv_rows = len(list(csv.DictReader(io.StringIO(
        client.get(f"{AFDC_BASE}/ev-charging-units.csv", params=params).text))))

    assert json_units == csv_rows == envelope, (
        f"JSON units={json_units}, CSV rows={csv_rows}, envelope={envelope}"
    )
