"""The published artifacts: what ships, and what the frontend is allowed to believe."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import pytest

from pipeline.export.access_points import (
    ACCESS_COLUMNS,
    build_access_points,
    gap_population,
    sensitivity_curve,
)
from pipeline.export.manifest import STALE_AFTER_DAYS, build_manifest
from pipeline.export.national import (
    HEX6_COLUMNS,
    NationalSurface,
    attach_access,
    attach_road_filter,
    cell_row,
    cell_tier,
    public_site_coordinates,
)
from pipeline.export.parquet import ExportError, WrittenArtifact, sha256_of, write_parquet
from pipeline.model.access import AccessThresholds
from pipeline.model.hexes import HexCell, HexSupply
from pipeline.model.uncertainty import COMPONENT_NAMES
from pipeline.spatial.h3_grid import PopulationPoint, cells_for_points

SEATTLE = (47.6062, -122.3321)
SPOKANE = (47.6588, -117.4260)


def hexcell(latitude: float, longitude: float, **kwargs: Any) -> HexCell:
    cell = cells_for_points([latitude], [longitude])[0]
    defaults: dict[str, Any] = {
        "h3_index": cell, "resolution": 6, "latitude": latitude,
        "longitude": longitude, "area_km2": 36.0, "demand_bev": 100.0,
        "population": 1000.0, "households": 400.0, "equity_population": 120.0,
        "tracts_contributing": 2, "largest_tract_share": 0.7,
        "uncertainty_score": 0.2,
        "uncertainty_components": dict.fromkeys(COMPONENT_NAMES, 0.2),
        "evidence_grain_share": {"native_tract": 1.0},
        "confidence_tier_share": {"A": 1.0},
        "value_provenance_share": {"observed_count": 1.0},
        "supply": HexSupply(station_count=1, dcfc_ports=2.0, l2_ports=4.0),
    }
    defaults.update(kwargs)
    return HexCell(**defaults)


# --- tiers: never geography, always Phase 3's rule ------------------------------------

def test_tier_comes_from_phase_3s_own_rule_not_a_restatement() -> None:
    anchored = hexcell(*SEATTLE, evidence_grain_share={"county_anchored": 1.0})
    assert cell_tier(anchored, 0.5) == "A"


def test_a_modelled_cell_below_the_threshold_is_tier_b() -> None:
    cell = hexcell(*SEATTLE, evidence_grain_share={"state_total_only": 1.0},
                   uncertainty_score=0.2)
    assert cell_tier(cell, 0.5) == "B"


def test_a_modelled_cell_above_the_threshold_is_tier_c() -> None:
    cell = hexcell(*SEATTLE, evidence_grain_share={"state_total_only": 1.0},
                   uncertainty_score=0.9)
    assert cell_tier(cell, 0.5) == "C"


def test_every_published_row_carries_its_tier_and_provenance() -> None:
    """§17: no modeled value ships without its uncertainty."""
    row = cell_row(hexcell(*SEATTLE), "53", 0.5)
    assert row["confidence_tier"] in {"A", "B", "C"}
    assert row["dominant_evidence_grain"]
    assert 0.0 <= float(row["sub_state_anchored_share"]) <= 1.0
    for column in HEX6_COLUMNS:
        if column not in {"km_to_nearest_dcfc_site", "km_to_nearest_public_site",
                          "km_to_nearest_primary_secondary_road", "passes_road_filter"}:
            assert column in row, column


# --- access ---------------------------------------------------------------------------

def test_access_distance_is_attached_to_every_row() -> None:
    rows = [cell_row(hexcell(*SEATTLE), "53", 0.5),
            cell_row(hexcell(*SPOKANE), "53", 0.5)]
    attach_access(rows, [SEATTLE], [SEATTLE])
    assert rows[0]["km_to_nearest_dcfc_site"] < 5.0
    assert rows[1]["km_to_nearest_dcfc_site"] > 100.0


def test_with_no_sites_anywhere_distance_is_infinite_not_missing() -> None:
    """D8: 'there is no charger anywhere' is the strongest access gap, not missing data."""
    rows = [cell_row(hexcell(*SEATTLE), "53", 0.5)]
    attach_access(rows, [], [])
    assert rows[0]["km_to_nearest_dcfc_site"] == float("inf")


def test_attaching_access_to_nothing_does_not_fail() -> None:
    attach_access([], [SEATTLE], [SEATTLE])


# --- the road filter, carried from Phase 4 --------------------------------------------

def test_the_road_filter_result_is_carried_into_the_artifact() -> None:
    """The browser cannot run Phase 4's road filter itself, so the pipeline ships the
    verdict. Without this the interactive candidate universe would silently differ from
    the one Phase 4 reasoned about."""
    rows = [cell_row(hexcell(*SEATTLE), "53", 0.5)]
    attach_road_filter(rows, "53")
    assert isinstance(rows[0]["passes_road_filter"], bool)
    assert rows[0]["km_to_nearest_primary_secondary_road"] >= 0.0


def test_attaching_the_road_filter_to_nothing_does_not_read_a_road_file() -> None:
    attach_road_filter([], "53")


# --- parquet --------------------------------------------------------------------------

def test_an_artifact_round_trips_through_parquet(tmp_path: Path) -> None:
    rows = [cell_row(hexcell(*SEATTLE), "53", 0.5)]
    attach_access(rows, [SEATTLE], [SEATTLE])
    attach_road_filter(rows, "53")
    path = tmp_path / "hex.parquet"
    artifact = write_parquet(rows, HEX6_COLUMNS, path)
    assert artifact.rows == 1
    assert artifact.bytes > 0
    assert artifact.sha256 == sha256_of(path)

    back = duckdb.sql(f"SELECT * FROM '{path}'").fetchall()
    names = [d[0] for d in duckdb.sql(f"SELECT * FROM '{path}' LIMIT 0").description]
    assert tuple(names) == HEX6_COLUMNS
    assert len(back) == 1


def test_an_empty_artifact_is_refused_rather_than_written(tmp_path: Path) -> None:
    """A zero-row artifact loads fine and renders an empty map, which is the failure
    mode hardest to notice from the browser."""
    with pytest.raises(ExportError, match="empty artifact"):
        write_parquet([], HEX6_COLUMNS, tmp_path / "x.parquet")


def test_a_row_missing_a_column_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ExportError, match="missing columns"):
        write_parquet([{"h3_index": "x"}], HEX6_COLUMNS, tmp_path / "x.parquet")


# --- access points --------------------------------------------------------------------

def point(tract: str, bg: str, lat: float, lon: float, pop: float) -> PopulationPoint:
    return PopulationPoint(tract_geoid=tract, block_group=bg, population=pop,
                           latitude=lat, longitude=lon)


def test_access_points_carry_both_distances_and_the_named_indicator() -> None:
    rows = build_access_points(
        {"53": [point("53033000100", "1", *SEATTLE, 500.0)]},
        [SEATTLE], [SPOKANE], {"53033000100": 0.25}, 6)
    assert len(rows) == 1
    assert rows[0]["block_group_geoid"] == "530330001001"
    assert rows[0]["km_to_nearest_dcfc_site"] < 1.0
    assert rows[0]["km_to_nearest_l2_site"] > 100.0
    assert rows[0]["income_share_under_35k"] == 0.25
    assert set(ACCESS_COLUMNS) <= set(rows[0])


def test_a_tract_with_no_indicator_gets_zero_not_a_guess() -> None:
    rows = build_access_points(
        {"53": [point("53033000100", "1", *SEATTLE, 500.0)]},
        [SEATTLE], [SEATTLE], {}, 6)
    assert rows[0]["income_share_under_35k"] == 0.0


def test_no_points_yields_no_rows() -> None:
    assert build_access_points({}, [SEATTLE], [SEATTLE], {}, 6) == []


def test_the_gap_population_is_the_same_arithmetic_the_browser_runs() -> None:
    rows = build_access_points(
        {"53": [point("53033000100", "1", *SEATTLE, 500.0),
                point("53033000200", "1", *SPOKANE, 300.0)]},
        [SEATTLE], [SEATTLE], {}, 6)
    assert gap_population(rows, 5.0) == 300.0
    assert gap_population(rows, 1000.0) == 0.0


def test_the_sensitivity_curve_is_monotone_in_the_threshold() -> None:
    rows = build_access_points(
        {"53": [point("53033000100", "1", *SEATTLE, 500.0),
                point("53033000200", "1", *SPOKANE, 300.0)]},
        [SEATTLE], [SEATTLE], {}, 6)
    thresholds = AccessThresholds(
        dcfc_gap_km=16.1, l2_gap_km=8.0, sensitivity_km=(1.0, 5.0, 50.0, 500.0),
        dcfc_levels=frozenset({"dc_fast"}), l2_levels=frozenset({"2"}),
        operational_status_codes=frozenset({"E"}),
        public_access_codes=frozenset({"public"}))
    curve = sensitivity_curve(rows, thresholds)
    values = [c["population_in_gap"] for c in curve]
    assert values == sorted(values, reverse=True)


# --- manifest -------------------------------------------------------------------------

def test_the_manifest_indexes_every_artifact_with_its_checksum(tmp_path: Path) -> None:
    artifact = WrittenArtifact("a.parquet", tmp_path / "a", 3, 99, "abc", ("x",))
    manifest = build_manifest([artifact], {"acs": "2024"}, {"demand": "Phase 3"},
                              {"cells": 5}, computed_at="2026-09-01T00:00:00+00:00")
    payload = manifest.to_dict()
    assert payload["artifacts"]["a.parquet"]["sha256"] == "abc"
    assert payload["source_vintages"] == {"acs": "2024"}
    assert payload["stale_after_days"] == STALE_AFTER_DAYS
    assert payload["computed_at"] == "2026-09-01T00:00:00+00:00"


def test_the_manifest_writes_and_reparses(tmp_path: Path) -> None:
    manifest = build_manifest([], {}, {}, {}, computed_at="2026-09-01T00:00:00+00:00")
    path = manifest.write(tmp_path / "manifest.json")
    assert json.loads(path.read_text())["computed_at"] == "2026-09-01T00:00:00+00:00"


def test_a_manifest_without_an_injected_timestamp_stamps_now() -> None:
    assert build_manifest([], {}, {}, {}).computed_at.endswith("+00:00")


# --- the surface summary --------------------------------------------------------------

def test_the_surface_reports_its_anchored_share_of_demand() -> None:
    rows = (
        {"demand_bev": 100.0, "sub_state_anchored_share": 1.0},
        {"demand_bev": 300.0, "sub_state_anchored_share": 0.0},
    )
    surface = NationalSurface(rows=rows, states=("53",), unallocated_demand=0.0,
                              source_vintages={})
    assert surface.demand_total == 400.0
    assert surface.sub_state_anchored_share_of_demand == pytest.approx(0.25)
    assert len(surface) == 2


def test_a_surface_with_no_demand_reports_zero_rather_than_dividing() -> None:
    surface = NationalSurface(rows=({"demand_bev": 0.0, "sub_state_anchored_share": 0.0},),
                              states=(), unallocated_demand=0.0, source_vintages={})
    assert surface.sub_state_anchored_share_of_demand == 0.0


def test_site_coordinates_are_deduplicated_per_station_not_per_unit_row() -> None:
    """G1: a station record is one network's presence at a site, and the export has many
    unit rows per station. Deduplication is by station id.

    Coordinates are NOT deduplicated, and must not be: 805 of the 82,056 public
    operational stations share exact coordinates with another station, and domain rule
    **G4** establishes that those are co-located multi-network infrastructure rather than
    duplicate records. Collapsing them would delete real sites.
    """
    dcfc, public = public_site_coordinates()
    assert len(public) == 82_056
    assert len(set(public)) == 81_251
    assert len(public) - len(set(public)) == 805
    assert len(dcfc) == 15_284
    assert len(dcfc) < len(public)


# --- the remaining branches -----------------------------------------------------------

def station(sid: str, lat: object, lon: object, status: str = "E",
            access: str = "public", level: str = "dc_fast") -> dict[str, Any]:
    """One AFDC station in the nested shape the real snapshot uses."""
    return {
        "id": sid, "status_code": status, "access_code": access,
        "latitude": lat, "longitude": lon,
        "ev_charging_units": [{"port_count": 1, "charging_level": level}],
    }


def test_a_station_with_unparseable_coordinates_is_skipped_not_placed_at_zero(
    tmp_path: Path,
) -> None:
    """A blank latitude coerced to 0.0 would put a site in the Gulf of Guinea and quietly
    shorten every access distance around it. It is skipped instead."""
    snapshot = tmp_path / "stations.json"
    snapshot.write_text(json.dumps({"fuel_stations": [
        station("good", 47.6, -122.3),
        station("blank", "", ""),
        station("private", 47.0, -122.0, access="private"),
        station("planned", 47.1, -122.1, status="P"),
        station("level2", 46.0, -121.0, level="2"),
    ]}))
    dcfc, public = public_site_coordinates(snapshot)
    # Public + operational only (G2, G3), and the unparseable one dropped.
    assert sorted(public) == [(46.0, -121.0), (47.6, -122.3)]
    # Only the DC fast one serves DCFC.
    assert dcfc == [(47.6, -122.3)]


def test_a_requested_state_with_no_estimates_is_skipped(tmp_path: Path) -> None:
    """build_national loops the states it is asked for. One contributing no tracts must
    be skipped rather than triggering a population-point read for nothing."""
    from pipeline.export.national import build_national
    from pipeline.model.build_demand import TractEstimate

    estimate = TractEstimate(
        geoid="50001960100", state_fips="50", households=400.0, population=1000.0,
        equity_population=120.0, raw_estimate=100.0, estimate=100.0,
        evidence_grain="state_total_only", estimate_method="modeled",
        uncertainty_score=0.3,
        uncertainty_components=dict.fromkeys(COMPONENT_NAMES, 0.3),
        confidence_tier="B", constraint_name="VT", constraint_vintage="2023",
        value_provenance="modelled")
    # Wyoming (56) is requested but contributes nothing; Vermont carries the surface.
    surface = build_national([estimate], {}, states=("56", "50"))
    assert surface.states == ("50",)
    assert len(surface) > 0


# --- human-readable place names, so nobody has to read an H3 index --------------------

def test_a_cell_row_is_complete_even_before_its_place_name_is_known() -> None:
    """`cell_row` cannot see the population weights, so it emits empty placeholders and
    `build_national` fills them. A partial row would fail the parquet writer's column
    check a long way from the cause."""
    row = cell_row(hexcell(*SEATTLE), "53", 0.5)
    assert row["county_name"] == ""
    assert row["state_code"] == ""
    assert row["county_population_share"] == 0.0


def test_county_names_load_from_the_census_reference() -> None:
    from pipeline.export.national import load_county_names

    counties = load_county_names()
    assert len(counties) > 3_000
    assert counties["53033"] == ("King County", "WA")
    assert counties["06037"] == ("Los Angeles County", "CA")


def test_the_dominant_county_is_the_one_with_the_most_population() -> None:
    """A resolution-6 cell can straddle a county line, so the label names the county that
    dominates and records by how much rather than implying the cell sits in one."""
    from pipeline.export.national import dominant_counties
    from pipeline.spatial.h3_grid import TractCellWeights

    counties = {"53033": ("King County", "WA"), "53053": ("Pierce County", "WA")}
    weights = {
        "a": TractCellWeights("53033000100", {"cellX": 1.0}, 900.0),
        "b": TractCellWeights("53053000100", {"cellX": 1.0}, 100.0),
    }
    result = dominant_counties(weights, counties)
    name, state, share = result["cellX"]
    assert (name, state) == ("King County", "WA")
    assert share == pytest.approx(0.9)


def test_an_unknown_county_yields_an_empty_label_rather_than_a_guess() -> None:
    from pipeline.export.national import dominant_counties
    from pipeline.spatial.h3_grid import TractCellWeights

    weights = {"a": TractCellWeights("99999000100", {"cellY": 1.0}, 10.0)}
    name, state, _share = dominant_counties(weights, {})["cellY"]
    assert name == ""
    assert state == ""


def test_a_malformed_county_line_is_skipped_not_guessed(tmp_path: Path) -> None:
    """The reference file ends with a blank line, and a short line would otherwise raise
    mid-parse and take the whole export with it."""
    from pipeline.export.national import load_county_names

    reference = tmp_path / "counties.txt"
    reference.write_text(
        "STATE|STATEFP|COUNTYFP|COUNTYNS|COUNTYNAME|CLASSFP|FUNCSTAT\n"
        "WA|53|033|00161526|King County|H1|A\n"
        "truncated|row\n"
        "\n",
        encoding="utf-8",
    )
    counties = load_county_names(reference)
    assert counties == {"53033": ("King County", "WA")}
