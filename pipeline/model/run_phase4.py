"""One command produces every Phase 4 number, as a hashed evidence artifact.

Run with ``python -m pipeline.model.run_phase4``. It reads only cached responses, so it
needs no network and no credentials, and writes ``docs/evidence/P4-1_siting.json``: the
candidate set with its exclusions, the epsilon-constraint frontier in both objective
directions, greedy solutions with measured optimality gaps against CBC, timing against
the two-second budget, and the four preflight investigations the assumption ledger
attached to this phase.

**The frontier is computed per state, and labelled as such.** CLAUDE.md §7.8 allows "per
state or on a stratified metro sample" because a national solve at eight epsilon levels in
two objective directions is sixteen national integer programs inside a six-hour CI ceiling.
The sample below spans jurisdiction size and, deliberately, all three evidence grains, so
the frontier is not accidentally reported only where the demand surface is best evidenced.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from pipeline.config.settings import PATHS
from pipeline.model.build_demand import TractEstimate, build_surface
from pipeline.model.hexes import (
    HexCell,
    assert_demand_conserved,
    assert_provenance_survived,
    build_hexes,
    load_hex_supply,
)
from pipeline.model.observed import load_all
from pipeline.model.panel import build_panels, load_area_tables
from pipeline.model.run_phase3 import allocation_penalty, constraint_totals
from pipeline.model.siting import (
    MAXIMISE_DEMAND,
    MAXIMISE_EQUITY,
    build_candidates,
    build_frontier,
    greedy_select,
    measure_optimality_gap,
)
from pipeline.model.siting_preflight import (
    assert_no_categorical_urban_rural,
    assess_cluster_sensitivity,
    assess_rounding_sensitivity,
    benchmark_centroid_resolution,
)
from pipeline.spatial.h3_grid import (
    RESOLUTION_NATIONAL,
    load_population_points,
    tract_cell_weights,
)

DEFAULT_OUT = PATHS.evidence / "P4-1_siting.json"

#: The documented stratified sample the published frontier is computed over. Chosen to
#: span jurisdiction size AND all three evidence grains, so the frontier is not reported
#: only where the demand surface happens to be best evidenced.
FRONTIER_STATES: tuple[tuple[str, str, str], ...] = (
    ("53", "Washington", "native_tract — the only tract-native registry"),
    ("47", "Tennessee", "county_anchored — complete county observations"),
    ("30", "Montana", "county_anchored — partial coverage, sparse and rural"),
    ("50", "Vermont", "state_total_only — small, ZIP-grain training evidence"),
    ("48", "Texas", "state_total_only — large, ZIP-grain training evidence"),
    ("06", "California", "state_total_only — largest jurisdiction by demand"),
)

BUDGETS: tuple[int, ...] = (5, 20, 50)
SATURATION_PORTS_PER_1K = 2.0
GREEDY_BUDGET_SECONDS = 2.0


def state_cells(
    estimates: Sequence[TractEstimate], state_fips: str,
    supply: Mapping[str, Any], resolution: int = RESOLUTION_NATIONAL,
) -> list[HexCell]:
    """Aggregate one state's tracts onto the grid, conserving demand and provenance."""
    rows = [row for row in estimates if row.state_fips == state_fips]
    weights = tract_cell_weights(load_population_points(state_fips), resolution)
    cells, unallocated = build_hexes(rows, weights, supply, resolution)
    assert_demand_conserved(rows, cells, unallocated)
    assert_provenance_survived(cells)
    return cells


def run(states: Sequence[str] = (), frontier_states: Sequence[str] = (),
        budgets: Sequence[int] = BUDGETS) -> dict[str, Any]:
    """Every Phase 4 measurement, from cached inputs only."""
    import time

    from pipeline.model.run_phase3 import ALL_STATE_FIPS

    wanted = tuple(states) if states else ALL_STATE_FIPS
    frontier = tuple(frontier_states) if frontier_states else tuple(
        f for f, _, _ in FRONTIER_STATES)

    tables = load_area_tables(states=wanted)
    observations = load_all(known_tracts=sorted(tables["tracts"].rows))
    penalty, _ = allocation_penalty()
    surface = build_surface(
        tables["tracts"], build_panels(observations, tables), observations,
        constraint_totals(observations), penalty, "poisson_glm",
        source_statuses=("confirmed",) * 8, bootstrap_replicates=20,
    )
    supply = load_hex_supply()

    per_state: list[dict[str, Any]] = []
    frontier_points: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    rounding: list[dict[str, Any]] = []
    slowest_greedy = 0.0

    labels = {fips: (name, why) for fips, name, why in FRONTIER_STATES}
    for state_fips in frontier:
        if state_fips not in wanted:
            continue
        cells = state_cells(surface.estimates, state_fips, supply)
        candidates = build_candidates(cells, SATURATION_PORTS_PER_1K)
        name, why = labels.get(state_fips, (state_fips, "unlabelled"))

        started = time.perf_counter()
        greedy = greedy_select(candidates, budgets[1])
        elapsed = time.perf_counter() - started
        slowest_greedy = max(slowest_greedy, elapsed)

        per_state.append({
            "state_fips": state_fips, "state": name, "why_in_the_sample": why,
            "tracts": sum(1 for r in surface.estimates if r.state_fips == state_fips),
            "cells": len(cells),
            "candidate_set": candidates.to_dict(),
            "demand_total": round(sum(c.demand_bev for c in cells), 4),
            "equity_population_total": round(
                sum(c.equity_population for c in cells), 2),
            "sub_state_anchored_share_of_demand": round(
                _weighted(cells, lambda c: c.sub_state_anchored_share), 6),
            "mean_uncertainty": round(_weighted(cells, lambda c: c.uncertainty_score), 6),
            "greedy": {**greedy.to_dict(), "seconds": round(elapsed, 4)},
        })
        for sense in (MAXIMISE_DEMAND, MAXIMISE_EQUITY):
            for point in build_frontier(candidates, budgets[1], sense=sense):
                frontier_points.append({"state": name, **point.to_dict()})
        for budget in budgets:
            gaps.append({"state": name,
                         **measure_optimality_gap(candidates, budget, name).to_dict()})
        rounding.append({
            "state": name,
            **assess_rounding_sensitivity(
                cells, budgets[1],
                sum(c.demand_bev for c in cells) or 1.0).to_dict()})

    sample_state = frontier[0] if frontier else wanted[0]
    points = load_population_points(sample_state)
    centroid = benchmark_centroid_resolution(
        points,
        {r.geoid: r.estimate for r in surface.estimates
         if r.state_fips == sample_state},
    )

    payload: dict[str, Any] = {
        "phase": 4,
        "spatial_unit": f"H3 resolution {RESOLUTION_NATIONAL}",
        "frontier_scope": (
            "PER STATE over a documented stratified sample, not national. CLAUDE.md "
            "§7.8 permits this because a national solve at eight epsilon levels in two "
            "directions is sixteen national integer programs inside a six-hour CI "
            "ceiling. The sample spans jurisdiction size and all three evidence grains."
        ),
        "budget_units": (
            "SITES, not dollars. Charger economics is Optional tier (§7.11) and no cost "
            "model exists; inventing a dollar cost would fabricate an input."
        ),
        "approximation_bound_claimed": None,
        "approximation_bound_note": (
            "No formal approximation bound is claimed anywhere. With uniform costs, a "
            "single coverage objective and no further constraint the problem would be "
            "cardinality-constrained maximum coverage, where a classical guarantee "
            "applies; the interactive surface exposes objective weights and constraint "
            "toggles, which is a different problem class, so the guarantee does not "
            "carry over. Measured optimality gaps are reported instead."
        ),
        "substation_filter": (
            "NONE. Phase 0 located no authoritative national substation dataset, so "
            "Core siting functions without one and no cell is excluded for lacking grid "
            "data (§7.9)."
        ),
        "transmission_language": (
            "Transmission proximity is not used by Phase 4. If it ever ships it is a "
            "labelled contextual proximity proxy and never an interconnection "
            "constraint (D6)."
        ),
        "per_state": per_state,
        "frontier": frontier_points,
        "empirical_optimality_gaps": gaps,
        "greedy_slowest_seconds": round(slowest_greedy, 4),
        "greedy_budget_seconds": GREEDY_BUDGET_SECONDS,
        "greedy_within_budget": slowest_greedy <= GREEDY_BUDGET_SECONDS,
        "preflight": {
            "A-2.1_site_clustering": assess_cluster_sensitivity().to_dict(),
            "A-2.2_rung_two_masked_power": {
                "assumption": "A-2.2",
                "triggered": False,
                "why": (
                    "A-2.2 conditions any phase that consumes IMPUTED capacity. Phase 4 "
                    "reads port COUNTS, which the source reports directly and which "
                    "involve no power-resolution ladder. HexSupply carries no kW field "
                    "at all, so the prerequisite cannot be violated by accident."
                ),
                "still_required_before": (
                    "any phase that consumes resolved capacity in kW"
                ),
            },
            "A-2.3_centroid_resolution": centroid.to_dict(),
            "A-3.4_state_total_rounding": rounding,
            "A-3.5_no_categorical_urban_rural": {
                "assumption": "A-3.5",
                "categorical_urban_rural_fields": [],
                "why": (
                    "Population density ships as a continuous feature. No keyless "
                    "tract-level Census urban/rural classification was retrieved, so a "
                    "category here would be manufactured and a threshold presented as a "
                    "finding."
                ),
            },
        },
    }
    for entry in per_state:
        assert_no_categorical_urban_rural(entry)
    return payload


def _weighted(cells: Sequence[HexCell], value: Callable[[HexCell], float]) -> float:
    """Demand-weighted mean: a big cell's evidence quality counts for more than a small
    one's, which a plain mean over cells would get wrong."""
    total = sum(c.demand_bev for c in cells)
    if total <= 0:
        return 0.0
    return float(sum(value(c) * c.demand_bev for c in cells) / total)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--states", nargs="*", default=[])
    parser.add_argument("--frontier-states", nargs="*", default=[])
    args = parser.parse_args(argv)
    payload = run(tuple(args.states), tuple(args.frontier_states))
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(f"wrote {args.out}")
    print(f"  states on the frontier   {len(payload['per_state'])}")
    print(f"  frontier points          {len(payload['frontier'])}")
    print(f"  slowest greedy           {payload['greedy_slowest_seconds']}s")
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
