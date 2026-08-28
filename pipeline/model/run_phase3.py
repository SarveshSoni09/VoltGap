"""One command produces every Phase 3 number, as a hashed evidence artifact.

Run with ``python -m pipeline.model.run_phase3``. It reads only cached responses, so it
needs no network and no credentials, and it writes
``docs/evidence/P3-2_demand_model.json``: the leave-one-state-out table, the measured
transformation ladder, the national surface summary, and the uncertainty calibration
curve. The Phase 3 report quotes that file rather than restating remembered numbers.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from pipeline.config.settings import PATHS
from pipeline.model.build_demand import DemandSurface, build_surface
from pipeline.model.demand import observed
from pipeline.model.observed import (
    STATE_FIPS,
    latest_state_totals,
    load_all,
    load_state_totals,
)
from pipeline.model.panel import build_panels, load_area_tables
from pipeline.model.uncertainty import AllocationPenalty, complexity_multipliers
from pipeline.validation.demand_model import (
    STATE_TOTAL_RECONCILED,
    LosoResult,
    calibration_curve,
    nearest_vintage,
    run_loso,
    snapshot_date,
)
from pipeline.validation.washington import (
    HOUSEHOLD_SHARE,
    HUD_METHOD,
    assert_ladder_ordering,
    measure_transformation_ladder,
)

#: 50 states plus the District of Columbia. Puerto Rico is excluded because the AFDC
#: registration series that supplies every reconciliation constraint covers 51
#: jurisdictions and not PR, so a PR tract would have no constraint to reconcile to.
ALL_STATE_FIPS: tuple[str, ...] = tuple(
    f"{code:02d}" for code in range(1, 57) if code not in (3, 7, 14, 43, 52)
)

DEFAULT_OUT = PATHS.evidence / "P3-2_demand_model.json"

#: Measured within-ZIP band error and its overall mean, from the Washington paired
#: comparison in ``docs/evidence/P3-1_wa_allocation_scope_and_error.json``. These set
#: the SHAPE of the allocation penalty across ZIP complexity; the ladder sets its level.
WITHIN_ZIP_BAND_TVD = {"1": 0.004584, "2-3": 0.107645, "4-7": 0.171512, "8+": 0.187192}
WITHIN_ZIP_OVERALL_TVD = 0.179354


def allocation_penalty() -> tuple[AllocationPenalty, list[dict[str, Any]]]:
    """The measured geographic transformation penalty, and the ladder behind it."""
    rungs = measure_transformation_ladder()
    assert_ladder_ordering(rungs)
    by_key = {(r.grain, r.method): r.statewide_tract_tvd for r in rungs}
    penalty = AllocationPenalty(
        statewide_tvd={
            "native_tract": 0.0,
            # The ZIP rung takes the method Phase 3 actually applies at that grain.
            "zip_anchored": by_key[("zip_anchored", HUD_METHOD)],
            "county_anchored": by_key[("county_anchored", HOUSEHOLD_SHARE)],
            "state_total_only": by_key[("state_total_only", HOUSEHOLD_SHARE)],
        },
        complexity_multiplier=complexity_multipliers(
            WITHIN_ZIP_BAND_TVD, WITHIN_ZIP_OVERALL_TVD
        ),
    )
    return penalty, [r.to_dict() for r in rungs]


def constraint_totals(observations: dict[str, Any]) -> dict[str, Any]:
    """One registration total per jurisdiction, at the vintage nearest its observation."""
    series = load_state_totals()
    chosen = latest_state_totals()
    for state, observed_state in observations.items():
        when = snapshot_date(observed_state.vintage_label)
        if when is not None:
            chosen[STATE_FIPS[state]] = nearest_vintage(series[STATE_FIPS[state]], when)
    return chosen


def uncertainty_calibration(surface: DemandSurface, loso: LosoResult,
                            observations: dict[str, Any]) -> list[dict[str, float]]:
    """Does a higher uncertainty score go with larger error where truth is known?

    Washington is the only place a tract-level error can be computed at all, and it is
    the non-independent state, so this curve is **diagnostic, not validation**. It is
    reported with that limitation attached rather than omitted: a calibration check that
    can only be run in one state is still worth more than none.
    """
    observed_tracts = {
        count.geography_id: float(count.bev_count)
        for state, o in observations.items() if state == "WA"
        for count in o.counts
    }
    scores: list[float] = []
    errors: list[float] = []
    for row in surface.estimates:
        truth = observed_tracts.get(row.geoid)
        if truth is None:
            continue
        scores.append(row.uncertainty_score)
        errors.append(abs(row.raw_estimate - truth))
    if not scores:  # pragma: no cover - Washington is always present in a full run
        return []
    return calibration_curve(scores, errors)


def run(states: Sequence[str] = ALL_STATE_FIPS,
        bootstrap_replicates: int = 20) -> dict[str, Any]:
    """Every Phase 3 measurement, from cached inputs only."""
    tables = load_area_tables(states=states)
    observations = load_all()
    panels = build_panels(observations, tables)
    loso = run_loso(panels, load_state_totals())
    penalty, ladder = allocation_penalty()
    surface = build_surface(
        tables["tracts"], panels, observations, constraint_totals(observations),
        penalty, loso.selected_estimator, source_statuses=("confirmed",) * 8,
        bootstrap_replicates=bootstrap_replicates,
    )
    return {
        "phase": 3,
        "pre_registration": "docs/evidence/P3-0_phase3_preregistration.md",
        "target_definition": (
            "battery-electric (BEV) registrations. AFDC publishes Electric (EV) and "
            "Plug-In Hybrid Electric (PHEV) separately and the delivered seed totals "
            "match the BEV column; counting PHEVs would make tract estimates "
            "irreconcilable with the only state constraint available."
        ),
        "observed_sources": {
            state: o.to_dict() for state, o in sorted(observations.items())
        },
        "panels": {state: p.to_dict() for state, p in sorted(panels.items())},
        "demand_model_validation": loso.to_dict(),
        "transformation_ladder": ladder,
        "allocation_penalty": {
            k: round(v, 6) for k, v in sorted(penalty.statewide_tvd.items())
        },
        "national_surface": surface.summary(),
        "uncertainty_calibration_washington_only": uncertainty_calibration(
            surface, loso, observations
        ),
        "selection_mode": STATE_TOTAL_RECONCILED,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--bootstrap", type=int, default=20)
    parser.add_argument("--states", nargs="*", default=list(ALL_STATE_FIPS))
    args = parser.parse_args(argv)
    payload = run(tuple(args.states), args.bootstrap)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    surface = payload["national_surface"]
    assert isinstance(surface, dict)
    print(f"wrote {args.out}")
    print(f"  estimator      {payload['demand_model_validation']['selected_estimator']}")
    print(f"  tracts         {surface['tracts']:,}")
    print(f"  national BEV   {surface['national_bev_estimate']:,}")
    return 0


def observed_totals(rows: Sequence[Any]) -> float:  # pragma: no cover - helper
    return float(np.sum(observed(list(rows))))


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
