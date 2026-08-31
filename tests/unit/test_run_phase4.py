"""The Phase 4 driver: one command reproduces every siting number, offline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pipeline.model.run_phase4 import (
    BUDGETS,
    FRONTIER_STATES,
    GREEDY_BUDGET_SECONDS,
    main,
    run,
    state_cells,
)


def test_the_frontier_sample_spans_every_evidence_grain() -> None:
    """So the frontier is not reported only where the demand surface is best evidenced."""
    reasons = " ".join(why for _, _, why in FRONTIER_STATES)
    for grain in ("native_tract", "county_anchored", "state_total_only"):
        assert grain in reasons, grain
    assert len(FRONTIER_STATES) == 6
    assert len({fips for fips, _, _ in FRONTIER_STATES}) == 6


def test_the_budget_ladder_is_documented_and_ordered() -> None:
    assert BUDGETS == (5, 20, 50)
    assert GREEDY_BUDGET_SECONDS == 2.0


@pytest.fixture(scope="module")
def payload() -> dict[str, Any]:
    return run(states=("50", "53"), frontier_states=("53",))


def test_the_driver_produces_every_published_section(payload: dict[str, Any]) -> None:
    assert payload["phase"] == 4
    for section in ("spatial_unit", "frontier_scope", "budget_units", "per_state",
                    "frontier", "greedy_objective_shortfall_vs_optimal_cbc",
                    "preflight"):
        assert section in payload, section
    assert payload["spatial_unit"] == "H3 resolution 6"


def test_no_approximation_bound_is_claimed_anywhere(payload: dict[str, Any]) -> None:
    """§7.8 and amendment A11."""
    assert payload["approximation_bound_claimed"] is None
    assert "does not carry over" in payload["approximation_bound_note"]
    for state in payload["per_state"]:
        assert state["greedy"]["approximation_bound_claimed"] is None


def test_no_substation_filter_and_no_interconnection_language(
    payload: dict[str, Any],
) -> None:
    """§7.9 and D6."""
    assert "NONE" in payload["substation_filter"]
    assert "never an interconnection" in payload["transmission_language"]
    for state in payload["per_state"]:
        assert state["candidate_set"]["no_mandatory_substation_filter"] is True


def test_every_frontier_point_is_feasible_and_both_directions_are_run(
    payload: dict[str, Any],
) -> None:
    senses = {p["objective_sense"] for p in payload["frontier"]}
    assert senses == {"maximise_demand_subject_to_equity",
                      "maximise_equity_subject_to_demand"}
    assert all(p["cbc_status"] == "optimal" for p in payload["frontier"])


def test_the_greedy_shortfall_is_measured_against_optimal_solves(
    payload: dict[str, Any],
) -> None:
    gaps = payload["greedy_objective_shortfall_vs_optimal_cbc"]
    assert len(gaps) == len(BUDGETS)
    for gap in gaps:
        assert gap["cbc_status"] == "optimal"
        assert 0.0 <= gap["greedy_objective_shortfall_vs_optimal_cbc"] < 0.25
        assert gap["greedy_objective"] <= gap["optimal_cbc_objective"] + 1e-6


def test_the_greedy_solver_meets_the_two_second_budget(
    payload: dict[str, Any],
) -> None:
    assert payload["greedy_within_budget"] is True
    assert payload["greedy_slowest_seconds"] <= GREEDY_BUDGET_SECONDS


def test_demand_provenance_survives_into_the_candidate_layer(
    payload: dict[str, Any],
) -> None:
    for state in payload["per_state"]:
        assert 0.0 <= state["sub_state_anchored_share_of_demand"] <= 1.0
        assert 0.0 <= state["mean_uncertainty"] <= 1.0


def test_every_preflight_assumption_is_addressed(payload: dict[str, Any]) -> None:
    preflight = payload["preflight"]
    assert preflight["A-2.1_site_clustering"]["assumption"] == "A-2.1"
    assert preflight["A-2.2_rung_two_masked_power"]["triggered"] is False
    assert preflight["A-2.3_centroid_resolution"]["assumption"] == "A-2.3"
    assert preflight["A-3.4_state_total_rounding"]
    assert preflight["A-3.5_no_categorical_urban_rural"][
        "categorical_urban_rural_fields"] == []


def test_state_cells_conserve_demand_and_provenance() -> None:
    """The helper asserts both internally; this proves it is actually called."""
    from pipeline.model.build_demand import build_surface
    from pipeline.model.observed import load_all
    from pipeline.model.panel import build_panels, load_area_tables
    from pipeline.model.run_phase3 import allocation_penalty, constraint_totals

    tables = load_area_tables(states=("50", "53"))
    observations = load_all(known_tracts=sorted(tables["tracts"].rows))
    penalty, _ = allocation_penalty()
    surface = build_surface(
        tables["tracts"], build_panels(observations, tables), observations,
        constraint_totals(observations), penalty, "poisson_glm",
        source_statuses=("confirmed",) * 8, bootstrap_replicates=2)
    cells = state_cells(surface.estimates, "53", {})
    assert len(cells) > 500
    assert all(c.evidence_grain_share for c in cells)


def test_the_artifact_is_written_where_asked(tmp_path: Path) -> None:
    out = tmp_path / "siting.json"
    assert main(["--out", str(out), "--states", "50", "53",
                 "--frontier-states", "53"]) == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["phase"] == 4
    assert written["per_state"]


def test_a_frontier_state_outside_the_loaded_set_is_skipped() -> None:
    """Asking for a frontier over a state whose tracts were not loaded must not crash."""
    result = run(states=("50",), frontier_states=("53", "50"))
    assert [s["state_fips"] for s in result["per_state"]] == ["50"]


def test_a_state_with_no_demand_reports_zero_rather_than_dividing_by_zero() -> None:
    from pipeline.model.run_phase4 import _weighted
    from tests.unit.test_siting import hexcell

    assert _weighted([], lambda c: c.uncertainty_score) == 0.0
    empty = [hexcell(0, 0.0), hexcell(1, 0.0)]
    assert _weighted(empty, lambda c: c.uncertainty_score) == 0.0
    real = [hexcell(0, 100.0), hexcell(1, 300.0)]
    assert _weighted(real, lambda c: c.demand_bev) == pytest.approx(250.0)
