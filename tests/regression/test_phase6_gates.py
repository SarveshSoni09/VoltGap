"""Phase 6 acceptance criteria (§15.5).

> Static export deploys. All performance budgets met and CI-enforced. Exports produce valid
> CSV and GeoJSON verified by parse. UI copy lint passes (§11.5 rules). Confidence tier
> renders on every modeled value. Unmoderated usability check: one person unfamiliar with
> the project produces a siting recommendation without instructions.

The last criterion needs a human participant and cannot be executed here. It is **not**
redefined into something passable — see `docs/reports/PLAN_CHANGE_6.md`, and P6-G below,
which asserts the blocker is recorded rather than asserting the check passed.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

import duckdb
import pytest

from pipeline.config.settings import PATHS

WEB = PATHS.root / "web"
OUT = WEB / "out"
DATA = WEB / "public" / "data"
EVIDENCE = PATHS.root / "docs" / "evidence" / "P4-1_siting.json"

FRONTIER_STATES = {
    "Washington": "53", "Tennessee": "47", "Montana": "30",
    "Vermont": "50", "Texas": "48", "California": "06",
}


@pytest.fixture(scope="module")
def phase4() -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    return payload


# --- P6-A: the static export exists and is real ---------------------------------------

def test_p6_a_the_static_export_produced_every_core_view() -> None:
    """§11.1: three Core views plus Methodology, all statically exported."""
    for page in ("index.html", "access/index.html", "studio/index.html",
                 "methodology/index.html"):
        path = OUT / page
        assert path.is_file(), f"{page} was not exported"
        assert path.stat().st_size > 2000, f"{page} is suspiciously small"


def test_p6_a_no_server_runtime_is_required() -> None:
    """§2: static export only, no serverless functions in Core."""
    assert not (OUT / "api").exists()
    for marker in ("_next/server", "server.js", "middleware.js", "proxy.js"):
        assert not (OUT / marker).exists(), f"{marker} implies a server runtime"


def test_p6_a_the_methodology_view_renders_its_content_statically() -> None:
    """It is a first-class view, so its text must be in the HTML rather than arriving
    later from JavaScript - a reader with a slow connection still gets the caveats."""
    html = (OUT / "methodology" / "index.html").read_text(encoding="utf-8")
    assert "Historical deployment alignment" in html
    assert "negative result" in html
    assert "sub-state anchored" in html
    assert "No approximation bound is claimed" in html


# --- P6-B: performance budget, CI-enforced --------------------------------------------

def test_p6_b_the_bundle_budget_script_passes_and_is_enforceable() -> None:
    """§11.3: app shell <= 600 KB gzipped, and CI fails on violation. The script exits
    non-zero on breach, which is what makes it an enforcement rather than a report."""
    result = subprocess.run(
        ["node", "scripts/bundle-budget.mjs"], cwd=WEB,
        capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: app shell" in result.stdout
    assert "600.0 KB" in result.stdout


def test_p6_b_the_shell_excludes_the_map_libraries() -> None:
    """deck.gl and MapLibre are ~460 KB gzipped. They are dynamically imported, so they
    are not in the shell - and the budget script must be measuring that, not assuming it."""
    result = subprocess.run(
        ["node", "scripts/bundle-budget.mjs"], cwd=WEB,
        capture_output=True, text=True, check=False)
    assert "Lazily loaded" in result.stdout
    assert "not counted against the shell" in result.stdout


# --- P6-C: the browser candidate universe matches Phase 4 -----------------------------

@pytest.mark.parametrize("state", sorted(FRONTIER_STATES))
def test_p6_c_the_published_artifact_reproduces_phase_4s_candidate_universe(
    state: str, phase4: dict[str, Any]
) -> None:
    """The strongest available check that the frontend sites on the same cells Phase 4
    reasoned about. Applying Phase 4's filter rules to the published artifact must give
    Phase 4's own counts, exclusion by exclusion.

    A mismatch would mean the Studio offers candidates the accepted pipeline excluded,
    which no amount of interface polish would make acceptable.
    """
    fips = FRONTIER_STATES[state]
    expected = next(s for s in phase4["per_state"] if s["state"] == state)
    counts = duckdb.sql(f"""
        SELECT
          count(*) FILTER (WHERE population < 1) AS uninhabited,
          count(*) FILTER (WHERE population >= 1
                             AND NOT passes_road_filter) AS beyond_road,
          count(*) FILTER (WHERE population >= 1 AND passes_road_filter
                             AND demand_bev > 0
                             AND dcfc_ports * 1000.0 / demand_bev >= 2.0) AS saturated,
          count(*) FILTER (WHERE population >= 1 AND passes_road_filter
                             AND NOT (demand_bev > 0
                               AND dcfc_ports * 1000.0 / demand_bev >= 2.0)) AS candidates
        FROM '{DATA / "hex6_national.parquet"}' WHERE state_fips = '{fips}'
    """).fetchone()
    assert counts is not None
    uninhabited, beyond_road, saturated, candidates = counts
    published = expected["candidate_set"]["excluded_by_reason"]

    assert candidates == expected["candidate_set"]["candidates"], state
    assert beyond_road == published["beyond_primary_secondary_road_network"], state
    assert saturated == published["already_saturated"], state
    assert uninhabited == published.get("uninhabited", 0), state


# --- P6-D: confidence renders on every modeled value ----------------------------------

def test_p6_d_every_published_cell_carries_a_tier_and_evidence_grain() -> None:
    """§17 and §11.1. Checked on the artifact, because a value that leaves the pipeline
    without its tier cannot acquire one in the browser."""
    bad = duckdb.sql(f"""
        SELECT count(*) FROM '{DATA / "hex6_national.parquet"}'
        WHERE confidence_tier NOT IN ('A','B','C')
           OR dominant_evidence_grain IS NULL
           OR uncertainty_score IS NULL
           OR sub_state_anchored_share IS NULL
    """).fetchone()
    assert bad is not None and bad[0] == 0


def test_p6_d_tier_a_is_never_called_observed_anywhere_in_the_exported_site() -> None:
    """§11.5, amendment A3. Checked against the built HTML and JavaScript, which is what
    a user actually reads - a constant renamed in source but stale in a bundle would pass
    a source-only check."""
    offenders = []
    for path in list(OUT.rglob("*.html")) + list(OUT.rglob("*.js")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if "sub-state anchored" in text or "Tier A" in text:
            # This list IS the prohibition: it must contain the phrases in order to
            # search the built output for them.
            for phrase in ('"observed"', "Tier A (observed)",  # copy-lint: allow
                           "tier A observed"):  # copy-lint: allow
                if phrase in text:
                    offenders.append((path.name, phrase))
    assert offenders == []


def test_p6_d_the_tier_vocabulary_reaches_the_built_output() -> None:
    text = "".join(
        p.read_text(encoding="utf-8", errors="replace") for p in OUT.rglob("*.js"))
    assert "sub-state anchored" in text
    assert "low confidence" in text


# --- P6-E: exports verified by parse (the TypeScript suite) ---------------------------

def test_p6_e_the_frontend_test_suite_passes() -> None:
    """Includes the export parse tests and the greedy port checked against Phase 4's
    own Python implementation."""
    result = subprocess.run(
        ["npx", "vitest", "run", "--reporter=basic"], cwd=WEB,
        capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]


# --- P6-F: the artifacts the views load ------------------------------------------------

def test_p6_f_every_artifact_the_manifest_names_exists_with_its_checksum() -> None:
    from pipeline.export.parquet import sha256_of

    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    for name, record in manifest["artifacts"].items():
        path = DATA / name
        assert path.is_file(), name
        assert path.stat().st_size == record["bytes"], name
        assert sha256_of(path) == record["sha256"], name


def test_p6_f_the_first_paint_artifact_is_within_its_size_budget() -> None:
    """§12 budgets hex6_national.parquet at 8-15 MB. It is the only data file the
    National Overview needs, so it bounds cold load."""
    size = (DATA / "hex6_national.parquet").stat().st_size
    assert size < 15_000_000, f"{size:,} bytes exceeds the §12 budget"


def test_p6_f_degradations_are_named_in_the_manifest() -> None:
    """D8: never substitute silently. tippecanoe is unavailable, so the vector tile sets
    are absent and the manifest says which and why."""
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    degradations = manifest["notes"]["degradations"]
    assert "tippecanoe" in degradations["sites_pmtiles"]
    assert "NOT SHIPPED" in degradations["transmission_pmtiles"]


# --- P6-G: the criterion that cannot be executed here ---------------------------------

def test_p6_g_the_unmoderated_usability_check_is_recorded_as_outstanding() -> None:
    """§15.5 Phase 6 requires an unmoderated usability check with a human participant.
    That cannot be executed by an automated gate, and §15.1 G-A forbids marking a
    criterion passed by inspection.

    This test does NOT assert the check passed. It asserts the blocker is recorded, with
    a protocol a human can actually run, so the gap is visible rather than quietly
    absorbed.
    """
    plan = PATHS.root / "docs" / "reports" / "PLAN_CHANGE_6.md"
    assert plan.is_file(), "the usability blocker must be escalated, not skipped"
    text = plan.read_text(encoding="utf-8")
    assert "unmoderated usability" in text.lower()
    assert "cannot" in text.lower()
    for section in ("## Options", "## Evidence", "## The protocol"):
        assert section in text, section
