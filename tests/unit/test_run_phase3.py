"""The Phase 3 driver: one command reproduces every published number, offline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.model.ablation import DCFC_LEVEL
from pipeline.model.demand import ConstantRateBaseline
from pipeline.model.run_phase3 import (
    ALL_STATE_FIPS,
    WITHIN_ZIP_BAND_TVD,
    WITHIN_ZIP_OVERALL_TVD,
    allocation_penalty,
    constraint_totals,
    main,
    run,
    uncertainty_calibration,
)
from tests.unit.test_ablation import snapshot, station


def test_the_jurisdiction_list_matches_the_constraint_series() -> None:
    """A tract with no published state total would have nothing to reconcile to."""
    assert len(ALL_STATE_FIPS) == 51
    assert "72" not in ALL_STATE_FIPS  # Puerto Rico: no AFDC registration series


def test_the_measured_penalty_respects_the_predicted_ordering() -> None:
    penalty, ladder = allocation_penalty()
    assert penalty.statewide_tvd["native_tract"] == 0.0
    assert (penalty.statewide_tvd["zip_anchored"]
            < penalty.statewide_tvd["county_anchored"]
            < penalty.statewide_tvd["state_total_only"])
    assert any(rung["method"] == "hud_res_ratio" for rung in ladder)


def test_the_band_multipliers_come_from_the_published_measurement() -> None:
    assert set(WITHIN_ZIP_BAND_TVD) == {"1", "2-3", "4-7", "8+"}
    assert pytest.approx(0.179354) == WITHIN_ZIP_OVERALL_TVD
    penalty, _ = allocation_penalty()
    assert (penalty.for_row("zip_anchored", "1")
            < penalty.for_row("zip_anchored", "8+"))


def test_each_state_is_constrained_at_the_vintage_nearest_its_own_snapshot() -> None:
    from pipeline.model.observed import load_all

    observations = load_all(("NC", "VT"))
    chosen = constraint_totals(observations)
    # North Carolina's snapshot is June 2024, so the 2025 vintage is not the right one.
    assert chosen["37"].vintage == "2023"
    assert chosen["50"].vintage == "2025"
    assert len(chosen) == 51


def tiny_supply(tmp_path: Path) -> Path:
    """A two-station snapshot, so the ablation does not read the 303 MB national file."""
    return snapshot(tmp_path, [station("05401", DCFC_LEVEL, 4),
                               station("98101", DCFC_LEVEL, 8, station_id=2)])


def test_the_driver_produces_every_published_section(tmp_path: Path) -> None:
    payload = run(states=("50", "53"), bootstrap_replicates=2,
                 supply_snapshot=tiny_supply(tmp_path),
                 estimators=[ConstantRateBaseline()])
    assert payload["phase"] == 3
    assert "battery-electric" in str(payload["target_definition"])
    for section in ("observed_sources", "panels", "demand_model_validation",
                    "transformation_ladder", "allocation_penalty",
                    "national_surface",
                    "washington_uncertainty_error_diagnostic",
                    "new_jersey_sensitivity", "feature_vintage"):
        assert section in payload, section
    validation = payload["demand_model_validation"]
    assert isinstance(validation, dict)
    assert validation["validation_term"] == "demand model validation"
    assert "WA" in validation["excluded_from_independent_aggregate"]


def test_the_artifact_is_json_serialisable_and_written_where_asked(
    tmp_path: Path,
) -> None:
    out = tmp_path / "evidence.json"
    assert main(["--out", str(out), "--bootstrap", "2", "--states", "50", "53",
                 "--supply-snapshot", str(tiny_supply(tmp_path))]) == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["national_surface"]["tracts"] > 0
    assert written["selection_mode"] == "state_total_reconciled"


def test_the_calibration_curve_is_marked_washington_only(tmp_path: Path) -> None:
    """Washington is the non-independent state, so the curve is diagnostic, not
    validation, and it is labelled that way in the artifact's own key."""
    payload = run(states=("50", "53"), bootstrap_replicates=2,
                 supply_snapshot=tiny_supply(tmp_path),
                 estimators=[ConstantRateBaseline()])
    diagnostic = payload["washington_uncertainty_error_diagnostic"]
    assert diagnostic["is_empirical_calibration"] is False
    assert "NOT empirically calibrated" in diagnostic["interpretation"]
    curve = diagnostic["curve"]
    assert isinstance(curve, list)
    assert all(set(row) == {"bin", "n", "mean_uncertainty", "mean_absolute_error"}
               for row in curve)


def test_calibration_needs_washington_rows_to_report_anything() -> None:
    from pipeline.model.build_demand import ConstraintAccounting, DemandSurface
    from pipeline.model.reconcile import ProportionalReconciler

    empty = DemandSurface(ConstraintAccounting(0.0, 0.0, 0.0, 0.0, {}), (), "e", (), 0,
                          ProportionalReconciler().reconcile(
                              __import__("numpy").zeros(0), []),
                          {}, 0.0)
    assert uncertainty_calibration(empty, None, {}) == []  # type: ignore[arg-type]


# --- the fragility description ------------------------------------------------------

def test_fragility_names_a_changed_winner() -> None:
    from pipeline.model.run_phase3 import _fragility

    text = _fragility(["a", "b"], ["b", "a"], ["a", "b"], ["b", "a"])
    assert "WINNER changes" in text and "a -> b" in text
    assert "retained regardless" in text


def test_fragility_names_a_changed_model_ordering_under_an_unchanged_winner() -> None:
    from pipeline.model.run_phase3 import _fragility

    text = _fragility(["a", "b", "c"], ["a", "c", "b"], ["a", "b", "c"], ["a", "c", "b"])
    assert "AMONG MODELS" in text


def test_fragility_says_so_when_only_the_baselines_swap() -> None:
    """A bare 'not stable' would be true and useless when two floors trade places."""
    from pipeline.model.run_phase3 import _fragility

    text = _fragility(["m", "base_x", "base_y"], ["m", "base_y", "base_x"],
                      ["m"], ["m"])
    assert "BASELINES" in text
    assert "floor to clear" in text


def test_fragility_reports_a_stable_ordering() -> None:
    from pipeline.model.run_phase3 import _fragility

    assert _fragility(["a", "b"], ["a", "b"], ["a"], ["a"]) == (
        "the candidate ordering is stable to removing New Jersey")


# --- the tract-set reconciliation ---------------------------------------------------

def test_the_tract_set_reconciliation_names_what_entered_and_what_left(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tract count that changes between vintages must be named tract by tract."""
    from pipeline.model.panel import build_area_table
    from pipeline.model.run_phase3 import tract_set_reconciliation
    from tests.unit.test_panel import acs_row

    def table(geoids: list[str]) -> dict[str, object]:
        return {
            "tracts": build_area_table([acs_row(g) for g in geoids], "tracts",
                                       dict.fromkeys(geoids, 5.0)),
            "zcta": build_area_table([acs_row("98101")], "zcta", {"98101": 5.0}),
            "county": build_area_table([acs_row("53033")], "county", {"53033": 5.0}),
        }

    previous = table(["53033000100", "53033000200"])
    production = table(["53033000100", "53033000300"])
    monkeypatch.setattr("pipeline.model.run_phase3.load_area_tables",
                        lambda states, year: previous)
    recon = tract_set_reconciliation(production, ("53",))
    assert recon["tracts_previous"] == 2
    assert recon["tracts_current"] == 2
    assert recon["intersection"] == 1
    assert [row["geoid"] for row in recon["entered"]] == ["53033000300"]
    assert [row["geoid"] for row in recon["left"]] == ["53033000200"]
    assert recon["entered"][0]["state_fips"] == "53"
    assert recon["entered"][0]["county_fips"] == "53033"
    assert recon["left"][0]["households"] == 100.0
