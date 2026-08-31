"""Leave-one-state-out at native granularity, and the pre-registered selection rule."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from pipeline.model.demand import ConstantRateBaseline, ModelRow, PoissonRate
from pipeline.model.features import FEATURE_NAMES
from pipeline.model.observed import StateTotal
from pipeline.model.panel import StatePanel
from pipeline.spatial.geography import SourceGeography
from pipeline.validation.demand_model import (
    STATE_TOTAL_RECONCILED,
    TIE_BREAK_WAPE,
    UNRECONCILED,
    ValidationError,
    calibration_curve,
    nearest_vintage,
    run_loso,
    score_state,
    select_estimator,
    snapshot_date,
    weighted_wape,
)
from pipeline.validation.scope import ExclusionLedger

STATES = ("CO", "CT", "ME", "MN", "NC", "NJ", "NM", "NY", "OR", "TX", "VT")


def panel(state: str, n: int = 25, independent: bool = True,
          geography: str = "zcta") -> StatePanel:
    seed = sum(ord(c) for c in state)
    rows = tuple(
        ModelRow(state, geography, f"{state}{i:04d}", 100.0 + i, 250.0 + i,
                 {name: float((seed + i * 3 + j) % 9) / 9.0
                  for j, name in enumerate(FEATURE_NAMES)},
                 float((seed + i) % 7) + 1.0)
        for i in range(n)
    )
    total = int(sum(float(r.observed_bev or 0) for r in rows))
    return StatePanel(
        state=state,
        source_geography=(SourceGeography.TRACT if geography == "tracts"
                          else SourceGeography.USPS_ZIP),
        vintage_label="DMV Snapshot (1/1/2026)",
        rows=rows,
        ledger=ExclusionLedger(total, total, {}, {}),
        is_independent=independent,
    )


def totals_for(panels: dict[str, StatePanel]) -> dict[str, list[StateTotal]]:
    from pipeline.model.observed import STATE_FIPS

    out: dict[str, list[StateTotal]] = {}
    for state, one in panels.items():
        fips = STATE_FIPS[state]
        observed = int(one.observed_total)
        out[fips] = [
            StateTotal(fips, state, "2024", int(observed * 0.8), 0),
            StateTotal(fips, state, "2025", observed, 0),
        ]
    return out


# --- vintage alignment --------------------------------------------------------------

def test_a_snapshot_label_parses_whatever_format_the_state_used() -> None:
    assert snapshot_date("DMV Snapshot (1/1/2026)") == dt.date(2026, 1, 1)
    assert snapshot_date("DMV Snapshot (01/01/2026)") == dt.date(2026, 1, 1)
    assert snapshot_date("current snapshot") is None
    assert snapshot_date("DMV Snapshot (13/45/2026)") is None


def test_the_nearest_vintage_is_chosen_rather_than_the_newest() -> None:
    """North Carolina's June 2024 snapshot against the 2025 total is -45.27%; against
    the contemporaneous vintage it is -5.66%."""
    series = [StateTotal("37", "NC", "2023", 70200, 0),
              StateTotal("37", "NC", "2025", 121000, 0)]
    assert nearest_vintage(series, dt.date(2024, 6, 1)).vintage == "2023"
    assert nearest_vintage(series, dt.date(2025, 12, 1)).vintage == "2025"


def test_with_no_observation_date_the_newest_vintage_is_used() -> None:
    series = [StateTotal("53", "WA", "2023", 1, 0), StateTotal("53", "WA", "2025", 2, 0)]
    assert nearest_vintage(series, None).vintage == "2025"


def test_choosing_a_vintage_from_nothing_is_refused() -> None:
    with pytest.raises(ValidationError, match="no state totals"):
        nearest_vintage([], dt.date(2025, 1, 1))


# --- scoring ------------------------------------------------------------------------

def test_a_state_is_scored_at_its_own_native_granularity() -> None:
    held = panel("VT", geography="zcta")
    training = list(panel("CO").rows)
    score = score_state(PoissonRate(), training, held, UNRECONCILED)
    assert score.geography == "zcta"
    assert score.evidence_grain == "usps_zip"
    assert score.areas == len(held.rows)
    assert score.independent is True
    assert score.to_dict()["status"] is None


def test_reconciling_needs_a_published_total_and_never_the_held_out_sum() -> None:
    held = panel("VT")
    with pytest.raises(ValidationError, match="refusing to reconcile"):
        score_state(PoissonRate(), list(panel("CO").rows), held,
                    STATE_TOTAL_RECONCILED)


def test_reconciled_predictions_sum_exactly_to_the_published_total() -> None:
    held = panel("VT")
    total = StateTotal("50", "VT", "2025", 12345, 0)
    score = score_state(PoissonRate(), list(panel("CO").rows), held,
                        STATE_TOTAL_RECONCILED, total)
    assert score.constraint_total == 12345.0
    assert score.constraint_vintage == "2025"
    assert score.to_dict()["constraint_bev"] == 12345


def test_an_unknown_reconciliation_mode_is_refused() -> None:
    with pytest.raises(ValidationError, match="unknown reconciliation mode"):
        score_state(PoissonRate(), list(panel("CO").rows), panel("VT"), "invented")


def test_a_state_with_nothing_to_score_is_refused() -> None:
    empty = panel("VT", n=0)
    with pytest.raises(ValidationError, match="nothing to score"):
        score_state(PoissonRate(), list(panel("CO").rows), empty, UNRECONCILED)


def test_a_non_independent_state_reports_its_status_in_its_own_row() -> None:
    held = panel("WA", geography="tracts", independent=False)
    score = score_state(PoissonRate(), list(panel("CO").rows), held, UNRECONCILED)
    assert score.independent is False
    assert score.to_dict()["status"] == "non_independent_preprocessing_selection_state"


# --- aggregation and selection ------------------------------------------------------

def test_the_aggregate_is_ev_weighted() -> None:
    from pipeline.validation.demand_model import StateScore

    def score(state: str, w: float, observed: float) -> StateScore:
        return StateScore(state, "e", UNRECONCILED, "zcta", "usps_zip", 1, observed,
                          w, 0.0, 0.0, True, None, None)

    assert weighted_wape([score("A", 0.2, 100.0), score("B", 0.8, 900.0)]) == (
        pytest.approx((0.2 * 100 + 0.8 * 900) / 1000))


def test_an_aggregate_over_nothing_is_refused() -> None:
    with pytest.raises(ValidationError, match="no observed vehicles"):
        weighted_wape([])


def test_a_tie_inside_one_point_goes_to_the_simpler_model() -> None:
    """The pre-registered tie-break. poisson_glm and boosted_poisson came out 0.0008
    apart on the real data, so this rule decides the published estimator."""
    assert TIE_BREAK_WAPE == 0.01
    chosen = select_estimator(
        {"poisson_glm": 0.3312, "boosted_poisson": 0.3320},
        [PoissonRate(), __import__("pipeline.model.demand", fromlist=["x"])
         .BoostedPoissonRate()],
    )
    assert chosen == "poisson_glm"


def test_a_clear_win_beats_a_simpler_model() -> None:
    chosen = select_estimator(
        {"baseline_household_share": 0.71, "poisson_glm": 0.33},
        [ConstantRateBaseline(), PoissonRate()],
    )
    assert chosen == "poisson_glm"


def test_selecting_from_nothing_is_refused() -> None:
    with pytest.raises(ValidationError, match="no candidate results"):
        select_estimator({}, [PoissonRate()])


# --- the harness --------------------------------------------------------------------

def test_loso_scores_every_state_in_both_modes_and_selects_one_estimator() -> None:
    panels = {state: panel(state) for state in STATES}
    result = run_loso(panels, totals_for(panels),
                      estimators=[ConstantRateBaseline(), PoissonRate()])
    assert set(result.independent_states) == set(STATES)
    assert result.excluded_states == {}
    assert len(result.scores) == len(STATES) * 2 * 2
    assert set(result.aggregates) == {UNRECONCILED, STATE_TOTAL_RECONCILED}
    assert result.selected_estimator in {"poisson_glm", "baseline_household_share"}
    payload = result.to_dict()
    assert payload["validation_term"] == "demand model validation"
    assert "native observed granularity" in str(payload["protocol"])


def test_a_non_independent_state_is_scored_but_kept_out_of_the_aggregate() -> None:
    panels = {state: panel(state) for state in STATES}
    panels["WA"] = panel("WA", geography="tracts", independent=False)
    result = run_loso(panels, totals_for(panels),
                      estimators=[ConstantRateBaseline()])
    assert "WA" not in result.independent_states
    assert result.excluded_states == {
        "WA": "non_independent_preprocessing_selection_state"}
    assert any(s.state == "WA" for s in result.scores)


def test_three_or_fewer_usable_states_triggers_a_plan_change_not_a_weaker_test() -> None:
    panels = {state: panel(state) for state in STATES[:3]}
    with pytest.raises(ValidationError, match="formal plan change"):
        run_loso(panels, totals_for(panels), estimators=[ConstantRateBaseline()])


def test_a_state_with_no_published_total_is_scored_unreconciled_only() -> None:
    """It is recorded, never scored against the held-out state's own observed sum."""
    panels = {state: panel(state) for state in STATES}
    totals = totals_for(panels)
    totals.pop("50")  # Vermont
    result = run_loso(panels, totals, estimators=[ConstantRateBaseline()])
    vermont = [s for s in result.scores if s.state == "VT"]
    assert {s.mode for s in vermont} == {UNRECONCILED}
    assert result.states_without_a_published_total == ("VT",)
    assert result.to_dict()["states_without_a_published_total"] == ["VT"]


# --- calibration --------------------------------------------------------------------

def test_the_calibration_curve_bins_by_uncertainty_and_reports_mean_error() -> None:
    scores = list(np.linspace(0.0, 1.0, 50))
    errors = [s * 100 for s in scores]
    curve = calibration_curve(scores, errors, bins=5)
    assert len(curve) == 5
    assert [row["n"] for row in curve] == [10.0] * 5
    assert curve[0]["mean_absolute_error"] < curve[-1]["mean_absolute_error"]


def test_the_curve_refuses_mismatched_or_empty_inputs() -> None:
    with pytest.raises(ValidationError, match="same length"):
        calibration_curve([0.1], [0.1, 0.2])
    with pytest.raises(ValidationError, match="no rows"):
        calibration_curve([], [])


def test_more_bins_than_rows_collapses_to_one_bin_per_row() -> None:
    curve = calibration_curve([0.1, 0.2], [1.0, 2.0], bins=10)
    assert len(curve) == 2


def test_a_state_whose_join_left_no_rows_is_recorded_not_crashed_on() -> None:
    panels = {state: panel(state) for state in STATES}
    panels["VA"] = panel("VA", n=0)
    result = run_loso(panels, totals_for(panels), estimators=[ConstantRateBaseline()])
    assert result.unscorable_states == ("VA",)
    assert result.to_dict()["states_with_no_rows_to_score"] == ["VA"]
    assert all(s.state != "VA" for s in result.scores)


def test_the_sensitivity_refuses_to_aggregate_over_nothing() -> None:
    """Excluding every independent state would leave a headline number with no states
    behind it, which is worse than no number at all."""
    from pipeline.validation.demand_model import aggregate_excluding

    panels = {state: panel(state) for state in STATES}
    result = run_loso(panels, totals_for(panels), estimators=[ConstantRateBaseline()])
    with pytest.raises(ValidationError, match="leaves no independent state"):
        aggregate_excluding(result, "baseline_household_share",
                            STATE_TOTAL_RECONCILED, STATES)


def test_the_sensitivity_is_computed_from_already_selected_scores() -> None:
    """It takes the estimator as an ARGUMENT and never refits, so it is structurally
    incapable of feeding back into estimator selection."""
    from pipeline.validation.demand_model import aggregate_excluding

    panels = {state: panel(state) for state in STATES}
    result = run_loso(panels, totals_for(panels), estimators=[ConstantRateBaseline()])
    everything = aggregate_excluding(result, "baseline_household_share",
                                     STATE_TOTAL_RECONCILED, ())
    without_one = aggregate_excluding(result, "baseline_household_share",
                                      STATE_TOTAL_RECONCILED, ("VT",))
    assert everything["states_aggregated"] == len(STATES)
    assert without_one["states_aggregated"] == len(STATES) - 1
    assert without_one["excluded_states"] == ["VT"]
    assert everything["diagnostic_only"] is True
