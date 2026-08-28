"""Measured ZIP-to-tract allocation error, using Washington as the paired holdout.

CLAUDE.md §7.5.1 point 5 requires allocation ambiguity to be **measured, not assumed**,
and point 6 requires the measurement to propagate into the continuous uncertainty score
(§7.4 component 5). Washington is the only state whose registration records carry a
postal ZIP Code **and** a 2020 census tract on the same observed vehicle row, so the
observed ZIP-to-tract EV distribution is directly measurable there and two candidate
allocation methods can be scored against it.

**Washington is not national ground truth.** It is direct paired evidence from one
state. Nothing here licenses calling a ZIP-derived tract value ``directly_observed``;
every such value stays ``zip_anchored`` / ``crosswalked`` (§7.4.1, amendment A2).

The decision rule that selected between the two methods was pre-registered at commit
``66f1bfb`` (``docs/evidence/L1-0_wa_decision_rule_preregistered.md``) before any result
was computed. This module re-derives that comparison as reproducible code rather than an
ad-hoc script, and adds the record accounting that the original run reported only as a
bare denominator: see :mod:`pipeline.validation.scope`.

**Terminology.** The 0.35 threshold is a **maximum acceptable TVD** — an acceptability
*ceiling*. Exceeding it is the failing direction. The earlier wording "acceptability
floor" inverted the sense of the number without changing the number or the test.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from pipeline.validation.scope import (
    ExclusionLedger,
    ExclusionRule,
    classify,
    classify_detailed,
    ledger_from,
    merge,
)

# Pre-registered constants. Fixed before any result was computed; see L1-0.
MIN_EVS_PER_ZIP = 10
MATERIAL_GAP = 0.05
MATERIAL_WIN_SHARE = 0.60
MAX_ACCEPTABLE_TVD = 0.35

#: Stratification bands for "how many observed tracts does this ZIP touch". The
#: allocation problem is trivial at one tract and hardest at many, so the uncertainty
#: model needs error *by complexity*, not one national average (§7.4 component 5).
COMPLEXITY_BANDS: tuple[tuple[str, int, int], ...] = (
    ("1", 1, 1),
    ("2-3", 2, 3),
    ("4-7", 4, 7),
    ("8+", 8, 1_000_000),
)


class AllocationValidationError(ValueError):
    """The paired comparison cannot be computed from the inputs given."""


@dataclass(frozen=True)
class PairedRecord:
    """One observed vehicle, carrying both geographies from the same source row."""

    zip_code: str
    tract_geoid: str


def normalise_digits(value: object, length: int) -> str | None:
    """Exactly ``length`` digits, or ``None``. Never pads, never guesses."""
    digits = "".join(c for c in str(value if value is not None else "") if c.isdigit())
    if length == 5:
        return digits[:5] if len(digits) >= 5 else None
    return digits if len(digits) == length else None


def record_level_rules(state_fips: str) -> tuple[ExclusionRule[Mapping[str, object]], ...]:
    """Dispositions applied to individual vehicle rows, in precedence order."""
    return (
        ExclusionRule(
            reason="unusable_zip_or_tract",
            description=(
                "the row carries no 5-digit ZIP Code or no 11-digit 2020 census tract, "
                "so it cannot enter a paired comparison at all"
            ),
            predicate=lambda r: (
                normalise_digits(r.get("zip_code"), 5) is None
                or normalise_digits(r.get("_2020_census_tract"), 11) is None
            ),
        ),
        ExclusionRule(
            reason="tract_outside_state",
            description=(
                "the geocoded tract lies outside the state whose crosswalk is under "
                "test; the vehicle is registered in-state but garaged or geocoded "
                "elsewhere, and the comparison is a within-state one"
            ),
            predicate=lambda r: not str(
                normalise_digits(r.get("_2020_census_tract"), 11) or ""
            ).startswith(state_fips),
        ),
    )


def paired_counts(
    records: Iterable[Mapping[str, object]], state_fips: str = "53"
) -> tuple[dict[tuple[str, str], int], ExclusionLedger]:
    """Aggregate raw vehicle rows into observed (ZIP, tract) counts.

    Returns the counts and the record-level ledger. Nothing is dropped silently: the
    ledger accounts for every retrieved row by name.
    """
    kept, ledger = classify(records, record_level_rules(state_fips))
    counts: dict[tuple[str, str], int] = {}
    for row in kept:
        zip_code = normalise_digits(row.get("zip_code"), 5)
        tract = normalise_digits(row.get("_2020_census_tract"), 11)
        assert zip_code is not None and tract is not None  # guaranteed by the rules
        counts[(zip_code, tract)] = counts.get((zip_code, tract), 0) + 1
    return counts, ledger


def zip_level_rules(
    zip_evs: Mapping[str, int],
    methods: Mapping[str, Mapping[str, Mapping[str, float]]],
    min_evs: int = MIN_EVS_PER_ZIP,
) -> tuple[ExclusionRule[str], ...]:
    """Dispositions applied to whole ZIPs, in documented precedence order.

    Precedence matters and is fixed here: a ZIP too small to carry signal is excluded
    for *that* reason even if a crosswalk would also have failed on it, so the counts
    stay mutually exclusive and the table sums.

    A ZIP whose weights sum to zero — HUD's zero-residential ZIPs, of which 99546 is
    the documented example — is reported as unallocatable by that method. It is
    **never renormalised**: manufacturing a distribution where the source reports no
    residential addresses would invent evidence (D8).
    """
    def _sums_to_zero(method: str) -> object:
        def predicate(zip_code: str) -> bool:
            weights = methods[method].get(zip_code)
            return weights is not None and sum(weights.values()) <= 0.0
        return predicate

    def _missing(method: str) -> object:
        def predicate(zip_code: str) -> bool:
            return not methods[method].get(zip_code)
        return predicate

    rules: list[ExclusionRule[str]] = [
        ExclusionRule(
            reason="zip_below_minimum_ev_count",
            description=(
                f"fewer than {min_evs} observed EVs, so the observed share vector is "
                "noise rather than evidence; pre-registered in L1-0 before any result"
            ),
            predicate=lambda z: zip_evs[z] < min_evs,
        )
    ]
    for method in methods:
        rules.append(
            ExclusionRule(
                reason=f"zip_no_mapping_{method}",
                description=(
                    f"method {method!r} returns no tract mapping for this ZIP, so it "
                    "cannot be scored; reported as unallocatable, not rescued"
                ),
                predicate=_missing(method),  # type: ignore[arg-type]
            )
        )
        rules.append(
            ExclusionRule(
                reason=f"zip_zero_weight_{method}",
                description=(
                    f"method {method!r} returns weights summing to zero for this ZIP "
                    "(no residential addresses). Never renormalised"
                ),
                predicate=_sums_to_zero(method),  # type: ignore[arg-type]
            )
        )
    return tuple(rules)


def total_variation_distance(
    observed: Mapping[str, float], estimated: Mapping[str, float]
) -> float:
    """``0.5 * sum_t |o(t) - e(t)|`` over the union of tracts.

    Reads directly as the fraction of EV mass assigned to the wrong tract. Both inputs
    are share vectors; neither is renormalised here.
    """
    tracts = set(observed) | set(estimated)
    return 0.5 * sum(abs(observed.get(t, 0.0) - estimated.get(t, 0.0)) for t in tracts)


def mean_absolute_error(
    observed: Mapping[str, float], estimated: Mapping[str, float]
) -> float:
    tracts = set(observed) | set(estimated)
    if not tracts:  # pragma: no cover - a ZIP with no tracts cannot reach here
        return 0.0
    return sum(
        abs(observed.get(t, 0.0) - estimated.get(t, 0.0)) for t in tracts
    ) / len(tracts)


def top_tract_hit(
    observed: Mapping[str, float], estimated: Mapping[str, float]
) -> bool:
    """Does the method put the plurality of EVs in the tract that actually holds it?

    Ties are resolved by tract id so the answer is deterministic rather than dependent
    on dictionary order.
    """
    if not observed or not estimated:  # pragma: no cover - excluded upstream
        return False
    best_observed = max(sorted(observed), key=lambda t: observed[t])
    best_estimated = max(sorted(estimated), key=lambda t: estimated[t])
    return best_observed == best_estimated


def band_for(tract_count: int) -> str:
    for label, low, high in COMPLEXITY_BANDS:
        if low <= tract_count <= high:
            return label
    raise AllocationValidationError(  # pragma: no cover - bands cover 1..1e6
        f"no complexity band covers {tract_count} tracts"
    )


@dataclass(frozen=True)
class ZipScore:
    """One ZIP's comparison, for every method under test."""

    zip_code: str
    observed_evs: int
    observed_tract_count: int
    band: str
    tvd: dict[str, float]
    mae: dict[str, float]
    top_tract: dict[str, bool]


@dataclass(frozen=True)
class MethodSummary:
    method: str
    weighted_mean_tvd: float
    unweighted_mean_tvd: float
    weighted_mean_mae: float
    top_tract_accuracy: float


@dataclass(frozen=True)
class AllocationErrorResult:
    """The complete measurement, with its denominator fully accounted for."""

    ledger: ExclusionLedger
    zip_ledger: ExclusionLedger
    zip_scores: tuple[ZipScore, ...]
    summaries: dict[str, MethodSummary]
    strata: dict[str, dict[str, float]]
    win_share: dict[str, float]
    included_evs: int
    state_fips: str
    method_names: tuple[str, ...] = field(default=())

    def to_dict(self) -> dict[str, object]:
        return {
            "state_fips": self.state_fips,
            "record_accounting": self.ledger.to_dict(),
            "zip_accounting": self.zip_ledger.to_dict(),
            "included_evs": self.included_evs,
            "included_zips": len(self.zip_scores),
            "methods": {
                name: {
                    "weighted_mean_tvd": round(s.weighted_mean_tvd, 6),
                    "unweighted_mean_tvd": round(s.unweighted_mean_tvd, 6),
                    "weighted_mean_mae": round(s.weighted_mean_mae, 6),
                    "top_tract_accuracy": round(s.top_tract_accuracy, 6),
                }
                for name, s in sorted(self.summaries.items())
            },
            "win_share": {k: round(v, 6) for k, v in sorted(self.win_share.items())},
            "stratified_by_observed_tracts_per_zip": {
                band: {k: round(v, 6) for k, v in sorted(values.items())}
                for band, values in sorted(self.strata.items())
            },
            "max_acceptable_tvd": MAX_ACCEPTABLE_TVD,
        }


def _weighted(values: Sequence[float], weights: Sequence[int]) -> float:
    total = sum(weights)
    if total <= 0:  # pragma: no cover - guarded by the minimum-EV rule
        return 0.0
    return sum(v * w for v, w in zip(values, weights, strict=True)) / total


def compare_methods(
    records: Iterable[Mapping[str, object]],
    methods: Mapping[str, Mapping[str, Mapping[str, float]]],
    state_fips: str = "53",
    min_evs: int = MIN_EVS_PER_ZIP,
) -> AllocationErrorResult:
    """Score every allocation method against the observed paired distribution.

    ``methods`` maps method name -> ZIP -> tract -> weight. Weights are used exactly as
    the method supplies them; this function never renormalises a method's output.
    """
    if not methods:
        raise AllocationValidationError("no allocation methods were supplied")

    counts, record_ledger = paired_counts(records, state_fips)
    zip_evs: dict[str, int] = {}
    observed: dict[str, dict[str, float]] = {}
    for (zip_code, tract), n in counts.items():
        zip_evs[zip_code] = zip_evs.get(zip_code, 0) + n
        observed.setdefault(zip_code, {})[tract] = float(n)

    kept_zips, excluded_zips, descriptions = classify_detailed(
        sorted(zip_evs), zip_level_rules(zip_evs, methods, min_evs)
    )
    # The ZIP-level stage decides about whole ZIPs, but the ledger has to be expressed
    # in vehicles to merge with the record-level stage. Both views are published: the
    # ZIP counts say how many ZIPs were dropped, the record counts say how much of the
    # denominator went with them.
    zip_ledger = ledger_from(kept_zips, excluded_zips, descriptions,
                             weight=lambda z: zip_evs[z])
    zip_count_ledger = ledger_from(kept_zips, excluded_zips, descriptions)
    included_evs = zip_ledger.included
    ledger = merge(record_ledger, zip_ledger)

    scores: list[ZipScore] = []
    for zip_code in kept_zips:
        total = float(zip_evs[zip_code])
        obs = {t: n / total for t, n in observed[zip_code].items()}
        tvd: dict[str, float] = {}
        mae: dict[str, float] = {}
        hit: dict[str, bool] = {}
        for name, mapping in methods.items():
            est = dict(mapping[zip_code])
            tvd[name] = total_variation_distance(obs, est)
            mae[name] = mean_absolute_error(obs, est)
            hit[name] = top_tract_hit(obs, est)
        scores.append(
            ZipScore(
                zip_code=zip_code,
                observed_evs=zip_evs[zip_code],
                observed_tract_count=len(obs),
                band=band_for(len(obs)),
                tvd=tvd, mae=mae, top_tract=hit,
            )
        )

    weights = [s.observed_evs for s in scores]
    summaries = {
        name: MethodSummary(
            method=name,
            weighted_mean_tvd=_weighted([s.tvd[name] for s in scores], weights),
            unweighted_mean_tvd=(
                sum(s.tvd[name] for s in scores) / len(scores) if scores else 0.0
            ),
            weighted_mean_mae=_weighted([s.mae[name] for s in scores], weights),
            top_tract_accuracy=(
                sum(1 for s in scores if s.top_tract[name]) / len(scores)
                if scores else 0.0
            ),
        )
        for name in methods
    }

    win_share = {
        name: (
            sum(
                1
                for s in scores
                if all(s.tvd[name] < s.tvd[other] for other in methods if other != name)
            ) / len(scores)
            if scores else 0.0
        )
        for name in methods
    }

    strata: dict[str, dict[str, float]] = {}
    for label, _, _ in COMPLEXITY_BANDS:
        band_scores = [s for s in scores if s.band == label]
        if not band_scores:
            continue
        band_weights = [s.observed_evs for s in band_scores]
        entry: dict[str, float] = {
            "zips": float(len(band_scores)),
            "evs": float(sum(band_weights)),
        }
        for name in methods:
            entry[f"weighted_tvd_{name}"] = _weighted(
                [s.tvd[name] for s in band_scores], band_weights
            )
        strata[label] = entry

    return AllocationErrorResult(
        ledger=ledger,
        zip_ledger=zip_count_ledger,
        zip_scores=tuple(scores),
        summaries=summaries,
        strata=strata,
        win_share=win_share,
        included_evs=included_evs,
        state_fips=state_fips,
        method_names=tuple(methods),
    )
