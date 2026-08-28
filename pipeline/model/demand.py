"""Tract-level EV propensity from demographics, and nothing else.

**D2 is the constraint that shapes this file.** Charger counts, port counts, charger
density, network presence and distance to the nearest charger are absent from the
primary feature set, enforced structurally by
:func:`pipeline.model.features.assert_primary_feature_set_is_clean`, which executes each
feature against a recording row and rejects any input outside the declared ACS
demographic set. CLAUDE.md §18 anti-pattern 5 is the reason it is enforced rather than
documented: supply features *do* improve fit, and that is exactly the problem.

**The model is fitted at the geography the data are observed at.** Eleven states publish
registrations by USPS ZIP Code, three by county, one by census tract. The obvious move -
allocate those counts down to tracts and fit on tract rows - would manufacture tract
labels from a crosswalk with a *measured* 17.94% EV-weighted total variation distance
(``docs/evidence/P3-1_wa_allocation_scope_and_error.json``) and then treat them as
observations. Instead ACS supplies features directly at tract, ZCTA and county grain, so
each state is fitted against the counts it actually publishes, at the geography it
actually publishes them at. No pseudo-label is created anywhere in the fitting path.

**The target is a rate, with households as exposure.** Modelling counts directly would
have the model spend its capacity rediscovering that big areas hold more vehicles.
Predicted count is ``rate * households``.

**Candidates are compared, not assumed.** CLAUDE.md §7.3 forbids hard-coding the
estimator. Five candidates are fitted, three models and two baselines, and the winner is
chosen by the rule pre-registered in ``docs/evidence/P3-0_phase3_preregistration.md`` §5
before any of them was run: lowest EV-weighted WAPE in leave-one-state-out validation,
ties inside one percentage point broken toward the simpler model. A candidate that
cannot beat both baselines is reported as failing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
import numpy.typing as npt

from pipeline.model.features import FEATURE_NAMES

FloatArray = npt.NDArray[np.float64]

#: Fixed everywhere a pseudo-random choice is made, so a rerun reproduces the run.
RANDOM_SEED = 20260828

#: Households with no exposure cannot carry a rate. An area with zero households is
#: kept in the output with a zero estimate rather than dropped, but it cannot train.
MIN_TRAINING_EXPOSURE = 1.0


class DemandModelError(ValueError):
    """The demand model cannot be fitted or applied as specified."""


@dataclass(frozen=True)
class ModelRow:
    """One area: identity, exposure, features, and (when training) an observed count."""

    state: str
    geography: str
    geoid: str
    households: float
    population: float
    features: Mapping[str, float]
    observed_bev: float | None = None

    def vector(self, names: Sequence[str] = FEATURE_NAMES) -> list[float]:
        return [float(self.features[name]) for name in names]


def design_matrix(rows: Sequence[ModelRow],
                  names: Sequence[str] = FEATURE_NAMES) -> FloatArray:
    if not rows:
        raise DemandModelError("no rows to build a design matrix from")
    return np.asarray([row.vector(names) for row in rows], dtype=np.float64)


def exposures(rows: Sequence[ModelRow],
              kind: str = "households") -> FloatArray:
    """The denominator an estimator's rate is expressed over."""
    if kind == EXPOSURE_POPULATION:
        return np.asarray([row.population for row in rows], dtype=np.float64)
    return np.asarray([row.households for row in rows], dtype=np.float64)


def observed(rows: Sequence[ModelRow]) -> FloatArray:
    missing = [r.geoid for r in rows if r.observed_bev is None]
    if missing:
        raise DemandModelError(
            f"{len(missing)} row(s) have no observed count and cannot be trained on "
            f"(first: {missing[0]})"
        )
    return np.asarray([float(r.observed_bev or 0.0) for r in rows], dtype=np.float64)


#: Which quantity an estimator's predicted rate is a rate *of*. The population-share
#: baseline is only a distinct baseline if it is applied to population: a per-person
#: rate converted to a per-household rate is algebraically the same constant as the
#: household baseline, and the two would report identical error for every state.
EXPOSURE_HOUSEHOLDS = "households"
EXPOSURE_POPULATION = "population"


class Estimator(Protocol):
    """A candidate propensity model. Fitted on rates, weighted by exposure."""

    name: str
    complexity_rank: int
    exposure_kind: str

    def fit(self, features: FloatArray, rate: FloatArray,
            exposure: FloatArray) -> None: ...  # pragma: no cover - Protocol declaration

    def predict_rate(self, features: FloatArray) -> FloatArray: ...  # pragma: no cover


@dataclass
class _Standardiser:
    """Zero-mean, unit-variance scaling fitted on the training rows only.

    Fitting the scaler on all rows including the held-out state would leak the held-out
    state's feature distribution into the fit. It is small leakage, and it is still
    leakage.
    """

    mean: FloatArray | None = None
    scale: FloatArray | None = None

    def fit(self, features: FloatArray) -> None:
        self.mean = features.mean(axis=0)
        scale = features.std(axis=0)
        # A constant column has zero variance; dividing by it would produce NaN and
        # silently poison every downstream coefficient.
        self.scale = np.where(scale > 0.0, scale, 1.0)

    def apply(self, features: FloatArray) -> FloatArray:
        if self.mean is None or self.scale is None:
            raise DemandModelError("standardiser used before it was fitted")
        return (features - self.mean) / self.scale


@dataclass
class RidgeLogRate:
    """Ridge regression on the log of the EV rate. The interpretable linear baseline."""

    alpha: float = 1.0
    name: str = "ridge_log_rate"
    exposure_kind: str = EXPOSURE_HOUSEHOLDS
    complexity_rank: int = 1
    _scaler: _Standardiser = field(default_factory=_Standardiser)
    _model: object = None

    def fit(self, features: FloatArray, rate: FloatArray,
            exposure: FloatArray) -> None:
        from sklearn.linear_model import Ridge

        self._scaler.fit(features)
        model = Ridge(alpha=self.alpha, random_state=None)
        # log1p rather than log: a ZIP with a genuine zero EV count is data, not an
        # error, and log(0) would either crash or force it to be dropped.
        model.fit(self._scaler.apply(features), np.log1p(rate), sample_weight=exposure)
        self._model = model

    def predict_rate(self, features: FloatArray) -> FloatArray:
        if self._model is None:
            raise DemandModelError(f"{self.name} used before it was fitted")
        predicted = self._model.predict(self._scaler.apply(features))  # type: ignore[attr-defined]
        return np.clip(np.expm1(np.asarray(predicted, dtype=np.float64)), 0.0, None)


@dataclass
class PoissonRate:
    """Poisson GLM with a log link, exposure carried as the sample weight.

    Fitting ``count / exposure`` with ``sample_weight = exposure`` is algebraically the
    same as a Poisson regression with ``log(exposure)`` as an offset, which is the
    natural specification for a count target.
    """

    alpha: float = 1e-6
    max_iter: int = 1000
    name: str = "poisson_glm"
    exposure_kind: str = EXPOSURE_HOUSEHOLDS
    complexity_rank: int = 2
    _scaler: _Standardiser = field(default_factory=_Standardiser)
    _model: object = None

    def fit(self, features: FloatArray, rate: FloatArray,
            exposure: FloatArray) -> None:
        from sklearn.linear_model import PoissonRegressor

        self._scaler.fit(features)
        model = PoissonRegressor(alpha=self.alpha, max_iter=self.max_iter)
        model.fit(self._scaler.apply(features), rate, sample_weight=exposure)
        self._model = model

    def predict_rate(self, features: FloatArray) -> FloatArray:
        if self._model is None:
            raise DemandModelError(f"{self.name} used before it was fitted")
        predicted = self._model.predict(self._scaler.apply(features))  # type: ignore[attr-defined]
        return np.clip(np.asarray(predicted, dtype=np.float64), 0.0, None)


@dataclass
class BoostedPoissonRate:
    """Gradient-boosted trees with a Poisson loss. Captures interaction without hand
    specification, at the cost of interpretability."""

    max_iter: int = 200
    max_depth: int | None = 4
    learning_rate: float = 0.06
    name: str = "boosted_poisson"
    exposure_kind: str = EXPOSURE_HOUSEHOLDS
    complexity_rank: int = 3
    _model: object = None

    def fit(self, features: FloatArray, rate: FloatArray,
            exposure: FloatArray) -> None:
        from sklearn.ensemble import HistGradientBoostingRegressor

        model = HistGradientBoostingRegressor(
            loss="poisson", max_iter=self.max_iter, max_depth=self.max_depth,
            learning_rate=self.learning_rate, random_state=RANDOM_SEED,
        )
        model.fit(features, rate, sample_weight=exposure)
        self._model = model

    def predict_rate(self, features: FloatArray) -> FloatArray:
        if self._model is None:
            raise DemandModelError(f"{self.name} used before it was fitted")
        predicted = self._model.predict(features)  # type: ignore[attr-defined]
        return np.clip(np.asarray(predicted, dtype=np.float64), 0.0, None)


@dataclass
class ConstantRateBaseline:
    """"EVs are spread like households." Not a model - a floor to clear.

    CLAUDE.md §18 anti-pattern 2 in miniature: a candidate that cannot beat this has
    learned nothing from demographics, however good its headline number looks.
    """

    name: str = "baseline_household_share"
    exposure_kind: str = EXPOSURE_HOUSEHOLDS
    complexity_rank: int = 0
    _rate: float = 0.0

    def fit(self, features: FloatArray, rate: FloatArray,
            exposure: FloatArray) -> None:
        total = float(exposure.sum())
        self._rate = float((rate * exposure).sum() / total) if total > 0 else 0.0

    def predict_rate(self, features: FloatArray) -> FloatArray:
        return np.full(features.shape[0], self._rate, dtype=np.float64)


@dataclass
class PopulationShareBaseline:
    """"EVs are spread like people." The second floor, on a different exposure.

    Its exposure is **population**, not households. Fitting a per-person rate and then
    converting it to a per-household rate would collapse to
    ``sum(counts) / sum(households)`` - exactly the household baseline - and the two
    would report identical error for every state, which is what happened before this
    was fixed.
    """

    name: str = "baseline_population_share"
    exposure_kind: str = EXPOSURE_POPULATION
    complexity_rank: int = 0
    _per_person: float = 0.0

    def fit(self, features: FloatArray, rate: FloatArray,
            exposure: FloatArray) -> None:
        """``rate`` here is per head of population and ``exposure`` is population."""
        people = float(exposure.sum())
        self._per_person = (float((rate * exposure).sum() / people)
                            if people > 0 else 0.0)

    def predict_rate(self, features: FloatArray) -> FloatArray:
        return np.full(features.shape[0], self._per_person, dtype=np.float64)


def candidate_estimators() -> list[Estimator]:
    """The pre-registered candidate set, simplest first."""
    return [
        ConstantRateBaseline(),
        PopulationShareBaseline(),
        RidgeLogRate(),
        PoissonRate(),
        BoostedPoissonRate(),
    ]


@dataclass
class FittedModel:
    """A fitted candidate and the training rows it saw."""

    estimator: Estimator
    feature_names: tuple[str, ...]
    training_rows: int
    training_states: tuple[str, ...]

    def predict_counts(self, rows: Sequence[ModelRow]) -> FloatArray:
        """Expected BEV counts: predicted rate times each area's own exposure."""
        rate = self.estimator.predict_rate(design_matrix(rows, self.feature_names))
        return rate * exposures(rows, self.estimator.exposure_kind)


def fit(estimator: Estimator, rows: Sequence[ModelRow],
        names: Sequence[str] = FEATURE_NAMES) -> FittedModel:
    """Fit one candidate on rows that carry observed counts."""
    usable = [r for r in rows if r.households >= MIN_TRAINING_EXPOSURE]
    if not usable:
        raise DemandModelError(
            "every training row has zero exposure; a rate model cannot be fitted"
        )
    features = design_matrix(usable, names)
    exposure = exposures(usable, estimator.exposure_kind)
    if float(exposure.sum()) <= 0.0:
        raise DemandModelError(
            f"{estimator.name}: total {estimator.exposure_kind} exposure is zero"
        )
    counts = observed(usable)
    # A single area with zero exposure would divide by zero; it cannot happen for
    # households (filtered above) but population can be zero in a group quarters area.
    rate = np.divide(counts, exposure, out=np.zeros_like(counts),
                     where=exposure > 0.0)
    estimator.fit(features, rate, exposure)
    return FittedModel(
        estimator=estimator,
        feature_names=tuple(names),
        training_rows=len(usable),
        training_states=tuple(sorted({r.state for r in usable})),
    )


# --- metrics ------------------------------------------------------------------------

def wape(observed_counts: FloatArray, predicted: FloatArray) -> float:
    """Weighted absolute percentage error: total error over total observed.

    Reported instead of MAPE because MAPE explodes on the small counts that dominate a
    ZIP- or county-level panel (CLAUDE.md §7.10 makes the same point for forecasting).
    """
    total = float(np.abs(observed_counts).sum())
    if total <= 0:
        raise DemandModelError("WAPE is undefined when the observed total is zero")
    return float(np.abs(predicted - observed_counts).sum() / total)


def mae(observed_counts: FloatArray, predicted: FloatArray) -> float:
    return float(np.abs(predicted - observed_counts).mean())


def r_squared(observed_counts: FloatArray, predicted: FloatArray) -> float:
    """Coefficient of determination against the observed mean."""
    residual = float(((observed_counts - predicted) ** 2).sum())
    total = float(((observed_counts - observed_counts.mean()) ** 2).sum())
    if total <= 0:
        raise DemandModelError("R^2 is undefined when every observed value is equal")
    return 1.0 - residual / total
