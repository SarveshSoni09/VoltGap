"""Demand model validation: leave-one-state-out at each state's native granularity.

This is **demand model validation** in the D3 sense - whether tract-level EV estimates
are accurate. It is not historical deployment alignment and it is not cross-objective
robustness, and no sentence here may blur the three.

**Every held-out state is scored at the geography it actually publishes.** A ZIP-grain
state is scored against its observed ZIP counts, a county-grain state against its
observed county counts, Washington against its observed tract counts. Crosswalk-generated
tract values are never used as observed tract labels: that would score the crosswalk
against itself. The rule was fixed in ``docs/evidence/P3-0_phase3_preregistration.md``
§3 before any state had been scored.

**Washington is excluded from the independent aggregate.** It selected the HUD crosswalk
over land-area weighting, so any Washington result here is tuning-influenced. It is still
run and still reported, in its own row, carrying the status
``non_independent_preprocessing_selection_state`` (pre-registration §2, rules W1-W4). The
cost is accepted explicitly: no tract-native state remains in the independent aggregate.

**Two reconciliation modes are reported, and the difference between them is the point.**

* ``unreconciled`` is the raw propensity surface. It has to guess the held-out state's
  overall EV penetration from demographics alone, which is not what the deployed system
  asks of it.
* ``state_total_reconciled`` scales the held-out state's predictions to the AFDC
  registration total for the vintage nearest that state's own DMV snapshot. This is what
  ships, and it is **not leakage**: AFDC publishes a state total for all 51 jurisdictions
  independently of any sub-state source, so the constraint is available at prediction
  time for a state with no sub-state data at all. No sub-state observation of the
  held-out state is used in either mode.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from pipeline.model.demand import (
    Estimator,
    FloatArray,
    ModelRow,
    candidate_estimators,
    fit,
    mae,
    observed,
    r_squared,
    wape,
)
from pipeline.model.observed import STATE_FIPS, StateTotal
from pipeline.model.panel import StatePanel
from pipeline.model.reconcile import Constraint, ProportionalReconciler

UNRECONCILED = "unreconciled"
STATE_TOTAL_RECONCILED = "state_total_reconciled"
RECONCILIATION_MODES: tuple[str, ...] = (UNRECONCILED, STATE_TOTAL_RECONCILED)

#: Pre-registration §5. Ties inside one percentage point of WAPE go to the simpler
#: model, so a marginal gain never buys a large increase in opacity.
TIE_BREAK_WAPE = 0.01

#: An AFDC annual vintage is read as a stock observation at 31 December of that year,
#: which is the convention used to pick the vintage nearest a DMV snapshot date.
VINTAGE_MONTH_DAY = (12, 31)

_SNAPSHOT_DATE = re.compile(r"\((\d{1,2})/(\d{1,2})/(\d{4})\)")


class ValidationError(ValueError):
    """Validation cannot be run as specified."""


def snapshot_date(label: str) -> dt.date | None:
    """The date inside a DMV snapshot label, or ``None`` if it carries none.

    Formats differ between states - ``1/1/2026`` in Maine, ``01/01/2026`` in Minnesota -
    so the date is parsed rather than string-compared.
    """
    found = _SNAPSHOT_DATE.search(label)
    if not found:
        return None
    month, day, year = (int(found.group(i)) for i in (1, 2, 3))
    try:
        return dt.date(year, month, day)
    except ValueError:  # pragma: no cover - defensive against a malformed label
        return None


def nearest_vintage(
    series: Sequence[StateTotal], observed_at: dt.date | None
) -> StateTotal:
    """The AFDC vintage closest in time to a state's own observation date.

    Reconciling a June 2024 snapshot to a 2025 total would attribute eighteen months of
    fleet growth to model error: North Carolina's gap against the 2025 vintage is
    -45.27%, and against the contemporaneous 2023 vintage it is -5.66%.
    """
    if not series:
        raise ValidationError("no state totals supplied to choose a vintage from")
    if observed_at is None:
        return max(series, key=lambda t: t.vintage)
    return min(
        series,
        key=lambda t: abs(
            (dt.date(int(t.vintage), *VINTAGE_MONTH_DAY) - observed_at).days
        ),
    )


@dataclass(frozen=True)
class StateScore:
    """One held-out state, one estimator, one reconciliation mode."""

    state: str
    estimator: str
    mode: str
    geography: str
    evidence_grain: str
    areas: int
    observed_total: float
    wape: float
    mae: float
    r_squared: float
    independent: bool
    constraint_vintage: str | None
    constraint_total: float | None

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "estimator": self.estimator,
            "reconciliation": self.mode,
            "native_geography": self.geography,
            "evidence_grain": self.evidence_grain,
            "areas_scored": self.areas,
            "observed_bev": int(self.observed_total),
            "wape": round(self.wape, 6),
            "mae": round(self.mae, 6),
            "r_squared": round(self.r_squared, 6),
            "independent": self.independent,
            "status": (None if self.independent
                       else "non_independent_preprocessing_selection_state"),
            "constraint_vintage": self.constraint_vintage,
            "constraint_bev": (None if self.constraint_total is None
                               else int(self.constraint_total)),
        }


def _reconcile_to_total(predicted: FloatArray, total: float) -> FloatArray:
    """Scale a held-out state's predictions to its published registration total."""
    constraint = Constraint("state", float(total), tuple(range(len(predicted))))
    result = ProportionalReconciler().reconcile(predicted, [constraint])
    result.assert_satisfied([constraint])
    return result.values


def score_state(
    estimator: Estimator,
    training: Sequence[ModelRow],
    panel: StatePanel,
    mode: str,
    state_total: StateTotal | None = None,
) -> StateScore:
    """Fit on the training states and score one held-out state at its own grain."""
    rows = list(panel.rows)
    if not rows:
        raise ValidationError(f"{panel.state}: nothing to score")
    model = fit(estimator, training)
    predicted = model.predict_counts(rows)
    actual = observed(rows)
    total: float | None = None
    vintage: str | None = None
    if mode == STATE_TOTAL_RECONCILED:
        if state_total is None:
            raise ValidationError(
                f"{panel.state}: {STATE_TOTAL_RECONCILED} needs a published state "
                "total; refusing to reconcile to the held-out state's own observed sum"
            )
        total, vintage = float(state_total.bev_count), state_total.vintage
        predicted = _reconcile_to_total(predicted, total)
    elif mode != UNRECONCILED:
        raise ValidationError(f"unknown reconciliation mode {mode!r}")
    return StateScore(
        state=panel.state,
        estimator=estimator.name,
        mode=mode,
        geography=panel.rows[0].geography,
        evidence_grain=panel.source_geography.value,
        areas=len(rows),
        observed_total=float(actual.sum()),
        wape=wape(actual, predicted),
        mae=mae(actual, predicted),
        r_squared=r_squared(actual, predicted),
        independent=panel.is_independent,
        constraint_vintage=vintage,
        constraint_total=total,
    )


@dataclass(frozen=True)
class LosoResult:
    """Every state, every estimator, every mode, plus the aggregates and the choice."""

    scores: tuple[StateScore, ...]
    aggregates: Mapping[str, Mapping[str, float]]
    selected_estimator: str
    selection_mode: str
    independent_states: tuple[str, ...]
    excluded_states: Mapping[str, str]

    def to_dict(self) -> dict[str, object]:
        return {
            "validation_term": "demand model validation",
            "protocol": "leave-one-state-out at each state's native observed granularity",
            "independent_states": list(self.independent_states),
            "excluded_from_independent_aggregate": dict(self.excluded_states),
            "selection_rule": (
                "lowest EV-weighted WAPE across the independent states in the "
                f"{self.selection_mode} mode; ties inside {TIE_BREAK_WAPE:.0%} of WAPE "
                "go to the simpler model. Pre-registered before any candidate was run."
            ),
            "selected_estimator": self.selected_estimator,
            "aggregate_weighted_wape": {
                mode: {name: round(value, 6) for name, value in sorted(by_name.items())}
                for mode, by_name in sorted(self.aggregates.items())
            },
            "per_state": [score.to_dict() for score in self.scores],
        }


def weighted_wape(scores: Sequence[StateScore]) -> float:
    """EV-weighted WAPE across states: total absolute error over total observed."""
    error = sum(s.wape * s.observed_total for s in scores)
    total = sum(s.observed_total for s in scores)
    if total <= 0:
        raise ValidationError("aggregate WAPE is undefined with no observed vehicles")
    return error / total


def select_estimator(
    aggregates: Mapping[str, float], estimators: Sequence[Estimator]
) -> str:
    """Apply the pre-registered selection rule, including its tie-break."""
    if not aggregates:
        raise ValidationError("no candidate results to select from")
    rank = {e.name: e.complexity_rank for e in estimators}
    best = min(aggregates.values())
    tied = [name for name, value in aggregates.items() if value <= best + TIE_BREAK_WAPE]
    return min(sorted(tied), key=lambda name: (rank.get(name, 99), aggregates[name]))


def run_loso(
    panels: Mapping[str, StatePanel],
    state_totals: Mapping[str, list[StateTotal]],
    estimators: Sequence[Estimator] | None = None,
    selection_mode: str = STATE_TOTAL_RECONCILED,
) -> LosoResult:
    """Leave-one-state-out across every independent state, for every candidate."""
    candidates = list(estimators) if estimators is not None else candidate_estimators()
    independent = tuple(sorted(s for s, p in panels.items() if p.is_independent))
    if len(independent) <= 3:
        raise ValidationError(
            f"only {len(independent)} genuinely usable independent state(s) remain "
            f"({', '.join(independent) or 'none'}). CLAUDE.md §10.1 and the Phase 3 "
            "pre-registration §4 require a formal plan change at three or fewer rather "
            "than continuing with a weakened definition of validation."
        )

    scores: list[StateScore] = []
    aggregates: dict[str, dict[str, float]] = {mode: {} for mode in RECONCILIATION_MODES}
    for estimator in candidates:
        by_mode: dict[str, list[StateScore]] = {m: [] for m in RECONCILIATION_MODES}
        for held, panel in sorted(panels.items()):
            training = [
                row for state, other in panels.items()
                if state != held and other.is_independent
                for row in other.rows
            ]
            series = state_totals.get(STATE_FIPS[held], [])
            chosen = (nearest_vintage(series, snapshot_date(panel.vintage_label))
                      if series else None)
            for mode in RECONCILIATION_MODES:
                # A fresh estimator per fit: a fitted object must never carry a
                # previous state's coefficients into the next fold.
                score = score_state(
                    _fresh(estimator), training, panel, mode,
                    chosen if mode == STATE_TOTAL_RECONCILED else None,
                )
                scores.append(score)
                if panel.is_independent:
                    by_mode[mode].append(score)
        for mode in RECONCILIATION_MODES:
            aggregates[mode][estimator.name] = weighted_wape(by_mode[mode])

    return LosoResult(
        scores=tuple(scores),
        aggregates=aggregates,
        selected_estimator=select_estimator(aggregates[selection_mode], candidates),
        selection_mode=selection_mode,
        independent_states=independent,
        excluded_states={
            state: "non_independent_preprocessing_selection_state"
            for state, panel in sorted(panels.items()) if not panel.is_independent
        },
    )


def _fresh(estimator: Estimator) -> Estimator:
    """A new, unfitted instance of the same candidate."""
    return type(estimator)()


def calibration_curve(
    scores: Sequence[float], errors: Sequence[float], bins: int = 5
) -> list[dict[str, float]]:
    """Is a higher uncertainty score actually associated with larger error?

    Returns one row per equal-count bin of the uncertainty score, with the mean score
    and the mean absolute error in that bin. A flat or non-monotonic curve is a
    **finding to publish**, not a signal to retune the weights: the Phase 3
    pre-registration §6 fixes the weights precisely so this check keeps its meaning.
    """
    if len(scores) != len(errors):
        raise ValidationError("uncertainty scores and errors must be the same length")
    if not scores:
        raise ValidationError("no rows to build a calibration curve from")
    order = [int(i) for i in
             np.argsort(np.asarray(scores, dtype=np.float64), kind="stable")]
    grouped = np.array_split(np.asarray(order, dtype=np.int64), min(bins, len(order)))
    curve: list[dict[str, float]] = []
    for position, index in enumerate(grouped):
        if index.size == 0:  # pragma: no cover - array_split fills left to right
            continue
        curve.append({
            "bin": float(position),
            "n": float(index.size),
            "mean_uncertainty": float(np.mean([scores[int(i)] for i in index])),
            "mean_absolute_error": float(np.mean([errors[int(i)] for i in index])),
        })
    return curve
