"""Reconciling modelled estimates to observed totals.

CLAUDE.md §7.3 requires tract estimates to "reconcile exactly to reliable county totals
where they exist and to state totals everywhere else", and explicitly forbids
hard-coding the estimator: IPF, raking and hierarchical proportional reconciliation are
all candidates, to be chosen from the data structure and documented with the reason.

**The data structure decides it.** Counties nest inside states exactly, and tracts nest
inside counties exactly, because a tract GEOID *is* its state and county codes followed
by the tract code. Every constraint that Phase 3 actually applies therefore partitions
the areas it constrains, and on a partition the exact solution is a single proportional
scaling - no iteration, no convergence question, no residual. That is
:class:`ProportionalReconciler`, and it is the published path.

**ZIP constraints are not applied in Phase 3, and the reason is scope, not merit.** A
USPS ZIP Code does not nest inside anything; ZIP and tract partitions overlap, which is
what iterative proportional fitting is for, and
:class:`IterativeProportionalFitting` implements it. Binding tract estimates to ZIP
totals would require the ZIP→tract allocation, and the Washington measurement is
genuinely two-sided about that:

* the allocation misplaces EV mass - 17.94% EV-weighted total variation distance
  within ZIPs (``docs/evidence/P3-1_wa_allocation_scope_and_error.json``);
* but measured *statewide at tract level*, ZIP-anchored allocation lands EV mass
  substantially better than a state total alone does - TVD 0.1621 against 0.3049 under
  a common distribution method
  (:func:`pipeline.validation.washington.measure_transformation_ladder`).

The second figure weakens the case against ZIP constraints rather than supporting it, so
this module does not claim they would be harmful. Phase 3 does not apply them because
evaluating a new constraint set properly is its own piece of work, and CLAUDE.md §19
scope control sends a useful enhancement to ``docs/FUTURE_WORK.md`` rather than into the
current phase. The IPF implementation is here, tested, so that the work is a comparison
when it happens and not a rewrite.

**Reconciliation moves things, and how much it moved is an output.** The movement is
component `c3` of the continuous uncertainty score: an estimate that had to be dragged a
long way to satisfy its constraint is worse evidenced than one that already agreed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]

#: Exact means exact to floating point, not "close enough". The Phase 3 acceptance
#: criterion is that tract sums equal their constraints to floating-point tolerance.
RECONCILIATION_TOLERANCE = 1e-6


class ReconciliationError(ValueError):
    """A constraint set cannot be satisfied, or was not satisfied."""


@dataclass(frozen=True)
class Constraint:
    """One observed total that a group of areas must sum to."""

    name: str
    total: float
    members: tuple[int, ...]

    def __post_init__(self) -> None:
        if self.total < 0:
            raise ReconciliationError(
                f"constraint {self.name!r} has a negative total ({self.total}); a "
                "registration count cannot be negative"
            )
        if not self.members:
            raise ReconciliationError(
                f"constraint {self.name!r} binds no areas, so it can never be met"
            )


@dataclass(frozen=True)
class ReconciledEstimates:
    """The reconciled values, and an honest account of what reconciliation did."""

    values: FloatArray
    raw: FloatArray
    iterations: int
    max_residual: float
    method: str
    unconstrained: tuple[int, ...] = ()

    @property
    def movement(self) -> FloatArray:
        """Symmetric relative movement per area, in ``[0, 1]``. Uncertainty `c3`."""
        return np.abs(self.values - self.raw) / (self.values + self.raw + 1.0)

    def assert_satisfied(
        self, constraints: Sequence[Constraint],
        tolerance: float = RECONCILIATION_TOLERANCE,
    ) -> None:
        """Raise unless every constraint is met. The identity is checked, not assumed."""
        worst = 0.0
        offender = ""
        for constraint in constraints:
            achieved = float(self.values[list(constraint.members)].sum())
            residual = abs(achieved - constraint.total)
            if residual > worst:
                worst, offender = residual, constraint.name
        if worst > tolerance:
            raise ReconciliationError(
                f"constraint {offender!r} is off by {worst:.6g}, above the tolerance "
                f"{tolerance:g}. Reconciliation must hold exactly, or the published "
                "estimates do not sum to the totals they claim to reconcile to."
            )


class Reconciler(Protocol):
    """The common interface CLAUDE.md §7.3 requires the candidates to sit behind."""

    name: str

    def reconcile(self, estimates: FloatArray,
                  constraints: Sequence[Constraint]) -> ReconciledEstimates: ...


def _check_partition(estimates: FloatArray,
                     constraints: Sequence[Constraint]) -> tuple[int, ...]:
    """Verify the constraints partition the areas, returning the unconstrained ones."""
    seen: dict[int, str] = {}
    for constraint in constraints:
        for member in constraint.members:
            if member in seen:
                raise ReconciliationError(
                    f"area {member} is bound by both {seen[member]!r} and "
                    f"{constraint.name!r}. Overlapping constraints do not have an "
                    "exact proportional solution; use iterative proportional fitting."
                )
            if not 0 <= member < len(estimates):
                raise ReconciliationError(
                    f"constraint {constraint.name!r} refers to area {member}, which "
                    f"is outside the {len(estimates)} estimates supplied"
                )
            seen[member] = constraint.name
    return tuple(i for i in range(len(estimates)) if i not in seen)


@dataclass
class ProportionalReconciler:
    """Exact single-pass scaling within each constraint group. The published path.

    Valid **only** when the constraints partition the areas, which is checked rather
    than assumed. Where a group's raw estimates sum to zero the total is spread evenly
    across its members: the alternative, leaving it at zero, would silently discard the
    observed total, and the alternative of refusing would discard the group.
    """

    name: str = "proportional"

    def reconcile(self, estimates: FloatArray,
                  constraints: Sequence[Constraint]) -> ReconciledEstimates:
        unconstrained = _check_partition(estimates, constraints)
        values = np.array(estimates, dtype=np.float64, copy=True)
        for constraint in constraints:
            index = list(constraint.members)
            group = values[index]
            subtotal = float(group.sum())
            if subtotal > 0:
                values[index] = group * (constraint.total / subtotal)
            else:
                values[index] = constraint.total / len(index)
        result = ReconciledEstimates(
            values=values, raw=np.asarray(estimates, dtype=np.float64),
            iterations=1, max_residual=0.0, method=self.name,
            unconstrained=unconstrained,
        )
        result.assert_satisfied(constraints)
        return ReconciledEstimates(
            values=values, raw=np.asarray(estimates, dtype=np.float64),
            iterations=1,
            max_residual=_worst_residual(values, constraints),
            method=self.name, unconstrained=unconstrained,
        )


def _worst_residual(values: FloatArray,
                    constraints: Sequence[Constraint]) -> float:
    return max(
        (abs(float(values[list(c.members)].sum()) - c.total) for c in constraints),
        default=0.0,
    )


@dataclass
class IterativeProportionalFitting:
    """Raking for constraint sets that overlap rather than partition.

    Implemented and tested so the choice of :class:`ProportionalReconciler` for the
    published surface rests on a comparison. It is what a ZIP-and-county constraint set
    would need, and Phase 3 declines to apply that set for the reason given in the
    module docstring, not because the machinery is missing.

    Convergence is not guaranteed for an arbitrary constraint set, so the iteration
    count and the worst remaining residual are returned rather than hidden, and
    ``assert_satisfied`` is the caller's to run.
    """

    max_iterations: int = 200
    tolerance: float = RECONCILIATION_TOLERANCE
    name: str = "ipf"

    def reconcile(self, estimates: FloatArray,
                  constraints: Sequence[Constraint]) -> ReconciledEstimates:
        values = np.array(estimates, dtype=np.float64, copy=True)
        # A zero start can never be scaled to a positive total, so a group that begins
        # at zero is seeded flat before iterating.
        for constraint in constraints:
            index = list(constraint.members)
            if float(values[index].sum()) <= 0 and constraint.total > 0:
                values[index] = constraint.total / len(index)
        iterations = 0
        residual = _worst_residual(values, constraints)
        while iterations < self.max_iterations and residual > self.tolerance:
            for constraint in constraints:
                index = list(constraint.members)
                subtotal = float(values[index].sum())
                if subtotal > 0:
                    values[index] = values[index] * (constraint.total / subtotal)
            iterations += 1
            residual = _worst_residual(values, constraints)
        constrained = {m for c in constraints for m in c.members}
        return ReconciledEstimates(
            values=values, raw=np.asarray(estimates, dtype=np.float64),
            iterations=iterations, max_residual=residual, method=self.name,
            unconstrained=tuple(i for i in range(len(values)) if i not in constrained),
        )


def candidate_reconcilers() -> list[Reconciler]:
    return [ProportionalReconciler(), IterativeProportionalFitting()]


def constraints_from_totals(
    group_of: Sequence[str], totals: Mapping[str, float]
) -> list[Constraint]:
    """Build partition constraints from a per-area group label and a total per group.

    An area whose group has no observed total is left unconstrained rather than being
    assigned one, and appears in :attr:`ReconciledEstimates.unconstrained`.
    """
    members: dict[str, list[int]] = {}
    for position, group in enumerate(group_of):
        if group in totals:
            members.setdefault(group, []).append(position)
    return [
        Constraint(name=group, total=float(totals[group]), members=tuple(index))
        for group, index in sorted(members.items())
    ]
