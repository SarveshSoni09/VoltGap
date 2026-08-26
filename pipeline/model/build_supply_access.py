"""Phase 2 build: supply capacity and access, from the Phase 1 canonical tables.

Reads only the Phase 1 supply marts and Census population geography. It deliberately
does **not** read ``mart_observed_subregion_ev``: Phase 2 must not consume ZIP-to-tract
or county-to-tract EV-registration allocations, because supply and access do not need
them and importing the unmeasured land-area weighting error would buy nothing
(CLAUDE.md 7.5.2, amendment A21, gate check P2-G).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pipeline.model.access import (
    AccessResult,
    AccessThresholds,
    compute_access,
    load_thresholds,
    qualifying_sites,
)
from pipeline.model.supply import (
    ConnectorSpec,
    EmpiricalTable,
    PowerDefaults,
    ResolvedPower,
    SiteCapacity,
    UnitCapacity,
    aggregate_site_capacity,
    aggregate_unit_capacity,
    build_empirical_table,
    load_connectors,
    load_power_defaults,
    resolve_power,
)
from pipeline.spatial.allocation import PopulationPoint
from pipeline.transform.runner import Warehouse

# Tables Phase 2 is permitted to read. Enforced by test (P2-G): a registration mart
# appearing here would mean allocated demand had leaked into supply and access.
PHASE_2_INPUT_TABLES: frozenset[str] = frozenset({
    "mart_sites", "mart_stations", "mart_charging_units",
    "mart_charging_unit_connectors", "raw_census_cenpop_blockgroup",
})
FORBIDDEN_INPUT_TABLES: frozenset[str] = frozenset({
    "mart_observed_subregion_ev", "int_observed_subregion_ev",
    "stg_atlas_registrations", "raw_atlas_registrations",
})


@dataclass
class SupplyAccessResult:
    """Everything Phase 2 produced."""

    unit_capacities: list[UnitCapacity]
    site_capacities: list[SiteCapacity]
    ladder_distribution: dict[str, int]
    ladder_share: dict[str, float]
    empirical_summary: list[dict[str, Any]]
    access: dict[str, AccessResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "units": len(self.unit_capacities),
            "sites": len(self.site_capacities),
            "ladder_distribution": dict(sorted(self.ladder_distribution.items())),
            "ladder_share": {k: round(v, 6) for k, v in sorted(self.ladder_share.items())},
            "empirical_groups_usable": sum(1 for g in self.empirical_summary if g["usable"]),
            "access": {k: v.to_dict() for k, v in sorted(self.access.items())},
        }


def read_connector_observations(warehouse: Warehouse) -> list[dict[str, Any]]:
    """Connector rows joined to their unit's network and source charging level.

    ``charging_level`` comes from the unit record, never from the connector name
    (gate check P2-B).
    """
    rows = warehouse.connection.execute(
        "SELECT c.charging_unit_record_key, c.connector_type, c.connector_count, "
        "       c.power_kw, u.charging_level, u.ev_network, u.port_count, u.site_id, "
        "       u.is_public_operational "
        "FROM mart_charging_unit_connectors c "
        "JOIN mart_charging_units u USING (charging_unit_record_key) "
        "ORDER BY c.charging_unit_record_key, c.connector_type"
    ).fetchall()
    return [
        {
            "charging_unit_record_key": str(r[0]), "connector_type_raw": str(r[1]),
            "connector_count": int(r[2] or 0), "power_kw": r[3],
            "charging_level": str(r[4] or ""), "network": str(r[5] or ""),
            "port_count": int(r[6] or 0), "site_id": str(r[7] or ""),
            "is_public_operational": bool(r[8]),
        }
        for r in rows
    ]


def resolve_all(
    observations: Sequence[Mapping[str, Any]],
    connectors: Mapping[str, ConnectorSpec] | None = None,
    defaults: PowerDefaults | None = None,
) -> tuple[list[ResolvedPower], EmpiricalTable, dict[str, int]]:
    """Run every connector observation through the ladder and tally the rungs."""
    table = connectors if connectors is not None else load_connectors()
    power_defaults = defaults if defaults is not None else load_power_defaults()

    # Rung 2 medians are derived from rung-1 records only, so the empirical table is
    # built before resolution rather than during it.
    normalised = [
        {**dict(o),
         "connector_normalized": table[str(o["connector_type_raw"])].normalized
         if str(o["connector_type_raw"]) in table else str(o["connector_type_raw"])}
        for o in observations if int(o.get("connector_count", 0) or 0) > 0
    ]
    empirical = build_empirical_table(normalised, power_defaults)

    resolved = [resolve_power(o, table, empirical, power_defaults) for o in normalised]
    tally: dict[str, int] = {}
    for entry in resolved:
        # str() so the tally keys are plain strings, not StrEnum members: these are
        # written to JSON artifacts and compared in tests.
        rung = str(entry.power_source)
        tally[rung] = tally.get(rung, 0) + 1
    return resolved, empirical, tally


def build_unit_capacities(
    observations: Sequence[Mapping[str, Any]], resolved: Sequence[ResolvedPower]
) -> list[UnitCapacity]:
    """Group resolved connectors by unit and apply the non-double-counting rule."""
    grouped: dict[str, list[ResolvedPower]] = {}
    meta: dict[str, tuple[str, int]] = {}
    for observation, entry in zip(observations, resolved, strict=True):
        key = str(observation["charging_unit_record_key"])
        grouped.setdefault(key, []).append(entry)
        meta[key] = (str(observation["charging_level"]), int(observation["port_count"]))
    return [
        aggregate_unit_capacity(key, meta[key][0], meta[key][1], entries)
        for key, entries in sorted(grouped.items())
    ]


def build_site_capacities(
    warehouse: Warehouse, units: Sequence[UnitCapacity]
) -> list[SiteCapacity]:
    """Aggregate unit capacity to sites, tracking public + operational units separately.

    A site can mix public and private infrastructure (domain rule G4 aggregates
    co-located multi-network stations), so private capacity must never be added to
    public capacity and level qualification must be evaluated on public units only.
    """
    rows = warehouse.connection.execute(
        "SELECT charging_unit_record_key, site_id, is_public_operational "
        "FROM mart_charging_units"
    ).fetchall()
    site_of = {str(r[0]): str(r[1] or "") for r in rows}
    public_of = {str(r[0]): bool(r[2]) for r in rows}
    grouped: dict[str, list[UnitCapacity]] = {}
    flags: dict[str, list[bool]] = {}
    for unit in units:
        site = site_of.get(unit.charging_unit_record_key, "")
        grouped.setdefault(site, []).append(unit)
        flags.setdefault(site, []).append(public_of.get(unit.charging_unit_record_key, False))
    return [aggregate_site_capacity(site, members, flags[site])
            for site, members in sorted(grouped.items()) if site]


def read_population_points(warehouse: Warehouse) -> list[PopulationPoint]:
    """Population-weighted centroids, never tract geometric centroids (CLAUDE.md 7.5).

    Block group is the finest ready-made population-weighted centroid the Census
    Bureau publishes; Phase 0 established that no block-level product exists (finding
    F-7). That limitation is carried into the Phase 2 report rather than hidden.
    """
    rows = warehouse.connection.execute(
        'SELECT "STATEFP", "COUNTYFP", "TRACTCE", "BLKGRPCE", "POPULATION", '
        '       "LATITUDE", "LONGITUDE" FROM raw_census_cenpop_blockgroup'
    ).fetchall()
    points: list[PopulationPoint] = []
    for r in rows:
        try:
            population = int(r[4])
            latitude, longitude = float(r[5]), float(r[6])
        except (TypeError, ValueError):  # pragma: no cover - malformed row
            continue
        tract = f"{r[0]}{r[1]}{r[2]}"
        points.append(PopulationPoint(
            point_id=f"{tract}{r[3]}", source_geoid=tract,
            population=population, latitude=latitude, longitude=longitude,
        ))
    return points


def site_supply_rows(
    warehouse: Warehouse, capacities: Sequence[SiteCapacity]
) -> list[dict[str, Any]]:
    """Join site capacity to site geography and public/operational status."""
    rows = warehouse.connection.execute(
        "SELECT site_id, latitude, longitude, state, public_operational_stations "
        "FROM mart_sites"
    ).fetchall()
    geography = {str(r[0]): r for r in rows}
    out: list[dict[str, Any]] = []
    for capacity in capacities:
        row = geography.get(capacity.site_id)
        if row is None or row[1] is None or row[2] is None:
            continue
        out.append({
            "site_id": capacity.site_id, "latitude": row[1], "longitude": row[2],
            "state": row[3],
            # Derived from UNITS that are simultaneously public and operational, not
            # from "the site has some public station". Those are different claims.
            "status_code": "E" if capacity.has_public_operational_service else "T",
            "access_code": ("public" if capacity.has_public_operational_service
                            else "private"),
            # Access qualification uses the PUBLIC level breakdown only: a private DC
            # charger at a site with a public Level 2 does not make it a public DCFC
            # site.
            "ports_by_level": dict(capacity.public_ports_by_level),
            "all_ports_by_level": dict(capacity.ports_by_level),
            "generic_service_capacity_kw": capacity.public_generic_service_capacity_kw,
            "all_generic_service_capacity_kw": capacity.generic_service_capacity_kw,
            "connector_compatible_kw": dict(capacity.public_connector_compatible_kw),
            "simultaneous_service_ports": capacity.public_simultaneous_service_ports,
        })
    return out


def build_supply_access(
    warehouse: Warehouse, thresholds: AccessThresholds | None = None
) -> SupplyAccessResult:
    """Run the whole Phase 2 model against the Phase 1 canonical tables."""
    limits = thresholds if thresholds is not None else load_thresholds()

    observations = read_connector_observations(warehouse)
    resolved, empirical, tally = resolve_all(observations)
    present = [o for o in observations if int(o.get("connector_count", 0) or 0) > 0]
    units = build_unit_capacities(present, resolved)
    sites = build_site_capacities(warehouse, units)

    total = sum(tally.values()) or 1
    share = {k: v / total for k, v in tally.items()}

    supply_rows = site_supply_rows(warehouse, sites)
    points = read_population_points(warehouse)
    access: dict[str, AccessResult] = {}
    for supply_class, levels in (("DCFC", limits.dcfc_levels), ("L2", limits.l2_levels)):
        eligible = qualifying_sites(supply_rows, levels, limits)
        access[supply_class] = compute_access(points, eligible, limits, supply_class)

    return SupplyAccessResult(
        unit_capacities=units, site_capacities=sites,
        ladder_distribution=tally, ladder_share=share,
        empirical_summary=empirical.summary(), access=access,
    )


# --- mart registration ----------------------------------------------------------------

PHASE_2_MARTS: tuple[str, ...] = ("mart_unit_capacity", "mart_site_supply")


def register_marts(warehouse: Warehouse, result: SupplyAccessResult,
                   computed_at: str, source_vintages: str) -> None:
    """Write the Phase 2 marts into the warehouse and validate them.

    ``generic_service_capacity_kw`` and ``connector_compatible_kw_json`` are separate
    columns on purpose (gate check P2-H). The connector-compatible values are
    serialised rather than exploded into one column per standard so that a reader
    cannot sum them across columns by accident.
    """
    import json

    warehouse.load_records(
        "mart_unit_capacity",
        ("charging_unit_record_key", "charging_level", "port_count",
         "simultaneous_service_ports", "generic_service_capacity_kw",
         "generic_capacity_basis", "connector_standards_available",
         "is_multi_connector_port", "power_source", "power_confidence",
         "computed_at", "source_vintages"),
        [
            (u.charging_unit_record_key, u.charging_level, str(u.port_count),
             str(u.simultaneous_service_ports),
             "" if u.generic_service_capacity_kw is None
             else repr(u.generic_service_capacity_kw),
             u.generic_capacity_basis, ",".join(u.connector_standards_available),
             str(u.is_multi_connector_port).lower(), u.power_source, u.power_confidence,
             computed_at, source_vintages)
            for u in result.unit_capacities
        ],
    )
    warehouse.connection.execute(
        "CREATE OR REPLACE TABLE mart_unit_capacity AS SELECT "
        "charging_unit_record_key, charging_level, "
        "CAST(port_count AS INTEGER) AS port_count, "
        "CAST(simultaneous_service_ports AS INTEGER) AS simultaneous_service_ports, "
        "TRY_CAST(generic_service_capacity_kw AS DOUBLE) AS generic_service_capacity_kw, "
        "generic_capacity_basis, connector_standards_available, "
        "CAST(is_multi_connector_port AS BOOLEAN) AS is_multi_connector_port, "
        "power_source, power_confidence, computed_at, source_vintages "
        "FROM mart_unit_capacity"
    )

    warehouse.load_records(
        "mart_site_supply",
        ("site_id", "unit_count", "simultaneous_service_ports",
         "generic_service_capacity_kw", "connector_compatible_kw_json",
         "ports_l1", "ports_l2", "ports_dcfc", "ports_legacy",
         "units_unresolved_capacity", "power_confidence_share",
         "public_unit_count", "public_simultaneous_service_ports",
         "public_generic_service_capacity_kw", "public_ports_l1", "public_ports_l2",
         "public_ports_dcfc", "has_public_operational_service",
         "computed_at", "source_vintages"),
        [
            (s.site_id, str(s.unit_count), str(s.simultaneous_service_ports),
             repr(s.generic_service_capacity_kw),
             json.dumps(dict(sorted(s.connector_compatible_kw.items())),
                        separators=(",", ":")),
             str(s.ports_by_level.get("1", 0)), str(s.ports_by_level.get("2", 0)),
             str(s.ports_by_level.get("dc_fast", 0)),
             str(s.ports_by_level.get("legacy", 0)),
             str(s.units_unresolved_capacity), repr(s.rung_1_capacity_share),
             str(s.public_unit_count), str(s.public_simultaneous_service_ports),
             repr(s.public_generic_service_capacity_kw),
             str(s.public_ports_by_level.get("1", 0)),
             str(s.public_ports_by_level.get("2", 0)),
             str(s.public_ports_by_level.get("dc_fast", 0)),
             str(s.has_public_operational_service).lower(),
             computed_at, source_vintages)
            for s in result.site_capacities
        ],
    )
    warehouse.connection.execute(
        "CREATE OR REPLACE TABLE mart_site_supply AS SELECT site_id, "
        "CAST(unit_count AS INTEGER) AS unit_count, "
        "CAST(simultaneous_service_ports AS INTEGER) AS simultaneous_service_ports, "
        "CAST(generic_service_capacity_kw AS DOUBLE) AS generic_service_capacity_kw, "
        "connector_compatible_kw_json, "
        "CAST(ports_l1 AS INTEGER) AS ports_l1, CAST(ports_l2 AS INTEGER) AS ports_l2, "
        "CAST(ports_dcfc AS INTEGER) AS ports_dcfc, "
        "CAST(ports_legacy AS INTEGER) AS ports_legacy, "
        "CAST(units_unresolved_capacity AS INTEGER) AS units_unresolved_capacity, "
        "CAST(power_confidence_share AS DOUBLE) AS power_confidence_share, "
        "CAST(public_unit_count AS INTEGER) AS public_unit_count, "
        "CAST(public_simultaneous_service_ports AS INTEGER) "
        "  AS public_simultaneous_service_ports, "
        "CAST(public_generic_service_capacity_kw AS DOUBLE) "
        "  AS public_generic_service_capacity_kw, "
        "CAST(public_ports_l1 AS INTEGER) AS public_ports_l1, "
        "CAST(public_ports_l2 AS INTEGER) AS public_ports_l2, "
        "CAST(public_ports_dcfc AS INTEGER) AS public_ports_dcfc, "
        "CAST(has_public_operational_service AS BOOLEAN) "
        "  AS has_public_operational_service, "
        "computed_at, source_vintages FROM mart_site_supply"
    )

    from pipeline.schemas.canonical import validate

    for table in PHASE_2_MARTS:
        validate(table, warehouse.fetch_df(table))
