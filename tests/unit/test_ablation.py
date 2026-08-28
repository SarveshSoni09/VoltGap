"""The supply-feature ablation: permitted here, forbidden everywhere else."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.model.ablation import (
    ABLATION_FEATURE_NAMES,
    DCFC_LEVEL,
    L2_LEVEL,
    OPERATIONAL_STATUS,
    PUBLIC_ACCESS,
    SUPPLY_FEATURE_NAMES,
    SupplyByZip,
    assert_supply_features_are_absent,
    load_supply_by_zip,
    with_supply_features,
    zip_grain_panels,
)
from pipeline.model.demand import ModelRow
from pipeline.model.features import FEATURE_NAMES
from pipeline.model.panel import StatePanel
from pipeline.spatial.geography import SourceGeography
from pipeline.validation.scope import ExclusionLedger


def station(zip_code: str, level: str, ports: int, status: str = OPERATIONAL_STATUS,
            access: str = PUBLIC_ACCESS, station_id: int = 1) -> dict[str, object]:
    return {
        "id": station_id, "zip": zip_code, "status_code": status,
        "access_code": access,
        "ev_charging_units": [{"port_count": ports, "charging_level": level,
                               "connectors": {}}],
    }


def snapshot(tmp_path: Path, stations: list[dict[str, object]]) -> Path:
    path = tmp_path / "stations.json"
    path.write_text(json.dumps({"fuel_stations": stations}), encoding="utf-8")
    return path


def panel(state: str = "VT", geoids: tuple[str, ...] = ("05401", "05402"),
          geography: SourceGeography = SourceGeography.USPS_ZIP) -> StatePanel:
    rows = tuple(
        ModelRow(state, "zcta", geoid, 1000.0, 2500.0,
                 dict.fromkeys(FEATURE_NAMES, 0.5), 20.0)
        for geoid in geoids
    )
    return StatePanel(state, geography, "DMV Snapshot (1/1/2026)", rows,
                      ExclusionLedger(40, 40, {}, {}), True)


# --- the declared boundary ----------------------------------------------------------

def test_the_supply_features_are_named_and_kept_out_of_the_primary_set() -> None:
    assert set(SUPPLY_FEATURE_NAMES).isdisjoint(FEATURE_NAMES)
    assert_supply_features_are_absent()


def test_a_supply_feature_leaking_into_the_primary_set_is_refused() -> None:
    with pytest.raises(ValueError, match="D2 violation"):
        assert_supply_features_are_absent(
            (*FEATURE_NAMES, "dcfc_ports_per_1k_households"))


def test_the_ablation_feature_set_is_the_primary_set_plus_supply() -> None:
    assert (*FEATURE_NAMES, *SUPPLY_FEATURE_NAMES) == ABLATION_FEATURE_NAMES
    assert len(ABLATION_FEATURE_NAMES) == len(FEATURE_NAMES) + 3


# --- aggregation --------------------------------------------------------------------

def test_only_public_operational_supply_is_counted(tmp_path: Path) -> None:
    """G2: operational supply is status E only. G3: private stations are not public."""
    path = snapshot(tmp_path, [
        station("05401", DCFC_LEVEL, 4, station_id=1),
        station("05401", DCFC_LEVEL, 8, status="T", station_id=2),
        station("05401", DCFC_LEVEL, 16, access="private", station_id=3),
        station("05401", L2_LEVEL, 2, station_id=4),
    ])
    supply = load_supply_by_zip(path)
    assert supply.dcfc_ports == {"05401": 4.0}
    assert supply.l2_ports == {"05401": 2.0}
    assert supply.stations == {"05401": 2.0}


def test_a_station_with_an_unusable_zip_is_skipped(tmp_path: Path) -> None:
    path = snapshot(tmp_path, [station("", DCFC_LEVEL, 4),
                               station("05401", DCFC_LEVEL, 1, station_id=2)])
    assert load_supply_by_zip(path).dcfc_ports == {"05401": 1.0}


def test_a_charging_level_the_source_does_not_call_dc_or_l2_is_not_guessed(
    tmp_path: Path,
) -> None:
    """Level comes from the source's own field, never from a connector name."""
    path = snapshot(tmp_path, [station("05401", "1", 4), station("05401", "legacy", 9)])
    supply = load_supply_by_zip(path)
    assert supply.dcfc_ports == {}
    assert supply.l2_ports == {}
    assert supply.stations == {"05401": 1.0}


def test_a_station_is_counted_once_however_many_units_it_has(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"fuel_stations": [{
        "id": 7, "zip": "05401", "status_code": OPERATIONAL_STATUS,
        "access_code": PUBLIC_ACCESS,
        "ev_charging_units": [
            {"port_count": 1, "charging_level": DCFC_LEVEL, "connectors": {}},
            {"port_count": 1, "charging_level": DCFC_LEVEL, "connectors": {}},
        ],
    }]}), encoding="utf-8")
    supply = load_supply_by_zip(path)
    assert supply.dcfc_ports == {"05401": 2.0}
    assert supply.stations == {"05401": 1.0}


def test_supply_features_are_expressed_per_thousand_households() -> None:
    supply = SupplyByZip({"05401": 10.0}, {"05401": 4.0}, {"05401": 2.0})
    features = supply.features_for("05401", 1000.0)
    assert features["dcfc_ports_per_1k_households"] == pytest.approx(10.0)
    assert features["l2_ports_per_1k_households"] == pytest.approx(4.0)
    assert features["public_stations_per_1k_households"] == pytest.approx(2.0)


def test_an_area_with_no_households_reports_zero_rather_than_dividing_by_zero() -> None:
    supply = SupplyByZip({"05401": 10.0}, {}, {})
    assert supply.features_for("05401", 0.0)["dcfc_ports_per_1k_households"] == 0.0


def test_an_area_with_no_supply_reports_zero_supply_not_a_missing_feature() -> None:
    features = SupplyByZip({}, {}, {}).features_for("05401", 1000.0)
    assert set(features) == set(SUPPLY_FEATURE_NAMES)
    assert all(value == 0.0 for value in features.values())


# --- panel construction -------------------------------------------------------------

def test_an_ablated_panel_carries_both_feature_families() -> None:
    supply = SupplyByZip({"05401": 10.0}, {"05401": 4.0}, {"05401": 2.0})
    ablated = with_supply_features(panel(), supply)
    assert set(ablated.rows[0].features) == set(ABLATION_FEATURE_NAMES)
    assert ablated.rows[0].observed_bev == 20.0
    assert ablated.rows[1].features["dcfc_ports_per_1k_households"] == 0.0


def test_a_county_grain_state_is_refused_because_afdc_carries_no_county() -> None:
    with pytest.raises(ValueError, match="ZIP-grain states only"):
        with_supply_features(panel("MT", geography=SourceGeography.COUNTY),
                             SupplyByZip({}, {}, {}))


def test_only_independent_zip_grain_states_enter_the_comparison() -> None:
    panels = {
        "VT": panel("VT"),
        "MT": panel("MT", geography=SourceGeography.COUNTY),
        "WA": StatePanel("WA", SourceGeography.TRACT, "s", panel("WA").rows,
                         ExclusionLedger(40, 40, {}, {}), False),
    }
    primary, ablated = zip_grain_panels(panels, SupplyByZip({}, {}, {}))
    assert set(primary) == {"VT"}
    assert set(ablated) == {"VT"}
    assert set(ablated["VT"].rows[0].features) == set(ABLATION_FEATURE_NAMES)
