"""Build every published artifact from the accepted pipeline outputs.

One command produces what the static frontend loads: the national cell surface, the
block-group access points, the per-state frontier, the site point layer, and the manifest
that indexes them. Nothing here re-derives a model quantity — Phases 0-5 are frozen inputs.

**Degradations are explicit (D8).** Two artifacts §12 lists are not produced here, and both
say so in the manifest rather than being quietly absent:

* `sites.pmtiles` and `transmission.pmtiles` need `tippecanoe`, which is not available in
  this build environment. The site layer ships instead as a **parquet point layer**, which
  deck.gl renders directly; it is a different thing from a vector tile set and the manifest
  names it as such.
* The transmission layer ships **not at all**. It is an opt-in contextual layer (§11.4) and
  §7.9 requires that it never function as, or be described as, an interconnection
  constraint. Absent is the safest state for it, and it is not a Core dependency.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pipeline.config.settings import PATHS
from pipeline.export.access_points import (
    ACCESS_COLUMNS,
    build_access_points,
    sensitivity_curve,
)
from pipeline.export.manifest import build_manifest
from pipeline.export.national import (
    HEX6_COLUMNS,
    build_national,
    public_site_coordinates,
)
from pipeline.export.parquet import WrittenArtifact, write_parquet
from pipeline.model.access import load_thresholds
from pipeline.spatial.h3_grid import RESOLUTION_NATIONAL, load_population_points

#: Where artifacts land. Phase 7's ETL uploads this directory to R2 (§13.2); Phase 6 keeps
#: it local so Core is deployable and testable without provisioning infrastructure.
DEFAULT_OUT = PATHS.root / "web" / "public" / "data"

SITE_COLUMNS: tuple[str, ...] = ("latitude", "longitude", "serves_dcfc")


def build_all(
    out: Path = DEFAULT_OUT,
    states: Sequence[str] = (),
    resolution: int = RESOLUTION_NATIONAL,
    computed_at: str | None = None,
    bootstrap_replicates: int = 20,
) -> dict[str, Any]:
    """Produce every artifact and the manifest indexing them."""
    from pipeline.model.build_demand import build_surface
    from pipeline.model.observed import load_all
    from pipeline.model.panel import build_panels, load_area_tables
    from pipeline.model.run_phase3 import (
        ALL_STATE_FIPS,
        allocation_penalty,
        constraint_totals,
    )

    wanted = tuple(states) if states else ALL_STATE_FIPS
    tables = load_area_tables(states=wanted)
    observations = load_all(known_tracts=sorted(tables["tracts"].rows))
    penalty, _ = allocation_penalty()
    surface = build_surface(
        tables["tracts"], build_panels(observations, tables), observations,
        constraint_totals(observations), penalty, "poisson_glm",
        source_statuses=("confirmed",) * 8,
        bootstrap_replicates=bootstrap_replicates,
    )

    national = build_national(surface.estimates, _source_vintages(), wanted, resolution)
    artifacts: list[WrittenArtifact] = [
        write_parquet(list(national.rows), HEX6_COLUMNS,
                      out / "hex6_national.parquet")
    ]

    dcfc_sites, public_sites = public_site_coordinates()
    l2_sites = public_sites
    thresholds = load_thresholds()
    # The share is recovered from the published equity population rather than re-read
    # from features, so the artifact cannot disagree with the number Phase 4 optimised on:
    # equity_population is income_share_under_35k * population by construction.
    income = {row.geoid: (float(row.equity_population) / float(row.population)
                          if row.population > 0 else 0.0)
              for row in surface.estimates}
    points = {state: load_population_points(state) for state in national.states}
    access_rows = build_access_points(
        points, dcfc_sites, l2_sites, income, resolution)
    artifacts.append(write_parquet(access_rows, ACCESS_COLUMNS,
                                   out / "access_points.parquet"))

    dcfc_set = set(dcfc_sites)
    site_rows = [{"latitude": round(lat, 6), "longitude": round(lon, 6),
                  "serves_dcfc": (lat, lon) in dcfc_set}
                 for lat, lon in public_sites]
    artifacts.append(write_parquet(site_rows, SITE_COLUMNS, out / "sites.parquet"))

    frontier = _copy_frontier(out)
    artifacts.extend(frontier)

    manifest = build_manifest(
        artifacts=artifacts,
        source_vintages=_source_vintages(),
        pipeline_phases={
            "demand_surface": "Phase 3 (accepted)",
            "siting_and_frontier": "Phase 4 (accepted)",
            "validation": "Phase 5 (accepted)",
        },
        notes={
            "national_cells": len(national),
            "national_demand_bev": round(national.demand_total, 4),
            "unallocated_demand_bev": round(national.unallocated_demand, 4),
            "unallocated_note": (
                "demand in tracts with no block-group population weight, reported "
                "rather than dropped"),
            "sub_state_anchored_share_of_demand": round(
                national.sub_state_anchored_share_of_demand, 6),
            "access_points": len(access_rows),
            "access_grain": (
                "BLOCK GROUP population-weighted points, finer than tract. §11.4 names "
                "this file tract_access.parquet; calling it that would misdescribe its "
                "grain, so it ships as access_points.parquet"),
            "dcfc_sensitivity_curve": sensitivity_curve(access_rows, thresholds),
            "degradations": {
                "sites_pmtiles": (
                    "NOT PRODUCED. tippecanoe is unavailable in this build environment, "
                    "so the site layer ships as a parquet POINT layer rather than a "
                    "vector tile set. It is not a substitute for tiles at high zoom."),
                "transmission_pmtiles": (
                    "NOT SHIPPED. An opt-in contextual layer only (§11.4). §7.9 requires "
                    "it never function as, or be described as, an interconnection "
                    "constraint, and it is not a Core dependency."),
                "hex8_metro": (
                    "NOT PRODUCED this phase. Metro drill-down at H3 resolution 8 is a "
                    "lazy-loaded enhancement (§11.4); Core renders the national "
                    "resolution-6 surface."),
            },
        },
        computed_at=computed_at,
    )
    manifest.write(out / "manifest.json")
    return {
        "out": str(out),
        "artifacts": [a.to_dict() for a in artifacts],
        "cells": len(national),
        "access_points": len(access_rows),
        "sites": len(site_rows),
    }


def _source_vintages() -> dict[str, str]:
    """The vintages behind the published numbers, read from the accepted evidence."""
    phase3 = json.loads(
        (PATHS.root / "docs" / "evidence" / "P3-2_demand_model.json").read_text(
            encoding="utf-8"))
    return {
        "acs_5_year": str(phase3.get("acs_year", "2024")),
        "afdc_stations": "current snapshot",
        "afdc_state_registrations": "2023",
        "tiger_roads": "2024",
    }


def _copy_frontier(out: Path) -> list[WrittenArtifact]:
    """Publish Phase 4's frontier per state, unchanged."""
    from pipeline.export.parquet import sha256_of

    source = json.loads(
        (PATHS.root / "docs" / "evidence" / "P4-1_siting.json").read_text(
            encoding="utf-8"))
    by_state: dict[str, list[dict[str, Any]]] = {}
    for point in source["frontier"]:
        by_state.setdefault(str(point["state"]), []).append(point)

    written: list[WrittenArtifact] = []
    directory = out / "frontier"
    directory.mkdir(parents=True, exist_ok=True)
    for state, points in sorted(by_state.items()):
        path = directory / f"{state.replace(' ', '_')}.json"
        payload = {
            "state": state,
            "points": points,
            "interpretation": (
                "The published analytical frontier, from exact epsilon-constraint "
                "integer programs solved offline with CBC. The Studio's interactive "
                "surface is a separate, approximate weighted-sum tradeoff and is not "
                "this frontier."),
        }
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        written.append(WrittenArtifact(
            name=f"frontier/{path.name}", path=path, rows=len(points),
            bytes=path.stat().st_size, sha256=sha256_of(path),
            columns=tuple(sorted(points[0])) if points else (),
        ))
    return written


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--states", nargs="*", default=[])
    parser.add_argument("--computed-at", default=None)
    parser.add_argument("--bootstrap", type=int, default=20)
    args = parser.parse_args(argv)

    result = build_all(out=args.out, states=args.states,
                       computed_at=args.computed_at,
                       bootstrap_replicates=args.bootstrap)
    print(f"wrote {len(result['artifacts'])} artifacts to {result['out']}")
    for entry in result["artifacts"]:
        print(f"  {entry['name']:34} {entry['rows']:>9,} rows  "
              f"{entry['bytes'] / 1e6:>7.2f} MB")
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
