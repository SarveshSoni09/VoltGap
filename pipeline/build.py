"""One command rebuilds every canonical table.

    python -m pipeline.build --fixture           # MN + IL two-state fixture
    python -m pipeline.build --national          # everything
    python -m pipeline.build --fixture --offline # replay only, no network

Sequence: retrieve sources (preserving every source row, A15) -> load into DuckDB ->
resolve sites by spatial clustering -> execute staging, intermediate and mart SQL in
dependency order -> validate every canonical table against its pandera schema, failing
the build on violation (CLAUDE.md section 9).
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pipeline.config.settings import PATHS
from pipeline.discovery.cache import Fetcher, LiveFetcher, ReplayFetcher
from pipeline.discovery.registry import ATLAS_STATES
from pipeline.sources.base import StagedTable
from pipeline.sources.catalog import (
    afdc_registration_sources,
    atlas_sources,
    local_json_source,
    seed_sources,
)
from pipeline.spatial.clustering import cluster_sites
from pipeline.transform.runner import ModelResult, Warehouse, build_context

# Source geography per Atlas state, declared explicitly and never inferred from column
# naming (CLAUDE.md 7.5.1). A USPS ZIP Code is a mail-delivery route collection, not an
# area, and is not interchangeable with a Census ZCTA.
ATLAS_GEOGRAPHY: dict[str, str] = {
    code: ("usps_zip" if grain == "zip" else "county") for code, _slug, grain in ATLAS_STATES
}
ATLAS_GEOGRAPHY_COLUMN: dict[str, str] = {"usps_zip": "ZIP Code", "county": "County"}


@dataclass
class BuildResult:
    """What a build produced."""

    models: list[ModelResult] = field(default_factory=list)
    source_vintages: dict[str, str] = field(default_factory=dict)
    staged_row_counts: dict[str, int] = field(default_factory=dict)
    semantic_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "models": [m.to_dict() for m in self.models],
            "source_vintages": dict(sorted(self.source_vintages.items())),
            "staged_row_counts": dict(sorted(self.staged_row_counts.items())),
            "semantic_hash": self.semantic_hash,
        }


def union_staged(source_id: str, tables: Sequence[StagedTable],
                 extra: Mapping[str, Sequence[str]] | None = None) -> StagedTable:
    """Concatenate staged tables into one, adding constant tag columns.

    Concatenation is mechanical and lossless: the union carries exactly the sum of the
    input rows, and ``assert_lossless`` enforces it.
    """
    extra = extra or {}
    columns: list[str] = []
    for table in tables:
        for name in table.columns:
            if name not in columns:
                columns.append(name)
    columns.extend(name for name in extra if name not in columns)

    rows: list[dict[str, str]] = []
    total = 0
    for index, table in enumerate(tables):
        tags = {name: values[index] for name, values in extra.items()}
        total += table.source_row_count
        for row in table.rows:
            rows.append({name: row.get(name, tags.get(name, "")) for name in columns})

    vintage = tables[0].vintage if tables else None
    assert vintage is not None, "union_staged needs at least one table"
    return StagedTable(source_id, tuple(columns), rows, vintage, total).assert_lossless()


def load_afdc(warehouse: Warehouse, result: BuildResult, *,
              stations_path: Path, units_path: Path) -> None:
    """Load AFDC stations and charging units from a cached national or state pull."""
    for source_id, path in (("afdc_stations", stations_path),
                            ("afdc_charging_units", units_path)):
        table = local_json_source(source_id, path).load()
        warehouse.load_staged(table)
        result.source_vintages[source_id] = table.vintage.vintage or "unknown"
        result.staged_row_counts[source_id] = len(table.rows)


def load_state_registrations(warehouse: Warehouse, result: BuildResult,
                             fetcher: Fetcher) -> None:
    """Ten annual AFDC vintages, unioned with a vintage tag."""
    sources = afdc_registration_sources()
    tables = [source.load(fetcher) for _, source in sorted(sources.items())]
    vintages = [str(source.declared_vintage)  # type: ignore[attr-defined]
                for _, source in sorted(sources.items())]
    union = union_staged("afdc_state_ev_registrations", tables, {"vintage": vintages})
    warehouse.load_staged(union)
    result.source_vintages["afdc_state_ev_registrations"] = ",".join(vintages)
    result.staged_row_counts["afdc_state_ev_registrations"] = len(union.rows)


def load_atlas(warehouse: Warehouse, result: BuildResult, fetcher: Fetcher,
               states: tuple[str, ...]) -> None:
    """Atlas state DMV registrations, with source geography declared per row."""
    sources = atlas_sources(states)
    if not sources:
        warehouse.load_records(
            "raw_atlas_registrations",
            ("State", "source_geography_type", "source_geography_id",
             "Registration Date", "Vehicle Make", "Vehicle Model", "Drivetrain Type",
             "Vehicle Count", "DMV Snapshot ID", "DMV Snapshot (Date)",
             "Latest DMV Snapshot Flag"),
            [],
        )
        return

    tables: list[StagedTable] = []
    codes: list[str] = []
    geographies: list[str] = []
    for source_id, source in sorted(sources.items()):
        code = source_id.rsplit("_", 1)[-1].upper()
        geography = ATLAS_GEOGRAPHY[code]
        table = source.load(fetcher)
        # Copy the state's own geography column into a uniformly named column. This is
        # a rename, not a filter: no row is dropped and no value is changed.
        column = ATLAS_GEOGRAPHY_COLUMN[geography]
        for row in table.rows:
            row["source_geography_id"] = row.get(column, "")
        table.columns = (*table.columns, "source_geography_id")
        tables.append(table)
        codes.append(code)
        geographies.append(geography)
        result.source_vintages[source_id] = table.vintage.vintage or "unknown"

    union = union_staged("atlas_registrations", tables,
                         {"source_geography_type": geographies})
    warehouse.load_staged(union)
    result.staged_row_counts["atlas_registrations"] = len(union.rows)


def load_seeds(warehouse: Warehouse, result: BuildResult,
               only: Sequence[str] | None = None) -> None:
    """The frozen seed fixtures. Their expectations never drift with the live source."""
    for source_id, source in sorted(seed_sources().items()):
        if only is not None and source_id not in only:
            continue
        table = source.load()
        warehouse.load_staged(table)
        result.source_vintages[source_id] = "frozen fixture"
        result.staged_row_counts[source_id] = len(table.rows)


def load_population(warehouse: Warehouse, result: BuildResult, fetcher: Fetcher,
                    state_fips: str = "27") -> None:
    """Population-weighted block group centroids: Phase 2's access geography.

    Block group is the finest ready-made population-weighted centroid the Census
    Bureau publishes; Phase 0 finding F-7 established that no block-level product
    exists.
    """
    from pipeline.sources.catalog import census_sources

    source = census_sources(state_fips)["census_cenpop_blockgroup"]
    table = source.load(fetcher)
    warehouse.load_staged(table)
    result.source_vintages["census_cenpop_blockgroup"] = table.vintage.vintage or "2020"
    result.staged_row_counts["census_cenpop_blockgroup"] = len(table.rows)


def resolve_sites(warehouse: Warehouse) -> int:
    """Cluster station coordinates into sites and register the assignment table."""
    rows = warehouse.connection.execute(
        "SELECT station_id, latitude, longitude FROM stg_afdc_stations"
    ).fetchall()
    assignments = cluster_sites(
        [str(r[0]) for r in rows],
        [r[1] for r in rows],
        [r[2] for r in rows],
    )
    warehouse.load_records(
        "computed_site_assignments",
        ("station_id", "site_id", "site_latitude", "site_longitude",
         "site_station_count"),
        [
            (a.station_id, a.site_id, repr(a.site_latitude), repr(a.site_longitude),
             str(a.site_station_count))
            for a in assignments
        ],
    )
    # site_latitude/longitude arrive as VARCHAR; cast them once here so the marts can
    # aggregate them numerically.
    warehouse.connection.execute(
        "CREATE OR REPLACE TABLE computed_site_assignments AS "
        "SELECT station_id, site_id, TRY_CAST(site_latitude AS DOUBLE) AS site_latitude, "
        "TRY_CAST(site_longitude AS DOUBLE) AS site_longitude, "
        "TRY_CAST(site_station_count AS INTEGER) AS site_station_count "
        "FROM computed_site_assignments"
    )
    return len({a.site_id for a in assignments})


MART_TABLES: tuple[str, ...] = (
    "mart_sites", "mart_stations", "mart_charging_units",
    "mart_charging_unit_connectors", "mart_state_totals",
    "mart_observed_subregion_ev",
)


def build(
    warehouse: Warehouse,
    fetcher: Fetcher,
    *,
    stations_path: Path,
    units_path: Path,
    atlas_states: tuple[str, ...] = (),
    computed_at: str | None = None,
) -> BuildResult:
    """Run the whole canonical build against an open warehouse."""
    result = BuildResult()
    load_afdc(warehouse, result, stations_path=stations_path, units_path=units_path)
    load_seeds(warehouse, result)
    # Not optional: stg_state_ev_registrations.sql reads raw_afdc_state_ev_registrations,
    # so skipping this would fail the staging layer rather than produce a smaller build.
    load_state_registrations(warehouse, result, fetcher)
    load_atlas(warehouse, result, fetcher, atlas_states)
    load_population(warehouse, result, fetcher)

    context = build_context(result.source_vintages, computed_at)
    # Staging must exist before sites can be clustered from it, so the run is split.
    from pipeline.transform.runner import MODELS_ROOT, discover_models

    for layer, path in discover_models(MODELS_ROOT):
        if layer == "staging":
            result.models.append(warehouse.run_model(layer, path, context))
    resolve_sites(warehouse)
    for layer, path in discover_models(MODELS_ROOT):
        if layer != "staging":
            result.models.append(warehouse.run_model(layer, path, context))

    validate_marts(warehouse)
    result.semantic_hash = warehouse.semantic_hash(MART_TABLES)
    return result


def validate_marts(warehouse: Warehouse) -> dict[str, int]:
    """Validate every canonical table against its pandera schema.

    CLAUDE.md section 9: a schema violation fails the build and blocks publication.
    """
    from pipeline.schemas.canonical import validate

    counts: dict[str, int] = {}
    for table in MART_TABLES:
        frame = warehouse.fetch_df(table)
        validate(table, frame)
        counts[table] = len(frame)
    return counts


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wrapper
    parser = argparse.ArgumentParser(description="Rebuild every canonical table")
    parser.add_argument("--fixture", action="store_true",
                        help="two-state fixture (MN + IL)")
    parser.add_argument("--offline", action="store_true", help="replay only")
    parser.add_argument("--cache-root", type=Path, default=PATHS.cache)
    parser.add_argument("--database", type=Path,
                        default=PATHS.root / "data" / "warehouse" / "voltgap.duckdb")
    parser.add_argument("--computed-at", default=None,
                        help="inject a fixed run timestamp for replay determinism")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    raw = PATHS.root / "data" / "cache" / "raw"
    stations = raw / ("afdc_stations_mn.json" if args.fixture
                      else "afdc_stations_national.json")
    args.database.parent.mkdir(parents=True, exist_ok=True)
    fetcher: Fetcher = (ReplayFetcher(args.cache_root) if args.offline
                        else LiveFetcher(args.cache_root))
    states = ("MN",) if args.fixture else tuple(c for c, _, _ in ATLAS_STATES)

    with Warehouse(args.database) as warehouse:
        result = build(warehouse, fetcher, stations_path=stations, units_path=stations,
                       atlas_states=states, computed_at=args.computed_at)
        for model in result.models:
            print(f"  {model.layer:13s} {model.name:34s} {model.rows:>10,} rows")
        print(f"semantic hash: {result.semantic_hash}")
    if args.out:
        args.out.write_text(json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
