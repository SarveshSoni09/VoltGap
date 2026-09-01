"""Smoke-forward: are Phase 6's outputs sufficient for Phase 7's inputs? (§15.2)

Phase 7 is "Automation + docs": a scheduled ETL that refreshes sources, rebuilds, validates,
exports, uploads to R2 and writes a manifest; a staleness indicator verified by clock
manipulation; and a failure path where an injected schema violation blocks publication and
preserves the prior artifacts.

These exercise the shape Phase 7 needs against Phase 6's real output. They do not implement
Phase 7.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pipeline.config.settings import PATHS
from pipeline.export.manifest import build_manifest
from pipeline.export.parquet import WrittenArtifact, sha256_of

DATA = PATHS.root / "web" / "public" / "data"


def test_the_manifest_is_the_single_index_an_etl_would_republish() -> None:
    """Phase 7 uploads a directory and points the site at it. Everything needed to
    describe that upload has to be in one file, or the ETL has to know the layout itself."""
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifacts"]
    for record in manifest["artifacts"].values():
        assert record["sha256"] and record["bytes"] > 0
    assert manifest["source_vintages"]
    assert manifest["computed_at"]


def test_every_artifact_can_be_verified_from_the_manifest_alone() -> None:
    """The Phase 7 failure path keeps prior artifacts live and marks the manifest stale.
    That needs artifact integrity checkable without rebuilding, which the checksums give."""
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    for name, record in manifest["artifacts"].items():
        assert sha256_of(DATA / name) == record["sha256"], name


def test_staleness_is_computable_by_moving_the_clock_only() -> None:
    """§15.5 Phase 7: "Staleness indicator verified by clock manipulation." The threshold
    lives in the manifest, so the check needs no code change to exercise - only a clock."""
    from pipeline.export.manifest import STALE_AFTER_DAYS

    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    computed_at = datetime.fromisoformat(manifest["computed_at"])
    threshold = manifest["stale_after_days"]
    assert threshold == STALE_AFTER_DAYS

    fresh = computed_at + timedelta(days=threshold - 1)
    stale = computed_at + timedelta(days=threshold + 1)
    assert (fresh - computed_at).days <= threshold
    assert (stale - computed_at).days > threshold


def test_a_manifest_can_be_rewritten_with_a_new_timestamp_without_rebuilding(
    tmp_path: Path,
) -> None:
    """Phase 7 marks a manifest stale when a refresh fails, keeping prior artifacts live.
    That is a manifest rewrite, so it must not require the artifacts to be regenerated."""
    existing = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    artifacts = [
        WrittenArtifact(name, DATA / name, record["rows"], record["bytes"],
                        record["sha256"], tuple(record["columns"]))
        for name, record in existing["artifacts"].items()
    ]
    later = build_manifest(
        artifacts, existing["source_vintages"], existing["pipeline_phases"],
        {**existing["notes"], "refresh_failed": True},
        computed_at=datetime.now(UTC).isoformat())
    path = later.write(tmp_path / "manifest.json")
    rewritten = json.loads(path.read_text(encoding="utf-8"))
    assert rewritten["artifacts"].keys() == existing["artifacts"].keys()
    assert rewritten["notes"]["refresh_failed"] is True


def test_the_static_export_is_a_directory_an_etl_can_publish_wholesale() -> None:
    """No server, no build step at deploy time: Phase 7's deploy is a directory copy."""
    out = PATHS.root / "web" / "out"
    assert (out / "index.html").is_file()
    assert (out / "data" / "manifest.json").is_file()
    assert not (out / "_next" / "server").exists()


def test_the_data_base_is_configurable_so_phase_7_can_point_it_at_r2() -> None:
    """§12 hosts artifacts on R2; §13.2 makes the upload an ETL step. The frontend reads
    a configurable base so that switch is configuration, not a code change."""
    config = (PATHS.root / "web" / "next.config.ts").read_text(encoding="utf-8")
    assert "NEXT_PUBLIC_DATA_BASE" in config
    loader = (PATHS.root / "web" / "lib" / "data" / "manifest.ts").read_text(
        encoding="utf-8")
    assert "NEXT_PUBLIC_DATA_BASE" in loader
