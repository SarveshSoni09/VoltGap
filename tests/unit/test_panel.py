"""Panel assembly: the out-of-state mailing ZIP defect, and joins that account for
every observed vehicle."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.model.features import FEATURE_NAMES
from pipeline.model.observed import ObservedCount, StateObservations
from pipeline.model.panel import (
    GEOGRAPHY_FOR_SOURCE,
    NON_INDEPENDENT_REASON,
    NON_INDEPENDENT_STATES,
    AreaTable,
    PanelError,
    build_area_table,
    build_panels,
    build_state_panel,
    default_land_area_path,
    load_area_tables,
    prediction_rows,
    state_resolver,
)
from pipeline.spatial.geography import SourceGeography
from pipeline.validation.scope import ExclusionLedger

T1, T2 = "53033000100", "53033000200"


def acs_row(geoid: str, households: str = "100", population: str = "250"
            ) -> dict[str, str]:
    row = {"geoid": geoid, "B25003_001E": households, "B01003_001E": population}
    for name in ("B19013_001E", "B19001_001E", "B25003_002E", "B25024_001E",
                 "B25024_002E", "B25024_003E", "B25044_001E", "B08301_001E",
                 "B08303_001E", "B15003_001E"):
        row.setdefault(name, "50")
    return row


def table(geoids: list[str], geography: str = "zcta",
          households: str = "100") -> AreaTable:
    return build_area_table(
        [acs_row(g, households) for g in geoids], geography,
        dict.fromkeys(geoids, 5.0),
    )


def observations(counts: list[tuple[str, int]], geography: SourceGeography,
                 state: str = "VT") -> StateObservations:
    rows = tuple(ObservedCount(state, geography, geoid, n, 0) for geoid, n in counts)
    return StateObservations(
        state, geography, "DMV Snapshot (1/1/2026)", rows,
        ExclusionLedger(sum(n for _, n in counts), sum(n for _, n in counts), {}, {}),
    )


# --- summary levels -----------------------------------------------------------------

def test_each_source_geography_maps_to_the_acs_level_that_serves_it() -> None:
    assert GEOGRAPHY_FOR_SOURCE[SourceGeography.USPS_ZIP] == "zcta"
    assert GEOGRAPHY_FOR_SOURCE[SourceGeography.COUNTY] == "county"
    assert GEOGRAPHY_FOR_SOURCE[SourceGeography.TRACT] == "tracts"


def test_a_zcta_reports_no_state_because_its_number_does_not_carry_one() -> None:
    assert state_resolver("zcta")("98101") == ""
    assert state_resolver("tracts")("53033000100") == "53"
    assert state_resolver("county")("53033") == "53"


def test_default_land_area_path_names_the_gazetteer_for_a_level() -> None:
    assert default_land_area_path("tracts").name == "gaz_tracts_2023.txt"


def test_an_area_table_records_imputation_counts_and_medians() -> None:
    built = table([T1, T2], "tracts")
    assert len(built) == 2
    assert set(built.rows) == {T1, T2}
    assert set(built.filled[T1]) == set(FEATURE_NAMES)
    # The count is the number of features this row could not compute, and it feeds the
    # uncertainty score, so it must equal what the row itself reports as missing.
    assert built.imputed_counts[T1] == len(built.rows[T1].missing_features)


# --- the out-of-state ZIP defect ----------------------------------------------------

def test_a_zip_outside_the_registering_state_is_excluded_by_name() -> None:
    """Oregon's export carries 00907 (Puerto Rico) and 10010 (Manhattan). Joining
    those to a like-numbered ZCTA imported 3.5 million out-of-state households."""
    areas = table(["05401", "10010"])
    panel = build_state_panel(
        observations([("05401", 40), ("10010", 3)], SourceGeography.USPS_ZIP),
        {"zcta": areas},
        {"05401": frozenset({"50"}), "10010": frozenset({"36"})},
    )
    assert [row.geoid for row in panel.rows] == ["05401"]
    assert panel.ledger.excluded["zip_outside_the_registering_state"] == 3
    assert "out-of-state mailing address" in panel.ledger.descriptions[
        "zip_outside_the_registering_state"]
    panel.ledger.assert_balanced()


def test_a_zip_touching_the_state_is_kept_even_if_it_straddles_a_border() -> None:
    areas = table(["05401"])
    panel = build_state_panel(
        observations([("05401", 40)], SourceGeography.USPS_ZIP),
        {"zcta": areas}, {"05401": frozenset({"50", "33"})},
    )
    assert len(panel.rows) == 1


def test_a_zip_with_no_like_numbered_zcta_is_reported_unallocatable() -> None:
    panel = build_state_panel(
        observations([("05401", 40)], SourceGeography.USPS_ZIP),
        {"zcta": table(["05401"])}, {},
    )
    assert panel.rows == ()
    assert panel.ledger.excluded["zip_has_no_like_numbered_zcta"] == 40


def test_an_observed_area_with_no_acs_record_is_excluded_by_name() -> None:
    panel = build_state_panel(
        observations([("05401", 40)], SourceGeography.USPS_ZIP),
        {"zcta": table(["05402"])}, {"05401": frozenset({"50"})},
    )
    assert panel.ledger.excluded["no_acs_area_for_geoid"] == 40


def test_an_area_with_no_households_cannot_carry_a_rate() -> None:
    panel = build_state_panel(
        observations([("05401", 40)], SourceGeography.USPS_ZIP),
        {"zcta": table(["05401"], households="0")}, {"05401": frozenset({"50"})},
    )
    assert panel.ledger.excluded["area_has_no_households"] == 40


def test_a_county_state_needs_no_zip_membership_check() -> None:
    panel = build_state_panel(
        observations([("50001", 12)], SourceGeography.COUNTY),
        {"county": table(["50001"], "county")},
    )
    assert len(panel.rows) == 1
    assert panel.observed_total == 12.0


def test_a_state_whose_summary_level_was_not_loaded_raises() -> None:
    with pytest.raises(PanelError, match="no ACS features loaded for county"):
        build_state_panel(observations([("50001", 1)], SourceGeography.COUNTY), {})


# --- independence -------------------------------------------------------------------

def test_washington_is_the_only_non_independent_state() -> None:
    assert {"WA"} == NON_INDEPENDENT_STATES
    assert NON_INDEPENDENT_REASON == "non_independent_preprocessing_selection_state"


def test_a_panel_reports_whether_it_may_enter_the_independent_aggregate() -> None:
    wa = build_state_panel(
        observations([(T1, 5)], SourceGeography.TRACT, "WA"),
        {"tracts": table([T1], "tracts")},
    )
    assert wa.is_independent is False
    assert wa.to_dict()["independent"] is False
    vt = build_state_panel(
        observations([("05401", 5)], SourceGeography.USPS_ZIP),
        {"zcta": table(["05401"])}, {"05401": frozenset({"50"})},
    )
    assert vt.is_independent is True


def test_build_panels_covers_every_supplied_state() -> None:
    panels = build_panels(
        {"VT": observations([("05401", 5)], SourceGeography.USPS_ZIP),
         "WA": observations([(T1, 9)], SourceGeography.TRACT, "WA")},
        {"zcta": table(["05401"]), "tracts": table([T1], "tracts")},
        {"05401": frozenset({"50"})},
    )
    assert set(panels) == {"VT", "WA"}
    assert panels["VT"].observed_total == 5.0


# --- prediction rows ----------------------------------------------------------------

def test_prediction_rows_carry_no_observed_count() -> None:
    rows = prediction_rows(table([T1, T2], "tracts"))
    assert [r.geoid for r in rows] == [T1, T2]
    assert all(r.observed_bev is None for r in rows)
    assert rows[0].state == "53"
    assert rows[0].geography == "tracts"


# --- loading ------------------------------------------------------------------------

def test_load_area_tables_reads_the_cached_summary_levels() -> None:
    tables = load_area_tables(states=("WA",))
    assert set(tables) == {"zcta", "county", "tracts"}
    assert len(tables["zcta"]) == 33772
    assert len(tables["county"]) == 3222
    assert len(tables["tracts"]) == 1784


def test_load_area_tables_omits_tracts_when_no_state_is_asked_for() -> None:
    tables = load_area_tables(states=())
    assert "tracts" not in tables


def test_build_area_table_falls_back_to_the_shipped_gazetteer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gazetteer = tmp_path / "gaz.txt"
    gazetteer.write_text("GEOID\tALAND\n53033000100\t1000000\n", encoding="utf-8")
    monkeypatch.setitem(
        __import__("pipeline.model.features", fromlist=["GAZETTEER"]).GAZETTEER,
        "tracts", gazetteer,
    )
    built = build_area_table([acs_row(T1)], "tracts")
    assert built.rows[T1].households == 100.0
    assert json.loads(json.dumps(built.medians)) == built.medians
