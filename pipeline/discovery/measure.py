"""Measurement primitives: schema discovery, row counts, and per-field missingness.

CLAUDE.md 4.2 task 1 requires the probe to "dump the live schema verbatim". These
functions therefore never rename, normalise case, or reorder discovered field names.
A field called ``EV J1772 Power Output (kW)`` is recorded exactly that way.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Values that count as "missing" in a delimited text source. Whitespace-only cells
# included; the literal strings below are what AFDC, Atlas and Census emit for null.
NULL_TOKENS: frozenset[str] = frozenset({"", "na", "n/a", "null", "none", "nan"})


@dataclass(frozen=True)
class Measurement:
    """What a probe learned about one source's payload."""

    row_count: int
    fields: tuple[str, ...]
    missingness: dict[str, float]
    schema_hash: str
    truncated: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_count": self.row_count,
            "field_count": len(self.fields),
            "fields": list(self.fields),
            "missingness": {k: round(v, 6) for k, v in sorted(self.missingness.items())},
            "schema_hash": self.schema_hash,
            "truncated": self.truncated,
            "notes": list(self.notes),
        }


def is_missing(value: object) -> bool:
    """True when a cell carries no information."""
    if value is None:
        return True
    if isinstance(value, float) and value != value:  # NaN
        return True
    return str(value).strip().lower() in NULL_TOKENS


def schema_hash(fields: Sequence[str]) -> str:
    """Order-sensitive hash of a field list. A column reorder is a schema change."""
    payload = json.dumps(list(fields), separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def measure_records(
    records: Iterable[dict[str, object]],
    fields: Sequence[str],
    truncated: bool = False,
    notes: Sequence[str] = (),
) -> Measurement:
    """Core measurement: count rows and per-field missingness over an iterable of dicts."""
    ordered = tuple(fields)
    present = dict.fromkeys(ordered, 0)
    total = 0
    for record in records:
        total += 1
        for name in ordered:
            if not is_missing(record.get(name)):
                present[name] += 1
    missingness = (
        {name: 1.0 - present[name] / total for name in ordered}
        if total
        else dict.fromkeys(ordered, 1.0)
    )
    return Measurement(
        row_count=total,
        fields=ordered,
        missingness=missingness,
        schema_hash=schema_hash(ordered),
        truncated=truncated,
        notes=tuple(notes),
    )


def measure_delimited(
    payload: bytes,
    delimiter: str = ",",
    encoding: str = "utf-8",
    max_rows: int | None = None,
) -> Measurement:
    """Measure a delimited text payload, preserving the header verbatim.

    ``max_rows`` bounds the sample; when it truncates, the result is flagged so the
    row count is never mistaken for a full count.
    """
    text = payload.decode(encoding, errors="replace")
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    header = tuple(reader.fieldnames or ())
    rows: list[dict[str, object]] = []
    truncated = False
    for row in reader:
        if max_rows is not None and len(rows) >= max_rows:
            truncated = True
            break
        rows.append(dict(row))
    return measure_records(rows, header, truncated=truncated)


def measure_delimited_file(
    path: Path,
    delimiter: str = ",",
    encoding: str = "utf-8",
) -> Measurement:
    """Stream a delimited file from disk so a 27 MB seed CSV never doubles in memory."""
    with path.open("r", encoding=encoding, errors="replace", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        header = tuple(reader.fieldnames or ())
        return measure_records((dict(row) for row in reader), header)


def measure_json_records(
    payload: bytes,
    record_path: Sequence[str] = (),
    max_rows: int | None = None,
) -> Measurement:
    """Measure a JSON payload whose records live at ``record_path`` (a key path).

    The field list is the union of keys observed across sampled records, sorted, so
    that a source with optional keys still reports every field it can emit.
    """
    document: Any = json.loads(payload.decode("utf-8", errors="replace"))
    for step in record_path:
        document = document[step]
    if not isinstance(document, list):
        document = [document]
    truncated = False
    if max_rows is not None and len(document) > max_rows:
        document = document[:max_rows]
        truncated = True
    names: set[str] = set()
    for record in document:
        names.update(record.keys())
    return measure_records(document, tuple(sorted(names)), truncated=truncated)


def iter_geojson_property_names(path: Path, max_features: int) -> Iterator[tuple[str, ...]]:
    """Yield property-name tuples from a GeoJSON file without parsing it whole.

    Domain rule G12 forbids loading the 137 MiB HIFLD transmission GeoJSON as a
    single object anywhere, so this reads it as a text stream and decodes one
    ``"properties": {...}`` object at a time.
    """
    seen = 0
    depth = 0
    buffer: list[str] = []
    capturing = False
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        pending = ""
        while seen < max_features:
            chunk = handle.read(1 << 20)
            if not chunk:
                break
            pending += chunk
            while seen < max_features:
                if not capturing:
                    index = pending.find('"properties"')
                    if index < 0:
                        pending = pending[-16:]
                        break
                    brace = pending.find("{", index)
                    if brace < 0:
                        break
                    pending = pending[brace:]
                    capturing, depth, buffer = True, 0, []
                consumed = 0
                for character in pending:
                    consumed += 1
                    buffer.append(character)
                    if character == "{":
                        depth += 1
                    elif character == "}":
                        depth -= 1
                        if depth == 0:
                            yield tuple(json.loads("".join(buffer)).keys())
                            seen += 1
                            capturing = False
                            break
                pending = pending[consumed:]
                if capturing:
                    break


def measure_geojson_properties(path: Path, max_features: int) -> Measurement:
    """Measure GeoJSON feature properties from a bounded, streamed sample (G12-safe)."""
    records: list[dict[str, object]] = []
    names: set[str] = set()
    for property_names in iter_geojson_property_names(path, max_features):
        names.update(property_names)
        records.append(dict.fromkeys(property_names, 1))
    return measure_records(
        records,
        tuple(sorted(names)),
        truncated=True,
        notes=(
            f"Streamed sample of {len(records)} features; the file is never parsed as a "
            "single GeoJSON object (domain rule G12).",
        ),
    )


# --- HTML table measurement ------------------------------------------------------
# The AFDC vehicle registration pages publish their yearly vintages as an HTML table
# with no JSON or CSV endpoint, so scraping is the only retrieval method available.
# A dependency-free parser keeps the Phase 0 footprint small and fully testable.

_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def parse_html_table(payload: bytes, encoding: str = "utf-8") -> tuple[tuple[str, ...],
                                                                      list[dict[str, object]]]:
    """Return (header, rows) for the first HTML table that has a header row.

    Cell text is tag-stripped and whitespace-trimmed; nothing else is normalised.
    """
    text = payload.decode(encoding, errors="replace")
    raw_rows: list[list[str]] = []
    for row_html in _ROW_RE.findall(text):
        cells = [_TAG_RE.sub("", cell).strip() for cell in _CELL_RE.findall(row_html)]
        if cells:
            raw_rows.append(cells)
    if not raw_rows:
        return (), []
    header = tuple(raw_rows[0])
    rows: list[dict[str, object]] = [
        {header[i]: cell for i, cell in enumerate(body) if i < len(header)}
        for body in raw_rows[1:]
    ]
    return header, rows


def measure_html_table(payload: bytes, encoding: str = "utf-8") -> Measurement:
    """Measure the first HTML table in a page as if it were a delimited source."""
    header, rows = parse_html_table(payload, encoding)
    return measure_records(rows, header)


# --- AFDC per-connector power coverage -------------------------------------------
# CLAUDE.md 4.2 task 2 requires Phase 0 to measure, numerically, whether the AFDC
# charging-units endpoint exposes per-connector power and port counts, because the
# supply model's power-resolution ladder (section 7.1) depends on rung-1 coverage.
# Rung 1 is "reported connector power". Raw column missingness would understate
# coverage badly, since a power column is only meaningful where that connector is
# actually present, so coverage is measured *conditional on the connector existing*
# and weighted by ports, which is the quantity the supply model sums.

CONNECTOR_TYPES: tuple[str, ...] = ("J1772", "CCS", "CHAdeMO", "J3400", "J3271")


def _to_float(value: object) -> float | None:
    if is_missing(value):
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


@dataclass(frozen=True)
class ConnectorCoverage:
    """Rung-1 power coverage for one connector type."""

    connector: str
    units_with_connector: int
    ports: int
    units_with_power: int
    ports_with_power: int

    @property
    def unit_coverage(self) -> float:
        if not self.units_with_connector:
            return 0.0
        return self.units_with_power / self.units_with_connector

    @property
    def port_coverage(self) -> float:
        if not self.ports:
            return 0.0
        return self.ports_with_power / self.ports

    def to_dict(self) -> dict[str, Any]:
        return {
            "connector": self.connector,
            "units_with_connector": self.units_with_connector,
            "ports": self.ports,
            "units_with_power": self.units_with_power,
            "ports_with_power": self.ports_with_power,
            "unit_coverage": round(self.unit_coverage, 6),
            "port_coverage": round(self.port_coverage, 6),
        }


def measure_connector_power_coverage(
    rows: Iterable[dict[str, object]],
    connectors: Sequence[str] = CONNECTOR_TYPES,
    public_operational_only: bool = False,
) -> dict[str, Any]:
    """Measure rung-1 (reported) power coverage over AFDC charging-unit rows.

    ``public_operational_only`` applies domain rules G2 (``Status Code == 'E'``) and
    G3 (``Access Code == 'public'``), which is the subset the supply model treats as
    public operational supply.
    """
    counters = {
        name: {"units": 0, "ports": 0, "units_kw": 0, "ports_kw": 0} for name in connectors
    }
    considered = 0
    zero_power_cells = 0
    for row in rows:
        if public_operational_only and not (
            str(row.get("Status Code", "")).strip() == "E"
            and str(row.get("Access Code", "")).strip() == "public"
        ):
            continue
        considered += 1
        for name in connectors:
            count = _to_float(row.get(f"EV {name} Connector Count")) or 0.0
            if count <= 0:
                continue
            power = _to_float(row.get(f"EV {name} Power Output (kW)"))
            bucket = counters[name]
            bucket["units"] += 1
            bucket["ports"] += int(count)
            if power is not None:
                bucket["units_kw"] += 1
                bucket["ports_kw"] += int(count)
                if power == 0.0:
                    zero_power_cells += 1
    per_connector = [
        ConnectorCoverage(
            connector=name,
            units_with_connector=counters[name]["units"],
            ports=counters[name]["ports"],
            units_with_power=counters[name]["units_kw"],
            ports_with_power=counters[name]["ports_kw"],
        )
        for name in connectors
    ]
    total_ports = sum(c.ports for c in per_connector)
    total_ports_kw = sum(c.ports_with_power for c in per_connector)
    return {
        "rows_considered": considered,
        "public_operational_only": public_operational_only,
        "per_connector": [c.to_dict() for c in per_connector],
        "total_ports": total_ports,
        "total_ports_with_reported_power": total_ports_kw,
        "rung1_port_coverage": round(total_ports_kw / total_ports, 6) if total_ports else 0.0,
        "reported_power_equal_zero_cells": zero_power_cells,
    }


def iter_csv_rows(path: Path, encoding: str = "utf-8") -> Iterator[dict[str, object]]:
    """Stream a CSV from disk as dicts, so a 111 MB export never loads whole."""
    with path.open("r", encoding=encoding, errors="replace", newline="") as handle:
        yield from csv.DictReader(handle)
