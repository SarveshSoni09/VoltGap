"""A-2.1: does station clustering change which cells are candidates?

External review rejected the first treatment of this assumption, correctly. Arguing from
the ratio ``500 m / 3,834 m`` establishes that a cluster is small relative to a cell; it
establishes **nothing** about whether a clustered site crossing an H3 boundary alters a
cell's saturation classification or its candidate status. That has to be measured.

**What is compared.** The shipped supply path places each AFDC station at its own reported
coordinates and never clusters. The bounded alternatives cluster stations into sites with
DBSCAN and place a whole site's ports at the site centroid, which is the mechanism by which
clustering could move ports across a cell boundary:

* **shipped** — no clustering, each station at its own coordinates;
* **eps 50 m** — the Phase 1 site-resolution configuration;
* **eps 200 m** — deliberately coarser, to bound the effect of a more aggressive
  clustering choice rather than only testing the shipped one.

**What is reported**, per state and per condition: candidate-set Jaccard, the number of
cells whose saturation classification changes, portfolio overlap at each tested budget, and
the demand and equity objective deltas.

**A-2.1 is resolved only if the measurements support insensitivity.** If they do not, the
finding is preserved and candidate construction is corrected — not argued away with cell
geometry.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from pipeline.model.hexes import HexCell, HexSupply
from pipeline.model.siting import CandidateSet, build_candidates, greedy_select
from pipeline.spatial.road_proximity import RoadDistances

#: The bounded alternatives. ``None`` is the shipped path: no clustering at all.
CONDITIONS: tuple[tuple[str, float | None], ...] = (
    ("shipped_no_clustering", None),
    ("dbscan_eps_50m", 50.0),
    ("dbscan_eps_200m", 200.0),
)


def _jaccard(left: Sequence[str], right: Sequence[str]) -> float:
    a, b = set(left), set(right)
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


@dataclass(frozen=True)
class ConditionResult:
    """One clustering condition, scored against the shipped baseline."""

    condition: str
    eps_m: float | None
    candidates: int
    candidate_jaccard: float
    saturation_changes: int
    portfolio_overlap: Mapping[int, float]
    demand_delta: float
    equity_delta: float

    @property
    def material(self) -> bool:
        """Any change at all to candidates, saturation or a portfolio."""
        return (self.candidate_jaccard < 1.0
                or self.saturation_changes > 0
                or any(v < 1.0 for v in self.portfolio_overlap.values())
                or self.demand_delta != 0.0
                or self.equity_delta != 0.0)

    def to_dict(self) -> dict[str, object]:
        return {
            "condition": self.condition,
            "dbscan_eps_m": self.eps_m,
            "candidates": self.candidates,
            "candidate_set_jaccard": round(self.candidate_jaccard, 6),
            "cells_whose_saturation_classification_changes": self.saturation_changes,
            "portfolio_overlap_by_budget": {
                str(k): round(v, 6) for k, v in sorted(self.portfolio_overlap.items())},
            "demand_objective_delta": round(self.demand_delta, 6),
            "equity_objective_delta": round(self.equity_delta, 6),
            "material": self.material,
        }


def _saturated(cell: HexCell, supply: HexSupply, threshold: float) -> bool:
    if cell.demand_bev <= 0:
        return False
    return supply.dcfc_ports * 1000.0 / cell.demand_bev >= threshold


def compare_conditions(
    cells: Sequence[HexCell],
    supply_by_condition: Mapping[str, Mapping[str, HexSupply]],
    road_distances: RoadDistances,
    saturation_ports_per_1k_demand: float,
    budgets: Sequence[int] = (5, 20, 50),
) -> list[ConditionResult]:
    """Score every clustering condition against the shipped baseline."""
    if not budgets:
        raise ValueError("at least one budget is needed to compare portfolios")
    baseline_name = CONDITIONS[0][0]
    if baseline_name not in supply_by_condition:
        raise ValueError(f"the baseline condition {baseline_name!r} must be supplied")
    #: The budget the objective deltas are reported at. Portfolio overlap is reported at
    #: every budget; the objective deltas need one, and it is named rather than implied.
    objective_budget = budgets[len(budgets) // 2]

    def build(supply: Mapping[str, HexSupply]) -> tuple[
            list[HexCell], CandidateSet, dict[int, tuple[str, ...]]]:
        applied = [replace(cell, supply=supply.get(cell.h3_index, HexSupply()))
                   for cell in cells]
        candidates = build_candidates(
            applied, saturation_ports_per_1k_demand, road_distances)
        portfolios = {b: greedy_select(candidates, b).selected for b in budgets}
        return applied, candidates, portfolios

    base_cells, base_candidates, base_portfolios = build(
        supply_by_condition[baseline_name])
    base_index = [c.h3_index for c in base_candidates.candidates]
    base_saturation = {
        cell.h3_index: _saturated(cell, cell.supply, saturation_ports_per_1k_demand)
        for cell in base_cells
    }
    def objectives(
        selected: Sequence[str], candidates: CandidateSet
    ) -> tuple[float, float]:
        coverage = candidates.coverage
        by_index = {c.h3_index: c for c in candidates.candidates}
        covered: set[str] = set()
        for site in selected:
            covered.update(coverage[site])
        return (sum(by_index[c].demand for c in covered),
                sum(by_index[c].equity_population for c in covered))

    base_demand, base_equity = objectives(base_portfolios[objective_budget], base_candidates)

    results: list[ConditionResult] = []
    for name, eps in CONDITIONS:
        supply = supply_by_condition.get(name)
        if supply is None:
            continue
        applied, candidates, portfolios = build(supply)
        index = [c.h3_index for c in candidates.candidates]
        saturation = {
            cell.h3_index: _saturated(cell, cell.supply, saturation_ports_per_1k_demand)
            for cell in applied
        }
        changed = sum(1 for k, v in saturation.items()
                      if base_saturation.get(k, False) != v)
        demand, equity = objectives(portfolios[objective_budget], candidates)
        results.append(ConditionResult(
            condition=name, eps_m=eps, candidates=len(index),
            candidate_jaccard=_jaccard(base_index, index),
            saturation_changes=changed,
            portfolio_overlap={b: _jaccard(base_portfolios[b], portfolios[b])
                               for b in budgets},
            demand_delta=demand - base_demand,
            equity_delta=equity - base_equity,
        ))
    return results
