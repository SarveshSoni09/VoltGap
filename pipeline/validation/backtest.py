"""Building a demand surface from ONLY what existed at a prediction cutoff.

**The backtested model and the deployed model are not the same model.** CLAUDE.md §10.2.3
requires that to be stated and every difference enumerated, and here it is, up front:

*Fitted on* - deployed: sub-state panels, 1 tract-native, 11 ZIP-grain and 4 county-grain
states. Backtest: **51 state-level observations**, because no sub-state registration data
exists at any 2020-2022 cutoff.

*Feature vintage* - deployed: ACS 2024 5-year. Backtest: the contemporaneous release,
ACS 2018 or 2019.

*Tract geography* - deployed: 2020 census tracts. Backtest: **2010** census tracts, which
is what those ACS releases are published on.

*Reconciliation* - deployed: county totals where complete, else state totals. Backtest:
cutoff-valid state totals only.

*Evidence grain* - deployed: native_tract / zip_anchored / county_anchored /
state_total_only. Backtest: **state_total_only everywhere**.

*Spatial output* - deployed: tracts, then H3 with 2020 block-group weights. Backtest: H3
with **2010** block-group weights.

**Why the fit is at state level.** The deployed model learns its coefficients from
sub-state registration panels. Every one of those datasets is a *current* download; none
of them publishes a 2019 or 2020 edition this project could retrieve. Fitting the backtest
on them would learn coefficients from post-cutoff outcomes and hand the backtest the
answer, which is exactly what directive D1 exists to prevent. What *does* exist at each
cutoff is the AFDC annual state registration series, so the backtest fits the same Poisson
specification on 51 state observations and applies it at tract grain.

That is a weaker model than the deployed one, and it should be: it is the model a person
standing at that cutoff could actually have built. Its weakness is a property of the
historical record, not a shortcut.

**A-0.5 still bites.** Phase 1 established the AFDC annual pages are *stable* but not that
they are *contemporaneous* - no capture predates 2022-08-18. If AFDC reconstructed the
annual series retrospectively from later VIN data, a "2019 vintage" used at a 2020 cutoff
carries information that did not exist in 2020. This cannot be ruled out and is not
claimed to be.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from pipeline.model.demand import ModelRow, PoissonRate, design_matrix, fit
from pipeline.model.features import FEATURE_NAMES
from pipeline.validation.vintage import (
    ExcludedFeature,
    VintagedFeature,
    assert_no_leakage,
)

#: Features the deployed model uses that a historical origin cannot. Enumerated as data
#: because §10.2.1 requires every exclusion listed, and prose drifts from what ran.
KNOWN_EXCLUSIONS: tuple[ExcludedFeature, ...] = (
    ExcludedFeature(
        "home_charging_access", "nrel_home_charging",
        "single undated NREL vintage, and Phase 0 established it is a parametric "
        "scenario surface rather than a dated observation, so no cutoff-appropriate "
        "edition exists to reconstruct (§7.2, amendment A7)"),
    ExcludedFeature(
        "sub_state_registration_panels", "atlas_ev_registrations / wa_ev_population",
        "every sub-state registration source is a CURRENT download; none publishes a "
        "2019-2021 edition. Fitting on them would learn coefficients from post-cutoff "
        "outcomes, which is the leakage D1 forbids"),
    ExcludedFeature(
        "existing_charger_features", "afdc_charging_units",
        "forbidden in the primary demand model at every cutoff by directive D2, not "
        "by vintage. Supply is an outcome of prior investment; predicting demand from "
        "it launders historical deployment into need"),
    ExcludedFeature(
        "hud_usps_zip_tract_crosswalk", "hud_usps_zip_tract",
        "the current crosswalk is not used at any historical origin. The backtest fits "
        "at state level and allocates tracts to H3 cells directly, so no ZIP->tract "
        "transformation occurs and the question of whether a current crosswalk counts "
        "as stable geography infrastructure does not have to be answered"),
    ExcludedFeature(
        "tiger_2024_road_network", "census_tiger_prisecroads",
        "the Phase 4 road-proximity candidate filter is NOT applied to any historical "
        "ranking. TIGER 2024 postdates every cutoff, and the backtest ranks cells by "
        "cutoff-valid modelled demand rather than by a filtered candidate set"),
)


@dataclass(frozen=True)
class HistoricalSurface:
    """A cutoff-valid demand surface: per-tract BEV estimates and how they were made."""

    cutoff: date
    acs_year: int
    tract_geography: str
    registration_vintage: str
    tracts: int
    states: int
    estimates: Mapping[str, float]
    households: Mapping[str, float]
    population: Mapping[str, float]
    state_total: float
    reconciliation_max_abs_error: float
    training_observations: int
    unreconciled: Mapping[str, float]

    def to_dict(self) -> dict[str, object]:
        return {
            "prediction_cutoff": self.cutoff.isoformat(),
            "acs_api_year": self.acs_year,
            "tract_geography": self.tract_geography,
            "state_registration_vintage": self.registration_vintage,
            "tracts": self.tracts,
            "states": self.states,
            "training_observations": self.training_observations,
            "reconciled_state_total_bev": round(self.state_total, 2),
            "reconciliation_max_abs_error_per_state": round(
                self.reconciliation_max_abs_error, 9),
            "estimate_method": "modelled",
            "evidence_grain": "state_total_only",
            "note": (
                "fitted on 51 state-level observations because no sub-state "
                "registration data exists at this cutoff; the backtested model and the "
                "deployed model are NOT the same model (§10.2.3)"),
        }


def state_rows(
    tract_rows: Sequence[ModelRow], totals: Mapping[str, float]
) -> list[ModelRow]:
    """Aggregate tract features to state level, household-weighted.

    A state's feature value is the household-weighted mean of its tracts', which is what
    makes a state-level fit comparable to a tract-level application: the same feature
    means the same thing at both grains.
    """
    by_state: dict[str, list[ModelRow]] = {}
    for row in tract_rows:
        by_state.setdefault(row.state, []).append(row)
    out = []
    for state, rows in sorted(by_state.items()):
        if state not in totals:
            continue
        weight = np.array([r.households for r in rows], dtype=float)
        total_households = float(weight.sum())
        if total_households <= 0:
            continue
        matrix = design_matrix(rows)
        means = (matrix * weight[:, None]).sum(axis=0) / total_households
        out.append(ModelRow(
            state=state, geography="state", geoid=state,
            households=total_households,
            population=float(sum(r.population for r in rows)),
            features=dict(zip(FEATURE_NAMES, means.tolist(), strict=True)),
            observed_bev=float(totals[state]),
        ))
    return out


def build_historical_surface(
    tract_rows: Sequence[ModelRow],
    state_totals: Mapping[str, float],
    cutoff: date,
    acs_year: int,
    tract_geography: str,
    registration_vintage: str,
    feature_vintage: date,
    acs_source_id: str,
    acs_provenance: str,
) -> HistoricalSurface:
    """Fit at state level on cutoff-valid data, apply at tract grain, reconcile.

    ``assert_no_leakage`` runs **before** the fit, on the actual feature columns, so a
    mis-declared vintage stops the run rather than producing a plausible number.
    """
    matrix = design_matrix(tract_rows)
    assert_no_leakage(
        [VintagedFeature(name=name, values=pd.Series(matrix[:, index], dtype=float),
                         feature_vintage=feature_vintage, source_id=acs_source_id,
                         provenance=acs_provenance)
         for index, name in enumerate(FEATURE_NAMES)],
        cutoff,
    )

    training = state_rows(tract_rows, state_totals)
    model = fit(PoissonRate(), training)
    raw = model.predict_counts(tract_rows)

    unreconciled = {row.geoid: float(value)
                    for row, value in zip(tract_rows, raw, strict=True)}
    estimates = dict(unreconciled)
    worst = 0.0
    for state, target in sorted(state_totals.items()):
        members = [r.geoid for r in tract_rows if r.state == state]
        if not members:
            continue
        subtotal = sum(unreconciled[g] for g in members)
        if subtotal <= 0:
            # No modelled propensity anywhere in the state: fall back to household
            # share so the constraint is still met, and it is visible as a fallback
            # rather than silently producing zeros (directive D8).
            household_total = sum(
                r.households for r in tract_rows if r.state == state) or 1.0
            for row in tract_rows:
                if row.state == state:
                    estimates[row.geoid] = target * row.households / household_total
        else:
            scale = target / subtotal
            for geoid in members:
                estimates[geoid] = unreconciled[geoid] * scale
        worst = max(worst, abs(sum(estimates[g] for g in members) - target))

    return HistoricalSurface(
        cutoff=cutoff, acs_year=acs_year, tract_geography=tract_geography,
        registration_vintage=registration_vintage,
        tracts=len(tract_rows), states=len({r.state for r in tract_rows}),
        estimates=estimates,
        households={r.geoid: r.households for r in tract_rows},
        population={r.geoid: r.population for r in tract_rows},
        state_total=sum(estimates.values()),
        reconciliation_max_abs_error=worst,
        training_observations=len(training),
        unreconciled=unreconciled,
    )
