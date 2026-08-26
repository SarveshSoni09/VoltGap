"""Shared fixtures."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest

from pipeline.config.settings import PATHS
from pipeline.transform.runner import Warehouse

REPO_ROOT = PATHS.root


@pytest.fixture
def replay_root() -> Path:
    """The committed replay fixtures used by the deterministic gate."""
    return PATHS.replay_fixtures


def make_client_factory(
    handler: Callable[[httpx.Request], httpx.Response],
) -> Callable[[], httpx.Client]:
    """Build a LiveFetcher client factory backed by an in-memory transport."""

    def factory() -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler))

    return factory


@pytest.fixture(scope="session")
def fixture_warehouse() -> Iterator[Warehouse]:
    """The two-state (MN + IL) canonical build, constructed once per test session.

    Built entirely from cached responses with an injected fixed timestamp, so it is
    deterministic and needs no network.
    """
    from pipeline.build import build
    from pipeline.discovery.cache import ReplayFetcher

    raw = PATHS.root / "data" / "cache" / "raw"
    warehouse = Warehouse()
    build(
        warehouse,
        ReplayFetcher(PATHS.cache),
        stations_path=raw / "afdc_stations_mn.json",
        units_path=raw / "afdc_stations_mn.json",
        atlas_states=("MN",),
        computed_at="2026-01-01T00:00:00+00:00",
    )
    yield warehouse
    warehouse.close()


@pytest.fixture(scope="session")
def phase2_warehouse(fixture_warehouse: Warehouse) -> Warehouse:
    """The Phase 1 fixture warehouse with the Phase 2 supply and access marts added."""
    from pipeline.model.build_supply_access import build_supply_access, register_marts

    if "mart_site_supply" not in fixture_warehouse.table_names():
        result = build_supply_access(fixture_warehouse)
        register_marts(fixture_warehouse, result,
                       "2026-01-01T00:00:00+00:00", "{}")
    return fixture_warehouse


@pytest.fixture(scope="session")
def seed_frame():  # type: ignore[no-untyped-def]
    """Loader for a frozen seed fixture, as a pandas DataFrame of strings."""
    import pandas as pd

    from pipeline.sources.catalog import SEED_SOURCES, seed_sources

    cache: dict[str, pd.DataFrame] = {}

    def load(source_id: str) -> pd.DataFrame:
        if source_id not in cache:
            assert source_id in SEED_SOURCES, f"unknown seed source {source_id}"
            table = seed_sources()[source_id].load()
            cache[source_id] = pd.DataFrame(table.rows, dtype="string")
        return cache[source_id]

    return load


def scalar(warehouse: Warehouse, sql: str) -> object:
    """First column of the first row. Fails loudly if the query returned nothing."""
    row = warehouse.connection.execute(sql).fetchone()
    assert row is not None, f"query returned no rows: {sql}"
    return row[0]
