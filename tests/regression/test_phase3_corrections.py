"""External-review correction pass — the fourteen required regression checks.

Each check below is one of the fourteen the external review named. They run offline
against cached responses and the published evidence artifact, so the corrections are
verified against the artifacts that ship rather than against a fresh in-test computation.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from pipeline.config.settings import PATHS
from pipeline.discovery.cache import ReplayFetcher
from pipeline.model.ablation import SUPPLY_FEATURE_NAMES
from pipeline.model.features import FEATURE_NAMES, assert_primary_feature_set_is_clean
from pipeline.model.observed import STATE_FIPS
from pipeline.model.panel import (
    NON_INDEPENDENT_STATES,
    NON_TRAINABLE_STATES,
)
from pipeline.sources.census_acs import (
    ACS_VARIABLES,
    ACS_YEAR,
    COUNTY,
    HISTORICAL_ACS_YEARS,
    TRACT,
    ZCTA,
    AcsSource,
)

ARTIFACT = PATHS.evidence / "P3-2_demand_model.json"


@pytest.fixture(scope="module")
def evidence() -> dict[str, Any]:
    assert ARTIFACT.exists(), (
        f"{ARTIFACT} is missing. Reproduce it with "
        "`python -m pipeline.model.run_phase3`."
    )
    payload: dict[str, Any] = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    return payload


def replay() -> ReplayFetcher:
    return ReplayFetcher(PATHS.cache)


# --- 1. ACS 2024 contains every required variable -----------------------------------

def test_check_01_acs_2024_serves_every_variable_phase_3_consumes() -> None:
    """Asserted against the cached 2024 responses: every requested variable came back."""
    assert ACS_YEAR == 2024
    table = AcsSource(TRACT, "44").load(replay())
    returned = set(table.columns)
    missing = sorted(v for v in ACS_VARIABLES if v not in returned)
    assert missing == [], f"ACS {ACS_YEAR} did not return {missing}"
    assert len(ACS_VARIABLES) == 78


# --- 2. ACS 2024 retrieval works at all three grains --------------------------------

def test_check_02_acs_2024_retrieves_at_tract_zcta_and_county() -> None:
    fetcher = replay()
    tract = AcsSource(TRACT, "44").load(fetcher)
    zcta = AcsSource(ZCTA).load(fetcher)
    county = AcsSource(COUNTY).load(fetcher)
    assert len(tract.rows) == 250
    assert len(zcta.rows) == 33772
    assert len(county.rows) == 3222
    for table in (tract, zcta, county):
        assert table.vintage.vintage == f"ACS {ACS_YEAR} 5-year"
        assert table.source_row_count == len(table.rows)


# --- 3. the surface records ACS 2024 as its feature vintage -------------------------

def test_check_03_the_national_surface_records_its_feature_vintage(
    evidence: dict[str, Any],
) -> None:
    assert evidence["national_surface"]["feature_vintage"] == f"ACS {ACS_YEAR} 5-year"
    assert evidence["feature_vintage"]["current_production"] == f"ACS {ACS_YEAR} 5-year"


# --- 4. historical ACS vintages survive -------------------------------------------

def test_check_04_historical_acs_vintages_are_still_replayable(
    evidence: dict[str, Any],
) -> None:
    """D1 needs cutoff-appropriate features in Phase 5, so older releases must survive.

    They do because the cache key hashes the request URL, which carries the year: each
    vintage occupies its own entry under the same source id rather than overwriting it.
    """
    fetcher = replay()
    assert HISTORICAL_ACS_YEARS, "at least one historical vintage must be retained"
    for year in HISTORICAL_ACS_YEARS:
        assert year != ACS_YEAR
        older = AcsSource(TRACT, "44", year=year).load(fetcher)
        assert len(older.rows) == 250
        assert older.vintage.vintage == f"ACS {year} 5-year"
    recorded = evidence["feature_vintage"]["historical_retained_for_phase_5"]
    assert recorded == [f"ACS {y} 5-year" for y in HISTORICAL_ACS_YEARS]


def test_check_04b_the_two_vintages_are_genuinely_different_data() -> None:
    """A cache that silently served 2024 for a 2023 request would pass check 4 vacuously."""
    fetcher = replay()
    current = AcsSource(TRACT, "44").load(fetcher)
    older = AcsSource(TRACT, "44", year=HISTORICAL_ACS_YEARS[0]).load(fetcher)
    by_geoid_now = {r["geoid"]: r["B01003_001E"] for r in current.rows}
    by_geoid_then = {r["geoid"]: r["B01003_001E"] for r in older.rows}
    shared = set(by_geoid_now) & set(by_geoid_then)
    assert shared, "the two vintages share no tracts, which cannot be right"
    assert any(by_geoid_now[g] != by_geoid_then[g] for g in shared), (
        "every population value is identical across vintages; the cache is probably "
        "serving one vintage for both requests"
    )


# --- 5 and 6. Washington: barred from validation, eligible for training -------------

def test_check_05_washington_is_excluded_from_the_independent_aggregate(
    evidence: dict[str, Any],
) -> None:
    validation = evidence["demand_model_validation"]
    assert "WA" not in validation["independent_validation_states"]
    assert validation["excluded_from_independent_aggregate"]["WA"] == (
        "non_independent_preprocessing_selection_state")
    assert validation["washington_role"]["independent_validation_evidence"] is False
    assert {"WA"} == NON_INDEPENDENT_STATES


def test_check_06_washington_is_eligible_for_training_in_other_states_folds(
    evidence: dict[str, Any],
) -> None:
    """Its tuning influence invalidates its own evaluation, not another state's."""
    validation = evidence["demand_model_validation"]
    assert "WA" in validation["training_states"]
    assert validation["washington_role"]["training_development_evidence"] is True
    assert frozenset() == NON_TRAINABLE_STATES


def test_check_06b_washington_appears_in_exactly_one_of_the_two_lists(
    evidence: dict[str, Any],
) -> None:
    validation = evidence["demand_model_validation"]
    in_validation = "WA" in validation["independent_validation_states"]
    in_training = "WA" in validation["training_states"]
    assert (in_validation, in_training) == (False, True)


# --- 7. the final production fit includes Washington --------------------------------

def test_check_07_the_production_fit_includes_washington(
    evidence: dict[str, Any],
) -> None:
    training = evidence["national_surface"]["training_states"]
    assert "WA" in training
    assert len(training) == 15


# --- 8 and 9. ZIP totals stay out of Core v1 ---------------------------------------

def test_check_08_zip_totals_are_not_reconciliation_constraints(
    evidence: dict[str, Any],
) -> None:
    """Reviewer decision closing A-3.6: county totals where reliable, state elsewhere."""
    surface = evidence["national_surface"]
    assert surface["reconciliation_method"] == "proportional"
    assert surface["unconstrained_tracts"] == 0
    grains = surface["tracts_by_evidence_grain"]
    assert set(grains) <= {"native_tract", "county_anchored", "state_total_only"}


def test_check_09_zip_anchored_is_absent_from_the_production_surface(
    evidence: dict[str, Any],
) -> None:
    assert "zip_anchored" not in evidence["national_surface"]["tracts_by_evidence_grain"]


# --- 10. the New Jersey sensitivity is diagnostic only ------------------------------

def test_check_10_new_jersey_sensitivity_is_reported_and_was_not_used_to_reselect(
    evidence: dict[str, Any],
) -> None:
    sensitivity = evidence["new_jersey_sensitivity"]
    assert sensitivity["new_jersey_status"] == "flagged_for_review"
    assert sensitivity["used_to_alter_estimator_selection"] is False
    assert sensitivity["affected_confidence_tiers"] is False
    # New Jersey is still IN the aggregate that selected the estimator, and the
    # published claim says so rather than pretending otherwise.
    assert "NJ" in evidence["demand_model_validation"]["independent_validation_states"]
    assert isinstance(sensitivity["with_new_jersey"], float)
    assert isinstance(sensitivity["without_new_jersey"], float)
    assert sensitivity["delta_weighted_wape"] == pytest.approx(
        sensitivity["without_new_jersey"] - sensitivity["with_new_jersey"], abs=1e-6)


def test_check_10b_the_pre_registered_winner_is_retained(
    evidence: dict[str, Any],
) -> None:
    validation = evidence["demand_model_validation"]
    aggregates = validation["aggregate_weighted_wape"][evidence["selection_mode"]]
    best = min(aggregates.values())
    assert aggregates[validation["selected_estimator"]] <= best + 0.01
    assert evidence["new_jersey_sensitivity"][
        "selected_under_the_pre_registered_rule"] == validation["selected_estimator"]


# --- 11. no calibration overclaim anywhere -----------------------------------------

OVERCLAIM = re.compile(
    r"partly[- ]calibrated|is empirically calibrated|well[- ]calibrated score",
    re.IGNORECASE,
)


def test_check_11_no_document_claims_the_uncertainty_score_is_calibrated(
    evidence: dict[str, Any],
) -> None:
    offenders: list[str] = []
    for path in sorted((PATHS.root / "docs").rglob("*.md")):
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            # A document may quote the banned phrase in order to ban it, marked with
            # the same inline allow marker the D3 copy lint uses.
            if "copy-lint: allow" in line:
                continue
            if OVERCLAIM.search(line) and "not empirically calibrated" not in line:
                offenders.append(f"{path.relative_to(PATHS.root)}:{number}: {line[:90]}")
    assert offenders == [], "calibration overclaim(s): " + "; ".join(offenders)
    diagnostic = evidence["washington_uncertainty_error_diagnostic"]
    assert diagnostic["is_empirical_calibration"] is False
    assert "NOT empirically calibrated" in diagnostic["interpretation"]


# --- 12. D2 --------------------------------------------------------------------------

def test_check_12_d2_still_forbids_every_supply_derived_primary_feature() -> None:
    assert_primary_feature_set_is_clean()
    assert set(FEATURE_NAMES).isdisjoint(SUPPLY_FEATURE_NAMES)
    assert len(FEATURE_NAMES) == 14


# --- 13. reconciliation ---------------------------------------------------------------

def test_check_13_the_reconciliation_identity_still_holds(
    evidence: dict[str, Any],
) -> None:
    surface = evidence["national_surface"]
    assert surface["reconciliation_max_residual"] < 1e-6
    assert surface["unconstrained_tracts"] == 0


# --- 14. provenance on every tract ----------------------------------------------------

def test_check_14_every_tract_still_carries_uncertainty_and_provenance(
    evidence: dict[str, Any],
) -> None:
    surface = evidence["national_surface"]
    grains = surface["tracts_by_evidence_grain"]
    tiers = surface["tracts_by_confidence_tier"]
    assert sum(grains.values()) == sum(tiers.values()) == surface["tracts"]
    assert len(surface["weight_sensitivity"]) == 5
    assert surface["weights_are_calibrated"] is False


# --- the states are all accounted for ------------------------------------------------

def test_every_declared_state_is_either_validation_or_training_evidence(
    evidence: dict[str, Any],
) -> None:
    validation = evidence["demand_model_validation"]
    covered = set(validation["independent_validation_states"]) | set(
        validation["training_states"])
    assert covered == set(STATE_FIPS)


# --- the vintage must be selectable by argument, not by patching a constant ----------

def test_a_vintage_can_be_requested_by_name_rather_than_by_mutating_a_constant() -> None:
    """``AcsSource`` binds ``ACS_YEAR`` as a DEFAULT ARGUMENT, evaluated once at
    definition time. Monkeypatching ``census_acs.ACS_YEAR`` therefore does **not** change
    which vintage loads - it silently returns the production vintage instead. That would
    hand Phase 5 a D1 violation that looks like a passing test, so the loader takes the
    vintage as a parameter.
    """
    from pipeline.model.panel import load_area_tables

    current = load_area_tables(states=("53",))
    older = load_area_tables(states=("53",), year=HISTORICAL_ACS_YEARS[0])
    now = current["tracts"].rows
    then = older["tracts"].rows
    assert set(now) & set(then), "the two vintages share no tracts"
    assert any(now[g].households != then[g].households
               for g in set(now) & set(then)), (
        "every household count is identical across vintages; the loader is probably "
        "ignoring its year argument and serving one vintage for both"
    )


# --- A. the tract set is reconciled between vintages, not asserted identical ---------

def test_check_a_every_tract_that_entered_or_left_is_named(
    evidence: dict[str, Any],
) -> None:
    """A national tract count that changes between releases is a fact about the Census,
    and it must be named tract by tract rather than waved through."""
    recon = evidence["tract_set_reconciliation"]
    assert recon["intersection"] + recon["entered_count"] == recon["tracts_current"]
    assert recon["intersection"] + recon["left_count"] == recon["tracts_previous"]
    assert len(recon["entered"]) == recon["entered_count"]
    assert len(recon["left"]) == recon["left_count"]
    for row in recon["entered"] + recon["left"]:
        assert set(row) == {"geoid", "state_fips", "county_fips",
                            "population", "households"}
        assert len(row["geoid"]) == 11


def test_check_a_the_surface_tract_count_matches_the_reconciliation(
    evidence: dict[str, Any],
) -> None:
    assert (evidence["tract_set_reconciliation"]["tracts_current"]
            == evidence["national_surface"]["tracts"])


def test_check_a_zcta_and_county_sets_are_compared_nationally_not_by_sample(
    evidence: dict[str, Any],
) -> None:
    """The earlier 'identical area counts' claim rested on a BOUNDED Rhode Island
    retrieval check. These are national counts."""
    recon = evidence["tract_set_reconciliation"]
    assert recon["zcta_previous"] == recon["zcta_current"] == 33772
    assert recon["county_previous"] == recon["county_current"] == 3222


# --- B. the national total is fully accounted for -----------------------------------

def test_check_b_the_national_total_balances_against_its_constraints(
    evidence: dict[str, Any],
) -> None:
    """A two-vehicle discrepancy is not floating-point noise when the reconciliation
    residual is 2.3e-10. Every vehicle in the national figure is attributed."""
    accounting = evidence["national_surface"]["national_accounting"]
    assert accounting["balances"] is True
    assert abs(accounting["imbalance"]) < 1e-6
    rebuilt = (accounting["constraint_sum"]
               + accounting["observed_substitution_delta"]
               + accounting["unconstrained_sum"])
    assert abs(rebuilt - accounting["national_published"]) < 1e-6


def test_check_b_nothing_overrides_a_constraint_from_outside_the_system(
    evidence: dict[str, Any],
) -> None:
    """Observed values are constraints, resolved by precedence BEFORE reconciliation.

    The former +611.03 Washington term was a post-reconciliation overwrite that left the
    surface no longer summing to the totals it reconciled to (impact I-16).
    """
    accounting = evidence["national_surface"]["national_accounting"]
    assert accounting["observed_substitution_delta"] == 0.0
    assert accounting["unconstrained_sum"] == 0.0
    assert accounting["national_published"] == accounting["constraint_sum"]
    assert accounting["imbalance"] == 0.0


def test_check_b_no_state_is_counted_twice_by_partial_county_coverage(
    evidence: dict[str, Any],
) -> None:
    """Impact I-15: Montana publishes 51 of 56 counties and Virginia 129 of 133.
    Reconciling the leftover tracts to the FULL state total counted both roughly twice."""
    precedence = {p["state_fips"]: p
                  for p in evidence["national_surface"]["constraint_precedence"]}
    for fips, expected in (("30", 6900.0), ("51", 134900.0)):
        entry = precedence[fips]
        # Partial coverage: the state total stays operative and the counties decompose it.
        assert entry["chosen_constraint_source"] == "state_registration_total"
        assert entry["chosen_constraint_total"] == expected
        assert "partition the state total rather than superseding" in (
            entry["constraint_precedence_reason"])


def test_check_b_every_jurisdiction_has_exactly_one_operative_constraint(
    evidence: dict[str, Any],
) -> None:
    precedence = evidence["national_surface"]["constraint_precedence"]
    assert len(precedence) == 51
    assert len({p["state_fips"] for p in precedence}) == 51
    for entry in precedence:
        assert entry["chosen_constraint_source"] in {
            "native_tract_registry", "county_observation", "state_registration_total"}
        assert entry["constraint_precedence_reason"]
        assert entry["chosen_constraint_vintage"]


def test_check_b_superseded_constraints_are_provenance_and_are_not_summed(
    evidence: dict[str, Any],
) -> None:
    surface = evidence["national_surface"]
    precedence = surface["constraint_precedence"]
    chosen = sum(p["chosen_constraint_total"] for p in precedence)
    superseded = sum(c["total"] for p in precedence
                     for c in p["superseded_constraints"])
    assert superseded > 0, "Washington's and Tennessee's state totals are superseded"
    assert surface["national_accounting"]["constraint_sum"] == pytest.approx(
        chosen, abs=1e-6)
    # The superseded totals are recorded but contribute nothing to the national figure.
    assert surface["national_accounting"]["constraint_sum"] != pytest.approx(
        chosen + superseded, abs=1e-6)


def test_check_b_the_native_registry_supersedes_only_where_it_qualifies(
    evidence: dict[str, Any],
) -> None:
    precedence = {p["state_fips"]: p
                  for p in evidence["national_surface"]["constraint_precedence"]}
    washington = precedence["53"]
    assert washington["chosen_constraint_source"] == "native_tract_registry"
    assert washington["chosen_constraint_total"] == 236994.0
    assert [c["source"] for c in washington["superseded_constraints"]] == [
        "state_registration_total"]
    assert [c["total"] for c in washington["superseded_constraints"]] == [236400.0]
    # Tennessee's COMPLETE county coverage supersedes its state total too.
    assert precedence["47"]["chosen_constraint_source"] == "county_observation"
    # No other jurisdiction supersedes anything.
    superseding = [f for f, p in precedence.items() if p["superseded_constraints"]]
    assert sorted(superseding) == ["47", "53"]


# --- C. the New Jersey sensitivity, across every candidate --------------------------

def test_check_c_the_sensitivity_covers_every_candidate(
    evidence: dict[str, Any],
) -> None:
    per_candidate = evidence["new_jersey_sensitivity"]["per_candidate"]
    assert set(per_candidate) == {
        "poisson_glm", "boosted_poisson", "ridge_log_rate",
        "baseline_population_share", "baseline_household_share",
    }
    for row in per_candidate.values():
        assert set(row) == {"with_new_jersey", "without_new_jersey", "delta"}


def test_check_c_the_claim_is_the_narrow_one(evidence: dict[str, Any]) -> None:
    """Not 'NJ could not have influenced selection' - it was in the selecting aggregate.
    The true claim is that this POST-SELECTION sensitivity was not used to alter it."""
    sensitivity = evidence["new_jersey_sensitivity"]
    assert sensitivity["used_to_alter_estimator_selection"] is False
    assert "could therefore in principle have influenced candidate ranking" in (
        sensitivity["interpretation"])
    assert "no refit, no " in sensitivity["interpretation"]


def test_check_c_the_selected_estimator_is_retained_whatever_the_table_shows(
    evidence: dict[str, Any],
) -> None:
    sensitivity = evidence["new_jersey_sensitivity"]
    validation = evidence["demand_model_validation"]
    assert sensitivity["selected_under_the_pre_registered_rule"] == (
        validation["selected_estimator"])
    assert sensitivity["selected_estimator_changes_without_new_jersey"] is False
    assert sensitivity["model_ranking_changes_without_new_jersey"] is False


def test_check_c_an_ordering_change_is_described_precisely(
    evidence: dict[str, Any],
) -> None:
    """A bare 'the ranking is not stable' would be true but useless when the only
    movement is two baselines swapping by 0.00015."""
    sensitivity = evidence["new_jersey_sensitivity"]
    if sensitivity["ranking_changes_without_new_jersey"]:
        assert sensitivity["selection_fragility"] != (
            "the candidate ordering is stable to removing New Jersey")
        assert ("BASELINES" in sensitivity["selection_fragility"]
                or "WINNER" in sensitivity["selection_fragility"]
                or "AMONG MODELS" in sensitivity["selection_fragility"])
