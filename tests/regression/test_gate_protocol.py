"""The gate itself, checked the way any other result-producing thing is checked.

The Phase 4 gate was optimised on 2026-08-31 (CLAUDE.md amendments A25 and A26): the
duplicate full-suite execution was merged into the coverage-instrumented run, and G-C
stopped recursively invoking each earlier phase's complete gate ceremony. Both changes
are mechanical, and both would be easy to turn into a real loss of validation by
deleting a suite from a list nobody checks. So the list is checked.

Nothing here asserts a runtime. These assert that what the gate *runs* is complete.
"""

from __future__ import annotations

import re

import pytest

from pipeline.config.settings import PATHS

MAKEFILE = (PATHS.root / "Makefile").read_text(encoding="utf-8")

#: Every prior-phase gate suite the Phase 4 gate must replay for G-C. Adding a phase
#: means adding its suite here as well as to the Makefile, deliberately.
REQUIRED_PRIOR_SUITES = (
    "tests/regression/test_source_findings.py",       # Phase 0
    "tests/regression/test_domain_rules.py",          # Phase 1, G1-G14
    "tests/regression/test_phase2_gates.py",          # Phase 2, P2-A to P2-H
    "tests/regression/test_phase3_gates.py",          # Phase 3, P3-A to P3-H
    "tests/regression/test_phase3_corrections.py",    # Phase 3 corrections
    "tests/integration/test_smoke_forward.py",        # Phase 0 -> 1
    "tests/integration/test_smoke_forward_phase2.py",  # Phase 1 -> 2
    "tests/integration/test_smoke_forward_phase3.py",  # Phase 2 -> 3
)

def gate_body(gate: str) -> str:
    """One gate target's recipe, from its rule line to its own PASS banner."""
    start = MAKEFILE.index(f"\n{gate}:")
    end = MAKEFILE.index("gate: PASS ===", start)
    return MAKEFILE[start:end]


GATE_4 = gate_body("gate-4")


def prior_suite_block() -> str:
    start = MAKEFILE.index("PRIOR_GATE_SUITES :=")
    return MAKEFILE[start:MAKEFILE.index(".PHONY: prior-gate-suites", start)]


# --- G-C: the prior-phase suites are all replayed -------------------------------------

@pytest.mark.parametrize("suite", REQUIRED_PRIOR_SUITES)
def test_the_phase_4_gate_replays_every_prior_phase_gate_suite(suite: str) -> None:
    """G-C. Dropping one from the Makefile would silently stop replaying a phase."""
    assert suite in prior_suite_block(), suite


def test_every_replayed_suite_actually_exists() -> None:
    """A path typo would be reported as a pytest error, but only if someone looked."""
    for suite in REQUIRED_PRIOR_SUITES:
        assert (PATHS.root / suite).is_file(), suite


def test_the_makefile_list_carries_nothing_the_test_does_not_know_about() -> None:
    """Both directions. An added suite must be recorded here too, so this list stays
    the authoritative statement of what G-C covers."""
    listed = set(re.findall(r"tests/\S+\.py", prior_suite_block()))
    assert listed == set(REQUIRED_PRIOR_SUITES)


def test_the_gate_runs_the_prior_suites_and_reports_them_individually() -> None:
    assert "prior-gate-suites" in GATE_4
    assert "PASS" in prior_suite_target()
    assert "FAIL" in prior_suite_target()


def prior_suite_target() -> str:
    start = MAKEFILE.index("prior-gate-suites:")
    return MAKEFILE[start:MAKEFILE.index("\ngate:", start)]


def test_a_failing_prior_suite_fails_the_gate_rather_than_being_reported_and_ignored(
) -> None:
    """The loop keeps going after a failure so every suite is reported, which makes it
    easy to forget the exit. Without it the gate would print FAIL and pass."""
    target = prior_suite_target()
    assert "failed=1" in target
    assert "exit 1" in target


# --- A25: one coverage-instrumented run satisfies both requirements -------------------

@pytest.mark.parametrize("gate", ["gate-0", "gate-1", "gate-2", "gate-3", "gate-4"])
def test_no_gate_runs_the_full_suite_twice(gate: str) -> None:
    """A25. The suite ran once plain and once under coverage; the plain run proved
    nothing the instrumented one does not. It must not come back."""
    bare = [line for line in gate_body(gate).splitlines()
            if re.search(r"\$\(PY\) -m pytest\s*$", line)]
    assert not bare, f"{gate} runs a bare whole-repository pytest: {bare}"


@pytest.mark.parametrize("gate", ["gate-0", "gate-1", "gate-2", "gate-3", "gate-4"])
def test_every_gate_still_runs_the_full_suite_under_coverage(gate: str) -> None:
    """The other half of A25: merging the two must not have dropped either."""
    assert "--no-print-directory coverage" in gate_body(gate), gate


def test_the_coverage_target_runs_the_whole_suite_with_no_deselection() -> None:
    """If coverage ran a subset, merging the two runs WOULD lose validation."""
    start = MAKEFILE.index("\ncoverage:")
    body = MAKEFILE[start:MAKEFILE.index("\nlint:", start)]
    invocation = next(line for line in body.splitlines()
                      if "-m pytest" in line and "--cov=pipeline" in line)
    assert "--cov-branch" in invocation
    # No path argument and no -k/-m deselection: this is the whole suite.
    assert "tests/" not in invocation
    assert " -k " not in invocation


def test_every_coverage_threshold_is_still_enforced() -> None:
    """A25 promised no threshold was removed. These are the tiers CLAUDE.md §15.1 G-B
    requires: 100% on result-computing code, 85% on sources/transform, 70% overall."""
    start = MAKEFILE.index("\ncoverage:")
    body = MAKEFILE[start:MAKEFILE.index("\nlint:", start)]
    for module, threshold in (
        ("pipeline/discovery/*", 100), ("pipeline/spatial/*", 100),
        ("pipeline/validation/*", 100), ("pipeline/model/*", 100),
        ("pipeline/quality/*", 100), ("pipeline/schemas/*", 100),
        ("pipeline/sources/*", 85), ("pipeline/transform/*", 85),
    ):
        assert f'--include="{module}" --fail-under={threshold}' in body, module
    assert "--fail-under=70" in body


# --- A26: G-C replays suites, it does not recurse into whole gate ceremonies ----------

def test_no_gate_recursively_invokes_another_phase_gate() -> None:
    """A26. `make gate PHASE=n` inside a gate re-runs the identical whole-repository
    suite and coverage work for every earlier phase, adding no evidence."""
    for gate in ("gate-0", "gate-1", "gate-2", "gate-3", "gate-4"):
        body = gate_body(gate)
        for other in ("gate-0", "gate-1", "gate-2", "gate-3", "gate-4"):
            assert f"--no-print-directory {other}" not in body, (gate, other)


# --- nothing else was quietly dropped -------------------------------------------------

@pytest.mark.parametrize(
    "step", ["lint", "coverage", "prior-gate-suites", "determinism", "copy-lint",
             "determinism-1", "build-fixture", "phase4"],
)
def test_the_phase_4_gate_still_runs_every_step_it_ran_before(step: str) -> None:
    assert f"--no-print-directory {step}" in GATE_4, step


def test_the_phase_4_gate_still_runs_its_own_acceptance_and_smoke_forward_suites(
) -> None:
    assert "tests/regression/test_phase4_gates.py" in GATE_4
    assert "tests/integration/test_smoke_forward_phase4.py" in GATE_4
