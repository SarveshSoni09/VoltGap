"""Smoke-forward: Phase 4's core operation against Phase 3's real output (Gate G-D).

CLAUDE.md §15.2 requires each gate to prove its outputs are usable by the *next* phase,
not merely internally correct. Phase 4 is siting: it ranks candidate cells by a score
built from demand, and selects a budget-feasible portfolio with a greedy marginal-gain
solver.

This exercises that shape — score, sort, select under a budget, report coverage — over a
real Phase 3 demand surface built from cached inputs. **It does not attempt to be a
siting model.** It proves the data shape works: that every candidate carries a demand
estimate, an uncertainty score and a confidence tier; that the tier and evidence grain
survive into a selection; and that a budget constraint can be applied without any field
Phase 3 failed to provide.

What it does NOT prove: that any selected cell is a good place to build. No validation in
this project demonstrates that, and none is claimed.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from pipeline.model.build_demand import TractEstimate, build_surface
from pipeline.model.observed import latest_state_totals, load_all, load_state_totals
from pipeline.model.panel import build_panels, load_area_tables
from pipeline.model.run_phase3 import allocation_penalty
from pipeline.validation.demand_model import nearest_vintage, snapshot_date

# Two states, as CLAUDE.md §14 requires of an integration fixture: Vermont (ZIP-grain,
# small) and Washington (the only tract-native source).
FIXTURE_STATES = ("50", "53")


@dataclass(frozen=True)
class Candidate:
    """The minimum a Phase 4 candidate needs from Phase 3."""

    geoid: str
    demand: float
    uncertainty: float
    tier: str
    evidence_grain: str
    cost: float


def to_candidate(row: TractEstimate) -> Candidate:
    """Phase 4 reads exactly these fields. A missing one would fail here, not there."""
    return Candidate(
        geoid=row.geoid,
        demand=row.estimate,
        uncertainty=row.uncertainty_score,
        tier=row.confidence_tier,
        evidence_grain=row.evidence_grain,
        # A placeholder unit cost. Phase 4 supplies the real cost model; this only has
        # to be positive so the budget constraint binds.
        cost=1.0,
    )


def greedy_under_budget(candidates: list[Candidate], budget: float) -> list[Candidate]:
    """Take candidates in descending demand until the budget is exhausted.

    This is a *shape* check, not the Phase 4 solver. Phase 4 must define its algorithm
    exactly, state its problem class, and report empirical optimality gaps against
    offline CBC; **no approximation bound is claimed here or anywhere** (amendment A11).
    """
    chosen: list[Candidate] = []
    spent = 0.0
    for candidate in sorted(candidates, key=lambda c: (-c.demand, c.geoid)):
        if spent + candidate.cost > budget:
            continue
        chosen.append(candidate)
        spent += candidate.cost
    return chosen


@pytest.fixture(scope="module")
def surface():  # type: ignore[no-untyped-def]
    tables = load_area_tables(states=FIXTURE_STATES)
    observations = load_all()
    panels = build_panels(observations, tables)
    penalty, _ = allocation_penalty()
    series = load_state_totals()
    chosen = latest_state_totals()
    for state, observed in observations.items():
        when = snapshot_date(observed.vintage_label)
        if when is not None:
            from pipeline.model.observed import STATE_FIPS

            chosen[STATE_FIPS[state]] = nearest_vintage(series[STATE_FIPS[state]], when)
    return build_surface(tables["tracts"], panels, observations, chosen, penalty,
                         "poisson_glm", source_statuses=("confirmed",) * 8,
                         bootstrap_replicates=4)


def test_every_tract_carries_the_fields_phase_4_will_read(surface) -> None:  # type: ignore[no-untyped-def]
    candidates = [to_candidate(row) for row in surface.estimates]
    # Vermont (193 tracts) plus Washington (1,784) in the two-state fixture.
    assert len(candidates) == 1977
    assert all(c.demand >= 0.0 for c in candidates)
    assert all(0.0 <= c.uncertainty <= 1.0 for c in candidates)
    assert all(c.tier in {"A", "B", "C"} for c in candidates)
    assert all(c.evidence_grain in
               {"native_tract", "county_anchored", "state_total_only"}
               for c in candidates)


def test_a_budget_constrained_selection_runs_over_the_real_surface(surface) -> None:  # type: ignore[no-untyped-def]
    candidates = [to_candidate(row) for row in surface.estimates]
    selected = greedy_under_budget(candidates, budget=250.0)
    assert len(selected) == 250
    assert sum(c.cost for c in selected) <= 250.0
    # Selection is deterministic: ties break on geoid, not on dictionary order.
    assert selected == greedy_under_budget(list(reversed(candidates)), 250.0)


def test_the_selection_carries_its_confidence_context_through(surface) -> None:  # type: ignore[no-untyped-def]
    """A ranked portfolio that lost its uncertainty on the way would breach D7."""
    selected = greedy_under_budget(
        [to_candidate(row) for row in surface.estimates], budget=100.0)
    tiers = {c.tier for c in selected}
    assert tiers, "a selection must report the confidence of what it selected"
    assert all(c.uncertainty > 0.0 or c.evidence_grain == "native_tract"
               for c in selected)


def test_demand_covered_by_the_selection_is_reportable(surface) -> None:  # type: ignore[no-untyped-def]
    candidates = [to_candidate(row) for row in surface.estimates]
    total = sum(c.demand for c in candidates)
    covered = sum(c.demand for c in greedy_under_budget(candidates, 500.0))
    assert 0.0 < covered <= total
    # The top 500 tracts by demand hold a materially larger share than 500/N.
    assert covered / total > 500.0 / len(candidates)


def test_the_surface_reconciles_exactly_before_phase_4_consumes_it(surface) -> None:  # type: ignore[no-untyped-def]
    assert surface.reconciliation.max_residual < 1e-6
    assert surface.estimator == "poisson_glm"
