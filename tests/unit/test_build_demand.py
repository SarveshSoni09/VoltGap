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
from pipeline.model.observed import (
    STATEWIDE_VEHICLE_REGISTRY,
    GeographyResolution,
    ObservedCount,
    StateObservations,
    StateTotal,
)
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
# In Washington's ACS geography but absent from its registry: a tract the enumeration
# does not name, which therefore holds no registered BEVs.
WA_UNOBSERVED = ["53061000200"]
MT_TRACTS = ["30049000100", "30049000200", "30031000100"]
OTHER_TRACTS = ["06037000100", "06037000200"]
ALL_TRACTS = WA_TRACTS + WA_UNOBSERVED + MT_TRACTS + OTHER_TRACTS


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
        "WA": StateObservations(
            "WA", SourceGeography.TRACT, "current snapshot", wa,
            ExclusionLedger(45, 45, {}, {}),
            publisher_scope=STATEWIDE_VEHICLE_REGISTRY,
            resolution=GeographyResolution(
                total_records=45, in_jurisdiction_records=45,
                in_jurisdiction_placed=45, out_of_jurisdiction_records=0,
                invalid_tract_format=0, tract_not_in_jurisdiction_geography=0)),
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
    # Their raw values are real output resting on NO observed total, so the accounting
    # names them rather than absorbing them.
    result.accounting.assert_balanced()
    assert result.accounting.unconstrained_sum == pytest.approx(
        sum(r.estimate for r in california))


def test_the_evidence_artifact_round_trips_as_json(tmp_path: Path) -> None:
    payload = [row.to_dict() for row in surface().estimates]
    path = tmp_path / "surface.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert len(json.loads(path.read_text(encoding="utf-8"))) == len(ALL_TRACTS)


# --- partial county coverage must not double count (impact I-15) ---------------------

def test_partial_county_coverage_constrains_the_rest_to_the_residual() -> None:
    """Montana publishes 51 of 56 counties and Virginia 129 of 133. Reconciling the
    leftover tracts to the FULL state total counted both states roughly twice: Montana
    summed to 13,673 against a 6,900 total, Virginia to 266,876 against 134,900."""
    from pipeline.model.build_demand import _constraint_plan
    from pipeline.model.demand import ModelRow

    rows = [
        ModelRow("MT", "tracts", "30049000100", 100.0, 200.0, {}),  # observed county
        ModelRow("MT", "tracts", "30031000100", 100.0, 200.0, {}),  # observed county
        ModelRow("MT", "tracts", "30099000100", 100.0, 200.0, {}),  # NOT observed
    ]
    counties = {"MT": {"30049": 40.0, "30031": 25.0}}
    totals = {"30": StateTotal("30", "Montana", "2025", 100, 0)}
    grains, group_of, plan, vintages = _constraint_plan(
        rows, counties, totals, {}, {})
    assert group_of == ["30049", "30031", "30"]
    assert plan["30049"] == 40.0 and plan["30031"] == 25.0
    # The residual, not the full 100: the observed counties already claim 65.
    assert plan["30"] == 35.0
    assert sum(plan.values()) == 100.0
    assert grains == [COUNTY_ANCHORED, COUNTY_ANCHORED, STATE_TOTAL_ONLY]
    assert "residual after 2 observed counties" in str(vintages["30"])


def test_complete_county_coverage_creates_no_state_group() -> None:
    """Tennessee publishes all 95 of its counties, so nothing falls through."""
    from pipeline.model.build_demand import _constraint_plan
    from pipeline.model.demand import ModelRow

    rows = [ModelRow("TN", "tracts", "47001000100", 100.0, 200.0, {})]
    grains, group_of, plan, _ = _constraint_plan(
        rows, {"TN": {"47001": 40.0}},
        {"47": StateTotal("47", "Tennessee", "2025", 100, 0)}, {}, {})
    assert group_of == ["47001"]
    assert set(plan) == {"47001"}
    assert grains == [COUNTY_ANCHORED]


def test_county_totals_exceeding_the_state_total_are_refused_not_clamped() -> None:
    """A negative residual would put negative vehicles in the remaining tracts."""
    from pipeline.model.build_demand import _constraint_plan
    from pipeline.model.demand import ModelRow

    rows = [
        ModelRow("MT", "tracts", "30049000100", 100.0, 200.0, {}),
        ModelRow("MT", "tracts", "30099000100", 100.0, 200.0, {}),
    ]
    with pytest.raises(ValueError, match="exceeds"):
        _constraint_plan(rows, {"MT": {"30049": 500.0}},
                         {"30": StateTotal("30", "Montana", "2025", 100, 0)}, {}, {})


def payload_zero_substitution(accounting: object) -> bool:
    from pipeline.model.build_demand import ConstraintAccounting

    assert isinstance(accounting, ConstraintAccounting)
    return accounting.to_dict()["observed_substitution_delta"] == 0.0


def test_the_national_accounting_balances_with_no_substitution_term() -> None:
    built = surface()
    accounting = built.accounting
    accounting.assert_balanced()
    assert abs(accounting.imbalance) < 1e-6
    # Washington's observed tracts override its constraint by design.
    # There is no substitution term any more: observed values are constraints.
    assert payload_zero_substitution(accounting)
    payload = accounting.to_dict()
    assert payload["balances"] is True
    assert payload["constraint_groups"] > 0


def test_an_unbalanced_accounting_raises_rather_than_publishing() -> None:
    from pipeline.model.build_demand import ConstraintAccounting

    broken = ConstraintAccounting(national_published=100.0, constraint_sum=90.0,
                                  unconstrained_sum=0.0, per_group={"a": 90.0},
                                  per_jurisdiction={})
    with pytest.raises(ValueError, match="does not balance"):
        broken.assert_balanced()


# --- the exact-reconciliation contract, after precedence resolution -------------------

def test_a_native_registry_state_reconciles_to_its_own_observed_total() -> None:
    """Washington's observed values are CONSTRAINTS now, not a post-hoc overwrite, so
    its surface still equals the total it reconciles to."""
    built = surface()
    wa = [row for row in built.estimates if row.state_fips == "53"]
    operative = built.operative_constraints["53"]
    assert operative.chosen.source.value == "native_tract_registry"
    assert sum(row.estimate for row in wa) == pytest.approx(operative.total, abs=1e-6)
    # Each observed tract carries exactly its observation.
    for row in wa:
        if row.estimate_method == "directly_observed":
            assert row.evidence_grain == NATIVE_TRACT


def test_a_tract_the_registry_does_not_name_is_constrained_to_zero() -> None:
    """A registry enumerates every registered vehicle, so a tract it omits holds none."""
    built = surface()
    unnamed = next(r for r in built.estimates if r.geoid == WA_UNOBSERVED[0])
    assert unnamed.estimate == pytest.approx(0.0, abs=1e-9)
    assert unnamed.evidence_grain == NATIVE_TRACT
    # And Washington still sums to its own observed total, not to that total plus a
    # stray modelled remainder.
    wa = sum(r.estimate for r in built.estimates if r.state_fips == "53")
    assert wa == pytest.approx(built.operative_constraints["53"].total, abs=1e-6)


def test_there_is_no_substitution_term_left_in_the_accounting() -> None:
    """A surface reconciled to one set of totals and then altered so it no longer sums
    to them breaks the exact-reconciliation contract."""
    payload = surface().accounting.to_dict()
    assert payload["observed_substitution_delta"] == 0.0
    assert payload["balances"] is True


def test_every_jurisdiction_balances_individually_not_just_nationally() -> None:
    """A national identity can hold while states are wrong in offsetting directions."""
    built = surface()
    published: dict[str, float] = {}
    for row in built.estimates:
        published[row.state_fips] = published.get(row.state_fips, 0.0) + row.estimate
    built.accounting.assert_every_jurisdiction_balances(published)
    for fips, expected in built.accounting.per_jurisdiction.items():
        assert published[fips] == pytest.approx(expected, abs=1e-6)


def test_a_poisoned_post_reconciliation_substitution_is_caught() -> None:
    """The negative test: if anything ever alters the surface after reconciliation, the
    per-jurisdiction identity must fail rather than the number quietly shipping."""
    built = surface()
    published: dict[str, float] = {}
    for row in built.estimates:
        published[row.state_fips] = published.get(row.state_fips, 0.0) + row.estimate
    poisoned = dict(published)
    poisoned["53"] = poisoned["53"] + 611.0328
    with pytest.raises(ValueError, match="do not sum to their operative"):
        built.accounting.assert_every_jurisdiction_balances(poisoned)


def test_superseded_constraints_are_preserved_but_never_summed() -> None:
    built = surface()
    operative = built.operative_constraints
    superseded_total = sum(c.total for op in operative.values() for c in op.superseded)
    assert superseded_total > 0, "Washington's state total should be recorded"
    # The accounting sums only the chosen constraints.
    assert built.accounting.constraint_sum == pytest.approx(
        sum(op.total for op in operative.values()
            if op.state_fips in {r.state_fips for r in built.estimates}), abs=1e-6)


def test_every_jurisdiction_has_exactly_one_operative_constraint() -> None:
    built = surface()
    states = {row.state_fips for row in built.estimates}
    for state in states:
        operative = built.operative_constraints[state]
        assert operative.state_fips == state
        assert operative.chosen.source.value in {
            "native_tract_registry", "county_observation", "state_registration_total"}
        assert operative.reason


def test_a_completed_zero_is_distinguishable_from_a_missing_value() -> None:
    """The distinction the external review required: a zero DERIVED FROM an exhaustive
    registry is not the same thing as a missing or unknown value, and the published row
    must say which it is."""
    from pipeline.model.build_demand import (
        PROVENANCE_MODELLED,
        PROVENANCE_OBSERVED_COUNT,
        PROVENANCE_ZERO_BY_ABSENCE,
    )

    built = surface()
    absent = next(r for r in built.estimates if r.geoid == WA_UNOBSERVED[0])
    assert absent.value_provenance == PROVENANCE_ZERO_BY_ABSENCE
    assert absent.estimate == pytest.approx(0.0, abs=1e-9)
    # It is NOT claimed to be directly observed: no source row named this tract.
    assert absent.estimate_method != "directly_observed"
    # Its evidence grain is still native: the registry covers it and reports nothing.
    assert absent.evidence_grain == NATIVE_TRACT
    assert absent.to_dict()["value_provenance"] == PROVENANCE_ZERO_BY_ABSENCE

    named = next(r for r in built.estimates if r.geoid == WA_TRACTS[0])
    assert named.value_provenance == PROVENANCE_OBSERVED_COUNT
    assert named.estimate_method == "directly_observed"

    modelled = next(r for r in built.estimates if r.state_fips == "06")
    assert modelled.value_provenance == PROVENANCE_MODELLED


def test_without_the_zero_completion_licence_absent_tracts_are_not_zeroed() -> None:
    """One unplaced in-jurisdiction record and the licence is refused, because that
    record could belong to any unnamed tract."""
    from dataclasses import replace as dc_replace

    from pipeline.model.observed import GeographyResolution

    tables = {"tracts": tract_table()}
    built = panels(tables)
    obs = observations()
    wa = obs["WA"]
    assert wa.resolution is not None
    obs["WA"] = dc_replace(wa, resolution=GeographyResolution(
        total_records=wa.resolution.total_records + 1,
        in_jurisdiction_records=wa.resolution.in_jurisdiction_records + 1,
        in_jurisdiction_placed=wa.resolution.in_jurisdiction_placed,
        out_of_jurisdiction_records=wa.resolution.out_of_jurisdiction_records,
        invalid_tract_format=1, tract_not_in_jurisdiction_geography=0))
    result = build_surface(tables["tracts"], built, obs, state_totals(), penalty(),
                           "baseline_household_share", bootstrap_replicates=3)
    # The native source no longer supersedes at all: it falls back to the external
    # total for the whole jurisdiction rather than inventing a residual for the tracts
    # it could not name.
    operative = result.operative_constraints["53"]
    assert operative.chosen.source.value == "state_registration_total"
    assert operative.licenses_zero_completion is False
    for row in result.estimates:
        if row.state_fips == "53":
            assert row.value_provenance != "native_registry_zero_by_absence"
            assert row.evidence_grain == "state_total_only"
