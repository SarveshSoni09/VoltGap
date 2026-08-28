"""Phase 3 acceptance criteria, each mapped to an executable check.

CLAUDE.md §15.1 part G-A: 100% of a phase's declared criteria verified by an executable
check, none marked passed by inspection. These read the published evidence artifact
``docs/evidence/P3-2_demand_model.json``, which one command reproduces from cached
inputs (``python -m pipeline.model.run_phase3``), so the criteria are checked against
the numbers that ship rather than against a fresh in-test computation that could differ.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from pipeline.config.settings import PATHS
from pipeline.model.ablation import (
    SUPPLY_FEATURE_NAMES,
    assert_supply_features_are_absent,
)
from pipeline.model.features import FEATURE_NAMES, assert_primary_feature_set_is_clean
from pipeline.validation.washington import GRAIN_ORDER

ARTIFACT = PATHS.evidence / "P3-2_demand_model.json"


@pytest.fixture(scope="module")
def evidence() -> dict[str, Any]:
    assert ARTIFACT.exists(), (
        f"{ARTIFACT} is missing. Reproduce it with "
        "`python -m pipeline.model.run_phase3`."
    )
    payload: dict[str, Any] = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    return payload


# --- P3-A: leave-one-state-out at native granularity --------------------------------

def test_p3_a_loso_runs_across_every_usable_state_with_all_three_metrics(
    evidence: dict[str, Any],
) -> None:
    validation = evidence["demand_model_validation"]
    assert validation["validation_term"] == "demand model validation"
    assert len(validation["independent_states"]) == 14
    for row in validation["per_state"]:
        assert isinstance(row["wape"], float)
        assert isinstance(row["mae"], float)
        assert isinstance(row["r_squared"], float)
        assert row["areas_scored"] > 0


def test_p3_a_every_state_is_scored_at_its_own_observed_granularity(
    evidence: dict[str, Any],
) -> None:
    """A ZIP-grain state is scored at ZIP, a county state at county, Washington at
    tract. Crosswalk-generated tract values are never used as observed labels."""
    expected = {
        "usps_zip": "zcta", "county": "county", "tract": "tracts",
    }
    for row in evidence["demand_model_validation"]["per_state"]:
        assert row["native_geography"] == expected[row["evidence_grain"]], row["state"]


def test_p3_a_the_selection_rule_was_pre_registered_and_applied(
    evidence: dict[str, Any],
) -> None:
    validation = evidence["demand_model_validation"]
    assert "Pre-registered before any candidate was run" in validation["selection_rule"]
    aggregates = validation["aggregate_weighted_wape"][evidence["selection_mode"]]
    assert validation["selected_estimator"] in aggregates
    best = min(aggregates.values())
    chosen = aggregates[validation["selected_estimator"]]
    assert chosen <= best + 0.01, "the selected estimator is outside the tie-break band"


def test_p3_a_both_models_beat_both_baselines(evidence: dict[str, Any]) -> None:
    """A candidate that cannot beat 'EVs are spread like households' has learned
    nothing from demographics, however good its headline number looks."""
    aggregates = evidence["demand_model_validation"]["aggregate_weighted_wape"][
        evidence["selection_mode"]]
    baselines = max(aggregates["baseline_household_share"],
                    aggregates["baseline_population_share"])
    for name in ("poisson_glm", "ridge_log_rate", "boosted_poisson"):
        assert aggregates[name] < baselines, name


# --- P3-B: Washington is not independent validation ---------------------------------

def test_p3_b_washington_is_excluded_from_the_independent_aggregate(
    evidence: dict[str, Any],
) -> None:
    validation = evidence["demand_model_validation"]
    assert "WA" not in validation["independent_states"]
    assert validation["excluded_from_independent_aggregate"]["WA"] == (
        "non_independent_preprocessing_selection_state")


def test_p3_b_washington_is_still_run_and_reported_in_its_own_row(
    evidence: dict[str, Any],
) -> None:
    washington = [row for row in evidence["demand_model_validation"]["per_state"]
                  if row["state"] == "WA"]
    assert washington, "Washington must still be scored, just not aggregated"
    for row in washington:
        assert row["independent"] is False
        assert row["status"] == "non_independent_preprocessing_selection_state"


# --- P3-C: D2, no supply feature in the primary model -------------------------------

def test_p3_c_the_primary_feature_set_contains_no_supply_derived_feature() -> None:
    assert_primary_feature_set_is_clean()
    assert_supply_features_are_absent()
    assert set(FEATURE_NAMES).isdisjoint(SUPPLY_FEATURE_NAMES)


def test_p3_c_the_ablation_is_run_and_reported_under_its_own_heading(
    evidence: dict[str, Any],
) -> None:
    ablation = evidence["supply_feature_ablation"]
    assert "forbidden in the primary" in ablation["WARNING"]
    assert set(ablation["supply_features_added"]) == set(SUPPLY_FEATURE_NAMES)
    assert "aggregate_weighted_wape_with_supply_features" in ablation
    assert "aggregate_weighted_wape_without_supply_features" in ablation


# --- P3-D: reconciliation is exact --------------------------------------------------

def test_p3_d_the_reconciliation_identity_holds_to_floating_point(
    evidence: dict[str, Any],
) -> None:
    surface = evidence["national_surface"]
    assert surface["reconciliation_max_residual"] < 1e-6
    assert surface["unconstrained_tracts"] == 0
    assert surface["reconciliation_method"] == "proportional"


# --- P3-E: uncertainty --------------------------------------------------------------

def test_p3_e_a_calibration_curve_is_produced(evidence: dict[str, Any]) -> None:
    curve = evidence["uncertainty_calibration_washington_only"]
    assert len(curve) >= 2
    for row in curve:
        assert set(row) == {"bin", "n", "mean_uncertainty", "mean_absolute_error"}
    means = [row["mean_uncertainty"] for row in curve]
    assert means == sorted(means), "bins must be ordered by uncertainty"


def test_p3_e_the_weights_are_never_presented_as_calibrated(
    evidence: dict[str, Any],
) -> None:
    """CLAUDE.md §18 anti-pattern 4."""
    surface = evidence["national_surface"]
    assert surface["weights_are_calibrated"] is False
    assert len(surface["weight_sensitivity"]) == 5


def test_p3_e_the_transformation_penalty_is_measured_not_chosen(
    evidence: dict[str, Any],
) -> None:
    """CLAUDE.md §7.4 component 5 forbids hard-coded numeric penalties."""
    ladder = evidence["transformation_ladder"]
    assert any(rung["method"] == "hud_res_ratio" for rung in ladder)
    penalty = evidence["allocation_penalty"]
    measured = [penalty[grain] for grain in GRAIN_ORDER if grain in penalty]
    assert measured == sorted(measured), (
        f"the measured ladder violates the ordering CLAUDE.md §7.4 predicts: {penalty}")
    assert penalty["native_tract"] == 0.0


# --- P3-F: the two orthogonal status fields -----------------------------------------

def test_p3_f_evidence_grain_and_tier_are_reported_separately(
    evidence: dict[str, Any],
) -> None:
    surface = evidence["national_surface"]
    grains = surface["tracts_by_evidence_grain"]
    tiers = surface["tracts_by_confidence_tier"]
    assert sum(grains.values()) == sum(tiers.values()) == surface["tracts"]
    assert set(tiers) <= {"A", "B", "C"}


def test_p3_f_no_tract_is_labelled_zip_anchored(evidence: dict[str, Any]) -> None:
    """Phase 3 allocates no ZIP count onto a tract, so no tract rests on a ZIP total."""
    grains = evidence["national_surface"]["tracts_by_evidence_grain"]
    assert "zip_anchored" not in grains


def test_p3_f_tier_a_exists_only_where_sub_state_evidence_constrains_the_value(
    evidence: dict[str, Any],
) -> None:
    surface = evidence["national_surface"]
    grains = surface["tracts_by_evidence_grain"]
    sub_state = sum(count for grain, count in grains.items()
                    if grain != "state_total_only")
    assert surface["tracts_by_confidence_tier"]["A"] == sub_state


# --- P3-G: record accounting --------------------------------------------------------

def test_p3_g_every_observed_source_publishes_a_balanced_ledger(
    evidence: dict[str, Any],
) -> None:
    for state, observed in evidence["observed_sources"].items():
        accounting = observed["record_accounting"]
        assert accounting["balances"] is True, state
        assert (accounting["retrieved"]
                == accounting["included"] + accounting["excluded_total"]), state


def test_p3_g_every_panel_join_publishes_a_balanced_ledger(
    evidence: dict[str, Any],
) -> None:
    for state, panel in evidence["panels"].items():
        accounting = panel["join_accounting"]
        assert accounting["balances"] is True, state


def test_p3_g_the_out_of_state_zip_defect_is_visible_in_the_ledgers(
    evidence: dict[str, Any],
) -> None:
    """Oregon's export carries ZIPs in Puerto Rico, Massachusetts and Manhattan."""
    oregon = evidence["panels"]["OR"]["join_accounting"]["excluded_by_reason"]
    assert oregon["zip_outside_the_registering_state"] > 0


# --- P3-H: the target definition ----------------------------------------------------

def test_p3_h_the_target_is_battery_electric_and_says_so(
    evidence: dict[str, Any],
) -> None:
    assert "battery-electric" in evidence["target_definition"]
    assert "PHEV" in evidence["target_definition"]


def test_p3_h_the_pre_registration_is_named_in_the_artifact(
    evidence: dict[str, Any],
) -> None:
    assert evidence["pre_registration"] == (
        "docs/evidence/P3-0_phase3_preregistration.md")
    assert (PATHS.root / evidence["pre_registration"]).exists()
