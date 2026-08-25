"""Unit tests for the corrected G9 checks (CLAUDE.md section 19 A1).

The rule was rewritten after Phase 0 disproved its original wording. The property that
matters most is the last one: an anomalous state is flagged for review, never
automatically marked low-confidence, because a genuine adoption-rate difference is not
a data-quality defect.
"""

from __future__ import annotations

import pytest

from pipeline.quality.registration_checks import (
    DEVIATION_TOLERANCE,
    EXPECTED_JURISDICTION_COUNT,
    PUBLISHED_TOTAL_LABELS,
    Confidence,
    DefectKind,
    ReviewFlag,
    VintageCheck,
    assign_confidence,
    check_registrations,
    screen_per_capita,
    screen_year_over_year,
)


def fifty_one() -> dict[str, int]:
    return {f"S{i:02d}": 1000 + i for i in range(EXPECTED_JURISDICTION_COUNT)}


# --- per-capita screening -----------------------------------------------------------

def test_fewer_than_three_rates_produces_no_flags() -> None:
    """A standard deviation over two points is not a meaningful screen."""
    assert screen_per_capita({"a": 1, "b": 2}, {"a": 10, "b": 10}) == []


def test_zero_deviation_produces_no_flags() -> None:
    """Identical rates have no outliers, and dividing by zero must not be attempted."""
    counts = {"a": 10, "b": 10, "c": 10}
    assert screen_per_capita(counts, dict.fromkeys(counts, 100)) == []


def test_states_without_population_are_skipped_not_divided_by_zero() -> None:
    counts = {"a": 10, "b": 11, "c": 12, "d": 5000}
    population = {"a": 100, "b": 100, "c": 100, "d": 0}
    flags = screen_per_capita(counts, population)
    assert "d" not in {f.jurisdiction for f in flags}


def test_an_extreme_outlier_is_flagged_with_its_z_score() -> None:
    counts = {f"s{i}": 10 for i in range(20)}
    counts["big"] = 100_000
    flags = screen_per_capita(counts, dict.fromkeys(counts, 100))
    assert [f.jurisdiction for f in flags] == ["big"]
    assert flags[0].value > 3.0
    assert "standard deviations" in flags[0].detail


def test_the_z_threshold_is_configurable() -> None:
    counts = {"a": 10, "b": 11, "c": 12, "d": 40}
    population = dict.fromkeys(counts, 100)
    assert screen_per_capita(counts, population, z_threshold=0.5)
    assert not screen_per_capita(counts, population, z_threshold=99.0)


# --- year-over-year screening -------------------------------------------------------

def test_growth_above_the_threshold_is_flagged() -> None:
    flags = screen_year_over_year({"a": 90}, {"a": 10})
    assert flags[0].screen == "year_over_year"
    assert flags[0].value == pytest.approx(9.0)


def test_collapse_below_the_inverse_threshold_is_flagged() -> None:
    flags = screen_year_over_year({"a": 10}, {"a": 900})
    assert flags and flags[0].value < 1.0


def test_normal_growth_is_not_flagged() -> None:
    assert screen_year_over_year({"a": 15}, {"a": 10}) == []


def test_a_state_absent_or_zero_in_the_previous_vintage_is_skipped() -> None:
    assert screen_year_over_year({"a": 100}, {}) == []
    assert screen_year_over_year({"a": 100}, {"a": 0}) == []


# --- structural checks ----------------------------------------------------------------

def test_a_complete_dataset_passes() -> None:
    counts = fifty_one()
    result = check_registrations(counts, vintage="2023",
                                 published_total=sum(counts.values()))
    assert result.passed is True
    assert result.jurisdictions_present == 51


def test_an_explicit_expected_jurisdiction_list_is_honoured() -> None:
    result = check_registrations({"MN": 1}, vintage="2023",
                                 expected_jurisdictions=["MN", "IL"])
    assert result.coverage_complete is False
    assert result.missing_jurisdictions == ("IL",)


def test_an_unresolved_vintage_fails() -> None:
    counts = fifty_one()
    assert check_registrations(counts, vintage=None).passed is False


def test_a_reconciliation_mismatch_fails_but_a_missing_total_does_not() -> None:
    counts = fifty_one()
    assert check_registrations(counts, vintage="2023",
                               published_total=1).passed is False
    assert check_registrations(counts, vintage="2023").passed is True


@pytest.mark.parametrize("label", sorted(PUBLISHED_TOTAL_LABELS))
def test_either_published_total_label_is_treated_as_a_coverage_defect(
    label: str,
) -> None:
    counts = {**fifty_one(), label: 999}
    result = check_registrations(counts, vintage="2023")
    assert result.coverage_complete is False
    assert f"UNEXPECTED_TOTAL_ROW:{label}" in result.missing_jurisdictions
    assert result.jurisdictions_present == 51, "the total is excluded from the count"


def test_the_check_serialises_with_its_review_flags() -> None:
    counts = {f"s{i}": 10 for i in range(20)}
    counts["big"] = 100_000
    result = check_registrations(counts, vintage="2023",
                                 expected_jurisdictions=list(counts),
                                 population=dict.fromkeys(counts, 100),
                                 previous_vintage_counts={"big": 10})
    payload = result.to_dict()
    assert payload["passed"] is True
    assert payload["vintage"] == "2023"
    assert len(payload["review_flags"]) >= 2
    assert all(f["is_diagnostic_only"] for f in payload["review_flags"])


def test_vintage_check_is_immutable() -> None:
    check = VintageCheck(True, "2023", 51, True, (), True, (), None, 0, None)
    with pytest.raises(AttributeError):
        check.vintage = "2024"  # type: ignore[misc]


# --- property 7: the load-bearing correction --------------------------------------------

def test_no_number_of_review_flags_can_lower_confidence() -> None:
    flags = [ReviewFlag(f"S{i}", "per_capita_z", "extreme", 99.0) for i in range(50)]
    assert assign_confidence("S0", flags) is Confidence.OK


def test_only_corroborating_evidence_of_a_defect_lowers_confidence() -> None:
    for defect in DefectKind:
        assert assign_confidence("S0", [], [defect]) is Confidence.LOW
    assert assign_confidence("S0", [], []) is Confidence.OK


def test_confidence_and_defect_kinds_are_string_enums() -> None:
    assert Confidence.LOW.value == "low_confidence"
    assert DefectKind.VINTAGE.value == "vintage"
    assert str(Confidence.LOW) == "low_confidence"


def test_near_zero_deviation_is_treated_as_zero_not_scored_against() -> None:
    """Identical rates give a deviation around 1e-17, never exactly 0.0.

    An equality test against zero would never fire, and every jurisdiction would then
    be divided by a near-zero denominator and flagged as a 1e16-sigma outlier.
    """
    counts = {"a": 10, "b": 10, "c": 10, "d": 10}
    assert screen_per_capita(counts, dict.fromkeys(counts, 100)) == []

    rates = [0.1, 0.1, 0.1]
    mean = sum(rates) / len(rates)
    deviation = (sum((r - mean) ** 2 for r in rates) / len(rates)) ** 0.5
    assert deviation != 0.0, "the guard cannot be an equality test"
    assert deviation < DEVIATION_TOLERANCE
