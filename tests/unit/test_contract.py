"""Unit tests for the source contract, its validation, and drift evaluation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from pipeline.discovery.contract import (
    ContractError,
    Drift,
    Observation,
    evaluate_drift,
    load_contract,
    load_observations,
    merge_observations,
    observations_document,
    tolerance_band,
    validate_contract,
    write_observations,
)


def complete_entry(**overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": "s1",
        "name": "Source One",
        "tier": "core",
        "retrieval": {"method": "rest_api", "endpoint": "https://x", "auth": "none",
                      "rate_limit": "none"},
        "coverage": {"geographic": "US", "temporal": "current",
                     "historical_vintages_available": False, "vintage_field": None,
                     "vintage_semantics": "snapshot"},
        "schema": {"join_keys": ["id"], "stable_keys": True, "schema_version": "abc"},
        "quality": {"expected_row_count": [100, 200], "drift_tolerance": 0.2,
                    "expected_range_derivation": "first observation"},
        "license": "public domain",
        "update_cadence": "daily",
        "fallback_source": "none",
        "used_by": ["supply"],
        "backtest_eligible": False,
        "known_limitations": ["none"],
    }
    entry.update(overrides)
    return entry


def complete_finding(**overrides: Any) -> dict[str, Any]:
    finding: dict[str, Any] = {
        "id": "F-1",
        "question": "q",
        "resolved_value": "v",
        "evidence_url": "https://x",
        "retrieved_at": "2026-08-19T00:00:00Z",
        "evidence_quote": "quote",
        "evidence_artifact": "docs/evidence/x.txt",
        "evidence_sha256": "deadbeef",
    }
    finding.update(overrides)
    return finding


def document(sources: list[dict[str, Any]] | None = None,
             findings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "sources": sources if sources is not None else [complete_entry()],
        "findings": findings if findings is not None else [complete_finding()],
    }


def test_a_complete_document_validates() -> None:
    validate_contract(document())


def test_missing_top_level_fields_are_all_reported() -> None:
    entry = complete_entry()
    del entry["license"]
    del entry["used_by"]
    with pytest.raises(ContractError) as excinfo:
        validate_contract(document([entry]))
    assert "missing required field 'license'" in str(excinfo.value)
    assert "missing required field 'used_by'" in str(excinfo.value)


@pytest.mark.parametrize(
    ("group", "field"),
    [("retrieval", "auth"), ("coverage", "vintage_semantics"),
     ("schema", "stable_keys"), ("quality", "drift_tolerance")],
)
def test_missing_subfields_are_reported(group: str, field: str) -> None:
    entry = complete_entry()
    del entry[group][field]
    with pytest.raises(ContractError, match=f"{group}.{field} is absent"):
        validate_contract(document([entry]))


def test_a_non_mapping_subblock_is_skipped_rather_than_crashing() -> None:
    """A malformed block is already reported as a missing field; do not double-fault."""
    entry = complete_entry(retrieval="not-a-mapping")
    validate_contract(document([entry]))


def test_invalid_tier_is_rejected() -> None:
    with pytest.raises(ContractError, match="tier 'gold' not in"):
        validate_contract(document([complete_entry(tier="gold")]))


def test_duplicate_source_ids_are_rejected() -> None:
    with pytest.raises(ContractError, match="duplicate source id"):
        validate_contract(document([complete_entry(), complete_entry()]))


def test_expected_row_count_must_be_an_ascending_pair() -> None:
    with pytest.raises(ContractError, match="must be \\[lo, hi\\]"):
        validate_contract(document([complete_entry(
            quality={"expected_row_count": [5], "drift_tolerance": 0.2,
                     "expected_range_derivation": "x"})]))
    with pytest.raises(ContractError, match="is descending"):
        validate_contract(document([complete_entry(
            quality={"expected_row_count": [9, 1], "drift_tolerance": 0.2,
                     "expected_range_derivation": "x"})]))


def test_a_null_expected_row_count_is_allowed() -> None:
    validate_contract(document([complete_entry(
        quality={"expected_row_count": None, "drift_tolerance": 0.2,
                 "expected_range_derivation": "not established"})]))


def test_backtest_eligible_must_agree_with_historical_vintages_available() -> None:
    """Directive D1: a source cannot be backtest-eligible without historical vintages."""
    entry = complete_entry(backtest_eligible=True)
    with pytest.raises(ContractError, match="backtest_eligible is true but"):
        validate_contract(document([entry]))


def test_a_document_without_sources_is_rejected() -> None:
    with pytest.raises(ContractError, match="no 'sources' list"):
        validate_contract({"sources": [], "findings": []})


def test_a_document_without_findings_is_rejected() -> None:
    with pytest.raises(ContractError, match="no 'findings' list"):
        validate_contract(document(findings=[]))


def test_an_unevidenced_finding_is_rejected() -> None:
    """The gate verifies resolution WITH evidence, never external truth."""
    finding = complete_finding()
    del finding["evidence_sha256"]
    del finding["evidence_quote"]
    with pytest.raises(ContractError) as excinfo:
        validate_contract(document(findings=[finding]))
    assert "missing required field 'evidence_sha256'" in str(excinfo.value)
    assert "missing required field 'evidence_quote'" in str(excinfo.value)


def test_load_contract_rejects_a_non_mapping_file(tmp_path: Path) -> None:
    path = tmp_path / "s.yml"
    path.write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(ContractError, match="did not parse to a mapping"):
        load_contract(path)


def test_load_contract_reads_yaml(tmp_path: Path) -> None:
    path = tmp_path / "s.yml"
    path.write_text(yaml.safe_dump(document()), encoding="utf-8")
    assert len(load_contract(path)["sources"]) == 1


# --- drift ------------------------------------------------------------------------

def observation(**overrides: Any) -> Observation:
    values: dict[str, Any] = {
        "source_id": "s1", "status": "confirmed", "url": "https://x", "http_status": 200,
        "retrieved_at": "t", "elapsed_ms": 1.0, "content_bytes": 10,
        "content_sha256": "h", "measurement": {"row_count": 150, "schema_hash": "abc"},
        "rate_limit_headers": {}, "vintage": None, "note": "",
    }
    values.update(overrides)
    return Observation(**values)


def test_tolerance_band_widens_both_ends() -> None:
    assert tolerance_band([100, 200], 0.2) == [80, 240]
    assert tolerance_band([100, 200], 0.0) == [100, 200]


def test_drift_inside_the_band_passes() -> None:
    drift = evaluate_drift(complete_entry(), observation())
    assert drift.within_expected_row_count is True
    assert drift.tolerance_band == [80, 240]
    assert drift.schema_hash_changed is False
    assert drift.note == "within tolerance"


def test_drift_outside_the_band_is_flagged() -> None:
    drift = evaluate_drift(
        complete_entry(), observation(measurement={"row_count": 5, "schema_hash": "abc"})
    )
    assert drift.within_expected_row_count is False
    assert drift.note == "OUTSIDE tolerance band"


def test_schema_hash_change_is_reported() -> None:
    drift = evaluate_drift(
        complete_entry(), observation(measurement={"row_count": 150, "schema_hash": "zzz"})
    )
    assert drift.schema_hash_changed is True


def test_drift_is_not_evaluated_when_nothing_was_measured() -> None:
    """A binary artifact or an unavailable source yields no row count; do not guess."""
    drift = evaluate_drift(complete_entry(), observation(measurement=None))
    assert drift.within_expected_row_count is None
    assert drift.schema_hash_changed is None
    assert drift.note == "not evaluated: no row count observed"


def test_drift_handles_an_entry_with_no_quality_block() -> None:
    entry = complete_entry()
    del entry["quality"]
    drift = evaluate_drift(entry, observation())
    assert drift.within_expected_row_count is None
    assert drift.expected_row_count is None


def test_drift_to_dict_is_serialisable() -> None:
    payload = Drift("s", True, 1, [1, 2], [1, 2], False, "n").to_dict()
    assert json.loads(json.dumps(payload))["source_id"] == "s"


# --- output ------------------------------------------------------------------------

def test_observations_document_sorts_by_source_id() -> None:
    doc = observations_document(
        [observation(source_id="z"), observation(source_id="a")],
        [Drift("z", None, None, None, None, None, "n"),
         Drift("a", None, None, None, None, None, "n")],
        "probe.py",
    )
    assert [o["source_id"] for o in doc["observations"]] == ["a", "z"]
    assert [d["source_id"] for d in doc["drift"]] == ["a", "z"]
    assert doc["generated_by"] == "probe.py"


def test_write_observations_is_deterministic(tmp_path: Path) -> None:
    doc = observations_document([observation()], [], "probe.py")
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    write_observations(first, doc)
    write_observations(second, doc)
    assert first.read_bytes() == second.read_bytes()
    assert first.read_text().endswith("\n")


def test_a_non_mapping_quality_block_is_skipped_rather_than_crashing() -> None:
    entry = complete_entry(quality="not-a-mapping")
    validate_contract(document([entry]))


def test_a_partial_probe_merges_rather_than_deleting_every_other_observation() -> None:
    """`--only` writing just what it probed would silently delete the evidence that
    every other source was measured — and the result would read as a clean file."""
    existing = {
        "generated_by": "old",
        "observations": [{"source_id": "a", "status": "confirmed"},
                         {"source_id": "b", "status": "confirmed"}],
        "drift": [{"source_id": "b", "field": "row_count"}],
    }
    fresh = {
        "generated_by": "new",
        "observations": [{"source_id": "b", "status": "degraded"},
                         {"source_id": "c", "status": "confirmed"}],
        "drift": [],
    }
    merged = merge_observations(existing, fresh)
    assert [o["source_id"] for o in merged["observations"]] == ["a", "b", "c"]
    # The fresh measurement wins where both have one; the untouched source survives.
    assert {o["source_id"]: o["status"] for o in merged["observations"]} == {
        "a": "confirmed", "b": "degraded", "c": "confirmed"}
    # Drift from a source this run did not probe is preserved, not silently cleared.
    assert [d["source_id"] for d in merged["drift"]] == ["b"]
    assert merged["generated_by"] == "new"


def test_the_sidecar_round_trips_through_load_and_write(tmp_path: Path) -> None:
    path = tmp_path / "observed.json"
    document = {"generated_by": "x", "observations": [], "drift": []}
    write_observations(path, document)
    assert load_observations(path) == document
    assert path.read_text(encoding="utf-8").endswith("\n")
