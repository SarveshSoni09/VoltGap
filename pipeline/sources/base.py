"""Source adapter framework: retrieval, vintage stamping, and lossless staging.

**The governing rule (CLAUDE.md section 9, amendment A15): retrieval and staging
preserve source rows.** An adapter may decode, decompress, handle character sets,
stream a large file, or reshape a fixed layout into rows — mechanical, lossless work.
It may **not** drop, filter, or editorialise rows. Every business filter (domain rules
G2 status, G3 access, G8 total rows, voltage thresholds) belongs in the intermediate
layer, where it is visible and testable.

The rule is enforced structurally rather than by convention: :class:`StagedTable`
records ``source_row_count`` alongside the rows it carries, and
:meth:`StagedTable.assert_lossless` raises if they ever disagree. Every adapter is
tested against it.

Adapters return staged rows with **all values as strings**. Typing belongs to the
staging SQL layer, which is where a type error becomes visible and testable rather
than being silently swallowed during retrieval.
"""

from __future__ import annotations

import csv
import io
import json
from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pipeline.discovery.cache import Fetcher, Response
from pipeline.discovery.measure import parse_html_table, schema_hash


class LossyStagingError(RuntimeError):
    """Raised when an adapter produced a different number of rows than it retrieved.

    That is always a defect: staging is not permitted to filter (A15).
    """


@dataclass(frozen=True)
class SourceVintage:
    """Provenance stamp carried on every staged table and propagated to every mart."""

    source_id: str
    vintage: str | None
    retrieved_at: str
    content_sha256: str | None = None
    endpoint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "vintage": self.vintage,
            "retrieved_at": self.retrieved_at,
            "content_sha256": self.content_sha256,
            "endpoint": self.endpoint,
        }


@dataclass
class StagedTable:
    """Rows exactly as the source supplied them, plus provenance."""

    source_id: str
    columns: tuple[str, ...]
    rows: list[dict[str, str]]
    vintage: SourceVintage
    source_row_count: int
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def schema_hash(self) -> str:
        return schema_hash(self.columns)

    def assert_unique_columns(self) -> StagedTable:
        """A duplicate column name silently loses data downstream; reject it here."""
        seen = [c for c in self.columns if self.columns.count(c) > 1]
        if seen:
            raise LossyStagingError(
                f"{self.source_id}: duplicate column name(s) {sorted(set(seen))}"
            )
        return self

    def assert_lossless(self) -> StagedTable:
        """Enforce A15. Called by every adapter before returning."""
        self.assert_unique_columns()
        if len(self.rows) != self.source_row_count:
            raise LossyStagingError(
                f"{self.source_id}: staging produced {len(self.rows)} rows from "
                f"{self.source_row_count} source rows. Retrieval and staging must "
                "preserve source rows; business filtering belongs in the intermediate "
                "layer (CLAUDE.md section 9)."
            )
        return self


class Source(ABC):
    """One ingestible source."""

    source_id: str
    endpoint: str

    def __init__(self, source_id: str, endpoint: str = "") -> None:
        self.source_id = source_id
        self.endpoint = endpoint

    @abstractmethod
    def load(self, fetcher: Fetcher | None = None) -> StagedTable:
        """Retrieve and stage. Must preserve every source row."""

    def _vintage(self, response: Response | None = None,
                 vintage: str | None = None) -> SourceVintage:
        if response is None:
            return SourceVintage(self.source_id, vintage, "", None, self.endpoint)
        return SourceVintage(
            source_id=self.source_id,
            vintage=vintage or response.headers.get("last-modified"),
            retrieved_at=response.retrieved_at,
            content_sha256=response.content_sha256,
            endpoint=self.endpoint,
        )


# --- mechanical decoders ----------------------------------------------------------
# Each returns (columns, rows). None of them drops a row.

def decode_delimited(payload: bytes, delimiter: str = ",",
                     encoding: str = "utf-8") -> tuple[tuple[str, ...], list[dict[str, str]]]:
    """Parse delimited text. Header preserved verbatim; every data row kept."""
    reader = csv.DictReader(
        io.StringIO(payload.decode(encoding, errors="replace")), delimiter=delimiter
    )
    columns = tuple(reader.fieldnames or ())
    rows = [{name: (row.get(name) or "") for name in columns} for row in reader]
    return columns, rows


def decode_json_records(payload: bytes, record_path: Sequence[str] = ()
                        ) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    """Parse JSON records into flat string rows. Nested values are re-serialised."""
    document: Any = json.loads(payload.decode("utf-8", errors="replace"))
    for step in record_path:
        document = document[step]
    if not isinstance(document, list):
        document = [document]
    names: set[str] = set()
    for record in document:
        names.update(record.keys())
    columns = tuple(sorted(names))
    rows = [
        {name: _flatten(record.get(name)) for name in columns} for record in document
    ]
    return columns, rows


def _flatten(value: object) -> str:
    """Scalars become strings; containers are re-serialised so nothing is lost."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return str(value)


def decode_html_table(payload: bytes) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    """Parse the first HTML table. Every row kept, including any total row (G8)."""
    header, raw_rows = parse_html_table(payload)
    rows = [{name: str(row.get(name, "")) for name in header} for row in raw_rows]
    return header, rows


def iter_delimited_file(path: Path, delimiter: str = ",",
                        encoding: str = "utf-8") -> Iterator[dict[str, str]]:
    """Stream a delimited file so a 27 MB seed CSV never doubles in memory."""
    with path.open("r", encoding=encoding, errors="replace", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        names = tuple(reader.fieldnames or ())
        for row in reader:
            yield {name: (row.get(name) or "") for name in names}


# --- generic adapters --------------------------------------------------------------

class DelimitedSource(Source):
    """CSV or pipe-delimited text, remote or local."""

    def __init__(self, source_id: str, *, endpoint: str = "", path: Path | None = None,
                 params: Mapping[str, str] | None = None,
                 headers: Mapping[str, str] | None = None,
                 delimiter: str = ",", encoding: str = "utf-8") -> None:
        super().__init__(source_id, endpoint)
        self.path = path
        self.params = dict(params or {})
        self.headers = dict(headers or {})
        self.delimiter = delimiter
        self.encoding = encoding

    def load(self, fetcher: Fetcher | None = None) -> StagedTable:
        if self.path is not None:
            with self.path.open("r", encoding=self.encoding, errors="replace",
                                newline="") as handle:
                reader = csv.DictReader(handle, delimiter=self.delimiter)
                columns = tuple(reader.fieldnames or ())
                rows = [{name: (row.get(name) or "") for name in columns} for row in reader]
            vintage = self._vintage(None, vintage="frozen fixture")
        else:
            if fetcher is None:
                raise ValueError(f"{self.source_id}: remote source needs a fetcher")
            response = fetcher.get(self.source_id, self.endpoint, self.params, self.headers)
            columns, rows = decode_delimited(response.content, self.delimiter, self.encoding)
            vintage = self._vintage(response)
        return StagedTable(self.source_id, columns, rows, vintage, len(rows)).assert_lossless()


class JsonRecordsSource(Source):
    """JSON records at a key path."""

    def __init__(self, source_id: str, endpoint: str,
                 record_path: Sequence[str] = (),
                 params: Mapping[str, str] | None = None,
                 path: Path | None = None) -> None:
        super().__init__(source_id, endpoint)
        self.record_path = tuple(record_path)
        self.params = dict(params or {})
        self.path = path

    def load(self, fetcher: Fetcher | None = None) -> StagedTable:
        if self.path is not None:
            payload = self.path.read_bytes()
            vintage = self._vintage(None, vintage="local snapshot")
        else:
            if fetcher is None:
                raise ValueError(f"{self.source_id}: remote source needs a fetcher")
            response = fetcher.get(self.source_id, self.endpoint, self.params)
            payload = response.content
            vintage = self._vintage(response)
        columns, rows = decode_json_records(payload, self.record_path)
        return StagedTable(self.source_id, columns, rows, vintage, len(rows)).assert_lossless()


class HtmlTableSource(Source):
    """An HTML table, the only retrieval method AFDC offers for registration vintages."""

    def __init__(self, source_id: str, endpoint: str,
                 params: Mapping[str, str] | None = None,
                 headers: Mapping[str, str] | None = None,
                 vintage: str | None = None) -> None:
        super().__init__(source_id, endpoint)
        self.params = dict(params or {})
        self.headers = dict(headers or {})
        self.declared_vintage = vintage

    def load(self, fetcher: Fetcher | None = None) -> StagedTable:
        if fetcher is None:
            raise ValueError(f"{self.source_id}: remote source needs a fetcher")
        response = fetcher.get(self.source_id, self.endpoint, self.params, self.headers)
        columns, rows = decode_html_table(response.content)
        return StagedTable(
            self.source_id, columns, rows,
            self._vintage(response, self.declared_vintage), len(rows),
            notes=("Includes the published total row; G8 removes it in intermediate.",),
        ).assert_lossless()


class NestedUnitsSource(Source):
    """AFDC station JSON reshaped to one row per nested charging unit.

    Reshaping a fixed nested layout into rows is mechanical and lossless, so A15
    permits it. Every unit object in the payload becomes exactly one row; none is
    dropped, merged or deduplicated, because the Phase 1 identifiability analysis
    established that identical unit objects are *real distinct physical units* that
    happen to be indistinguishable in every reported attribute (the same situation as
    domain rule G4 for coordinate duplicates).

    A synthetic ``charging_unit_record_key`` is assigned as
    ``{station_id}:{ordinal}``. It is **per-snapshot and carries no longitudinal
    meaning** — see CLAUDE.md section 6.1.1. The ordinal is row order within the
    station, which is the only thing that separates identical units, and row order is
    not guaranteed stable across refreshes. This key must never be used to track a
    unit over time.
    """

    STATION_FIELDS = ("state", "status_code", "access_code", "ev_network",
                      "latitude", "longitude", "open_date", "station_name", "city",
                      "zip", "facility_type", "owner_type_code", "date_last_confirmed")
    UNIT_FIELDS = ("port_count", "charging_level", "network")

    def __init__(self, source_id: str, endpoint: str,
                 params: Mapping[str, str] | None = None,
                 path: Path | None = None) -> None:
        super().__init__(source_id, endpoint)
        self.params = dict(params or {})
        self.path = path

    def load(self, fetcher: Fetcher | None = None) -> StagedTable:
        if self.path is not None:
            payload = self.path.read_bytes()
            vintage = self._vintage(None, vintage="local snapshot")
        else:
            if fetcher is None:
                raise ValueError(f"{self.source_id}: remote source needs a fetcher")
            response = fetcher.get(self.source_id, self.endpoint, self.params)
            payload = response.content
            vintage = self._vintage(response)

        document = json.loads(payload.decode("utf-8", errors="replace"))
        stations = document.get("fuel_stations", document) if isinstance(
            document, dict) else document

        connector_names: set[str] = set()
        staged: list[dict[str, str]] = []
        source_units = 0
        for station in stations:
            units = station.get("ev_charging_units") or []
            for ordinal, unit in enumerate(units):
                source_units += 1
                row: dict[str, str] = {
                    "charging_unit_record_key": f"{station.get('id')}:{ordinal}",
                    "station_id": _flatten(station.get("id")),
                    "record_ordinal": str(ordinal),
                }
                for name in self.STATION_FIELDS:
                    row[f"station_{name}"] = _flatten(station.get(name))
                for name in self.UNIT_FIELDS:
                    row[f"unit_{name}"] = _flatten(unit.get(name))
                for connector, spec in (unit.get("connectors") or {}).items():
                    connector_names.add(connector)
                    row[f"connector_{connector}_port_count"] = _flatten(
                        (spec or {}).get("port_count"))
                    row[f"connector_{connector}_power_kw"] = _flatten(
                        (spec or {}).get("power_kw"))
                staged.append(row)

        columns = (
            "charging_unit_record_key", "station_id", "record_ordinal",
            *(f"station_{name}" for name in self.STATION_FIELDS),
            *(f"unit_{name}" for name in self.UNIT_FIELDS),
            *(
                f"connector_{name}_{suffix}"
                for name in sorted(connector_names)
                for suffix in ("port_count", "power_kw")
            ),
        )
        rows = [{name: row.get(name, "") for name in columns} for row in staged]
        return StagedTable(
            self.source_id, columns, rows, vintage, source_units,
            notes=(
                "charging_unit_record_key is synthetic and per-snapshot; it carries no "
                "longitudinal physical-unit identity (CLAUDE.md 6.1.1).",
                "Identical unit rows are real distinct physical units, not duplicates "
                "to be collapsed.",
            ),
        ).assert_lossless()
