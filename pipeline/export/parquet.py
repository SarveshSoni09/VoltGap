"""Parquet writing, via DuckDB.

DuckDB is already the project's warehouse (§2), so parquet needs no new dependency and
therefore no new supply-chain or licence question. Written with ZSTD, which the browser
reader handles and which is materially smaller than Snappy on this data.

**Columnar on purpose.** §12 budgets `hex6_national.parquet` at 8-15 MB and notes HTTP
range requests. Parquet stores each column separately, so a browser reading one metric
fetches that column's pages rather than the whole file. Row-group size is set small enough
that a range request is worth making and large enough that the footer does not dominate.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

#: Rows per group. 8,192 keeps each group's column chunk in the tens of kilobytes at this
#: width, so a range request fetches a useful amount without pulling the whole column.
ROW_GROUP_SIZE = 8192

#: ZSTD at its default level. Measured against Snappy on the national surface; the choice
#: is recorded here rather than left implicit because artifact size is a §12 budget.
COMPRESSION = "zstd"


class ExportError(RuntimeError):
    """An artifact could not be written, or would have been written wrong."""


@dataclass(frozen=True)
class WrittenArtifact:
    """One published file, with everything `manifest.json` needs to describe it (§12)."""

    name: str
    path: Path
    rows: int
    bytes: int
    sha256: str
    columns: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "bytes": self.bytes,
            "rows": self.rows,
            "sha256": self.sha256,
            "columns": list(self.columns),
        }


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_parquet(
    rows: Sequence[Mapping[str, Any]],
    columns: Sequence[str],
    path: Path,
    name: str | None = None,
) -> WrittenArtifact:
    """Write rows to parquet in the given column order.

    Raises rather than writing a partial artifact: a row missing a column would produce a
    file that loads fine and renders a blank metric, which is the failure mode hardest to
    notice from the browser.
    """
    if not rows:
        raise ExportError(f"{path.name}: refusing to write an empty artifact")
    missing = {c for c in columns if c not in rows[0]}
    if missing:
        raise ExportError(f"{path.name}: rows are missing columns {sorted(missing)}")

    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    try:
        connection.register("rows", _as_columns(rows, columns))
        projection = ", ".join(f'"{c}"' for c in columns)
        connection.execute(
            f"COPY (SELECT {projection} FROM rows) TO '{path}' "
            f"(FORMAT PARQUET, COMPRESSION '{COMPRESSION}', "
            f"ROW_GROUP_SIZE {ROW_GROUP_SIZE})"
        )
    finally:
        connection.close()
    return WrittenArtifact(
        name=name or path.name, path=path, rows=len(rows),
        bytes=path.stat().st_size, sha256=sha256_of(path),
        columns=tuple(columns),
    )


def _as_columns(
    rows: Sequence[Mapping[str, Any]], columns: Sequence[str]
) -> Any:
    """Rows to a column-oriented frame DuckDB can register without a copy per row."""
    import pandas as pd

    return pd.DataFrame({c: [row[c] for row in rows] for c in columns})
