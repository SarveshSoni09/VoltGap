"""The continuous uncertainty score, and the presentation tiers derived from it.

Directive D7: uncertainty is a first-class output, and no point estimate ships without
it. CLAUDE.md §7.4 names five components; the Phase 3 pre-registration
(``docs/evidence/P3-0_phase3_preregistration.md`` §6) fixed their definitions, their
combination and their weights **before any model was fitted**, so that none of them
could be chosen after seeing which choice flattered the calibration curve.

    U_i = sum_k w_k * c_k(i),   w_k = 0.2 for all five

**The weights are equal by declaration, not by calibration.** That is stated wherever
the score is published, they live in ``pipeline/config/thresholds.yml``, and the score
ships with a weight-sensitivity control. Presenting hand-chosen weights as calibrated is
CLAUDE.md §18 anti-pattern 4; the defence is to say plainly that they are not.

**The weights are not tuned against validation results.** If the calibration curve - do
high-uncertainty tracts really carry larger error? - comes out flat or non-monotonic,
that is published as a negative finding. Tuning until it looks good would destroy the
only thing the check was for.

**Component 4 is measured, never chosen.** CLAUDE.md §7.4 forbids hard-coded numeric
penalties and requires the geographic transformation penalty to be derived from a
measurement. It is: Washington's vehicle records carry a ZIP, a county and a tract on
the same row, so all three transformations were measured against the observed tract
distribution by :func:`pipeline.validation.washington.measure_transformation_ladder`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from pipeline.model.demand import RANDOM_SEED, Estimator, FloatArray, ModelRow, fit

COMPONENT_NAMES: tuple[str, ...] = (
    "prediction_interval", "out_of_distribution", "reconciliation_movement",
    "allocation_error", "source_degradation",
)

#: Equal by declaration. Not calibrated. Exposed and sensitivity-tested (D7).
DEFAULT_WEIGHTS: Mapping[str, float] = dict.fromkeys(COMPONENT_NAMES, 0.2)

#: Pre-registration §8. Declared in advance and not moved to change the tier mix.
BC_THRESHOLD_QUANTILE = 0.75

DEFAULT_BOOTSTRAP_REPLICATES = 40


class UncertaintyError(ValueError):
    """The uncertainty score cannot be computed as specified."""


# --- c1: prediction interval --------------------------------------------------------

def bootstrap_prediction_spread(
    estimator_factory: Callable[[], Estimator],
    training: Sequence[ModelRow],
    targets: Sequence[ModelRow],
    replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
    seed: int = RANDOM_SEED,
) -> FloatArray:
    """Half-width of the 10th-90th percentile band of bootstrap predicted counts.

    Resampling the **training areas** rather than the residuals is the honest version
    here: the dominant uncertainty is which states and areas happened to be observed at
    all, not the noise around a fitted curve.
    """
    if replicates < 2:
        raise UncertaintyError("a bootstrap needs at least two replicates")
    rng = np.random.default_rng(seed)
    size = len(training)
    if size == 0:
        raise UncertaintyError("no training rows to resample")
    draws = np.empty((replicates, len(targets)), dtype=np.float64)
    for replicate in range(replicates):
        index = rng.integers(0, size, size=size)
        sample = [training[int(i)] for i in index]
        draws[replicate] = fit(estimator_factory(), sample).predict_counts(targets)
    band = np.percentile(draws, [10.0, 90.0], axis=0)
    half: FloatArray = (band[1] - band[0]) / 2.0
    return half


def relative_interval_width(half_width: FloatArray,
                            estimate: FloatArray) -> FloatArray:
    """``h / (h + max(estimate, 1))``: bounded in [0, 1) and scale-free.

    A raw half-width would make every large tract look uncertain simply for being
    large, so it is expressed relative to the estimate it qualifies.
    """
    denominator = half_width + np.maximum(estimate, 1.0)
    clipped: FloatArray = np.clip(half_width / denominator, 0.0, 1.0)
    return clipped


# --- c2: out of distribution --------------------------------------------------------

def mahalanobis_percentile(training: FloatArray, targets: FloatArray) -> FloatArray:
    """Each target's Mahalanobis distance from the training distribution, as a percentile.

    A tract unlike anything in the sub-state anchored training set gets high uncertainty
    **regardless of geography**, which is exactly what CLAUDE.md §7.4 asks for: the tier
    must never be geography-based.
    """
    if training.shape[1] != targets.shape[1]:
        raise UncertaintyError(
            f"training has {training.shape[1]} features, targets {targets.shape[1]}"
        )
    mean = training.mean(axis=0)
    covariance = np.cov(training, rowvar=False)
    covariance = np.atleast_2d(covariance)
    # A singular covariance happens when two features are collinear in the training
    # sample. Ridging the diagonal is preferable to failing: the alternative is no
    # out-of-distribution component at all, which would understate uncertainty.
    ridge = 1e-8 * np.trace(covariance) / max(covariance.shape[0], 1)
    inverse = np.linalg.pinv(covariance + ridge * np.eye(covariance.shape[0]))
    delta = targets - mean
    distance = np.einsum("ij,jk,ik->i", delta, inverse, delta)
    distance = np.sqrt(np.clip(distance, 0.0, None))
    order = np.argsort(np.argsort(distance, kind="stable"), kind="stable")
    return (order + 0.5) / len(distance)


# --- c4: measured geographic transformation error -----------------------------------

@dataclass(frozen=True)
class AllocationPenalty:
    """Measured transformation error, by evidence grain and by ZIP complexity.

    ``statewide_tvd`` comes from the Washington ladder and sets the LEVEL, which is
    comparable across grains. ``complexity_multiplier`` comes from the within-ZIP
    stratification of the same measurement and sets the SHAPE - how much harder a ZIP
    touching many tracts is than one touching a single tract. Both are measurements;
    neither is a chosen penalty.
    """

    statewide_tvd: Mapping[str, float]
    complexity_multiplier: Mapping[str, float]

    def for_row(self, evidence_grain: str, band: str | None = None) -> float:
        base = self.statewide_tvd.get(evidence_grain)
        if base is None:
            raise UncertaintyError(
                f"no measured transformation error for evidence grain "
                f"{evidence_grain!r}; a penalty must never be invented (CLAUDE.md §7.4)"
            )
        if band is None:
            return float(np.clip(base, 0.0, 1.0))
        return float(np.clip(base * self.complexity_multiplier.get(band, 1.0), 0.0, 1.0))


def complexity_multipliers(band_tvd: Mapping[str, float],
                           overall_tvd: float) -> dict[str, float]:
    """Band error relative to the overall mean, from the same measurement."""
    if overall_tvd <= 0:
        raise UncertaintyError("the overall measured TVD must be positive")
    return {band: value / overall_tvd for band, value in band_tvd.items()}


# --- c5: source degradation ---------------------------------------------------------

def source_degradation_share(statuses: Sequence[str]) -> float:
    """Share of the contributing sources whose contract status is not ``confirmed``."""
    if not statuses:
        return 0.0
    degraded = sum(1 for status in statuses if status != "confirmed")
    return degraded / len(statuses)


# --- combination --------------------------------------------------------------------

@dataclass(frozen=True)
class UncertaintyScore:
    """One area's continuous score and the components behind it."""

    geoid: str
    components: Mapping[str, float]
    weights: Mapping[str, float]

    @property
    def score(self) -> float:
        return float(sum(self.components[name] * self.weights[name]
                         for name in self.components))

    def to_dict(self) -> dict[str, object]:
        return {
            "geoid": self.geoid,
            "uncertainty_score": round(self.score, 6),
            "components": {k: round(v, 6) for k, v in sorted(self.components.items())},
            "weights_are_calibrated": False,
        }


def combine(
    geoids: Sequence[str],
    components: Mapping[str, Sequence[float]],
    weights: Mapping[str, float] = DEFAULT_WEIGHTS,
) -> list[UncertaintyScore]:
    """Weighted arithmetic mean of the five components, per area."""
    missing = sorted(set(COMPONENT_NAMES) - set(components))
    if missing:
        raise UncertaintyError(
            f"uncertainty components {missing} are absent. D7 makes uncertainty a "
            "first-class output; a score missing a component would overstate confidence."
        )
    total = sum(weights[name] for name in COMPONENT_NAMES)
    if not np.isclose(total, 1.0):
        raise UncertaintyError(f"component weights sum to {total}, not 1.0")
    for name in COMPONENT_NAMES:
        if len(components[name]) != len(geoids):
            raise UncertaintyError(
                f"component {name!r} has {len(components[name])} values for "
                f"{len(geoids)} areas"
            )
    return [
        UncertaintyScore(
            geoid=geoid,
            components={name: float(np.clip(components[name][position], 0.0, 1.0))
                        for name in COMPONENT_NAMES},
            weights=dict(weights),
        )
        for position, geoid in enumerate(geoids)
    ]


def weight_sensitivity(
    components: Mapping[str, Sequence[float]],
    weights: Mapping[str, float] = DEFAULT_WEIGHTS,
    step: float = 0.1,
) -> dict[str, float]:
    """How far the mean score moves when each component's weight is raised.

    D7 requires a weight-sensitivity control to ship with any composite. This is the
    numeric half of it: a component that barely moves the score is not doing work, and a
    component that dominates it should be visible as dominating.
    """
    geoids = [str(i) for i in range(len(next(iter(components.values()))))]
    base = float(np.mean([s.score for s in combine(geoids, components, weights)]))
    out: dict[str, float] = {}
    for name in COMPONENT_NAMES:
        shifted = dict(weights)
        shifted[name] = shifted[name] + step
        scale = sum(shifted.values())
        shifted = {k: v / scale for k, v in shifted.items()}
        moved = float(np.mean([s.score for s in combine(geoids, components, shifted)]))
        out[name] = moved - base
    return out


# --- tiers --------------------------------------------------------------------------

TIER_A = "A"
TIER_B = "B"
TIER_C = "C"

#: CLAUDE.md §11.5 and amendment A3. Tier A must NEVER be labelled "observed": most
#: Tier A areas are ZIP- or county-anchored, not directly observed.
TIER_LABELS: Mapping[str, str] = {
    TIER_A: "sub-state anchored",
    TIER_B: "modeled",
    TIER_C: "low confidence",
}


def bc_threshold(scores: Sequence[float], evidence_grains: Sequence[str],
                 quantile: float = BC_THRESHOLD_QUANTILE) -> float:
    """The B/C boundary: a quantile of the score among state-total-only areas.

    Fixed in advance by the pre-registration and not moved to change how many areas
    land in each tier. It is a reporting convention, not a finding.
    """
    modelled = [s for s, grain in zip(scores, evidence_grains, strict=True)
                if grain == "state_total_only"]
    if not modelled:
        raise UncertaintyError(
            "no state-total-only areas, so the B/C threshold has no population to be "
            "defined over"
        )
    return float(np.quantile(modelled, quantile))


def assign_tier(score: float, evidence_grain: str, threshold: float) -> str:
    """Tier from the continuous score and the evidence grain. Never from geography."""
    if evidence_grain != "state_total_only":
        return TIER_A
    return TIER_C if score >= threshold else TIER_B
