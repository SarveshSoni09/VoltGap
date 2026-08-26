"""Supply model: connector normalisation, the power-resolution ladder, and capacity.

Two operations that must never be conflated (CLAUDE.md 7.1.1, amendment A20):

1. **Resolution** assigns a power value to a connector observation, through the
   three-rung ladder. It answers "what can this connector deliver?"
2. **Aggregation** converts resolved capabilities into capacity. It answers two
   *different* questions that have two different answers.

The aggregation distinction is the important one. Phase 1 found **16,610 charging-unit
records exposing more than one connector standard on a single service port** — CHAdeMO
plus CCS, CCS plus NACS, J1772 plus NACS. Those connector rows are **alternative
compatibility interfaces for the same simultaneous service position**, not independent
ports. A one-port unit offering CCS at 200 kW and CHAdeMO at 100 kW can serve one
vehicle at up to 200 kW. It cannot serve 300 kW, and it cannot serve two vehicles.

So:

* **Generic service capacity** is non-overlapping. It comes from the *service port
  count* and the *maximum* compatible connector power, never from summing connectors.
* **Connector-compatible capacity** answers "what is available to a CCS vehicle?" and
  **may overlap physically** across connector types. Summing it across types does not
  give total site capacity.

Both ship as separate, clearly named fields. Neither may substitute for the other.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
CONNECTORS_CONFIG = CONFIG_DIR / "connectors.yml"
POWER_DEFAULTS_CONFIG = CONFIG_DIR / "power_defaults.yml"

# Exactly 0.00 kW is not a valid reported power; 55 such cells exist nationally.
ZERO_POWER = 0.0


class PowerSource(StrEnum):
    """Which rung of the ladder produced a power value (CLAUDE.md 7.1)."""

    REPORTED = "reported"
    EMPIRICAL_FALLBACK = "empirical_fallback"
    TYPE_DEFAULT = "type_default"
    UNRESOLVED = "unresolved"


class PowerConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


CONFIDENCE_FOR_SOURCE: Mapping[PowerSource, PowerConfidence] = {
    PowerSource.REPORTED: PowerConfidence.HIGH,
    PowerSource.EMPIRICAL_FALLBACK: PowerConfidence.MEDIUM,
    PowerSource.TYPE_DEFAULT: PowerConfidence.LOW,
    PowerSource.UNRESOLVED: PowerConfidence.NONE,
}


class SupplyConfigError(ValueError):
    """The connector or power configuration is missing or malformed."""


# --- configuration ------------------------------------------------------------------

@dataclass(frozen=True)
class ConnectorSpec:
    """One raw connector value and its normalisation."""

    raw: str
    normalized: str
    display: str
    standard_family: str
    typical_levels: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"connector_type_raw": self.raw, "connector_type_normalized": self.normalized,
                "connector_display": self.display,
                "connector_standard_family": self.standard_family}


@dataclass(frozen=True)
class PowerDefaults:
    """Rung-2 grouping rules and rung-3 documented defaults."""

    rung_2_minimum_sample: int
    rung_2_hierarchy: tuple[tuple[str, ...], ...]
    defaults: Mapping[tuple[str, str], float]
    justifications: Mapping[tuple[str, str], str]

    def default_for(self, connector_normalized: str, charging_level: str) -> float | None:
        return self.defaults.get((connector_normalized, charging_level))


def load_connectors(path: Path | None = None) -> dict[str, ConnectorSpec]:
    """Load the connector normalisation table. Raises rather than guessing."""
    source = path or CONNECTORS_CONFIG
    if not source.exists():
        raise SupplyConfigError(f"connector configuration missing at {source}")
    document = yaml.safe_load(source.read_text(encoding="utf-8"))
    entries = (document or {}).get("connectors")
    if not entries:
        raise SupplyConfigError(f"{source} declares no connectors")
    return {
        raw: ConnectorSpec(
            raw=raw,
            normalized=str(spec["normalized"]),
            display=str(spec["display"]),
            standard_family=str(spec["standard_family"]),
            typical_levels=tuple(str(x) for x in spec.get("typical_levels", ())),
        )
        for raw, spec in entries.items()
    }


def load_power_defaults(path: Path | None = None) -> PowerDefaults:
    """Load rung-2 grouping rules and rung-3 defaults. No magic numbers in Python."""
    source = path or POWER_DEFAULTS_CONFIG
    if not source.exists():
        raise SupplyConfigError(f"power defaults missing at {source}")
    document = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    rows = document.get("defaults")
    if not rows:
        raise SupplyConfigError(f"{source} declares no defaults")
    defaults: dict[tuple[str, str], float] = {}
    justifications: dict[tuple[str, str], str] = {}
    for row in rows:
        key = (str(row["connector"]), str(row["charging_level"]))
        defaults[key] = float(row["power_kw"])
        justifications[key] = str(row.get("justification", "")).strip()
        if not justifications[key]:
            raise SupplyConfigError(f"{source}: default {key} has no justification")
    return PowerDefaults(
        rung_2_minimum_sample=int(document["rung_2_minimum_sample"]),
        rung_2_hierarchy=tuple(tuple(str(k) for k in group)
                               for group in document["rung_2_hierarchy"]),
        defaults=defaults,
        justifications=justifications,
    )


def normalize_connector(raw: str, table: Mapping[str, ConnectorSpec]) -> ConnectorSpec:
    """Normalise a raw connector value, preserving the raw form (P2-C).

    An unrecognised value is passed through with its raw form as the normalised form
    and a family of ``unknown``, rather than being dropped or guessed at: a new
    connector standard appearing upstream is information, not an error.
    """
    spec = table.get(raw)
    if spec is not None:
        return spec
    return ConnectorSpec(raw=raw, normalized=raw, display=raw,
                         standard_family="unknown", typical_levels=())


# --- rung 1: reported ----------------------------------------------------------------

def _as_float(value: object) -> float | None:
    """Parse to float, or None. Never raises: unparseable input is simply absent."""
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def is_valid_reported_power(value: object) -> bool:
    """Exactly 0.00 kW is an anomaly, not a reported value (CLAUDE.md 7.1)."""
    power = _as_float(value)
    return power is not None and power > ZERO_POWER


# --- rung 2: empirical fallback -------------------------------------------------------

@dataclass(frozen=True)
class EmpiricalGroup:
    """A rung-2 peer group and the median it supports."""

    keys: tuple[str, ...]
    values: tuple[str, ...]
    sample_size: int
    median_kw: float

    @property
    def label(self) -> str:
        return "+".join(f"{k}={v}" for k, v in zip(self.keys, self.values, strict=True))


@dataclass
class EmpiricalTable:
    """Medians derived from rung-1 observations, by grouping level."""

    minimum_sample: int
    hierarchy: tuple[tuple[str, ...], ...]
    groups: dict[tuple[str, tuple[str, ...]], EmpiricalGroup] = field(default_factory=dict)

    def lookup(self, attributes: Mapping[str, str]) -> EmpiricalGroup | None:
        """Most specific sufficiently-populated group wins."""
        for keys in self.hierarchy:
            values = tuple(str(attributes.get(k, "")) for k in keys)
            group = self.groups.get(("|".join(keys), values))
            if group is not None and group.sample_size >= self.minimum_sample:
                return group
        return None

    def summary(self) -> list[dict[str, Any]]:
        return [
            {"grouping": "|".join(g.keys), "group": g.label,
             "sample_size": g.sample_size, "median_kw": round(g.median_kw, 3),
             "usable": g.sample_size >= self.minimum_sample}
            for g in sorted(self.groups.values(), key=lambda g: (-g.sample_size, g.label))
        ]


def build_empirical_table(
    observations: Iterable[Mapping[str, Any]], defaults: PowerDefaults
) -> EmpiricalTable:
    """Derive rung-2 medians from rung-1 records only.

    Only observations whose power is a *valid reported* value contribute. A median
    built on a handful of points is not reliable, so groups below the configured
    minimum sample are retained for reporting but never used for resolution.
    """
    table = EmpiricalTable(defaults.rung_2_minimum_sample, defaults.rung_2_hierarchy)
    buckets: dict[tuple[str, tuple[str, ...]], list[float]] = {}
    for record in observations:
        if not is_valid_reported_power(record.get("power_kw")):
            continue
        power = float(record["power_kw"])
        for keys in defaults.rung_2_hierarchy:
            values = tuple(str(record.get(k, "")) for k in keys)
            buckets.setdefault(("|".join(keys), values), []).append(power)
    for (grouping, values), powers in buckets.items():
        table.groups[(grouping, values)] = EmpiricalGroup(
            keys=tuple(grouping.split("|")), values=values,
            sample_size=len(powers), median_kw=statistics.median(powers),
        )
    return table


# --- the ladder ------------------------------------------------------------------------

@dataclass(frozen=True)
class ResolvedPower:
    """One connector observation with its power resolved and fully provenanced."""

    connector_type_raw: str
    connector_type_normalized: str
    charging_level: str
    connector_count: int
    power_kw: float | None
    power_source: str
    power_confidence: str
    fallback_group: str | None = None
    is_zero_power_anomaly: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "connector_type_raw": self.connector_type_raw,
            "connector_type_normalized": self.connector_type_normalized,
            "charging_level": self.charging_level,
            "connector_count": self.connector_count,
            "power_kw": self.power_kw,
            "power_source": self.power_source,
            "power_confidence": self.power_confidence,
            "fallback_group": self.fallback_group,
            "is_zero_power_anomaly": self.is_zero_power_anomaly,
        }


def resolve_power(
    record: Mapping[str, Any],
    connectors: Mapping[str, ConnectorSpec],
    empirical: EmpiricalTable,
    defaults: PowerDefaults,
) -> ResolvedPower:
    """Run one connector observation through the three-rung ladder.

    ``charging_level`` is taken from the record and never inferred from the connector
    name (P2-B, CLAUDE.md 7.1.2).
    """
    spec = normalize_connector(str(record.get("connector_type_raw", "")), connectors)
    level = str(record.get("charging_level", ""))
    count = int(record.get("connector_count", 0) or 0)
    raw_power = record.get("power_kw")
    zero_anomaly = raw_power is not None and _as_float(raw_power) == ZERO_POWER

    def build(power: float | None, rung: PowerSource,
              fallback_group: str | None = None) -> ResolvedPower:
        return ResolvedPower(
            connector_type_raw=spec.raw,
            connector_type_normalized=spec.normalized,
            charging_level=level,
            connector_count=count,
            power_kw=power,
            power_source=str(rung),
            power_confidence=str(CONFIDENCE_FOR_SOURCE[rung]),
            fallback_group=fallback_group,
            is_zero_power_anomaly=zero_anomaly,
        )

    # Rung 1
    if is_valid_reported_power(raw_power):
        return build(float(raw_power), PowerSource.REPORTED)  # type: ignore[arg-type]
    # Rung 2
    group = empirical.lookup({
        "network": str(record.get("network", "")),
        "connector_normalized": spec.normalized,
        "charging_level": level,
    })
    if group is not None:
        return build(group.median_kw, PowerSource.EMPIRICAL_FALLBACK, group.label)
    # Rung 3
    default = defaults.default_for(spec.normalized, level)
    if default is not None:
        return build(default, PowerSource.TYPE_DEFAULT)
    # Nothing resolved. Reported as unresolved rather than filled with a guess (D8).
    return build(None, PowerSource.UNRESOLVED)



# --- aggregation: capacity ---------------------------------------------------------
# Resolution (above) answers "what can this connector deliver?". Aggregation answers
# two different questions with two different answers, and they must never substitute
# for one another (CLAUDE.md 7.1.1, gate checks P2-A and P2-H).


@dataclass(frozen=True)
class UnitCapacity:
    """Capacity for one charging-unit record.

    ``generic_service_capacity_kw`` is NON-OVERLAPPING: what the unit can deliver to
    the vehicles it can serve at once. ``connector_compatible_kw`` is per-standard and
    MAY OVERLAP: several entries can describe the same physical service position.
    Summing the latter does not give the former.
    """

    charging_unit_record_key: str
    charging_level: str
    port_count: int
    simultaneous_service_ports: int
    generic_service_capacity_kw: float | None
    generic_capacity_basis: str
    connector_compatible_kw: Mapping[str, float]
    connector_standards_available: tuple[str, ...]
    is_multi_connector_port: bool
    power_source: str
    power_confidence: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "charging_unit_record_key": self.charging_unit_record_key,
            "charging_level": self.charging_level,
            "port_count": self.port_count,
            "simultaneous_service_ports": self.simultaneous_service_ports,
            "generic_service_capacity_kw": self.generic_service_capacity_kw,
            "generic_capacity_basis": self.generic_capacity_basis,
            "connector_compatible_kw": dict(sorted(self.connector_compatible_kw.items())),
            "connector_standards_available": list(self.connector_standards_available),
            "is_multi_connector_port": self.is_multi_connector_port,
            "power_source": self.power_source,
            "power_confidence": self.power_confidence,
        }


class CapacityBasis(StrEnum):
    """How a unit's generic service capacity was derived. Recorded on every row."""

    UNIT_REPORTED_MAXIMUM = "unit_reported_maximum"
    SINGLE_PORT_CONNECTOR_MAXIMUM = "single_port_connector_maximum"
    MULTI_PORT_UNRESOLVED = "multi_port_unresolved"
    UNRESOLVED = "unresolved"


# The weakest resolution among a unit's connectors governs the unit, because a
# capacity is only as trustworthy as the least trustworthy input it rests on.
_SOURCE_RANK = {
    PowerSource.REPORTED: 0,
    PowerSource.EMPIRICAL_FALLBACK: 1,
    PowerSource.TYPE_DEFAULT: 2,
    PowerSource.UNRESOLVED: 3,
}


def aggregate_unit_capacity(
    charging_unit_record_key: str,
    charging_level: str,
    port_count: int,
    resolved: Sequence[ResolvedPower],
    unit_reported_maximum_kw: float | None = None,
) -> UnitCapacity:
    """Combine resolved connector powers into a unit's two capacity quantities.

    Precedence for generic service capacity (CLAUDE.md 7.1.1):

    1. an explicit, trustworthy unit-level maximum output where the source exposes one;
    2. otherwise, for a ``port_count == 1`` unit, the **maximum** resolved compatible
       connector output;
    3. **never** the sum of mutually alternative connector outputs.

    A unit with ``port_count > 1`` does **not** automatically inherit the one-port
    maximum rule. AFDC exposes no per-port connector mapping, so which connectors serve
    which of several ports is unknown, and inventing an allocation would fabricate
    structure the source does not report. Such a unit is reported with
    ``generic_service_capacity_kw = None`` and basis ``multi_port_unresolved`` until
    source semantics settle it (amendment A19).
    """
    present = [r for r in resolved if r.connector_count > 0]
    standards = tuple(sorted({r.connector_type_normalized for r in present}))

    # Connector-compatible capacity: per standard, the best power available for it.
    # These MAY overlap physically and must never be summed into physical capacity.
    compatible: dict[str, float] = {}
    for entry in present:
        if entry.power_kw is None:
            continue
        name = entry.connector_type_normalized
        compatible[name] = max(compatible.get(name, 0.0), entry.power_kw)

    powers = [r.power_kw for r in present if r.power_kw is not None]
    worst = max((_SOURCE_RANK[PowerSource(r.power_source)] for r in present), default=3)
    source = next(k for k, v in _SOURCE_RANK.items() if v == worst)

    if unit_reported_maximum_kw is not None and unit_reported_maximum_kw > ZERO_POWER:
        capacity: float | None = float(unit_reported_maximum_kw)
        basis = CapacityBasis.UNIT_REPORTED_MAXIMUM
        source = PowerSource.REPORTED
    elif port_count > 1:
        capacity, basis = None, CapacityBasis.MULTI_PORT_UNRESOLVED
    elif powers:
        # THE non-double-counting rule. max, never sum.
        capacity, basis = max(powers), CapacityBasis.SINGLE_PORT_CONNECTOR_MAXIMUM
    else:
        capacity, basis = None, CapacityBasis.UNRESOLVED

    return UnitCapacity(
        charging_unit_record_key=charging_unit_record_key,
        charging_level=charging_level,
        port_count=port_count,
        # One service position per port. Connector count is irrelevant here: a
        # dual-standard port serves one vehicle, not two.
        simultaneous_service_ports=port_count,
        generic_service_capacity_kw=capacity,
        generic_capacity_basis=str(basis),
        connector_compatible_kw=compatible,
        connector_standards_available=standards,
        is_multi_connector_port=len(standards) > 1 and port_count == 1,
        power_source=str(source),
        power_confidence=str(CONFIDENCE_FOR_SOURCE[source]),
    )


@dataclass(frozen=True)
class SiteCapacity:
    """Capacity for one site. Generic capacity sums across UNITS, never connectors."""

    site_id: str
    unit_count: int
    simultaneous_service_ports: int
    generic_service_capacity_kw: float
    connector_compatible_kw: Mapping[str, float]
    ports_by_level: Mapping[str, int]
    units_unresolved_capacity: int
    rung_1_capacity_share: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "site_id": self.site_id,
            "unit_count": self.unit_count,
            "simultaneous_service_ports": self.simultaneous_service_ports,
            "generic_service_capacity_kw": round(self.generic_service_capacity_kw, 3),
            "connector_compatible_kw": dict(sorted(self.connector_compatible_kw.items())),
            "ports_by_level": dict(sorted(self.ports_by_level.items())),
            "units_unresolved_capacity": self.units_unresolved_capacity,
            "rung_1_capacity_share": round(self.rung_1_capacity_share, 6),
        }


def aggregate_site_capacity(site_id: str, units: Sequence[UnitCapacity]) -> SiteCapacity:
    """Sum capacity across a site's units.

    Summing across UNITS is correct — separate units genuinely serve separate vehicles
    (domain rule G4: co-located multi-network infrastructure is aggregated for coverage
    and its ports summed for capacity). Summing across CONNECTORS within a unit is not.

    Connector-compatible capacity is also summed across units per standard, and is
    still not physical capacity: a site whose every unit offers both CCS and CHAdeMO
    reports the full site power under each standard, because a CCS vehicle really can
    use all of it — just not at the same time as a CHAdeMO vehicle.
    """
    compatible: dict[str, float] = {}
    levels: dict[str, int] = {}
    generic = 0.0
    unresolved = 0
    rung_1_capacity = 0.0
    for unit in units:
        if unit.generic_service_capacity_kw is None:
            unresolved += 1
        else:
            generic += unit.generic_service_capacity_kw
            if unit.power_source == PowerSource.REPORTED:
                rung_1_capacity += unit.generic_service_capacity_kw
        levels[unit.charging_level] = (levels.get(unit.charging_level, 0)
                                       + unit.simultaneous_service_ports)
        for name, power in unit.connector_compatible_kw.items():
            compatible[name] = compatible.get(name, 0.0) + power
    return SiteCapacity(
        site_id=site_id,
        unit_count=len(units),
        simultaneous_service_ports=sum(u.simultaneous_service_ports for u in units),
        generic_service_capacity_kw=generic,
        connector_compatible_kw=compatible,
        ports_by_level=levels,
        units_unresolved_capacity=unresolved,
        rung_1_capacity_share=(rung_1_capacity / generic) if generic > 0 else 0.0,
    )
