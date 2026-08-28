"""The continuous uncertainty score: five components, declared weights, honest tiers."""

from __future__ import annotations

import numpy as np
import pytest

from pipeline.model.demand import ModelRow, PoissonRate
from pipeline.model.features import FEATURE_NAMES
from pipeline.model.uncertainty import (
    BC_THRESHOLD_QUANTILE,
    COMPONENT_NAMES,
    DEFAULT_WEIGHTS,
    TIER_A,
    TIER_B,
    TIER_C,
    TIER_LABELS,
    AllocationPenalty,
    UncertaintyError,
    assign_tier,
    bc_threshold,
    bootstrap_prediction_spread,
    combine,
    complexity_multipliers,
    mahalanobis_percentile,
    relative_interval_width,
    source_degradation_share,
    weight_sensitivity,
)


def components(n: int = 10) -> dict[str, list[float]]:
    return {name: list(np.linspace(0.0, 1.0, n)) for name in COMPONENT_NAMES}


def rows(n: int = 30) -> list[ModelRow]:
    return [
        ModelRow("XX", "zcta", f"{i:05d}", 100.0 + i, 250.0,
                 {name: float((i * 5 + j) % 7) / 7.0
                  for j, name in enumerate(FEATURE_NAMES)},
                 float(i % 6))
        for i in range(n)
    ]


# --- declared configuration ---------------------------------------------------------

def test_five_components_are_declared_with_equal_weights_summing_to_one() -> None:
    assert len(COMPONENT_NAMES) == 5
    assert set(DEFAULT_WEIGHTS) == set(COMPONENT_NAMES)
    assert sum(DEFAULT_WEIGHTS.values()) == pytest.approx(1.0)
    assert set(DEFAULT_WEIGHTS.values()) == {0.2}


def test_the_published_score_never_claims_its_weights_are_calibrated() -> None:
    """CLAUDE.md 18 anti-pattern 4: hand-picked weights presented as calibrated."""
    score = combine(["a"], {name: [0.5] for name in COMPONENT_NAMES})[0]
    assert score.to_dict()["weights_are_calibrated"] is False


def test_tier_a_is_labelled_sub_state_anchored_and_never_observed() -> None:
    """Amendment A3: most Tier A areas are ZIP- or county-anchored, not observed."""
    assert TIER_LABELS[TIER_A] == "sub-state anchored"
    assert "observed" not in TIER_LABELS[TIER_A]


# --- c1 -----------------------------------------------------------------------------

def test_the_bootstrap_spreads_over_resampled_training_areas() -> None:
    training, targets = rows(40), rows(5)
    spread = bootstrap_prediction_spread(PoissonRate, training, targets, replicates=4)
    assert spread.shape == (5,)
    assert (spread >= 0).all()


def test_the_bootstrap_is_reproducible_from_its_seed() -> None:
    training, targets = rows(30), rows(4)
    first = bootstrap_prediction_spread(PoissonRate, training, targets, 3, seed=7)
    second = bootstrap_prediction_spread(PoissonRate, training, targets, 3, seed=7)
    assert np.allclose(first, second)


def test_a_bootstrap_needs_replicates_and_training_rows() -> None:
    with pytest.raises(UncertaintyError, match="at least two replicates"):
        bootstrap_prediction_spread(PoissonRate, rows(5), rows(2), replicates=1)
    with pytest.raises(UncertaintyError, match="no training rows"):
        bootstrap_prediction_spread(PoissonRate, [], rows(2), replicates=3)


def test_interval_width_is_relative_so_a_large_area_is_not_penalised_for_size() -> None:
    half = np.array([10.0, 10.0])
    estimate = np.array([10.0, 1000.0])
    relative = relative_interval_width(half, estimate)
    assert relative[0] > relative[1]
    assert (relative >= 0).all() and (relative <= 1).all()


# --- c2 -----------------------------------------------------------------------------

def test_out_of_distribution_is_a_percentile_of_mahalanobis_distance() -> None:
    rng = np.random.default_rng(0)
    training = rng.normal(size=(200, 3))
    targets = np.vstack([np.zeros((1, 3)), np.full((1, 3), 8.0)])
    percentile = mahalanobis_percentile(training, targets)
    assert percentile[1] > percentile[0]
    assert (percentile > 0).all() and (percentile < 1).all()


def test_a_singular_covariance_is_ridged_rather_than_failing() -> None:
    """Two collinear features would otherwise remove the component altogether."""
    training = np.tile(np.array([[1.0, 1.0]]), (10, 1))
    out = mahalanobis_percentile(training, np.array([[1.0, 1.0], [5.0, 5.0]]))
    assert np.isfinite(out).all()


def test_mismatched_feature_counts_are_refused() -> None:
    with pytest.raises(UncertaintyError, match="training has 3 features"):
        mahalanobis_percentile(np.zeros((5, 3)), np.zeros((2, 4)))


# --- c4 -----------------------------------------------------------------------------

def penalty() -> AllocationPenalty:
    return AllocationPenalty(
        statewide_tvd={"native_tract": 0.0, "zip_anchored": 0.1621,
                       "county_anchored": 0.2367, "state_total_only": 0.3049},
        complexity_multiplier=complexity_multipliers(
            {"1": 0.004584, "8+": 0.187192}, 0.179354),
    )


def test_the_penalty_comes_from_the_measured_ladder_and_respects_its_order() -> None:
    p = penalty()
    assert p.for_row("native_tract") == 0.0
    assert p.for_row("zip_anchored") < p.for_row("county_anchored")
    assert p.for_row("county_anchored") < p.for_row("state_total_only")


def test_a_complex_zip_is_penalised_more_than_a_single_tract_zip() -> None:
    p = penalty()
    assert p.for_row("zip_anchored", "1") < p.for_row("zip_anchored", "8+")


def test_an_unmeasured_grain_raises_rather_than_inventing_a_penalty() -> None:
    """CLAUDE.md 7.4 forbids hard-coded numeric penalties."""
    with pytest.raises(UncertaintyError, match="must never be invented"):
        penalty().for_row("something_new")


def test_complexity_multipliers_need_a_positive_overall_measurement() -> None:
    with pytest.raises(UncertaintyError, match="must be positive"):
        complexity_multipliers({"1": 0.1}, 0.0)


# --- c5 -----------------------------------------------------------------------------

def test_source_degradation_is_the_share_of_non_confirmed_sources() -> None:
    assert source_degradation_share([]) == 0.0
    assert source_degradation_share(["confirmed", "confirmed"]) == 0.0
    assert source_degradation_share(["confirmed", "degraded"]) == 0.5
    assert source_degradation_share(["unavailable"]) == 1.0


# --- combination --------------------------------------------------------------------

def test_the_score_is_the_weighted_mean_of_the_five_components() -> None:
    scores = combine(["a", "b"], {name: [0.0, 1.0] for name in COMPONENT_NAMES})
    assert scores[0].score == pytest.approx(0.0)
    assert scores[1].score == pytest.approx(1.0)


def test_a_component_out_of_range_is_clipped_not_propagated() -> None:
    scores = combine(["a"], {name: [5.0] for name in COMPONENT_NAMES})
    assert scores[0].score == pytest.approx(1.0)


def test_a_missing_component_is_refused_rather_than_overstating_confidence() -> None:
    partial = {name: [0.5] for name in COMPONENT_NAMES[:-1]}
    with pytest.raises(UncertaintyError, match="first-class output"):
        combine(["a"], partial)


def test_weights_that_do_not_sum_to_one_are_refused() -> None:
    weights = dict.fromkeys(COMPONENT_NAMES, 0.5)
    with pytest.raises(UncertaintyError, match="sum to"):
        combine(["a"], {name: [0.5] for name in COMPONENT_NAMES}, weights)


def test_a_component_of_the_wrong_length_is_refused() -> None:
    payload = {name: [0.5, 0.5] for name in COMPONENT_NAMES}
    payload["source_degradation"] = [0.5]
    with pytest.raises(UncertaintyError, match="has 1 values for 2 areas"):
        combine(["a", "b"], payload)


def test_weight_sensitivity_reports_how_far_each_component_moves_the_score() -> None:
    """D7 requires a weight-sensitivity control to ship with any composite."""
    payload = components(20)
    payload["source_degradation"] = [0.0] * 20
    moved = weight_sensitivity(payload)
    assert set(moved) == set(COMPONENT_NAMES)
    assert moved["source_degradation"] < 0
    assert moved["prediction_interval"] > 0


# --- tiers --------------------------------------------------------------------------

def test_the_bc_threshold_is_a_quantile_of_the_modelled_population() -> None:
    scores = [float(i) / 10 for i in range(11)]
    grains = ["state_total_only"] * 11
    assert BC_THRESHOLD_QUANTILE == 0.75
    assert bc_threshold(scores, grains) == pytest.approx(0.75)


def test_the_threshold_ignores_areas_that_are_not_state_total_only() -> None:
    scores = [0.9, 0.1, 0.2]
    grains = ["zip_anchored", "state_total_only", "state_total_only"]
    assert bc_threshold(scores, grains) == pytest.approx(0.175)


def test_a_population_with_no_modelled_areas_has_no_threshold() -> None:
    with pytest.raises(UncertaintyError, match="no state-total-only areas"):
        bc_threshold([0.5], ["native_tract"])


def test_the_tier_comes_from_evidence_and_score_never_from_geography() -> None:
    assert assign_tier(0.99, "native_tract", 0.5) == TIER_A
    assert assign_tier(0.99, "county_anchored", 0.5) == TIER_A
    assert assign_tier(0.10, "state_total_only", 0.5) == TIER_B
    assert assign_tier(0.90, "state_total_only", 0.5) == TIER_C
