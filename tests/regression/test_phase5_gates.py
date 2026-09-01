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
