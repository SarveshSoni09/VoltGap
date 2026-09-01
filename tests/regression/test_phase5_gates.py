"""Phase 5 acceptance criteria, asserted against the real published artifact.

CLAUDE.md §15.5 Phase 5:

> `assert_no_leakage` raises on a deliberately poisoned feature set (negative test). All
> three origins run with gain curves and lift against random and population baselines.
> Excluded backtest features enumerated. Robustness reported against four baselines on six
> objectives. Every claim uses the D3 vocabulary (checked by the copy lint created in
> Phase 1 and extended here). Backtest methodology states the A-0.5 vintage-semantics
> finding explicitly, including the limitation if it remained unresolved.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest

from pipeline.config.settings import PATHS
from pipeline.validation.robustness import BASELINE_NAMES, OBJECTIVE_NAMES

EVIDENCE_PATH = PATHS.root / "docs" / "evidence" / "P5-1_validation.json"


@pytest.fixture(scope="module")
def evidence() -> dict[str, Any]:
    assert EVIDENCE_PATH.exists(), (
        f"{EVIDENCE_PATH} missing; run `make phase5` to reproduce it")
    return json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


# --- P5-A: the leakage guard ----------------------------------------------------------

def test_p5_a_the_negative_leakage_test_exists_and_passes() -> None:
    """The mandatory negative test, re-run here so the gate covers it directly rather
    than trusting that the unit suite included it."""
    from tests.unit.test_vintage_guard import (
        test_a_deliberately_poisoned_feature_set_raises,
    )

    test_a_deliberately_poisoned_feature_set_raises()


def test_p5_a_no_origin_uses_a_feature_vintage_after_its_cutoff(
    evidence: dict[str, Any],
) -> None:
    """D1, asserted on the published record rather than on the code that wrote it."""
    for plan in evidence["origin_plans"]:
        cutoff = date.fromisoformat(str(plan["prediction_cutoff"]))
        assert date.fromisoformat(str(plan["acs_released"])) <= cutoff, plan
        assert date.fromisoformat(
            str(plan["state_registration_released"])) <= cutoff, plan


def test_p5_a_no_origin_uses_the_production_acs_vintage(
    evidence: dict[str, Any],
) -> None:
    """The headline leakage risk: ACS 2024 is the deployed surface."""
    for plan in evidence["origin_plans"]:
        assert int(plan["acs_api_year"]) <= 2019, plan


# --- P5-B: three rolling origins ------------------------------------------------------

def test_p5_b_all_three_required_origins_ran(evidence: dict[str, Any]) -> None:
    origins = [a["origin"] for a in evidence["deployment_alignment"]]
    assert origins == ["2020", "2021", "2022"]


def test_p5_b_every_origin_predicts_the_following_24_months(
    evidence: dict[str, Any],
) -> None:
    for entry in evidence["deployment_alignment"]:
        cutoff = date.fromisoformat(str(entry["prediction_cutoff"]))
        end = date.fromisoformat(str(entry["evaluation_window_end"]))
        assert end.year - cutoff.year == 2, entry["origin"]


def test_p5_b_every_origin_has_deployments_to_evaluate_against(
    evidence: dict[str, Any],
) -> None:
    """A gain curve computed against nothing would be meaningless."""
    for entry in evidence["deployment_alignment"]:
        assert entry["subsequent_deployments_available"] > 1000, entry["origin"]
        assert entry["subsequent_deployment_ports"] > 0
        assert entry["geographic_coverage_states"] >= 50, entry["origin"]


def test_p5_b_every_origin_reports_a_full_gain_curve(
    evidence: dict[str, Any],
) -> None:
    for entry in evidence["deployment_alignment"]:
        for ranking in [entry["model"], *entry["baselines"]]:
            curve = ranking["gain_curve"]
            assert len(curve) == 10, ranking["ranking"]
            captured = [p["share_of_subsequent_stations_captured"] for p in curve]
            assert captured == sorted(captured), ranking["ranking"]
            assert curve[-1]["decile"] == 1.0


def test_p5_b_lift_is_reported_against_random_and_population(
    evidence: dict[str, Any],
) -> None:
    """§10.2.4 names both baselines explicitly."""
    for entry in evidence["deployment_alignment"]:
        names = {b["ranking"] for b in entry["baselines"]}
        assert {"random", "population"} <= names, entry["origin"]
        for key in ("lift_vs_random_stations", "lift_vs_population_stations",
                    "lift_vs_random_ports", "lift_vs_population_ports"):
            assert isinstance(entry[key], (int, float)), key


def test_p5_b_ports_are_reported_not_only_station_counts(
    evidence: dict[str, Any],
) -> None:
    """G1: a station record is one network's presence at a site, not capacity."""
    for entry in evidence["deployment_alignment"]:
        for point in entry["model"]["gain_curve"]:
            assert "share_of_subsequent_ports_captured" in point
            assert "share_of_subsequent_dcfc_ports_captured" in point


def test_p5_b_the_reconstruction_is_labelled_approximate(
    evidence: dict[str, Any],
) -> None:
    """G10, G11 and §10.2.5: survivorship bias must travel with the number."""
    labelling = str(evidence["station_reconstruction"]["labelling"])
    assert "APPROXIMATE RECONSTRUCTION" in labelling
    assert "survivorship" in labelling
    for entry in evidence["deployment_alignment"]:
        assert entry["reconstruction_confidence"]


# --- P5-C: excluded features enumerated -----------------------------------------------

def test_p5_c_every_excluded_feature_is_enumerated_with_a_reason(
    evidence: dict[str, Any],
) -> None:
    exclusions = evidence["vintage_ledger"]["exclusions"]
    assert len(exclusions) >= 5
    for entry in exclusions:
        assert entry["feature"] and len(str(entry["reason"])) > 30, entry


def test_p5_c_the_named_leakage_risks_are_all_addressed(
    evidence: dict[str, Any],
) -> None:
    """Each item the Phase 5 brief called out by name."""
    text = json.dumps(evidence["vintage_ledger"]["exclusions"])
    assert "hud_usps_zip_tract" in text
    assert "census_tiger_prisecroads" in text
    assert "afdc_charging_units" in text
    assert "nrel_home_charging" in text


def test_p5_c_supply_features_are_excluded_by_directive_not_only_by_vintage(
    evidence: dict[str, Any],
) -> None:
    """D2 forbids them at every cutoff, including ones where a contemporaneous edition
    existed. Excluding them 'because of vintage' would be the wrong reason."""
    supply = next(e for e in evidence["vintage_ledger"]["exclusions"]
                  if e["source_id"] == "afdc_charging_units")
    assert "D2" in str(supply["reason"])


def test_p5_c_the_a_0_5_contemporaneity_limitation_is_stated(
    evidence: dict[str, Any],
) -> None:
    """§15.5: the backtest methodology must state the A-0.5 finding explicitly,
    including the limitation because it remained unresolved."""
    declared = json.dumps(evidence["vintage_ledger"]["declared_vintages"])
    assert "A-0.5" in declared
    assert "Contemporaneity UNRESOLVED" in declared


# --- P5-D: cross-objective robustness -------------------------------------------------

def test_p5_d_robustness_reports_six_objectives(evidence: dict[str, Any]) -> None:
    rows = evidence["cross_objective_robustness"]["per_state_and_budget"]
    assert rows
    for row in rows:
        for portfolio in row["portfolios"]:
            assert set(portfolio["scores"]) == set(OBJECTIVE_NAMES)


def test_p5_d_robustness_reports_all_four_baselines(evidence: dict[str, Any]) -> None:
    rows = evidence["cross_objective_robustness"]["per_state_and_budget"]
    for row in rows:
        names = {p["portfolio"] for p in row["portfolios"]}
        assert {f"baseline_{b}" for b in BASELINE_NAMES} <= names, row["label"]


def test_p5_d_a_portfolio_is_scored_on_objectives_it_did_not_optimise(
    evidence: dict[str, Any],
) -> None:
    rows = evidence["cross_objective_robustness"]["per_state_and_budget"]
    optimised = [p for row in rows for p in row["portfolios"]
                 if p["optimised_for"] != "none (baseline rule)"]
    assert optimised
    for portfolio in optimised:
        assert len(portfolio["scores"]) == 6


def test_p5_d_tradeoffs_are_published_rather_than_suppressed(
    evidence: dict[str, Any],
) -> None:
    """§10.3: a portfolio strong on one measure and weak on another is a RESULT."""
    rows = evidence["cross_objective_robustness"]["per_state_and_budget"]
    assert all("tradeoffs_where_below_95_percent_of_best" in row for row in rows)
    found = [row for row in rows
             if any(v for v in row["tradeoffs_where_below_95_percent_of_best"].values())]
    assert found, "no tradeoff was recorded anywhere, which would itself be suspicious"


def test_p5_d_the_circularity_caveat_travels_with_the_result(
    evidence: dict[str, Any],
) -> None:
    robustness = evidence["cross_objective_robustness"]
    assert "CIRCULAR" in str(robustness["what_this_is_not"])
    assert "NOT" in str(robustness["what_this_is_not"])


# --- P5-E: D3 vocabulary --------------------------------------------------------------

def test_p5_e_the_three_validation_terms_are_defined_and_distinct(
    evidence: dict[str, Any],
) -> None:
    terms = evidence["validation_terms"]
    assert set(terms) >= {"demand_model_validation", "historical_deployment_alignment",
                          "cross_objective_robustness"}
    assert "optimal" in str(terms["none_of_these_shows"])


def test_p5_e_alignment_never_claims_optimality_or_causality(
    evidence: dict[str, Any],
) -> None:
    for entry in evidence["deployment_alignment"]:
        disclaimers = " ".join(entry["what_this_does_not_measure"])
        assert "were optimal" in disclaimers
        assert "causally correct" in disclaimers
        assert "should have followed" in disclaimers
        assert "reproduces industry deployment behaviour" in disclaimers


def test_p5_e_demand_model_validation_is_restated_not_refitted(
    evidence: dict[str, Any],
) -> None:
    """Phase 5 validates the model; it is not licence for a post-hoc bakeoff."""
    track = evidence["demand_model_validation"]
    assert "restated not re-fitted" in str(track["source"])
    assert track["supply_features_in_primary_model"] == 0
    assert "EXCLUDED from the independent headline" in str(track["washington_status"])


# --- P5-F: the backtested model is not the deployed model -----------------------------

def test_p5_f_the_backtest_declares_it_is_a_different_model(
    evidence: dict[str, Any],
) -> None:
    """§10.2.3 requires this stated, with every difference listed."""
    for entry in evidence["deployment_alignment"]:
        surface = entry["vintages_used"]["surface"]
        assert "NOT the same model" in str(surface["note"])
        assert surface["evidence_grain"] == "state_total_only"
        assert surface["estimate_method"] == "modelled"


def test_p5_f_every_origin_reconciles_exactly_to_its_state_totals(
    evidence: dict[str, Any],
) -> None:
    for entry in evidence["deployment_alignment"]:
        surface = entry["vintages_used"]["surface"]
        assert float(surface["reconciliation_max_abs_error_per_state"]) < 1e-6


def test_p5_f_every_origin_uses_2010_tract_geography_and_matching_weights(
    evidence: dict[str, Any],
) -> None:
    """The ACS releases available at these cutoffs are published on 2010 boundaries, so
    the population weights must be the 2010 product too."""
    for entry in evidence["deployment_alignment"]:
        surface = entry["vintages_used"]["surface"]
        assert surface["tract_geography"] == "2010"
        assert "CenPop2010" in str(surface["population_weight_vintage"])


# --- external review corrections, 2026-08-31 ------------------------------------------

def test_p5_g_capacity_captured_is_reported_alongside_ports(
    evidence: dict[str, Any],
) -> None:
    """§10.2.4 requires ports AND capacity captured, not only station counts (G1)."""
    for entry in evidence["deployment_alignment"]:
        assert entry["subsequent_deployment_capacity_kw"] > 0
        for ranking in [entry["model"], *entry["baselines"]]:
            assert "top_decile_capture_capacity_kw" in ranking, ranking["ranking"]
            for point in ranking["gain_curve"]:
                assert "share_of_subsequent_capacity_kw_captured" in point


def test_p5_g_every_ranking_is_scored_over_the_same_eligible_support(
    evidence: dict[str, Any],
) -> None:
    """A lift figure is meaningless if the model and its baselines see different
    universes. The full-ranking capture is identical for all of them by construction."""
    for entry in evidence["deployment_alignment"]:
        full = [r["gain_curve"][-1]["share_of_subsequent_stations_captured"]
                for r in [entry["model"], *entry["baselines"]]]
        assert len(set(full)) == 1, entry["origin"]
        support = entry["eligible_support"]
        assert support["baselines_share_this_support"] is True
        assert support["ranked_cells"] > 0
        # The full-ranking capture is exactly the share that fell inside the support.
        assert full[0] == pytest.approx(
            support["share_of_subsequent_stations_inside_ranked_cells"], abs=1e-6)


def test_p5_g_the_capture_denominator_and_top_decile_are_documented(
    evidence: dict[str, Any],
) -> None:
    for entry in evidence["deployment_alignment"]:
        support = entry["eligible_support"]
        assert "ALL subsequent deployments" in str(support["capture_denominator"])
        assert "round(0.1 *" in str(support["top_decile_construction"])


def test_p5_g_the_random_baseline_reports_its_sampling_noise(
    evidence: dict[str, Any],
) -> None:
    """The 2020 single-draw figure sat at percentile 0 of its own distribution, which
    overstated lift there. The baseline is now a mean over draws - still empirical - and
    the spread ships with it."""
    for entry in evidence["deployment_alignment"]:
        spread = entry["random_baseline_spread"]
        assert spread["draws"] >= 100
        assert spread["top_decile_stations_sd"] > 0
        assert (spread["top_decile_stations_p5"]
                <= spread["top_decile_stations_mean"]
                <= spread["top_decile_stations_p95"])
        random_curve = next(b for b in entry["baselines"] if b["ranking"] == "random")
        assert random_curve["top_decile_capture_stations"] == pytest.approx(
            spread["top_decile_stations_mean"], abs=1e-6)


def test_p5_g_random_capture_is_now_consistent_across_origins(
    evidence: dict[str, Any],
) -> None:
    """The anomaly this correction addressed: 0.0687 / 0.1050 / 0.0991 from single
    draws, against a support that barely moves between origins."""
    captures = [next(b for b in e["baselines"] if b["ranking"] == "random")
                ["top_decile_capture_stations"]
                for e in evidence["deployment_alignment"]]
    assert max(captures) - min(captures) < 0.01, captures


def test_p5_g_no_road_geometry_enters_any_historical_origin(
    evidence: dict[str, Any],
) -> None:
    """D1. TIGER/Line 2024 postdates every cutoff; no earlier edition was retrieved."""
    for plan in evidence["origin_plans"]:
        assert plan["road_filter_vintage"] == (
            "none - no road geometry enters this origin")
        assert "NOT applied here" in str(plan["road_filter_audit"])


def test_p5_g_the_acs_2020_release_date_is_recorded_as_established(
    evidence: dict[str, Any],
) -> None:
    """Recorded on external review. It postdates the 2022 cutoff, so selection is
    unchanged - but the exclusion reason is now demonstrable rather than precautionary."""
    acs2020 = next(v for v in evidence["vintage_ledger"]["declared_vintages"]
                   if "ACS 2020" in v["label"])
    assert acs2020["released"] == "2022-03-17"
    assert acs2020["release_date_certain"] is True
    assert [p["acs_api_year"] for p in evidence["origin_plans"]] == [2018, 2019, 2019]


def test_p5_g_capacity_is_labelled_reconstructed_with_no_bias_direction_claimed(
    evidence: dict[str, Any],
) -> None:
    """G10/G11. Capacity is resolved from the CURRENT snapshot and attributed to each
    station's open date, so a reader must not take it for known installation-time
    capacity. The caveat travels with every capacity figure rather than living in prose
    somewhere else.

    It must also NOT claim a direction of bias. The biases compete - surviving stations
    may carry upgraded power, closed stations are missing entirely, and neither effect
    need be distributed equally between selected and non-selected cells - so no
    guaranteed direction exists for the total or for any capture fraction. An earlier
    draft called the capture result a lower bound; that claim is withdrawn and this test
    stops it returning.
    """
    basis = evidence["station_reconstruction"]["capacity_kw_basis"]
    assert "RECONSTRUCTED" in basis
    assert "CURRENT-SNAPSHOT kW" in basis
    assert "NOT known installation-time capacity" in basis
    assert "G10, G11" in basis
    assert "COMPETING biases" in basis
    assert "UNKNOWN" in basis
    for banned in ("OVERSTATING", "overstates", "lower bound", "upper bound"):
        assert banned not in basis, banned

    for entry in evidence["deployment_alignment"]:
        assert entry["subsequent_deployment_capacity_kw_basis"] == basis
        for ranking in [entry["model"], *entry["baselines"]]:
            for point in ranking["gain_curve"]:
                assert point["capacity_kw_basis"] == basis, ranking["ranking"]
