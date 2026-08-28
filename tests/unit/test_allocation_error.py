"""The measured ZIP-to-tract allocation error, and its record accounting.

CLAUDE.md §7.5.1 point 5 requires allocation ambiguity to be measured rather than
assumed. These tests exercise the measurement on small hand-checkable fixtures; the
national Washington run is a separate driver.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from pipeline.spatial.crosswalk import AllocationLink
from pipeline.validation.allocation_error import (
    MAX_ACCEPTABLE_TVD,
    AllocationValidationError,
    band_for,
    compare_methods,
    mean_absolute_error,
    normalise_digits,
    paired_counts,
    top_tract_hit,
    total_variation_distance,
    zip_level_rules,
)
from pipeline.validation.washington import (
    land_area_links_for,
    load_hud_links,
    main,
    run,
    to_evidence,
)

T1 = "53033000100"
T2 = "53033000200"
T3 = "53033000300"


def record(zip_code: str, tract: str) -> dict[str, object]:
    return {"zip_code": zip_code, "_2020_census_tract": tract}


# --- digit normalisation ------------------------------------------------------------

def test_normalise_digits_takes_the_first_five_of_a_zip_plus_four() -> None:
    assert normalise_digits("98101-1234", 5) == "98101"


def test_normalise_digits_preserves_a_leading_zero_zip() -> None:
    assert normalise_digits("04101", 5) == "04101"


def test_normalise_digits_refuses_a_short_zip() -> None:
    assert normalise_digits("981", 5) is None


def test_normalise_digits_requires_an_exact_eleven_digit_tract() -> None:
    assert normalise_digits(T1, 11) == T1
    assert normalise_digits("5303300010", 11) is None
    assert normalise_digits(None, 11) is None


# --- record-level accounting --------------------------------------------------------

def test_paired_counts_accounts_for_every_retrieved_record() -> None:
    rows = [
        record("98101", T1), record("98101", T1), record("98101", T2),
        record("", T1),                       # unusable: no ZIP
        record("98101", "not-a-tract"),       # unusable: no 11-digit tract
        record("98101", "41051000100"),       # Oregon tract: outside the state
    ]
    counts, ledger = paired_counts(rows, state_fips="53")
    assert counts == {("98101", T1): 2, ("98101", T2): 1}
    assert ledger.retrieved == 6
    assert ledger.included == 3
    assert ledger.excluded == {"unusable_zip_or_tract": 2, "tract_outside_state": 1}
    ledger.assert_balanced()


# --- the metrics themselves ---------------------------------------------------------

def test_tvd_is_the_share_of_mass_assigned_to_the_wrong_tract() -> None:
    observed = {T1: 0.8, T2: 0.2}
    estimated = {T1: 0.5, T2: 0.5}
    assert total_variation_distance(observed, estimated) == pytest.approx(0.3)


def test_tvd_counts_a_tract_the_method_invented() -> None:
    """A tract present only in the estimate still contributes misallocated mass."""
    assert total_variation_distance({T1: 1.0}, {T1: 0.6, T3: 0.4}) == pytest.approx(0.4)


def test_tvd_is_zero_for_a_perfect_reconstruction() -> None:
    assert total_variation_distance({T1: 0.5, T2: 0.5}, {T1: 0.5, T2: 0.5}) == 0.0


def test_mean_absolute_error_divides_by_the_union_of_tracts() -> None:
    assert mean_absolute_error({T1: 1.0}, {T1: 0.6, T3: 0.4}) == pytest.approx(0.4)


def test_top_tract_hit_is_true_when_the_plurality_tract_matches() -> None:
    assert top_tract_hit({T1: 0.6, T2: 0.4}, {T1: 0.9, T2: 0.1}) is True
    assert top_tract_hit({T1: 0.6, T2: 0.4}, {T1: 0.1, T2: 0.9}) is False


def test_top_tract_ties_break_deterministically_on_the_lowest_tract_id() -> None:
    """Dictionary order must not decide a metric."""
    forwards = top_tract_hit({T1: 0.5, T2: 0.5}, {T1: 0.5, T2: 0.5})
    backwards = top_tract_hit({T2: 0.5, T1: 0.5}, {T2: 0.5, T1: 0.5})
    assert forwards is backwards is True


def test_band_for_maps_tract_counts_to_the_published_complexity_bands() -> None:
    assert band_for(1) == "1"
    assert band_for(3) == "2-3"
    assert band_for(7) == "4-7"
    assert band_for(80) == "8+"


# --- ZIP-level exclusion rules ------------------------------------------------------

def test_a_zip_below_the_minimum_ev_count_is_excluded_for_that_reason_first() -> None:
    """Precedence is fixed so counts stay mutually exclusive."""
    methods: Mapping[str, Mapping[str, Mapping[str, float]]] = {"m": {}}
    rules = zip_level_rules({"98101": 4}, methods, min_evs=10)
    matched = [r.reason for r in rules if r.predicate("98101")]
    assert matched[0] == "zip_below_minimum_ev_count"


def test_a_zip_with_no_mapping_is_reported_unallocatable_not_rescued() -> None:
    rules = zip_level_rules({"98101": 99}, {"m": {}}, min_evs=10)
    assert [r.reason for r in rules if r.predicate("98101")] == ["zip_no_mapping_m"]


def test_a_zero_residential_zip_keeps_its_zero_and_is_never_renormalised() -> None:
    """HUD ZIP 99546 sums to 0.0 because it holds no residential addresses."""
    methods = {"m": {"99546": {T1: 0.0, T2: 0.0}}}
    rules = zip_level_rules({"99546": 40}, methods, min_evs=10)
    assert [r.reason for r in rules if r.predicate("99546")] == ["zip_zero_weight_m"]


# --- the comparison -----------------------------------------------------------------

def small_case() -> tuple[list[dict[str, object]], dict[str, dict[str, dict[str, float]]]]:
    rows: list[dict[str, object]] = []
    rows += [record("98101", T1)] * 80 + [record("98101", T2)] * 20
    rows += [record("98102", T3)] * 50
    methods = {
        "perfect": {"98101": {T1: 0.8, T2: 0.2}, "98102": {T3: 1.0}},
        "flat": {"98101": {T1: 0.5, T2: 0.5}, "98102": {T3: 1.0}},
    }
    return rows, methods


def test_compare_methods_scores_each_method_against_the_observed_distribution() -> None:
    rows, methods = small_case()
    result = compare_methods(rows, methods, state_fips="53")
    assert result.included_evs == 150
    assert len(result.zip_scores) == 2
    # 98101 carries 100 of the 150 EVs, so the weighted mean is 100/150 * 0.3.
    assert result.summaries["flat"].weighted_mean_tvd == pytest.approx(0.2)
    assert result.summaries["perfect"].weighted_mean_tvd == pytest.approx(0.0)
    assert result.summaries["perfect"].top_tract_accuracy == pytest.approx(1.0)


def test_win_share_counts_only_strict_wins() -> None:
    """98102 is a tie between the methods, so neither wins it."""
    rows, methods = small_case()
    result = compare_methods(rows, methods, state_fips="53")
    assert result.win_share["perfect"] == pytest.approx(0.5)
    assert result.win_share["flat"] == pytest.approx(0.0)


def test_strata_report_error_by_zip_complexity() -> None:
    rows, methods = small_case()
    result = compare_methods(rows, methods, state_fips="53")
    assert set(result.strata) == {"1", "2-3"}
    assert result.strata["2-3"]["zips"] == 1.0
    assert result.strata["2-3"]["evs"] == 100.0
    assert result.strata["1"]["weighted_tvd_perfect"] == pytest.approx(0.0)


def test_the_result_publishes_a_balanced_ledger_and_the_ceiling() -> None:
    rows, methods = small_case()
    rows += [record("98109", T1)] * 3          # below the 10-EV minimum
    payload = compare_methods(rows, methods, state_fips="53").to_dict()
    accounting = payload["record_accounting"]
    assert isinstance(accounting, dict)
    assert accounting["retrieved"] == 153
    assert accounting["included"] == 150
    assert accounting["excluded_by_reason"]["zip_below_minimum_ev_count"] == 3
    assert accounting["balances"] is True
    assert payload["max_acceptable_tvd"] == MAX_ACCEPTABLE_TVD


def test_a_comparison_with_no_methods_is_refused() -> None:
    with pytest.raises(AllocationValidationError, match="no allocation methods"):
        compare_methods([], {})


def test_a_comparison_where_every_zip_is_excluded_reports_zeroes_not_a_crash() -> None:
    rows = [record("98101", T1)] * 3           # below the minimum
    result = compare_methods(rows, {"m": {"98101": {T1: 1.0}}}, state_fips="53")
    assert result.zip_scores == ()
    assert result.included_evs == 0
    assert result.summaries["m"].weighted_mean_tvd == 0.0
    assert result.summaries["m"].unweighted_mean_tvd == 0.0
    assert result.summaries["m"].top_tract_accuracy == 0.0
    assert result.win_share["m"] == 0.0
    assert result.strata == {}
    result.ledger.assert_balanced()


def test_exclusion_reason_keys_are_namespaced_per_method() -> None:
    """Two methods must not collide on a reason key, or the ledger stops being readable."""
    rules = zip_level_rules({"98101": 99}, {"hud_res_ratio": {}, "land_area": {}})
    reasons = [rule.reason for rule in rules]
    assert reasons == [
        "zip_below_minimum_ev_count",
        "zip_no_mapping_hud_res_ratio",
        "zip_zero_weight_hud_res_ratio",
        "zip_no_mapping_land_area",
        "zip_zero_weight_land_area",
    ]
    assert len(set(reasons)) == len(reasons)


# --- the Washington driver ----------------------------------------------------------

def test_load_hud_links_sums_repeated_tract_rows_and_skips_unusable_keys(
    tmp_path: Path,
) -> None:
    payload = {
        "98101": [
            {"geoid": T1, "res_ratio": 0.5},
            {"geoid": T1, "res_ratio": 0.25},   # same tract twice: summed, not replaced
            {"geoid": "bad", "res_ratio": 0.9},  # unusable tract: skipped
        ],
        "9810": [{"geoid": T1, "res_ratio": 1.0}],   # unusable ZIP: skipped
    }
    path = tmp_path / "hud.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    links = load_hud_links(path)
    assert links == {"98101": {T1: 0.75}}


def test_land_area_links_omit_a_zip_with_no_like_numbered_zcta() -> None:
    table = {
        "98101": [AllocationLink("zcta", "98101", T1, 0.6, "land_area"),
                  AllocationLink("zcta", "98101", T2, 0.4, "land_area")],
    }
    links = land_area_links_for(["98101", "98999"], table)
    assert links == {"98101": {T1: 0.6, T2: 0.4}}
    assert "98999" not in links


def test_land_area_links_fall_back_to_the_national_crosswalk_when_none_is_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: dict[str, bool] = {}

    def fake_load() -> dict[str, list[AllocationLink]]:
        called["yes"] = True
        return {"98101": [AllocationLink("zcta", "98101", T1, 1.0, "land_area")]}

    monkeypatch.setattr(
        "pipeline.validation.washington.load_zcta_tract_links", fake_load
    )
    assert land_area_links_for(["98101"]) == {"98101": {T1: 1.0}}
    assert called == {"yes": True}


def washington_fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, list[AllocationLink]]]:
    rows = [record("98101", T1)] * 70 + [record("98101", T2)] * 30
    rows += [record("98102", T3)] * 40
    rows += [record("98101", "41051000100")]          # outside Washington
    records_path = tmp_path / "wa.json"
    records_path.write_text(json.dumps(rows), encoding="utf-8")
    hud_path = tmp_path / "hud.json"
    hud_path.write_text(json.dumps({
        "98101": [{"geoid": T1, "res_ratio": 0.7}, {"geoid": T2, "res_ratio": 0.3}],
        "98102": [{"geoid": T3, "res_ratio": 1.0}],
    }), encoding="utf-8")
    links = {
        "98101": [AllocationLink("zcta", "98101", T1, 0.5, "land_area"),
                  AllocationLink("zcta", "98101", T2, 0.5, "land_area")],
        "98102": [AllocationLink("zcta", "98102", T3, 1.0, "land_area")],
    }
    return records_path, hud_path, links


def test_run_scores_both_candidate_methods_on_the_paired_records(tmp_path: Path) -> None:
    records_path, hud_path, links = washington_fixture(tmp_path)
    result = run(records_path, hud_path, links)
    assert result.included_evs == 140
    assert result.ledger.excluded == {"tract_outside_state": 1}
    assert result.summaries["hud_res_ratio"].weighted_mean_tvd == pytest.approx(0.0)
    # Land area splits 98101 evenly against an observed 70/30, so TVD is 0.2 there.
    assert result.summaries["land_area"].weighted_mean_tvd == pytest.approx(
        0.2 * 100 / 140
    )


def test_to_evidence_names_the_pre_registration_and_what_it_supersedes(
    tmp_path: Path,
) -> None:
    records_path, hud_path, links = washington_fixture(tmp_path)
    payload = to_evidence(run(records_path, hud_path, links))
    assert "66f1bfb" in str(payload["decision_rule_preregistered_at"])
    assert "L1-1" in str(payload["supersedes"])
    assert "NOT national ground truth" in str(payload["why_washington"])


def test_main_writes_a_balanced_evidence_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    records_path, hud_path, links = washington_fixture(tmp_path)
    monkeypatch.setattr(
        "pipeline.validation.washington.load_zcta_tract_links", lambda: links
    )
    out = tmp_path / "evidence.json"
    assert main(["--records", str(records_path), "--hud", str(hud_path),
                 "--out", str(out)]) == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["record_accounting"]["balances"] is True
    assert written["record_accounting"]["retrieved"] == 141
