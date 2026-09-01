"""PR CI's protection of the ENVIRONMENT-DEPENDENT performance budgets.

CLAUDE.md §11.3, amendment A27, divides the budgets into two enforcement classes. The
portable ones are PR CI hard gates. The environment-dependent ones — time to interactive and
sustained frame rate — are hard gates in the authoritative gate on a documented reference
environment, because direct measurement showed their accepted semantics do not survive a
GitHub-hosted runner.

PR CI does **not** measure those two. This module is what it runs instead: the seven
assertions §11.3 requires, so that the budgets cannot be quietly weakened, redefined, or
replaced by a proxy in a pull request that never runs them.

None of these is a performance measurement. They are integrity checks on the harnesses.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from pipeline.config.settings import PATHS

WEB = PATHS.root / "web"
SCRIPTS = WEB / "scripts"
TTI = SCRIPTS / "perf-tti.mjs"
FPS = SCRIPTS / "perf-fps.mjs"
RENDER = SCRIPTS / "render-check.mjs"
PROVENANCE = PATHS.root / "docs" / "evidence" / "P6-1_performance.json"

TTI_SOURCE = TTI.read_text(encoding="utf-8")
FPS_SOURCE = FPS.read_text(encoding="utf-8")
RENDER_SOURCE = RENDER.read_text(encoding="utf-8")


# --- 1. the harnesses are present and executable --------------------------------------

@pytest.mark.parametrize("script", [TTI, FPS, RENDER])
def test_the_harness_is_present(script: Path) -> None:
    assert script.is_file(), script.name
    assert script.stat().st_size > 2000


@pytest.mark.parametrize("script", [TTI, FPS, RENDER])
def test_the_harness_parses_and_is_executable_by_node(script: Path) -> None:
    """Syntax-checked without running it: a harness that cannot start would otherwise be
    discovered only on the reference environment, long after the PR merged."""
    result = subprocess.run(
        ["node", "--check", str(script)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


# --- 2. the authoritative thresholds are neither duplicated nor changed ---------------

def test_the_thresholds_are_the_pre_registered_ones() -> None:
    assert "const BUDGET_SECONDS = 3.0;" in TTI_SOURCE
    assert "const BUDGET_FPS = 55;" in FPS_SOURCE


def test_each_threshold_is_declared_exactly_once() -> None:
    """A second declaration is how a threshold gets quietly relaxed: one is edited, the
    other is the one that runs."""
    assert TTI_SOURCE.count("BUDGET_SECONDS =") == 1
    assert FPS_SOURCE.count("BUDGET_FPS =") == 1


def test_no_threshold_is_restated_outside_its_harness() -> None:
    """The workflow and the Makefile must invoke, never restate."""
    for path in (PATHS.root / ".github" / "workflows" / "ci.yml", PATHS.root / "Makefile"):
        text = path.read_text(encoding="utf-8")
        body = "\n".join(
            line for line in text.splitlines()
            if not line.strip().startswith("#") and not line.strip().startswith("@echo")
        )
        assert "BUDGET_SECONDS" not in body, path.name
        assert "BUDGET_FPS" not in body, path.name


@pytest.mark.parametrize("script", [TTI, FPS])
def test_each_harness_fails_the_process_on_breach(script: Path) -> None:
    assert "process.exit(1)" in script.read_text(encoding="utf-8")


# --- 3. TTI refuses a page below the required national cell count ---------------------

def test_the_tti_harness_refuses_a_page_that_did_not_load_the_national_surface() -> None:
    """Measured: without the published artifacts the National Overview renders its error
    state, and TTI came back 0.96 s — a comfortable pass against a 3.0 s budget, measuring
    a page with no map and no data."""
    assert "const MIN_CELLS = 50000;" in TTI_SOURCE
    assert "did not load its data is meaningless" in TTI_SOURCE
    assert "__voltgapLayerCells" in TTI_SOURCE


# --- 4. FPS refuses too few cells, software rendering, or no WebGL --------------------

def test_the_fps_harness_requires_the_national_layer() -> None:
    assert "const MIN_CELLS = 50000;" in FPS_SOURCE
    assert "near-empty layer means nothing" in FPS_SOURCE


def test_the_fps_harness_refuses_software_rendering() -> None:
    assert "swiftshader" in FPS_SOURCE.lower()
    assert "llvmpipe" in FPS_SOURCE.lower()
    assert "software rasteriser" in FPS_SOURCE


def test_the_fps_harness_refuses_an_absent_webgl_context() -> None:
    """A GPU-less Chrome serves NO WebGL context here rather than falling back to
    SwiftShader, so a name-only check would miss exactly the case CI produces."""
    assert 'renderer === "none"' in FPS_SOURCE
    assert "no WebGL context is available" in FPS_SOURCE


def test_the_fps_harness_measures_the_worst_window_not_the_mean() -> None:
    """An average lets a half-second stall hide behind fast frames either side of it."""
    assert "worstWindow" in FPS_SOURCE
    assert "requestAnimationFrame" in FPS_SOURCE
    assert "not the average" in FPS_SOURCE or "not the mean" in FPS_SOURCE


# --- 5. no fallback metric may replace TTI --------------------------------------------

def test_tti_is_read_from_the_interactive_audit_and_nothing_else() -> None:
    assert "audits.interactive.numericValue" in TTI_SOURCE
    for substitute in ("audits['largest-contentful-paint'].numericValue / 1000;\n  tti",
                       "tti: audits[\"largest-contentful-paint\"]",
                       "tti: audits[\"total-blocking-time\"]",
                       "tti: audits[\"interaction-to-next-paint\"]"):
        assert substitute not in TTI_SOURCE, substitute


def test_the_harness_fails_rather_than_substituting_if_tti_disappears() -> None:
    """TTI is legacy — unscored and hidden since Lighthouse 10, still computed. If a
    future release drops the computation, the criterion becomes unmeasurable and that must
    be an owner decision, not a silent swap for LCP or INP."""
    assert "does not emit the `interactive` audit" in TTI_SOURCE
    assert "Do NOT substitute LCP, TBT" in TTI_SOURCE
    assert "PLAN_CHANGE_6.md" in TTI_SOURCE


def test_the_contemporary_metrics_are_labelled_diagnostics() -> None:
    assert "NOT substituted for the budget" in TTI_SOURCE
    assert "LEGACY" in TTI_SOURCE
    assert "not a Core Web Vital" in TTI_SOURCE


# --- 6. benchmark provenance and reference-environment metadata exist ------------------

def test_the_provenance_artifact_exists_and_is_well_formed() -> None:
    assert PROVENANCE.is_file(), "the reference-environment record must be published"
    payload = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    assert "time_to_interactive" in payload
    assert "sustained_frame_rate" in payload


@pytest.mark.parametrize("benchmark", ["time_to_interactive", "sustained_frame_rate"])
def test_each_benchmark_records_the_environment_that_produced_it(benchmark: str) -> None:
    """An environment-dependent number without its environment is not evidence."""
    entry = json.loads(PROVENANCE.read_text(encoding="utf-8"))[benchmark]
    environment = entry["reference_environment"]
    for field in ("platform", "arch", "cpu_model", "cpu_cores", "node"):
        assert environment.get(field), f"{benchmark}.{field}"
    assert entry["measured_at"]
    assert entry["harness"].startswith("web/scripts/")
    assert "environment-dependent" in entry["enforcement_class"]
    assert entry["within_budget"] is True


def test_the_tti_record_names_its_toolchain_and_its_host_dependence() -> None:
    entry = json.loads(PROVENANCE.read_text(encoding="utf-8"))["time_to_interactive"]
    assert entry["lighthouse_version"]
    assert entry["chrome"]
    assert entry["throttling"]["cpuSlowdownMultiplier"] == 4
    assert "not comparable" in entry["host_dependence"]
    assert "LEGACY" in entry["metric_status"]


def test_the_fps_record_names_the_renderer_and_the_cells_rendered() -> None:
    entry = json.loads(PROVENANCE.read_text(encoding="utf-8"))["sustained_frame_rate"]
    assert entry["cells_rendered"] >= 50_000
    assert entry["renderer"]
    assert "swiftshader" not in entry["renderer"].lower()
    assert entry["renderer"] != "none"
    assert len(entry["validity_guards"]) >= 3


# --- 7. the PR status reports these as not executed, never as PASS --------------------

def test_the_workflow_reports_unexecuted_budgets_as_not_executed() -> None:
    workflow = (PATHS.root / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8")
    assert "NOT EXECUTED ON THIS RUNNER" in workflow
    # And it must never print a pass for something it did not run.
    assert "not a PASS" in workflow


# --- the machine-validity guard, added after a contended gate run -------------------

def test_the_tti_harness_refuses_a_contended_machine() -> None:
    """§11.3 makes TTI environment-dependent, and that cuts both ways: as well as not
    comparing an arbitrary runner's figure against 3.0 s, the reference machine's own
    figure is only admissible while it is behaving like the reference environment.

    Measured: eight competing CPU burners moved TTI from 2.91 s to 3.84 s on identical
    code, and Lighthouse's own `benchmarkIndex` fell from ~4092 to 2840. The harness uses
    that instrument to refuse rather than report a number the contention produced.
    """
    assert "REFERENCE_BENCHMARK_INDEX_FLOOR = 3500" in TTI_SOURCE
    assert "NOT MEASURED" in TTI_SOURCE
    assert "benchmarkIndex" in TTI_SOURCE
    # It must be reported as not measured, NOT as a pass or a failure of the application.
    assert "not a budget failure" in TTI_SOURCE


def test_the_validity_floor_is_derived_from_measurement_not_chosen() -> None:
    """A floor picked to make a run pass would be indistinguishable from one derived from
    the machine, unless the derivation is recorded next to it."""
    assert "quiescent range 4032-4136" in TTI_SOURCE or "4032-4136" in TTI_SOURCE
    assert "2840" in TTI_SOURCE


def test_the_provenance_records_the_machine_validity_of_the_accepted_figure() -> None:
    entry = json.loads(PROVENANCE.read_text(encoding="utf-8"))["time_to_interactive"]
    assert entry["benchmark_index_median"] >= entry["benchmark_index_floor"]
    assert "benchmark_index_note" in entry


def test_the_gate_quiesces_the_machine_before_the_dependent_benchmarks() -> None:
    """The gate runs ~20 minutes of full load immediately before measuring. Doing so
    without settling measures the gate's own load; the settle is part of establishing the
    reference conditions, and changes no threshold or measured quantity."""
    settle = PATHS.root / "web" / "scripts" / "perf-settle.mjs"
    assert settle.is_file()
    text = settle.read_text(encoding="utf-8")
    assert "QUIESCENT_LOAD_PER_CORE" in text
    assert "changes no threshold" in text
    makefile = (PATHS.root / "Makefile").read_text(encoding="utf-8")
    gate = makefile[makefile.index("\ngate-6:"):]
    settle_at = gate.index("directory web-perf-settle")
    measure_at = gate.index("directory web-perf-tti")
    assert settle_at < measure_at, "the machine must settle before it is measured"


# --- the analytical layer must be VISIBLY rendered, not merely populated --------------

def test_the_render_check_compares_rendered_output_not_loaded_state() -> None:
    """The defect this exists for: deck.gl reported all 53,208 cells, held valid US
    coordinates and non-zero alpha, and drew nothing a person could see. Every check the
    project had passed. Only rendered output distinguishes populated from visible."""
    assert "?layer=off" in RENDER_SOURCE or "layer=off" in RENDER_SOURCE
    assert "screenshot" in RENDER_SOURCE
    assert "MIN_CHANGED_SHARE" in RENDER_SOURCE


def test_the_render_check_asserts_the_palette_not_only_a_pixel_count() -> None:
    """A count-only check passes the real defect: with `_normalize: false` the layer drew
    the whole surface in WHITE on a white basemap, changing 5.2% of pixels while being
    invisible. Measured: 0.9% of changed pixels carried the palette in that state against
    51.6% when correct."""
    assert "MIN_CHROMATIC_SHARE_OF_CHANGED" in RENDER_SOURCE
    assert "saturation" in RENDER_SOURCE
    assert "luminance" in RENDER_SOURCE


def test_the_render_check_is_a_difference_not_a_golden_image() -> None:
    """A golden screenshot would break on a basemap tile change or a browser update and
    would be quietly re-blessed."""
    assert "golden" in RENDER_SOURCE.lower()
    assert "pngjs" in RENDER_SOURCE


@pytest.mark.parametrize(
    "guard",
    ["MIN_CELLS", "US_BOUNDS", "CONUS", "colours PER VERTEX", "not closed"],
)
def test_the_render_check_keeps_its_structural_guards(guard: str) -> None:
    assert guard in RENDER_SOURCE, guard


def test_the_frame_rate_harness_requires_a_per_vertex_colour_buffer() -> None:
    """A frame rate measured over an invisible layer measures an idle GPU."""
    assert "colours PER VERTEX" in FPS_SOURCE
    assert "web-render-check" in FPS_SOURCE


def test_the_gate_runs_the_render_check() -> None:
    makefile = (PATHS.root / "Makefile").read_text(encoding="utf-8")
    gate = makefile[makefile.index("\ngate-6:"):]
    assert "directory web-render-check" in gate
