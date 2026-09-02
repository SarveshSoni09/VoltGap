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
    "tests/regression/test_phase4_gates.py",           # Phase 4, P4-A to P4-G
    "tests/regression/test_gate_protocol.py",          # the gate's own invariants
    "tests/integration/test_smoke_forward_phase4.py",
    "tests/regression/test_phase5_gates.py",          # Phase 5, P5-A to P5-G
    "tests/integration/test_smoke_forward_phase5.py",  # Phase 4 -> 5  # Phase 3 -> 4
)

def gate_body(gate: str) -> str:
    """One gate target's recipe, from its rule line to its own PASS banner."""
    start = MAKEFILE.index(f"\n{gate}:")
    end = MAKEFILE.index("gate: PASS ===", start)
    return MAKEFILE[start:end]


GATE_4 = gate_body("gate-4")
GATE_6 = gate_body("gate-6")
GATE_5 = gate_body("gate-5")


def prior_suite_block() -> str:
    start = MAKEFILE.index("PRIOR_GATE_SUITES :=")
    return MAKEFILE[start:MAKEFILE.index(".PHONY: prior-gate-suites", start)]


# --- G-C: the prior-phase suites are all replayed -------------------------------------

@pytest.mark.parametrize("suite", REQUIRED_PRIOR_SUITES)
def test_the_current_gate_replays_every_prior_phase_gate_suite(suite: str) -> None:
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

ALL_GATES = ["gate-0", "gate-1", "gate-2", "gate-3", "gate-4", "gate-5",
             "gate-6"]


@pytest.mark.parametrize("gate", ALL_GATES)
def test_no_gate_runs_the_full_suite_twice(gate: str) -> None:
    """A25. The suite ran once plain and once under coverage; the plain run proved
    nothing the instrumented one does not. It must not come back."""
    bare = [line for line in gate_body(gate).splitlines()
            if re.search(r"\$\(PY\) -m pytest\s*$", line)]
    assert not bare, f"{gate} runs a bare whole-repository pytest: {bare}"


@pytest.mark.parametrize("gate", ALL_GATES)
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
        ("pipeline/export/*", 100),
        ("pipeline/sources/*", 85), ("pipeline/transform/*", 85),
    ):
        assert f'--include="{module}" --fail-under={threshold}' in body, module
    assert "--fail-under=70" in body


# --- A26: G-C replays suites, it does not recurse into whole gate ceremonies ----------

def test_no_gate_recursively_invokes_another_phase_gate() -> None:
    """A26. `make gate PHASE=n` inside a gate re-runs the identical whole-repository
    suite and coverage work for every earlier phase, adding no evidence."""
    for gate in ALL_GATES:
        body = gate_body(gate)
        for other in ALL_GATES:
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


@pytest.mark.parametrize(
    "step", ["lint", "coverage", "prior-gate-suites", "determinism", "copy-lint",
             "determinism-1", "build-fixture", "phase4", "phase5"],
)
def test_the_phase_5_gate_runs_every_required_step(step: str) -> None:
    assert f"--no-print-directory {step}" in GATE_5, step


def test_the_phase_5_gate_runs_its_own_acceptance_and_smoke_forward_suites() -> None:
    assert "tests/regression/test_phase5_gates.py" in GATE_5
    assert "tests/integration/test_smoke_forward_phase5.py" in GATE_5


# --- Phase 6 additions ----------------------------------------------------------------

@pytest.mark.parametrize(
    "step", ["web-install", "artifacts", "web-build", "lint", "web-typecheck",
             "coverage", "prior-gate-suites", "determinism", "copy-lint",
             "determinism-1", "build-fixture", "phase4", "phase5", "web-test",
             "web-budget", "web-perf-greedy", "web-perf-guards", "web-perf-settle",
             "web-render-check", "web-ux-check",
             "web-perf-tti", "web-perf-fps"],
)
def test_the_phase_6_gate_runs_every_step_it_declares(step: str) -> None:
    assert f"--no-print-directory {step}" in GATE_6, step


def test_the_phase_6_gate_runs_its_own_acceptance_and_smoke_forward_suites() -> None:
    assert "tests/regression/test_phase6_gates.py" in GATE_6
    assert "tests/integration/test_smoke_forward_phase6.py" in GATE_6


def test_the_bundle_budget_is_enforced_by_the_gate_not_merely_reported() -> None:
    """§11.3: "CI fails on bundle budget violation." A reporting step that always exits
    zero would satisfy the letter and none of the intent."""
    start = MAKEFILE.index("\nweb-budget:")
    body = MAKEFILE[start:MAKEFILE.index("\n\n", start)]
    assert "bundle-budget.mjs" in body
    script = (PATHS.root / "web" / "scripts" / "bundle-budget.mjs").read_text(
        encoding="utf-8")
    assert "process.exit(1)" in script


def test_the_frontend_is_covered_by_the_copy_lint() -> None:
    """§11.5's rules apply to UI strings above all. The lint reads .ts and .tsx, and
    skips only generated build output."""
    from pipeline.quality.copy_lint import EXTENSIONS, SKIP_DIRECTORIES

    assert ".ts" in EXTENSIONS
    assert ".tsx" in EXTENSIONS
    assert "node_modules" in SKIP_DIRECTORIES
    assert "out" in SKIP_DIRECTORIES
    assert ".next" in SKIP_DIRECTORIES


def test_the_phase_6_gate_builds_generated_inputs_before_it_tests_them() -> None:
    """The Phase 6 criteria are checked against the published artifacts and the static
    export, both generated and git-ignored. If the gate tested them before building them,
    it would pass on leftovers from a previous run and fail on a clean clone."""
    body = gate_body("gate-6")
    build_at = min(body.index("directory artifacts"), body.index("directory web-build"))
    test_at = body.index("directory coverage")
    assert build_at < test_at, "artifacts and the export must be built before the tests"


def test_the_generated_artifacts_are_not_committed() -> None:
    """They are reproducible from the accepted pipeline, so committing them would make a
    stale copy indistinguishable from a fresh build."""
    ignored = (PATHS.root / ".gitignore").read_text(encoding="utf-8")
    assert "web/public/data/" in ignored
    assert "web/out" in ignored


# --- 11.3: three performance budgets, each enforced ----------------------------------

@pytest.mark.parametrize(
    ("script", "must_contain"),
    [
        ("bundle-budget.mjs", "600 * 1024"),
        ("perf-tti.mjs", "BUDGET_SECONDS = 3.0"),
        ("perf-fps.mjs", "BUDGET_FPS = 55"),
    ],
)
def test_each_performance_budget_is_the_one_the_specification_states(
    script: str, must_contain: str
) -> None:
    """11.3 fixes the numbers. A harness that measured honestly against a budget it had
    quietly relaxed would pass while meaning nothing."""
    text = (PATHS.root / "web" / "scripts" / script).read_text(encoding="utf-8")
    assert must_contain in text, f"{script} does not carry the specified budget"
    assert "process.exit(1)" in text, f"{script} does not fail on breach"


def test_the_frame_rate_benchmark_measures_frames_not_a_proxy() -> None:
    """The one substitution that would be easy and wrong: reporting bundle size, render
    success or script time instead of presented frames."""
    text = (PATHS.root / "web" / "scripts" / "perf-fps.mjs").read_text(encoding="utf-8")
    assert "requestAnimationFrame" in text
    # "Sustained" must be the worst window, not the mean: an average lets a half-second
    # stall hide behind fast frames either side of it.
    assert "worstWindow" in text
    assert "sliding window" in text or "worst 1 s window" in text
    # And it must refuse to report a number from a software rasteriser.
    assert "swiftshader" in text.lower()
    # And it must confirm the layer actually holds the national surface.
    assert "MIN_CELLS" in text


def test_the_tti_measurement_names_what_it_measures() -> None:
    """The budget says "time to interactive". Lighthouse's `interactive` audit is that
    metric; LCP, FCP and TBT are context and must not stand in for it."""
    text = (PATHS.root / "web" / "scripts" / "perf-tti.mjs").read_text(encoding="utf-8")
    assert "audits.interactive.numericValue" in text
    # The throttling profile must be pinned, or the number means something different on
    # every machine that runs it.
    assert "cpuSlowdownMultiplier: 4" in text
    assert "throttlingMethod: \"simulate\"" in text


def test_the_tti_harness_does_not_present_a_legacy_metric_as_current() -> None:
    """Lighthouse 10 removed Time to Interactive from the performance score and the report
    display. It is still computed — in 12.8.2 as `{weight: 0, group: 'hidden'}` — and that
    is what the pre-registered §11.3 criterion is measured from. The harness must say so
    rather than let a reader assume TTI is a current scored metric or a Core Web Vital."""
    text = (PATHS.root / "web" / "scripts" / "perf-tti.mjs").read_text(encoding="utf-8")
    assert "LEGACY" in text
    assert "not a Core Web Vital" in text or "NOT a Core Web Vital" in text
    assert "weight: 0" in text and "hidden" in text
    # And it must refuse to silently substitute a modern metric if TTI ever disappears.
    assert "does not emit the `interactive` audit" in text
    assert "Do NOT substitute LCP, TBT" in text


def test_the_tti_harness_reports_contemporary_metrics_as_diagnostics() -> None:
    """Kept available for modern frontend diagnostics, and explicitly not substituted."""
    text = (PATHS.root / "web" / "scripts" / "perf-tti.mjs").read_text(encoding="utf-8")
    for metric in ("cumulative-layout-shift", "speed-index", "largest-contentful-paint",
                   "total-blocking-time"):
        assert metric in text, metric
    assert "NOT substituted for the budget" in text


def test_the_harness_records_the_versions_that_produced_the_number() -> None:
    """A performance figure without the toolchain that produced it is not reproducible."""
    text = (PATHS.root / "web" / "scripts" / "perf-tti.mjs").read_text(encoding="utf-8")
    assert "lighthouseVersion" in text
    assert "hostUserAgent" in text


def test_the_ci_workflow_suite_runs_in_the_gate() -> None:
    """The workflow is the only place §11.3's "CI-enforced" is met at all, and it is a
    file no other test reads. It must be exercised by the full suite the gate runs."""
    assert (PATHS.root / "tests" / "regression" / "test_ci_workflow.py").is_file()


def test_the_tti_harness_refuses_a_page_that_did_not_load_its_data() -> None:
    """Measured: without the published artifacts the National Overview renders its error
    state, and TTI came back 0.96 s — a comfortable pass against a 3.0 s budget, measuring
    a page with no map and no data. The guard makes that impossible."""
    text = (PATHS.root / "web" / "scripts" / "perf-tti.mjs").read_text(encoding="utf-8")
    assert "MIN_CELLS" in text
    assert "did not load its data is meaningless" in text


def test_the_fps_harness_rejects_absent_webgl_not_only_named_software_renderers() -> None:
    """A GPU-less Chrome here serves NO WebGL context rather than falling back to
    SwiftShader, so a name-only check would miss exactly the case CI produces."""
    text = (PATHS.root / "web" / "scripts" / "perf-fps.mjs").read_text(encoding="utf-8")
    assert 'renderer === "none"' in text
    assert "no WebGL context is available" in text
