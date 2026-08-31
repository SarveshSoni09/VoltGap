"""The national tract demand surface: fit, predict, reconcile, score uncertainty.

This is the Phase 3 deliverable. It applies the estimator that leave-one-state-out
validation selected under the pre-registered rule to all 84,400 census tracts,
reconciles the result exactly to published registration totals, attaches the continuous
uncertainty score with its five components, and derives the presentation tier.

**Two orthogonal status fields, never collapsed (amendment A2).**

``evidence_grain`` records the finest observed registration evidence that **constrains
the published value**:

* ``native_tract`` - Washington, where the source reports the tract itself and the
  observed count is published as-is;
* ``county_anchored`` - a state whose observed county totals constrain its tracts;
* ``state_total_only`` - everywhere else.

``zip_anchored`` **does not appear in the published surface, and that is deliberate.**
Eleven states publish registrations by ZIP Code, and those observations do real work:
they train the model and they are what leave-one-state-out scores against. But Phase 3
does not allocate ZIP counts onto tracts, so no tract value is anchored to a ZIP total,
and labelling one ``zip_anchored`` would claim evidence the published number does not
rest on. Whether ZIP totals should become constraints is a measured, open question
recorded in ``docs/FUTURE_WORK.md``; it is not silently assumed either way.

A consequence worth stating plainly: **no tract in this surface carries a ZIP- or
county-derived allocated value, so the requirement that no such value be labelled
``directly_observed`` is satisfied by construction rather than by a check.**
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from pipeline.model.demand import (
    Estimator,
    FloatArray,
    ModelRow,
    candidate_estimators,
    design_matrix,
    fit,
)
from pipeline.model.observed import STATE_FIPS, StateObservations, StateTotal
from pipeline.model.panel import AreaTable, StatePanel, prediction_rows
from pipeline.model.reconcile import (
    ProportionalReconciler,
    ReconciledEstimates,
    constraints_from_totals,
)
from pipeline.model.uncertainty import (
    AllocationPenalty,
    UncertaintyScore,
    assign_tier,
    bc_threshold,
    bootstrap_prediction_spread,
    combine,
    mahalanobis_percentile,
    relative_interval_width,
    source_degradation_share,
    weight_sensitivity,
)
from pipeline.spatial.geography import EstimateMethod, EvidenceGrain, SourceGeography

NATIVE_TRACT = EvidenceGrain.NATIVE_TRACT.value
COUNTY_ANCHORED = EvidenceGrain.COUNTY_ANCHORED.value
STATE_TOTAL_ONLY = EvidenceGrain.STATE_TOTAL_ONLY.value


@dataclass(frozen=True)
class TractEstimate:
    """One published tract row. Every field a reader needs to judge it travels with it."""

    geoid: str
    state_fips: str
    households: float
    population: float
    raw_estimate: float
    estimate: float
    evidence_grain: str
    estimate_method: str
    uncertainty_score: float
    uncertainty_components: Mapping[str, float]
    confidence_tier: str
    constraint_name: str
    constraint_vintage: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "geoid": self.geoid,
            "state_fips": self.state_fips,
            "households": round(self.households, 1),
            "population": round(self.population, 1),
            "bev_estimate": round(self.estimate, 4),
            "bev_estimate_unreconciled": round(self.raw_estimate, 4),
            "evidence_grain": self.evidence_grain,
            "estimate_method": self.estimate_method,
            "uncertainty_score": round(self.uncertainty_score, 6),
            "uncertainty_components": {
                k: round(v, 6) for k, v in sorted(self.uncertainty_components.items())
            },
            "confidence_tier": self.confidence_tier,
            "constraint": self.constraint_name,
            "constraint_vintage": self.constraint_vintage,
        }


@dataclass(frozen=True)
class DemandSurface:
    """The national surface plus everything needed to audit how it was made."""

    estimates: tuple[TractEstimate, ...]
    estimator: str
    training_states: tuple[str, ...]
    training_rows: int
    reconciliation: ReconciledEstimates
    weight_sensitivity: Mapping[str, float]
    bc_threshold: float

    def summary(self) -> dict[str, object]:
        by_grain: dict[str, int] = {}
        by_tier: dict[str, int] = {}
        for row in self.estimates:
            by_grain[row.evidence_grain] = by_grain.get(row.evidence_grain, 0) + 1
            by_tier[row.confidence_tier] = by_tier.get(row.confidence_tier, 0) + 1
        from pipeline.sources.census_acs import ACS_YEAR

        return {
            "tracts": len(self.estimates),
            "estimator": self.estimator,
            # The vintage the PRODUCTION surface was built from. Phase 5's backtests
            # must not use it: D1 requires feature_vintage <= prediction_cutoff.
            "feature_vintage": f"ACS {ACS_YEAR} 5-year",
            "training_states": list(self.training_states),
            "training_rows": self.training_rows,
            "national_bev_estimate": int(sum(r.estimate for r in self.estimates)),
            "tracts_by_evidence_grain": dict(sorted(by_grain.items())),
            "tracts_by_confidence_tier": dict(sorted(by_tier.items())),
            "mean_uncertainty": round(
                float(np.mean([r.uncertainty_score for r in self.estimates])), 6
            ),
            "bc_threshold": round(self.bc_threshold, 6),
            "weights_are_calibrated": False,
            "weight_sensitivity": {
                k: round(v, 6) for k, v in sorted(self.weight_sensitivity.items())
            },
            "reconciliation_method": self.reconciliation.method,
            "reconciliation_max_residual": self.reconciliation.max_residual,
            "unconstrained_tracts": len(self.reconciliation.unconstrained),
        }


def estimator_by_name(name: str) -> Estimator:
    for candidate in candidate_estimators():
        if candidate.name == name:
            return candidate
    raise ValueError(f"no candidate estimator named {name!r}")


def county_constraint_states(
    observations: Mapping[str, StateObservations],
) -> dict[str, dict[str, float]]:
    """County BEV totals, per state, for states observed at county grain."""
    out: dict[str, dict[str, float]] = {}
    for state, observed in observations.items():
        if observed.source_geography is not SourceGeography.COUNTY:
            continue
        out[state] = {c.geography_id: float(c.bev_count) for c in observed.counts}
    return out


def build_surface(
    tract_table: AreaTable,
    panels: Mapping[str, StatePanel],
    observations: Mapping[str, StateObservations],
    state_totals: Mapping[str, StateTotal],
    penalty: AllocationPenalty,
    estimator_name: str,
    source_statuses: Sequence[str] = (),
    bootstrap_replicates: int = 20,
) -> DemandSurface:
    """Fit, predict nationally, reconcile exactly, and score uncertainty."""
    # The final production fit uses every state that is usable as TRAINING evidence,
    # which includes Washington. Barring a state from the independent validation
    # aggregate is a statement about its evaluation, not about the information its
    # observations carry (pre-registration amendment, 2026-08-29).
    training = [row for panel in panels.values() if panel.is_trainable
                for row in panel.rows]
    if not training:
        raise ValueError(
            "no training rows at all; the surface cannot be fitted. Note this is a "
            "different condition from having no INDEPENDENT states: a state barred "
            "from the validation aggregate is still training evidence."
        )
    model = fit(estimator_by_name(estimator_name), training)
    targets = prediction_rows(tract_table)
    raw = model.predict_counts(targets)

    counties = county_constraint_states(observations)
    grains, group_of, totals, vintages = _constraint_plan(
        targets, counties, state_totals
    )
    constraints = constraints_from_totals(group_of, totals)
    reconciled = ProportionalReconciler().reconcile(raw, constraints)
    reconciled.assert_satisfied(constraints)

    observed_tracts = _observed_tract_counts(observations)
    values = np.array(reconciled.values, dtype=np.float64)
    for position, row in enumerate(targets):
        if row.geoid in observed_tracts:
            values[position] = observed_tracts[row.geoid]
            grains[position] = NATIVE_TRACT

    components = _components(
        model=model, training=training, targets=targets, raw=raw,
        reconciled=reconciled, grains=grains, penalty=penalty,
        source_statuses=source_statuses, replicates=bootstrap_replicates,
        estimator_name=estimator_name,
    )
    scores = combine([row.geoid for row in targets], components)
    threshold = bc_threshold([s.score for s in scores], grains)
    sensitivity = weight_sensitivity(components)

    estimates = tuple(
        _to_estimate(row, position, values, raw, grains, scores, threshold,
                     group_of, vintages, observed_tracts)
        for position, row in enumerate(targets)
    )
    return DemandSurface(
        estimates=estimates,
        estimator=estimator_name,
        training_states=model.training_states,
        training_rows=model.training_rows,
        reconciliation=reconciled,
        weight_sensitivity=sensitivity,
        bc_threshold=threshold,
    )


def _constraint_plan(
    targets: Sequence[ModelRow],
    county_totals: Mapping[str, Mapping[str, float]],
    state_totals: Mapping[str, StateTotal],
) -> tuple[list[str], list[str], dict[str, float], dict[str, str | None]]:
    """Which constraint binds each tract: its county where observed, else its state.

    Counties nest inside states and tracts inside counties, so whichever is chosen the
    constraints partition the tracts and the reconciliation is exact.
    """
    by_state_fips = {STATE_FIPS[state]: totals for state, totals in county_totals.items()}
    grains: list[str] = []
    group_of: list[str] = []
    totals: dict[str, float] = {}
    vintages: dict[str, str | None] = {}
    for row in targets:
        state_fips = row.geoid[:2]
        county_fips = row.geoid[:5]
        counties = by_state_fips.get(state_fips)
        if counties is not None and county_fips in counties:
            group_of.append(county_fips)
            totals[county_fips] = counties[county_fips]
            vintages[county_fips] = "state DMV county observation"
            grains.append(COUNTY_ANCHORED)
            continue
        group_of.append(state_fips)
        grains.append(STATE_TOTAL_ONLY)
        total = state_totals.get(state_fips)
        if total is not None:
            totals[state_fips] = float(total.bev_count)
            vintages[state_fips] = total.vintage
    return grains, group_of, totals, vintages


def _observed_tract_counts(
    observations: Mapping[str, StateObservations],
) -> dict[str, float]:
    """Directly observed tract counts, which are published instead of an estimate."""
    out: dict[str, float] = {}
    for observed in observations.values():
        if observed.source_geography is SourceGeography.TRACT:
            for count in observed.counts:
                out[count.geography_id] = float(count.bev_count)
    return out


def _components(
    *, model: object, training: Sequence[ModelRow], targets: Sequence[ModelRow],
    raw: FloatArray, reconciled: ReconciledEstimates, grains: Sequence[str],
    penalty: AllocationPenalty, source_statuses: Sequence[str], replicates: int,
    estimator_name: str,
) -> dict[str, list[float]]:
    spread = bootstrap_prediction_spread(
        lambda: estimator_by_name(estimator_name), training, targets, replicates
    )
    degradation = source_degradation_share(list(source_statuses))
    return {
        "prediction_interval": list(relative_interval_width(spread, raw)),
        "out_of_distribution": list(
            mahalanobis_percentile(design_matrix(list(training)),
                                   design_matrix(list(targets)))
        ),
        "reconciliation_movement": list(reconciled.movement),
        "allocation_error": [penalty.for_row(grain) for grain in grains],
        "source_degradation": [degradation] * len(targets),
    }


def _to_estimate(
    row: ModelRow, position: int, values: FloatArray, raw: FloatArray,
    grains: Sequence[str], scores: Sequence[UncertaintyScore], threshold: float,
    group_of: Sequence[str], vintages: Mapping[str, str | None],
    observed_tracts: Mapping[str, float],
) -> TractEstimate:
    grain = grains[position]
    score = scores[position]
    if row.geoid in observed_tracts:
        method = EstimateMethod.DIRECTLY_OBSERVED.value
        tier = assign_tier(score.score, grain, threshold)
    else:
        tier = assign_tier(score.score, grain, threshold)
        method = (EstimateMethod.MODELED_HIGH_UNCERTAINTY.value if tier == "C"
                  else EstimateMethod.MODELED.value)
    return TractEstimate(
        geoid=row.geoid,
        state_fips=row.geoid[:2],
        households=row.households,
        population=row.population,
        raw_estimate=float(raw[position]),
        estimate=float(values[position]),
        evidence_grain=grain,
        estimate_method=method,
        uncertainty_score=score.score,
        uncertainty_components=dict(score.components),
        confidence_tier=tier,
        constraint_name=group_of[position],
        constraint_vintage=vintages.get(group_of[position]),
    )
