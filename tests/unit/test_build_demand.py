"""The national surface: exact reconciliation, honest evidence grains, and tiers."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from pipeline.model.build_demand import (
    COUNTY_ANCHORED,
    NATIVE_TRACT,
    STATE_TOTAL_ONLY,
    build_surface,
    county_constraint_states,
    estimator_by_name,
)
from pipeline.model.observed import ObservedCount, StateObservations, StateTotal
from pipeline.model.panel import (
    AreaTable,
    StatePanel,
    build_area_table,
    build_state_panel,
)
from pipeline.model.uncertainty import AllocationPenalty, complexity_multipliers
from pipeline.spatial.geography import SourceGeography
from pipeline.validation.scope import ExclusionLedger

# Two states: 53 (Washington, tract-observed) and 30 (Montana, county-observed).
WA_TRACTS = ["53033000100", "53033000200", "53061000100"]
MT_TRACTS = ["30049000100", "30049000200", "30031000100"]
OTHER_TRACTS = ["06037000100", "06037000200"]
ALL_TRACTS = WA_TRACTS + MT_TRACTS + OTHER_TRACTS


def acs_row(geoid: str, households: int) -> dict[str, str]:
    row = {"geoid": geoid, "B25003_001E": str(households),
           "B01003_001E": str(households * 2)}
    for name in ("B19013_001E", "B19001_001E", "B25003_002E", "B25024_001E",
                 "B25024_002E", "B25024_003E", "B25044_001E", "B08301_001E",
                 "B08303_001E", "B15003_001E"):
        row.setdefault(name, str(50 + len(geoid) + int(geoid[-2:])))
    return row


def tract_table() -> AreaTable:
    return build_area_table(
        [acs_row(g, 100 + i * 10) for i, g in enumerate(ALL_TRACTS)],
        "tracts", dict.fromkeys(ALL_TRACTS, 4.0),
    )


def observations() -> dict[str, StateObservations]:
    wa = tuple(ObservedCount("WA", SourceGeography.TRACT, g, 10 + i * 5, 0)
               for i, g in enumerate(WA_TRACTS))
    mt = (ObservedCount("MT", SourceGeography.COUNTY, "30049", 40, 0),
          ObservedCount("MT", SourceGeography.COUNTY, "30031", 25, 0))
    return {
        "WA": StateObservations("WA", SourceGeography.TRACT, "current snapshot", wa,
                                ExclusionLedger(45, 45, {}, {})),
        "MT": StateObservations("MT", SourceGeography.COUNTY, "DMV Snapshot (1/1/2026)",
                                mt, ExclusionLedger(65, 65, {}, {})),
    }


def panels(tables: dict[str, AreaTable]) -> dict[str, StatePanel]:
    county = build_area_table(
        [acs_row("30049", 500), acs_row("30031", 300)], "county",
        {"30049": 90.0, "30031": 70.0},
    )
    tables["county"] = county
    return {
        "WA": build_state_panel(observations()["WA"], tables),
        "MT": build_state_panel(observations()["MT"], tables),
    }


def penalty() -> AllocationPenalty:
    return AllocationPenalty(
        statewide_tvd={"native_tract": 0.0, "zip_anchored": 0.1621,
                       "county_anchored": 0.2367, "state_total_only": 0.3049},
        complexity_multiplier=complexity_multipliers({"1": 0.0046}, 0.1794),
    )


def state_totals() -> dict[str, StateTotal]:
    return {
        "53": StateTotal("53", "Washington", "2025", 45, 0),
        "30": StateTotal("30", "Montana", "2025", 65, 0),
        "06": StateTotal("06", "California", "2025", 1000, 0),
    }


def surface(**kwargs: object):  # type: ignore[no-untyped-def]
    tables = {"tracts": tract_table()}
    built = panels(tables)
    return build_surface(
        tables["tracts"], built, observations(), state_totals(), penalty(),
        kwargs.pop("estimator", "baseline_household_share"),  # type: ignore[arg-type]
        source_statuses=kwargs.pop("source_statuses", ("confirmed",)),  # type: ignore[arg-type]
        bootstrap_replicates=3, **kwargs,
    )


# --- helpers ------------------------------------------------------------------------

def test_an_estimator_is_looked_up_by_its_published_name() -> None:
    assert estimator_by_name("poisson_glm").name == "poisson_glm"
    with pytest.raises(ValueError, match="no candidate estimator named"):
        estimator_by_name("invented")


def test_only_county_observed_states_contribute_county_constraints() -> None:
    counties = county_constraint_states(observations())
    assert set(counties) == {"MT"}
    assert counties["MT"] == {"30049": 40.0, "30031": 25.0}


# --- the surface --------------------------------------------------------------------

def test_every_tract_is_estimated_and_reconciled_exactly() -> None:
    built = surface()
    assert len(built.estimates) == len(ALL_TRACTS)
    assert built.reconciliation.max_residual < 1e-6
    assert built.reconciliation.unconstrained == ()
    by_state: dict[str, float] = {}
    for row in built.estimates:
        if row.evidence_grain != NATIVE_TRACT:
            by_state[row.state_fips] = by_state.get(row.state_fips, 0.0) + row.estimate
    assert by_state["06"] == pytest.approx(1000.0)


def test_county_totals_bind_where_they_exist_and_state_totals_elsewhere() -> None:
    built = surface()
    grains = {row.geoid: row.evidence_grain for row in built.estimates}
    assert grains["30049000100"] == COUNTY_ANCHORED
    assert grains["06037000100"] == STATE_TOTAL_ONLY
    montana = [r for r in built.estimates if r.constraint_name == "30049"]
    assert sum(r.estimate for r in montana) == pytest.approx(40.0)


def test_an_observed_tract_publishes_the_observation_not_an_estimate() -> None:
    built = surface()
    observed_row = next(r for r in built.estimates if r.geoid == "53033000100")
    assert observed_row.evidence_grain == NATIVE_TRACT
    assert observed_row.estimate_method == "directly_observed"
    assert observed_row.estimate == 10.0


def test_no_tract_is_ever_labelled_zip_anchored() -> None:
    """Phase 3 does not allocate ZIP counts onto tracts, so no tract value rests on a
    ZIP total, and claiming one would overstate the evidence."""
    built = surface()
    assert all(r.evidence_grain != "zip_anchored" for r in built.estimates)


def test_no_modelled_tract_claims_to_be_directly_observed() -> None:
    built = surface()
    for row in built.estimates:
        if row.evidence_grain != NATIVE_TRACT:
            assert row.estimate_method in {"modeled", "modeled_high_uncertainty"}


def test_every_estimate_carries_its_uncertainty_and_tier() -> None:
    """D7: no point estimate ships without uncertainty."""
    built = surface()
    for row in built.estimates:
        assert 0.0 <= row.uncertainty_score <= 1.0
        assert row.confidence_tier in {"A", "B", "C"}
        assert len(row.uncertainty_components) == 5
        payload = row.to_dict()
        assert payload["uncertainty_score"] == pytest.approx(row.uncertainty_score, abs=5e-7)
        assert payload["evidence_grain"] == row.evidence_grain


def test_a_high_uncertainty_modelled_tract_is_labelled_as_such() -> None:
    built = surface()
    tier_c = [r for r in built.estimates if r.confidence_tier == "C"]
    assert all(r.estimate_method == "modeled_high_uncertainty" for r in tier_c)


def test_the_summary_never_claims_the_weights_are_calibrated() -> None:
    summary = surface().summary()
    assert summary["weights_are_calibrated"] is False
    assert set(summary["weight_sensitivity"]) == {
        "prediction_interval", "out_of_distribution", "reconciliation_movement",
        "allocation_error", "source_degradation",
    }
    assert summary["tracts"] == len(ALL_TRACTS)
    assert summary["reconciliation_method"] == "proportional"


def test_a_degraded_source_raises_every_tract_s_uncertainty() -> None:
    clean = surface(source_statuses=("confirmed", "confirmed"))
    degraded = surface(source_statuses=("confirmed", "degraded"))
    assert (degraded.estimates[0].uncertainty_components["source_degradation"]
            > clean.estimates[0].uncertainty_components["source_degradation"])


def test_the_final_production_fit_includes_washington() -> None:
    """Washington is the only tract-native source. Barring it from the independent
    validation aggregate says nothing about the information its observations carry, so
    the production fit uses it (pre-registration amendment W7, 2026-08-29)."""
    tables = {"tracts": tract_table()}
    built = panels(tables)
    assert built["WA"].is_independent is False
    assert built["WA"].is_trainable is True
    surface_with_wa = build_surface(
        tables["tracts"], built, observations(), state_totals(), penalty(),
        "baseline_household_share", bootstrap_replicates=3)
    assert "WA" in surface_with_wa.training_states


def test_a_surface_with_no_trainable_rows_at_all_is_refused() -> None:
    tables = {"tracts": tract_table()}
    built = panels(tables)
    barred = {state: replace(panel, is_trainable=False)
              for state, panel in built.items()}
    with pytest.raises(ValueError, match="no training rows"):
        build_surface(tables["tracts"], barred, observations(), state_totals(),
                      penalty(), "baseline_household_share",
                      bootstrap_replicates=3)


def test_a_tract_whose_state_has_no_published_total_is_left_unconstrained() -> None:
    tables = {"tracts": tract_table()}
    built = panels(tables)
    partial = {k: v for k, v in state_totals().items() if k != "06"}
    result = build_surface(tables["tracts"], built, observations(), partial,
                           penalty(), "baseline_household_share",
                           bootstrap_replicates=3)
    assert len(result.reconciliation.unconstrained) == len(OTHER_TRACTS)
    california = [r for r in result.estimates if r.state_fips == "06"]
    assert all(r.constraint_vintage is None for r in california)


def test_the_evidence_artifact_round_trips_as_json(tmp_path: Path) -> None:
    payload = [row.to_dict() for row in surface().estimates]
    path = tmp_path / "surface.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert len(json.loads(path.read_text(encoding="utf-8"))) == len(ALL_TRACTS)
