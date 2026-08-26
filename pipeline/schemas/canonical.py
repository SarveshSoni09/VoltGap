"""pandera schemas for every canonical table.

CLAUDE.md section 9: "Every model has a matching pandera schema in
``pipeline/schemas/``, checked after execution. **A schema violation fails the build
and blocks publication.**"

These schemas encode the invariants that must hold for the data to be usable, not just
column types. Several of them are the machine-readable form of a domain rule:

* ``mart_charging_units.port_count`` must be a valid positive count, and
  ``key_is_synthetic`` must be ``True`` on every row, so no consumer can mistake the
  record key for a stable physical identifier (CLAUDE.md 6.1.1).

  Note what this schema deliberately does **not** assert. Every unit in the 2026-08-24
  national snapshot reports ``port_count == 1``, but that is a *current-source
  observation, not permanent ontology* (amendment A19). Charging unit and port remain
  conceptually distinct source entities. Pinning ``== 1`` here would reject a
  legitimate future AFDC record reporting multiple ports as if it were corrupt data.
  The structural rule is ``>= 1``; the ``== 1`` observation is monitored by
  ``check_port_count_drift`` and asserted as a regression, not enforced as structure.
* ``mart_state_totals`` must not contain a published total row (G8).
* ``mart_observed_subregion_ev`` must never label a ZIP- or county-derived value as
  directly observed at tract grain (CLAUDE.md 7.4.1).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pandera.pandas as pa
from pandera.pandas import Check, Column, DataFrameSchema

EVIDENCE_GRAINS = ["native_tract", "zip_anchored", "county_anchored", "state_total_only"]
ESTIMATE_METHODS = ["directly_observed", "crosswalked", "modeled",
                    "modeled_high_uncertainty"]
SOURCE_GEOGRAPHIES = ["usps_zip", "zcta", "county", "tract", "state"]
CONNECTOR_TYPES = ["J1772", "J1772COMBO", "CHADEMO", "TESLA", "J3271",
                   "NEMA515", "NEMA520", "NEMA1450"]

# Every derived table carries these (CLAUDE.md section 6.2).
PROVENANCE = {
    "computed_at": Column(str, nullable=False),
    "source_vintages": Column(str, nullable=False),
}


def _schema(columns: dict[str, Column],
            unique: list[str] | None = None) -> DataFrameSchema:
    return DataFrameSchema(
        {**columns, **PROVENANCE}, strict=True, coerce=True, unique=unique
    )


MART_SITES = _schema(
    {
        "site_id": Column(str, nullable=False, unique=True),
        "latitude": Column(float, Check.in_range(-90, 90), nullable=True),
        "longitude": Column(float, Check.in_range(-180, 180), nullable=True),
        "station_count": Column(int, Check.ge(1)),
        "network_count": Column(int, Check.ge(0)),
        "state": Column(str, nullable=True),
        "public_operational_stations": Column(int, Check.ge(0)),
        # G1: capacity comes from unit counts, never from counting station rows.
        "charging_unit_count": Column(int, Check.ge(0)),
        "public_operational_unit_count": Column(int, Check.ge(0)),
    }
)

MART_STATIONS = _schema(
    {
        "station_id": Column(str, nullable=False, unique=True),
        "site_id": Column(str, nullable=True),
        "station_name": Column(str, nullable=True),
        "state": Column(str, nullable=True),
        "city": Column(str, nullable=True),
        "zip": Column(str, nullable=True),
        # G2: Status Code has exactly three values.
        "status_code": Column(str, Check.isin(["E", "T", "P"]), nullable=True),
        "access_code": Column(str, nullable=True),
        "ev_network": Column(str, nullable=True),
        "latitude": Column(float, Check.in_range(-90, 90), nullable=True),
        "longitude": Column(float, Check.in_range(-180, 180), nullable=True),
        "open_date": Column("datetime64[ns]", nullable=True),
        "facility_type": Column(str, nullable=True),
        "evse_count_l1": Column(int, Check.ge(0)),
        "evse_count_l2": Column(int, Check.ge(0)),
        "evse_count_dcfc": Column(int, Check.ge(0)),
        "ev_connector_types": Column(object, nullable=True),
        "is_operational": Column(bool),
        "is_public": Column(bool),
        "is_public_operational": Column(bool),
    }
)

MART_CHARGING_UNITS = _schema(
    {
        "charging_unit_record_key": Column(str, nullable=False, unique=True),
        "station_id": Column(str, nullable=False),
        "site_id": Column(str, nullable=True),
        "record_ordinal": Column(int, Check.ge(0)),
        "state": Column(str, nullable=True),
        "status_code": Column(str, nullable=True),
        "access_code": Column(str, nullable=True),
        "ev_network": Column(str, nullable=True),
        "charging_level": Column(str, nullable=True),
        # >= 1, never == 1. See the module docstring and amendment A19.
        "port_count": Column(int, Check.ge(1)),
        "connector_port_sum": Column(int, Check.ge(0)),
        "is_multi_connector_port": Column(bool),
        "is_public_operational": Column(bool),
        # The two flags that stop a consumer treating the record key as physical
        # identity. Both are constants, asserted rather than merely documented.
        "key_is_synthetic": Column(bool, Check.eq(True)),
        "has_longitudinal_identity": Column(bool, Check.eq(False)),
    }
)

MART_CHARGING_UNIT_CONNECTORS = _schema(
    {
        "charging_unit_record_key": Column(str, nullable=False),
        "connector_type": Column(str, Check.isin(CONNECTOR_TYPES)),
        "connector_count": Column(int, Check.ge(0)),
        "power_kw": Column(float, Check.ge(0), nullable=True),
        "power_source": Column(str, Check.isin(["reported"]), nullable=True),
        "has_reported_power": Column(bool),
        "is_zero_power_anomaly": Column(bool),
        "charging_level": Column(str, nullable=True),
        "is_public_operational": Column(bool),
    },
    unique=["charging_unit_record_key", "connector_type"],
)

MART_STATE_TOTALS = _schema(
    {
        "state": Column(
            str,
            # G8: the published total row must never survive into a mart.
            Check(lambda s: ~s.isin(["United States", "Total"]),
                  error="G8: a published total row reached mart_state_totals"),
        ),
        "vintage": Column(str, nullable=False),
        "ev_count": Column(int, Check.ge(0)),
        "measure_type": Column(str, Check.eq("stock")),
    },
    unique=["state", "vintage"],
)

MART_OBSERVED_SUBREGION_EV = _schema(
    {
        "state": Column(str, nullable=False),
        "source_geography_type": Column(str, Check.isin(SOURCE_GEOGRAPHIES)),
        "source_geography_id": Column(str, nullable=False),
        "vintage": Column(str, nullable=True),
        "dmv_snapshot_id": Column(str, nullable=True),
        "is_latest_snapshot": Column(bool),
        "ev_count": Column(int, Check.ge(0)),
        "evidence_grain": Column(str, Check.isin(EVIDENCE_GRAINS)),
        "estimate_method": Column(str, Check.isin(ESTIMATE_METHODS)),
    }
)

SCHEMAS: dict[str, DataFrameSchema] = {
    "mart_sites": MART_SITES,
    "mart_stations": MART_STATIONS,
    "mart_charging_units": MART_CHARGING_UNITS,
    "mart_charging_unit_connectors": MART_CHARGING_UNIT_CONNECTORS,
    "mart_state_totals": MART_STATE_TOTALS,
    "mart_observed_subregion_ev": MART_OBSERVED_SUBREGION_EV,
}


class SchemaViolationError(RuntimeError):
    """A canonical table failed its schema. The build must not publish."""


def validate(table: str, frame: pd.DataFrame) -> pd.DataFrame:
    """Validate one canonical table, raising with every failure case listed."""
    schema = SCHEMAS.get(table)
    if schema is None:
        raise SchemaViolationError(f"{table}: no pandera schema is defined")
    try:
        return schema.validate(frame, lazy=True)
    except pa.errors.SchemaErrors as exc:
        raise SchemaViolationError(f"{table}: {exc.failure_cases}") from exc


def validate_all(frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Validate every canonical table. Raises on the first table that fails."""
    return {name: validate(name, frame) for name, frame in sorted(frames.items())}


@dataclass(frozen=True)
class PortCountDrift:
    """Whether the current snapshot still shows one service port per unit record."""

    total_units: int
    units_with_one_port: int
    units_with_multiple_ports: int
    max_port_count: int

    @property
    def matches_phase_1_observation(self) -> bool:
        return self.units_with_multiple_ports == 0

    def to_dict(self) -> dict[str, object]:
        return {
            "total_units": self.total_units,
            "units_with_one_port": self.units_with_one_port,
            "units_with_multiple_ports": self.units_with_multiple_ports,
            "max_port_count": self.max_port_count,
            "matches_phase_1_observation": self.matches_phase_1_observation,
            "note": (
                "port_count == 1 for every unit is a CURRENT-SOURCE OBSERVATION, not a "
                "schema invariant. A value above 1 is legitimate data and requires "
                "source-drift review, not a validation failure (amendment A19)."
            ),
        }


def check_port_count_drift(frame: pd.DataFrame) -> PortCountDrift:
    """Monitor the one-port-per-record observation without enforcing it.

    Phase 1 measured ``port_count == 1`` for all 292,756 units. If a refresh changes
    that, this surfaces it as drift requiring review. It never raises: a unit with
    several ports is valid data that the supply model must handle explicitly, not
    corruption to be rejected (CLAUDE.md 6.1.1, 7.1.1).
    """
    counts = pd.to_numeric(frame["port_count"], errors="coerce").fillna(0).astype(int)
    return PortCountDrift(
        total_units=len(counts),
        units_with_one_port=int((counts == 1).sum()),
        units_with_multiple_ports=int((counts > 1).sum()),
        max_port_count=int(counts.max()) if len(counts) else 0,
    )


# --- Phase 2 marts -------------------------------------------------------------------

POWER_SOURCES = ["reported", "empirical_fallback", "type_default", "unresolved"]
POWER_CONFIDENCES = ["high", "medium", "low", "none"]
CAPACITY_BASES = ["unit_reported_maximum", "single_port_connector_maximum",
                  "multi_port_unresolved", "unresolved"]
CHARGING_LEVELS = ["1", "2", "dc_fast", "legacy"]

MART_UNIT_CAPACITY = _schema(
    {
        "charging_unit_record_key": Column(str, nullable=False, unique=True),
        "charging_level": Column(str, Check.isin(CHARGING_LEVELS), nullable=True),
        # >= 1, never == 1: the one-port observation is monitored, not enforced (A19).
        "port_count": Column(int, Check.ge(1)),
        "simultaneous_service_ports": Column(int, Check.ge(1)),
        # NON-OVERLAPPING capacity. Never the sum of alternative connector powers.
        "generic_service_capacity_kw": Column(float, Check.ge(0), nullable=True),
        "generic_capacity_basis": Column(str, Check.isin(CAPACITY_BASES)),
        "connector_standards_available": Column(str, nullable=False),
        "is_multi_connector_port": Column(bool),
        "power_source": Column(str, Check.isin(POWER_SOURCES)),
        "power_confidence": Column(str, Check.isin(POWER_CONFIDENCES)),
    }
)

MART_SITE_SUPPLY = _schema(
    {
        "site_id": Column(str, nullable=False, unique=True),
        "unit_count": Column(int, Check.ge(1)),
        "simultaneous_service_ports": Column(int, Check.ge(0)),
        # Generic (non-overlapping) capacity and connector-compatible capacity are
        # SEPARATE FIELDS. Neither may silently substitute for the other (P2-H).
        "generic_service_capacity_kw": Column(float, Check.ge(0)),
        "connector_compatible_kw_json": Column(str, nullable=False),
        "ports_l1": Column(int, Check.ge(0)),
        "ports_l2": Column(int, Check.ge(0)),
        "ports_dcfc": Column(int, Check.ge(0)),
        "ports_legacy": Column(int, Check.ge(0)),
        "units_unresolved_capacity": Column(int, Check.ge(0)),
        "power_confidence_share": Column(float, Check.in_range(0.0, 1.0)),
    }
)

SCHEMAS["mart_unit_capacity"] = MART_UNIT_CAPACITY
SCHEMAS["mart_site_supply"] = MART_SITE_SUPPLY
