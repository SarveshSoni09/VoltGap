"""The pull-request workflow cannot silently lose a required job.

`.github/workflows/ci.yml` is the only place §11.3's "CI-enforced" is met at all, and a
workflow is unusually easy to break quietly: delete a step and everything still goes green.
These assert the jobs, the steps, and — for the two budgets a GitHub-hosted runner cannot
measure — that the gap stays documented rather than being quietly filled with a proxy.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from pipeline.config.settings import PATHS

WORKFLOW = PATHS.root / ".github" / "workflows" / "ci.yml"
PLAN_CHANGE = PATHS.root / "docs" / "reports" / "PLAN_CHANGE_6.md"


@pytest.fixture(scope="module")
def workflow() -> dict[Any, Any]:
    loaded: dict[Any, Any] = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return loaded


def steps_of(workflow: dict[Any, Any], job: str) -> str:
    """The job's steps as text. Structural assertions use the parsed YAML; CONTENT
    assertions use the raw file, because `safe_dump` line-wraps long strings and a
    substring check against the round-trip would fail on formatting rather than meaning."""
    return yaml.safe_dump(workflow["jobs"][job]["steps"])


RAW = WORKFLOW.read_text(encoding="utf-8")


def triggers_of(workflow: dict[Any, Any]) -> list[str]:
    """The `on:` block. PyYAML parses the bare key `on` as the BOOLEAN True, not the
    string "on", so both spellings have to be looked for or this reads as absent."""
    block = workflow[True] if True in workflow else workflow["on"]
    return list(block)


# --- it runs on pull requests ---------------------------------------------------------

def test_the_workflow_runs_on_pull_requests(workflow: dict[Any, Any]) -> None:
    assert "pull_request" in triggers_of(workflow)


@pytest.mark.parametrize(
    "job",
    ["python", "frontend", "tti", "fps", "performance-enforcement-status"],
)
def test_every_required_job_is_present(workflow: dict[Any, Any], job: str) -> None:
    assert job in workflow["jobs"], job


def test_the_test_knows_about_every_job_the_workflow_defines(
    workflow: dict[Any, Any],
) -> None:
    """Both directions: an added job must be recorded here too, so this list stays the
    authoritative statement of what PR CI does."""
    assert set(workflow["jobs"]) == {
        "python", "frontend", "tti", "fps", "performance-enforcement-status",
    }


# --- it invokes the accepted checks, rather than reimplementing them -------------------

@pytest.mark.parametrize(
    ("job", "target"),
    [
        ("python", "make lint"),
        ("python", "make copy-lint"),
        ("frontend", "make web-typecheck"),
        ("frontend", "make web-build"),
        ("frontend", "make web-test"),
        ("frontend", "make web-budget"),
        ("frontend", "make web-perf-greedy"),
        ("python", "make web-perf-guards"),
        ("tti", "make web-perf-tti"),
        ("fps", "make web-perf-fps"),
    ],
)
def test_each_job_invokes_the_existing_accepted_check(
    workflow: dict[Any, Any], job: str, target: str
) -> None:
    """A workflow that restated a threshold would be a second place for it to be wrong."""
    assert target in steps_of(workflow, job), f"{job} does not run {target}"


def test_no_threshold_is_restated_in_the_workflow(workflow: dict[Any, Any]) -> None:
    """The numbers live in the harnesses. If one appeared here as a literal, the two could
    disagree and the workflow would win silently."""
    text = WORKFLOW.read_text(encoding="utf-8")
    body = "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("#")
    )
    for restated in ("--fail-under", "BUDGET_FPS", "BUDGET_SECONDS", "600 * 1024"):
        assert restated not in body, restated


# --- the host-dependent budgets are skipped, never faked -------------------------------

@pytest.mark.parametrize(
    ("job", "variable"),
    [("tti", "PERF_DATA_RUNNER"), ("fps", "PERF_GPU_RUNNER")],
)
def test_a_budget_that_cannot_be_measured_is_skipped_not_substituted(
    workflow: dict[Any, Any], job: str, variable: str
) -> None:
    """A GitHub-hosted runner has no GPU and no source cache. Running a weakened
    measurement would be worse than not running one: it would report green."""
    condition = str(workflow["jobs"][job].get("if", ""))
    assert variable in condition, f"{job} must be conditional on {variable}"
    assert str(workflow["jobs"][job]["runs-on"]).find(variable) != -1


def test_the_gap_is_reported_on_every_pull_request(workflow: dict[Any, Any]) -> None:
    """So a green CI cannot be read as more than it is."""
    status = workflow["jobs"]["performance-enforcement-status"]
    assert "if" not in status, "the status report must always run"
    assert "PORTABLE class" in RAW
    assert "ENVIRONMENT-DEPENDENT class" in RAW
    assert "PLAN_CHANGE_6.md" in RAW


def test_an_unexecuted_budget_is_never_reported_as_a_pass(
    workflow: dict[Any, Any],
) -> None:
    """§11.3, amendment A27: "the PR status explicitly reports TTI and frame rate as not
    executed on this runner, never as PASS, when valid infrastructure is unavailable"."""
    assert "NOT EXECUTED ON THIS RUNNER" in RAW
    assert "This is not a PASS. Nothing was measured." in RAW


def test_the_portable_budgets_are_hard_gates_on_every_pull_request(
    workflow: dict[Any, Any],
) -> None:
    """App shell and greedy solve keep their semantics on any runner, so they are measured
    here rather than merely protected."""
    frontend = steps_of(workflow, "frontend")
    assert "make web-budget" in frontend
    assert "make web-perf-greedy" in frontend
    assert "if" not in workflow["jobs"]["frontend"]


def test_the_environment_dependent_budgets_are_protected_on_every_pull_request(
    workflow: dict[Any, Any],
) -> None:
    """Not measured here, but their harnesses, thresholds, guards and provenance are."""
    python_job = steps_of(workflow, "python")
    assert "make web-perf-guards" in python_job
    assert "if" not in workflow["jobs"]["python"]


def test_the_status_job_fails_if_the_limitation_stops_being_documented(
    workflow: dict[Any, Any],
) -> None:
    assert "grep -q" in RAW
    assert "PLAN_CHANGE_6.md" in RAW


def test_the_plan_change_records_the_limitation_and_the_options() -> None:
    text = PLAN_CHANGE.read_text(encoding="utf-8")
    assert "CI runner limits" in text
    assert "PERF_DATA_RUNNER" in text and "PERF_GPU_RUNNER" in text
    assert "NO WEBGL AT ALL" in text
    # The narrowest truthful distinction the review asked for.
    assert "regression check" in text
    assert "acceptance benchmark" in text
    for option in ("**Option A", "**Option B", "**Option C"):
        assert option in text, option
    # And the owner's decision on it, so the record is not left open-ended.
    assert "Owner decision" in text
    assert "A27" in text


# --- Phase 6 scope only ----------------------------------------------------------------

def test_no_phase_7_automation_has_crept_in(workflow: dict[Any, Any]) -> None:
    """§13.2 and §13.3 — scheduled refresh, keepalive, deployment, health monitoring — are
    Phase 7. This file is Phase 6 acceptance plumbing."""
    assert "schedule" not in triggers_of(workflow)
    text = WORKFLOW.read_text(encoding="utf-8").lower()
    body = "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("#")
    )
    for forbidden in ("cron", "vercel", "wrangler", "r2", "deploy", "keepalive"):
        assert forbidden not in body, forbidden


def test_no_other_workflow_files_exist() -> None:
    """etl.yml and keepalive.yml are Phase 7 deliverables (§3)."""
    present = sorted(p.name for p in WORKFLOW.parent.glob("*.yml"))
    assert present == ["ci.yml"]
