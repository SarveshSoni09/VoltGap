"""Historical deployment alignment: gain curves, lift, and the claims it must not make.

This validation asks whether the model assigned higher priority to locations where
charging infrastructure was subsequently deployed. It does NOT establish that those
deployments were optimal, that the model is causally correct, that operators should have
followed it, or that any future site is validated. Several tests below exist purely to
keep those disclaimers attached to the number.
"""

from __future__ import annotations

from datetime import date

import pytest

from pipeline.validation.deployment_alignment import (
    DECILES,
    Deployment,
    GainPoint,
    OriginAlignment,
    RankingResult,
    gain_curve,
    random_ranking,
    ranked_by,
    score_ranking,
)

CELLS = [f"cell_{i:02d}" for i in range(10)]


def test_the_gain_curve_has_a_point_at_every_decile() -> None:
    assert DECILES == (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)


def test_a_perfect_ranking_captures_everything_in_the_top_decile() -> None:
    weights = {"cell_00": 10.0}
    curve = gain_curve(CELLS, weights)
    assert curve[0][2] == pytest.approx(1.0)
    assert curve[-1][2] == pytest.approx(1.0)


def test_the_full_ranking_always_captures_everything() -> None:
    """A sanity invariant: the last decile is the whole list."""
    weights = {c: float(i + 1) for i, c in enumerate(CELLS)}
    assert gain_curve(CELLS, weights)[-1][2] == pytest.approx(1.0)


def test_a_curve_is_monotone_non_decreasing() -> None:
    weights = {c: float(i + 1) for i, c in enumerate(CELLS)}
    captured = [c for _, _, c in gain_curve(CELLS, weights)]
    assert captured == sorted(captured)


def test_a_deployment_in_a_cell_that_was_never_ranked_counts_as_a_miss() -> None:
    """It was not a candidate, so building there is a miss, not an exclusion. Dropping
    it would quietly flatter every ranking."""
    weights = {"cell_00": 1.0, "somewhere_unranked": 9.0}
    assert gain_curve(CELLS, weights)[-1][2] == pytest.approx(0.1)


def test_no_deployments_at_all_gives_zero_capture_rather_than_dividing_by_zero() -> None:
    curve = gain_curve(CELLS, {})
    assert [c for _, _, c in curve] == [0.0] * 10


def test_ranking_by_value_is_descending_and_deterministic_on_ties() -> None:
    values = {"a": 1.0, "b": 3.0, "c": 3.0, "d": 2.0}
    assert ranked_by(values, ["a", "b", "c", "d"]) == ["b", "c", "d", "a"]


def test_a_cell_with_no_value_ranks_last_rather_than_being_dropped() -> None:
    assert ranked_by({"b": 1.0}, ["a", "b"]) == ["b", "a"]


def test_the_random_baseline_is_seeded_so_it_reproduces() -> None:
    assert random_ranking(CELLS, 2020) == random_ranking(CELLS, 2020)
    assert random_ranking(CELLS, 2020) != random_ranking(CELLS, 2021)
    assert sorted(random_ranking(CELLS, 2020)) == sorted(CELLS)


def test_ports_and_stations_are_scored_separately() -> None:
    """G1: a station record is one network's presence at a site, not a unit of capacity.
    A ranking can capture many small stations and little actual capacity, so the two
    curves must be able to disagree."""
    result = score_ranking(
        "m", CELLS,
        stations={"cell_00": 1.0, "cell_09": 1.0},
        ports={"cell_00": 1.0, "cell_09": 99.0},
        dcfc={"cell_00": 0.0, "cell_09": 50.0})
    top = result.gain[0]
    assert top.cells == 1
    assert top.stations_captured == pytest.approx(0.5)
    assert top.ports_captured == pytest.approx(0.01)
    assert top.dcfc_ports_captured == pytest.approx(0.0)
    assert result.top_decile_stations != result.top_decile_ports


def alignment(model_top: float, random_top: float, population_top: float
              ) -> OriginAlignment:
    def flat(name: str, value: float) -> RankingResult:
        return RankingResult(name=name, cells_ranked=10, gain=(
            GainPoint(0.1, 1, value, value, value),))
    return OriginAlignment(
        origin="2021", cutoff=date(2021, 1, 1), window_end=date(2023, 1, 1),
        cells_evaluated=10, deployments=100, deployment_ports=500.0,
        deployment_dcfc_ports=50.0, states_covered=51,
        model=flat("model", model_top),
        baselines=(flat("random", random_top), flat("population", population_top)),
        reconstruction_confidence="middle", vintages={})


def test_lift_is_the_model_over_the_baseline() -> None:
    assert alignment(0.4, 0.1, 0.2).lift("random") == pytest.approx(4.0)
    assert alignment(0.4, 0.1, 0.2).lift("population") == pytest.approx(2.0)


def test_a_model_that_loses_to_a_baseline_reports_lift_below_one() -> None:
    """Reported, not suppressed. Weak results are results."""
    assert alignment(0.05, 0.1, 0.2).lift("random") == pytest.approx(0.5)
    assert alignment(0.05, 0.1, 0.2).lift("population") == pytest.approx(0.25)


def test_a_baseline_that_captured_nothing_does_not_divide_by_zero() -> None:
    assert alignment(0.4, 0.0, 0.2).lift("random") == float("inf")
    assert alignment(0.0, 0.0, 0.2).lift("random") == 1.0


def test_the_published_record_carries_the_disclaimers_with_the_number() -> None:
    """§10.2 and D3. The caveat travels with the result, in the artifact itself, so a
    reader of the JSON alone cannot take alignment for proof of optimality."""
    payload = alignment(0.4, 0.1, 0.2).to_dict()
    assert payload["subsequent_deployments_available"] == 100
    assert payload["geographic_coverage_states"] == 51
    disclaimers = payload["what_this_does_not_measure"]
    assert isinstance(disclaimers, list)
    joined = " ".join(disclaimers)
    assert "were optimal" in joined
    assert "causally correct" in joined
    assert "should have followed" in joined
    assert "reproduces industry deployment behaviour" in joined
    assert "priority to locations where" in str(payload["what_this_measures"])


def test_the_record_reports_ports_lift_as_well_as_station_lift() -> None:
    payload = alignment(0.4, 0.1, 0.2).to_dict()
    assert "lift_vs_random_ports" in payload
    assert "lift_vs_population_ports" in payload


def test_a_deployment_carries_its_date_cell_and_capacity() -> None:
    d = Deployment("42", "cell_00", date(2021, 6, 1), ports=4.0, dcfc_ports=2.0)
    assert d.opened.year == 2021
    assert d.ports == 4.0
