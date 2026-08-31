"""Observed sub-state registrations: declared geographies, the BEV target, and ledgers."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from pipeline.model.observed import (
    ATLAS_STATE_CODES,
    JURISDICTION_FIPS,
    NATIONAL_TOTAL_LABELS,
    STATE_FIPS,
    STATE_GEOGRAPHY,
    ObservationError,
    _parse_count,
    latest_snapshot_label,
    latest_state_totals,
    load_all,
    load_atlas_state,
    load_state_totals,
    load_washington,
)
from pipeline.spatial.geography import EstimateMethod, EvidenceGrain, SourceGeography

HEADER = ('State,ZIP Code,Registration Date,Vehicle Make,Vehicle Model,'
          'Vehicle Model Year,Drivetrain Type,Vehicle GVWR Class,'
          'Vehicle GVWR Category,Vehicle Count,DMV Snapshot ID,'
          'DMV Snapshot (Date),Latest DMV Snapshot Flag')
COUNTY_HEADER = HEADER.replace("ZIP Code", "County")


def atlas_csv(path: Path, rows: list[str], header: str = HEADER) -> Path:
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return path


def row(area: str, drivetrain: str = "BEV", count: int = 1, latest: str = "True",
        snapshot: str = "DMV Snapshot (1/1/2026)", state: str = "VT") -> str:
    return (f'{state},{area},1/1/2024,TESLA,"MODEL 3, LONG RANGE",2024,{drivetrain},'
            f'1,Light-Duty (Class 1-2A),{count},9,{snapshot},{latest}')


# --- declarations -------------------------------------------------------------------

def test_every_state_declares_its_source_geography_explicitly() -> None:
    """CLAUDE.md 7.5.1: the geography is declared, never inferred from a column name."""
    assert len(STATE_GEOGRAPHY) == 15
    assert sum(1 for g in STATE_GEOGRAPHY.values()
               if g is SourceGeography.USPS_ZIP) == 11
    assert sum(1 for g in STATE_GEOGRAPHY.values()
               if g is SourceGeography.COUNTY) == 3
    assert STATE_GEOGRAPHY["WA"] is SourceGeography.TRACT


def test_every_declared_state_has_a_fips_code_and_atlas_excludes_washington() -> None:
    assert set(STATE_GEOGRAPHY) <= set(STATE_FIPS)
    assert "WA" not in ATLAS_STATE_CODES
    assert len(ATLAS_STATE_CODES) == 14


def test_the_jurisdiction_table_covers_fifty_states_and_dc() -> None:
    assert len(JURISDICTION_FIPS) == 51
    assert JURISDICTION_FIPS["District of Columbia"] == "11"


def test_the_published_national_row_is_named_so_g8_can_remove_it() -> None:
    assert {"United States", "Total"} == NATIONAL_TOTAL_LABELS


# --- Atlas extraction ---------------------------------------------------------------

def test_a_zip_state_counts_only_the_latest_snapshot_and_only_bev(
    tmp_path: Path,
) -> None:
    path = atlas_csv(tmp_path / "VT.csv", [
        row("05401", count=10),
        row("05401", "PHEV", count=4),
        row("05402", count=7),
        row("05401", count=99, latest="False",
            snapshot="DMV Snapshot (1/1/2020)"),
        row("05401", "HEV", count=3),
    ])
    observed = load_atlas_state("VT", path.parent)
    assert observed.vintage_label == "DMV Snapshot (1/1/2026)"
    assert {c.geography_id: c.bev_count for c in observed.counts} == {
        "05401": 10, "05402": 7}
    assert observed.total_bev == 17
    ledger = observed.ledger
    assert ledger.retrieved == 123
    assert ledger.excluded["superseded_snapshot"] == 99
    assert ledger.excluded["plug_in_hybrid_not_the_target"] == 4
    assert ledger.excluded["drivetrain_not_plug_in"] == 3
    ledger.assert_balanced()


def test_the_quoted_model_field_containing_a_comma_parses(tmp_path: Path) -> None:
    """Virginia's export has "JEST ELECTRIC, JEST EV, E-JEST"; auto-detected quoting
    read that row as 14 columns and failed the whole file."""
    path = atlas_csv(tmp_path / "VT.csv", [row("05401", count=5)])
    assert load_atlas_state("VT", path.parent).total_bev == 5


def test_a_phev_count_is_carried_alongside_rather_than_discarded(
    tmp_path: Path,
) -> None:
    path = atlas_csv(tmp_path / "VT.csv",
                     [row("05401", count=6), row("05401", "PHEV", count=2)])
    observed = load_atlas_state("VT", path.parent)
    assert observed.counts[0].bev_count == 6
    assert observed.counts[0].phev_count == 2


def test_an_unusable_zip_is_excluded_by_name(tmp_path: Path) -> None:
    path = atlas_csv(tmp_path / "VT.csv", [row("05401", count=4), row("", count=3)])
    observed = load_atlas_state("VT", path.parent)
    assert observed.ledger.excluded["geography_unresolvable"] == 3
    assert observed.total_bev == 4


def test_a_county_state_resolves_names_to_fips_and_never_guesses(
    tmp_path: Path,
) -> None:
    path = atlas_csv(tmp_path / "MT.csv", [
        row("Lewis and Clark", count=5, state="MT"),
        row("Nowhere", count=2, state="MT"),
    ], header=COUNTY_HEADER)
    observed = load_atlas_state("MT", path.parent)
    assert observed.source_geography is SourceGeography.COUNTY
    assert [c.geography_id for c in observed.counts] == ["30049"]
    assert observed.ledger.excluded["geography_unresolvable"] == 2


def test_an_observation_reports_its_grain_and_never_claims_more(tmp_path: Path) -> None:
    path = atlas_csv(tmp_path / "VT.csv", [row("05401", count=4)])
    count = load_atlas_state("VT", path.parent).counts[0]
    assert count.evidence_grain is EvidenceGrain.ZIP_ANCHORED
    assert count.estimate_method is EstimateMethod.DIRECTLY_OBSERVED


def test_a_missing_export_raises_rather_than_being_skipped(tmp_path: Path) -> None:
    with pytest.raises(ObservationError, match="reported as unavailable"):
        load_atlas_state("VT", tmp_path)


def test_washington_is_not_an_atlas_state(tmp_path: Path) -> None:
    with pytest.raises(ObservationError, match="not an Atlas state"):
        load_atlas_state("WA", tmp_path)


def test_a_file_with_no_latest_flag_raises(tmp_path: Path) -> None:
    path = atlas_csv(tmp_path / "VT.csv", [row("05401", latest="False")])
    with pytest.raises(ObservationError, match="no rows carry the latest-snapshot flag"):
        latest_snapshot_label(path, duckdb.connect())


def test_two_snapshot_labels_flagged_latest_is_an_ambiguous_vintage(
    tmp_path: Path,
) -> None:
    path = atlas_csv(tmp_path / "VT.csv", [
        row("05401", snapshot="DMV Snapshot (1/1/2026)"),
        row("05402", snapshot="DMV Snapshot (2/2/2026)"),
    ])
    with pytest.raises(ObservationError, match="ambiguous"):
        latest_snapshot_label(path, duckdb.connect())


# --- Washington ---------------------------------------------------------------------

def wa_json(path: Path, records: list[dict[str, str]]) -> Path:
    path.write_text(json.dumps(records), encoding="utf-8")
    return path


def test_washington_counts_bev_by_tract_and_accounts_for_the_rest(
    tmp_path: Path,
) -> None:
    path = wa_json(tmp_path / "wa.json", [
        {"_2020_census_tract": "53033000100",
         "ev_type": "Battery Electric Vehicle (BEV)"},
        {"_2020_census_tract": "53033000100",
         "ev_type": "Battery Electric Vehicle (BEV)"},
        {"_2020_census_tract": "53033000100",
         "ev_type": "Plug-in Hybrid Electric Vehicle (PHEV)"},
        {"_2020_census_tract": "41051000100",
         "ev_type": "Battery Electric Vehicle (BEV)"},
        {"_2020_census_tract": "bad", "ev_type": "Battery Electric Vehicle (BEV)"},
        {"_2020_census_tract": "53033000200", "ev_type": "Diesel"},
    ])
    observed = load_washington(path)
    assert observed.source_geography is SourceGeography.TRACT
    assert observed.total_bev == 2
    assert observed.counts[0].phev_count == 1
    assert observed.ledger.excluded == {
        "plug_in_hybrid_not_the_target": 1, "tract_outside_state": 1,
        "tract_unusable": 1, "drivetrain_not_plug_in": 1,
    }
    observed.ledger.assert_balanced()


def test_a_missing_washington_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ObservationError, match="records missing"):
        load_washington(tmp_path / "absent.json")


def test_load_all_reads_each_state_at_its_declared_geography(tmp_path: Path) -> None:
    atlas_csv(tmp_path / "VT.csv", [row("05401", count=3)])
    wa = wa_json(tmp_path / "wa.json", [
        {"_2020_census_tract": "53033000100",
         "ev_type": "Battery Electric Vehicle (BEV)"}])
    out = load_all(("VT", "WA"), tmp_path, wa)
    assert out["VT"].total_bev == 3
    assert out["WA"].total_bev == 1
    assert out["VT"].to_dict()["evidence_grain"] == "zip_anchored"


# --- state totals -------------------------------------------------------------------

def test_state_totals_load_every_vintage_for_every_jurisdiction() -> None:
    series = load_state_totals()
    assert len(series) == 51
    vintages = {t.vintage for rows in series.values() for t in rows}
    assert vintages == {str(y) for y in range(2016, 2026)}


def test_state_totals_can_be_restricted_to_a_vintage() -> None:
    series = load_state_totals(vintages=("2023",))
    assert {t.vintage for rows in series.values() for t in rows} == {"2023"}


def test_the_latest_vintage_is_chosen_per_jurisdiction() -> None:
    latest = latest_state_totals()
    assert latest["53"].jurisdiction == "Washington"
    assert latest["53"].vintage == "2025"
    assert latest_state_totals(vintage="2023")["53"].vintage == "2023"


def test_a_thousands_separator_parses_and_a_blank_does_not() -> None:
    assert _parse_count("13,047") == 13047
    assert _parse_count("") is None
    assert _parse_count(None) is None
    assert _parse_count("n/a") is None


def registration_html(rows: str) -> bytes:
    return (b"<table><tr><th>State</th><th>Electric (EV)</th>"
            b"<th>Plug-In Hybrid Electric (PHEV)</th></tr>"
            + rows.encode("utf-8") + b"</table>")


def test_the_published_national_total_row_is_removed_here_not_at_retrieval() -> None:
    """G8 and amendment A15: the adapter ingests it; the model layer drops it."""
    from tests.conftest import FakeFetcher

    body = registration_html(
        "<tr><td>Washington</td><td>236,400</td><td>41,200</td></tr>"
        "<tr><td>United States</td><td>5,689,100</td><td>0</td></tr>"
    )
    series = load_state_totals(FakeFetcher([body] * 10))
    assert set(series) == {"53"}
    assert series["53"][0].bev_count == 236400


def test_a_row_whose_bev_count_will_not_parse_is_skipped_not_defaulted() -> None:
    from tests.conftest import FakeFetcher

    body = registration_html(
        "<tr><td>Washington</td><td></td><td>41,200</td></tr>"
        "<tr><td>Oregon</td><td>98,000</td><td></td></tr>"
    )
    series = load_state_totals(FakeFetcher([body] * 10))
    assert set(series) == {"41"}
    assert series["41"][0].phev_count == 0


def test_no_usable_totals_at_all_raises_rather_than_returning_empty() -> None:
    from tests.conftest import FakeFetcher

    body = registration_html("<tr><td>Atlantis</td><td>1</td><td>1</td></tr>")
    with pytest.raises(ObservationError, match=r"cannot be\s+reconciled"):
        load_state_totals(FakeFetcher([body] * 10))


def test_asking_for_a_vintage_that_does_not_exist_yields_no_jurisdictions() -> None:
    assert latest_state_totals(vintage="1999") == {}


def test_an_unbalanced_geography_ledger_raises_rather_than_publishing() -> None:
    from pipeline.model.observed import GeographyResolution

    broken = GeographyResolution(
        total_records=100, in_jurisdiction_records=80, out_of_jurisdiction_records=5,
        in_jurisdiction_placed=80, invalid_tract_format=0,
        tract_not_in_jurisdiction_geography=0)
    with pytest.raises(ObservationError, match="geography ledger does not balance"):
        broken.assert_balanced()
    with pytest.raises(ObservationError):
        broken.to_dict()


def test_a_well_formed_geoid_naming_no_real_tract_is_excluded_by_name(
    tmp_path: Path,
) -> None:
    """An in-state, 11-digit GEOID that names no tract in the current Census geography
    cannot be placed, and must not be silently counted."""
    path = wa_json(tmp_path / "wa.json", [
        {"_2020_census_tract": "53033000100",
         "ev_type": "Battery Electric Vehicle (BEV)", "state": "WA"},
        {"_2020_census_tract": "53033999999",
         "ev_type": "Battery Electric Vehicle (BEV)", "state": "WA"},
    ])
    observed = load_washington(path, known_tracts=["53033000100"])
    assert observed.total_bev == 1
    assert observed.ledger.excluded["tract_not_in_census_geography"] == 1
    assert observed.resolution is not None
    # The unplaceable record keeps the source from licensing zero-completion.
    assert observed.resolution.unresolved_in_jurisdiction == 1
    assert observed.resolution.fully_resolved is False
    assert observed.resolution.tract_not_in_jurisdiction_geography == 1
