"""Unit tests for the unit/port/connector identifiability analysis.

CLAUDE.md 6.1.1 forbids manufacturing physical identity the source does not supply.
These tests verify the analysis reports what is actually there, and that the
pre-registered decision rules fire the way the Phase 1 plan committed to in advance.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pipeline.quality.identifiability import (
    analyse,
    analyse_file,
    analyse_station_json,
    scan_header_for_identifiers,
)

HEADER = (
    "ID", "Status Code", "Access Code", "EV Network",
    "EV Level1 EVSE Num", "EV Level2 EVSE Num", "EV DC Fast Count",
    "EV J1772 Connector Count", "EV CCS Connector Count",
    "EV CHAdeMO Connector Count", "EV J3400 Connector Count",
    "EV J3271 Connector Count",
)


def row(station: str = "1", status: str = "E", access: str = "public",
        l1: str = "", l2: str = "1", dcfc: str = "", **connectors: str) -> dict[str, object]:
    values: dict[str, object] = {
        "ID": station, "Status Code": status, "Access Code": access,
        "EV Network": "Non-Networked",
        "EV Level1 EVSE Num": l1, "EV Level2 EVSE Num": l2, "EV DC Fast Count": dcfc,
    }
    for name in ("J1772", "CCS", "CHAdeMO", "J3400", "J3271"):
        values[f"EV {name} Connector Count"] = connectors.get(name, "0")
    return values


# --- identifier scanning ----------------------------------------------------------

def test_scan_finds_no_identifier_in_the_real_afdc_header() -> None:
    result = scan_header_for_identifiers(HEADER)
    assert result["any_unit_or_port_identifier"] is False
    assert result["identifier_columns_found"] == []
    assert "ID" in result["id_like_columns_that_are_not_unit_identity"]


def test_scan_would_detect_an_identifier_if_afdc_ever_added_one() -> None:
    """A future release adding real identity must be detected, not assumed away."""
    result = scan_header_for_identifiers((*HEADER, "EVSE ID"))
    assert result["any_unit_or_port_identifier"] is True
    assert result["identifier_columns_found"] == ["EVSE ID"]


# --- duplicate-row measurement ------------------------------------------------------

def test_identical_rows_are_counted_as_indistinguishable() -> None:
    rows = [row(l2="3"), row(l2="3"), row(l2="3")]
    result = analyse(rows, HEADER)
    national = result["scopes"]["national"]
    assert national["rows"] == 3
    assert national["distinct_full_row_values"] == 1
    assert national["redundant_rows"] == 2
    assert national["largest_identical_group"] == 3
    assert result["findings"]["m8_duplicate_rows_distinguishable_other_than_by_order"] is False


def test_distinct_rows_are_reported_as_distinguishable() -> None:
    rows = [row(station="1", J1772="1"), row(station="2", CCS="1")]
    result = analyse(rows, HEADER)
    assert result["scopes"]["national"]["redundant_rows"] == 0
    assert result["findings"]["m8_duplicate_rows_distinguishable_other_than_by_order"] is True


def test_row_count_reconciliation_against_reported_evse_totals() -> None:
    """The finding that makes aggregate capacity trustworthy despite absent identity."""
    rows = [row(station="1", l2="2"), row(station="1", l2="2")]
    result = analyse(rows, HEADER)
    national = result["scopes"]["national"]
    assert national["stations_row_count_reconciles_to_reported_evse"] == 1
    assert national["reconciliation_share"] == 1.0


def test_reconciliation_fails_when_row_count_disagrees() -> None:
    rows = [row(station="1", l2="5")]
    assert analyse(rows, HEADER)["scopes"]["national"]["reconciliation_share"] == 0.0


# --- G2 / G3 scoping -----------------------------------------------------------------

def test_public_operational_scope_applies_g2_and_g3() -> None:
    rows = [
        row(station="1"),
        row(station="2", status="T"),
        row(station="3", access="private"),
    ]
    result = analyse(rows, HEADER)
    assert result["scopes"]["national"]["rows"] == 3
    assert result["scopes"]["public_operational"]["rows"] == 1


# --- connector mapping ----------------------------------------------------------------

def test_multi_connector_rows_are_detected() -> None:
    """sum(connector counts) > 1 means one port exposes several standards."""
    rows = [row(CCS="1", CHAdeMO="1"), row(J1772="1")]
    result = analyse(rows, HEADER)
    assert result["scopes"]["national"]["rows_connector_sum_gt_one"] == 1
    assert result["findings"]["m3_connector_counts_map_unambiguously_to_ports"] is False
    assert result["findings"]["m4_rows_where_connector_sum_exceeds_one_port"] == 1


def test_single_connector_rows_map_unambiguously() -> None:
    result = analyse([row(J1772="1"), row(CCS="1")], HEADER)
    assert result["findings"]["m3_connector_counts_map_unambiguously_to_ports"] is True


def test_rows_with_no_connector_counts_are_tracked() -> None:
    assert analyse([row()], HEADER)["scopes"]["national"]["rows_with_no_connector_counts"] == 1


def test_unparseable_counts_are_treated_as_absent() -> None:
    assert analyse([row(J1772="not-a-number")], HEADER)["scopes"]["national"][
        "rows_with_no_connector_counts"
    ] == 1


def test_empty_input_does_not_divide_by_zero() -> None:
    result = analyse([], HEADER)
    national = result["scopes"]["national"]
    assert national["rows"] == 0
    assert national["reconciliation_share"] == 0.0
    assert national["largest_identical_group"] == 0


# --- pre-registered decision rules -----------------------------------------------------

def test_decision_rules_fire_against_a_source_with_no_identity() -> None:
    """The outcome the Phase 1 plan pre-registered, so it cannot be rationalised later."""
    findings = analyse([row(J1772="1"), row(J1772="1")], HEADER)["findings"]
    assert findings["m7_stable_charging_unit_identity_recoverable"] is False
    assert findings["decision_ports_table_populated"] is False
    assert findings["decision_charging_unit_key_is_synthetic"] is True
    assert findings["decision_connector_grain"] == "(charging_unit_record_key, connector_type)"
    assert findings["decision_longitudinal_unit_identity_claimable"] is False


def test_decision_rules_invert_if_identity_ever_becomes_available() -> None:
    header = (*HEADER, "EVSE ID")
    findings = analyse([{**row(), "EVSE ID": "abc"}], header)["findings"]
    assert findings["m7_stable_charging_unit_identity_recoverable"] is True
    assert findings["decision_ports_table_populated"] is True
    assert findings["decision_connector_grain"] == "physical_connector_id"
    assert findings["decision_longitudinal_unit_identity_claimable"] is True


# --- JSON representation -----------------------------------------------------------------

def json_station(units: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": 1, "ev_charging_units": units}


def json_unit(port_count: int = 1, **connectors: int) -> dict[str, Any]:
    return {
        "network": "Non-Networked",
        "port_count": port_count,
        "charging_level": "2",
        "funding_sources": [],
        "connectors": {
            name: {"power_kw": None, "port_count": count}
            for name, count in (connectors or {"J1772": 1}).items()
        },
    }


def test_json_analysis_measures_unit_level_port_count() -> None:
    """The CSV carries station-level EVSE totals; only the JSON has unit-level counts."""
    result = analyse_station_json([json_station([json_unit(), json_unit()])])
    assert result["units"] == 2
    assert result["unit_level_port_count_share"] == 1.0
    assert result["total_ports_from_unit_port_count"] == 2


def test_json_analysis_finds_no_unit_identifier() -> None:
    result = analyse_station_json([json_station([json_unit()])])
    assert result["any_unit_identifier_in_network_metadata"] is False
    assert result["unit_object_keys"] == [
        "charging_level", "connectors", "funding_sources", "network", "port_count"
    ]


def test_json_analysis_detects_an_identifier_if_one_appears() -> None:
    unit = {**json_unit(), "evse_id": "X-1"}
    result = analyse_station_json([json_station([unit])])
    assert result["any_unit_identifier_in_network_metadata"] is True
    assert result["unit_identifier_keys_found"] == ["evse_id"]


def test_json_analysis_flags_connector_ports_exceeding_unit_port_count() -> None:
    unit = json_unit(port_count=1, CHADEMO=1, J1772COMBO=1)
    result = analyse_station_json([json_station([unit])])
    assert result["units_where_connector_ports_exceed_unit_port_count"] == 1
    assert result["connector_types_exposed"] == ["CHADEMO", "J1772COMBO"]


def test_json_analysis_counts_redundant_unit_objects() -> None:
    result = analyse_station_json([json_station([json_unit(), json_unit(), json_unit()])])
    assert result["distinct_unit_objects"] == 1
    assert result["redundant_unit_objects"] == 2
    assert result["largest_identical_unit_group"] == 3


def test_json_analysis_handles_a_station_with_no_units() -> None:
    result = analyse_station_json([{"id": 1}])
    assert result["stations"] == 1
    assert result["units"] == 0
    assert result["unit_level_port_count_share"] == 0.0


def test_json_analysis_handles_a_unit_with_no_connectors_block() -> None:
    unit = {"network": "X", "port_count": 1, "charging_level": "2"}
    result = analyse_station_json([json_station([unit])])
    assert result["units_with_connectors_block"] == 0
    assert result["connector_types_exposed"] == []


def test_json_analysis_handles_a_unit_with_no_port_count() -> None:
    unit = {"network": "X", "charging_level": "2", "connectors": {}}
    result = analyse_station_json([json_station([unit])])
    assert result["units_with_unit_level_port_count"] == 0


def test_analyse_file_streams_a_csv(tmp_path: Path) -> None:
    path = tmp_path / "units.csv"
    path.write_text(
        ",".join(HEADER) + "\n"
        + "1,E,public,Net,,1,,1,0,0,0,0\n"
        + "1,E,public,Net,,1,,1,0,0,0,0\n",
        encoding="utf-8",
    )
    result = analyse_file(path)
    assert result["scopes"]["national"]["rows"] == 2
    assert result["scopes"]["national"]["redundant_rows"] == 1
    assert result["findings"]["decision_charging_unit_key_is_synthetic"] is True


def test_a_row_with_no_reported_evse_levels_is_not_counted_as_reporting() -> None:
    """Some rows carry no L1/L2/DCFC totals at all; they must not fake a reconciliation."""
    result = analyse([row(l1="", l2="", dcfc="")], HEADER)
    national = result["scopes"]["national"]
    assert national["rows_with_level_totals"] == 0
    assert national["rows_with_level_totals_share"] == 0.0
    assert national["stations_row_count_reconciles_to_reported_evse"] == 0
