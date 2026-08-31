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
from collections.abc import Mapping, Sequence
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
from pipeline.sources.census_acs import ACS_YEAR, HISTORICAL_ACS_YEARS
from pipeline.validation.demand_model import (
    STATE_TOTAL_RECONCILED,
    LosoResult,
    aggregate_excluding,
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
    """The Washington uncertainty-error diagnostic. **Not a calibration result.**

    Washington is the only place a tract-level error can be computed at all, and it is
    also the non-independent state, so this is a diagnostic and nothing more. Higher
    uncertainty identifies the highest-error quintile, but error is not monotonic across
    the remaining bins, so the score is **not empirically calibrated**. The curve is
    reported with that limitation attached rather than omitted, and the weights are never
    retuned in response to it - doing so would destroy the only thing the check was for.
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


def _fragility(rank_with: Sequence[str], rank_without: Sequence[str],
               models_with: Sequence[str], models_without: Sequence[str]) -> str:
    """Describe an ordering change precisely, rather than as a bare boolean.

    "The ranking is not stable" is true but useless if the only movement is two
    baselines swapping by 0.00015 while every real model holds its place. What matters
    is whether the *selected* estimator or the ordering *among models* moves.
    """
    if rank_with[0] != rank_without[0]:
        return (f"the WINNER changes without New Jersey: {rank_with[0]} -> "
                f"{rank_without[0]}. The estimator selected under the original "
                "pre-registered rule is retained regardless")
    if list(models_with) != list(models_without):
        return ("the winner is unchanged but the ordering AMONG MODELS moves without "
                "New Jersey")
    if list(rank_with) != list(rank_without):
        return ("the winner and the model ordering are both unchanged; only the two "
                "BASELINES swap places, which does not bear on selection since a "
                "baseline is a floor to clear rather than a candidate that can win")
    return "the candidate ordering is stable to removing New Jersey"


def _new_jersey_sensitivity(loso: LosoResult) -> dict[str, Any]:
    """The independent aggregate with and without New Jersey, for **every candidate**.

    New Jersey's observed total is 21.65% below the comparable AFDC figure and its latest
    snapshot carries one distinct registration date, but corrected domain rule G9 forbids
    marking a state low-confidence on statistical unusualness alone. It stays
    ``flagged_for_review`` and stays in the panel.

    **The precise claim.** New Jersey **was** part of the aggregate that selected the
    estimator, so it could in principle have influenced candidate ranking. What is true is
    narrower and is stated as such: **this post-selection sensitivity was not used to
    alter estimator selection.** It reuses already-generated leave-one-state-out scores -
    no refit, no reselection - and the estimator chosen under the original pre-registered
    rule is retained regardless of what the table shows.
    """
    mode = loso.selection_mode
    candidates = sorted({s.estimator for s in loso.scores})

    def wape_of(result: dict[str, Any]) -> float:
        value = result["weighted_wape"]
        assert isinstance(value, float)
        return value

    with_nj = {c: wape_of(aggregate_excluding(loso, c, mode, ()))
               for c in candidates}
    without_nj = {c: wape_of(aggregate_excluding(loso, c, mode, ("NJ",)))
                  for c in candidates}

    def rank(table: dict[str, float]) -> list[str]:
        return sorted(candidates, key=lambda c: table[c])

    rank_with, rank_without = rank(with_nj), rank(without_nj)
    models = [c for c in candidates if not c.startswith("baseline_")]
    model_rank_with = [c for c in rank_with if c in models]
    model_rank_without = [c for c in rank_without if c in models]
    return {
        "new_jersey_status": "flagged_for_review",
        "not_marked_low_confidence_because": (
            "corrected domain rule G9 requires corroborating evidence of a vintage, "
            "coverage, definition or source-quality problem; a statistical anomaly "
            "alone is not enough"
        ),
        "interpretation": (
            "New Jersey WAS included in the aggregate that selected the estimator and "
            "could therefore in principle have influenced candidate ranking. The precise "
            "claim is narrower: this post-selection sensitivity was not used to alter "
            "estimator selection. It reuses already-generated LOSO scores - no refit, no "
            "reselection - and the estimator chosen under the original pre-registered "
            "rule is retained regardless of what this table shows."
        ),
        "selected_under_the_pre_registered_rule": loso.selected_estimator,
        "per_candidate": {
            candidate: {
                "with_new_jersey": round(with_nj[candidate], 6),
                "without_new_jersey": round(without_nj[candidate], 6),
                "delta": round(without_nj[candidate] - with_nj[candidate], 6),
            }
            for candidate in candidates
        },
        "ranking_with_new_jersey": rank_with,
        "ranking_without_new_jersey": rank_without,
        "ranking_changes_without_new_jersey": rank_with != rank_without,
        "model_ranking_changes_without_new_jersey": (
            model_rank_with != model_rank_without),
        "selected_estimator_changes_without_new_jersey": (
            rank_with[0] != rank_without[0]),
        "selection_fragility": _fragility(rank_with, rank_without,
                                          model_rank_with, model_rank_without),
        "with_new_jersey": round(with_nj[loso.selected_estimator], 6),
        "without_new_jersey": round(without_nj[loso.selected_estimator], 6),
        "delta_weighted_wape": round(
            without_nj[loso.selected_estimator]
            - with_nj[loso.selected_estimator], 6),
        "used_to_alter_estimator_selection": False,
        "affected_confidence_tiers": False,
    }


def tract_set_reconciliation(
    production: Mapping[str, Any],
    states: Sequence[str],
    historical_year: int | None = None,
) -> dict[str, Any]:
    """Account for every tract that entered or left the surface between ACS vintages.

    A national tract count that changes between releases is a fact about the Census, not
    noise, and it must be named tract by tract. "Identical area counts" was claimed once
    on the strength of a **bounded** Rhode Island retrieval check plus national ZCTA and
    county counts - it was never a national tract-count comparison, and the national
    tract count had in fact changed by one.
    """
    year = historical_year or HISTORICAL_ACS_YEARS[0]
    previous = load_area_tables(states=states, year=year)
    old, new = set(previous["tracts"].rows), set(production["tracts"].rows)
    entered, left = sorted(new - old), sorted(old - new)

    def profile(geoid: str, table: Any) -> dict[str, Any]:
        row = table["tracts"].rows[geoid]
        return {
            "geoid": geoid,
            "state_fips": geoid[:2],
            "county_fips": geoid[:5],
            "population": row.population,
            "households": row.households,
        }

    return {
        "comparison": f"ACS {year} 5-year against ACS {ACS_YEAR} 5-year",
        "tracts_previous": len(old),
        "tracts_current": len(new),
        "intersection": len(old & new),
        "entered_count": len(entered),
        "left_count": len(left),
        "entered": [profile(g, production) for g in entered],
        "left": [profile(g, previous) for g in left],
        "zcta_previous": len(previous["zcta"].rows),
        "zcta_current": len(production["zcta"].rows),
        "county_previous": len(previous["county"].rows),
        "county_current": len(production["county"].rows),
    }


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
    # Washington's geography ledger checks each tract against real Census geography, so
    # a well-formed GEOID naming no actual tract is caught rather than counted.
    observations = load_all(known_tracts=sorted(tables["tracts"].rows))
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
        "feature_vintage": {
            "current_production": f"ACS {ACS_YEAR} 5-year",
            "historical_retained_for_phase_5": [
                f"ACS {y} 5-year" for y in HISTORICAL_ACS_YEARS
            ],
            "note": (
                "Directive D1 requires feature_vintage <= prediction_cutoff. The "
                "production surface uses the latest release; Phase 5's rolling origins "
                "must use the ACS release contemporaneous with each cutoff, which is "
                "why the older vintages stay cached and are never overwritten."
            ),
        },
        "national_surface": surface.summary(),
        "tract_set_reconciliation": tract_set_reconciliation(tables, states),
        "supply_feature_ablation": supply_feature_ablation(
            dict(panels), dict(load_state_totals()), supply_snapshot
        ),
        "washington_uncertainty_error_diagnostic": {
            "is_empirical_calibration": False,
            "interpretation": (
                "Higher uncertainty identifies the highest-error quintile, but error is "
                "not monotonic across the remaining bins. The current uncertainty score "
                "is therefore NOT empirically calibrated; this diagnostic only provides "
                "limited evidence that the score identifies some high-error "
                "observations."
            ),
            "why_washington_only": (
                "Washington is the only source reporting registrations at tract grain, "
                "so it is the only place a tract-level error can be computed. It is "
                "also the non-independent preprocessing-selection state."
            ),
            "curve": uncertainty_calibration(surface, loso, observations),
        },
        "new_jersey_sensitivity": _new_jersey_sensitivity(loso),
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
