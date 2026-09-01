"""The export driver, end to end on a real state.

Vermont: the smallest frontier state, so this exercises the whole path - Phase 3 surface,
national assembly, road filter, access points, sites, frontier, manifest - in seconds
rather than minutes. The path is the same one the national build runs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import pytest

from pipeline.export.national import HEX6_COLUMNS
from pipeline.export.run import build_all

VERMONT = "50"


@pytest.fixture(scope="module")
def exported(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    out = tmp_path_factory.mktemp("artifacts")
    return build_all(out=out, states=(VERMONT,),
                     computed_at="2026-09-01T00:00:00+00:00", bootstrap_replicates=2)


def out_dir(exported: dict[str, Any]) -> Path:
    return Path(str(exported["out"]))


def artifact_names(exported: dict[str, Any]) -> set[str]:
    records: list[dict[str, Any]] = exported["artifacts"]
    return {str(record["name"]) for record in records}


def test_every_expected_artifact_is_written(exported: dict[str, Any]) -> None:
    names = artifact_names(exported)
    assert "hex6_national.parquet" in names
    assert "access_points.parquet" in names
    assert "sites.parquet" in names
    assert any(n.startswith("frontier/") for n in names)


def test_the_cell_artifact_has_exactly_the_published_schema(
    exported: dict[str, Any],
) -> None:
    path = out_dir(exported) / "hex6_national.parquet"
    names = [d[0] for d in duckdb.sql(f"SELECT * FROM '{path}' LIMIT 0").description]
    assert tuple(names) == HEX6_COLUMNS


def test_every_cell_carries_a_tier_and_an_evidence_grain(
    exported: dict[str, Any],
) -> None:
    """§17 and §11.1: no modeled value ships without its confidence."""
    path = out_dir(exported) / "hex6_national.parquet"
    bad = duckdb.sql(
        f"SELECT count(*) FROM '{path}' WHERE confidence_tier NOT IN ('A','B','C') "
        f"OR dominant_evidence_grain IS NULL OR uncertainty_score IS NULL"
    ).fetchone()
    assert bad is not None and bad[0] == 0


def test_the_road_filter_verdict_ships_so_the_browser_can_apply_it(
    exported: dict[str, Any],
) -> None:
    path = out_dir(exported) / "hex6_national.parquet"
    row = duckdb.sql(
        f"SELECT count(*) n, sum(passes_road_filter::int) p FROM '{path}'"
    ).fetchone()
    assert row is not None
    assert row[0] > 0
    assert 0 < row[1] <= row[0]


def test_the_manifest_describes_what_was_written(exported: dict[str, Any]) -> None:
    manifest = json.loads((out_dir(exported) / "manifest.json").read_text())
    assert manifest["computed_at"] == "2026-09-01T00:00:00+00:00"
    assert manifest["artifacts"]["hex6_national.parquet"]["rows"] > 0
    assert manifest["source_vintages"]["acs_5_year"]
    assert manifest["notes"]["national_cells"] > 0


def test_the_manifest_names_what_was_not_produced(exported: dict[str, Any]) -> None:
    """D8: degrade explicitly. tippecanoe is unavailable, so the vector tile sets are
    absent - and the manifest says so rather than the frontend finding a missing file."""
    manifest = json.loads((out_dir(exported) / "manifest.json").read_text())
    degradations = manifest["notes"]["degradations"]
    assert "NOT PRODUCED" in degradations["sites_pmtiles"]
    assert "tippecanoe" in degradations["sites_pmtiles"]
    assert "NOT SHIPPED" in degradations["transmission_pmtiles"]


def test_unallocated_demand_is_reported_rather_than_dropped(
    exported: dict[str, Any],
) -> None:
    manifest = json.loads((out_dir(exported) / "manifest.json").read_text())
    assert "unallocated_demand_bev" in manifest["notes"]
    assert manifest["notes"]["unallocated_note"]


def test_the_access_grain_is_named_honestly(exported: dict[str, Any]) -> None:
    """§11.4 calls the file tract_access.parquet; it is block-group grain, and calling it
    tract would misdescribe it."""
    manifest = json.loads((out_dir(exported) / "manifest.json").read_text())
    assert "BLOCK GROUP" in manifest["notes"]["access_grain"]


def test_the_frontier_is_published_with_its_interpretation(
    exported: dict[str, Any],
) -> None:
    files = sorted((out_dir(exported) / "frontier").glob("*.json"))
    assert files
    payload = json.loads(files[0].read_text())
    assert payload["points"]
    assert "approximate" in payload["interpretation"]
    assert "epsilon-constraint" in payload["interpretation"]


def test_the_command_line_entry_point_writes_and_reports(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`make artifacts` runs this. It must write the files and say what it wrote, so a
    refresh that silently produced nothing is visible in the log."""
    from pipeline.export.run import main

    code = main(["--out", str(tmp_path), "--states", VERMONT,
                 "--computed-at", "2026-09-01T00:00:00+00:00", "--bootstrap", "2"])
    assert code == 0
    printed = capsys.readouterr().out
    assert "hex6_national.parquet" in printed
    assert "access_points.parquet" in printed
    assert (tmp_path / "manifest.json").exists()
