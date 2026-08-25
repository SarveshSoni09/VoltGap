"""Unit tests for the source adapter framework and the Phase 1 catalogue.

The central property under test is amendment A15: **retrieval and staging preserve
source rows.** An adapter may decode, decompress, stream or reshape; it may not drop,
filter or editorialise. That is enforced structurally by ``assert_lossless``, and
every adapter is exercised against it here.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from pipeline.discovery.cache import LiveFetcher, ReplayFetcher
from pipeline.sources.base import (
    DelimitedSource,
    HtmlTableSource,
    JsonRecordsSource,
    LossyStagingError,
    NestedUnitsSource,
    SourceVintage,
    StagedTable,
    decode_delimited,
    decode_html_table,
    decode_json_records,
    iter_delimited_file,
)
from pipeline.sources.catalog import (
    FIXTURE_STATES,
    SEED_SOURCES,
    afdc_registration_sources,
    afdc_sources,
    all_sources,
    atlas_sources,
    census_sources,
    local_json_source,
    seed_sources,
    washington_source,
)
from tests.conftest import make_client_factory


def vintage() -> SourceVintage:
    return SourceVintage("s", "v", "t")


# --- the A15 guard -------------------------------------------------------------------

def test_a_lossless_table_passes() -> None:
    table = StagedTable("s", ("a",), [{"a": "1"}], vintage(), 1)
    assert table.assert_lossless() is table


def test_dropping_a_row_raises() -> None:
    table = StagedTable("s", ("a",), [{"a": "1"}], vintage(), source_row_count=2)
    with pytest.raises(LossyStagingError, match="preserve source rows"):
        table.assert_lossless()


def test_adding_a_row_also_raises() -> None:
    table = StagedTable("s", ("a",), [{"a": "1"}, {"a": "2"}], vintage(), 1)
    with pytest.raises(LossyStagingError):
        table.assert_lossless()


def test_duplicate_column_names_are_rejected() -> None:
    table = StagedTable("s", ("a", "a"), [], vintage(), 0)
    with pytest.raises(LossyStagingError, match="duplicate column name"):
        table.assert_unique_columns()


def test_schema_hash_is_derived_from_the_columns() -> None:
    assert StagedTable("s", ("a", "b"), [], vintage(), 0).schema_hash != \
        StagedTable("s", ("b", "a"), [], vintage(), 0).schema_hash


def test_source_vintage_serialises() -> None:
    payload = SourceVintage("s", "2023", "t", "abc", "https://x").to_dict()
    assert payload["source_id"] == "s"
    assert payload["endpoint"] == "https://x"


# --- decoders --------------------------------------------------------------------------

def test_decode_delimited_keeps_every_row_and_the_header_verbatim() -> None:
    columns, rows = decode_delimited(b"EV Level1 EVSE Num,State\n1,MN\n,IL\n")
    assert columns == ("EV Level1 EVSE Num", "State")
    assert rows == [{"EV Level1 EVSE Num": "1", "State": "MN"},
                    {"EV Level1 EVSE Num": "", "State": "IL"}]


def test_decode_delimited_supports_a_pipe_delimiter() -> None:
    columns, rows = decode_delimited(b"GEO_ID|VALUE\n1|2\n", delimiter="|")
    assert columns == ("GEO_ID", "VALUE")
    assert len(rows) == 1


def test_decode_json_records_reserialises_nested_values_rather_than_losing_them() -> None:
    payload = b'{"r":[{"a":1,"nested":{"x":2},"list":[1,2]}]}'
    columns, rows = decode_json_records(payload, ("r",))
    assert columns == ("a", "list", "nested")
    assert rows[0]["nested"] == '{"x":2}'
    assert rows[0]["list"] == "[1,2]"
    assert rows[0]["a"] == "1"


def test_decode_json_records_wraps_a_bare_object_and_blanks_nulls() -> None:
    columns, rows = decode_json_records(b'{"last_updated":null}')
    assert columns == ("last_updated",)
    assert rows[0]["last_updated"] == ""


def test_decode_html_table_keeps_a_published_total_row() -> None:
    """G8 removal is intermediate work, never the adapter's (A15)."""
    html = (b"<table><tr><th>State</th><th>EV</th></tr>"
            b"<tr><td>Oregon</td><td>64,400</td></tr>"
            b"<tr><td>United States</td><td>7,111,800</td></tr></table>")
    columns, rows = decode_html_table(html)
    assert columns == ("State", "EV")
    assert [r["State"] for r in rows] == ["Oregon", "United States"]


def test_iter_delimited_file_streams(tmp_path: Path) -> None:
    path = tmp_path / "x.csv"
    path.write_text("a,b\n1,2\n3,\n", encoding="utf-8")
    assert list(iter_delimited_file(path)) == [{"a": "1", "b": "2"}, {"a": "3", "b": ""}]


# --- adapters ---------------------------------------------------------------------------

def test_delimited_source_reads_a_local_file(tmp_path: Path) -> None:
    path = tmp_path / "x.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    table = DelimitedSource("s", path=path).load()
    assert table.rows == [{"a": "1", "b": "2"}]
    assert table.vintage.vintage == "frozen fixture"


def test_delimited_source_fetches_a_remote_file(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"a\n1\n", headers={"Last-Modified": "Mon"})

    fetcher = LiveFetcher(tmp_path, client_factory=make_client_factory(handler))
    table = DelimitedSource("s", endpoint="https://x/a.csv").load(fetcher)
    assert len(table.rows) == 1
    assert table.vintage.vintage == "Mon"


def test_a_remote_source_without_a_fetcher_raises() -> None:
    for source in (
        DelimitedSource("s", endpoint="https://x"),
        JsonRecordsSource("s", "https://x"),
        HtmlTableSource("s", "https://x"),
        NestedUnitsSource("s", "https://x"),
    ):
        with pytest.raises(ValueError, match="needs a fetcher"):
            source.load(None)


def test_json_records_source_reads_a_local_file(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    path.write_text('{"fuel_stations":[{"id":1}]}', encoding="utf-8")
    table = JsonRecordsSource("s", "", ("fuel_stations",), path=path).load()
    assert table.rows == [{"id": "1"}]
    assert table.vintage.vintage == "local snapshot"


def test_json_records_source_fetches_remotely(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'{"fuel_stations":[{"id":1},{"id":2}]}')

    fetcher = LiveFetcher(tmp_path, client_factory=make_client_factory(handler))
    table = JsonRecordsSource("s", "https://x", ("fuel_stations",)).load(fetcher)
    assert len(table.rows) == 2


def test_html_table_source_records_that_it_kept_the_total_row(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=(
            b"<table><tr><th>State</th><th>EV</th></tr>"
            b"<tr><td>United States</td><td>1</td></tr></table>"))

    fetcher = LiveFetcher(tmp_path, client_factory=make_client_factory(handler))
    table = HtmlTableSource("s", "https://x", vintage="2020").load(fetcher)
    assert table.vintage.vintage == "2020"
    assert "G8 removes it in intermediate" in table.notes[0]


# --- nested units -------------------------------------------------------------------------

def station(units: int = 2, station_id: int = 7) -> dict[str, object]:
    return {
        "id": station_id, "state": "MN", "status_code": "E", "access_code": "public",
        "latitude": 44.9, "longitude": -93.0,
        "ev_charging_units": [
            {"network": "N", "port_count": 1, "charging_level": "2",
             "connectors": {"J1772": {"power_kw": 6.5, "port_count": 1}}}
            for _ in range(units)
        ],
    }


def test_nested_units_produces_one_row_per_unit(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    path.write_text(json.dumps({"fuel_stations": [station(3)]}), encoding="utf-8")
    table = NestedUnitsSource("s", "", path=path).load()
    assert len(table.rows) == 3
    assert table.source_row_count == 3


def test_nested_units_keys_are_synthetic_and_per_snapshot(tmp_path: Path) -> None:
    """The key is station_id:ordinal, and ordinal is row order, not identity."""
    path = tmp_path / "x.json"
    path.write_text(json.dumps({"fuel_stations": [station(2)]}), encoding="utf-8")
    table = NestedUnitsSource("s", "", path=path).load()
    assert [r["charging_unit_record_key"] for r in table.rows] == ["7:0", "7:1"]
    assert any("no longitudinal" in note for note in table.notes)


def test_nested_units_does_not_deduplicate_identical_units(tmp_path: Path) -> None:
    """Identical unit objects are real distinct physical units, as G4 describes."""
    path = tmp_path / "x.json"
    path.write_text(json.dumps({"fuel_stations": [station(40)]}), encoding="utf-8")
    table = NestedUnitsSource("s", "", path=path).load()
    assert len(table.rows) == 40
    assert any("real distinct physical units" in note for note in table.notes)


def test_nested_units_flattens_connector_columns(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    path.write_text(json.dumps({"fuel_stations": [station(1)]}), encoding="utf-8")
    table = NestedUnitsSource("s", "", path=path).load()
    assert "connector_J1772_port_count" in table.columns
    assert "connector_J1772_power_kw" in table.columns
    assert table.rows[0]["connector_J1772_power_kw"] == "6.5"
    assert table.rows[0]["unit_port_count"] == "1"


def test_nested_units_handles_a_station_with_no_units(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    path.write_text(json.dumps({"fuel_stations": [{"id": 1}]}), encoding="utf-8")
    assert NestedUnitsSource("s", "", path=path).load().rows == []


def test_nested_units_handles_a_bare_list_payload(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    path.write_text(json.dumps([station(1)]), encoding="utf-8")
    assert len(NestedUnitsSource("s", "", path=path).load().rows) == 1


def test_nested_units_fetches_remotely(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps(
            {"fuel_stations": [station(2)]}).encode())

    fetcher = LiveFetcher(tmp_path, client_factory=make_client_factory(handler))
    assert len(NestedUnitsSource("s", "https://x").load(fetcher).rows) == 2


def test_nested_units_tolerates_a_missing_connectors_block(tmp_path: Path) -> None:
    payload = {"fuel_stations": [{"id": 1, "ev_charging_units": [{"port_count": 1}]}]}
    path = tmp_path / "x.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    table = NestedUnitsSource("s", "", path=path).load()
    assert len(table.rows) == 1
    assert not [c for c in table.columns if c.startswith("connector_")]


# --- catalogue -------------------------------------------------------------------------

def test_seed_sources_cover_every_declared_seed_file() -> None:
    assert set(seed_sources()) == set(SEED_SOURCES)


def test_afdc_sources_can_be_scoped_to_a_state() -> None:
    national = afdc_sources()["afdc_stations"]
    scoped = afdc_sources("MN")["afdc_stations"]
    assert "state" not in national.params  # type: ignore[attr-defined]
    assert scoped.params["state"] == "MN"  # type: ignore[attr-defined]


def test_ten_registration_vintages_are_catalogued() -> None:
    sources = afdc_registration_sources()
    assert len(sources) == 10
    assert sources["afdc_state_ev_registrations_2020"].declared_vintage == "2020"  # type: ignore[attr-defined]


def test_atlas_none_means_all_states_and_empty_means_none() -> None:
    """An empty tuple is not the same as 'unspecified'."""
    assert len(atlas_sources(None)) == 14
    assert atlas_sources(()) == {}
    assert set(atlas_sources(("MN", "TX"))) == {
        "atlas_ev_registrations_mn", "atlas_ev_registrations_tx"
    }


def test_washington_and_census_sources_are_catalogued() -> None:
    assert "wa_ev_population" in washington_source()
    assert set(census_sources()) == {"census_cenpop_tract", "census_cenpop_blockgroup"}
    assert "27" in census_sources("27")["census_cenpop_tract"].endpoint


def test_all_sources_is_the_union_and_the_fixture_states_are_declared() -> None:
    catalogue = all_sources()
    assert len(catalogue) == 38
    assert FIXTURE_STATES == ("MN", "IL")


def test_local_json_source_selects_the_right_adapter(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    path.write_text('{"fuel_stations":[]}', encoding="utf-8")
    assert isinstance(local_json_source("afdc_charging_units", path), NestedUnitsSource)
    assert isinstance(local_json_source("afdc_stations", path), JsonRecordsSource)


def test_a_cache_miss_propagates_rather_than_yielding_an_empty_table(
    tmp_path: Path,
) -> None:
    from pipeline.discovery.cache import CacheMissError

    with pytest.raises(CacheMissError):
        DelimitedSource("s", endpoint="https://x/a.csv").load(ReplayFetcher(tmp_path))
