"""Unit tests for the seed provenance and integrity inventory."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pipeline.config.settings import PATHS
from pipeline.discovery.seed_inventory import (
    SEED_PROVENANCE,
    build_inventory,
    inventory_to_json,
    inventory_to_markdown,
    sha256_of,
    write_inventory,
)


def test_sha256_of_matches_hashlib(tmp_path: Path) -> None:
    path = tmp_path / "f.bin"
    path.write_bytes(b"abc" * 1000)
    assert sha256_of(path, chunk_bytes=7) == hashlib.sha256(path.read_bytes()).hexdigest()


def test_build_inventory_skips_docs_dotfiles_and_directories(tmp_path: Path) -> None:
    (tmp_path / "MANIFEST.md").write_text("doc", encoding="utf-8")
    (tmp_path / "seed_inventory.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".DS_Store").write_bytes(b"\x00")
    (tmp_path / "subdir").mkdir()
    (tmp_path / "ev_launch_data.csv").write_text("a\n1\n", encoding="utf-8")
    entries = build_inventory(tmp_path)
    assert [e.raw_filename for e in entries] == ["ev_launch_data.csv"]


def test_build_inventory_flags_an_undeclared_file(tmp_path: Path) -> None:
    """An unexpected file in data/seed/ must not pass unnoticed."""
    (tmp_path / "surprise.csv").write_text("a\n", encoding="utf-8")
    entry = build_inventory(tmp_path)[0]
    assert entry.canonical_id == "unmapped_surprise"
    assert entry.provenance.startswith("UNMAPPED")


def test_build_inventory_marks_ignored_files_as_not_version_controlled(
    tmp_path: Path,
) -> None:
    name = "Electric__Power_Transmission_Lines.geojson"
    (tmp_path / name).write_text('{"features":[]}', encoding="utf-8")
    (tmp_path / "ev_launch_data.csv").write_text("a\n", encoding="utf-8")
    by_name = {e.raw_filename: e for e in build_inventory(tmp_path)}
    assert by_name[name].version_controlled is False
    assert by_name["ev_launch_data.csv"].version_controlled is True


def test_build_inventory_is_deterministically_ordered(tmp_path: Path) -> None:
    for name in ("z.csv", "a.csv", "m.csv"):
        (tmp_path / name).write_text("x\n", encoding="utf-8")
    assert [e.raw_filename for e in build_inventory(tmp_path)] == ["a.csv", "m.csv", "z.csv"]


def test_inventory_to_json_is_deterministic_and_newline_terminated(tmp_path: Path) -> None:
    (tmp_path / "a.csv").write_text("x\n", encoding="utf-8")
    entries = build_inventory(tmp_path)
    assert inventory_to_json(entries) == inventory_to_json(entries)
    assert inventory_to_json(entries).endswith("\n")
    assert json.loads(inventory_to_json(entries))["seed_files"][0]["raw_filename"] == "a.csv"


def test_inventory_to_markdown_renders_a_table(tmp_path: Path) -> None:
    (tmp_path / "a.csv").write_text("x\n", encoding="utf-8")
    markdown = inventory_to_markdown(build_inventory(tmp_path))
    assert "| Canonical ID | Raw filename |" in markdown
    assert "`a.csv`" in markdown


def test_write_inventory_produces_both_artifacts() -> None:
    entries = write_inventory()
    assert PATHS.seed_inventory_json.exists()
    assert PATHS.seed_inventory_md.exists()
    assert len(entries) == len(SEED_PROVENANCE)


def test_raw_filenames_are_preserved_exactly_as_delivered() -> None:
    """Raw-source immutability outranks shell convenience."""
    assert "alt_fuel_stations (Dec 11 2024).csv" in SEED_PROVENANCE
    assert "IEA Global EV Data 2024.csv" in SEED_PROVENANCE
    for name, (canonical_id, _) in SEED_PROVENANCE.items():
        assert " " not in canonical_id and "(" not in canonical_id, (
            f"canonical id for {name!r} must be shell-clean even though the raw name is not"
        )
