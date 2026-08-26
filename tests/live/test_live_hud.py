"""Live integration: HUD USER USPS ZIP Code Crosswalk (`HUD_USER_TOKEN`).

This is the candidate preferred Phase 3 ZIP-to-tract allocation path. The tests verify
the endpoint, the Bearer authentication, the ratio semantics, and the edge cases that
would otherwise be discovered mid-model: ZIPs with no residential addresses, ZIPs with
no tract mapping at all, and whether ratios may be renormalised.
"""

from __future__ import annotations

import httpx
import pytest

from pipeline.config.settings import ApiKeys
from tests.live.conftest import HUD_USPS, TEST_ZIP, require

pytestmark = pytest.mark.live

ZIP_TO_TRACT = 1  # HUD's documented crosswalk type code


def bearer(keys: ApiKeys) -> dict[str, str]:
    return {"Authorization": f"Bearer {keys.hud}"}


def test_the_token_authenticates(client: httpx.Client, keys: ApiKeys) -> None:
    require(bool(keys.hud), "HUD_USER_TOKEN")
    response = client.get(HUD_USPS, params={"type": ZIP_TO_TRACT, "query": TEST_ZIP},
                          headers=bearer(keys))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")


def test_a_missing_token_is_refused(client: httpx.Client) -> None:
    response = client.get(HUD_USPS, params={"type": ZIP_TO_TRACT, "query": TEST_ZIP})
    assert response.status_code == 401
    assert response.json()["error"] == "Unauthenticated"


def test_an_invalid_token_is_refused_and_not_echoed(client: httpx.Client) -> None:
    response = client.get(HUD_USPS, params={"type": ZIP_TO_TRACT, "query": TEST_ZIP},
                          headers={"Authorization": "Bearer not-a-real-key"})
    assert response.status_code == 401
    assert "not-a-real-key" not in response.text


def test_the_response_carries_its_geography_vintage(
    client: httpx.Client, keys: ApiKeys
) -> None:
    """A crosswalk without a stated vintage cannot be recorded in the contract."""
    require(bool(keys.hud), "HUD_USER_TOKEN")
    data = client.get(HUD_USPS, params={"type": ZIP_TO_TRACT, "query": TEST_ZIP},
                      headers=bearer(keys)).json()["data"]
    assert data["crosswalk_type"] == "zip-tract"
    assert int(data["year"]) >= 2020
    assert int(data["quarter"]) in (1, 2, 3, 4)


def test_the_output_fields_are_what_the_allocation_needs(
    client: httpx.Client, keys: ApiKeys
) -> None:
    require(bool(keys.hud), "HUD_USER_TOKEN")
    results = client.get(HUD_USPS, params={"type": ZIP_TO_TRACT, "query": TEST_ZIP},
                         headers=bearer(keys)).json()["data"]["results"]
    assert results
    assert set(results[0]) >= {"zip", "geoid", "res_ratio", "bus_ratio", "oth_ratio",
                               "tot_ratio"}
    # geoid must be an 11-digit tract FIPS, joinable to Census geography directly.
    assert all(len(r["geoid"]) == 11 and r["geoid"].isdigit() for r in results)
    assert all(r["zip"] == TEST_ZIP for r in results)


def test_ratios_are_within_zero_and_one(client: httpx.Client, keys: ApiKeys) -> None:
    require(bool(keys.hud), "HUD_USER_TOKEN")
    results = client.get(HUD_USPS, params={"type": ZIP_TO_TRACT, "query": TEST_ZIP},
                         headers=bearer(keys)).json()["data"]["results"]
    for field in ("res_ratio", "bus_ratio", "oth_ratio", "tot_ratio"):
        assert all(0.0 <= float(r[field]) <= 1.0 for r in results), field


@pytest.mark.parametrize("zip_code", ["98101", "10001", "00601", "20001"])
def test_residential_ratios_sum_to_one_for_a_residential_zip(
    client: httpx.Client, keys: ApiKeys, zip_code: str
) -> None:
    require(bool(keys.hud), "HUD_USER_TOKEN")
    results = client.get(HUD_USPS, params={"type": ZIP_TO_TRACT, "query": zip_code},
                         headers=bearer(keys)).json()["data"]["results"]
    total = sum(float(r["res_ratio"]) for r in results)
    assert abs(total - 1.0) < 1e-9, f"{zip_code}: res_ratio sums to {total}"


def test_a_zip_with_no_residential_addresses_sums_to_zero_not_one(
    client: httpx.Client, keys: ApiKeys
) -> None:
    """The edge case that must NOT be silently renormalised.

    99546 is a real ZIP whose residential ratio is 0: there are no residential
    addresses to allocate. Rescaling it to 1 would invent residents. Such a ZIP is
    reported as unallocatable by the residential method, not fixed up.
    """
    require(bool(keys.hud), "HUD_USER_TOKEN")
    results = client.get(HUD_USPS, params={"type": ZIP_TO_TRACT, "query": "99546"},
                         headers=bearer(keys)).json()["data"]["results"]
    assert results, "the ZIP does map to a tract"
    assert sum(float(r["res_ratio"]) for r in results) == 0.0
    assert sum(float(r["tot_ratio"]) for r in results) > 0.0, (
        "total addresses exist; only residential ones do not"
    )


def test_a_zip_with_no_tract_mapping_is_reported_not_silently_empty(
    client: httpx.Client, keys: ApiKeys
) -> None:
    """98504 is a PO-Box-only ZIP with no areal equivalent."""
    require(bool(keys.hud), "HUD_USER_TOKEN")
    response = client.get(HUD_USPS, params={"type": ZIP_TO_TRACT, "query": "98504"},
                          headers=bearer(keys))
    assert response.status_code == 404, (
        "an unmappable ZIP must fail loudly so it can be reported as unallocatable"
    )


def test_the_rate_limit_is_advertised(client: httpx.Client, keys: ApiKeys) -> None:
    """Measured at 60 per minute; an adapter must respect it rather than discover it."""
    require(bool(keys.hud), "HUD_USER_TOKEN")
    response = client.get(HUD_USPS, params={"type": ZIP_TO_TRACT, "query": TEST_ZIP},
                          headers=bearer(keys))
    limit = response.headers.get("x-ratelimit-limit")
    assert limit is not None, "HUD advertises a per-minute rate limit"
    assert int(limit) > 0
