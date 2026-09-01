"""The Phase 5 driver: one command reproduces every validation number, offline."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from pipeline.model.run_phase5 import (
    ALIGNMENT_BASELINES,
    align_origin,
    cross_objective_robustness,
    demand_model_validation,
    historical_cells,
    load_station_history,
    main,
    run,
)
from pipeline.validation.deployment_alignment import Deployment
from pipeline.validation.origins import Origin, plan_origins


def test_the_alignment_baselines_are_fixed_before_any_result_was_seen() -> None:
    """§10.2.4 requires random and population; existing-network is added because it is
    the baseline this project most needs to beat. Pre-registering keeps it honest."""
    assert ALIGNMENT_BASELINES == ("random", "population", "existing_network")


# --- the reconstruction ---------------------------------------------------------------

@pytest.fixture(scope="module")
def history() -> tuple[list[Deployment], dict[str, int]]:
    return load_station_history()


def test_the_station_history_is_placed_on_the_grid_with_dates_and_capacity(
    history: tuple[list[Deployment], dict[str, int]],
) -> None:
    deployments, counts = history
    assert len(deployments) > 70000
    assert counts["distinct_stations"] > 80000
    assert all(d.cell and d.state for d in deployments[:100])


def test_every_station_dropped_from_the_reconstruction_is_counted_by_reason(
    history: tuple[list[Deployment], dict[str, int]],
) -> None:
    """D8: an exclusion is a reportable gap, not something to make disappear."""
    _, counts = history
    for reason in ("not_operational", "not_public", "no_open_date",
                   "unparseable_open_date", "no_coordinates"):
        assert reason in counts, reason
    assert counts["no_open_date"] > 0


def test_only_public_operational_stations_enter_the_reconstruction(
    history: tuple[list[Deployment], dict[str, int]],
) -> None:
    """G2 and G3, the same filters the supply model uses."""
    _, counts = history
    assert counts["not_operational"] > 0
    assert counts["not_public"] > 0


# --- one origin, end to end on a two-state fixture ------------------------------------

@pytest.fixture(scope="module")
def two_states() -> tuple[Any, dict[str, float], dict[str, float], dict[str, Any]]:
    plans, _ = plan_origins()
    plan = plans[0]
    demand, population, detail = historical_cells(plan, None, states=("50", "11"))
    return plan, demand, population, detail


def test_a_historical_origin_builds_from_contemporaneous_inputs_only(
    two_states: tuple[Any, dict[str, float], dict[str, float], dict[str, Any]],
) -> None:
    _plan, demand, population, detail = two_states
    assert detail["acs_api_year"] == 2018
    assert detail["tract_geography"] == "2010"
    assert "CenPop2010" in str(detail["population_weight_vintage"])
    assert detail["evidence_grain"] == "state_total_only"
    assert demand and population


def test_the_historical_surface_conserves_its_state_totals_onto_cells(
    two_states: tuple[Any, dict[str, float], dict[str, float], dict[str, Any]],
) -> None:
    _, demand, _, detail = two_states
    allocated = sum(demand.values())
    unallocated = float(detail["tract_demand_not_allocated_to_any_cell"])
    assert allocated + unallocated == pytest.approx(
        float(detail["reconciled_state_total_bev"]), rel=1e-6)


def test_scoring_an_origin_produces_a_model_and_every_baseline(
    two_states: tuple[Any, dict[str, float], dict[str, float], dict[str, Any]],
    history: tuple[list[Deployment], dict[str, int]],
) -> None:
    plan, demand, population, detail = two_states
    deployments, _ = history
    alignment = align_origin(plan, demand, population, deployments, detail)
    assert alignment.model.name == "model_cutoff_valid_demand"
    assert {b.name for b in alignment.baselines} == set(ALIGNMENT_BASELINES)
    assert alignment.deployments > 0
    assert alignment.states_covered > 0


def test_only_inhabited_cells_are_ranked(
    two_states: tuple[Any, dict[str, float], dict[str, float], dict[str, Any]],
    history: tuple[list[Deployment], dict[str, int]],
) -> None:
    """An uninhabited cell is not a siting candidate under any model, and including
    them would inflate every ranking equally rather than informatively."""
    plan, demand, population, detail = two_states
    deployments, _ = history
    alignment = align_origin(plan, demand, population, deployments, detail)
    assert alignment.cells_evaluated <= len(demand)
    assert alignment.cells_evaluated > 0


def test_an_origin_whose_window_predates_every_station_scores_zero_not_an_error(
    two_states: tuple[Any, dict[str, float], dict[str, float], dict[str, Any]],
    history: tuple[list[Deployment], dict[str, int]],
) -> None:
    """AFDC open dates start in 1995; a 1990 window has nothing in it. The harness must
    report a zero capture rather than dividing by zero."""
    plan, demand, population, detail = two_states
    deployments, _ = history
    ancient = type(plan)(
        origin=Origin("1990", date(1990, 1, 1)), acs=plan.acs,
        registrations=plan.registrations, acs_year=plan.acs_year,
        tract_geography=plan.tract_geography)
    alignment = align_origin(ancient, demand, population, deployments, detail)
    assert alignment.deployments == 0
    assert alignment.model.top_decile_stations == 0.0
    assert alignment.lift("random") == 1.0


# --- the other two tracks -------------------------------------------------------------

def test_demand_model_validation_is_read_from_phase_3_rather_than_refitted() -> None:
    track = demand_model_validation()
    assert "restated not re-fitted" in str(track["source"])
    assert track["term"] == "demand model validation"
    assert track["leave_one_state_out"]


def test_cross_objective_robustness_covers_every_frontier_state_and_budget() -> None:
    from pipeline.model.run_phase4 import FRONTIER_STATES

    result = cross_objective_robustness(budgets=(5,))
    rows = result["per_state_and_budget"]
    assert isinstance(rows, list)
    assert len(rows) == len(FRONTIER_STATES)
    assert all(row["budget_sites"] == 5 for row in rows)


# --- the artifact ---------------------------------------------------------------------

@pytest.fixture(scope="module")
def payload() -> dict[str, Any]:
    """One origin and two states: enough to prove every section is produced, without
    paying for the full national run three times."""
    from pipeline.validation.origins import ORIGINS

    return run(states=("50", "11"), origins=ORIGINS[:1])


def test_the_driver_produces_every_published_section(payload: dict[str, Any]) -> None:
    for section in ("phase", "validation_terms", "vintage_ledger", "origin_plans",
                    "station_reconstruction", "deployment_alignment",
                    "demand_model_validation", "cross_objective_robustness"):
        assert section in payload, section
    assert payload["phase"] == 5


def test_the_three_validation_terms_are_never_blurred(payload: dict[str, Any]) -> None:
    """D3. Each has its own definition and none claims what another claims."""
    terms = payload["validation_terms"]
    assert "leave-one-state-out" in terms["demand_model_validation"]
    assert "rolling-origin backtest" in terms["historical_deployment_alignment"]
    assert "never in the loss function" in terms["cross_objective_robustness"]


def test_the_artifact_is_json_serialisable_and_written_where_asked(
    tmp_path: Path,
) -> None:
    out = tmp_path / "validation.json"
    assert main(["--out", str(out), "--states", "50", "11"]) == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["phase"] == 5
    assert len(written["deployment_alignment"]) == 3


# --- the reconstruction's rejection paths ---------------------------------------------

def station(open_date: str = "2021-06-01", lat: object = "47.6",
            lon: object = "-122.3") -> dict[str, Any]:
    return {"open": open_date, "lat": lat, "lon": lon, "state": "WA",
            "ports": 2.0, "dcfc": 1.0}


def test_a_station_with_a_usable_open_date_and_coordinates_is_accepted() -> None:
    from pipeline.model.run_phase5 import parse_station

    counts: dict[str, int] = {"no_open_date": 0, "unparseable_open_date": 0,
                              "no_coordinates": 0}
    entry = station()
    assert parse_station(entry, counts) == date(2021, 6, 1)
    assert counts == {"no_open_date": 0, "unparseable_open_date": 0,
                      "no_coordinates": 0}
    # The parsed floats are carried so the caller does not parse them twice.
    assert entry["latf"] == 47.6 and entry["lonf"] == -122.3


@pytest.mark.parametrize(
    ("entry", "reason"),
    [
        (station(open_date=""), "no_open_date"),
        (station(open_date="not-a-date"), "unparseable_open_date"),
        (station(open_date="2021-13-45"), "unparseable_open_date"),
        (station(lat=None), "no_coordinates"),
        (station(lon="north"), "no_coordinates"),
    ],
)
def test_an_unusable_station_is_counted_by_reason_rather_than_dropped(
    entry: dict[str, Any], reason: str
) -> None:
    """D8: an excluded record is a reportable gap. On the committed snapshot two of these
    paths never fire, and a counter nobody has exercised is a counter nobody knows
    works."""
    from pipeline.model.run_phase5 import parse_station

    counts = {"no_open_date": 0, "unparseable_open_date": 0, "no_coordinates": 0}
    assert parse_station(entry, counts) is None
    assert counts[reason] == 1
    assert sum(counts.values()) == 1


# --- station capacity, reusing Phase 2's ladder ---------------------------------------

def unit_row(key: str, station: str, level: str = "DC",
             **connectors: object) -> dict[str, Any]:
    row: dict[str, Any] = {
        "charging_unit_record_key": key, "station_id": station,
        "unit_charging_level": level, "unit_network": "Test", "unit_port_count": 1,
    }
    row.update(connectors)
    return row


def test_capacity_takes_the_maximum_of_alternative_connectors_never_the_sum() -> None:
    """§7.1.1: a one-port unit offering CCS at 200 kW and CHAdeMO at 100 kW contributes
    200 kW of simultaneous capacity, not 300."""
    from pipeline.model.run_phase5 import station_capacity_kw

    rows = [unit_row("u1", "s1",
                     connector_J1772COMBO_port_count=1,
                     connector_J1772COMBO_power_kw=200.0,
                     connector_CHADEMO_port_count=1,
                     connector_CHADEMO_power_kw=100.0)]
    assert station_capacity_kw(rows)["s1"] == pytest.approx(200.0)


def test_capacity_sums_across_the_units_of_one_station() -> None:
    """Separate units ARE separate service positions, so those do add."""
    from pipeline.model.run_phase5 import station_capacity_kw

    rows = [unit_row("u1", "s1", connector_J1772COMBO_port_count=1,
                     connector_J1772COMBO_power_kw=150.0),
            unit_row("u2", "s1", connector_J1772COMBO_port_count=1,
                     connector_J1772COMBO_power_kw=50.0)]
    assert station_capacity_kw(rows)["s1"] == pytest.approx(200.0)


def test_a_unit_whose_capacity_cannot_be_resolved_contributes_nothing_not_a_guess(
) -> None:
    """A multi-port unit does not inherit the one-port maximum rule (amendment A19):
    AFDC exposes no per-port connector mapping, so which connectors serve which port is
    unknown. Such a unit reports None, and D8 says contribute 0 rather than invent."""
    from pipeline.model.run_phase5 import station_capacity_kw

    rows = [unit_row("u1", "s1", connector_J1772COMBO_port_count=2,
                     connector_J1772COMBO_power_kw=150.0,
                     connector_CHADEMO_port_count=2,
                     connector_CHADEMO_power_kw=50.0)]
    rows[0]["unit_port_count"] = 2
    assert station_capacity_kw(rows) == {}


def test_a_unit_with_no_connectors_at_all_is_skipped() -> None:
    from pipeline.model.run_phase5 import station_capacity_kw

    assert station_capacity_kw([unit_row("u1", "s1")]) == {}
