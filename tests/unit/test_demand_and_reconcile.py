"""The candidate estimators, the metrics, and the two reconcilers."""

from __future__ import annotations

import numpy as np
import pytest

from pipeline.model.demand import (
    EXPOSURE_HOUSEHOLDS,
    EXPOSURE_POPULATION,
    MIN_TRAINING_EXPOSURE,
    BoostedPoissonRate,
    ConstantRateBaseline,
    DemandModelError,
    ModelRow,
    PoissonRate,
    PopulationShareBaseline,
    RidgeLogRate,
    candidate_estimators,
    design_matrix,
    exposures,
    fit,
    mae,
    observed,
    r_squared,
    wape,
)
from pipeline.model.features import FEATURE_NAMES
from pipeline.model.reconcile import (
    RECONCILIATION_TOLERANCE,
    Constraint,
    IterativeProportionalFitting,
    ProportionalReconciler,
    ReconciledEstimates,
    ReconciliationError,
    candidate_reconcilers,
    constraints_from_totals,
)


def rows(n: int = 40, observed_counts: bool = True) -> list[ModelRow]:
    out = []
    for i in range(n):
        features = {name: float((i * 7 + j) % 11) / 11.0
                    for j, name in enumerate(FEATURE_NAMES)}
        out.append(ModelRow(
            state="XX", geography="zcta", geoid=f"{i:05d}",
            households=100.0 + i, population=250.0 + 3 * i, features=features,
            observed_bev=float(i % 9) if observed_counts else None,
        ))
    return out


# --- design matrix and exposure -----------------------------------------------------

def test_the_design_matrix_follows_the_declared_feature_order() -> None:
    matrix = design_matrix(rows(3))
    assert matrix.shape == (3, len(FEATURE_NAMES))


def test_an_empty_design_matrix_is_refused() -> None:
    with pytest.raises(DemandModelError, match="no rows"):
        design_matrix([])


def test_exposure_is_households_or_population_as_the_estimator_declares() -> None:
    sample = rows(2)
    assert list(exposures(sample)) == [100.0, 101.0]
    assert list(exposures(sample, EXPOSURE_POPULATION)) == [250.0, 253.0]


def test_training_on_rows_without_observed_counts_is_refused() -> None:
    with pytest.raises(DemandModelError, match="no observed count"):
        observed(rows(2, observed_counts=False))


# --- estimators ---------------------------------------------------------------------

def test_five_candidates_are_offered_simplest_first() -> None:
    names = [e.name for e in candidate_estimators()]
    assert names == ["baseline_household_share", "baseline_population_share",
                     "ridge_log_rate", "poisson_glm", "boosted_poisson"]
    ranks = [e.complexity_rank for e in candidate_estimators()]
    assert ranks == sorted(ranks)


def test_every_candidate_fits_and_predicts_a_non_negative_count() -> None:
    sample = rows()
    for estimator in candidate_estimators():
        model = fit(estimator, sample)
        predicted = model.predict_counts(sample)
        assert predicted.shape == (len(sample),)
        assert (predicted >= 0).all(), estimator.name
        assert model.training_rows == len(sample)
        assert model.training_states == ("XX",)


def test_the_two_baselines_are_genuinely_different_models() -> None:
    """A per-person rate converted to a per-household rate collapses to the household
    baseline, and the two reported identical error for every state until this was fixed."""
    sample = rows()
    household = fit(ConstantRateBaseline(), sample).predict_counts(sample)
    population = fit(PopulationShareBaseline(), sample).predict_counts(sample)
    assert not np.allclose(household, population)
    assert ConstantRateBaseline().exposure_kind == EXPOSURE_HOUSEHOLDS
    assert PopulationShareBaseline().exposure_kind == EXPOSURE_POPULATION


def test_the_baselines_reproduce_the_training_total() -> None:
    sample = rows()
    total = sum(float(r.observed_bev or 0) for r in sample)
    for estimator in (ConstantRateBaseline(), PopulationShareBaseline()):
        predicted = fit(estimator, sample).predict_counts(sample)
        assert float(predicted.sum()) == pytest.approx(total, rel=1e-9)


def test_a_baseline_with_no_exposure_at_all_reports_a_zero_rate() -> None:
    flat = [ModelRow("XX", "zcta", "1", 5.0, 0.0,
                     dict.fromkeys(FEATURE_NAMES, 0.0), 3.0)]
    with pytest.raises(DemandModelError, match="exposure is zero"):
        fit(PopulationShareBaseline(), flat)


def test_predicting_before_fitting_is_refused() -> None:
    matrix = design_matrix(rows(2))
    for estimator in (RidgeLogRate(), PoissonRate(), BoostedPoissonRate()):
        with pytest.raises(DemandModelError, match="before it was fitted"):
            estimator.predict_rate(matrix)


def test_an_unfitted_standardiser_is_refused() -> None:
    estimator = RidgeLogRate()
    with pytest.raises(DemandModelError, match="before it was fitted"):
        estimator._scaler.apply(design_matrix(rows(2)))


def test_a_constant_feature_column_does_not_produce_nan_coefficients() -> None:
    """Zero variance would divide by zero and silently poison the whole model."""
    sample = [
        ModelRow("XX", "zcta", str(i), 100.0 + i, 250.0,
                 dict.fromkeys(FEATURE_NAMES, 1.0), float(i % 5))
        for i in range(20)
    ]
    predicted = fit(RidgeLogRate(), sample).predict_counts(sample)
    assert np.isfinite(predicted).all()


def test_training_needs_at_least_one_row_with_exposure() -> None:
    sample = [ModelRow("XX", "zcta", "1", 0.0, 0.0,
                       dict.fromkeys(FEATURE_NAMES, 0.5), 1.0)]
    assert MIN_TRAINING_EXPOSURE == 1.0
    with pytest.raises(DemandModelError, match="zero exposure"):
        fit(PoissonRate(), sample)


# --- metrics ------------------------------------------------------------------------

def test_wape_is_total_error_over_total_observed() -> None:
    actual = np.array([10.0, 10.0])
    assert wape(actual, np.array([12.0, 8.0])) == pytest.approx(0.2)


def test_wape_is_undefined_when_nothing_was_observed() -> None:
    with pytest.raises(DemandModelError, match="observed total is zero"):
        wape(np.zeros(3), np.ones(3))


def test_mae_and_r_squared_behave_as_defined() -> None:
    actual = np.array([1.0, 2.0, 3.0])
    assert mae(actual, actual) == 0.0
    assert r_squared(actual, actual) == pytest.approx(1.0)


def test_r_squared_is_undefined_when_every_observation_is_equal() -> None:
    with pytest.raises(DemandModelError, match="every observed value is equal"):
        r_squared(np.ones(3), np.zeros(3))


# --- reconciliation -----------------------------------------------------------------

def test_a_partition_constraint_is_met_exactly() -> None:
    estimates = np.array([1.0, 3.0, 5.0])
    constraints = constraints_from_totals(["A", "A", "B"], {"A": 100.0, "B": 50.0})
    result = ProportionalReconciler().reconcile(estimates, constraints)
    assert list(result.values) == [25.0, 75.0, 50.0]
    assert result.max_residual <= RECONCILIATION_TOLERANCE
    result.assert_satisfied(constraints)


def test_a_group_whose_estimates_sum_to_zero_is_spread_evenly() -> None:
    """Leaving it at zero would silently discard an observed total."""
    result = ProportionalReconciler().reconcile(
        np.zeros(2), [Constraint("A", 10.0, (0, 1))])
    assert list(result.values) == [5.0, 5.0]


def test_an_area_no_constraint_binds_is_reported_not_dropped() -> None:
    result = ProportionalReconciler().reconcile(
        np.array([1.0, 2.0]), [Constraint("A", 10.0, (0,))])
    assert result.unconstrained == (1,)
    assert result.values[1] == 2.0


def test_overlapping_constraints_are_refused_by_the_exact_reconciler() -> None:
    with pytest.raises(ReconciliationError, match="Overlapping constraints"):
        ProportionalReconciler().reconcile(
            np.ones(3), [Constraint("A", 1.0, (0, 1)), Constraint("B", 1.0, (1, 2))])


def test_a_constraint_referring_to_a_missing_area_is_refused() -> None:
    with pytest.raises(ReconciliationError, match="outside the 2 estimates"):
        ProportionalReconciler().reconcile(np.ones(2), [Constraint("A", 1.0, (5,))])


def test_a_negative_or_empty_constraint_is_refused_at_construction() -> None:
    with pytest.raises(ReconciliationError, match="negative total"):
        Constraint("A", -1.0, (0,))
    with pytest.raises(ReconciliationError, match="binds no areas"):
        Constraint("A", 1.0, ())


def test_movement_is_symmetric_relative_and_bounded() -> None:
    result = ReconciledEstimates(np.array([10.0]), np.array([0.0]), 1, 0.0, "p")
    assert 0.0 <= float(result.movement[0]) <= 1.0
    unchanged = ReconciledEstimates(np.array([5.0]), np.array([5.0]), 1, 0.0, "p")
    assert float(unchanged.movement[0]) == 0.0


def test_an_unmet_constraint_raises_rather_than_publishing() -> None:
    result = ReconciledEstimates(np.array([1.0]), np.array([1.0]), 1, 0.0, "p")
    with pytest.raises(ReconciliationError, match="is off by"):
        result.assert_satisfied([Constraint("A", 99.0, (0,))])


def test_constraints_are_only_built_where_a_total_exists() -> None:
    built = constraints_from_totals(["A", "B"], {"A": 5.0})
    assert [c.name for c in built] == ["A"]


def test_ipf_satisfies_overlapping_constraints_and_reports_its_work() -> None:
    result = IterativeProportionalFitting().reconcile(
        np.array([1.0, 1.0, 1.0]),
        [Constraint("x", 10.0, (0, 1)), Constraint("y", 10.0, (1, 2))])
    assert result.iterations >= 1
    assert result.max_residual <= RECONCILIATION_TOLERANCE
    assert result.method == "ipf"


def test_ipf_seeds_a_group_that_starts_at_zero() -> None:
    """A zero start can never be scaled up to a positive total."""
    result = IterativeProportionalFitting().reconcile(
        np.zeros(2), [Constraint("x", 8.0, (0, 1))])
    assert list(result.values) == [4.0, 4.0]


def test_ipf_stops_at_its_iteration_cap_and_reports_the_residual() -> None:
    """An inconsistent constraint set cannot converge, and the harness must say so
    rather than silently returning a wrong answer."""
    result = IterativeProportionalFitting(max_iterations=5).reconcile(
        np.array([1.0, 1.0, 1.0]),
        [Constraint("x", 10.0, (0, 1)), Constraint("y", 1.0, (1, 2))])
    assert result.iterations == 5
    assert result.max_residual > RECONCILIATION_TOLERANCE


def test_both_reconcilers_are_offered_behind_one_interface() -> None:
    names = [r.name for r in candidate_reconcilers()]
    assert names == ["proportional", "ipf"]


def test_ipf_leaves_a_group_that_is_already_zero_against_a_zero_total_alone() -> None:
    """Scaling a zero group is undefined; skipping it is correct, not a silent drop."""
    result = IterativeProportionalFitting().reconcile(
        np.array([1.0, 1.0, 0.0]),
        [Constraint("x", 4.0, (0, 1)), Constraint("z", 0.0, (2,))])
    assert list(result.values) == [2.0, 2.0, 0.0]
    assert result.max_residual <= RECONCILIATION_TOLERANCE
