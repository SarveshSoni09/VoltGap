"""DuckDB transform runner: staging -> intermediate -> marts, in dependency order.

CLAUDE.md section 9 fixes the layering:

* ``staging/stg_*.sql``       one per source, typing and renaming only, **no filtering**
* ``intermediate/int_*.sql``  joins, entity resolution, spatial allocation, business filters
* ``marts/mart_*.sql``        the tables that become published artifacts

Execution order is derived from the layer, then from the filename within a layer, so a
run is reproducible and a reader can predict it. Every mart carries ``computed_at`` and
``source_vintages``.

Determinism (CLAUDE.md section 14.1, amendment A14) is *semantic*, not byte-level: the
runner accepts an injected ``computed_at`` so that a replay run against pinned inputs
produces an identical semantic hash, while a live run still records when it happened.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from pipeline.config.settings import PATHS
from pipeline.sources.base import StagedTable

LAYERS: tuple[str, ...] = ("staging", "intermediate", "marts")
MODELS_ROOT = Path(__file__).resolve().parent / "models"

# Columns whose value is a function of *when* a run happened rather than of what the
# data are. Excluded from the semantic hash (CLAUDE.md 14.1).
VOLATILE_COLUMNS: frozenset[str] = frozenset({
    "computed_at", "retrieved_at", "last_successful_retrieval", "elapsed_ms",
})


class TransformError(RuntimeError):
    """A model failed to execute."""


@dataclass(frozen=True)
class ModelResult:
    """One executed SQL model."""

    layer: str
    name: str
    rows: int
    columns: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"layer": self.layer, "name": self.name, "rows": self.rows,
                "columns": list(self.columns)}


def discover_models(root: Path = MODELS_ROOT) -> list[tuple[str, Path]]:
    """Every SQL model, ordered by layer then filename."""
    found: list[tuple[str, Path]] = []
    for layer in LAYERS:
        directory = root / layer
        if not directory.is_dir():
            continue
        found.extend((layer, path) for path in sorted(directory.glob("*.sql")))
    return found


class Warehouse:
    """A file-backed or in-memory DuckDB warehouse."""

    def __init__(self, database: str | Path = ":memory:") -> None:
        self.connection = duckdb.connect(str(database))
        self.connection.execute("SET TimeZone='UTC'")

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> Warehouse:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- loading -------------------------------------------------------------------

    def load_staged(self, table: StagedTable) -> None:
        """Register a staged table as ``raw_<source_id>``, all columns VARCHAR.

        Typing happens in the staging SQL layer, where a type error is visible and
        testable, rather than being swallowed during retrieval.

        Loading goes through Arrow rather than row-by-row parameter binding. The Atlas
        Minnesota export alone is 903,083 rows; binding those individually dominated
        the whole test suite's runtime.
        """
        name = f"raw_{table.source_id}"
        columns = ", ".join(f'"{c}" VARCHAR' for c in table.columns)
        self.connection.execute(f'CREATE OR REPLACE TABLE "{name}" ({columns})')
        if not table.rows:
            return
        frame = pd.DataFrame(
            {c: [row.get(c, "") for row in table.rows] for c in table.columns},
            dtype="object",
        )
        self.connection.register("_staged_frame", frame)
        try:
            projection = ", ".join(f'CAST("{c}" AS VARCHAR) AS "{c}"'
                                   for c in table.columns)
            self.connection.execute(
                f'INSERT INTO "{name}" SELECT {projection} FROM _staged_frame'
            )
        finally:
            self.connection.unregister("_staged_frame")

    def load_records(self, name: str, columns: Sequence[str],
                     rows: Iterable[Sequence[object]]) -> None:
        """Register a computed table (site clusters, crosswalk output, and similar)."""
        column_sql = ", ".join(f'"{c}" VARCHAR' for c in columns)
        self.connection.execute(f'CREATE OR REPLACE TABLE "{name}" ({column_sql})')
        payload = [list(row) for row in rows]
        if payload:
            placeholders = ", ".join("?" for _ in columns)
            self.connection.executemany(
                f'INSERT INTO "{name}" VALUES ({placeholders})', payload
            )

    # --- execution -----------------------------------------------------------------

    def run_model(self, layer: str, path: Path, context: Mapping[str, str]) -> ModelResult:
        """Execute one SQL model as ``CREATE OR REPLACE TABLE <stem> AS <sql>``."""
        name = path.stem
        sql = path.read_text(encoding="utf-8")
        try:
            rendered = sql.format(**context)
        except KeyError as exc:
            raise TransformError(f"{name}: unknown placeholder {exc}") from exc
        try:
            self.connection.execute(f'CREATE OR REPLACE TABLE "{name}" AS {rendered}')
        except duckdb.Error as exc:
            raise TransformError(f"{name}: {exc}") from exc
        rows = self.connection.execute(f'SELECT count(*) FROM "{name}"').fetchone()
        described = self.connection.execute(f'DESCRIBE "{name}"').fetchall()
        return ModelResult(layer, name, int(rows[0]) if rows else 0,
                           tuple(str(d[0]) for d in described))

    def run_all(self, context: Mapping[str, str],
                root: Path = MODELS_ROOT) -> list[ModelResult]:
        return [self.run_model(layer, path, context)
                for layer, path in discover_models(root)]

    # --- inspection ----------------------------------------------------------------

    def table_names(self) -> list[str]:
        rows = self.connection.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='main' ORDER BY table_name"
        ).fetchall()
        return [str(r[0]) for r in rows]

    def fetch_df(self, table: str) -> Any:
        return self.connection.execute(f'SELECT * FROM "{table}"').df()

    def semantic_hash(self, tables: Sequence[str]) -> str:
        """Order-independent hash over table contents, volatile columns excluded.

        Implements the determinism definition in CLAUDE.md 14.1. Rows are sorted
        before hashing so that a change in row *order* alone is not treated as a
        semantic change, and `computed_at` and friends are dropped so that a replay
        run against pinned inputs reproduces the hash exactly.
        """
        import hashlib

        digest = hashlib.sha256()
        for table in sorted(tables):
            described = self.connection.execute(f'DESCRIBE "{table}"').fetchall()
            keep = [str(d[0]) for d in described if str(d[0]) not in VOLATILE_COLUMNS]
            digest.update(f"TABLE:{table}:{','.join(keep)}\n".encode())
            if not keep:
                continue
            projection = ", ".join(f'CAST("{c}" AS VARCHAR)' for c in keep)
            rows = self.connection.execute(
                f'SELECT {projection} FROM "{table}"'
            ).fetchall()
            for row in sorted(str(tuple(r)) for r in rows):
                digest.update(row.encode())
                digest.update(b"\n")
        return digest.hexdigest()


def build_context(source_vintages: Mapping[str, str],
                  computed_at: str | None = None) -> dict[str, str]:
    """Values substituted into every model. ``computed_at`` is injectable for replay."""
    return {
        "computed_at": computed_at or datetime.now(UTC).isoformat(timespec="seconds"),
        "source_vintages": json.dumps(dict(sorted(source_vintages.items())),
                                      separators=(",", ":")),
    }


def default_database() -> Path:
    return PATHS.root / "data" / "warehouse" / "voltgap.duckdb"
