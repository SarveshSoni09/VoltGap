"""Fixtures for live-network integration tests.

Every test in this package hits a production endpoint and is marked ``live``. None of
them runs in the deterministic phase gates: `make gate PHASE=n` must stay
network-independent. They are invoked deliberately through `make live-smoke`,
`make live-integration` or `make integration-assurance`.

**Credential handling.** Values are read once into memory and never printed, logged,
persisted or included in assertion messages. Tests report presence, not value.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest

from pipeline.config.settings import ApiKeys, api_keys

AFDC_BASE = "https://developer.nlr.gov/api/alt-fuel-stations/v1"
CENSUS_ACS = "https://api.census.gov/data/2023/acs/acs5"
HUD_USPS = "https://www.huduser.gov/hudapi/public/usps"
EIA_RETAIL = "https://api.eia.gov/v2/electricity/retail-sales/data/"

# Bounded scopes. Rhode Island is the smallest state by station count; one tract and
# one ZIP keep every check cheap (CLAUDE.md live-checkpoint scope discipline).
SMALL_STATE = "RI"
TEST_TRACT = {"state": "53", "county": "033", "tract": "007202"}
TEST_ZIP = "98101"


@pytest.fixture(scope="session")
def keys() -> ApiKeys:
    return api_keys()


@pytest.fixture(scope="session")
def client() -> Iterator[httpx.Client]:
    with httpx.Client(timeout=120, follow_redirects=True) as session:
        yield session


def require(present: bool, name: str) -> None:
    """Skip with a message that names the variable but never its value."""
    if not present:
        pytest.skip(f"{name} is not configured in the environment or .env")
