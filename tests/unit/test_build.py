"""Unit tests for the canonical build orchestrator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.build import (
    ATLAS_GEOGRAPHY,
    ATLAS_GEOGRAPHY_COLUMN,
    MART_TABLES,
    BuildResult,
    load_afdc,
    load_atlas,
    load_seeds,
    resolve_sites,
    union_staged,
    validate_marts,
)
from pipeline.discovery.cache import ReplayFetcher
from pipeline.sources.base import LossyStagingError, SourceVintage, StagedTable
from pipeline.transform.runner import Warehouse


def table(source_id: str, rows: list[dict[str, str]],
          columns: tuple[str, ...]) -> StagedTable:
    return StagedTable(source_id, columns, rows,
                       SourceVintage(source_id, "v", "t"), len(rows))


# --- union ----------------------------------------------------------------------------

def test_union_concatenates_and_tags() -> None:
    a = table("a", [{"x": "1"}], ("x",))
    b = table("b", [{"x": "2"}, {"x": "3"}], ("x",))
    union = union_staged("u", [a, b], {"vintage": ["2020", "2021"]})
    assert union.source_row_count == 3
    assert [r["vintage"] for r in union.rows] == ["2020", "2021", "2021"]
    assert union.columns == ("x", "vintage")


def test_union_widens_to_the_union_of_columns() -> None:
    a = table("a", [{"x": "1"}], ("x",))
    b = table("b", [{"y": "2"}], ("y",))
    union = union_staged("u", [a, b])
    assert union.columns == ("x", "y")
    assert union.rows == [{"x": "1", "y": ""}, {"x": "", "y": "2"}]


def test_union_is_lossless_by_construction() -> None:
    a = table("a", [{"x": "1"}], ("x",))
    assert union_staged("u", [a]).assert_lossless().source_row_count == 1


def test_union_of_a_mismatched_table_raises() -> None:
    broken = StagedTable("a", ("x",), [{"x": "1"}],
                         SourceVintage("a", "v", "t"), source_row_count=5)
    with pytest.raises(LossyStagingError):
        union_staged("u", [broken])


def test_union_requires_at_least_one_table() -> None:
    with pytest.raises(AssertionError, match="at least one table"):
        union_staged("u", [])


# --- atlas geography ------------------------------------------------------------------

def test_every_atlas_state_has_a_declared_geography_and_column() -> None:
    """CLAUDE.md 7.5.1: declared per source, never inferred from column naming."""
    assert len(ATLAS_GEOGRAPHY) == 14
    assert set(ATLAS_GEOGRAPHY.values()) == {"usps_zip", "county"}
    assert sum(1 for v in ATLAS_GEOGRAPHY.values() if v == "usps_zip") == 11
    for geography in set(ATLAS_GEOGRAPHY.values()):
        assert geography in ATLAS_GEOGRAPHY_COLUMN


def test_usps_zip_is_never_labelled_zcta() -> None:
    """They are not interchangeable and must never be silently equated."""
    assert "zcta" not in set(ATLAS_GEOGRAPHY.values())


def test_load_atlas_with_no_states_registers_an_empty_table(tmp_path: Path) -> None:
    with Warehouse() as warehouse:
        load_atlas(warehouse, BuildResult(), ReplayFetcher(tmp_path), ())
        assert "raw_atlas_registrations" in warehouse.table_names()
        assert len(warehouse.fetch_df("raw_atlas_registrations")) == 0


# --- loaders ----------------------------------------------------------------------------

def test_load_seeds_can_be_restricted(tmp_path: Path) -> None:
    with Warehouse() as warehouse:
        result = BuildResult()
        load_seeds(warehouse, result, only=["seed_state_ev_registrations"])
        assert warehouse.table_names() == ["raw_seed_state_ev_registrations"]
        assert result.staged_row_counts == {"seed_state_ev_registrations": 52}
        assert result.source_vintages["seed_state_ev_registrations"] == "frozen fixture"


def test_load_afdc_registers_both_tables(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"fuel_stations": [
        {"id": 1, "latitude": 44.9, "longitude": -93.0,
         "ev_charging_units": [{"port_count": 1, "connectors": {}}]}
    ]}), encoding="utf-8")
    with Warehouse() as warehouse:
        result = BuildResult()
        load_afdc(warehouse, result, stations_path=path, units_path=path)
        assert set(warehouse.table_names()) == {
            "raw_afdc_stations", "raw_afdc_charging_units"
        }
        assert result.staged_row_counts["afdc_stations"] == 1
        assert result.staged_row_counts["afdc_charging_units"] == 1


# --- sites -------------------------------------------------------------------------------

def test_resolve_sites_registers_typed_assignments() -> None:
    with Warehouse() as warehouse:
        warehouse.connection.execute(
            "CREATE TABLE stg_afdc_stations AS SELECT * FROM (VALUES "
            "('a', 44.9, -93.0), ('b', 44.90009, -93.0), ('c', 45.5, -93.0)) "
            "t(station_id, latitude, longitude)"
        )
        sites = resolve_sites(warehouse)
        assert sites == 2
        frame = warehouse.fetch_df("computed_site_assignments")
        assert len(frame) == 3
        assert frame["site_latitude"].dtype.kind == "f"
        by_station = dict(zip(frame["station_id"], frame["site_id"], strict=True))
        assert by_station["a"] == by_station["b"] != by_station["c"]


# --- results and validation ------------------------------------------------------------

def test_build_result_serialises_with_sorted_keys() -> None:
    result = BuildResult(source_vintages={"b": "2", "a": "1"},
                         staged_row_counts={"z": 1, "y": 2}, semantic_hash="abc")
    payload = result.to_dict()
    assert list(payload["source_vintages"]) == ["a", "b"]
    assert list(payload["staged_row_counts"]) == ["y", "z"]
    assert payload["semantic_hash"] == "abc"


def test_mart_tables_matches_the_schema_registry() -> None:
    from pipeline.schemas.canonical import SCHEMAS

    assert set(MART_TABLES) == set(SCHEMAS)


def test_validate_marts_returns_row_counts(fixture_warehouse: Warehouse) -> None:
    counts = validate_marts(fixture_warehouse)
    assert set(counts) == set(MART_TABLES)
    assert counts["mart_stations"] > 0


def test_a_schema_violation_blocks_the_build(fixture_warehouse: Warehouse) -> None:
    """CLAUDE.md section 9: a violation fails the build and blocks publication."""
    from pipeline.schemas.canonical import SchemaViolationError

    fixture_warehouse.connection.execute(
        "CREATE OR REPLACE TABLE mart_state_totals_backup AS "
        "SELECT * FROM mart_state_totals"
    )
    fixture_warehouse.connection.execute(
        "UPDATE mart_state_totals SET state = 'United States' WHERE rowid = 0"
    )
    try:
        with pytest.raises(SchemaViolationError, match="mart_state_totals"):
            validate_marts(fixture_warehouse)
    finally:
        fixture_warehouse.connection.execute(
            "CREATE OR REPLACE TABLE mart_state_totals AS "
            "SELECT * FROM mart_state_totals_backup"
        )
