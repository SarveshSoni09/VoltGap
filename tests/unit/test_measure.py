"""Unit tests for the measurement primitives."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.discovery.measure import (
    is_missing,
    iter_csv_rows,
    measure_connector_power_coverage,
    measure_delimited,
    measure_delimited_file,
    measure_geojson_properties,
    measure_html_table,
    measure_json_records,
    measure_records,
    parse_html_table,
    schema_hash,
)


def test_is_missing_covers_null_tokens_nan_and_whitespace() -> None:
    assert is_missing(None) is True
    assert is_missing(float("nan")) is True
    assert is_missing("  ") is True
    assert is_missing("N/A") is True
    assert is_missing("NULL") is True
    assert is_missing(0) is False
    assert is_missing("value") is False


def test_schema_hash_is_order_sensitive() -> None:
    """A column reorder is a schema change and must be detected as one."""
    assert schema_hash(["a", "b"]) != schema_hash(["b", "a"])
    assert schema_hash(["a", "b"]) == schema_hash(["a", "b"])


def test_measure_records_computes_missingness_per_field() -> None:
    result = measure_records(
        [{"a": 1, "b": None}, {"a": 2, "b": "x"}, {"a": None, "b": ""}], ("a", "b")
    )
    assert result.row_count == 3
    assert result.missingness["a"] == pytest.approx(1 / 3)
    assert result.missingness["b"] == pytest.approx(2 / 3)


def test_measure_records_on_empty_input_reports_full_missingness() -> None:
    result = measure_records([], ("a", "b"))
    assert result.row_count == 0
    assert result.missingness == {"a": 1.0, "b": 1.0}


def test_measurement_to_dict_rounds_and_sorts() -> None:
    payload = measure_records([{"b": 1, "a": None}], ("b", "a")).to_dict()
    assert payload["fields"] == ["b", "a"], "field order is preserved verbatim"
    assert list(payload["missingness"]) == ["a", "b"], "missingness is sorted for stable diffs"
    assert payload["field_count"] == 2
    assert payload["truncated"] is False


def test_measure_delimited_preserves_the_header_verbatim() -> None:
    result = measure_delimited(b"EV J1772 Power Output (kW),State\n6.5,MN\n")
    assert result.fields == ("EV J1772 Power Output (kW)", "State")


def test_measure_delimited_honours_max_rows_and_flags_truncation() -> None:
    result = measure_delimited(b"a\n1\n2\n3\n", max_rows=2)
    assert result.row_count == 2
    assert result.truncated is True


def test_measure_delimited_supports_alternative_delimiters() -> None:
    result = measure_delimited(b"GEO_ID|B25003_E001\n0100000US|127482865\n", delimiter="|")
    assert result.fields == ("GEO_ID", "B25003_E001")
    assert result.row_count == 1


def test_measure_delimited_file_streams_from_disk(tmp_path: Path) -> None:
    path = tmp_path / "x.csv"
    path.write_text("a,b\n1,\n2,3\n", encoding="utf-8")
    result = measure_delimited_file(path)
    assert result.row_count == 2
    assert result.missingness["b"] == 0.5


def test_measure_json_records_unions_optional_keys() -> None:
    result = measure_json_records(b'{"r":[{"a":1},{"b":2}]}', ("r",))
    assert result.fields == ("a", "b")
    assert result.row_count == 2
    assert result.missingness == {"a": 0.5, "b": 0.5}


def test_measure_json_records_wraps_a_bare_object() -> None:
    result = measure_json_records(b'{"last_updated":"2026-08-19"}')
    assert result.row_count == 1
    assert result.fields == ("last_updated",)


def test_measure_json_records_truncates() -> None:
    result = measure_json_records(b'{"r":[{"a":1},{"a":2},{"a":3}]}', ("r",), max_rows=2)
    assert result.row_count == 2
    assert result.truncated is True


def test_parse_html_table_returns_empty_when_there_is_no_table() -> None:
    assert parse_html_table(b"<p>no table here</p>") == ((), [])


def test_measure_html_table_reads_header_and_rows() -> None:
    html = (
        b"<table><tr><th>State</th><th>Electric (EV)</th></tr>"
        b"<tr><td>Oregon</td><td>64,400</td></tr>"
        b"<tr><td>Kansas</td><td>11,300</td></tr></table>"
    )
    result = measure_html_table(html)
    assert result.fields == ("State", "Electric (EV)")
    assert result.row_count == 2


def test_measure_geojson_properties_streams_a_bounded_sample(tmp_path: Path) -> None:
    """Domain rule G12: the file is never parsed as one GeoJSON object."""
    path = tmp_path / "x.geojson"
    features = ",".join(
        f'{{ "type": "Feature", "properties": {{ "VOLTAGE": {v}, "OWNER": "X" }}, '
        '"geometry": null }'
        for v in range(5)
    )
    path.write_text('{"type":"FeatureCollection","features":[' + features + "]}", encoding="utf-8")
    result = measure_geojson_properties(path, max_features=3)
    assert result.row_count == 3
    assert result.fields == ("OWNER", "VOLTAGE")
    assert result.truncated is True
    assert "G12" in result.notes[0]


def test_measure_geojson_properties_stops_at_end_of_file(tmp_path: Path) -> None:
    path = tmp_path / "x.geojson"
    path.write_text('{"features":[{ "properties": { "A": 1 } }]}', encoding="utf-8")
    result = measure_geojson_properties(path, max_features=99)
    assert result.row_count == 1


def test_measure_geojson_properties_handles_a_file_with_no_properties(tmp_path: Path) -> None:
    path = tmp_path / "x.geojson"
    path.write_text("x" * 3000, encoding="utf-8")
    assert measure_geojson_properties(path, max_features=5).row_count == 0


def test_iter_csv_rows_streams_dicts(tmp_path: Path) -> None:
    path = tmp_path / "x.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    assert list(iter_csv_rows(path)) == [{"a": "1", "b": "2"}]


# --- connector power coverage ----------------------------------------------------

def _unit(**kwargs: object) -> dict[str, object]:
    row: dict[str, object] = {"Status Code": "E", "Access Code": "public"}
    for name in ("J1772", "CCS", "CHAdeMO", "J3400", "J3271"):
        row[f"EV {name} Connector Count"] = "0"
        row[f"EV {name} Power Output (kW)"] = ""
    row.update(kwargs)
    return row


def test_power_coverage_is_conditional_on_the_connector_existing() -> None:
    """A power column is only meaningful where that connector is actually present."""
    rows = [
        _unit(**{"EV CCS Connector Count": "2", "EV CCS Power Output (kW)": "350"}),
        _unit(**{"EV CCS Connector Count": "1", "EV CCS Power Output (kW)": ""}),
    ]
    result = measure_connector_power_coverage(rows)
    ccs = next(c for c in result["per_connector"] if c["connector"] == "CCS")
    assert ccs["units_with_connector"] == 2
    assert ccs["ports"] == 3
    assert ccs["ports_with_power"] == 2
    assert ccs["port_coverage"] == pytest.approx(2 / 3, abs=1e-6)
    assert result["rung1_port_coverage"] == pytest.approx(2 / 3, abs=1e-6)


def test_power_coverage_applies_g2_and_g3_when_asked() -> None:
    rows = [
        _unit(**{"EV CCS Connector Count": "1", "EV CCS Power Output (kW)": "350"}),
        _unit(**{"Status Code": "T", "EV CCS Connector Count": "9",
                 "EV CCS Power Output (kW)": "350"}),
        _unit(**{"Access Code": "private", "EV CCS Connector Count": "9",
                 "EV CCS Power Output (kW)": "350"}),
    ]
    assert measure_connector_power_coverage(rows)["total_ports"] == 19
    filtered = measure_connector_power_coverage(rows, public_operational_only=True)
    assert filtered["rows_considered"] == 1
    assert filtered["total_ports"] == 1


def test_power_coverage_counts_zero_kilowatt_cells_separately() -> None:
    """0.00 kW is not a valid reported power and must be visible as a data fault."""
    rows = [_unit(**{"EV J1772 Connector Count": "1", "EV J1772 Power Output (kW)": "0"})]
    result = measure_connector_power_coverage(rows)
    assert result["reported_power_equal_zero_cells"] == 1


def test_power_coverage_ignores_unparseable_values_and_empty_input() -> None:
    rows = [_unit(**{"EV CCS Connector Count": "not-a-number"})]
    assert measure_connector_power_coverage(rows)["total_ports"] == 0
    empty = measure_connector_power_coverage([])
    assert empty["rung1_port_coverage"] == 0.0
    assert empty["total_ports"] == 0


def test_parse_html_table_ignores_rows_with_no_cells() -> None:
    html = b"<table><tr></tr><tr><th>a</th></tr><tr><td>1</td></tr></table>"
    header, rows = parse_html_table(html)
    assert header == ("a",)
    assert rows == [{"a": "1"}]


def test_geojson_streaming_handles_features_spanning_read_chunks(tmp_path: Path) -> None:
    """The reader consumes 1 MiB at a time; a feature must survive a chunk boundary."""
    path = tmp_path / "big.geojson"
    # The properties object itself is larger than the 1 MiB read chunk, so the
    # decoder must carry a partially captured object across chunk boundaries.
    long_owner = "A" * (3 << 20)
    body = (
        '{"type":"FeatureCollection","features":['
        + '{ "type": "Feature", "properties": { "VOLTAGE": 345, "OWNER": "'
        + long_owner + '" }, "geometry": null },'
        + " " * (1 << 20)
        + '{ "type": "Feature", "properties": { "VOLTAGE": 500 }, "geometry": null }]}'
    )
    path.write_text(body, encoding="utf-8")
    result = measure_geojson_properties(path, max_features=2)
    assert result.row_count == 2
    assert set(result.fields) == {"VOLTAGE", "OWNER"}


def test_geojson_streaming_handles_a_properties_key_with_no_object(tmp_path: Path) -> None:
    path = tmp_path / "x.geojson"
    path.write_text('{"a":"properties"}', encoding="utf-8")
    assert measure_geojson_properties(path, max_features=5).row_count == 0


def test_geojson_streaming_stops_on_an_unterminated_properties_object(
    tmp_path: Path,
) -> None:
    path = tmp_path / "x.geojson"
    path.write_text('{ "properties": { "A": 1', encoding="utf-8")
    assert measure_geojson_properties(path, max_features=5).row_count == 0
