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

from pipeline.model.observed import StateObservations, StateTotal
from pipeline.spatial.geography import SourceGeography

#: How far a native total may sit from the external total it claims to supersede. A
#: registry-grade enumeration of the same population should land close to a published
#: aggregate of it; a large gap means one of them is measuring something else, and the
#: native source has not earned precedence. Declared here rather than tuned: it is a
#: qualification threshold, not a fitted parameter.
NATIVE_SUPERSEDE_TOLERANCE = 0.10


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
        }


def native_source_qualifies(
    observations: StateObservations,
    state_fips: str,
    external: StateTotal | None,
    tolerance: float = NATIVE_SUPERSEDE_TOLERANCE,
) -> tuple[bool, str]:
    """May this native source supersede the external total? Four conditions, all checked.

    A source that fails any of them is still valuable evidence — it trains the model and
    it validates — but it does not become the jurisdiction's operative constraint.
    """
    if observations.source_geography is not SourceGeography.TRACT:
        return False, (
            f"the source reports at {observations.source_geography.value} grain, not "
            "natively at tract grain, so it cannot supersede a state total"
        )
    try:
        observations.ledger.assert_balanced()
    except ValueError:
        return False, (
            "the source's record ledger does not balance, so its total cannot be "
            "trusted as an enumeration"
        )
    stray = [c.geography_id for c in observations.counts
             if not c.geography_id.startswith(state_fips)]
    if stray:
        return False, (
            f"{len(stray)} observed tract(s) lie outside the jurisdiction, so the "
            "source does not enumerate this jurisdiction cleanly"
        )
    if external is None:
        return False, (
            "no external total exists to corroborate the native total against, so "
            "completeness cannot be demonstrated and precedence is not granted"
        )
    if external.bev_count <= 0:
        return False, "the external total is not positive, so no comparison is possible"
    gap = abs(observations.total_bev - external.bev_count) / external.bev_count
    if gap > tolerance:
        return False, (
            f"the native total {observations.total_bev:,} differs from the external "
            f"total {external.bev_count:,} by {gap:.2%}, beyond the "
            f"{tolerance:.0%} tolerance. A gap that size means one of them is measuring "
            "a different population; the native source has not demonstrated completeness"
        )
    return True, (
        f"native tract registry: {len(observations.counts):,} tracts enumerated at "
        f"tract grain with a balanced record ledger, total {observations.total_bev:,} "
        f"within {gap:.2%} of the external {external.vintage} total "
        f"{external.bev_count:,}. Finer and directly observed, so it supersedes the "
        "coarser external total (CLAUDE.md §7.3 precedence, §7.4.1 evidence hierarchy)"
    )


def resolve(
    state_fips: str,
    observations: StateObservations | None,
    external: StateTotal | None,
    county_totals: Mapping[str, float] | None,
    county_coverage_complete: bool = False,
    tolerance: float = NATIVE_SUPERSEDE_TOLERANCE,
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

    if observations is not None:
        qualifies, reason = native_source_qualifies(
            observations, state_fips, external, tolerance)
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
            return OperativeConstraint(state_fips, chosen, reason, tuple(candidates))

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
