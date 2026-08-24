"""One regression test per domain rule G1-G14 (CLAUDE.md section 5, section 14).

These lock properties of the UPSTREAM DATA, not preferences. Each is asserted against
the frozen seed fixtures, whose expectations never drift with the live source, or
against the two-state canonical build.

G9 is the corrected rule (CLAUDE.md section 19 A1); the original was disproved by
Phase 0 and rewritten through docs/reports/PLAN_CHANGE_0.md.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal

import pandas as pd
import pytest

from pipeline.config.settings import PATHS
from pipeline.quality.registration_checks import (
    Confidence,
    DefectKind,
    ReviewFlag,
    assign_confidence,
    check_registrations,
    screen_per_capita,
    screen_year_over_year,
)

Loader = Callable[[str], pd.DataFrame]
NATIONAL = "seed_afdc_stations_national_20241211"


def to_int(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0).astype(int)


# --- G1 -----------------------------------------------------------------------------

def test_g1_station_rows_are_not_capacity(seed_frame: Loader) -> None:
    """A record with one Level 2 plug and one with forty DC stalls are both one row."""
    frame = seed_frame(NATIONAL)
    ports = (to_int(frame["EV Level1 EVSE Num"])
             + to_int(frame["EV Level2 EVSE Num"])
             + to_int(frame["EV DC Fast Count"]))
    assert len(frame) == 79_618
    assert int(ports.sum()) == 228_662
    assert int(ports.max()) > 1, "some single rows carry many ports"
    ratio = int(ports.sum()) / len(frame)
    assert ratio > 2.8, (
        f"counting rows as capacity understates supply by {ratio:.2f}x"
    )


def test_g1_mart_capacity_comes_from_units_not_station_rows(fixture_warehouse) -> None:  # type: ignore[no-untyped-def]
    sites = fixture_warehouse.fetch_df("mart_sites")
    assert (sites["charging_unit_count"] >= sites["station_count"]).all()
    assert sites["charging_unit_count"].sum() > sites["station_count"].sum()


# --- G2 -----------------------------------------------------------------------------

def test_g2_status_code_has_three_values_with_known_counts(seed_frame: Loader) -> None:
    counts = seed_frame(NATIONAL)["Status Code"].value_counts().to_dict()
    assert set(counts) == {"E", "T", "P"}
    assert counts["E"] == 73_972
    assert counts["T"] == 5_217
    assert counts["P"] == 429


def test_g2_only_status_e_is_operational_supply(fixture_warehouse) -> None:  # type: ignore[no-untyped-def]
    stations = fixture_warehouse.fetch_df("mart_stations")
    assert (stations.loc[stations["is_operational"], "status_code"] == "E").all()
    assert not stations.loc[stations["status_code"] != "E", "is_operational"].any()


# --- G3 -----------------------------------------------------------------------------

def test_g3_private_stations_exist_and_are_not_public_supply(seed_frame: Loader) -> None:
    counts = seed_frame(NATIONAL)["Access Code"].value_counts().to_dict()
    assert counts["private"] == 4_662
    assert counts["public"] == 74_956


def test_g3_public_operational_requires_both_flags(fixture_warehouse) -> None:  # type: ignore[no-untyped-def]
    stations = fixture_warehouse.fetch_df("mart_stations")
    both = stations["is_operational"] & stations["is_public"]
    assert (stations["is_public_operational"] == both).all()


# --- G4 -----------------------------------------------------------------------------

def test_g4_exact_coordinate_duplicates_exist_in_the_snapshot(seed_frame: Loader) -> None:
    frame = seed_frame(NATIONAL)
    duplicated = frame.duplicated(subset=["Latitude", "Longitude"], keep="first")
    assert int(duplicated.sum()) == 1_756


def test_g4_coordinate_duplicates_are_aggregated_into_one_site_not_deleted(
    fixture_warehouse,  # type: ignore[no-untyped-def]
) -> None:
    """They are co-located multi-network infrastructure, not duplicate records."""
    stations = fixture_warehouse.fetch_df("mart_stations")
    sites = fixture_warehouse.fetch_df("mart_sites")
    # Nothing was deleted: every station still has a row and a site.
    assert stations["station_id"].is_unique
    assert stations["site_id"].notna().all()
    # Aggregation happened: there are fewer sites than stations.
    assert len(sites) < len(stations)
    multi = sites[sites["station_count"] > 1]
    assert len(multi) > 0, "co-located stations must share a site"
    # Ports are summed across the site, not taken from one station.
    assert (multi["charging_unit_count"] >= multi["station_count"]).all()


def test_g4_site_ids_come_from_clustering_not_coordinate_rounding() -> None:
    """Rounding creates arbitrary grid-boundary splits; clustering does not."""
    from pipeline.spatial.clustering import cluster_sites

    # Two points 8 m apart that straddle a 3-decimal rounding boundary.
    assignments = cluster_sites(["a", "b"], [44.90049, 44.90056], [-93.0, -93.0])
    assert assignments[0].site_id == assignments[1].site_id
    assert round(44.90049, 3) != round(44.90056, 3), "they do straddle the boundary"


# --- G5, G6, G7 (IEA) ---------------------------------------------------------------

def test_g5_iea_category_has_three_values_and_summing_scenarios_double_counts(
    seed_frame: Loader,
) -> None:
    frame = seed_frame("seed_iea_global_ev_2024")
    assert set(frame["category"].unique()) == {
        "Historical", "Projection-STEPS", "Projection-APS"
    }
    usa = frame[(frame["region"] == "USA") & (frame["parameter"] == "EV sales")
                & (frame["category"] != "Historical")]
    usa_2035 = usa[usa["year"] == "2035"]
    summed = pd.to_numeric(usa_2035["value"], errors="coerce").sum()
    assert summed > 20_000_000, (
        f"summing STEPS and APS gives {summed:,.0f}, which exceeds total annual US "
        "light vehicle sales and is not a real figure"
    )
    per_scenario = usa_2035.groupby("category")["value"].apply(
        lambda s: pd.to_numeric(s, errors="coerce").sum()
    )
    assert len(per_scenario) == 2
    assert all(v < summed for v in per_scenario)


def test_g6_iea_usa_projection_years_are_only_2025_2030_2035(seed_frame: Loader) -> None:
    frame = seed_frame("seed_iea_global_ev_2024")
    usa = frame[(frame["region"] == "USA") & (frame["category"] != "Historical")]
    assert set(usa["year"].unique()) == {"2025", "2030", "2035"}


def test_g7_iea_mode_has_four_values(seed_frame: Loader) -> None:
    modes = set(seed_frame("seed_iea_global_ev_2024")["mode"].unique())
    assert modes == {"Cars", "Buses", "Trucks", "Vans"}


# --- G8 -----------------------------------------------------------------------------

def test_g8_seed_file_contains_a_total_row_that_equals_the_jurisdiction_sum(
    seed_frame: Loader,
) -> None:
    frame = seed_frame("seed_state_ev_registrations")
    total_row = frame[frame["State"] == "Total"]
    assert len(total_row) == 1
    total = int(total_row["Registration Count"].iloc[0])
    states = frame[frame["State"] != "Total"]
    assert len(states) == 51
    assert int(to_int(states["Registration Count"]).sum()) == total == 3_555_445


def test_g8_total_rows_never_reach_the_mart(fixture_warehouse) -> None:  # type: ignore[no-untyped-def]
    """The adapter ingests the total row (A15); intermediate removes it."""
    raw = fixture_warehouse.connection.execute(
        "SELECT count(*) FROM raw_afdc_state_ev_registrations "
        "WHERE \"State\" = 'United States'"
    ).fetchone()[0]
    assert raw == 10, "the adapter must preserve one total row per vintage"

    mart = fixture_warehouse.fetch_df("mart_state_totals")
    assert not mart["state"].isin(["United States", "Total"]).any()
    assert len(mart) == 510, "51 jurisdictions x 10 vintages"


def test_g8_counts_are_labelled_stock_never_sales(fixture_warehouse) -> None:  # type: ignore[no-untyped-def]
    mart = fixture_warehouse.fetch_df("mart_state_totals")
    assert (mart["measure_type"] == "stock").all()


# --- G9 (corrected) -----------------------------------------------------------------
# Seven properties, per docs/reports/PLAN_CHANGE_0.md section 8.

def seed_counts(loader: Loader) -> tuple[dict[str, int], int]:
    frame = loader("seed_state_ev_registrations")
    counts = {
        str(r["State"]): int(r["Registration Count"])
        for _, r in frame.iterrows()
    }
    return {k: v for k, v in counts.items() if k != "Total"}, counts["Total"]


def test_g9_property_1_vintage_is_resolved(seed_frame: Loader) -> None:
    counts, total = seed_counts(seed_frame)
    assert check_registrations(counts, vintage="2023", published_total=total
                               ).vintage_resolved is True
    assert check_registrations(counts, vintage=None).vintage_resolved is False


def test_g9_property_1_the_delivered_file_resolves_to_the_2023_afdc_vintage(
    seed_frame: Loader, fixture_warehouse,  # type: ignore[no-untyped-def]
) -> None:
    """Phase 0's dating, re-derived: 51/51 jurisdictions match after half-up rounding."""
    counts, _ = seed_counts(seed_frame)
    afdc = fixture_warehouse.connection.execute(
        "SELECT state, ev_count FROM mart_state_totals WHERE vintage = '2023'"
    ).fetchall()
    published = {str(r[0]): int(r[1]) for r in afdc}

    def half_up(value: int) -> int:
        return int((Decimal(value) / 100).quantize(Decimal("1"),
                                                   rounding=ROUND_HALF_UP) * 100)

    matches = [s for s in counts if published.get(s) == half_up(counts[s])]
    assert len(matches) == 51, f"only {len(matches)}/51 matched the 2023 vintage"
    assert counts["Oregon"] == 64_361, "the original G9 asserted 6,436; it is 64,361"
    assert counts["Oregon"] > counts["Kansas"] > counts["Iowa"]


def test_g9_property_2_jurisdiction_coverage_is_complete(seed_frame: Loader) -> None:
    counts, total = seed_counts(seed_frame)
    result = check_registrations(counts, vintage="2023", published_total=total)
    assert result.jurisdictions_present == 51
    assert result.coverage_complete is True

    incomplete = check_registrations({k: v for k, v in list(counts.items())[:40]},
                                     vintage="2023")
    assert incomplete.coverage_complete is False
    assert incomplete.passed is False


def test_g9_property_3_counts_must_be_non_negative() -> None:
    result = check_registrations({"Oregon": -5, "Iowa": 10}, vintage="2023",
                                 expected_jurisdictions=["Oregon", "Iowa"])
    assert result.all_counts_non_negative is False
    assert result.negative_jurisdictions == ("Oregon",)
    assert result.passed is False


def test_g9_property_4_published_total_reconciles(seed_frame: Loader) -> None:
    counts, total = seed_counts(seed_frame)
    assert check_registrations(counts, vintage="2023",
                               published_total=total).total_reconciles is True
    assert check_registrations(counts, vintage="2023",
                               published_total=total + 1).total_reconciles is False
    # A dataset with no published total is not a failure; it is simply not checkable.
    assert check_registrations(counts, vintage="2023").total_reconciles is None


def test_g9_property_5_anomaly_screening_executes(seed_frame: Loader) -> None:
    counts, total = seed_counts(seed_frame)
    population = dict.fromkeys(counts, 1_000_000)
    population["California"] = 39_000_000
    result = check_registrations(counts, vintage="2023", published_total=total,
                                 population=population)
    assert isinstance(result.review_flags, tuple)
    # The screen ran; whether it flagged anything is data-dependent.
    assert screen_per_capita({"a": 10, "b": 11, "c": 12, "d": 5_000},
                             dict.fromkeys("abcd", 100))


def test_g9_property_5_year_over_year_screening_executes() -> None:
    flags = screen_year_over_year({"Oregon": 90_000}, {"Oregon": 10_000})
    assert [f.screen for f in flags] == ["year_over_year"]
    assert "9.00x" in flags[0].detail


def test_g9_property_6_anomalies_surface_as_diagnostic_review_flags() -> None:
    flags = screen_per_capita({"a": 10, "b": 11, "c": 12, "d": 5_000},
                              dict.fromkeys("abcd", 100))
    assert flags, "an extreme outlier must be flagged"
    for flag in flags:
        assert flag.to_dict()["is_diagnostic_only"] is True


def test_g9_property_6_review_flags_do_not_fail_the_structural_check(
    seed_frame: Loader,
) -> None:
    counts, total = seed_counts(seed_frame)
    population = dict.fromkeys(counts, 100)
    result = check_registrations(counts, vintage="2023", published_total=total,
                                 population=population)
    assert result.review_flags, "this population makes California a huge outlier"
    assert result.passed is True, "a review flag is not a structural failure"


def test_g9_property_7_low_confidence_cannot_come_from_unusualness_alone() -> None:
    """The load-bearing correction: an outlier is a diagnostic, not proof of a defect.

    A state's genuine EV adoption rate may differ sharply from its neighbours because
    of income, incentives, urbanisation, housing structure, climate, electricity
    prices or market maturity. Downgrading it would push a fabricated quality signal
    into the uncertainty model.
    """
    flags = [
        ReviewFlag("Oregon", "per_capita_z", "5.9 sd from the mean", 5.9),
        ReviewFlag("Oregon", "year_over_year", "9.00x between vintages", 9.0),
    ]
    assert assign_confidence("Oregon", flags) is Confidence.OK
    assert assign_confidence("Oregon", flags, []) is Confidence.OK


@pytest.mark.parametrize("defect", list(DefectKind))
def test_g9_property_7_low_confidence_requires_a_corroborating_defect(
    defect: DefectKind,
) -> None:
    assert assign_confidence("Oregon", [], [defect]) is Confidence.LOW


def test_g9_a_stray_total_row_is_treated_as_a_coverage_defect() -> None:
    counts = {f"S{i}": 1 for i in range(51)}
    result = check_registrations({**counts, "United States": 51}, vintage="2023")
    assert result.coverage_complete is False
    assert any("UNEXPECTED_TOTAL_ROW" in m for m in result.missing_jurisdictions)


# --- G10 ----------------------------------------------------------------------------

def test_g10_open_dates_span_1995_to_the_snapshot_and_some_are_absent(
    seed_frame: Loader,
) -> None:
    """AFDC documents that some dates are approximate or reflect feed first-appearance."""
    dates = pd.to_datetime(seed_frame(NATIONAL)["Open Date"], errors="coerce")
    assert int(dates.isna().sum()) == 455
    assert dates.min().year == 1995
    assert dates.max().year == 2024


# --- G11 ----------------------------------------------------------------------------

def test_g11_a_snapshot_plus_open_date_cannot_reconstruct_a_historical_network(
    seed_frame: Loader, fixture_warehouse,  # type: ignore[no-untyped-def]
) -> None:
    """Reconstruction is survivorship-biased: closures and removals are invisible."""
    frame = seed_frame(NATIONAL)
    dates = pd.to_datetime(frame["Open Date"], errors="coerce")
    # A backwards reconstruction is monotonically non-increasing by construction: it
    # can only ever lose stations going back in time, never gain them. That is the
    # bias, and it is why the output must be labelled an approximate reconstruction.
    counts = [int((dates <= pd.Timestamp(f"{year}-12-31")).sum())
              for year in (2018, 2020, 2022, 2024)]
    assert counts == sorted(counts), "reconstruction is monotonic by construction"
    # The live 2026 snapshot has more stations than the Dec 2024 file recorded, so
    # stations that existed in 2024 and later vanished cannot be seen from either.
    assert counts[-1] == len(frame) - 455


# --- G12 ----------------------------------------------------------------------------

def test_g12_the_transmission_geojson_is_never_parsed_as_one_object() -> None:
    """137 MiB, 94,216 features. It is read as a stream, never loaded whole."""
    path = PATHS.seed / "Electric__Power_Transmission_Lines.geojson"
    if not path.exists():  # pragma: no cover - the file is gitignored by design
        pytest.skip("gitignored source file not present in this clone")

    from pipeline.discovery.measure import measure_geojson_properties

    measurement = measure_geojson_properties(path, max_features=25)
    assert measurement.row_count == 25
    assert measurement.truncated is True
    assert "G12" in measurement.notes[0]
    assert path.stat().st_size > 100_000_000


def test_g12_no_code_path_calls_json_load_on_the_transmission_file() -> None:
    source = (PATHS.root / "pipeline").rglob("*.py")
    for module in source:
        text = module.read_text(encoding="utf-8")
        assert "Electric__Power_Transmission_Lines" not in text or (
            "measure_geojson_properties" in text or "seed_inventory" in text
            or "SEED_PROVENANCE" in text
        ), f"{module} references the GeoJSON without the streaming reader"


# --- G13 ----------------------------------------------------------------------------

def test_g13_county_names_collide_across_states_so_joins_must_use_fips() -> None:
    """Both Minnesota and Illinois have a Cook County."""
    from pipeline.spatial.geography import county_fips_lookup

    lookup = county_fips_lookup()
    cooks = sorted(k for k in lookup if k[1] == "Cook County")
    assert len(cooks) >= 2
    assert {state for state, _ in cooks} >= {"MN", "IL"}
    assert lookup[("MN", "Cook County")] != lookup[("IL", "Cook County")]


def test_g13_illinois_panel_county_names_require_fips_resolution(
    seed_frame: Loader,
) -> None:
    frame = seed_frame("seed_il_county_ev_monthly_panel")
    non_counties = {"Chicago", "Unknown County", "Total Count"}
    assert non_counties <= set(frame.columns), (
        "trailing columns are not counties and must be excluded from aggregation"
    )
    assert "Cook" in " ".join(frame.columns)


# --- G14 ----------------------------------------------------------------------------

def test_g14_connector_types_is_a_space_delimited_string_not_a_normalised_field(
    seed_frame: Loader,
) -> None:
    values = seed_frame(NATIONAL)["EV Connector Types"].dropna()
    assert values.str.contains(" ").any(), "multi-connector rows are space-delimited"
    exploded = sorted({t for v in values for t in str(v).split()})
    assert "J1772" in exploded
    assert len(exploded) < 15, f"a small closed vocabulary, got {exploded}"


def test_g14_the_pipeline_splits_rather_than_substring_matches(
    fixture_warehouse,  # type: ignore[no-untyped-def]
) -> None:
    stations = fixture_warehouse.fetch_df("mart_stations")
    assert stations["ev_connector_types"].apply(
        lambda v: isinstance(v, (list, tuple)) or v is None
    ).all(), "connector types must arrive as a list, not a raw string"


# --- suite completeness ----------------------------------------------------------------

def test_every_domain_rule_g1_to_g14_has_at_least_one_test() -> None:
    """A rule with no test is a rule that is not locked."""
    import pathlib
    import re

    text = pathlib.Path(__file__).read_text(encoding="utf-8")
    covered = {m.group(1).upper() for m in re.finditer(r"def test_(g\d+)_", text)}
    expected = {f"G{i}" for i in range(1, 15)}
    assert covered == expected, f"missing tests for {sorted(expected - covered)}"
