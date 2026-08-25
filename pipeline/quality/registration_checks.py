"""Domain rule G9: state registration vintage and plausibility validation.

G9 was rewritten after Phase 0 disproved its original wording. The original asserted
that the delivered file mixes reporting vintages across states and that Oregon reports
6,436; the file actually records Oregon at 64,361 and resolves to a single consistent
2023 AFDC vintage across all 51 jurisdictions. See ``docs/reports/PLAN_CHANGE_0.md``
and ``CLAUDE.md`` §19 A1.

The authoritative rule:

    Each ingested state-registration dataset must resolve to a documented vintage,
    jurisdiction coverage must be complete for the claimed geography, counts must be
    non-negative, and jurisdiction totals must reconcile to the published total where
    one exists. Per-capita and year-over-year anomaly screening must be run as a
    diagnostic quality check, but an anomalous state is **flagged for review rather
    than automatically marked low-confidence**. A low-confidence designation requires
    corroborating evidence of a vintage, coverage, definition, or source-quality
    problem.

The last sentence is the load-bearing one. A state's genuine EV adoption rate can
differ sharply from its neighbours for real reasons — income, incentives, urbanisation,
housing structure, climate, electricity prices, commute patterns, local market
maturity. An outlier is therefore a **diagnostic requiring investigation**, never proof
of a defective source. :func:`assign_confidence` refuses to lower confidence on
statistical unusualness alone, and that refusal is the point.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

# The 50 states plus the District of Columbia: the geography AFDC claims to cover.
EXPECTED_JURISDICTION_COUNT = 51
PUBLISHED_TOTAL_LABELS: frozenset[str] = frozenset({"United States", "Total"})

# Screening thresholds. These select rows for HUMAN REVIEW; they never by themselves
# change a confidence label.
PER_CAPITA_Z_THRESHOLD = 3.0
# Below this, the rates are identical to floating-point precision and there is no
# meaningful distribution to score against.
DEVIATION_TOLERANCE = 1e-12
YEAR_OVER_YEAR_GROWTH_THRESHOLD = 3.0  # a tripling year on year is worth a look


class Confidence(StrEnum):
    """Confidence in a jurisdiction's registration count."""

    OK = "ok"
    LOW = "low_confidence"


class DefectKind(StrEnum):
    """Corroborating evidence classes that CAN justify a low-confidence label."""

    VINTAGE = "vintage"
    COVERAGE = "coverage"
    DEFINITION = "definition"
    SOURCE_QUALITY = "source_quality"


@dataclass(frozen=True)
class ReviewFlag:
    """A diagnostic. Surfaced for investigation; NOT a quality judgement."""

    jurisdiction: str
    screen: str
    detail: str
    value: float

    def to_dict(self) -> dict[str, Any]:
        return {"jurisdiction": self.jurisdiction, "screen": self.screen,
                "detail": self.detail, "value": round(self.value, 6),
                "is_diagnostic_only": True}


@dataclass(frozen=True)
class VintageCheck:
    """Result of validating one registration dataset."""

    vintage_resolved: bool
    vintage: str | None
    jurisdictions_present: int
    coverage_complete: bool
    missing_jurisdictions: tuple[str, ...]
    all_counts_non_negative: bool
    negative_jurisdictions: tuple[str, ...]
    published_total: int | None
    sum_of_jurisdictions: int
    total_reconciles: bool | None
    review_flags: tuple[ReviewFlag, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        """Structural validity. Review flags do NOT affect this."""
        return (
            self.vintage_resolved
            and self.coverage_complete
            and self.all_counts_non_negative
            and self.total_reconciles is not False
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "vintage_resolved": self.vintage_resolved,
            "vintage": self.vintage,
            "jurisdictions_present": self.jurisdictions_present,
            "coverage_complete": self.coverage_complete,
            "missing_jurisdictions": list(self.missing_jurisdictions),
            "all_counts_non_negative": self.all_counts_non_negative,
            "negative_jurisdictions": list(self.negative_jurisdictions),
            "published_total": self.published_total,
            "sum_of_jurisdictions": self.sum_of_jurisdictions,
            "total_reconciles": self.total_reconciles,
            "review_flags": [f.to_dict() for f in self.review_flags],
            "passed": self.passed,
        }


def screen_per_capita(counts: Mapping[str, int],
                      population: Mapping[str, int],
                      z_threshold: float = PER_CAPITA_Z_THRESHOLD) -> list[ReviewFlag]:
    """Property 5: run per-capita anomaly screening. Output is diagnostic only."""
    rates = {
        name: counts[name] / population[name]
        for name in counts
        if population.get(name)
    }
    if len(rates) < 3:
        return []
    values = list(rates.values())
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    deviation = variance ** 0.5
    # Compared against a tolerance, not against exact zero. Identical rates give a
    # deviation on the order of 1e-17 rather than 0.0, so an equality test would never
    # fire and every jurisdiction would then be scored against a near-zero denominator,
    # flagging the whole file as anomalous.
    if deviation < DEVIATION_TOLERANCE:
        return []
    flags = [
        ReviewFlag(name, "per_capita_z",
                   f"EV per capita {rate:.6f} is {abs(rate - mean) / deviation:.2f} "
                   f"standard deviations from the mean of {mean:.6f}",
                   (rate - mean) / deviation)
        for name, rate in sorted(rates.items())
        if abs(rate - mean) / deviation > z_threshold
    ]
    return flags


def screen_year_over_year(
    current: Mapping[str, int], previous: Mapping[str, int],
    growth_threshold: float = YEAR_OVER_YEAR_GROWTH_THRESHOLD,
) -> list[ReviewFlag]:
    """Property 5: run year-over-year anomaly screening. Diagnostic only."""
    flags: list[ReviewFlag] = []
    for name, value in sorted(current.items()):
        before = previous.get(name)
        if not before:
            continue
        growth = value / before
        if growth > growth_threshold or growth < 1.0 / growth_threshold:
            flags.append(
                ReviewFlag(name, "year_over_year",
                           f"count moved from {before:,} to {value:,} "
                           f"({growth:.2f}x) between vintages", growth)
            )
    return flags


def check_registrations(
    counts: Mapping[str, int],
    *,
    vintage: str | None,
    published_total: int | None = None,
    expected_jurisdictions: Sequence[str] | None = None,
    population: Mapping[str, int] | None = None,
    previous_vintage_counts: Mapping[str, int] | None = None,
) -> VintageCheck:
    """Run all seven G9 properties over one registration dataset.

    ``counts`` must already have the published total row removed (G8 handles that in
    the intermediate layer); passing one in is treated as a coverage defect.
    """
    stray_totals = tuple(sorted(set(counts) & PUBLISHED_TOTAL_LABELS))
    working = {k: v for k, v in counts.items() if k not in PUBLISHED_TOTAL_LABELS}

    missing: tuple[str, ...] = ()
    if expected_jurisdictions is not None:
        missing = tuple(sorted(set(expected_jurisdictions) - set(working)))
        coverage_complete = not missing and not stray_totals
    else:
        coverage_complete = (
            len(working) == EXPECTED_JURISDICTION_COUNT and not stray_totals
        )

    negatives = tuple(sorted(name for name, value in working.items() if value < 0))
    total = sum(working.values())
    reconciles = None if published_total is None else published_total == total

    flags: list[ReviewFlag] = []
    if population:
        flags.extend(screen_per_capita(working, population))
    if previous_vintage_counts:
        flags.extend(screen_year_over_year(working, previous_vintage_counts))

    return VintageCheck(
        vintage_resolved=bool(vintage),
        vintage=vintage,
        jurisdictions_present=len(working),
        coverage_complete=coverage_complete,
        missing_jurisdictions=missing + tuple(f"UNEXPECTED_TOTAL_ROW:{t}"
                                              for t in stray_totals),
        all_counts_non_negative=not negatives,
        negative_jurisdictions=negatives,
        published_total=published_total,
        sum_of_jurisdictions=total,
        total_reconciles=reconciles,
        review_flags=tuple(flags),
    )


def assign_confidence(
    jurisdiction: str,
    review_flags: Sequence[ReviewFlag] = (),
    corroborating_defects: Sequence[DefectKind] = (),
) -> Confidence:
    """Property 7: a low-confidence label requires corroborating evidence of a defect.

    Statistical or geographic unusualness alone is **never** sufficient. A state whose
    EV adoption genuinely differs from its neighbours is not a data-quality problem,
    and labelling it one would push a fabricated signal into the uncertainty model.
    """
    if corroborating_defects:
        return Confidence.LOW
    # review_flags are deliberately ignored here. They exist to route a jurisdiction
    # to a human, not to downgrade it.
    _ = (jurisdiction, review_flags)
    return Confidence.OK
