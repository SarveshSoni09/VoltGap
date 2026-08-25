"""Determinism, as CLAUDE.md section 14.1 (amendment A14) defines it.

    Same pinned source snapshots + same code + same configuration
      => same semantic data output.

Two properties are tested, and they are NOT the same thing:

* **Replay reproducibility.** Required. Two runs against pinned inputs with an
  injected fixed timestamp must produce an identical semantic hash. A failure here is
  a real defect.
* **Live-source refresh behaviour.** Different artifacts from a live refresh are
  expected and legitimate, because upstream data change. Treating that as a
  determinism failure would push the pipeline toward suppressing real upstream change,
  which is the opposite of what section 13.2 requires.

Naive byte equality is impossible: every derived table carries ``computed_at``.
Volatile columns are therefore normalised out before hashing.
"""

from __future__ import annotations

import pytest

from pipeline.build import MART_TABLES, build
from pipeline.config.settings import PATHS
from pipeline.discovery.cache import ReplayFetcher
from pipeline.transform.runner import VOLATILE_COLUMNS, Warehouse

FIXED_TIMESTAMP = "2026-01-01T00:00:00+00:00"
RAW = PATHS.root / "data" / "cache" / "raw"


def run_build(computed_at: str) -> tuple[str, dict[str, int]]:
    with Warehouse() as warehouse:
        result = build(
            warehouse,
            ReplayFetcher(PATHS.cache),
            stations_path=RAW / "afdc_stations_mn.json",
            units_path=RAW / "afdc_stations_mn.json",
            atlas_states=(),
            computed_at=computed_at,
        )
        counts = {m.name: m.rows for m in result.models}
        return result.semantic_hash, counts


def test_replay_reproducibility_is_byte_identical_on_the_semantic_hash() -> None:
    """The required property. Same pinned inputs, same code, same config."""
    first_hash, first_counts = run_build(FIXED_TIMESTAMP)
    second_hash, second_counts = run_build(FIXED_TIMESTAMP)
    assert first_hash == second_hash
    assert first_counts == second_counts
    assert len(first_hash) == 64


def test_the_semantic_hash_ignores_the_run_timestamp() -> None:
    """A different `computed_at` alone is not a semantic change."""
    first_hash, _ = run_build(FIXED_TIMESTAMP)
    later_hash, _ = run_build("2030-06-15T12:34:56+00:00")
    assert first_hash == later_hash, (
        "computed_at is volatile metadata and must not affect the semantic hash"
    )


def test_naive_byte_equality_would_fail_which_is_why_it_is_not_the_gate() -> None:
    """Demonstrates the problem A14 exists to solve, rather than asserting it abstractly."""
    with Warehouse() as warehouse:
        build(warehouse, ReplayFetcher(PATHS.cache),
              stations_path=RAW / "afdc_stations_mn.json",
              units_path=RAW / "afdc_stations_mn.json",
              atlas_states=(), computed_at=FIXED_TIMESTAMP)
        early = warehouse.fetch_df("mart_sites")["computed_at"].iloc[0]
    with Warehouse() as warehouse:
        build(warehouse, ReplayFetcher(PATHS.cache),
              stations_path=RAW / "afdc_stations_mn.json",
              units_path=RAW / "afdc_stations_mn.json",
              atlas_states=(), computed_at="2031-01-01T00:00:00+00:00")
        late = warehouse.fetch_df("mart_sites")["computed_at"].iloc[0]
    assert early != late, "computed_at genuinely differs between runs"


def test_volatile_columns_are_declared_and_minimal() -> None:
    """The exclusion list must stay small, or a real change could hide inside it."""
    assert {
        "computed_at", "retrieved_at", "last_successful_retrieval", "elapsed_ms",
    } == VOLATILE_COLUMNS
    for column in VOLATILE_COLUMNS:
        assert "vintage" not in column, (
            "source_vintages is a genuine semantic change and must stay in scope"
        )


def test_source_vintages_is_in_scope_for_the_hash() -> None:
    """A change of source vintage IS a semantic change and must move the hash."""
    with Warehouse() as warehouse:
        build(warehouse, ReplayFetcher(PATHS.cache),
              stations_path=RAW / "afdc_stations_mn.json",
              units_path=RAW / "afdc_stations_mn.json",
              atlas_states=(), computed_at=FIXED_TIMESTAMP)
        baseline = warehouse.semantic_hash(MART_TABLES)
        warehouse.connection.execute(
            "UPDATE mart_sites SET source_vintages = 'tampered'"
        )
        assert warehouse.semantic_hash(MART_TABLES) != baseline


def test_row_order_alone_is_not_a_semantic_change() -> None:
    with Warehouse() as warehouse:
        build(warehouse, ReplayFetcher(PATHS.cache),
              stations_path=RAW / "afdc_stations_mn.json",
              units_path=RAW / "afdc_stations_mn.json",
              atlas_states=(), computed_at=FIXED_TIMESTAMP)
        baseline = warehouse.semantic_hash(("mart_sites",))
        warehouse.connection.execute(
            "CREATE OR REPLACE TABLE mart_sites AS "
            "SELECT * FROM mart_sites ORDER BY random()"
        )
        assert warehouse.semantic_hash(("mart_sites",)) == baseline


def test_a_genuine_data_change_does_move_the_hash() -> None:
    """The guard that makes the previous tests meaningful."""
    with Warehouse() as warehouse:
        build(warehouse, ReplayFetcher(PATHS.cache),
              stations_path=RAW / "afdc_stations_mn.json",
              units_path=RAW / "afdc_stations_mn.json",
              atlas_states=(), computed_at=FIXED_TIMESTAMP)
        baseline = warehouse.semantic_hash(("mart_sites",))
        warehouse.connection.execute(
            "UPDATE mart_sites SET station_count = station_count + 1"
        )
        assert warehouse.semantic_hash(("mart_sites",)) != baseline


@pytest.mark.live
def test_live_refresh_is_not_expected_to_be_byte_identical() -> None:
    """Documented as a marked test rather than asserted: it needs the network.

    A live refresh producing different artifacts is NOT a determinism failure. It is
    verified by schema conformance, drift bounds and quality gates instead. This test
    is excluded from the deterministic gate by the `live` marker.
    """
    pytest.skip("live-source behaviour is verified by schema and drift checks, not "
                "by byte equality (CLAUDE.md 14.1)")
