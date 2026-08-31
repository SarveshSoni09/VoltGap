"""Observed sub-state EV registration counts, at each source's own geography.

Sixteen states publish EV registrations below the state level. **They do not publish
them at the same geography**, and CLAUDE.md §7.5.1 forbids inferring which geography a
source uses from its column names: eleven Atlas EV Hub states are keyed by *USPS ZIP
Code*, three by county, and Washington alone by census tract. Every state's geography is
therefore declared here, in one table, and read from that declaration.

**The target is BEV, not "EV".** The AFDC state series this project reconciles to
publishes ``Electric (EV)`` and ``Plug-In Hybrid Electric (PHEV)`` as separate columns,
and the delivered seed totals match the BEV column (Alabama 13,047 against a rounded
13,000). Atlas and Washington both label drivetrain explicitly. Counting PHEVs into the
target would make the tract estimates irreconcilable with the only state constraint
available, so the target is battery-electric registrations and PHEV counts are carried
separately. This is a definitional choice and it is stated wherever a count is
published.

**Nothing is dropped silently (D8).** Each state's extraction returns an
:class:`~pipeline.validation.scope.ExclusionLedger` accounting for every vehicle in the
source: rows outside the latest snapshot, non-BEV rows, and rows whose geography cannot
be resolved are each counted under their own name.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import duckdb

from pipeline.config.settings import PATHS
from pipeline.spatial.geography import (
    EstimateMethod,
    EvidenceGrain,
    GeographyError,
    SourceGeography,
    county_fips_lookup,
    evidence_grain_for,
    normalise_zip,
    resolve_county_fips,
)
from pipeline.validation.scope import ExclusionLedger

ATLAS_DIRECTORY = PATHS.root / "data" / "cache" / "raw" / "atlas"
WASHINGTON_RECORDS = PATHS.root / "data" / "cache" / "raw" / "wa_ev_population_full.json"

#: Explicit quoting rather than DuckDB's auto-detection. Virginia's export contains
#: ``"JEST ELECTRIC, JEST EV, E-JEST"`` in a model-name field; with an auto-detected
#: empty quote character that row parses as 14 columns instead of 13 and the read
#: fails. Setting the quote character is the fix. ``ignore_errors`` would have been the
#: other way to make the read succeed, and it is exactly the silent-row-loss that
#: amendment A15 forbids.
CSV_READ_OPTIONS = "header=true, all_varchar=true, quote='\"', escape='\"'"

BEV = "BEV"
PHEV = "PHEV"

#: Declared publisher scope values. Only an exhaustive jurisdiction-wide enumeration can
#: establish that an area it does not name holds zero.
STATEWIDE_VEHICLE_REGISTRY = "statewide_vehicle_registry"
PARTIAL_OR_UNDECLARED = "partial_or_undeclared"

#: Source geography per state, declared and never inferred (CLAUDE.md §7.5.1).
STATE_GEOGRAPHY: Mapping[str, SourceGeography] = {
    "CO": SourceGeography.USPS_ZIP,
    "CT": SourceGeography.USPS_ZIP,
    "ME": SourceGeography.USPS_ZIP,
    "MN": SourceGeography.USPS_ZIP,
    "NC": SourceGeography.USPS_ZIP,
    "NJ": SourceGeography.USPS_ZIP,
    "NM": SourceGeography.USPS_ZIP,
    "NY": SourceGeography.USPS_ZIP,
    "OR": SourceGeography.USPS_ZIP,
    "TX": SourceGeography.USPS_ZIP,
    "VT": SourceGeography.USPS_ZIP,
    "MT": SourceGeography.COUNTY,
    "TN": SourceGeography.COUNTY,
    "VA": SourceGeography.COUNTY,
    "WA": SourceGeography.TRACT,
}

ATLAS_STATE_CODES: tuple[str, ...] = tuple(
    code for code in STATE_GEOGRAPHY if code != "WA"
)

STATE_FIPS: Mapping[str, str] = {
    "CO": "08", "CT": "09", "ME": "23", "MN": "27", "MT": "30", "NC": "37",
    "NJ": "34", "NM": "35", "NY": "36", "OR": "41", "TN": "47", "TX": "48",
    "VA": "51", "VT": "50", "WA": "53",
}


class ObservationError(ValueError):
    """An observed registration source could not be read as declared."""


@dataclass(frozen=True)
class ObservedCount:
    """One observed EV count at the geography the source actually reports."""

    state: str
    source_geography: SourceGeography
    geography_id: str
    bev_count: int
    phev_count: int

    @property
    def evidence_grain(self) -> EvidenceGrain:
        return evidence_grain_for(self.source_geography)

    @property
    def estimate_method(self) -> EstimateMethod:
        """Observed at its own geography. Allocation downgrades this, not retrieval."""
        return EstimateMethod.DIRECTLY_OBSERVED


@dataclass(frozen=True)
class GeographyResolution:
    """How completely a registry places its own in-jurisdiction records.

    **This, not agreement with an external total, is what establishes completeness.** A
    registry may be exhaustive over the vehicles it registers and still fail to geocode
    some of them; a tract absent from a source with unplaced in-jurisdiction records
    cannot be completed to zero, because one of those records might belong to it.

    ``in_jurisdiction_records`` counts records whose **address of record** is in the
    jurisdiction, read from the source's own state field rather than inferred from the
    tract. That distinction is the whole point: Washington's eight BEV rows with a null
    tract all carry a non-Washington state (BC, QC, AE, NH), so they are *resolved as
    out-of-state*, not unresolved within Washington.
    """

    total_records: int
    in_jurisdiction_records: int
    in_jurisdiction_placed: int
    out_of_jurisdiction_records: int
    invalid_tract_format: int
    tract_not_in_jurisdiction_geography: int

    @property
    def unresolved_in_jurisdiction(self) -> int:
        """In-jurisdiction records the source could not place. Must be 0 for zero-completion."""
        return self.in_jurisdiction_records - self.in_jurisdiction_placed

    @property
    def fully_resolved(self) -> bool:
        return self.unresolved_in_jurisdiction == 0

    def assert_balanced(self) -> None:
        total = self.in_jurisdiction_records + self.out_of_jurisdiction_records
        if total != self.total_records:
            raise ObservationError(
                f"geography ledger does not balance: {self.total_records} records != "
                f"{self.in_jurisdiction_records} in-jurisdiction + "
                f"{self.out_of_jurisdiction_records} out-of-jurisdiction"
            )

    def to_dict(self) -> dict[str, object]:
        self.assert_balanced()
        return {
            "total_records": self.total_records,
            "in_jurisdiction_records": self.in_jurisdiction_records,
            "in_jurisdiction_placed_in_a_valid_tract": self.in_jurisdiction_placed,
            "unresolved_in_jurisdiction": self.unresolved_in_jurisdiction,
            "out_of_jurisdiction_records": self.out_of_jurisdiction_records,
            "invalid_tract_format": self.invalid_tract_format,
            "tract_not_in_jurisdiction_geography":
                self.tract_not_in_jurisdiction_geography,
            "fully_resolved": self.fully_resolved,
            "balances": True,
        }


@dataclass(frozen=True)
class StateObservations:
    """Every observation for one state, plus the accounting for what was excluded."""

    state: str
    source_geography: SourceGeography
    vintage_label: str
    counts: tuple[ObservedCount, ...]
    ledger: ExclusionLedger
    #: Declared publisher scope. A source that does not claim to enumerate the whole
    #: jurisdiction cannot establish that an absent area holds zero.
    publisher_scope: str = "unknown"
    resolution: GeographyResolution | None = None

    @property
    def total_bev(self) -> int:
        return sum(c.bev_count for c in self.counts)

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "source_geography": self.source_geography.value,
            "evidence_grain": evidence_grain_for(self.source_geography).value,
            "vintage_label": self.vintage_label,
            "areas": len(self.counts),
            "total_bev": self.total_bev,
            "total_phev": sum(c.phev_count for c in self.counts),
            "record_accounting": self.ledger.to_dict(),
            "publisher_scope": self.publisher_scope,
            "geography_resolution": (None if self.resolution is None
                                     else self.resolution.to_dict()),
        }


def _atlas_path(state: str, directory: Path | None = None) -> Path:
    path = (directory or ATLAS_DIRECTORY) / f"{state}.csv"
    if not path.exists():
        raise ObservationError(
            f"{state}: Atlas export missing at {path}. A state cannot be validated "
            "against registrations it does not have; it must be reported as "
            "unavailable rather than skipped."
        )
    return path


def latest_snapshot_label(path: Path, connection: duckdb.DuckDBPyConnection) -> str:
    """The label of the snapshot the publisher marks as latest.

    Read from the publisher's own ``Latest DMV Snapshot Flag`` rather than by parsing
    and sorting the date text, because the label format is not consistent across states
    (``1/1/2026`` in Maine, ``01/01/2026`` in Minnesota).
    """
    row = connection.execute(
        f"""SELECT any_value("DMV Snapshot (Date)"),
                   count(DISTINCT "DMV Snapshot (Date)")
            FROM read_csv('{path}', {CSV_READ_OPTIONS})
            WHERE lower("Latest DMV Snapshot Flag") = 'true'"""
    ).fetchone()
    if row is None or row[0] is None:
        raise ObservationError(f"{path.name}: no rows carry the latest-snapshot flag")
    if row[1] != 1:
        raise ObservationError(
            f"{path.name}: {row[1]} distinct snapshot labels carry the latest flag; "
            "the observation vintage would be ambiguous"
        )
    return str(row[0])


def load_atlas_state(
    state: str,
    directory: Path | None = None,
    connection: duckdb.DuckDBPyConnection | None = None,
) -> StateObservations:
    """Observed BEV counts for one Atlas state, at its declared source geography."""
    geography = STATE_GEOGRAPHY[state]
    if geography is SourceGeography.TRACT:
        raise ObservationError(f"{state} is not an Atlas state")
    column = "ZIP Code" if geography is SourceGeography.USPS_ZIP else "County"
    path = _atlas_path(state, directory)
    con = connection or duckdb.connect()
    label = latest_snapshot_label(path, con)

    rows = con.execute(
        f"""SELECT coalesce("{column}", '') AS area,
                   upper(coalesce("Drivetrain Type", '')) AS drivetrain,
                   lower(coalesce("Latest DMV Snapshot Flag", '')) = 'true' AS latest,
                   sum(coalesce(TRY_CAST("Vehicle Count" AS BIGINT), 0)) AS vehicles
            FROM read_csv('{path}', {CSV_READ_OPTIONS})
            GROUP BY ALL"""
    ).fetchall()

    lookup = county_fips_lookup() if geography is SourceGeography.COUNTY else {}
    excluded: dict[str, int] = {}
    descriptions: dict[str, str] = {}

    def drop(reason: str, description: str, n: int) -> None:
        if n <= 0:
            return
        excluded[reason] = excluded.get(reason, 0) + n
        descriptions.setdefault(reason, description)

    bev: dict[str, int] = {}
    phev: dict[str, int] = {}
    retrieved = 0
    for area, drivetrain, latest, vehicles in rows:
        n = int(vehicles or 0)
        retrieved += n
        if not latest:
            drop("superseded_snapshot",
                 "the row belongs to an earlier DMV snapshot; the publisher's own "
                 "latest-snapshot flag selects the current stock", n)
            continue
        if drivetrain not in (BEV, PHEV):
            drop("drivetrain_not_plug_in",
                 f"drivetrain {drivetrain or 'blank'!r} is neither BEV nor PHEV", n)
            continue
        try:
            key = (normalise_zip(area) if geography is SourceGeography.USPS_ZIP
                   else resolve_county_fips(state, area, lookup))
        except GeographyError:
            drop("geography_unresolvable",
                 "the row carries no usable ZIP Code or no county name that resolves "
                 "to a FIPS code; county names collide across states (G13) so a name "
                 "that does not resolve exactly is never guessed", n)
            continue
        if drivetrain == BEV:
            bev[key] = bev.get(key, 0) + n
        else:
            phev[key] = phev.get(key, 0) + n

    drop("plug_in_hybrid_not_the_target",
         "PHEV registrations are carried separately: the AFDC state series this "
         "project reconciles to counts battery-electric vehicles only",
         sum(phev.values()))

    counts = tuple(
        ObservedCount(state, geography, key, n, phev.get(key, 0))
        for key, n in sorted(bev.items())
    )
    ledger = ExclusionLedger(
        retrieved=retrieved,
        included=sum(c.bev_count for c in counts),
        excluded=excluded,
        descriptions=descriptions,
    )
    ledger.assert_balanced()
    return StateObservations(state, geography, label, counts, ledger)


def load_washington(
    path: Path | None = None,
    known_tracts: Sequence[str] | None = None,
) -> StateObservations:
    """Washington's tract-grain observations: the only natively tract-keyed source.

    Washington is the **preprocessing-method-selection state** (Phase 3 pre-registration
    §2): it chose HUD ``res_ratio`` over land-area weighting, so any leave-one-state-out
    result it produces is tuning-influenced and is excluded from the independent
    aggregate. It is loaded here because it is still reported, and because it is training
    evidence and - where it proves itself exhaustive - a constraint.

    **The geography ledger built here is what licenses zero-completion, or refuses it.**
    A record's jurisdiction is read from the source's own ``state`` field, not inferred
    from its tract: the eight BEV rows with a null tract all carry a non-Washington state
    (BC, QC, AE, NH), so they are out-of-jurisdiction rather than unplaced. Passing
    ``known_tracts`` additionally checks each tract against real Census geography, so a
    well-formed GEOID that names no actual tract is caught rather than counted.
    """
    import json

    source = path or WASHINGTON_RECORDS
    if not source.exists():
        raise ObservationError(f"Washington records missing at {source}")
    records = json.loads(source.read_text(encoding="utf-8"))
    valid_tracts = set(known_tracts) if known_tracts is not None else None
    fips = STATE_FIPS["WA"]

    excluded: dict[str, int] = {}
    descriptions: dict[str, str] = {}

    def drop(reason: str, description: str) -> None:
        excluded[reason] = excluded.get(reason, 0) + 1
        descriptions.setdefault(reason, description)

    bev: dict[str, int] = {}
    phev: dict[str, int] = {}
    counters = dict.fromkeys(
        ("bev_total", "in_jurisdiction", "in_jurisdiction_placed",
         "out_of_jurisdiction", "invalid_format", "tract_not_real"), 0)

    for record in records:
        tract = "".join(c for c in str(record.get("_2020_census_tract") or "")
                        if c.isdigit())
        kind = str(record.get("ev_type") or "")
        addressed_here = str(record.get("state") or "").upper() == "WA"
        is_bev = "BEV" in kind

        if is_bev:
            counters["bev_total"] += 1
            counters["in_jurisdiction" if addressed_here
                     else "out_of_jurisdiction"] += 1
            if len(tract) != 11:
                counters["invalid_format"] += 1
            elif valid_tracts is not None and tract not in valid_tracts:
                counters["tract_not_real"] += 1
            elif addressed_here and tract.startswith(fips):
                counters["in_jurisdiction_placed"] += 1

        if len(tract) != 11:
            drop("tract_unusable",
                 "the row carries no 11-digit 2020 census tract, so it cannot be "
                 "placed at the geography this source is valued for")
            continue
        if not tract.startswith(fips):
            drop("tract_outside_state",
                 "the geocoded tract lies outside Washington; the vehicle is "
                 "registered in-state but addressed elsewhere")
            continue
        if valid_tracts is not None and tract not in valid_tracts:
            drop("tract_not_in_census_geography",
                 "the GEOID is well formed and in-state but names no tract in the "
                 "current Census geography, so it cannot be placed")
            continue
        if is_bev:
            bev[tract] = bev.get(tract, 0) + 1
        elif "PHEV" in kind:
            phev[tract] = phev.get(tract, 0) + 1
            drop("plug_in_hybrid_not_the_target",
                 "PHEV registrations are carried separately: the AFDC state series "
                 "counts battery-electric vehicles only")
        else:
            drop("drivetrain_not_plug_in", f"unrecognised ev_type {kind!r}")

    counts = tuple(
        ObservedCount("WA", SourceGeography.TRACT, tract, n, phev.get(tract, 0))
        for tract, n in sorted(bev.items())
    )
    ledger = ExclusionLedger(
        retrieved=len(records),
        included=sum(c.bev_count for c in counts),
        excluded=excluded,
        descriptions=descriptions,
    )
    ledger.assert_balanced()
    resolution = GeographyResolution(
        total_records=counters["bev_total"],
        in_jurisdiction_records=counters["in_jurisdiction"],
        in_jurisdiction_placed=counters["in_jurisdiction_placed"],
        out_of_jurisdiction_records=counters["out_of_jurisdiction"],
        invalid_tract_format=counters["invalid_format"],
        tract_not_in_jurisdiction_geography=counters["tract_not_real"],
    )
    resolution.assert_balanced()
    return StateObservations("WA", SourceGeography.TRACT, "current snapshot",
                             counts, ledger,
                             publisher_scope=STATEWIDE_VEHICLE_REGISTRY,
                             resolution=resolution)


def load_all(
    states: Sequence[str] = tuple(STATE_GEOGRAPHY),
    directory: Path | None = None,
    washington_path: Path | None = None,
    known_tracts: Sequence[str] | None = None,
) -> dict[str, StateObservations]:
    """Every declared sub-state source, keyed by state code."""
    connection = duckdb.connect()
    out: dict[str, StateObservations] = {}
    for state in states:
        out[state] = (load_washington(washington_path, known_tracts) if state == "WA"
                      else load_atlas_state(state, directory, connection))
    return out


#: AFDC publishes registrations by jurisdiction NAME; every join downstream is by FIPS,
#: because county and state names are not reliable keys (domain rule G13 is the county
#: version of the same problem).
JURISDICTION_FIPS: Mapping[str, str] = {
    "Alabama": "01", "Alaska": "02", "Arizona": "04", "Arkansas": "05",
    "California": "06", "Colorado": "08", "Connecticut": "09", "Delaware": "10",
    "District of Columbia": "11", "Florida": "12", "Georgia": "13", "Hawaii": "15",
    "Idaho": "16", "Illinois": "17", "Indiana": "18", "Iowa": "19", "Kansas": "20",
    "Kentucky": "21", "Louisiana": "22", "Maine": "23", "Maryland": "24",
    "Massachusetts": "25", "Michigan": "26", "Minnesota": "27", "Mississippi": "28",
    "Missouri": "29", "Montana": "30", "Nebraska": "31", "Nevada": "32",
    "New Hampshire": "33", "New Jersey": "34", "New Mexico": "35", "New York": "36",
    "North Carolina": "37", "North Dakota": "38", "Ohio": "39", "Oklahoma": "40",
    "Oregon": "41", "Pennsylvania": "42", "Rhode Island": "44",
    "South Carolina": "45", "South Dakota": "46", "Tennessee": "47", "Texas": "48",
    "Utah": "49", "Vermont": "50", "Virginia": "51", "Washington": "53",
    "West Virginia": "54", "Wisconsin": "55", "Wyoming": "56",
}

#: G8: the published national row is a total, not a jurisdiction. It is ingested by the
#: adapter unchanged (A15) and removed here, visibly.
NATIONAL_TOTAL_LABELS: frozenset[str] = frozenset({"United States", "Total"})


@dataclass(frozen=True)
class StateTotal:
    """One jurisdiction's battery-electric registration stock for one vintage."""

    state_fips: str
    jurisdiction: str
    vintage: str
    bev_count: int
    phev_count: int


def load_state_totals(
    fetcher: object = None, vintages: Sequence[str] = ()
) -> dict[str, list[StateTotal]]:
    """AFDC state EV registration vintages, keyed by state FIPS.

    The values are **battery-electric stock**, from the ``Electric (EV)`` column; the
    separate ``Plug-In Hybrid Electric (PHEV)`` column is carried but is not the target
    (see the module docstring). Domain rule G8 also applies: these are stock, never
    sales, and the published national total row is removed here rather than at
    retrieval.

    AFDC rounds the figures on its year pages to the nearest hundred - Alabama 2023
    reads 13,000 against the delivered seed file's 13,047 - so a constraint built from
    them is precise to about ±50 vehicles per state. That is recorded wherever a
    reconciled estimate is published.
    """
    from pipeline.config.settings import PATHS as _PATHS
    from pipeline.discovery.cache import ReplayFetcher
    from pipeline.sources.catalog import afdc_registration_sources

    source = fetcher if fetcher is not None else ReplayFetcher(_PATHS.cache)
    out: dict[str, list[StateTotal]] = {}
    for source_id, adapter in sorted(afdc_registration_sources().items()):
        vintage = source_id.rsplit("_", 1)[-1]
        if vintages and vintage not in vintages:
            continue
        table = adapter.load(source)  # type: ignore[arg-type]
        for row in table.rows:
            name = (row.get("State") or "").strip()
            if name in NATIONAL_TOTAL_LABELS or name not in JURISDICTION_FIPS:
                continue
            bev = _parse_count(row.get("Electric (EV)"))
            phev = _parse_count(row.get("Plug-In Hybrid Electric (PHEV)"))
            if bev is None:
                continue
            out.setdefault(JURISDICTION_FIPS[name], []).append(
                StateTotal(JURISDICTION_FIPS[name], name, vintage, bev, phev or 0)
            )
    if not out:
        raise ObservationError(
            "no state registration totals were loaded; tract estimates cannot be "
            "reconciled to a constraint that does not exist"
        )
    return out


def _parse_count(value: str | None) -> int | None:
    text = (value or "").replace(",", "").strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def latest_state_totals(
    fetcher: object = None, vintage: str | None = None
) -> dict[str, StateTotal]:
    """One BEV total per jurisdiction: the newest vintage, or a named one."""
    everything = load_state_totals(fetcher)
    chosen: dict[str, StateTotal] = {}
    for fips, series in everything.items():
        candidates = [t for t in series if vintage is None or t.vintage == vintage]
        if candidates:
            chosen[fips] = max(candidates, key=lambda t: t.vintage)
    return chosen
