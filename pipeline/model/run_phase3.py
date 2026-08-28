"""One command produces every Phase 3 number, as a hashed evidence artifact.

Run with ``python -m pipeline.model.run_phase3``. It reads only cached responses, so it
needs no network and no credentials, and it writes
``docs/evidence/P3-2_demand_model.json``: the leave-one-state-out table, the measured
transformation ladder, the national surface summary, and the uncertainty calibration
curve. The Phase 3 report quotes that file rather than restating remembered numbers.
"""

from __future__ import annotations

import argparse
import functools
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pipeline.config.settings import PATHS
from pipeline.model.ablation import (
    ABLATION_FEATURE_NAMES,
    SUPPLY_FEATURE_NAMES,
    load_supply_by_zip,
    zip_grain_panels,
)
from pipeline.model.build_demand import DemandSurface, build_surface
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


@functools.lru_cache(maxsize=1)
def allocation_penalty() -> tuple[AllocationPenalty, tuple[dict[str, Any], ...]]:
    """The measured geographic transformation penalty, and the ladder behind it.

    Cached because measuring it reads Washington's full 294,193-record vehicle file, and
    every caller in one process wants the same answer from the same inputs.
    """
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
    return penalty, tuple(r.to_dict() for r in rungs)


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


def supply_feature_ablation(
    panels: dict[str, Any], state_totals: dict[str, Any],
    supply_snapshot: Path | None = None,
) -> dict[str, Any]:
    """The one place supply features may appear, run and reported separately.

    CLAUDE.md §15.5 makes this a Phase 3 acceptance criterion, and §18 anti-pattern 5
    explains why it is worth measuring: supply features *improve fit*, and that is
    exactly the problem. A number makes the case for the prohibition better than a
    paragraph does.

    **Nothing here feeds the published surface.** It is a comparison over the same
    eleven ZIP-grain states, with and without charger counts, port counts and station
    density, and the result is published under its own heading.
    """
    from pipeline.model.demand import candidate_estimators

    supply = load_supply_by_zip(supply_snapshot)
    primary, ablated = zip_grain_panels(panels, supply)
    if len(primary) <= 3:  # pragma: no cover - eleven ZIP-grain states always qualify
        return {"status": "not run: too few ZIP-grain states"}
    estimators = [e for e in candidate_estimators()
                  if e.name in ("poisson_glm", "ridge_log_rate")]
    without = run_loso(primary, state_totals, estimators=estimators)
    with_supply = run_loso(
        ablated, state_totals, estimators=estimators,
        feature_names=ABLATION_FEATURE_NAMES,
    )
    return {
        "in_sample_wape": _in_sample_wape(primary, ablated),
        "WARNING": (
            "SUPPLY-FEATURE ABLATION ONLY. These features are forbidden in the primary "
            "demand model by directive D2: existing infrastructure is an OUTCOME of "
            "prior investment decisions, so using it to predict demand and then siting "
            "from that demand launders historical deployment patterns into 'need'. "
            "This result is not used for anything and must never be quoted as the "
            "model's performance."
        ),
        "scope": "the eleven ZIP-grain states, which is where AFDC ZIPs join directly",
        "supply_features_added": list(SUPPLY_FEATURE_NAMES),
        "aggregate_weighted_wape_without_supply_features":
            without.to_dict()["aggregate_weighted_wape"],
        "aggregate_weighted_wape_with_supply_features":
            with_supply.to_dict()["aggregate_weighted_wape"],
    }


def _in_sample_wape(primary: dict[str, Any],
                    ablated: dict[str, Any]) -> dict[str, float]:
    """Fit and score on the same rows, with and without supply features.

    CLAUDE.md §18 anti-pattern 5 states flatly that supply features *will* improve fit,
    and that this is the problem rather than the point. Reporting in-sample fit beside
    out-of-state transfer is what makes that visible: if fit improves while transfer
    degrades, the features are carrying state-specific deployment history rather than
    demand.
    """
    from pipeline.model.demand import PoissonRate, observed, wape
    from pipeline.model.demand import fit as fit_model

    out: dict[str, float] = {}
    for label, panels in (("without_supply_features", primary),
                          ("with_supply_features", ablated)):
        rows = [row for panel in panels.values() for row in panel.rows]
        names = (ABLATION_FEATURE_NAMES if label == "with_supply_features"
                 else None)
        model = (fit_model(PoissonRate(), rows, names) if names
                 else fit_model(PoissonRate(), rows))
        out[label] = wape(observed(rows), model.predict_counts(rows))
    return {k: round(v, 6) for k, v in out.items()}


def run(states: Sequence[str] = ALL_STATE_FIPS,
        bootstrap_replicates: int = 20,
        supply_snapshot: Path | None = None,
        estimators: Sequence[Any] | None = None) -> dict[str, Any]:
    """Every Phase 3 measurement, from cached inputs only.

    ``estimators`` narrows the candidate set. The published run leaves it unset, so all
    five candidates compete under the pre-registered rule; a test may pass one cheap
    candidate to exercise the plumbing without refitting the whole leaderboard.
    """
    tables = load_area_tables(states=states)
    observations = load_all()
    panels = build_panels(observations, tables)
    loso = run_loso(panels, load_state_totals(), estimators=estimators)
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
        "transformation_ladder": list(ladder),
        "allocation_penalty": {
            k: round(v, 6) for k, v in sorted(penalty.statewide_tvd.items())
        },
        "national_surface": surface.summary(),
        "supply_feature_ablation": supply_feature_ablation(
            dict(panels), dict(load_state_totals()), supply_snapshot
        ),
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
    parser.add_argument("--supply-snapshot", type=Path, default=None,
                        help="AFDC station snapshot for the ablation; defaults to the "
                             "cached national pull")
    args = parser.parse_args(argv)
    payload = run(tuple(args.states), args.bootstrap, args.supply_snapshot)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    surface = payload["national_surface"]
    assert isinstance(surface, dict)
    print(f"wrote {args.out}")
    print(f"  estimator      {payload['demand_model_validation']['selected_estimator']}")
    print(f"  tracts         {surface['tracts']:,}")
    print(f"  national BEV   {surface['national_bev_estimate']:,}")
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
