"""The rolling origins, the vintages they resolve to, and the cutoff-valid surface.

§10.2.2 requires three origins - 2020, 2021, 2022 - each predicting the following 24
months. §10.2.3 requires that where the backtested model differs from the deployed model,
those differences are stated. These tests pin both.
"""

from __future__ import annotations

from datetime import date

import pytest

from pipeline.model.demand import ModelRow
from pipeline.model.features import FEATURE_NAMES
from pipeline.validation.backtest import (
    KNOWN_EXCLUSIONS,
    build_historical_surface,
    state_rows,
)
from pipeline.validation.origins import (
    ACS_SOURCE,
    ACS_VINTAGES,
    ORIGINS,
    REGISTRATION_SOURCE,
    Origin,
    plan_origins,
)
from pipeline.validation.vintage import LeakageError

# --- the origins ---------------------------------------------------------------------

def test_the_three_required_origins_are_declared_with_24_month_windows() -> None:
    assert [o.name for o in ORIGINS] == ["2020", "2021", "2022"]
    for origin in ORIGINS:
        assert origin.horizon_months == 24
        assert origin.window_end.year == origin.cutoff.year + 2


def test_a_window_contains_its_own_start_but_not_its_end() -> None:
    origin = Origin("2021", date(2021, 1, 1))
    assert origin.contains(date(2021, 1, 1))
    assert origin.contains(date(2022, 12, 31))
    assert not origin.contains(date(2023, 1, 1))
    assert not origin.contains(date(2020, 12, 31))


def test_reconstruction_confidence_is_lowest_for_the_oldest_origin() -> None:
    """G11: survivorship bias grows with age, so conclusions weight toward the recent."""
    assert "lowest" in Origin("2020", date(2020, 1, 1)).reconstruction_confidence
    assert "highest" in Origin("2022", date(2022, 1, 1)).reconstruction_confidence


# --- what each origin is allowed to see ----------------------------------------------

def test_each_origin_resolves_to_the_contemporaneous_acs_release() -> None:
    plans, _ = plan_origins()
    resolved = {p.origin.name: p.acs_year for p in plans}
    assert resolved == {"2020": 2018, "2021": 2019, "2022": 2019}


def test_no_origin_uses_the_production_acs_vintage() -> None:
    """The headline leakage risk: ACS 2024 is the deployed surface and postdates every
    cutoff by years."""
    plans, _ = plan_origins()
    for plan in plans:
        assert plan.acs_year <= 2019
        assert plan.acs.released <= plan.origin.cutoff


def test_every_origin_lands_on_2010_tract_geography() -> None:
    """ACS releases through 2019 are published on 2010 tract boundaries and the 2020
    release onward on 2020 boundaries. All three cutoffs fall before the 2020 release
    was available, so the whole backtest is 2010-geography while production is 2020."""
    plans, _ = plan_origins()
    assert {p.tract_geography for p in plans} == {"2010"}


def test_the_2022_origin_does_not_use_the_acs_2020_release() -> None:
    """Its period ends before the cutoff, which makes it tempting. Its release date is
    not established by this project, so it is skipped in favour of ACS 2019 - the
    direction that cannot manufacture leakage."""
    plans, ledger = plan_origins()
    plan = next(p for p in plans if p.origin.name == "2022")
    assert plan.acs_year == 2019
    assert any("ACS 2020" in e.name for e in ledger.exclusions)


def test_the_acs_2020_vintage_is_declared_uncertain_rather_than_quietly_dropped() -> None:
    acs2020 = next(v for v in ACS_VINTAGES if v.period_end.year == 2020)
    assert acs2020.release_date_certain is False
    assert "NOT verified against a primary source" in acs2020.release_evidence


def test_each_origin_uses_a_state_registration_vintage_from_before_its_cutoff() -> None:
    plans, _ = plan_origins()
    for plan in plans:
        assert plan.registrations.released <= plan.origin.cutoff
        assert plan.registrations.period_end.year == plan.origin.cutoff.year - 1


def test_the_registration_vintages_carry_the_unresolved_contemporaneity_caveat() -> None:
    """A-0.5. Phase 1 established the AFDC annual pages are stable but not that they are
    contemporaneous, and §10.2.3 requires Phase 5 to state that limitation."""
    plans, _ = plan_origins()
    assert "Contemporaneity UNRESOLVED" in plans[0].registrations.release_evidence
    assert "A-0.5" in plans[0].registrations.release_evidence


def test_the_published_plan_names_every_vintage_and_the_window() -> None:
    plans, _ = plan_origins()
    payload = plans[0].to_dict()
    assert payload["prediction_cutoff"] == "2020-01-01"
    assert "2022-01-01" in str(payload["evaluation_window"])
    assert payload["acs_vintage"] == "ACS 2018 5-year (2014-2018)"
    assert payload["tract_geography"] == "2010"


def test_both_sources_are_declared_or_resolution_fails_loudly() -> None:
    assert ACS_SOURCE == "census_acs_tracts"
    assert REGISTRATION_SOURCE == "afdc_state_ev_registrations"


# --- exclusions -----------------------------------------------------------------------

def test_every_known_exclusion_names_a_source_and_a_reason() -> None:
    assert len(KNOWN_EXCLUSIONS) >= 5
    for exclusion in KNOWN_EXCLUSIONS:
        assert exclusion.source_id and len(exclusion.reason) > 40


def test_supply_features_are_excluded_by_directive_not_by_vintage() -> None:
    """D2 forbids them at every cutoff, including one where a contemporaneous edition
    would have existed. The reason recorded must say so."""
    supply = next(e for e in KNOWN_EXCLUSIONS if "charger" in e.name)
    assert "D2" in supply.reason
    assert "not" in supply.reason.lower()


def test_the_current_hud_crosswalk_is_recorded_as_not_used() -> None:
    """Rather than justified as stable geography infrastructure: the backtest fits at
    state level, so no ZIP->tract transformation happens and the question is moot."""
    hud = next(e for e in KNOWN_EXCLUSIONS if "hud" in e.source_id)
    assert "not used at any historical origin" in hud.reason


def test_the_current_road_network_is_excluded_from_historical_rankings() -> None:
    roads = next(e for e in KNOWN_EXCLUSIONS if "tiger" in e.source_id)
    assert "postdates every cutoff" in roads.reason


# --- the cutoff-valid surface ---------------------------------------------------------

def row(geoid: str, households: float, population: float,
        value: float) -> ModelRow:
    return ModelRow(state=geoid[:2], geography="tracts", geoid=geoid,
                    households=households, population=population,
                    features=dict.fromkeys(FEATURE_NAMES, value))


def test_state_aggregation_is_household_weighted() -> None:
    rows = [row("530000001", 100.0, 250.0, 1.0), row("530000002", 300.0, 750.0, 5.0)]
    aggregated = state_rows(rows, {"53": 1000.0})
    assert len(aggregated) == 1
    assert aggregated[0].households == 400.0
    # (100*1 + 300*5) / 400 = 4.0, not the unweighted mean of 3.0
    assert aggregated[0].features[FEATURE_NAMES[0]] == pytest.approx(4.0)


def test_a_state_with_no_registration_total_is_not_trained_on() -> None:
    rows = [row("530000001", 100.0, 250.0, 1.0), row("060000001", 100.0, 250.0, 2.0)]
    assert [r.geoid for r in state_rows(rows, {"53": 500.0})] == ["53"]


def test_a_state_with_no_households_cannot_carry_a_rate() -> None:
    rows = [row("530000001", 0.0, 0.0, 1.0)]
    assert state_rows(rows, {"53": 500.0}) == []


def surface(cutoff: date, feature_vintage: date):  # type: ignore[no-untyped-def]
    rows = [row(f"53000000{i}", 100.0 * (i + 1), 250.0 * (i + 1), float(i + 1))
            for i in range(5)]
    return build_historical_surface(
        rows, {"53": 1000.0}, cutoff, 2018, "2010", "AFDC 2019",
        feature_vintage, "census_acs_tracts", "ACS 2018, released 2019-12-19")


def test_the_surface_reconciles_exactly_to_the_state_total() -> None:
    result = surface(date(2020, 1, 1), date(2018, 12, 31))
    assert sum(result.estimates.values()) == pytest.approx(1000.0)
    assert result.reconciliation_max_abs_error < 1e-6


def test_the_surface_keeps_the_unreconciled_estimates_too() -> None:
    """Phase 5 objective 3: report unreconciled and reconciled results distinctly.

    Two states, whose totals the state-level fit cannot reproduce exactly, so the
    reconciliation step actually moves something and the two mappings genuinely differ.
    """
    rows = [row(f"53000000{i}", 100.0 * (i + 1), 250.0 * (i + 1), float(i + 1))
            for i in range(4)]
    rows += [row(f"06000000{i}", 500.0, 1200.0, float(i + 1)) for i in range(4)]
    result = build_historical_surface(
        rows, {"53": 1000.0, "06": 90000.0}, date(2020, 1, 1), 2018, "2010",
        "AFDC 2019", date(2018, 12, 31), "census_acs_tracts", "ACS 2018")

    assert set(result.unreconciled) == set(result.estimates)
    assert sum(result.estimates.values()) == pytest.approx(91000.0)
    moved = max(abs(result.estimates[g] - result.unreconciled[g])
                for g in result.estimates)
    assert moved > 0.0, "reconciliation moved nothing, so the two are not distinct"


def test_the_surface_refuses_to_build_from_a_future_dated_feature() -> None:
    """The leakage guard runs BEFORE the fit, so a mis-declared vintage stops the run
    rather than producing a plausible number."""
    with pytest.raises(LeakageError, match="postdate the prediction cutoff"):
        surface(date(2020, 1, 1), date(2024, 12, 31))


def test_the_surface_declares_itself_modelled_and_state_anchored_only() -> None:
    payload = surface(date(2020, 1, 1), date(2018, 12, 31)).to_dict()
    assert payload["estimate_method"] == "modelled"
    assert payload["evidence_grain"] == "state_total_only"
    assert "NOT the same model" in str(payload["note"])
    assert payload["tract_geography"] == "2010"


def test_a_state_with_a_total_but_no_tracts_is_skipped_not_crashed() -> None:
    """A registration vintage can name a jurisdiction the ACS request did not cover."""
    rows = [row("530000001", 100.0, 250.0, 1.0)]
    result = build_historical_surface(
        rows, {"53": 1000.0, "72": 500.0}, date(2020, 1, 1), 2018, "2010", "AFDC 2019",
        date(2018, 12, 31), "census_acs_tracts", "ACS 2018")
    assert sum(result.estimates.values()) == pytest.approx(1000.0)


def test_a_state_with_no_exposure_falls_back_to_household_share() -> None:
    """D8. Predicted count is rate times exposure, so a state whose tracts report no
    households gets a zero subtotal and cannot be rescaled - dividing by it would be the
    silent failure. The fallback path runs instead, and it is a visible branch.

    Realistic rather than contrived: a tract can genuinely report zero households while
    holding population, for instance one that is entirely group quarters.
    """
    rows = [row("530000001", 0.0, 250.0, 1.0), row("530000002", 0.0, 750.0, 1.0),
            row("060000001", 200.0, 500.0, 9.0), row("060000002", 400.0, 900.0, 3.0)]
    result = build_historical_surface(
        rows, {"53": 0.0, "06": 5000.0}, date(2020, 1, 1), 2018, "2010", "AFDC 2019",
        date(2018, 12, 31), "census_acs_tracts", "ACS 2018")

    # Washington took the fallback path: no exposure anywhere, and a zero target.
    assert sum(v for g, v in result.estimates.items() if g.startswith("53")) == 0.0
    # California took the normal rescaling path and its neighbour did not disturb it.
    assert sum(v for g, v in result.estimates.items()
               if g.startswith("06")) == pytest.approx(5000.0)
    assert result.reconciliation_max_abs_error < 1e-9
    # Only California could train: a state with no households carries no rate.
    assert result.training_observations == 1
