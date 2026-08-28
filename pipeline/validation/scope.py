"""Record accounting: every retrieved record is either included or excluded by name.

A validation result is only interpretable if the denominator is. The Washington paired
allocation comparison retrieved **294,193** vehicle records and reported its result over
**292,581**; the 1,612-record difference was real and explainable but was never written
down, so a reader could not tell whether records had been dropped deliberately or lost.

This module makes that impossible to repeat. Records are classified through an ordered
list of :class:`ExclusionRule`, **first match wins**, so every record receives exactly
one disposition and the reasons are mutually exclusive by construction rather than by
inspection. :meth:`ExclusionLedger.assert_balanced` then enforces the identity

    retrieved == included + sum(excluded_by_reason)

and raises rather than letting a silent drop through. Directive D8 requires explicit
degradation; an unexplained denominator is the quiet version of the same failure.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


class ScopeError(ValueError):
    """A record ledger does not balance, or a rule set is malformed."""


@dataclass(frozen=True)
class ExclusionRule(Generic[T]):
    """One named, documented reason for excluding a record.

    ``reason`` is the machine-readable key that appears in the ledger and in published
    evidence. ``description`` is the human-readable justification and is required: a
    reason without a stated justification is exactly the thing this module exists to
    prevent.
    """

    reason: str
    description: str
    predicate: Callable[[T], bool]

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ScopeError("an exclusion rule must carry a non-empty reason key")
        if not self.description.strip():
            raise ScopeError(
                f"exclusion reason {self.reason!r} has no description; every exclusion "
                "must state why it is defensible"
            )


@dataclass(frozen=True)
class ExclusionLedger:
    """The full disposition of a retrieved population.

    ``excluded`` maps reason -> count and is ordered by the rule order that produced it,
    so the published table reads in the same precedence the classifier applied.
    """

    retrieved: int
    included: int
    excluded: dict[str, int]
    descriptions: dict[str, str]

    @property
    def excluded_total(self) -> int:
        return sum(self.excluded.values())

    def assert_balanced(self) -> None:
        """Raise unless ``retrieved == included + sum(excluded_by_reason)``."""
        if self.retrieved != self.included + self.excluded_total:
            raise ScopeError(
                f"record ledger does not balance: retrieved {self.retrieved} != "
                f"included {self.included} + excluded {self.excluded_total}. "
                f"Unaccounted records: "
                f"{self.retrieved - self.included - self.excluded_total}. "
                "Every retrieved record must carry exactly one disposition."
            )

    def to_dict(self) -> dict[str, object]:
        self.assert_balanced()
        return {
            "retrieved": self.retrieved,
            "included": self.included,
            "excluded_total": self.excluded_total,
            "excluded_by_reason": dict(self.excluded),
            "exclusion_descriptions": dict(self.descriptions),
            "balances": True,
        }


def _check_unique(rules: Sequence[ExclusionRule[T]]) -> None:
    seen: set[str] = set()
    for rule in rules:
        if rule.reason in seen:
            raise ScopeError(
                f"duplicate exclusion reason {rule.reason!r}: reasons must be distinct "
                "or the ledger cannot be read as mutually exclusive"
            )
        seen.add(rule.reason)


def classify_detailed(
    records: Iterable[T], rules: Sequence[ExclusionRule[T]]
) -> tuple[list[T], dict[str, list[T]], dict[str, str]]:
    """Split ``records`` into kept records and the records excluded under each reason.

    **First matching rule wins.** Rule order is therefore the documented exclusion
    precedence, and no record can be counted under two reasons. Returning the excluded
    records themselves - rather than only their counts - lets a caller re-express the
    same dispositions in a different unit (whole ZIPs, or the vehicles inside them)
    without re-running the predicates and risking a different answer.
    """
    _check_unique(rules)
    kept: list[T] = []
    excluded: dict[str, list[T]] = {rule.reason: [] for rule in rules}
    for record in records:
        for rule in rules:
            if rule.predicate(record):
                excluded[rule.reason].append(record)
                break
        else:
            kept.append(record)
    descriptions = {
        rule.reason: rule.description for rule in rules if excluded[rule.reason]
    }
    return kept, {r: items for r, items in excluded.items() if items}, descriptions


def ledger_from(
    kept: Sequence[T],
    excluded: Mapping[str, Sequence[T]],
    descriptions: Mapping[str, str],
    weight: Callable[[T], int] | None = None,
) -> ExclusionLedger:
    """Build a balanced ledger, counting either records or a per-record weight.

    ``weight`` exists because a disposition decided at one grain often has to be
    published at another: excluding a whole ZIP is a decision about ZIPs, but the
    denominator a reader cares about is vehicles.
    """
    size = (lambda items: sum(weight(i) for i in items)) if weight else len
    ledger = ExclusionLedger(
        retrieved=size(list(kept)) + sum(size(list(v)) for v in excluded.values()),
        included=size(list(kept)),
        excluded={reason: size(list(items)) for reason, items in excluded.items()},
        descriptions=dict(descriptions),
    )
    ledger.assert_balanced()
    return ledger


def classify(
    records: Iterable[T], rules: Sequence[ExclusionRule[T]]
) -> tuple[list[T], ExclusionLedger]:
    """:func:`classify_detailed` with the dispositions counted as records."""
    kept, excluded, descriptions = classify_detailed(records, rules)
    return kept, ledger_from(kept, excluded, descriptions)


def merge(first: ExclusionLedger, second: ExclusionLedger) -> ExclusionLedger:
    """Chain two classification stages into one ledger over the original population.

    The second stage must have been applied to exactly the records the first stage
    kept; otherwise the combined ledger would not describe the original retrieval.
    """
    if second.retrieved != first.included:
        raise ScopeError(
            f"cannot merge ledgers: stage two saw {second.retrieved} records but stage "
            f"one kept {first.included}. The stages do not describe one population."
        )
    overlap = set(first.excluded) & set(second.excluded)
    if overlap:
        raise ScopeError(f"exclusion reasons collide across stages: {sorted(overlap)}")
    merged = ExclusionLedger(
        retrieved=first.retrieved,
        included=second.included,
        excluded={**first.excluded, **second.excluded},
        descriptions={**first.descriptions, **second.descriptions},
    )
    merged.assert_balanced()
    return merged
