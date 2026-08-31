"""Siting: candidate filtering, the epsilon-constraint frontier, and the greedy solver.

CLAUDE.md §7.8 fixes the offline formulation exactly::

    maximize   sum_i demand_i * y_i
    subject to sum_j cost_j * x_j <= B
               sum_i equity_pop_i * y_i >= epsilon      # the epsilon-constraint
               y_i <= sum_{j in N(i)} x_j
               x_j, y_i in {0,1}

``x_j`` builds at candidate *j*; ``y_i`` marks demand cell *i* covered; ``N(i)`` is the set
of candidates that cover *i*. Epsilon is swept across a documented range and **the
objectives are then reversed** as a check, because weighted-sum scalarisation cannot
recover unsupported Pareto-efficient points on an integer program.

**Nothing here claims optimality.** The output is a ranked, budget-feasible portfolio
under a stated objective and stated constraints. No validation in this project establishes
that a selected cell is objectively the right place to build, and none is claimed. What a
solve does establish is narrower and worth stating precisely: given *this* demand surface,
*these* constraints and *this* budget, no other selection covers more of the stated
objective.

**No mandatory national substation-proximity filter (§7.9).** Phase 0 could not locate an
authoritative national substation dataset, so Core siting functions without one and an
otherwise viable cell is never excluded for lacking grid data. Transmission proximity, if
it ever ships, is a labelled contextual proximity proxy and never an interconnection
constraint (D6).

**Cost is expressed in sites, not dollars.** Charger economics is Optional tier (§7.11) and
no cost model exists, so every candidate costs one unit and the budget is a **site count**.
Inventing a dollar cost would be a fabricated input; saying "twenty sites" is what the data
supports. The consequence for the approximation guarantee is worked through in
:func:`greedy_select`, and it is not a convenient one to hand-wave.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

import h3

from pipeline.model.build_demand import EQUITY_INDICATOR
from pipeline.model.hexes import HexCell
from pipeline.spatial.road_proximity import RoadDistances


class SitingError(ValueError):
    """A siting problem cannot be built or solved as specified."""


class ExclusionReason(StrEnum):
    """Why a cell is not a candidate. Every exclusion is named and counted (D8)."""

    UNINHABITED = "uninhabited"
    #: Named for the network actually measured. "beyond_road_network" implied every
    #: road; what is measured is TIGER/Line PRIMARY and SECONDARY roads, with local
    #: streets deliberately excluded, so a cell counted here may well have streets.
    BEYOND_PRIMARY_SECONDARY_ROADS = "beyond_primary_secondary_road_network"
    ALREADY_SATURATED = "already_saturated"


@dataclass(frozen=True)
class Candidate:
    """One buildable cell, carrying the evidence behind its demand."""

    h3_index: str
    demand: float
    equity_population: float
    population: float
    uncertainty_score: float
    sub_state_anchored_share: float
    dominant_evidence_grain: str
    existing_dcfc_ports: float
    cost: float = 1.0

    def to_dict(self) -> dict[str, object]:
        return {
            "h3_index": self.h3_index,
            "demand_bev": round(self.demand, 4),
            "equity_population": round(self.equity_population, 2),
            "population": round(self.population, 1),
            "uncertainty_score": round(self.uncertainty_score, 6),
            "sub_state_anchored_share": round(self.sub_state_anchored_share, 6),
            "dominant_evidence_grain": self.dominant_evidence_grain,
            "existing_dcfc_ports": round(self.existing_dcfc_ports, 2),
            "cost_units": self.cost,
        }


@dataclass(frozen=True)
class CandidateSet:
    """The candidates, plus a full account of what was excluded and why."""

    candidates: tuple[Candidate, ...]
    excluded: Mapping[str, int]
    coverage: Mapping[str, tuple[str, ...]]
    coverage_k: int
    road_filter: Mapping[str, object] | None = None
    #: Cells admitted **without** the road filter having run, in degraded mode. Nonzero
    #: means the published candidate set does not satisfy the §7.8 road constraint, and
    #: the artifact says so rather than the number quietly standing in for a filtered one.
    admitted_without_road_filter: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "candidates": len(self.candidates),
            "excluded_by_reason": dict(sorted(self.excluded.items())),
            "coverage_k_ring": self.coverage_k,
            "mean_cells_covered": (
                round(sum(len(v) for v in self.coverage.values())
                      / max(len(self.coverage), 1), 3)),
            "no_mandatory_substation_filter": True,
            "road_network_filter": (
                dict(self.road_filter) if self.road_filter is not None
                else "NOT APPLIED — DEGRADED. These candidates do not satisfy the "
                     "CLAUDE.md §7.8 road-proximity constraint."),
            "cells_admitted_without_road_filter": self.admitted_without_road_filter,
            "equity_objective_indicator": EQUITY_INDICATOR,
        }


def coverage_sets(
    cells: Sequence[str], k: int = 1
) -> dict[str, tuple[str, ...]]:
    """Which demand cells each candidate covers: itself and its k-ring neighbours.

    A driver does not have to be in the same 36 km² cell as a charger for it to be
    useful, so coverage extends to adjacent cells. ``k`` is configuration, not a finding.
    """
    known = set(cells)
    return {
        cell: tuple(sorted(n for n in h3.grid_disk(cell, k) if n in known))
        for cell in cells
    }


def build_candidates(
    cells: Sequence[HexCell],
    saturation_ports_per_1k_demand: float,
    road_distances: RoadDistances | None = None,
    minimum_population: float = 1.0,
    coverage_k: int = 1,
    allow_missing_roads: bool = False,
) -> CandidateSet:
    """Filter cells to buildable candidates. **No substation filter (§7.9).**

    Three filters apply, and every one is named and counted in the output:

    * **beyond the primary/secondary road network** — no TIGER/Line primary (MTFCC
      ``S1100``) or secondary (``S1200``) road within the pre-registered distance of the
      cell centroid, measured to the nearest **point on** a road rather than to the
      nearest vertex. This is the filter CLAUDE.md §7.8 specifies. Its threshold, road
      classes and distance method were fixed in
      ``docs/evidence/P4-0_road_filter_preregistration.md`` before any candidate set was
      recomputed. It is **not** proximity to all roads: a cell served only by local
      streets (``S1400``) is excluded, and the name says so.
    * **uninhabited** — no resident population. This is retained **on its own merits**: a
      cell with nobody in it is not a siting candidate. It was previously described as
      standing in for the road filter, which it never was, and that framing is withdrawn.
    * **already saturated** — existing public operational DC fast ports per 1,000 BEV of
      demand above the configured threshold. This is the only place supply enters siting,
      and it is not a demand feature: D2 governs the demand model, not the question of
      where capacity already exists.

    **Failure behaviour (D8).** Without road distances this raises. Passing every cell
    through would silently drop the filter, and falling back to the population filter is
    exactly the substitution this source exists to replace. A caller may set
    ``allow_missing_roads`` to proceed, in which case every cell is recorded under
    ``road_data_unavailable`` and the degradation appears in the published artifact.
    Degradation is never the default and never silent.
    """
    if road_distances is None and not allow_missing_roads:
        raise SitingError(
            "candidate construction needs road distances. CLAUDE.md §7.8 requires "
            "candidates to be within a configured distance of the road network, and "
            "TIGER/Line primary and secondary roads are the Core source for it. To "
            "proceed without them, pass allow_missing_roads=True, which records every "
            "cell as road_data_unavailable rather than pretending the filter ran."
        )

    kept: list[Candidate] = []
    excluded: dict[str, int] = {}
    degraded = 0

    def drop(reason: ExclusionReason) -> None:
        excluded[reason.value] = excluded.get(reason.value, 0) + 1

    for cell in cells:
        if cell.population < minimum_population:
            drop(ExclusionReason.UNINHABITED)
            continue
        if road_distances is None:
            # Degraded: the filter did not run. The cell is admitted, and the count of
            # such cells is published so nobody mistakes this candidate set for a
            # road-filtered one.
            degraded += 1
        elif not road_distances.within(cell.h3_index):
            drop(ExclusionReason.BEYOND_PRIMARY_SECONDARY_ROADS)
            continue
        if cell.demand_bev > 0:
            ports_per_1k = cell.supply.dcfc_ports * 1000.0 / cell.demand_bev
            if ports_per_1k >= saturation_ports_per_1k_demand:
                drop(ExclusionReason.ALREADY_SATURATED)
                continue
        kept.append(Candidate(
            h3_index=cell.h3_index,
            demand=cell.demand_bev,
            equity_population=cell.equity_population,
            population=cell.population,
            uncertainty_score=cell.uncertainty_score,
            sub_state_anchored_share=cell.sub_state_anchored_share,
            dominant_evidence_grain=cell.dominant_evidence_grain,
            existing_dcfc_ports=cell.supply.dcfc_ports,
        ))
    return CandidateSet(
        candidates=tuple(kept),
        excluded=excluded,
        coverage=coverage_sets([c.h3_index for c in kept], coverage_k),
        coverage_k=coverage_k,
        road_filter=(None if road_distances is None
                     else road_distances.to_dict([c.h3_index for c in cells])),
        admitted_without_road_filter=degraded,
    )


# --- the epsilon-constraint frontier -------------------------------------------------

class SolveStatus(StrEnum):
    OPTIMAL = "optimal"
    FEASIBLE_TIME_LIMIT = "feasible_time_limit"
    INFEASIBLE = "infeasible"
    NOT_SOLVED = "not_solved"


@dataclass(frozen=True)
class FrontierPoint:
    """One epsilon level solved to completion or to its time limit."""

    epsilon: float
    budget: int
    objective_sense: str
    demand_covered: float
    equity_covered: float
    selected: tuple[str, ...]
    status: str
    #: The CBC solver's own MIP gap between its best bound and its incumbent. This is
    #: the branch-and-bound sense of "optimality gap" and is a property of the SOLVE.
    #: It is not, and must never be conflated with, how far the browser greedy falls
    #: short of the optimum (:class:`GreedyShortfall`).
    optimality_gap: float | None
    solve_seconds: float

    def to_dict(self) -> dict[str, object]:
        return {
            "epsilon": round(self.epsilon, 4),
            "budget_sites": self.budget,
            "objective_sense": self.objective_sense,
            "demand_covered": round(self.demand_covered, 4),
            "equity_population_covered": round(self.equity_covered, 2),
            "sites_selected": len(self.selected),
            "cbc_status": self.status,
            "cbc_optimality_gap": (None if self.optimality_gap is None
                                   else round(self.optimality_gap, 6)),
            "solve_seconds": round(self.solve_seconds, 3),
        }


MAXIMISE_DEMAND = "maximise_demand_subject_to_equity"
MAXIMISE_EQUITY = "maximise_equity_subject_to_demand"


def solve_epsilon_constraint(
    candidates: CandidateSet,
    budget: int,
    epsilon: float,
    sense: str = MAXIMISE_DEMAND,
    time_limit_s: float = 60.0,
) -> FrontierPoint:
    """One integer program at one epsilon level, exactly as §7.8 specifies.

    ``sense`` selects the direction: maximise demand subject to an equity floor, or the
    **reverse** - maximise equity subject to a demand floor - which §7.8 requires as a
    check on the frontier.
    """
    import time

    import pulp

    if budget < 0:
        raise SitingError("budget must be non-negative")
    by_index = {c.h3_index: c for c in candidates.candidates}
    if not by_index:
        raise SitingError("no candidates to site among")

    if sense not in (MAXIMISE_DEMAND, MAXIMISE_EQUITY):
        raise SitingError(f"unknown objective sense {sense!r}")

    def primary(candidate: Candidate) -> float:
        return (candidate.demand if sense == MAXIMISE_DEMAND
                else candidate.equity_population)

    def secondary(candidate: Candidate) -> float:
        return (candidate.equity_population if sense == MAXIMISE_DEMAND
                else candidate.demand)

    problem = pulp.LpProblem("voltgap_siting", pulp.LpMaximize)
    build = {i: pulp.LpVariable(f"x_{i}", cat="Binary") for i in by_index}
    covered = {i: pulp.LpVariable(f"y_{i}", cat="Binary") for i in by_index}

    problem += pulp.lpSum(primary(by_index[i]) * covered[i] for i in by_index)
    problem += pulp.lpSum(by_index[i].cost * build[i] for i in by_index) <= budget
    problem += pulp.lpSum(
        secondary(by_index[i]) * covered[i] for i in by_index) >= epsilon
    for cell, coverers in candidates.coverage.items():
        # y_i <= sum_{j in N(i)} x_j : a cell counts as covered only if something that
        # covers it was actually built.
        problem += covered[cell] <= pulp.lpSum(build[j] for j in coverers)

    started = time.perf_counter()
    solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=time_limit_s)
    problem.solve(solver)
    elapsed = time.perf_counter() - started

    status = {
        pulp.LpStatusOptimal: SolveStatus.OPTIMAL,
        pulp.LpStatusInfeasible: SolveStatus.INFEASIBLE,
        pulp.LpStatusNotSolved: SolveStatus.NOT_SOLVED,
        pulp.LpStatusUndefined: SolveStatus.NOT_SOLVED,
    }.get(problem.status, SolveStatus.NOT_SOLVED)

    if status is SolveStatus.INFEASIBLE:
        return FrontierPoint(epsilon, budget, sense, 0.0, 0.0, (), status.value,
                             None, elapsed)

    selected = tuple(sorted(i for i in by_index if (build[i].value() or 0) > 0.5))
    hit = tuple(i for i in by_index if (covered[i].value() or 0) > 0.5)
    demand = sum(by_index[i].demand for i in hit)
    equity = sum(by_index[i].equity_population for i in hit)
    # CBC through PuLP does not expose a bound, so optimality is reported as a status
    # rather than a fabricated gap. A solve that hit the time limit says so.
    gap = 0.0 if status is SolveStatus.OPTIMAL else None
    return FrontierPoint(epsilon, budget, sense, demand, equity, selected,
                         status.value, gap, elapsed)


def epsilon_levels(
    candidates: CandidateSet, budget: int, count: int = 8,
    sense: str = MAXIMISE_DEMAND, time_limit_s: float = 60.0,
) -> list[float]:
    """A documented sweep across the **achievable** range, not the theoretical total.

    Sweeping fractions of the *total* equity population is what a first implementation
    does and it is wrong: a twenty-site portfolio cannot reach most of a state's equity
    population, so the upper levels are infeasible and the frontier is mostly empty
    points. The achievable maximum is found first, by solving the secondary objective on
    its own at this budget, and epsilon is swept from zero up to it.
    """
    if count < 2:
        raise SitingError("an epsilon sweep needs at least two levels")
    other = MAXIMISE_EQUITY if sense == MAXIMISE_DEMAND else MAXIMISE_DEMAND
    reachable = solve_epsilon_constraint(candidates, budget, 0.0, other, time_limit_s)
    ceiling = (reachable.equity_covered if sense == MAXIMISE_DEMAND
               else reachable.demand_covered)
    return [ceiling * i / count for i in range(count)]


def build_frontier(
    candidates: CandidateSet,
    budget: int,
    levels: Sequence[float] | None = None,
    sense: str = MAXIMISE_DEMAND,
    time_limit_s: float = 60.0,
) -> list[FrontierPoint]:
    """Sweep epsilon and return one solved point per level."""
    sweep = (list(levels) if levels is not None
             else epsilon_levels(candidates, budget, sense=sense,
                                 time_limit_s=time_limit_s))
    return [solve_epsilon_constraint(candidates, budget, e, sense, time_limit_s)
            for e in sweep]


# --- the interactive greedy solver ---------------------------------------------------

@dataclass(frozen=True)
class GreedyResult:
    """What the browser-side algorithm would return, computed here for comparison."""

    selected: tuple[str, ...]
    demand_covered: float
    equity_covered: float
    weights: Mapping[str, float]

    def to_dict(self) -> dict[str, object]:
        return {
            "sites_selected": len(self.selected),
            "demand_covered": round(self.demand_covered, 4),
            "equity_population_covered": round(self.equity_covered, 2),
            "weights": dict(sorted(self.weights.items())),
            "approximation_bound_claimed": None,
        }


DEFAULT_WEIGHTS: Mapping[str, float] = {"demand": 1.0, "equity": 0.0}


def greedy_select(
    candidates: CandidateSet,
    budget: int,
    weights: Mapping[str, float] = DEFAULT_WEIGHTS,
) -> GreedyResult:
    """Greedy marginal gain: repeatedly take the candidate adding the most new value.

    **This is the exact algorithm the browser runs**, stated so §7.8's requirement to
    define it precisely is met by code rather than prose:

    1. start with nothing selected and no cell covered;
    2. for each unselected candidate, compute the weighted value of the cells it would
       newly cover;
    3. take the candidate with the highest marginal gain per unit cost, breaking ties on
       the cell index so the result is deterministic;
    4. mark its coverage; repeat until the budget is exhausted or no candidate adds
       anything.

    **Problem class, and what follows for a guarantee.** With a single objective, uniform
    costs and no further constraint, this is cardinality-constrained maximum coverage,
    whose objective is monotone and submodular, and the Nemhauser-Wolsey-Fisher result
    would then apply. **That is not the problem the interactive surface poses.** The
    shipped surface exposes objective weights and constraint toggles, which makes it a
    weighted multi-objective selection under additional constraints, and the guarantee
    does not carry over to it. Phase 4 therefore claims **no approximation bound
    anywhere**, and reports the measured shortfall against CBC instead. See the Phase 4
    report for the full determination.
    """
    by_index = {c.h3_index: c for c in candidates.candidates}
    if not by_index:
        raise SitingError("no candidates to site among")
    demand_w = float(weights.get("demand", 0.0))
    equity_w = float(weights.get("equity", 0.0))

    def value(index: str) -> float:
        candidate = by_index[index]
        return demand_w * candidate.demand + equity_w * candidate.equity_population

    selected: list[str] = []
    covered: set[str] = set()
    spent = 0.0
    while len(selected) < len(by_index):
        best_index, best_gain = None, 0.0
        for index in sorted(by_index):
            if index in selected:
                continue
            candidate = by_index[index]
            if spent + candidate.cost > budget:
                continue
            gain = sum(value(c) for c in candidates.coverage[index]
                       if c not in covered)
            per_cost = gain / candidate.cost if candidate.cost > 0 else gain
            if per_cost > best_gain:
                best_index, best_gain = index, per_cost
        if best_index is None:
            break
        selected.append(best_index)
        covered.update(candidates.coverage[best_index])
        spent += by_index[best_index].cost

    return GreedyResult(
        selected=tuple(selected),
        demand_covered=sum(by_index[c].demand for c in covered),
        equity_covered=sum(by_index[c].equity_population for c in covered),
        weights=dict(weights),
    )


@dataclass(frozen=True)
class GreedyShortfall:
    """How far the browser greedy falls short of an exact CBC solve on the same problem.

    **This is not an "optimality gap".** A solver's optimality gap is the distance
    between its own bound and its own incumbent, and it is reported separately, per
    frontier point, as ``cbc_optimality_gap``. What this measures is a different
    quantity: the objective a heuristic achieved, against the objective the optimum
    achieved. Calling both "the gap" invites a reader to think the browser solver
    carries a solver-style guarantee, and it carries none (§7.8, amendment A11).
    """

    budget: int
    greedy_objective: float
    exact_objective: float
    exact_status: str
    label: str = ""

    @property
    def shortfall(self) -> float:
        """Fraction of the optimal objective the greedy solution did not achieve."""
        if self.exact_objective <= 0:
            return 0.0
        return (self.exact_objective - self.greedy_objective) / self.exact_objective

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "budget_sites": self.budget,
            "greedy_objective": round(self.greedy_objective, 4),
            "optimal_cbc_objective": round(self.exact_objective, 4),
            "cbc_status": self.exact_status,
            "greedy_objective_shortfall_vs_optimal_cbc": round(self.shortfall, 6),
            "measures": (
                "observed shortfall of the greedy objective against the optimal CBC "
                "objective on the same problem. NOT a solver optimality gap and NOT an "
                "approximation bound: no bound is claimed for the browser algorithm."
            ),
        }


def measure_greedy_shortfall(
    candidates: CandidateSet, budget: int, label: str = "",
    time_limit_s: float = 60.0,
) -> GreedyShortfall:
    """Compare greedy against the exact solve, with epsilon relaxed to zero.

    Relaxing epsilon isolates the comparison to the objective the greedy actually
    optimises; comparing against a constrained solve would measure the constraint rather
    than the algorithm.
    """
    exact = solve_epsilon_constraint(candidates, budget, 0.0, MAXIMISE_DEMAND,
                                     time_limit_s)
    approx = greedy_select(candidates, budget)
    return GreedyShortfall(
        budget=budget,
        greedy_objective=approx.demand_covered,
        exact_objective=exact.demand_covered,
        exact_status=exact.status,
        label=label,
    )
