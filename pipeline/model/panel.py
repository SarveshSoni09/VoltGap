"""Assembling the modelling panel: observed counts joined to ACS features.

Each state contributes rows **at the geography it actually publishes**: eleven states at
USPS ZIP Code matched to the like-numbered ZCTA, three at county, Washington at census
tract. ACS publishes features directly at all three summary levels, so no registration
count is ever allocated to a finer geography in order to be fitted against. That is the
whole point: a crosswalk with a measured 17.94% EV-weighted total variation distance
must not be used to manufacture the labels a model is then scored on.

**The out-of-state mailing ZIP defect.** A state DMV export can key a vehicle by a ZIP
Code outside the state. Oregon's latest snapshot carries 310 such ZIPs - 00907 in Puerto
Rico, 01742 in Massachusetts, 10010 in Manhattan - holding 1,253 vehicles between them.
Joining those to their like-numbered ZCTA imported 3.5 million out-of-state households,
62% of Oregon's matched exposure, behind ZIPs holding almost no vehicles. The model then
predicted large EV counts in places the state has no residents, and Oregon's rank
correlation between predicted and observed went *negative*. Every ZIP is therefore
checked against :func:`~pipeline.spatial.crosswalk.zcta_state_index` and one outside the
state is excluded **by name**, its vehicles counted in the ledger rather than dropped:
they are part of the state total but cannot be attributed to any in-state area.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from pipeline.config.settings import PATHS
from pipeline.discovery.cache import Fetcher, ReplayFetcher
from pipeline.model.demand import ModelRow
from pipeline.model.features import (
    FEATURE_NAMES,
    FeatureRow,
    build_feature_rows,
    impute,
    load_land_area_km2,
)
from pipeline.model.observed import STATE_FIPS, StateObservations
from pipeline.sources.census_acs import (
    ACS_YEAR,
    COUNTY,
    TRACT,
    ZCTA,
    AcsSource,
)
from pipeline.spatial.crosswalk import zcta_state_index
from pipeline.spatial.geography import SourceGeography
from pipeline.validation.scope import ExclusionLedger

#: Which ACS summary level supplies features for a source geography.
GEOGRAPHY_FOR_SOURCE: Mapping[SourceGeography, str] = {
    SourceGeography.USPS_ZIP: "zcta",
    SourceGeography.COUNTY: "county",
    SourceGeography.TRACT: "tracts",
}


class PanelError(ValueError):
    """The modelling panel cannot be assembled as declared."""


@dataclass(frozen=True)
class AreaTable:
    """ACS features for one summary level, keyed by GEOID."""

    geography: str
    rows: Mapping[str, FeatureRow]
    imputed_counts: Mapping[str, int]
    medians: Mapping[str, float]
    filled: Mapping[str, Mapping[str, float]]

    def __len__(self) -> int:
        return len(self.rows)


def build_area_table(
    staged: Sequence[Mapping[str, str]],
    geography: str,
    land_areas: Mapping[str, float] | None = None,
) -> AreaTable:
    """Features, imputation counts and medians for one ACS summary level."""
    areas = land_areas if land_areas is not None else load_land_area_km2(geography)
    rows = build_feature_rows(staged, geography, areas, state_resolver(geography))
    filled, missing, medians = impute(rows)
    return AreaTable(
        geography=geography,
        rows={row.geoid: row for row in rows},
        imputed_counts={row.geoid: n for row, n in zip(rows, missing, strict=True)},
        medians=medians,
        filled={row.geoid: values for row, values in zip(rows, filled, strict=True)},
    )


def state_resolver(geography: str) -> Callable[[str], str]:
    """How to read a state FIPS out of a GEOID at this summary level.

    A tract or county GEOID begins with its state FIPS. **A ZCTA does not carry a state
    at all** - its state membership is a property of the areas it intersects, and 137 of
    33,791 ZCTAs span more than one - so it reports an empty string rather than the
    first two digits of a postal number that mean nothing.
    """
    if geography == "zcta":
        return lambda geoid: ""
    return lambda geoid: geoid[:2]


def load_area_tables(
    fetcher: Fetcher | None = None,
    states: Sequence[str] = (),
    year: int | None = None,
) -> dict[str, AreaTable]:
    """ACS features at every summary level the panel needs, for one ACS vintage.

    Tract features are fetched per state because the API serves tracts one state at a
    time; ZCTA and county come back nationally in a single request each.

    ``year`` defaults to the **current production** vintage. It is an explicit parameter
    rather than a module-level default read at call time because
    :class:`~pipeline.sources.census_acs.AcsSource` binds ``ACS_YEAR`` as a default
    argument at definition time, so patching the module attribute does **not** change
    which vintage is loaded. Phase 5 needs cutoff-appropriate vintages under directive
    D1, and it must be able to ask for one by name rather than by mutating a constant.
    """
    source = fetcher or ReplayFetcher(PATHS.cache)
    vintage = ACS_YEAR if year is None else year
    tables: dict[str, AreaTable] = {
        "zcta": build_area_table(
            AcsSource(ZCTA, year=vintage).load(source).rows, "zcta"),
        "county": build_area_table(
            AcsSource(COUNTY, year=vintage).load(source).rows, "county"),
    }
    tract_rows: list[Mapping[str, str]] = []
    for state in states:
        tract_rows.extend(
            AcsSource(TRACT, STATE_FIPS.get(state, state), year=vintage)
            .load(source).rows)
    if tract_rows:
        tables["tracts"] = build_area_table(tract_rows, "tracts")
    return tables


@dataclass(frozen=True)
class StatePanel:
    """One state's model rows, with the accounting for observations that did not join."""

    state: str
    source_geography: SourceGeography
    vintage_label: str
    rows: tuple[ModelRow, ...]
    ledger: ExclusionLedger
    is_independent: bool
    is_trainable: bool = True

    @property
    def observed_total(self) -> float:
        return sum(float(row.observed_bev or 0.0) for row in self.rows)

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "source_geography": self.source_geography.value,
            "vintage_label": self.vintage_label,
            "areas": len(self.rows),
            "observed_bev": int(self.observed_total),
            "independent_validation_evidence": self.is_independent,
            "training_evidence": self.is_trainable,
            "join_accounting": self.ledger.to_dict(),
        }


#: Washington selected the HUD crosswalk over land-area weighting, so any Washington
#: validation result is tuning-influenced. Pre-registration §2, rules W1-W4.
#:
#: **This governs evaluation, not training.** A state listed here is barred from the
#: independent leave-one-state-out aggregate and from being described as independent
#: demand model validation. It remains eligible as development/training evidence, which
#: is a separate field (:attr:`StatePanel.is_trainable`).
NON_INDEPENDENT_STATES: frozenset[str] = frozenset({"WA"})
NON_INDEPENDENT_REASON = "non_independent_preprocessing_selection_state"

#: States barred from TRAINING. Empty: no state has been shown to contaminate another
#: state's holdout merely by being in its training set.
NON_TRAINABLE_STATES: frozenset[str] = frozenset()


def build_state_panel(
    observations: StateObservations,
    tables: Mapping[str, AreaTable],
    zcta_states: Mapping[str, frozenset[str]] | None = None,
) -> StatePanel:
    """Join one state's observed counts to ACS features at its own geography."""
    geography = GEOGRAPHY_FOR_SOURCE[observations.source_geography]
    table = tables.get(geography)
    if table is None:
        raise PanelError(
            f"{observations.state}: no ACS features loaded for {geography}; the state "
            "cannot be modelled at the geography its data are published at"
        )
    state_fips = STATE_FIPS[observations.state]
    membership = (zcta_states if zcta_states is not None
                  else (zcta_state_index()
                        if observations.source_geography is SourceGeography.USPS_ZIP
                        else {}))

    excluded: dict[str, int] = {}
    descriptions: dict[str, str] = {}

    def drop(reason: str, description: str, n: int) -> None:
        excluded[reason] = excluded.get(reason, 0) + n
        descriptions.setdefault(reason, description)

    rows: list[ModelRow] = []
    for count in observations.counts:
        geoid = count.geography_id
        if observations.source_geography is SourceGeography.USPS_ZIP:
            states_touched = membership.get(geoid)
            if states_touched is None:
                drop("zip_has_no_like_numbered_zcta",
                     "the USPS ZIP Code has no like-numbered ZCTA, so it has no areal "
                     "equivalent and no census features; typically a point or "
                     "PO-Box-only ZIP", count.bev_count)
                continue
            if state_fips not in states_touched:
                drop("zip_outside_the_registering_state",
                     "the ZIP Code lies wholly outside the state whose DMV reported "
                     "it - an out-of-state mailing address. The vehicles are real and "
                     "belong in the state total, but they cannot be attributed to any "
                     "in-state area, and joining them to a like-numbered ZCTA "
                     "elsewhere would import that area's households as exposure",
                     count.bev_count)
                continue
        area = table.rows.get(geoid)
        if area is None:
            drop("no_acs_area_for_geoid",
                 f"no ACS {geography} record exists for this GEOID in the 2023 5-year "
                 "release", count.bev_count)
            continue
        if area.households <= 0:
            drop("area_has_no_households",
                 "the area reports zero occupied housing units, so it carries no "
                 "exposure and cannot support a rate", count.bev_count)
            continue
        rows.append(
            ModelRow(
                state=observations.state,
                geography=geography,
                geoid=geoid,
                households=area.households,
                population=area.population,
                features=table.filled[geoid],
                observed_bev=float(count.bev_count),
            )
        )

    ledger = ExclusionLedger(
        retrieved=sum(c.bev_count for c in observations.counts),
        included=int(sum(float(r.observed_bev or 0.0) for r in rows)),
        excluded={r: n for r, n in excluded.items() if n},
        descriptions=descriptions,
    )
    ledger.assert_balanced()
    return StatePanel(
        state=observations.state,
        source_geography=observations.source_geography,
        vintage_label=observations.vintage_label,
        rows=tuple(rows),
        ledger=ledger,
        is_independent=observations.state not in NON_INDEPENDENT_STATES,
        # Eligibility to TRAIN is a different question from eligibility to serve as
        # INDEPENDENT EVALUATION EVIDENCE, and conflating them was an implementation
        # over-restriction rather than anything the pre-registration required. Rules
        # W1-W4 speak only to validation records and the headline aggregate.
        # Washington's tuning influence invalidates its own evaluation; it does not
        # contaminate an Oregon or Texas holdout merely by sitting in their training
        # set. See the 2026-08-29 amendment to the Phase 3 pre-registration.
        is_trainable=True,
    )


def build_panels(
    observations: Mapping[str, StateObservations],
    tables: Mapping[str, AreaTable],
    zcta_states: Mapping[str, frozenset[str]] | None = None,
) -> dict[str, StatePanel]:
    membership = zcta_states if zcta_states is not None else zcta_state_index()
    return {
        state: build_state_panel(observed, tables, membership)
        for state, observed in observations.items()
    }


def prediction_rows(
    table: AreaTable, feature_names: Sequence[str] = FEATURE_NAMES
) -> list[ModelRow]:
    """Every area in a table as a prediction row, with no observed count attached."""
    return [
        ModelRow(
            state=row.geoid[:2],
            geography=table.geography,
            geoid=row.geoid,
            households=row.households,
            population=row.population,
            features={name: table.filled[row.geoid][name] for name in feature_names},
        )
        for row in table.rows.values()
    ]


def default_land_area_path(geography: str) -> Path:
    from pipeline.model.features import GAZETTEER

    return GAZETTEER[geography]
