"""Phase 5 driver: the three validation tracks, from cached inputs only.

CLAUDE.md §10 and directive D3. Three terms, never blurred:

1. **Demand model validation** - whether tract-level EV estimates are accurate.
   Leave-one-state-out against observed states. Ran in Phase 3; restated here under the
   vintage guard, not re-fitted.
2. **Historical deployment alignment** - whether priority areas match where industry
   actually built. Vintage-enforced rolling-origin backtest.
3. **Cross-objective robustness** - whether a portfolio optimised for one objective also
   performs on others. Evaluated on objectives never in the loss function.

None of these demonstrates that a site is optimal.
Ground truth for optimal siting does not exist, and no output of this module claims
otherwise.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pipeline.config.settings import PATHS
from pipeline.discovery.cache import Fetcher, ReplayFetcher
from pipeline.model.ablation import (
    DCFC_LEVEL,
    OPERATIONAL_STATUS,
    PUBLIC_ACCESS,
    STATIONS_SNAPSHOT,
)
from pipeline.model.features import GAZETTEER_BY_TRACT_GEOGRAPHY, load_land_area_km2
from pipeline.model.panel import build_area_table, prediction_rows
from pipeline.model.run_phase3 import ALL_STATE_FIPS
from pipeline.sources.catalog import local_json_source
from pipeline.sources.census_acs import TRACT, AcsSource
from pipeline.spatial.h3_grid import (
    RESOLUTION_NATIONAL,
    allocate_to_cells,
    cells_for_points,
    load_population_points,
    tract_cell_weights,
)
from pipeline.validation.backtest import KNOWN_EXCLUSIONS, build_historical_surface
from pipeline.validation.deployment_alignment import (
    Deployment,
    OriginAlignment,
    ranked_by,
    score_random_baseline,
    score_ranking,
)
from pipeline.validation.origins import ORIGINS, OriginPlan, plan_origins
from pipeline.validation.robustness import evaluate as evaluate_robustness

#: Baselines for deployment alignment, fixed here before any result was seen (§10.2.4
#: requires random and population; existing-network is added because it is the baseline
#: this project most needs to beat, and pre-registering it now is what keeps it honest).
ALIGNMENT_BASELINES = ("random", "population", "existing_network")

EVIDENCE = PATHS.root / "docs" / "evidence" / "P5-1_validation.json"


def station_capacity_kw(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """Non-overlapping generic service capacity per station, in kW (§7.1.1).

    Reuses Phase 2's power ladder and its capacity rule rather than restating them, so
    the two cannot drift: connector powers resolve through reported -> empirical median
    -> documented type default, and a unit's generic capacity is the MAXIMUM of its
    mutually alternative connector outputs, never their sum. §10.2.4 requires capacity
    captured alongside ports, because a station record is one network's presence at a
    site and not a unit of capacity (G1).

    A unit whose capacity the source cannot resolve contributes 0 rather than a guess.
    """
    from pipeline.model.build_supply_access import build_unit_capacities, resolve_all
    from pipeline.model.supply import load_connectors

    connectors = load_connectors()
    observations: list[dict[str, Any]] = []
    unit_station: dict[str, str] = {}
    for row in rows:
        key = str(row.get("charging_unit_record_key") or "")
        unit_station[key] = str(row.get("station_id") or "")
        for raw in connectors:
            count = row.get(f"connector_{raw}_port_count")
            if not count or int(float(count)) <= 0:
                continue
            observations.append({
                "charging_unit_record_key": key,
                "connector_type_raw": raw,
                "connector_count": int(float(count)),
                "power_kw": row.get(f"connector_{raw}_power_kw"),
                "charging_level": str(row.get("unit_charging_level") or ""),
                "network": str(row.get("unit_network") or ""),
                "port_count": int(float(row.get("unit_port_count") or 0)),
            })
    resolved, _empirical, _tally = resolve_all(observations, connectors)
    kept = [o for o in observations if int(o.get("connector_count", 0) or 0) > 0]
    capacity: dict[str, float] = {}
    for unit in build_unit_capacities(kept, resolved):
        station = unit_station.get(unit.charging_unit_record_key, "")
        if station and unit.generic_service_capacity_kw is not None:
            capacity[station] = (capacity.get(station, 0.0)
                                 + float(unit.generic_service_capacity_kw))
    return capacity


def parse_station(
    entry: dict[str, Any], counts: dict[str, int]
) -> date | None:
    """The open date of one station, or ``None`` with the reason counted.

    Extracted so the rejection paths are reachable from a test. On the committed snapshot
    two of them never fire - 0 unparseable dates, 0 stations without coordinates - but a
    refresh can produce either, and a counter that has never been exercised is a counter
    nobody knows works. Directive D8: an excluded record is a reportable gap, not
    something to make disappear.

    ``entry`` is mutated to carry the parsed float coordinates, so the caller does not
    parse them a second time.
    """
    if not entry["open"]:
        counts["no_open_date"] += 1
        return None
    try:
        opened = date.fromisoformat(entry["open"])
    except ValueError:
        counts["unparseable_open_date"] += 1
        return None
    try:
        entry["latf"] = float(entry["lat"])
        entry["lonf"] = float(entry["lon"])
    except (TypeError, ValueError):
        counts["no_coordinates"] += 1
        return None
    return opened


def load_station_history(
    resolution: int = RESOLUTION_NATIONAL,
) -> tuple[list[Deployment], dict[str, int]]:
    """Every public operational station with a usable open date, placed on the grid.

    **This is an approximate reconstruction (G10, G11).** A current snapshot plus
    ``Open Date`` cannot recover stations that closed, left the feed, or changed port
    counts, so the historical network is survivorship-biased and the bias grows with age.
    Open dates are documented as approximate and, for automated network feeds, may record
    first appearance in the Station Locator rather than actual opening.
    """
    table = local_json_source("afdc_charging_units", STATIONS_SNAPSHOT).load()
    capacity_by_station = station_capacity_kw(table.rows)
    stations: dict[str, dict[str, Any]] = {}
    counts = {"rows": 0, "not_operational": 0, "not_public": 0, "no_open_date": 0,
              "unparseable_open_date": 0, "no_coordinates": 0}
    for row in table.rows:
        counts["rows"] += 1
        if row.get("station_status_code") != OPERATIONAL_STATUS:
            counts["not_operational"] += 1
            continue
        if row.get("station_access_code") != PUBLIC_ACCESS:
            counts["not_public"] += 1
            continue
        station_id = str(row.get("station_id") or "")
        entry = stations.get(station_id)
        if entry is None:
            entry = {"open": (row.get("station_open_date") or "")[:10],
                     "lat": row.get("station_latitude"),
                     "lon": row.get("station_longitude"),
                     "state": str(row.get("station_state") or ""),
                     "ports": 0.0, "dcfc": 0.0}
            stations[station_id] = entry
        ports = float(row.get("unit_port_count") or 0.0)
        entry["ports"] += ports
        if row.get("unit_charging_level") == DCFC_LEVEL:
            entry["dcfc"] += ports

    usable: list[tuple[str, dict[str, Any], date]] = []
    for station_id, entry in stations.items():
        opened = parse_station(entry, counts)
        if opened is not None:
            usable.append((station_id, entry, opened))

    cells = cells_for_points([e["latf"] for _, e, _ in usable],
                             [e["lonf"] for _, e, _ in usable], resolution)
    deployments = [
        Deployment(station_id=sid, cell=cell, opened=opened,
                   ports=float(e["ports"]), dcfc_ports=float(e["dcfc"]),
                   state=str(e["state"]),
                   capacity_kw=capacity_by_station.get(sid, 0.0))
        for (sid, e, opened), cell in zip(usable, cells, strict=True)
    ]
    counts["stations_placed"] = len(deployments)
    counts["distinct_stations"] = len(stations)
    return deployments, counts


def historical_cells(
    plan: OriginPlan, fetcher: Fetcher | None = None,
    states: Sequence[str] = ALL_STATE_FIPS,
    resolution: int = RESOLUTION_NATIONAL,
) -> tuple[dict[str, float], dict[str, float], dict[str, Any]]:
    """Cutoff-valid modelled demand and population, on H3 cells.

    Every input is contemporaneous: the ACS release the origin resolved to, that
    release's own tract geography, the matching gazetteer for land area, the state
    registration vintage available at the cutoff, and the **2010** block-group
    population weights that go with 2010 tracts.
    """
    from pipeline.model.observed import load_state_totals

    source = fetcher or ReplayFetcher(PATHS.cache)
    geography = plan.tract_geography
    land = load_land_area_km2("tracts", GAZETTEER_BY_TRACT_GEOGRAPHY[geography])

    staged: list[Mapping[str, str]] = []
    for state in states:
        staged.extend(
            AcsSource(TRACT, state, year=plan.acs_year).load(source).rows)
    table = build_area_table(staged, "tracts", land)
    rows = prediction_rows(table)

    vintage_year = str(plan.registrations.period_end.year)
    totals_by_state = load_state_totals(source, vintages=(vintage_year,))
    totals = {
        state: float(entries[0].bev_count)
        for state, entries in totals_by_state.items()
        if entries and state in {r.state for r in rows}
    }

    surface = build_historical_surface(
        rows, totals, plan.origin.cutoff, plan.acs_year, geography,
        plan.registrations.label, plan.acs.period_end, "census_acs_tracts",
        f"{plan.acs.label}, released {plan.acs.released.isoformat()}")

    census_vintage = "2010" if geography == "2010" else "2020"
    weights: dict[str, Any] = {}
    for state in states:
        weights.update(tract_cell_weights(
            load_population_points(state, source, census_vintage), resolution))
    demand_cells, unallocated_demand = allocate_to_cells(surface.estimates, weights)
    population_cells, _ = allocate_to_cells(dict(surface.population), weights)

    detail = surface.to_dict()
    detail["population_weight_vintage"] = f"CenPop{census_vintage} block group"
    detail["cells"] = len(demand_cells)
    detail["tract_demand_not_allocated_to_any_cell"] = round(
        sum(unallocated_demand.values()), 4)
    detail["state_totals_used"] = len(totals)
    return demand_cells, population_cells, detail


def align_origin(
    plan: OriginPlan,
    demand_cells: Mapping[str, float],
    population_cells: Mapping[str, float],
    deployments: Sequence[Deployment],
    surface_detail: Mapping[str, Any],
) -> OriginAlignment:
    """Score the cutoff-valid ranking, and every baseline, against what got built."""
    cutoff, window_end = plan.origin.cutoff, plan.origin.window_end
    prior_dcfc: dict[str, float] = {}
    for d in deployments:
        if d.opened < cutoff and d.dcfc_ports > 0:
            prior_dcfc[d.cell] = prior_dcfc.get(d.cell, 0.0) + d.dcfc_ports

    target_stations: dict[str, float] = {}
    target_ports: dict[str, float] = {}
    target_dcfc: dict[str, float] = {}
    target_capacity: dict[str, float] = {}
    states_seen: set[str] = set()
    built = 0
    for d in deployments:
        if not (cutoff <= d.opened < window_end):
            continue
        built += 1
        target_stations[d.cell] = target_stations.get(d.cell, 0.0) + 1.0
        target_ports[d.cell] = target_ports.get(d.cell, 0.0) + d.ports
        target_dcfc[d.cell] = target_dcfc.get(d.cell, 0.0) + d.dcfc_ports
        target_capacity[d.cell] = target_capacity.get(d.cell, 0.0) + d.capacity_kw
        states_seen.add(d.state)

    # Only inhabited cells are rankable: an uninhabited cell is not a siting candidate
    # under any model, and including them would inflate every ranking equally. EVERY
    # ranking - model and baselines alike - is scored over exactly this support, so a
    # deployment outside it is a miss for all of them rather than an exclusion for some.
    cells = sorted(c for c in demand_cells if population_cells.get(c, 0.0) >= 1.0)
    eligible = set(cells)
    total_stations = sum(target_stations.values()) or 1.0
    support = {
        "ranked_cells": len(cells),
        "cells_with_demand": len(demand_cells),
        "cells_dropped_as_uninhabited": len(demand_cells) - len(cells),
        "share_of_subsequent_stations_inside_ranked_cells": round(
            sum(v for c, v in target_stations.items() if c in eligible)
            / total_stations, 6),
        "share_of_subsequent_ports_inside_ranked_cells": round(
            sum(v for c, v in target_ports.items() if c in eligible)
            / (sum(target_ports.values()) or 1.0), 6),
        "capture_denominator": (
            "ALL subsequent deployments in the window, including any landing outside "
            "the ranked cells. A deployment in an unranked cell is a miss for every "
            "ranking, not an exclusion, so the full-ranking capture is below 1.0 by "
            "exactly the share that fell outside."),
        "top_decile_construction": (
            "round(0.1 * len(ranked_cells)) cells taken from the head of the ranking; "
            "ties broken by cell id so the order is deterministic."),
        "baselines_share_this_support": True,
    }

    model = score_ranking("model_cutoff_valid_demand", ranked_by(demand_cells, cells),
                          target_stations, target_ports, target_dcfc, target_capacity)
    random_result, random_spread = score_random_baseline(
        cells, target_stations, target_ports, target_dcfc, target_capacity,
        seed=int(plan.origin.name))
    baselines = (
        random_result,
        score_ranking("population", ranked_by(population_cells, cells),
                      target_stations, target_ports, target_dcfc, target_capacity),
        score_ranking("existing_network", ranked_by(prior_dcfc, cells),
                      target_stations, target_ports, target_dcfc, target_capacity),
    )
    return OriginAlignment(
        origin=plan.origin.name, cutoff=cutoff, window_end=window_end,
        cells_evaluated=len(cells), deployments=built,
        deployment_ports=sum(target_ports.values()),
        deployment_dcfc_ports=sum(target_dcfc.values()),
        states_covered=len(states_seen - {""}),
        model=model, baselines=baselines,
        reconstruction_confidence=plan.origin.reconstruction_confidence,
        vintages={**plan.to_dict(), "surface": dict(surface_detail)},
        eligible_support=support,
        random_baseline_spread=random_spread.to_dict(),
        deployment_capacity_kw=sum(target_capacity.values()),
    )


def cross_objective_robustness(budgets: Sequence[int] = (5, 20, 50)) -> dict[str, Any]:
    """Track 3: score Phase 4 portfolios on objectives their optimiser never saw.

    Uses the **current** surface and the frozen Phase 4 candidate construction. This is
    not a temporal exercise, so no cutoff applies and no vintage question arises; what is
    being asked is whether optimising for one objective costs performance on another.
    """
    from pipeline.model.build_demand import build_surface
    from pipeline.model.hexes import load_hex_supply
    from pipeline.model.observed import load_all
    from pipeline.model.panel import build_panels, load_area_tables
    from pipeline.model.run_phase3 import allocation_penalty, constraint_totals
    from pipeline.model.run_phase4 import (
        FRONTIER_STATES,
        SATURATION_PORTS_PER_1K,
        state_cells,
    )
    from pipeline.model.siting import (
        MAXIMISE_DEMAND,
        MAXIMISE_EQUITY,
        build_candidates,
        greedy_select,
        solve_epsilon_constraint,
    )
    from pipeline.sources.tiger_roads import read_road_vertices
    from pipeline.spatial.road_proximity import (
        DEFAULT_ROAD_PROXIMITY_KM,
        measure_road_distances,
    )

    frontier = tuple(f for f, _, _ in FRONTIER_STATES)
    tables = load_area_tables(states=frontier)
    observations = load_all(known_tracts=sorted(tables["tracts"].rows))
    penalty, _ = allocation_penalty()
    surface = build_surface(
        tables["tracts"], build_panels(observations, tables), observations,
        constraint_totals(observations), penalty, "poisson_glm",
        source_statuses=("confirmed",) * 8, bootstrap_replicates=20)
    supply = load_hex_supply()

    results: list[dict[str, Any]] = []
    labels = {fips: name for fips, name, _ in FRONTIER_STATES}
    for state_fips in frontier:
        cells = state_cells(surface.estimates, state_fips, supply)
        geometry = read_road_vertices(state_fips).index()
        distances = measure_road_distances(
            [c.h3_index for c in cells], geometry, DEFAULT_ROAD_PROXIMITY_KM)
        candidates = build_candidates(cells, SATURATION_PORTS_PER_1K, distances)
        for budget in budgets:
            optimised = {
                "greedy_demand": greedy_select(candidates, budget).selected,
                "epsilon_demand_first": solve_epsilon_constraint(
                    candidates, budget, 0.0, MAXIMISE_DEMAND).selected,
                "epsilon_equity_first": solve_epsilon_constraint(
                    candidates, budget, 0.0, MAXIMISE_EQUITY).selected,
            }
            results.append(evaluate_robustness(
                labels.get(state_fips, state_fips), candidates, budget, optimised,
                seed=budget).to_dict())
    return {
        "what_this_is": (
            "cross-objective robustness (§10.3): a portfolio optimised on one objective, "
            "scored on objectives that were never in its loss function"),
        "what_this_is_not": (
            "This is NOT proof of siting correctness and NOT evidence of real-world "
            "optimality. A portfolio scoring well on the objective it was optimised for "
            "is CIRCULAR and is not a finding. "
            "Ground truth for optimal siting does not exist."),
        "per_state_and_budget": results,
    }


def demand_model_validation() -> dict[str, Any]:
    """Track 1: restate the Phase 3 leave-one-state-out result under the vintage guard.

    **Restated, not re-fitted.** Phase 5 validates the model; it is not licence for a
    post-hoc bakeoff, and re-running estimator selection here would be exactly that. The
    figures are read from the Phase 3 evidence artifact so the two cannot drift.
    """
    path = PATHS.root / "docs" / "evidence" / "P3-2_demand_model.json"
    if not path.exists():  # pragma: no cover - Phase 3 evidence is committed
        return {"available": False,
                "reason": f"Phase 3 evidence artifact missing at {path}"}
    phase3 = json.loads(path.read_text(encoding="utf-8"))
    loso = phase3.get("demand_model_validation", {})
    return {
        "term": "demand model validation",
        "definition": (
            "whether tract-level EV estimates are accurate; leave-one-state-out against "
            "observed states, reported at each held-out state's NATIVE granularity"),
        "source": "docs/evidence/P3-2_demand_model.json, restated not re-fitted",
        "washington_status": (
            "development/training evidence, EXCLUDED from the independent headline "
            "aggregate because it is the only tract-native registry and the model saw "
            "it during development"),
        "leave_one_state_out": loso,
        "production_feature_vintage": phase3.get("feature_vintage", {}),
        "supply_feature_ablation": phase3.get("supply_feature_ablation", {}),
        "supply_features_in_primary_model": 0,
    }


def run(
    states: Sequence[str] = ALL_STATE_FIPS,
    origins: Sequence[Any] = ORIGINS,
    fetcher: Fetcher | None = None,
) -> dict[str, Any]:
    """Every Phase 5 measurement."""
    plans, ledger = plan_origins(origins)
    for exclusion in KNOWN_EXCLUSIONS:
        ledger.exclude(exclusion)

    deployments, station_counts = load_station_history()
    alignments = []
    for plan in plans:
        demand_cells, population_cells, detail = historical_cells(
            plan, fetcher, states)
        alignments.append(align_origin(
            plan, demand_cells, population_cells, deployments, detail))

    return {
        "phase": 5,
        "computed_at": datetime.now().astimezone().isoformat(),
        "validation_terms": {
            "demand_model_validation":
                "whether tract-level EV estimates are accurate; leave-one-state-out "
                "against observed states (ran in Phase 3, restated here)",
            "historical_deployment_alignment":
                "whether priority areas match where industry actually built; "
                "vintage-enforced rolling-origin backtest",
            "cross_objective_robustness":
                "whether a portfolio optimised for one objective also performs on "
                "others; evaluated on objectives never in the loss function",
            "none_of_these_shows":
                "that a site is optimal. Ground truth for optimal siting does not exist",
        },
        "vintage_ledger": ledger.to_dict(),
        "origin_plans": [p.to_dict() for p in plans],
        "station_reconstruction": {
            **station_counts,
            "labelling": (
                "APPROXIMATE RECONSTRUCTION. A current snapshot plus Open Date cannot "
                "recover stations that closed, left the feed, or changed port counts, "
                "so the historical network is survivorship-biased and the bias grows "
                "with age (G10, G11)"),
        },
        "deployment_alignment": [a.to_dict() for a in alignments],
        "demand_model_validation": demand_model_validation(),
        "cross_objective_robustness": cross_objective_robustness(),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 5 validation")
    parser.add_argument("--out", default=str(EVIDENCE))
    parser.add_argument("--states", nargs="*", default=list(ALL_STATE_FIPS))
    args = parser.parse_args(argv)

    payload = run(states=tuple(args.states))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"wrote {out}")
    for entry in payload["deployment_alignment"]:
        print(f"  origin {entry['origin']}: "
              f"{entry['subsequent_deployments_available']:,} deployments, "
              f"top-decile capture {entry['model']['top_decile_capture_stations']:.3f}, "
              f"lift vs random {entry['lift_vs_random_stations']:.2f}, "
              f"vs population {entry['lift_vs_population_stations']:.2f}")
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
