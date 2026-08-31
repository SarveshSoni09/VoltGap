"""Constraint precedence: exactly one authority per jurisdiction, and it is earned."""

from __future__ import annotations

import pytest

from pipeline.model.observed import ObservedCount, StateObservations, StateTotal
from pipeline.model.precedence import (
    NATIVE_SUPERSEDE_TOLERANCE,
    PRECEDENCE,
    ConstraintSource,
    PrecedenceError,
    native_source_qualifies,
    resolve,
    resolve_all,
)
from pipeline.spatial.geography import SourceGeography
from pipeline.validation.scope import ExclusionLedger


def native(total: int, tracts: int = 3, state: str = "WA", prefix: str = "53",
           balanced: bool = True) -> StateObservations:
    counts = tuple(
        ObservedCount(state, SourceGeography.TRACT, f"{prefix}033{i:06d}",
                      total // tracts, 0)
        for i in range(tracts)
    )
    actual = sum(c.bev_count for c in counts)
    ledger = (ExclusionLedger(actual, actual, {}, {}) if balanced
              else ExclusionLedger(actual + 5, actual, {}, {}))
    return StateObservations(state, SourceGeography.TRACT, "current snapshot",
                             counts, ledger)


def county(total: int, state: str = "MT") -> StateObservations:
    counts = (ObservedCount(state, SourceGeography.COUNTY, "30049", total, 0),)
    return StateObservations(state, SourceGeography.COUNTY, "DMV Snapshot (1/1/2026)",
                             counts, ExclusionLedger(total, total, {}, {}))


def external(total: int, fips: str = "53", name: str = "Washington") -> StateTotal:
    return StateTotal(fips, name, "2025", total, 0)


# --- the declared order --------------------------------------------------------------

def test_precedence_runs_finest_first() -> None:
    assert PRECEDENCE == (
        ConstraintSource.NATIVE_TRACT_REGISTRY,
        ConstraintSource.COUNTY_OBSERVATION,
        ConstraintSource.STATE_REGISTRATION_TOTAL,
    )


# --- superseding is earned ------------------------------------------------------------

def test_a_balanced_native_tract_registry_close_to_the_external_total_qualifies() -> None:
    ok, reason = native_source_qualifies(native(300), "53", external(303))
    assert ok
    assert "supersedes the coarser external total" in reason


def test_a_source_that_is_not_tract_grain_cannot_supersede_a_state_total() -> None:
    ok, reason = native_source_qualifies(county(300, "MT"), "30", external(300, "30"))
    assert not ok
    assert "not\nnatively at tract grain" in reason or "not" in reason


def test_an_unbalanced_ledger_disqualifies_the_source() -> None:
    ok, reason = native_source_qualifies(native(300, balanced=False), "53", external(303))
    assert not ok
    assert "does not balance" in reason


def test_a_source_reaching_outside_the_jurisdiction_disqualifies() -> None:
    ok, reason = native_source_qualifies(native(300, prefix="41"), "53", external(303))
    assert not ok
    assert "outside the jurisdiction" in reason


def test_a_native_total_far_from_the_external_total_does_not_qualify() -> None:
    """A partial extract must not silently become a jurisdiction's constraint."""
    ok, reason = native_source_qualifies(native(300), "53", external(1000))
    assert not ok
    assert "beyond the 10% tolerance" in reason
    assert NATIVE_SUPERSEDE_TOLERANCE == 0.10


def test_without_an_external_total_completeness_cannot_be_demonstrated() -> None:
    ok, reason = native_source_qualifies(native(300), "53", None)
    assert not ok
    assert "cannot be demonstrated" in reason


def test_a_non_positive_external_total_cannot_corroborate() -> None:
    ok, reason = native_source_qualifies(native(300), "53", external(0))
    assert not ok
    assert "not positive" in reason


# --- resolution ------------------------------------------------------------------------

def test_a_qualifying_native_source_supersedes_and_records_what_it_displaced() -> None:
    op = resolve("53", native(300), external(303), None)
    assert op.chosen.source is ConstraintSource.NATIVE_TRACT_REGISTRY
    assert op.total == 300.0
    superseded = [c.source for c in op.superseded]
    assert ConstraintSource.STATE_REGISTRATION_TOTAL in superseded
    # Superseded totals are provenance, never summed.
    assert sum(c.total for c in op.superseded) == 303.0
    published = op.to_dict()["superseded_constraints"]
    assert isinstance(published, list)
    assert published[0]["total"] == 303.0


def test_a_disqualified_native_source_falls_back_to_the_external_total() -> None:
    op = resolve("53", native(300), external(1000), None)
    assert op.chosen.source is ConstraintSource.STATE_REGISTRATION_TOTAL
    assert op.total == 1000.0
    assert op.superseded == ()


def test_complete_county_coverage_supersedes_the_state_total() -> None:
    op = resolve("47", county(53029, "TN"), external(55400, "47", "Tennessee"),
                 {"47001": 53029.0}, county_coverage_complete=True)
    assert op.chosen.source is ConstraintSource.COUNTY_OBSERVATION
    assert op.total == 53029.0
    assert [c.source for c in op.superseded] == [
        ConstraintSource.STATE_REGISTRATION_TOTAL]


def test_partial_county_coverage_leaves_the_state_total_operative() -> None:
    """The counties decompose the state total rather than replacing it (impact I-15)."""
    op = resolve("30", county(6773, "MT"), external(6900, "30", "Montana"),
                 {"30049": 6773.0}, county_coverage_complete=False)
    assert op.chosen.source is ConstraintSource.STATE_REGISTRATION_TOTAL
    assert op.total == 6900.0
    assert "partition the state total rather than superseding" in op.reason


def test_a_native_source_also_records_a_superseded_county_candidate() -> None:
    op = resolve("53", native(300), external(303), {"53033": 250.0})
    assert op.chosen.source is ConstraintSource.NATIVE_TRACT_REGISTRY
    assert {c.source for c in op.superseded} == {
        ConstraintSource.STATE_REGISTRATION_TOTAL,
        ConstraintSource.COUNTY_OBSERVATION,
    }


def test_a_jurisdiction_with_no_candidate_at_all_is_refused() -> None:
    with pytest.raises(PrecedenceError, match="no candidate constraint"):
        resolve("99", None, None, None)


def test_resolve_all_gives_every_jurisdiction_exactly_one_authority() -> None:
    resolved = resolve_all(
        {"WA": native(300), "TN": county(53029, "TN")},
        {"53": external(303), "47": external(55400, "47", "Tennessee"),
         "06": external(1000, "06", "California")},
        {"TN": {"47001": 53029.0}},
        complete_coverage=("TN",),
    )
    assert set(resolved) == {"53", "47", "06"}
    assert resolved["53"].chosen.source is ConstraintSource.NATIVE_TRACT_REGISTRY
    assert resolved["47"].chosen.source is ConstraintSource.COUNTY_OBSERVATION
    assert resolved["06"].chosen.source is ConstraintSource.STATE_REGISTRATION_TOTAL
    for op in resolved.values():
        assert isinstance(op.chosen.source, ConstraintSource)


def test_complete_county_coverage_without_any_external_total_still_resolves() -> None:
    """A jurisdiction the external series omits is still constrained by its counties."""
    op = resolve("47", county(53029, "TN"), None, {"47001": 53029.0},
                 county_coverage_complete=True)
    assert op.chosen.source is ConstraintSource.COUNTY_OBSERVATION
    assert op.total == 53029.0
    assert op.superseded == ()


def test_complete_county_coverage_without_observations_names_an_unknown_vintage() -> None:
    op = resolve("47", None, None, {"47001": 40.0}, county_coverage_complete=True)
    assert op.chosen.vintage == "unknown"
