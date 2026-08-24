"""Identifiability analysis for charging units, ports and connectors.

CLAUDE.md section 6.1.1 (amendments A5 and A13) forbids manufacturing physical
identity that the source does not supply, and requires this analysis to run **before
the Phase 1 canonical schema is frozen**. It answers eight questions, reported both
nationally and for the public + operational subset (domain rules G2 and G3):

1. how often unit-level ``port_count`` is available;
2. how often stable, network-provided port identifiers are available;
3. whether connector-specific counts map unambiguously to physical ports;
4. how often ``sum(connector counts) > charging_unit.port_count``, which indicates one
   physical port exposing multiple connector types;
5. what share of infrastructure supports true individual port identity;
6. what share supports only aggregate charging-unit capacity;
7. whether **any stable charging-unit identity** is recoverable from the export or from
   network metadata;
8. whether identical duplicate rows can be distinguished by any means other than row
   order.

The decision rules are fixed in advance in ``docs/reports/PHASE_1_PLAN.md`` so the
outcome cannot be rationalised after the fact.
"""

from __future__ import annotations

import collections
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pipeline.discovery.measure import CONNECTOR_TYPES, is_missing, iter_csv_rows

# The AFDC charging-units export columns this analysis reads. Named explicitly so a
# column rename upstream fails loudly rather than silently producing zeroes.
STATION_KEY = "ID"
LEVEL_COLUMNS = ("EV Level1 EVSE Num", "EV Level2 EVSE Num", "EV DC Fast Count")
STATUS_COLUMN = "Status Code"
ACCESS_COLUMN = "Access Code"
NETWORK_COLUMN = "EV Network"

# Column-name fragments that would indicate a per-unit or per-port identifier if the
# source ever grew one. Checked against the live header so that a future AFDC release
# adding real identity is detected rather than assumed away.
IDENTIFIER_HINTS = ("unit_id", "unitid", "evse_id", "evseid", "port_id", "portid",
                    "serial", "uuid", "guid", "connector_id", "connectorid")
# Columns whose names contain "id" but which are known NOT to be unit identity.
KNOWN_NON_UNIT_IDS = ("ID", "Federal Agency ID", "NPS Unit Name")


def _int(value: object) -> int | None:
    if is_missing(value):
        return None
    try:
        return int(float(str(value).strip()))
    except ValueError:
        return None


@dataclass
class UnitIdentifiability:
    """Accumulated evidence about one scope (national, or public + operational)."""

    scope: str
    rows: int = 0
    stations: set[str] = field(default_factory=set)
    rows_with_level_totals: int = 0
    reported_evse_total: int = 0
    connector_sum_total: int = 0
    rows_connector_sum_exceeds_ports: int = 0
    rows_connector_sum_equals_ports: int = 0
    rows_connector_sum_below_ports: int = 0
    rows_with_no_connector_counts: int = 0
    _row_values: collections.Counter[tuple[str, ...]] = field(
        default_factory=collections.Counter
    )
    _station_rows: collections.Counter[str] = field(default_factory=collections.Counter)
    _station_reported: dict[str, int] = field(default_factory=dict)
    networks: collections.Counter[str] = field(default_factory=collections.Counter)

    def observe(self, row: dict[str, object]) -> None:
        self.rows += 1
        station = str(row.get(STATION_KEY, "")).strip()
        self.stations.add(station)
        self._station_rows[station] += 1
        self._row_values[tuple(str(v) for v in row.values())] += 1
        self.networks[str(row.get(NETWORK_COLUMN, "")).strip()] += 1

        levels = [_int(row.get(column)) for column in LEVEL_COLUMNS]
        if any(level is not None for level in levels):
            self.rows_with_level_totals += 1
            self._station_reported[station] = sum(x for x in levels if x is not None)

        # Measurement 3/4: connector counts against the unit's own port capacity.
        # One export row is one EVSE, so its port capacity is the number of ports that
        # unit presents. Where the connector counts sum higher, one physical port is
        # exposing more than one connector type.
        connector_sum = sum(
            _int(row.get(f"EV {name} Connector Count")) or 0 for name in CONNECTOR_TYPES
        )
        self.connector_sum_total += connector_sum
        if connector_sum == 0:
            self.rows_with_no_connector_counts += 1
        elif connector_sum > 1:
            self.rows_connector_sum_exceeds_ports += 1
        else:
            self.rows_connector_sum_equals_ports += 1

    def finalise(self) -> dict[str, Any]:
        duplicate_groups = {v: c for v, c in self._row_values.items() if c > 1}
        rows_in_duplicate_group = sum(duplicate_groups.values())
        redundant_rows = sum(c - 1 for c in duplicate_groups.values())
        reconciling = sum(
            1
            for station, count in self._station_rows.items()
            if self._station_reported.get(station) == count
        )
        self.reported_evse_total = sum(self._station_reported.values())
        return {
            "scope": self.scope,
            "rows": self.rows,
            "distinct_station_ids": len(self.stations),
            "distinct_full_row_values": len(self._row_values),
            "rows_in_duplicate_group": rows_in_duplicate_group,
            "rows_in_duplicate_group_share": _share(rows_in_duplicate_group, self.rows),
            "redundant_rows": redundant_rows,
            "redundant_rows_share": _share(redundant_rows, self.rows),
            "largest_identical_group": max(self._row_values.values(), default=0),
            "stations_row_count_reconciles_to_reported_evse": reconciling,
            "stations_total": len(self._station_rows),
            "reconciliation_share": _share(reconciling, len(self._station_rows)),
            "rows_with_level_totals": self.rows_with_level_totals,
            "rows_with_level_totals_share": _share(self.rows_with_level_totals, self.rows),
            "connector_counts_sum": self.connector_sum_total,
            "rows_connector_sum_gt_one": self.rows_connector_sum_exceeds_ports,
            "rows_connector_sum_gt_one_share": _share(
                self.rows_connector_sum_exceeds_ports, self.rows
            ),
            "rows_connector_sum_eq_one": self.rows_connector_sum_equals_ports,
            "rows_with_no_connector_counts": self.rows_with_no_connector_counts,
            "distinct_networks": len(self.networks),
        }


def _share(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def scan_header_for_identifiers(header: Sequence[str]) -> dict[str, Any]:
    """Measurement 2 and 7: does the export expose any identifier column at all?"""
    normalised = {name: name.lower().replace(" ", "_") for name in header}
    hits = [
        name
        for name, flat in normalised.items()
        if any(hint in flat for hint in IDENTIFIER_HINTS)
    ]
    id_like = [name for name in header if "id" in name.lower()]
    return {
        "columns": len(header),
        "identifier_columns_found": hits,
        "any_unit_or_port_identifier": bool(hits),
        "id_like_columns": id_like,
        "id_like_columns_that_are_not_unit_identity": [
            name for name in id_like if name in KNOWN_NON_UNIT_IDS
        ],
    }


def analyse(
    rows: Iterable[dict[str, object]], header: Sequence[str]
) -> dict[str, Any]:
    """Run the full eight-measurement analysis over charging-unit rows."""
    national = UnitIdentifiability("national")
    public_operational = UnitIdentifiability("public_operational")
    for row in rows:
        national.observe(row)
        if (
            str(row.get(STATUS_COLUMN, "")).strip() == "E"
            and str(row.get(ACCESS_COLUMN, "")).strip() == "public"
        ):
            public_operational.observe(row)

    identifiers = scan_header_for_identifiers(header)
    scopes = {
        "national": national.finalise(),
        "public_operational": public_operational.finalise(),
    }
    return {
        "identifier_scan": identifiers,
        "scopes": scopes,
        "findings": _conclude(identifiers, scopes),
    }


def _conclude(identifiers: dict[str, Any], scopes: dict[str, Any]) -> dict[str, Any]:
    """Apply the pre-registered decision rules. No judgement is exercised here."""
    national = scopes["national"]
    has_identifier = bool(identifiers["any_unit_or_port_identifier"])
    rows_indistinguishable = national["redundant_rows"] > 0
    return {
        "m1_unit_port_count_available": national["rows_with_level_totals_share"],
        "m2_stable_port_identifier_available": has_identifier,
        "m3_connector_counts_map_unambiguously_to_ports": (
            national["rows_connector_sum_gt_one"] == 0
        ),
        "m4_rows_where_connector_sum_exceeds_one_port": national[
            "rows_connector_sum_gt_one"
        ],
        "m5_share_supporting_individual_port_identity": 1.0 if has_identifier else 0.0,
        "m6_share_supporting_only_aggregate_capacity": 0.0 if has_identifier else 1.0,
        "m7_stable_charging_unit_identity_recoverable": has_identifier,
        "m8_duplicate_rows_distinguishable_other_than_by_order": not rows_indistinguishable,
        "decision_ports_table_populated": has_identifier,
        "decision_charging_unit_key_is_synthetic": not has_identifier,
        "decision_connector_grain": (
            "physical_connector_id"
            if has_identifier
            else "(charging_unit_record_key, connector_type)"
        ),
        "decision_longitudinal_unit_identity_claimable": has_identifier,
    }


# --- JSON representation ----------------------------------------------------------
# The REST endpoint returns a nested ``ev_charging_units`` array per station that the
# CSV export does not expose. It is the only representation carrying a genuine
# UNIT-level ``port_count`` (the CSV carries station-level EVSE totals only), so
# measurement 1 must be taken here to be honest. It also carries a wider connector
# taxonomy than the CSV's five columns.

JSON_UNIT_IDENTIFIER_KEYS = ("id", "unit_id", "evse_id", "uuid", "serial", "port_id")


def analyse_station_json(stations: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Measurement 1 and the network-metadata half of measurement 7."""
    unit_keys: collections.Counter[str] = collections.Counter()
    connector_types: collections.Counter[str] = collections.Counter()
    units = 0
    units_with_port_count = 0
    units_with_connectors = 0
    port_count_total = 0
    connector_sum_exceeds_port_count = 0
    unit_fingerprints: collections.Counter[str] = collections.Counter()
    stations_seen = 0
    for station in stations:
        stations_seen += 1
        for unit in station.get("ev_charging_units") or []:
            units += 1
            unit_keys.update(unit.keys())
            port_count = unit.get("port_count")
            if port_count is not None:
                units_with_port_count += 1
                port_count_total += int(port_count)
            connectors = unit.get("connectors") or {}
            if connectors:
                units_with_connectors += 1
            connector_types.update(connectors.keys())
            positive = sum(
                int((spec or {}).get("port_count") or 0) for spec in connectors.values()
            )
            if port_count is not None and positive > int(port_count):
                connector_sum_exceeds_port_count += 1
            unit_fingerprints[json.dumps(unit, sort_keys=True)] += 1

    identifier_keys = [k for k in unit_keys if k.lower() in JSON_UNIT_IDENTIFIER_KEYS]
    redundant = sum(c - 1 for c in unit_fingerprints.values() if c > 1)
    return {
        "stations": stations_seen,
        "units": units,
        "unit_object_keys": sorted(unit_keys),
        "unit_identifier_keys_found": identifier_keys,
        "any_unit_identifier_in_network_metadata": bool(identifier_keys),
        "units_with_unit_level_port_count": units_with_port_count,
        "unit_level_port_count_share": _share(units_with_port_count, units),
        "total_ports_from_unit_port_count": port_count_total,
        "units_with_connectors_block": units_with_connectors,
        "connector_types_exposed": sorted(connector_types),
        "connector_types_exposed_count": len(connector_types),
        "units_where_connector_ports_exceed_unit_port_count": connector_sum_exceeds_port_count,
        "distinct_unit_objects": len(unit_fingerprints),
        "redundant_unit_objects": redundant,
        "redundant_unit_object_share": _share(redundant, units),
        "largest_identical_unit_group": max(unit_fingerprints.values(), default=0),
    }


def analyse_file(path: Path) -> dict[str, Any]:
    """Run the analysis over a charging-units CSV on disk, streaming it."""
    import csv

    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        header = tuple(csv.DictReader(handle).fieldnames or ())
    return analyse(iter_csv_rows(path), header)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wrapper
    import argparse

    parser = argparse.ArgumentParser(description="AFDC identifiability analysis")
    parser.add_argument("csv", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    result = analyse_file(args.csv)
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.write_text(payload, encoding="utf-8")
    print(payload)
    return 0
