"""Phase 4 acceptance criteria, each mapped to an executable check.

Quoted from CLAUDE.md §15.5:

> Frontier computed per state with solve status and optimality gap recorded per point.
> Reverse-objective check run. The browser algorithm is defined exactly, its problem class
> stated, and either a formal approximation guarantee is cited with its theorem and its
> assumptions verified to hold, **or no bound is claimed anywhere** (§7.8). **Empirical
> optimality gaps against offline CBC reported** on controlled fixtures and on
> representative real state problems. Greedy solves a state in <= 2 s. Candidate filtering
> verified against constraint definitions, **with no mandatory national
> substation-proximity filter** (§7.9).

These read the published evidence artifact, so the criteria are checked against the
numbers that ship.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from pipeline.config.settings import PATHS
from pipeline.model.hexes import HexSupply
from pipeline.model.run_phase4 import GREEDY_BUDGET_SECONDS
from pipeline.model.siting_preflight import assert_no_categorical_urban_rural

ARTIFACT = PATHS.evidence / "P4-1_siting.json"


@pytest.fixture(scope="module")
def evidence() -> dict[str, Any]:
    assert ARTIFACT.exists(), (
        f"{ARTIFACT} is missing. Reproduce it with "
        "`python -m pipeline.model.run_phase4`."
    )
    payload: dict[str, Any] = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    return payload


# --- P4-A: the frontier ---------------------------------------------------------------

def test_p4_a_the_frontier_is_computed_per_state_and_labelled(
    evidence: dict[str, Any],
) -> None:
    assert "PER STATE" in evidence["frontier_scope"]
    assert len(evidence["per_state"]) == 6
    states = {p["state"] for p in evidence["frontier"]}
    assert len(states) == 6


def test_p4_a_every_frontier_point_records_status_and_gap(
    evidence: dict[str, Any],
) -> None:
    for point in evidence["frontier"]:
        assert point["cbc_status"] in {"optimal", "feasible_time_limit", "infeasible",
                                   "not_solved"}
        assert "cbc_optimality_gap" in point
        assert "solve_seconds" in point
        if point["cbc_status"] == "optimal":
            assert point["cbc_optimality_gap"] == 0.0


def test_p4_a_the_reverse_objective_check_was_run(evidence: dict[str, Any]) -> None:
    senses = {p["objective_sense"] for p in evidence["frontier"]}
    assert senses == {"maximise_demand_subject_to_equity",
                      "maximise_equity_subject_to_demand"}
    for state in {p["state"] for p in evidence["frontier"]}:
        for sense in senses:
            assert any(p["state"] == state and p["objective_sense"] == sense
                       for p in evidence["frontier"]), (state, sense)


def test_p4_a_the_frontier_shows_a_real_tradeoff_somewhere(
    evidence: dict[str, Any],
) -> None:
    """If demand never falls as the equity floor rises, the constraint never bound and
    the frontier would be a single point wearing eight labels."""
    forward = [p for p in evidence["frontier"]
               if p["objective_sense"] == "maximise_demand_subject_to_equity"]
    by_state: dict[str, list[dict[str, Any]]] = {}
    for point in forward:
        by_state.setdefault(point["state"], []).append(point)
    assert any(
        min(p["demand_covered"] for p in points) < max(p["demand_covered"] for p in points)
        for points in by_state.values()
    ), "no state showed any demand/equity tradeoff at all"


# --- P4-B: no approximation bound -----------------------------------------------------

# Hyphen-like characters written as escapes so this file contains no
# ambiguous Unicode of its own, matching the D3 copy lint's own approach.
BOUND = re.compile(r"\(1\s*[-\u2212\u2013]\s*1/e\)")


def test_p4_b_no_approximation_bound_is_claimed_in_the_artifact(
    evidence: dict[str, Any],
) -> None:
    assert evidence["approximation_bound_claimed"] is None
    for state in evidence["per_state"]:
        assert state["greedy"]["approximation_bound_claimed"] is None
    assert not BOUND.search(json.dumps(evidence))


def test_p4_b_the_problem_class_and_the_reason_are_stated(
    evidence: dict[str, Any],
) -> None:
    note = evidence["approximation_bound_note"]
    assert "cardinality-constrained maximum coverage" in note
    assert "does not carry over" in note


def test_p4_b_the_greedy_algorithm_is_defined_exactly_in_code() -> None:
    """§7.8 task 1: define the exact browser algorithm."""
    from pipeline.model.siting import greedy_select

    doc = greedy_select.__doc__ or ""
    for step in ("marginal gain", "budget", "deterministic"):
        assert step in doc, step
    assert "no approximation bound" in doc


# --- P4-C: measured greedy shortfall against optimal CBC ------------------------------

def test_p4_c_gaps_are_reported_on_representative_real_state_problems(
    evidence: dict[str, Any],
) -> None:
    gaps = evidence["greedy_objective_shortfall_vs_optimal_cbc"]
    assert len(gaps) >= 12
    assert len({g["label"] for g in gaps}) == 6
    for gap in gaps:
        assert gap["cbc_status"] == "optimal", gap
        assert gap["greedy_objective"] <= gap["optimal_cbc_objective"] + 1e-6
        assert 0.0 <= gap["greedy_objective_shortfall_vs_optimal_cbc"] < 0.25


def test_p4_c_gaps_are_reported_on_controlled_fixtures_too() -> None:
    """The named fixture test in the unit suite is the controlled half of §7.8 task 6."""
    from tests.unit.test_siting import (
        test_the_greedy_shortfall_is_measured_against_an_exact_solve,
    )

    test_the_greedy_shortfall_is_measured_against_an_exact_solve()


# --- P4-D: the two-second budget ------------------------------------------------------

def test_p4_d_greedy_solves_a_state_within_two_seconds(
    evidence: dict[str, Any],
) -> None:
    assert evidence["greedy_budget_seconds"] == GREEDY_BUDGET_SECONDS
    assert evidence["greedy_within_budget"] is True
    for state in evidence["per_state"]:
        assert state["greedy"]["seconds"] <= GREEDY_BUDGET_SECONDS, state["state"]


# --- P4-E: candidate filtering --------------------------------------------------------

def test_p4_e_there_is_no_mandatory_substation_filter(
    evidence: dict[str, Any],
) -> None:
    """§7.9: Core siting must function without a national substation dataset."""
    assert "NONE" in evidence["substation_filter"]
    for state in evidence["per_state"]:
        candidates = state["candidate_set"]
        assert candidates["no_mandatory_substation_filter"] is True
        # The road filter §7.8 requires IS present. What must not appear is a
        # substation or interconnection exclusion, which §7.9 forbids as a Core filter.
        assert set(candidates["excluded_by_reason"]) <= {
            "uninhabited", "already_saturated",
            "beyond_primary_secondary_road_network"}
        assert not any("substation" in r or "interconnect" in r
                       for r in candidates["excluded_by_reason"])


def test_p4_e_the_road_proximity_filter_actually_ran_in_every_state(
    evidence: dict[str, Any],
) -> None:
    """§7.8 requires it. Phase 4 first shipped without it and substituted a resident
    population filter, which is not a road filter. This asserts it is back and that it
    removed cells rather than passing everything through."""
    for state in evidence["per_state"]:
        candidates = state["candidate_set"]
        assert candidates["cells_admitted_without_road_filter"] == 0, state["state"]
        road = candidates["road_network_filter"]
        assert isinstance(road, dict), state["state"]
        assert road["threshold_km"] == 5.0
        assert road["road_vertices"] > 0
        assert state["candidates_removed_by_road_filter"] > 0, state["state"]
        assert (state["candidates_before_road_filter"]
                - state["candidates_after_road_filter"]
                == state["candidates_removed_by_road_filter"])
        assert state["road_source"]["road_classes_included"] == ["S1100", "S1200"]
        assert state["road_source"]["vintage"] == "2024"


def test_p4_e_transmission_is_never_an_interconnection_constraint(
    evidence: dict[str, Any],
) -> None:
    """D6."""
    assert "never an interconnection" in evidence["transmission_language"]


def test_p4_e_every_state_retains_candidates_after_filtering(
    evidence: dict[str, Any],
) -> None:
    for state in evidence["per_state"]:
        assert state["candidate_set"]["candidates"] > 0, state["state"]


# --- P4-F: the prerequisites ----------------------------------------------------------

def test_p4_f_a21_site_clustering_was_measured(evidence: dict[str, Any]) -> None:
    """A-2.1 must be MEASURED, not argued from the ratio of cluster diameter to cell
    edge. That ratio establishes clusters are small relative to cells; it establishes
    nothing about whether a cluster straddling a boundary flips a saturation
    classification. External review rejected the geometric argument, correctly."""
    result = evidence["preflight"]["A-2.1_site_clustering"]
    assert "Measured, not argued from cell geometry" in result["method"]
    assert "diameter_as_share_of_cell_edge" not in result

    states = result["per_state"]
    assert len(states) == 6
    for state in states:
        conditions = {c["condition"]: c for c in state["conditions"]}
        assert set(conditions) == {
            "shipped_no_clustering", "dbscan_eps_50m", "dbscan_eps_200m"}
        # The baseline is compared against itself, so it must show no difference.
        baseline = conditions["shipped_no_clustering"]
        assert baseline["material"] is False
        assert baseline["candidate_set_jaccard"] == 1.0
        for name in ("dbscan_eps_50m", "dbscan_eps_200m"):
            measured = conditions[name]
            # Whatever the verdict, every portfolio at every budget must be reported.
            assert set(measured["portfolio_overlap_by_budget"]) == {"5", "20", "50"}
            assert measured["material"] in (True, False)


def test_p4_f_a21_the_shipped_clustering_configuration_changes_nothing(
    evidence: dict[str, Any],
) -> None:
    """The Phase 1 site-resolution configuration (eps = 50 m) is the one that would be
    used if clustering were adopted. It is immaterial in all six states."""
    for state in evidence["preflight"]["A-2.1_site_clustering"]["per_state"]:
        measured = {c["condition"]: c for c in state["conditions"]}["dbscan_eps_50m"]
        assert measured["material"] is False, state["state"]
        assert measured["candidate_set_jaccard"] == 1.0
        assert measured["cells_whose_saturation_classification_changes"] == 0


def test_p4_f_a21_no_portfolio_changes_under_any_clustering_condition(
    evidence: dict[str, Any],
) -> None:
    """The consequential question. A candidate-set difference that never reaches a
    portfolio does not change a siting recommendation; one that does, would."""
    for state in evidence["preflight"]["A-2.1_site_clustering"]["per_state"]:
        for measured in state["conditions"]:
            for budget, overlap in measured["portfolio_overlap_by_budget"].items():
                assert overlap == 1.0, (state["state"], measured["condition"], budget)
            assert measured["demand_objective_delta"] == 0.0
            assert measured["equity_objective_delta"] == 0.0


def test_p4_f_a22_is_not_triggered_and_cannot_be_violated(
    evidence: dict[str, Any],
) -> None:
    """Phase 4 reads port COUNTS; there is no kW field on the siting supply record."""
    result = evidence["preflight"]["A-2.2_rung_two_masked_power"]
    assert result["triggered"] is False
    assert not hasattr(HexSupply(), "capacity_kw")
    assert "capacity_kw" not in json.dumps(evidence)


def test_p4_f_a23_centroid_resolution_was_benchmarked(
    evidence: dict[str, Any],
) -> None:
    result = evidence["preflight"]["A-2.3_centroid_resolution"]
    assert result["block_level_benchmark_available"] is False
    assert result["share_of_demand_placed_differently_by_tract_centroid"] > 0.0


def test_p4_f_a34_rounding_does_not_reorder_the_portfolio(
    evidence: dict[str, Any],
) -> None:
    for result in evidence["preflight"]["A-3.4_state_total_rounding"]:
        assert result["rounding_half_width_vehicles"] == 50.0
        assert result["identical_portfolio"] is True, result["state"]


def test_p4_f_a35_no_categorical_urban_rural_anywhere(
    evidence: dict[str, Any],
) -> None:
    assert evidence["preflight"]["A-3.5_no_categorical_urban_rural"][
        "categorical_urban_rural_fields"] == []
    for state in evidence["per_state"]:
        assert_no_categorical_urban_rural(state)


# --- P4-G: provenance survives --------------------------------------------------------

def test_p4_g_demand_uncertainty_and_provenance_reach_the_candidate_layer(
    evidence: dict[str, Any],
) -> None:
    """The explicit external-review requirement: Phase 3's uncertainty and evidence
    provenance must not disappear at the H3 layer."""
    for state in evidence["per_state"]:
        assert 0.0 <= state["sub_state_anchored_share_of_demand"] <= 1.0
        assert 0.0 < state["mean_uncertainty"] < 1.0, state["state"]


def test_p4_g_the_budget_is_expressed_in_sites_not_fabricated_dollars(
    evidence: dict[str, Any],
) -> None:
    assert "SITES, not dollars" in evidence["budget_units"]
    assert "no cost model exists" in evidence["budget_units"]
