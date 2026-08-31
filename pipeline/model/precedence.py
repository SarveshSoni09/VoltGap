"""Which total is authoritative for a jurisdiction, and why.

CLAUDE.md §7.3 already states a precedence: "Tract estimates must reconcile exactly to
**reliable county totals where they exist** and to state totals everywhere else." Finer,
more reliable evidence supersedes a coarser external total. Tennessee already demonstrates
it in the shipped surface — its complete county observations displace its AFDC state
total, 53,029 against 55,400 — and §7.4.1 puts ``native_tract`` at the top of the same
hierarchy.

This module makes that rule **explicit, ordered and testable**, and extends it one rung to
the grain the hierarchy already ranks highest:

    native tract registry  >  county observations  >  external state total

**Why this matters beyond tidiness.** The previous implementation applied the native rung
*after* reconciliation, overwriting Washington's reconciled tract values with observed
ones. That left the published surface reconciled to a set of totals it then no longer
summed to: a free-floating +611.03 outside the constraint system, which the exact
reconciliation contract forbids. Resolving precedence **before** reconciling puts the
observed values inside the system, where they belong.

**A superseded total is provenance, not rubbish.** It is recorded on the jurisdiction so a
reader can see what was set aside and why, and it is never summed into a national figure.

**Superseding is earned, not assumed.** A partial or broken extract must not silently
become a jurisdiction's constraint, so :func:`native_source_qualifies` states four
conditions and every one is checked.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from pipeline.model.observed import (
    STATEWIDE_VEHICLE_REGISTRY,
    StateObservations,
    StateTotal,
)
from pipeline.spatial.geography import SourceGeography

#: Agreement with an external total is a **plausibility diagnostic**, never a proof of
#: completeness. A source could agree closely with an external aggregate while omitting a
#: whole region, and could disagree widely while being perfectly exhaustive over a
#: differently-defined population. It is reported for review; it does not gate anything.
EXTERNAL_AGREEMENT_REVIEW_THRESHOLD = 0.10


class ConstraintSource(StrEnum):
    """The kinds of total a jurisdiction can be reconciled to, finest first."""

    NATIVE_TRACT_REGISTRY = "native_tract_registry"
    COUNTY_OBSERVATION = "county_observation"
    STATE_REGISTRATION_TOTAL = "state_registration_total"


#: Precedence order. Index 0 wins where it qualifies.
PRECEDENCE: tuple[ConstraintSource, ...] = (
    ConstraintSource.NATIVE_TRACT_REGISTRY,
    ConstraintSource.COUNTY_OBSERVATION,
    ConstraintSource.STATE_REGISTRATION_TOTAL,
)


class PrecedenceError(ValueError):
    """A jurisdiction's constraint could not be resolved to exactly one authority."""


@dataclass(frozen=True)
class ConstraintCandidate:
    """One total that could serve as a jurisdiction's constraint."""

    source: ConstraintSource
    vintage: str
    total: float
    grain: str
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source.value,
            "vintage": self.vintage,
            "total": round(self.total, 6),
            "grain": self.grain,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class OperativeConstraint:
    """The single authoritative total for one jurisdiction, plus what it displaced."""

    state_fips: str
    chosen: ConstraintCandidate
    reason: str
    superseded: tuple[ConstraintCandidate, ...] = ()
    #: Whether an area this jurisdiction's source does not name may be constrained to
    #: zero. Only an exhaustively resolved jurisdiction-wide enumeration earns this.
    assessment: SourceAssessment | None = None

    @property
    def licenses_zero_completion(self) -> bool:
        return self.assessment is not None and self.assessment.licenses_zero_completion

    @property
    def total(self) -> float:
        return self.chosen.total

    def to_dict(self) -> dict[str, object]:
        return {
            "state_fips": self.state_fips,
            "chosen_constraint_source": self.chosen.source.value,
            "chosen_constraint_vintage": self.chosen.vintage,
            "chosen_constraint_total": round(self.chosen.total, 6),
            "constraint_precedence_reason": self.reason,
            "superseded_constraints": [c.to_dict() for c in self.superseded],
            "source_assessment": (None if self.assessment is None
                                  else self.assessment.to_dict()),
        }


@dataclass(frozen=True)
class SourceAssessment:
    """What a native source has and has not demonstrated about itself."""

    is_complete: bool
    completeness_reason: str
    licenses_zero_completion: bool
    zero_completion_reason: str
    unresolved_in_jurisdiction: int
    external_agreement: float | None
    external_agreement_within_review_threshold: bool | None

    def to_dict(self) -> dict[str, object]:
        return {
            "source_complete": self.is_complete,
            "completeness_reason": self.completeness_reason,
            "licenses_zero_completion": self.licenses_zero_completion,
            "zero_completion_reason": self.zero_completion_reason,
            "unresolved_in_jurisdiction_records": self.unresolved_in_jurisdiction,
            "external_agreement_diagnostic": (
                None if self.external_agreement is None
                else round(self.external_agreement, 6)),
            "external_agreement_within_review_threshold":
                self.external_agreement_within_review_threshold,
            "note": (
                "External agreement is a plausibility diagnostic for review. It does "
                "NOT establish completeness and gates nothing."
            ),
        }


def assess_native_source(
    observations: StateObservations,
    state_fips: str,
    external: StateTotal | None,
) -> SourceAssessment:
    """Separate **source completeness** from **external plausibility**.

    Completeness rests on the publisher's declared scope and on explicit record and
    geography accounting — what the source says it covers, and whether it actually placed
    what it covers. It does **not** rest on agreement with a third-party aggregate: a
    source can agree closely while omitting a region, or disagree widely while being
    exhaustive over a differently-defined population. Agreement is reported as a
    diagnostic and gates nothing.

    Two distinct privileges are assessed, because they need different evidence:

    * **completeness** lets the source supersede a coarser external total *for the areas
      it names*;
    * **zero-completion** additionally lets an area it does *not* name be constrained to
      zero, and that requires every in-jurisdiction record to have been placed. One
      unplaced record and the licence is refused, because that record might belong to any
      unnamed area.
    """
    agreement: float | None = None
    if external is not None and external.bev_count > 0:
        agreement = abs(
            observations.total_bev - external.bev_count) / external.bev_count

    failures: list[str] = []
    if observations.source_geography is not SourceGeography.TRACT:
        failures.append(
            f"reports at {observations.source_geography.value} grain, not natively at "
            "tract grain")
    if observations.publisher_scope != STATEWIDE_VEHICLE_REGISTRY:
        failures.append(
            f"publisher scope is {observations.publisher_scope!r}, not a declared "
            "jurisdiction-wide enumeration")
    try:
        observations.ledger.assert_balanced()
    except ValueError:
        failures.append("its record ledger does not balance")
    stray = [c.geography_id for c in observations.counts
             if not c.geography_id.startswith(state_fips)]
    if stray:
        failures.append(f"{len(stray)} observed tract(s) lie outside the jurisdiction")
    if observations.resolution is None:
        failures.append("it publishes no geography-resolution accounting")

    complete = not failures
    completeness_reason = (
        f"declared {STATEWIDE_VEHICLE_REGISTRY}, reporting natively at tract grain, "
        f"with a balanced record ledger and {len(observations.counts):,} tracts all "
        "inside the jurisdiction"
        if complete else "; ".join(failures)
    )

    unresolved = (observations.resolution.unresolved_in_jurisdiction
                  if observations.resolution is not None else -1)
    if not complete:
        licenses, why = False, (
            "the source has not demonstrated completeness, so an area it does not name "
            "cannot be read as zero")
    elif unresolved > 0:
        licenses, why = False, (
            f"{unresolved:,} in-jurisdiction record(s) were not placed in a valid tract. "
            "Any of them could belong to an unnamed area, so absence does not mean zero"
        )
    else:
        assert observations.resolution is not None
        licenses, why = True, (
            f"every one of the {observations.resolution.in_jurisdiction_records:,} "
            "in-jurisdiction records is placed in a valid Census tract of the "
            "jurisdiction, so the enumeration is exhaustive and an unnamed tract holds "
            "zero. This is a COMPLETED ZERO derived from an exhaustive registry, not a "
            "literal zero-valued source row"
        )

    return SourceAssessment(
        is_complete=complete,
        completeness_reason=completeness_reason,
        licenses_zero_completion=licenses,
        zero_completion_reason=why,
        unresolved_in_jurisdiction=unresolved,
        external_agreement=agreement,
        external_agreement_within_review_threshold=(
            None if agreement is None
            else agreement <= EXTERNAL_AGREEMENT_REVIEW_THRESHOLD),
    )


def native_source_qualifies(
    observations: StateObservations,
    state_fips: str,
    external: StateTotal | None,
) -> tuple[bool, str]:
    """Back-compatible wrapper: may this source supersede the external total?"""
    assessment = assess_native_source(observations, state_fips, external)
    if not assessment.is_complete:
        return False, assessment.completeness_reason
    return True, (
        f"native tract registry: {assessment.completeness_reason}. It supersedes the "
        "coarser external total (CLAUDE.md §7.3 precedence, §7.4.1 evidence hierarchy)"
    )


def resolve(
    state_fips: str,
    observations: StateObservations | None,
    external: StateTotal | None,
    county_totals: Mapping[str, float] | None,
    county_coverage_complete: bool = False,
) -> OperativeConstraint:
    """Pick exactly one authoritative constraint for a jurisdiction, in precedence order.

    ``county_coverage_complete`` decides whether county observations displace the state
    total outright or merely claim part of it: with partial coverage the state total
    stays operative and the counties are a *decomposition* of it, which is what impact
    I-15 was about.
    """
    candidates: list[ConstraintCandidate] = []
    external_candidate: ConstraintCandidate | None = None
    if external is not None:
        external_candidate = ConstraintCandidate(
            ConstraintSource.STATE_REGISTRATION_TOTAL, external.vintage,
            float(external.bev_count), "state",
            f"AFDC published registration total for {external.jurisdiction}",
        )

    assessment: SourceAssessment | None = None
    if observations is not None:
        assessment = assess_native_source(observations, state_fips, external)
        qualifies, reason = native_source_qualifies(
            observations, state_fips, external)
        # Superseding requires the zero-completion licence too. A source that cannot
        # place every in-jurisdiction record cannot be the authority for the whole
        # jurisdiction: its named tracts would claim their share while its unnamed ones
        # still needed a total, and inventing a residual for them - or letting them take
        # the full external total the named tracts had already claimed - is exactly the
        # double count of impact I-15. Falling back entirely is conservative and invents
        # nothing; the observations remain training and validation evidence.
        if qualifies and not assessment.licenses_zero_completion:
            qualifies = False
            reason = assessment.zero_completion_reason
        if qualifies:
            chosen = ConstraintCandidate(
                ConstraintSource.NATIVE_TRACT_REGISTRY, observations.vintage_label,
                float(observations.total_bev), "tract",
                f"{len(observations.counts):,} natively observed tracts",
            )
            # Qualification requires an external total to corroborate against, so
            # there is always one here to record as superseded.
            assert external_candidate is not None
            candidates.append(external_candidate)
            if county_totals:
                candidates.append(ConstraintCandidate(
                    ConstraintSource.COUNTY_OBSERVATION, observations.vintage_label,
                    float(sum(county_totals.values())), "county",
                    f"{len(county_totals):,} observed counties"))
            return OperativeConstraint(state_fips, chosen, reason, tuple(candidates),
                                       assessment)

    if county_totals and county_coverage_complete:
        chosen = ConstraintCandidate(
            ConstraintSource.COUNTY_OBSERVATION,
            observations.vintage_label if observations else "unknown",
            float(sum(county_totals.values())), "county",
            f"{len(county_totals):,} observed counties covering the jurisdiction",
        )
        if external_candidate is not None:
            candidates.append(external_candidate)
        return OperativeConstraint(
            state_fips, chosen,
            f"complete county coverage: {len(county_totals):,} observed counties span "
            "the jurisdiction, so they supersede the coarser external state total "
            "(CLAUDE.md §7.3)",
            tuple(candidates),
        )

    if external_candidate is None:
        raise PrecedenceError(
            f"{state_fips}: no candidate constraint at all. A jurisdiction with no "
            "published total cannot be reconciled, and its tracts must be reported as "
            "unconstrained rather than silently assigned one."
        )
    reason = "external state registration total; no finer source qualified"
    if county_totals:
        reason = (
            f"external state registration total, decomposed across "
            f"{len(county_totals):,} observed counties with the remainder constrained to "
            "the residual. County coverage is incomplete, so the counties partition the "
            "state total rather than superseding it (impact I-15)"
        )
    return OperativeConstraint(state_fips, external_candidate, reason, ())


def resolve_all(
    observations: Mapping[str, StateObservations],
    external: Mapping[str, StateTotal],
    county_totals: Mapping[str, Mapping[str, float]],
    complete_coverage: Sequence[str] = (),
    state_fips_of: Mapping[str, str] | None = None,
) -> dict[str, OperativeConstraint]:
    """Resolve every jurisdiction. Exactly one operative constraint each."""
    from pipeline.model.observed import STATE_FIPS

    lookup = dict(state_fips_of or STATE_FIPS)
    by_fips = {lookup[code]: obs for code, obs in observations.items() if code in lookup}
    counties_by_fips = {lookup[code]: totals for code, totals in county_totals.items()
                        if code in lookup}
    complete = {lookup[code] for code in complete_coverage if code in lookup}

    out: dict[str, OperativeConstraint] = {}
    for state_fips in sorted(set(external) | set(by_fips)):
        out[state_fips] = resolve(
            state_fips,
            by_fips.get(state_fips),
            external.get(state_fips),
            counties_by_fips.get(state_fips),
            state_fips in complete,
        )
    return out
