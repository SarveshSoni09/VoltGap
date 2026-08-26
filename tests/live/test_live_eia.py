"""Live integration: EIA Open Data v2 (`EIA_API_KEY`).

A working credential does **not** justify expanding Core scope. EIA has no Core
consumer in CLAUDE.md section 7; it is validated here because the credential exists and
the source is likely useful for the Optional-tier economics model (section 7.11).
"""

from __future__ import annotations

import httpx
import pytest

from pipeline.config.settings import ApiKeys
from tests.live.conftest import EIA_RETAIL, require

pytestmark = pytest.mark.live

# Commercial sector, not residential: public charging is a commercial load, and using
# residential prices for charger economics would be a category error (CLAUDE.md 7.11).
SERIES = {"frequency": "monthly", "data[0]": "price",
          "facets[stateid][]": "WA", "facets[sectorid][]": "COM",
          "start": "2024-01", "end": "2024-03",
          "sort[0][column]": "period", "sort[0][direction]": "asc"}


def test_the_key_authenticates(client: httpx.Client, keys: ApiKeys) -> None:
    require(bool(keys.eia), "EIA_API_KEY")
    response = client.get(EIA_RETAIL, params={**SERIES, "api_key": keys.eia})
    assert response.status_code == 200
    assert "response" in response.json()


def test_a_missing_key_is_refused(client: httpx.Client) -> None:
    response = client.get(EIA_RETAIL, params=SERIES)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "API_KEY_MISSING"


def test_an_invalid_key_is_refused_distinctly(client: httpx.Client) -> None:
    response = client.get(EIA_RETAIL, params={**SERIES, "api_key": "not-a-real-key"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "API_KEY_INVALID"


def test_the_series_carries_the_semantics_an_economics_model_would_need(
    client: httpx.Client, keys: ApiKeys
) -> None:
    require(bool(keys.eia), "EIA_API_KEY")
    payload = client.get(EIA_RETAIL,
                         params={**SERIES, "api_key": keys.eia}).json()["response"]
    assert payload["frequency"] == "monthly"
    rows = payload["data"]
    assert rows
    row = rows[0]
    assert row["price-units"] == "cents per kilowatt-hour"
    assert row["sectorid"] == "COM", "commercial, not residential"
    assert row["stateid"] == "WA"
    assert row["period"].startswith("2024-")


def test_pagination_does_not_duplicate_or_drop(
    client: httpx.Client, keys: ApiKeys
) -> None:
    require(bool(keys.eia), "EIA_API_KEY")
    base = {**SERIES, "api_key": keys.eia}
    page_1 = client.get(EIA_RETAIL,
                        params={**base, "length": "2", "offset": "0"}).json()["response"]
    page_2 = client.get(EIA_RETAIL,
                        params={**base, "length": "2", "offset": "2"}).json()["response"]
    def key(row: dict[str, str]) -> tuple[str, str, str]:
        return (row["period"], row["stateid"], row["sectorid"])

    ids_1 = [key(r) for r in page_1["data"]]
    ids_2 = [key(r) for r in page_2["data"]]
    assert not set(ids_1) & set(ids_2), "pages must not overlap"
    assert int(page_1["total"]) == len(ids_1) + len(ids_2)


def test_eia_has_no_core_consumer_and_must_not_acquire_one_by_accident() -> None:
    """A working API is not a reason to expand scope (CLAUDE.md 7.11, 7.12)."""
    from pipeline.config.settings import PATHS
    from pipeline.discovery.contract import load_contract

    contract = load_contract(PATHS.contract)
    entries = {e["id"]: e for e in contract["sources"]}
    for source_id in ("eia_prices_api", "eia_prices_bulk"):
        assert entries[source_id]["tier"] == "optional", source_id
        assert set(entries[source_id]["used_by"]) <= {"economics"}, (
            f"{source_id} has acquired a consumer beyond the Optional-tier economics "
            "model; that requires a deliberate promotion, not a working credential"
        )
