"""Feature engineering: D2 enforcement by execution, and explicit missing-data handling."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.model.features import (
    ACS_JAM_VALUES,
    EXPOSURE_VARIABLE,
    FEATURE_NAMES,
    FEATURES,
    Feature,
    FeatureError,
    assert_primary_feature_set_is_clean,
    build_feature_rows,
    compute_features,
    feature_inputs,
    impute,
    load_land_area_km2,
    numeric,
    share,
    to_numeric_row,
    weighted_mean,
)

# --- parsing ------------------------------------------------------------------------

def test_the_census_jam_value_becomes_none_not_a_large_negative_number() -> None:
    """Reading -666666666 as a number puts -666 million dollars of income in a model."""
    assert "-666666666" in ACS_JAM_VALUES
    assert numeric("-666666666") is None


def test_blank_and_unparseable_cells_become_none() -> None:
    assert numeric("") is None
    assert numeric(None) is None
    assert numeric("  ") is None
    assert numeric("not a number") is None


def test_an_ordinary_cell_parses() -> None:
    assert numeric(" 1234 ") == 1234.0
    assert numeric(7.5) == 7.5


# --- shares and means ---------------------------------------------------------------

def test_a_share_with_a_zero_denominator_is_none_not_zero() -> None:
    """Returning 0.0 would assert that no household owns in an area with no households."""
    assert share([1.0], 0.0) is None
    assert share([1.0], None) is None


def test_a_share_with_any_missing_numerator_part_is_none() -> None:
    assert share([1.0, None], 10.0) is None


def test_a_share_sums_its_numerator_parts() -> None:
    assert share([1.0, 3.0], 8.0) == 0.5


def test_a_weighted_mean_uses_the_declared_bin_midpoints() -> None:
    assert weighted_mean([1.0, 1.0], [0.0, 4.0], 2.0) == 2.0


def test_a_weighted_mean_refuses_missing_counts_or_a_zero_total() -> None:
    assert weighted_mean([1.0, None], [0.0, 4.0], 2.0) is None
    assert weighted_mean([1.0, 1.0], [0.0, 4.0], 0.0) is None
    assert weighted_mean([1.0, 1.0], [0.0, 4.0], None) is None


# --- D2 -----------------------------------------------------------------------------

def test_the_primary_feature_set_reads_only_acs_demographics_and_land_area() -> None:
    assert_primary_feature_set_is_clean()


def test_feature_inputs_are_discovered_by_running_the_feature() -> None:
    density = next(f for f in FEATURES if f.name == "log_population_density_km2")
    assert feature_inputs(density) == frozenset({"B01003_001E", "land_area_km2"})


def test_a_feature_reaching_outside_the_declared_variables_is_rejected() -> None:
    """The guarantee is structural: a supply input fails here even if the name is bland."""
    smuggled = Feature("neighbourhood_quality", "innocuous", "innocuous",
                       lambda r: r.get("afdc_port_count_within_5km"))
    with pytest.raises(FeatureError, match=r"D2 violation.*neighbourhood_quality"):
        assert_primary_feature_set_is_clean([smuggled])


def test_a_feature_named_after_infrastructure_is_rejected() -> None:
    allowed = Feature("charger_density", "d", "d", lambda r: r.get("B01003_001E"))
    with pytest.raises(FeatureError, match="describe infrastructure"):
        assert_primary_feature_set_is_clean([allowed])


def test_the_feature_names_are_unique_and_stable() -> None:
    assert len(FEATURE_NAMES) == len(set(FEATURE_NAMES)) == 14


# --- computation --------------------------------------------------------------------

def complete_row() -> dict[str, float | None]:
    row: dict[str, float | None] = {name: 10.0 for f in FEATURES
                                    for name in feature_inputs(f)}
    row.update({
        "B01003_001E": 1000.0, "land_area_km2": 10.0, "B19013_001E": 75000.0,
        "B19001_001E": 100.0, "B25003_001E": 100.0, "B25003_002E": 60.0,
        "B25024_001E": 100.0, "B25024_002E": 55.0, "B25024_003E": 5.0,
        "B25044_001E": 100.0, "B08301_001E": 200.0, "B08303_001E": 200.0,
        "B15003_001E": 500.0,
    })
    return row


def test_every_feature_computes_from_a_complete_row() -> None:
    values = compute_features(complete_row())
    assert set(values) == set(FEATURE_NAMES)
    assert all(v is not None for v in values.values())
    assert values["owner_occupied_share"] == pytest.approx(0.6)
    assert values["single_family_share"] == pytest.approx(0.6)
    assert values["median_household_income_k"] == pytest.approx(75.0)


def test_density_is_none_without_land_area_rather_than_infinite() -> None:
    row = complete_row()
    row["land_area_km2"] = None
    assert compute_features(row)["log_population_density_km2"] is None
    row["land_area_km2"] = 0.0
    assert compute_features(row)["log_population_density_km2"] is None


def test_density_is_none_without_population() -> None:
    row = complete_row()
    row["B01003_001E"] = None
    assert compute_features(row)["log_population_density_km2"] is None


def test_median_income_is_none_when_the_jam_value_was_published() -> None:
    row = to_numeric_row({"geoid": "x", "B19013_001E": "-666666666"}, 1.0)
    assert compute_features(row)["median_household_income_k"] is None


def test_to_numeric_row_attaches_land_area_and_drops_the_geoid() -> None:
    row = to_numeric_row({"geoid": "53033000100", "B01003_001E": "12"}, 3.0)
    assert "geoid" not in row
    assert row["B01003_001E"] == 12.0
    assert row["land_area_km2"] == 3.0


# --- assembly and imputation --------------------------------------------------------

def staged(n: int = 3) -> list[dict[str, str]]:
    rows = []
    for i in range(n):
        row = {"geoid": f"5303300010{i}"}
        row.update({k: str(v) for k, v in complete_row().items()
                    if k != "land_area_km2" and v is not None})
        rows.append(row)
    return rows


def test_build_feature_rows_keeps_every_input_area() -> None:
    rows = build_feature_rows(staged(3), "tracts",
                              {"53033000100": 5.0, "53033000101": 5.0},
                              lambda g: g[:2])
    assert [r.geoid for r in rows] == ["53033000100", "53033000101", "53033000102"]
    assert rows[0].state_fips == "53"
    assert rows[0].households == 100.0
    # The third has no land area, so its density is missing and is REPORTED, not filled.
    assert "log_population_density_km2" in rows[2].missing_features


def test_impute_fills_with_the_national_median_and_counts_what_it_filled() -> None:
    rows = build_feature_rows(staged(3), "tracts",
                              {"53033000100": 5.0, "53033000101": 5.0},
                              lambda g: g[:2])
    filled, counts, medians = impute(rows)
    assert counts == [0, 0, 1]
    assert all(set(f) == set(FEATURE_NAMES) for f in filled)
    assert filled[2]["log_population_density_km2"] == medians[
        "log_population_density_km2"]


def test_impute_falls_back_to_zero_when_a_feature_is_missing_everywhere() -> None:
    rows = build_feature_rows(staged(2), "tracts", {}, lambda g: g[:2])
    _, counts, medians = impute(rows)
    assert medians["log_population_density_km2"] == 0.0
    assert counts == [1, 1]


def test_the_exposure_variable_is_the_household_count() -> None:
    assert EXPOSURE_VARIABLE == "B25003_001E"


# --- land area ----------------------------------------------------------------------

def test_land_area_is_read_in_square_kilometres_from_the_gazetteer(
    tmp_path: Path,
) -> None:
    path = tmp_path / "gaz.txt"
    path.write_text("USPS\tGEOID\tALAND\tAWATER\n"
                    "WA\t53033000100\t2000000\t5\n"
                    "WA\t53033000200\t\t5\n", encoding="utf-8")
    areas = load_land_area_km2("tracts", path)
    assert areas == {"53033000100": 2.0}


def test_a_missing_gazetteer_raises_rather_than_defaulting_the_area(
    tmp_path: Path,
) -> None:
    """Substituting total area or a constant is the silent default D8 forbids."""
    with pytest.raises(FeatureError, match="silent default"):
        load_land_area_km2("tracts", tmp_path / "absent.txt")


def test_a_gazetteer_with_no_usable_rows_raises(tmp_path: Path) -> None:
    path = tmp_path / "gaz.txt"
    path.write_text("USPS\tGEOID\tALAND\n", encoding="utf-8")
    with pytest.raises(FeatureError, match="zero areas"):
        load_land_area_km2("tracts", path)
