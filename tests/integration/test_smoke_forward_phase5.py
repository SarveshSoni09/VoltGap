"""G-D smoke-forward: is Phase 5's output usable by Phase 6 (Frontend Core)?

§15.2 requires a minimal executable exercise of the NEXT phase's core operation against
this phase's real output. Phase 6 ships three views plus a Methodology and Validation
page, which is a first-class view rather than a footer link (§11.1). That page renders
Phase 5's results, so what it needs from this artifact is: every number reachable without
recomputation, every claim carrying the disclaimer it must be displayed with, and the D3
vocabulary intact so the copy lint passes over rendered strings.

This does not have to be a frontend. It has to prove the data shape works.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from pipeline.config.settings import PATHS

EVIDENCE = PATHS.root / "docs" / "evidence" / "P5-1_validation.json"


@pytest.fixture(scope="module")
def evidence() -> dict[str, Any]:
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def test_a_validation_page_can_be_rendered_from_the_artifact_alone(
    evidence: dict[str, Any],
) -> None:
    """The Methodology and Validation view must not need the pipeline to draw itself."""
    lines: list[str] = []
    for term, definition in evidence["validation_terms"].items():
        lines.append(f"{term}: {definition}")
    for entry in evidence["deployment_alignment"]:
        lines.append(
            f"origin {entry['origin']} (cutoff {entry['prediction_cutoff']}): "
            f"top-decile capture "
            f"{entry['model']['top_decile_capture_stations']:.1%}, "
            f"lift vs random {entry['lift_vs_random_stations']:.2f}, "
            f"lift vs population {entry['lift_vs_population_stations']:.2f}")
    assert len(lines) >= 7
    assert all(line.strip() for line in lines)


def test_every_alignment_number_ships_with_the_caveat_it_must_be_shown_with(
    evidence: dict[str, Any],
) -> None:
    """A frontend that renders the capture rate without the caveat would be a bug, so
    the caveat has to be in the same record as the number."""
    for entry in evidence["deployment_alignment"]:
        assert entry["what_this_measures"]
        assert len(entry["what_this_does_not_measure"]) >= 4


def test_a_gain_curve_can_be_plotted_without_recomputation(
    evidence: dict[str, Any],
) -> None:
    """Ten (x, y) pairs per ranking, already cumulative and already normalised."""
    entry = evidence["deployment_alignment"][0]
    for ranking in [entry["model"], *entry["baselines"]]:
        points = [(p["decile"], p["share_of_subsequent_stations_captured"])
                  for p in ranking["gain_curve"]]
        assert len(points) == 10
        assert points[0][0] == 0.1 and points[-1][0] == 1.0
        assert all(0.0 <= y <= 1.0 for _, y in points)


def test_a_robustness_table_can_be_rendered_as_portfolios_by_objective(
    evidence: dict[str, Any],
) -> None:
    """The shape a tradeoff table needs: one row per portfolio, one column per
    objective, already normalised to the best score so the cells are comparable."""
    row = evidence["cross_objective_robustness"]["per_state_and_budget"][0]
    relative = row["relative_to_best"]
    objectives = sorted({o for scores in relative.values() for o in scores})
    assert len(objectives) == 6
    for portfolio, scores in relative.items():
        assert set(scores) == set(objectives), portfolio
        assert all(0.0 <= v <= 1.0 for v in scores.values()), portfolio


def test_the_vintage_ledger_can_be_rendered_as_a_provenance_table(
    evidence: dict[str, Any],
) -> None:
    """§11.1 requires provenance visible. Every declared vintage carries what a reader
    needs to check it rather than trust it."""
    for vintage in evidence["vintage_ledger"]["declared_vintages"]:
        assert set(vintage) >= {"source_id", "label", "period_end", "released",
                                "release_date_certain", "release_evidence"}


def test_no_rendered_string_claims_optimality_or_proof(
    evidence: dict[str, Any],
) -> None:
    """§11.5 copy rules, applied to the strings a frontend would actually display.

    The rules come from the copy lint itself rather than being restated here, so this
    test cannot drift from them and adding a rule automatically covers this artifact.
    """
    from pipeline.quality.copy_lint import RULES, lint_text

    violations = lint_text(json.dumps(evidence, indent=1), EVIDENCE, RULES)
    assert not violations, [
        f"{v.rule_id}: {v.line.strip()[:120]}" for v in violations[:5]]


def test_phase_6_can_tell_independent_validation_from_diagnostic_evidence(
    evidence: dict[str, Any],
) -> None:
    """Required Phase 5 evidence question 10. A view that presented Washington's
    calibration as independent validation would be misreporting it."""
    track = evidence["demand_model_validation"]
    assert "EXCLUDED from the independent headline aggregate" in str(
        track["washington_status"])
