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
from pipeline.model.precedence import (
    ConstraintSource,
    OperativeConstraint,
    resolve_all,
)
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

#: How a published value came to hold the number it holds. Distinct from
#: ``estimate_method``, which says whether the value was observed or modelled: this says
#: what KIND of evidence produced it, and in particular tells a **completed zero derived
#: from an exhaustive registry** apart from a missing or unknown value.
PROVENANCE_OBSERVED_COUNT = "native_registry_observed_count"
PROVENANCE_ZERO_BY_ABSENCE = "native_registry_zero_by_absence"
PROVENANCE_MODELLED = "modeled_reconciled"

#: What the equity objective actually measures, published alongside every artifact that
#: carries an equity number so a reader of the JSON alone cannot mistake it for a
#: composite disadvantage index. CLAUDE.md §8 requires the primary equity measure to come
#: from current ACS-derived indicators rather than the archived CEJST overlay, and §17
#: forbids shipping a composite index without a weight-sensitivity control. This is ONE
#: named indicator, so there are no weights to hand-pick — and correspondingly it is a
#: narrower view of disadvantage than a composite would be.
EQUITY_INDICATOR = (
    "population in households with income below $35,000 a year, from the ACS "
    "five-year feature income_share_under_35k multiplied by tract population. ONE "
    "named current ACS-derived socioeconomic indicator, NOT a composite index and NOT "
    "a general measure of disadvantage."
)

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
    #: Population in households below $35,000 a year, from ACS `income_share_under_35k`.
    #: A **single named current ACS-derived socioeconomic indicator**, not a composite:
    #: CLAUDE.md §8 requires the primary equity measure to be built from current ACS
    #: indicators rather than the archived CEJST overlay, and §17 forbids shipping a
    #: composite index without a weight-sensitivity control. One indicator needs no
    #: weights, so there is nothing to hand-pick.
    equity_population: float
    raw_estimate: float
    estimate: float
    evidence_grain: str
    estimate_method: str
    uncertainty_score: float
    uncertainty_components: Mapping[str, float]
    confidence_tier: str
    constraint_name: str
    constraint_vintage: str | None
    value_provenance: str = PROVENANCE_MODELLED

    def to_dict(self) -> dict[str, object]:
        return {
            "geoid": self.geoid,
            "state_fips": self.state_fips,
            "households": round(self.households, 1),
            "population": round(self.population, 1),
            "equity_population": round(self.equity_population, 2),
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
            "value_provenance": self.value_provenance,
        }


@dataclass(frozen=True)
class DemandSurface:
    """The national surface plus everything needed to audit how it was made."""

    accounting: ConstraintAccounting
    operative_constraints: dict[str, OperativeConstraint]
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
        by_provenance: dict[str, int] = {}
        for row in self.estimates:
            by_grain[row.evidence_grain] = by_grain.get(row.evidence_grain, 0) + 1
            by_tier[row.confidence_tier] = by_tier.get(row.confidence_tier, 0) + 1
            by_provenance[row.value_provenance] = by_provenance.get(
                row.value_provenance, 0) + 1
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
            "tracts_by_value_provenance": dict(sorted(by_provenance.items())),
            "mean_uncertainty": round(
                float(np.mean([r.uncertainty_score for r in self.estimates])), 6
            ),
            "bc_threshold": round(self.bc_threshold, 6),
            "weights_are_calibrated": False,
            "weight_sensitivity": {
                k: round(v, 6) for k, v in sorted(self.weight_sensitivity.items())
            },
            "national_accounting": self.accounting.to_dict(),
            "constraint_precedence": [
                op.to_dict() for _, op in sorted(self.operative_constraints.items())
            ],
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
    observed_tracts = _observed_tract_counts(observations)
    operative = resolve_all(observations, state_totals, counties,
                            county_coverage_complete(observations))
    grains, group_of, totals, vintages = _constraint_plan(
        targets, counties, state_totals, operative, observed_tracts
    )
    constraints = constraints_from_totals(group_of, totals)
    reconciled = ProportionalReconciler().reconcile(raw, constraints)
    reconciled.assert_satisfied(constraints)

    # No post-reconciliation substitution. Observed values entered as constraints above,
    # so the reconciled surface already carries them and still reconciles.
    values = np.array(reconciled.values, dtype=np.float64)

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
    published_by_state: dict[str, float] = {}
    for position, row in enumerate(targets):
        state = row.geoid[:2]
        published_by_state[state] = published_by_state.get(state, 0.0) + float(
            values[position])
    accounting = ConstraintAccounting(
        national_published=float(values.sum()),
        constraint_sum=sum(c.total for c in constraints),
        unconstrained_sum=float(
            sum(values[i] for i in reconciled.unconstrained)
        ),
        per_group={c.name: c.total for c in constraints},
        per_jurisdiction={fips: op.total for fips, op in operative.items()
                          if fips in published_by_state},
    )
    accounting.assert_balanced()
    accounting.assert_every_jurisdiction_balances(published_by_state)
    return DemandSurface(
        accounting=accounting,
        operative_constraints=dict(operative),
        estimates=estimates,
        estimator=estimator_name,
        training_states=model.training_states,
        training_rows=model.training_rows,
        reconciliation=reconciled,
        weight_sensitivity=sensitivity,
        bc_threshold=threshold,
    )


def county_coverage_complete(
    observations: Mapping[str, StateObservations],
) -> tuple[str, ...]:
    """States whose observed counties span every county their tracts fall in.

    Complete coverage lets the counties supersede the state total; partial coverage
    means they merely decompose it (impact I-15).
    """
    from pipeline.spatial.geography import county_fips_lookup

    reference = county_fips_lookup()
    complete: list[str] = []
    for state, observed in observations.items():
        if observed.source_geography is not SourceGeography.COUNTY:
            continue
        all_counties = {fips for (code, _name), fips in reference.items()
                        if code == state}
        seen = {c.geography_id for c in observed.counts}
        if all_counties and seen >= all_counties:
            complete.append(state)
    return tuple(sorted(complete))


def _constraint_plan(
    targets: Sequence[ModelRow],
    county_totals: Mapping[str, Mapping[str, float]],
    state_totals: Mapping[str, StateTotal],
    operative: Mapping[str, OperativeConstraint],
    observed_tracts: Mapping[str, float],
) -> tuple[list[str], list[str], dict[str, float], dict[str, str | None]]:
    """Which constraint binds each tract, following the resolved precedence.

    Three shapes, one per operative source:

    * **native tract registry** - each observed tract is its own constraint, holding its
      observed count, and the jurisdiction's remaining tracts are constrained to **zero**.
      A registry enumerates every registered vehicle, so a tract it does not name has
      none. This is what puts the observed values *inside* the reconciliation rather than
      overwriting it afterwards.
    * **county observations** - one constraint per observed county. Where coverage is
      incomplete the remaining tracts take the **residual** of the state total, never the
      full total the counties have already claimed (impact I-15).
    * **external state total** - one constraint for the jurisdiction.
    """
    by_state_fips = {STATE_FIPS[state]: totals for state, totals in county_totals.items()}
    native_states = {
        fips for fips, op in operative.items()
        if op.chosen.source is ConstraintSource.NATIVE_TRACT_REGISTRY
    }
    grains: list[str] = []
    group_of: list[str] = []
    totals: dict[str, float] = {}
    vintages: dict[str, str | None] = {}

    for row in targets:
        state_fips = row.geoid[:2]
        county_fips = row.geoid[:5]

        if state_fips in native_states:
            op = operative[state_fips]
            if row.geoid in observed_tracts:
                name = f"tract:{row.geoid}"
                group_of.append(name)
                totals[name] = observed_tracts[row.geoid]
                vintages[name] = op.chosen.vintage
                grains.append(NATIVE_TRACT)
            else:
                # Superseding requires the zero-completion licence, so a state reaching
                # here has it: the registry is exhaustively resolved and a tract it does
                # not name genuinely holds none.
                assert op.licenses_zero_completion
                name = f"{state_fips}:zero_by_absence"
                group_of.append(name)
                # An exhaustively resolved jurisdiction-wide registry names every
                # registered vehicle, so a tract it omits genuinely holds none. This is
                # a COMPLETED ZERO, not a literal zero-valued source row, and the
                # distinction is carried on the row as provenance.
                totals.setdefault(name, 0.0)
                vintages[name] = op.chosen.vintage
                grains.append(NATIVE_TRACT)
            continue

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

    # Partial county coverage: the leftover tracts take the residual, not the full total.
    for state, counties in county_totals.items():
        state_fips = STATE_FIPS[state]
        if state_fips not in totals or state_fips in native_states:
            continue
        already = sum(counties.values())
        residual = totals[state_fips] - already
        if residual < 0:
            raise ValueError(
                f"{state}: observed county totals sum to {already:,.0f}, which exceeds "
                f"the published state total {totals[state_fips]:,.0f}. Reconciling to a "
                "negative residual would put negative vehicles in the state's remaining "
                "tracts; the two sources disagree and that must be resolved, not clamped."
            )
        totals[state_fips] = residual
        vintages[state_fips] = (
            f"{vintages[state_fips]} residual after {len(counties)} observed counties"
        )
    return grains, group_of, totals, vintages


@dataclass(frozen=True)
class ConstraintAccounting:
    """Proof that the published national total is exactly what the constraints imply.

    The identity is::

        national_published == constraint_sum + unconstrained_sum

    **There is no substitution term, and there must never be one again.** Observed tract
    values are constraints, resolved by precedence *before* reconciliation, so they sit
    inside the constraint system rather than being applied on top of it. A published
    surface that is reconciled to one set of totals and then altered so it no longer sums
    to them breaks the exact-reconciliation contract; that is what the former +611.03
    Washington term was.

    ``unconstrained_sum`` is the raw model output of tracts no constraint binds - a
    jurisdiction with no published total - reported rather than absorbed because it is
    the share of the national figure resting on **no observed total at all**.

    This exists because a two-vehicle national discrepancy once went unexplained, and
    "floating-point noise" is not a defensible answer when the reconciliation residual is
    2.3e-10. It also catches the failure it was written after: a state with **partial**
    county coverage whose leftover tracts were reconciled to the *full* state total that
    its observed counties had already claimed (impact I-15).
    """

    national_published: float
    constraint_sum: float
    unconstrained_sum: float
    per_group: dict[str, float]
    per_jurisdiction: dict[str, float]

    @property
    def imbalance(self) -> float:
        return (self.national_published
                - self.constraint_sum
                - self.unconstrained_sum)

    def assert_balanced(self, tolerance: float = 1e-6) -> None:
        if abs(self.imbalance) > tolerance:
            raise ValueError(
                f"national accounting does not balance: published "
                f"{self.national_published:,.6f} != constraints "
                f"{self.constraint_sum:,.6f} + unconstrained "
                f"{self.unconstrained_sum:,.6f}. Unexplained: "
                f"{self.imbalance:,.6f}. A national total that does not equal the "
                "totals it reconciles to is wrong, however small the gap."
            )

    def to_dict(self) -> dict[str, object]:
        self.assert_balanced()
        return {
            "national_published": round(self.national_published, 6),
            "constraint_sum": round(self.constraint_sum, 6),
            "unconstrained_sum": round(self.unconstrained_sum, 6),
            "observed_substitution_delta": 0.0,
            "imbalance": round(self.imbalance, 9),
            "constraint_groups": len(self.per_group),
            "jurisdictions": len(self.per_jurisdiction),
            "balances": True,
        }

    def assert_every_jurisdiction_balances(
        self, published: Mapping[str, float], tolerance: float = 1e-6
    ) -> None:
        """Each jurisdiction's surface must equal its own operative constraint.

        A national identity can hold while individual states are wrong in offsetting
        directions, so the per-jurisdiction identity is checked too.
        """
        offenders = {
            fips: (published[fips], expected)
            for fips, expected in self.per_jurisdiction.items()
            if abs(published.get(fips, 0.0) - expected) > tolerance
        }
        if offenders:
            worst = max(offenders.items(), key=lambda kv: abs(kv[1][0] - kv[1][1]))
            raise ValueError(
                f"{len(offenders)} jurisdiction(s) do not sum to their operative "
                f"constraint; worst is {worst[0]}: published {worst[1][0]:,.6f} against "
                f"constraint {worst[1][1]:,.6f}. A state surface that does not equal the "
                "total it reconciles to is wrong."
            )


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
        equity_population=row.population * float(
            row.features.get("income_share_under_35k", 0.0)),
        raw_estimate=float(raw[position]),
        estimate=float(values[position]),
        evidence_grain=grain,
        estimate_method=method,
        uncertainty_score=score.score,
        uncertainty_components=dict(score.components),
        confidence_tier=tier,
        constraint_name=group_of[position],
        constraint_vintage=vintages.get(group_of[position]),
        value_provenance=(
            PROVENANCE_OBSERVED_COUNT if row.geoid in observed_tracts
            else PROVENANCE_ZERO_BY_ABSENCE
            if group_of[position].endswith(":zero_by_absence")
            else PROVENANCE_MODELLED
        ),
    )
