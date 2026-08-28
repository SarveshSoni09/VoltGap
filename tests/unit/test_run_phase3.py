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
                    "uncertainty_calibration_washington_only"):
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
    curve = payload["uncertainty_calibration_washington_only"]
    assert isinstance(curve, list)
    assert all(set(row) == {"bin", "n", "mean_uncertainty", "mean_absolute_error"}
               for row in curve)


def test_calibration_needs_washington_rows_to_report_anything() -> None:
    from pipeline.model.build_demand import DemandSurface
    from pipeline.model.reconcile import ProportionalReconciler

    empty = DemandSurface((), "e", (), 0,
                          ProportionalReconciler().reconcile(
                              __import__("numpy").zeros(0), []),
                          {}, 0.0)
    assert uncertainty_calibration(empty, None, {}) == []  # type: ignore[arg-type]
