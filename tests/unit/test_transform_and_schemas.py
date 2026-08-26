"""Unit tests for the DuckDB transform runner and the canonical pandera schemas."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from pipeline.schemas.canonical import (
    SCHEMAS,
    SchemaViolationError,
    validate,
    validate_all,
)
from pipeline.sources.base import SourceVintage, StagedTable
from pipeline.transform.runner import (
    LAYERS,
    VOLATILE_COLUMNS,
    ModelResult,
    TransformError,
    Warehouse,
    build_context,
    default_database,
    discover_models,
)

# --- runner ---------------------------------------------------------------------------

def staged(name: str = "s", rows: int = 2) -> StagedTable:
    data = [{"a": str(i), "b": "x"} for i in range(rows)]
    return StagedTable(name, ("a", "b"), data, SourceVintage(name, "v", "t"), rows)


def test_load_staged_creates_an_all_varchar_table() -> None:
    with Warehouse() as warehouse:
        warehouse.load_staged(staged())
        described = warehouse.connection.execute("DESCRIBE raw_s").fetchall()
        assert [str(d[1]) for d in described] == ["VARCHAR", "VARCHAR"]
        assert warehouse.table_names() == ["raw_s"]


def test_load_staged_handles_an_empty_table() -> None:
    with Warehouse() as warehouse:
        warehouse.load_staged(staged(rows=0))
        row = warehouse.connection.execute("SELECT count(*) FROM raw_s").fetchone()
        assert row is not None and row[0] == 0


def test_load_records_registers_a_computed_table() -> None:
    with Warehouse() as warehouse:
        warehouse.load_records("computed", ("x", "y"), [("1", "2")])
        assert warehouse.fetch_df("computed").iloc[0]["x"] == "1"
        warehouse.load_records("empty", ("x",), [])
        assert len(warehouse.fetch_df("empty")) == 0


def test_run_model_creates_a_table_and_reports_its_shape(tmp_path: Path) -> None:
    model = tmp_path / "stg_thing.sql"
    model.write_text("SELECT 1 AS n, '{computed_at}' AS computed_at", encoding="utf-8")
    with Warehouse() as warehouse:
        result = warehouse.run_model("staging", model, {"computed_at": "T"})
        assert result == ModelResult("staging", "stg_thing", 1, ("n", "computed_at"))
        assert warehouse.fetch_df("stg_thing").iloc[0]["computed_at"] == "T"


def test_an_unknown_placeholder_is_reported_clearly(tmp_path: Path) -> None:
    model = tmp_path / "stg_bad.sql"
    model.write_text("SELECT '{nope}' AS x", encoding="utf-8")
    with Warehouse() as warehouse, pytest.raises(TransformError, match="unknown placeholder"):
        warehouse.run_model("staging", model, {"computed_at": "T"})


def test_invalid_sql_is_reported_with_the_model_name(tmp_path: Path) -> None:
    model = tmp_path / "stg_broken.sql"
    model.write_text("SELECT * FROM nonexistent_table", encoding="utf-8")
    with Warehouse() as warehouse, pytest.raises(TransformError, match="stg_broken"):
        warehouse.run_model("staging", model, {})


def test_discover_models_orders_by_layer_then_filename(tmp_path: Path) -> None:
    for layer in LAYERS:
        (tmp_path / layer).mkdir()
        for name in ("b", "a"):
            (tmp_path / layer / f"{name}.sql").write_text("SELECT 1", encoding="utf-8")
    found = discover_models(tmp_path)
    assert [layer for layer, _ in found] == ["staging"] * 2 + ["intermediate"] * 2 + \
        ["marts"] * 2
    assert [path.stem for _, path in found] == ["a", "b"] * 3


def test_discover_models_skips_absent_layers(tmp_path: Path) -> None:
    (tmp_path / "staging").mkdir()
    (tmp_path / "staging" / "a.sql").write_text("SELECT 1", encoding="utf-8")
    assert len(discover_models(tmp_path)) == 1


def test_run_all_executes_every_model(tmp_path: Path) -> None:
    (tmp_path / "staging").mkdir()
    (tmp_path / "staging" / "stg_a.sql").write_text("SELECT 1 AS n", encoding="utf-8")
    (tmp_path / "marts").mkdir()
    (tmp_path / "marts" / "mart_a.sql").write_text("SELECT * FROM stg_a", encoding="utf-8")
    with Warehouse() as warehouse:
        results = warehouse.run_all({}, tmp_path)
        assert [r.name for r in results] == ["stg_a", "mart_a"]


def test_model_result_serialises() -> None:
    payload = ModelResult("marts", "mart_x", 3, ("a",)).to_dict()
    assert payload == {"layer": "marts", "name": "mart_x", "rows": 3, "columns": ["a"]}


def test_build_context_injects_a_timestamp_and_sorts_vintages() -> None:
    context = build_context({"b": "2", "a": "1"}, "2026-01-01T00:00:00+00:00")
    assert context["computed_at"] == "2026-01-01T00:00:00+00:00"
    assert context["source_vintages"] == '{"a":"1","b":"2"}'


def test_build_context_defaults_to_now_when_no_timestamp_is_injected() -> None:
    assert build_context({}, None)["computed_at"].startswith("20")


def test_default_database_is_under_the_warehouse_directory() -> None:
    assert default_database().name == "voltgap.duckdb"
    assert default_database().parent.name == "warehouse"


def test_a_file_backed_warehouse_persists(tmp_path: Path) -> None:
    database = tmp_path / "w.duckdb"
    warehouse = Warehouse(database)
    warehouse.load_records("t", ("a",), [("1",)])
    warehouse.close()
    reopened = Warehouse(database)
    assert len(reopened.fetch_df("t")) == 1
    reopened.close()


# --- semantic hash ----------------------------------------------------------------------

def test_semantic_hash_excludes_volatile_columns() -> None:
    with Warehouse() as warehouse:
        warehouse.load_records("t", ("a", "computed_at"), [("1", "T1")])
        first = warehouse.semantic_hash(("t",))
        warehouse.load_records("t", ("a", "computed_at"), [("1", "T2")])
        assert warehouse.semantic_hash(("t",)) == first


def test_semantic_hash_covers_a_table_whose_columns_are_all_volatile() -> None:
    """Nothing survives the exclusion, so only the table's identity is hashed."""
    with Warehouse() as warehouse:
        warehouse.load_records("t", ("computed_at",), [("T1",)])
        first = warehouse.semantic_hash(("t",))
        warehouse.load_records("t", ("computed_at",), [("T2",), ("T3",)])
        assert warehouse.semantic_hash(("t",)) == first
        # The table name still participates, so two such tables are distinguishable.
        warehouse.load_records("u", ("computed_at",), [("T1",)])
        assert warehouse.semantic_hash(("u",)) != first


def test_semantic_hash_detects_a_column_rename() -> None:
    with Warehouse() as warehouse:
        warehouse.load_records("t", ("a",), [("1",)])
        first = warehouse.semantic_hash(("t",))
        warehouse.load_records("t", ("b",), [("1",)])
        assert warehouse.semantic_hash(("t",)) != first


def test_volatile_columns_are_exactly_the_declared_set() -> None:
    assert {"computed_at", "retrieved_at",
                                "last_successful_retrieval", "elapsed_ms"} == VOLATILE_COLUMNS


# --- schemas ------------------------------------------------------------------------------

def valid_state_totals() -> pd.DataFrame:
    return pd.DataFrame({
        "state": ["Oregon"], "vintage": ["2023"], "ev_count": [64361],
        "measure_type": ["stock"], "computed_at": ["T"], "source_vintages": ["{}"],
    })


def test_a_valid_frame_validates() -> None:
    assert len(validate("mart_state_totals", valid_state_totals())) == 1


def test_an_unknown_table_has_no_schema() -> None:
    with pytest.raises(SchemaViolationError, match="no pandera schema"):
        validate("mart_invented", pd.DataFrame())


def test_g8_a_surviving_total_row_fails_the_schema() -> None:
    """The schema is the last line of defence for G8."""
    frame = valid_state_totals()
    frame.loc[0, "state"] = "United States"
    with pytest.raises(SchemaViolationError, match="mart_state_totals"):
        validate("mart_state_totals", frame)


def test_a_negative_count_fails_the_schema() -> None:
    frame = valid_state_totals()
    frame.loc[0, "ev_count"] = -1
    with pytest.raises(SchemaViolationError):
        validate("mart_state_totals", frame)


def test_missing_provenance_columns_fail_the_schema() -> None:
    frame = valid_state_totals().drop(columns=["source_vintages"])
    with pytest.raises(SchemaViolationError):
        validate("mart_state_totals", frame)


def test_a_synthetic_key_flag_of_false_fails_the_schema() -> None:
    """No consumer may be told the record key is a stable physical identifier."""
    frame = pd.DataFrame({
        "charging_unit_record_key": ["7:0"], "station_id": ["7"], "site_id": ["s"],
        "record_ordinal": [0], "state": ["MN"], "status_code": ["E"],
        "access_code": ["public"], "ev_network": ["N"], "charging_level": ["2"],
        "port_count": [1], "connector_port_sum": [1], "is_multi_connector_port": [False],
        "is_public_operational": [True], "key_is_synthetic": [False],
        "has_longitudinal_identity": [False], "computed_at": ["T"],
        "source_vintages": ["{}"],
    })
    with pytest.raises(SchemaViolationError, match="mart_charging_units"):
        validate("mart_charging_units", frame)


def test_validate_all_checks_every_supplied_table() -> None:
    result = validate_all({"mart_state_totals": valid_state_totals()})
    assert set(result) == {"mart_state_totals"}


def test_every_mart_has_a_schema_and_every_schema_requires_provenance() -> None:
    # Six Phase 1 marts plus the two Phase 2 supply marts. Later phases add more, so
    # this asserts the Phase 1 set is intact rather than pinning a total.
    phase_1 = {"mart_sites", "mart_stations", "mart_charging_units",
               "mart_charging_unit_connectors", "mart_state_totals",
               "mart_observed_subregion_ev"}
    assert phase_1 <= set(SCHEMAS)
    assert len(SCHEMAS) >= 6
    for name, schema in SCHEMAS.items():
        assert "computed_at" in schema.columns, name
        assert "source_vintages" in schema.columns, name
        assert schema.strict is True, name
