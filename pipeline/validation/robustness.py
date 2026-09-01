"""Cross-objective robustness: does a portfolio optimised for one thing hold up on others?

CLAUDE.md §10.3. Optimise a portfolio on **one** objective, then score it on objectives
that were **never in the loss function**.

**"The optimiser wins on its own objective" is not a result.** It is circular, and §10.3
forbids reporting it as a finding. What is informative is one of two things, and both are
publishable:

* **cross-objective robustness** - a demand-optimised portfolio also performs on equity;
* **an exposed tradeoff** - it does not.

A portfolio that is strong on one measure and weak on another is a **result**, not a
failure to hide. The ε-constraint frontier is the tradeoff surface; nothing here declares
a winner.

**This is not proof of siting correctness or real-world optimality.** It says how a
portfolio scores on measures the optimiser did not see.
Ground truth for optimal siting does not exist (D3), and no string in this module or its
outputs may suggest otherwise.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from pipeline.model.siting import Candidate, CandidateSet

#: The six outcomes §10.3 names. Every portfolio is scored on all six, including the one
#: it was optimised for - which is reported, and explicitly labelled circular.
OBJECTIVE_NAMES: tuple[str, ...] = (
    "population_served",
    "demand_covered",
    "equity_coverage",
    "accessibility_improvement",
    "estimated_utilisation",
    "cost_efficiency",
)

#: The four baselines §10.3 names, fixed before any result was seen.
BASELINE_NAMES: tuple[str, ...] = (
    "population_weighted",
    "demand_only",
    "existing_network_proximity",
    "random",
)


@dataclass(frozen=True)
class ObjectiveDefinition:
    """One outcome, defined in terms a reader can check rather than a name to trust."""

    name: str
    definition: str
    units: str

    def to_dict(self) -> dict[str, str]:
        return {"objective": self.name, "definition": self.definition,
                "units": self.units}


OBJECTIVES: tuple[ObjectiveDefinition, ...] = (
    ObjectiveDefinition(
        "population_served",
        "resident population of every cell covered by the portfolio's k-ring service "
        "areas, counted once per cell however many selected sites reach it",
        "people"),
    ObjectiveDefinition(
        "demand_covered",
        "modelled BEV demand in every covered cell, the Phase 3 reconciled surface",
        "battery-electric vehicles"),
    ObjectiveDefinition(
        "equity_coverage",
        "population in households with income below $35,000 a year in every covered "
        "cell, from the ACS five-year feature income_share_under_35k multiplied by "
        "tract population. ONE named current ACS-derived socioeconomic indicator, NOT a "
        "composite index and NOT a general measure of disadvantage",
        "people"),
    ObjectiveDefinition(
        "accessibility_improvement",
        "demand in covered cells that had NO existing public operational DC fast port "
        "before the portfolio was built; the part of coverage that changes access "
        "rather than reinforcing it",
        "battery-electric vehicles"),
    ObjectiveDefinition(
        "estimated_utilisation",
        "covered demand per selected site, a crude throughput proxy. NOT a queueing "
        "result: Erlang C and the discrete-event check are Extension tier E1 and are "
        "not in Core",
        "battery-electric vehicles per site"),
    ObjectiveDefinition(
        "cost_efficiency",
        "demand covered per unit of portfolio cost. Cost is uniform per site because no "
        "cost model exists (§7.11 is Optional tier), so this is currently demand per "
        "site and assumption A-4.4 applies",
        "battery-electric vehicles per cost unit"),
)


def _covered(selected: Sequence[str], candidates: CandidateSet) -> set[str]:
    covered: set[str] = set()
    for site in selected:
        covered.update(candidates.coverage[site])
    return covered


def score_portfolio(
    selected: Sequence[str], candidates: CandidateSet
) -> dict[str, float]:
    """Every one of the six objectives, for one portfolio."""
    by_index: Mapping[str, Candidate] = {
        c.h3_index: c for c in candidates.candidates}
    covered = _covered(selected, candidates)
    reached = [by_index[c] for c in covered if c in by_index]
    demand = sum(c.demand for c in reached)
    cost = sum(by_index[s].cost for s in selected if s in by_index)
    return {
        "population_served": sum(c.population for c in reached),
        "demand_covered": demand,
        "equity_coverage": sum(c.equity_population for c in reached),
        "accessibility_improvement": sum(
            c.demand for c in reached if c.existing_dcfc_ports <= 0),
        "estimated_utilisation": demand / len(selected) if selected else 0.0,
        "cost_efficiency": demand / cost if cost > 0 else 0.0,
    }


def baseline_portfolios(
    candidates: CandidateSet, budget: int, seed: int
) -> dict[str, tuple[str, ...]]:
    """The four §10.3 baselines, each a simple rule fixed before any result was seen."""
    pool = list(candidates.candidates)

    def top(key: Callable[[Candidate], float]) -> tuple[str, ...]:
        ordered = sorted(pool, key=lambda c: (-key(c), c.h3_index))
        return tuple(c.h3_index for c in ordered[:budget])

    generator = np.random.default_rng(seed)
    shuffled = generator.permutation(len(pool))
    return {
        "population_weighted": top(lambda c: c.population),
        "demand_only": top(lambda c: c.demand),
        # Nearest to what already exists. This is the baseline the project exists to
        # beat: siting where infrastructure already is, is how underserved areas stay
        # underserved (directive D2's rationale, applied as a comparison rather than as
        # a feature).
        "existing_network_proximity": top(lambda c: c.existing_dcfc_ports),
        "random": tuple(pool[i].h3_index for i in shuffled[:budget]),
    }


@dataclass(frozen=True)
class PortfolioScore:
    """One portfolio, scored on all six objectives."""

    name: str
    optimised_for: str
    sites: int
    scores: Mapping[str, float]

    def to_dict(self) -> dict[str, object]:
        return {
            "portfolio": self.name,
            "optimised_for": self.optimised_for,
            "sites": self.sites,
            "scores": {k: round(v, 4) for k, v in sorted(self.scores.items())},
        }


@dataclass(frozen=True)
class RobustnessResult:
    """One state at one budget: every portfolio against every objective."""

    label: str
    budget: int
    portfolios: tuple[PortfolioScore, ...]

    def best_on(self, objective: str) -> str:
        return max(self.portfolios, key=lambda p: p.scores[objective]).name

    def relative(self, name: str, objective: str) -> float:
        """A portfolio's score on an objective, as a share of the best score on it."""
        best = max(p.scores[objective] for p in self.portfolios)
        mine = next(p for p in self.portfolios if p.name == name).scores[objective]
        return mine / best if best > 0 else 1.0

    def tradeoffs(self, name: str, threshold: float = 0.95) -> list[str]:
        """Objectives where this portfolio falls below `threshold` of the best score.

        Reported, not suppressed. §10.3: an exposed tradeoff is a finding.
        """
        return [o for o in OBJECTIVE_NAMES if self.relative(name, o) < threshold]

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "budget_sites": self.budget,
            "objective_definitions": [o.to_dict() for o in OBJECTIVES],
            "portfolios": [p.to_dict() for p in self.portfolios],
            "best_portfolio_by_objective": {
                o: self.best_on(o) for o in OBJECTIVE_NAMES},
            "relative_to_best": {
                p.name: {o: round(self.relative(p.name, o), 6)
                         for o in OBJECTIVE_NAMES}
                for p in self.portfolios
            },
            "tradeoffs_where_below_95_percent_of_best": {
                p.name: self.tradeoffs(p.name) for p in self.portfolios},
            "interpretation": (
                "cross-objective robustness, NOT proof of siting correctness or "
                "real-world optimality. A portfolio scoring well on the objective it "
                "was optimised for is circular and is not a finding; what is "
                "informative is how it scores on the objectives it never saw."
            ),
        }


def evaluate(
    label: str,
    candidates: CandidateSet,
    budget: int,
    optimised: Mapping[str, Sequence[str]],
    seed: int,
) -> RobustnessResult:
    """Score optimised portfolios and all four baselines on all six objectives."""
    scores = [
        PortfolioScore(name=name, optimised_for=name, sites=len(selected),
                       scores=score_portfolio(selected, candidates))
        for name, selected in sorted(optimised.items())
    ]
    scores += [
        PortfolioScore(name=f"baseline_{name}", optimised_for="none (baseline rule)",
                       sites=len(selected),
                       scores=score_portfolio(selected, candidates))
        for name, selected in sorted(
            baseline_portfolios(candidates, budget, seed).items())
    ]
    return RobustnessResult(label=label, budget=budget, portfolios=tuple(scores))
