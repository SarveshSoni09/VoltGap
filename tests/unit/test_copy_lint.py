"""Unit tests for the D3 / UI terminology lint.

Every prohibited phrase gets a positive test (it is caught) so the rule set cannot
silently rot. String literals here deliberately contain prohibited phrases; this file
is allowlisted for exactly that reason.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.quality.copy_lint import (
    ALLOWLISTED_PATHS,
    INLINE_ALLOW,
    RULES,
    Rule,
    is_allowlisted,
    iter_files,
    lint_paths,
    lint_text,
    main,
)


def rule_ids(text: str) -> set[str]:
    return {v.rule_id for v in lint_text(text, Path("x.md"))}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("we recommend the optimal site here", "D3-OPT-01"),
        ("optimal siting is what we deliver", "D3-OPT-01"),
        ("this portfolio is validated-optimal", "D3-OPT-02"),
        ("a validated as optimal result", "D3-OPT-02"),
        ("reports optimal siting accuracy of 91%", "D3-OPT-03"),
        ("the proven best locations", "D3-OPT-04"),
        ("these are the best sites in the state", "D3-OPT-04"),
        ("the cell is grid feasible", "D6-GRID-01"),
        ("grid-feasibility confirmed", "D6-GRID-01"),
        ("site is interconnection ready", "D6-GRID-02"),
        ("interconnection-readiness score", "D6-GRID-02"),
        ("shows available grid capacity", "D6-GRID-03"),
        ("estimated feeder capacity", "D6-GRID-04"),
        ("transformer headroom of 2 MW", "D6-GRID-05"),
        ("this is a charging desert", "UI-GAP-01"),
        ("tract is Justice40 compliant", "UI-J40-01"),
        ("Tier A (observed) tracts", "UI-TIER-01"),
        ("carries a (1 - 1/e) approximation bound", "MATH-BOUND-01"),
        ("greedy gives 1 - 1/e of optimum", "MATH-BOUND-01"),
    ],
)
def test_each_prohibited_phrase_is_caught(text: str, expected: str) -> None:
    assert expected in rule_ids(text), f"{expected} did not fire on {text!r}"


def test_d3_conflation_rules_fire() -> None:
    assert "D3-CONFLATE-01" in rule_ids(
        "deployment alignment validates the demand model"
    )
    assert "D3-CONFLATE-02" in rule_ids("the backtest proves the model is right")


def test_permitted_language_is_not_flagged() -> None:
    """The approved vocabulary must pass cleanly, or the lint is unusable."""
    good = """
    Grid proximity is a proximity proxy and says nothing about hosting capacity.
    Tier A means sub-state anchored, never observed.
    This is a DCFC access gap, not a desert of any kind.
    The archived CEJST overlay reflects a policy framework no longer in force.
    Interactive approximation. Exact offline solutions are used for the published
    analytical frontier. Historical deployment alignment measures whether priorities
    match where industry actually built; it does not measure whether that was correct.
    Demand model validation is leave-one-state-out. Cross-objective robustness is
    an epsilon-constraint analysis.
    """
    assert lint_text(good, Path("x.md")) == []


def test_inline_marker_suppresses_a_line() -> None:
    text = f"the optimal site is here  {INLINE_ALLOW}"
    assert lint_text(text, Path("x.md")) == []


def test_violation_render_is_relative_and_truncated(tmp_path: Path) -> None:
    target = tmp_path / "doc.md"
    target.write_text("x" * 200 + " optimal site", encoding="utf-8")
    violation = lint_paths([target], tmp_path)[0]
    rendered = violation.render(tmp_path)
    assert rendered.startswith("doc.md:1: [D3-OPT-01]")
    assert len(rendered.splitlines()[1]) <= 170


def test_allowlisted_files_are_skipped(tmp_path: Path) -> None:
    claude = tmp_path / "CLAUDE.md"
    claude.write_text("never say optimal site", encoding="utf-8")
    assert lint_paths([claude], tmp_path) == []
    assert is_allowlisted(claude, tmp_path) is True


def test_report_and_plan_change_globs_are_allowlisted(tmp_path: Path) -> None:
    (tmp_path / "docs" / "reports").mkdir(parents=True)
    for name in ("PHASE_0_REPORT.md", "PHASE_12_REPORT.md", "PLAN_CHANGE_3.md"):
        path = tmp_path / "docs" / "reports" / name
        path.write_text("quoting 'grid feasible' to forbid it", encoding="utf-8")
        assert is_allowlisted(path, tmp_path) is True, name


def test_non_report_docs_are_not_allowlisted(tmp_path: Path) -> None:
    """The places a false claim would actually ship must stay in scope."""
    (tmp_path / "docs").mkdir()
    path = tmp_path / "docs" / "METHODOLOGY.md"
    path.write_text("the optimal site selection", encoding="utf-8")
    assert is_allowlisted(path, tmp_path) is False
    assert len(lint_paths([path], tmp_path)) == 1


def test_path_outside_root_is_not_allowlisted(tmp_path: Path) -> None:
    assert is_allowlisted(Path("/elsewhere/CLAUDE.md"), tmp_path) is False


def test_iter_files_selects_extensions_and_skips_vendored_trees(tmp_path: Path) -> None:
    (tmp_path / "keep.md").write_text("a", encoding="utf-8")
    (tmp_path / "keep.py").write_text("a", encoding="utf-8")
    (tmp_path / "skip.png").write_bytes(b"\x00")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.md").write_text("optimal site", encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "y.md").write_text("optimal site", encoding="utf-8")
    names = {p.name for p in iter_files(tmp_path)}
    assert names == {"keep.md", "keep.py"}


def test_custom_rule_set_is_honoured() -> None:
    rules = (Rule.of("X-1", r"\bwidget\b", "no widgets"),)
    assert [v.rule_id for v in lint_text("a widget here", Path("x.md"), rules)] == ["X-1"]
    assert lint_text("an optimal site", Path("x.md"), rules) == []


def test_main_returns_zero_on_a_clean_tree(tmp_path: Path,
                                           capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "ok.md").write_text("grid proximity, sub-state anchored", encoding="utf-8")
    assert main(["--root", str(tmp_path)]) == 0
    assert "copy lint: clean" in capsys.readouterr().out


def test_main_returns_one_and_reports_on_a_violation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "bad.md").write_text("the optimal site", encoding="utf-8")
    assert main(["--root", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert "D3-OPT-01" in captured.err
    assert "1 violation(s)" in captured.err


def test_main_accepts_explicit_paths(tmp_path: Path) -> None:
    target = tmp_path / "bad.md"
    target.write_text("grid feasible", encoding="utf-8")
    assert main(["--root", str(tmp_path), str(target)]) == 1


def test_the_repository_itself_is_clean() -> None:
    """The guard that actually matters: this repository passes its own lint."""
    assert main([]) == 0


def test_rule_ids_are_unique() -> None:
    ids = [rule.rule_id for rule in RULES]
    assert len(ids) == len(set(ids))


def test_allowlist_entries_are_repo_relative_posix_paths() -> None:
    for entry in ALLOWLISTED_PATHS:
        assert not entry.startswith("/"), entry
        assert "\\" not in entry, entry


def test_all_three_dash_forms_of_the_bound_are_caught() -> None:
    """CLAUDE.md writes the bound with U+2212; prose elsewhere uses hyphen or en dash."""
    for dash in ("-", "\u2212", "\u2013"):  # hyphen, minus sign, en dash
        assert "MATH-BOUND-01" in rule_ids(f"carries a (1 {dash} 1/e) bound"), dash
        assert "MATH-BOUND-01" in rule_ids(f"greedy gives 1 {dash} 1/e of optimum"), dash


def test_the_bound_rule_does_not_fire_on_unrelated_arithmetic() -> None:
    assert "MATH-BOUND-01" not in rule_ids("the value 1 - 1/exp(x) is used")


# --- Phase 5 extension: sanctioned disclaimers ----------------------------------------

def test_the_project_can_state_its_own_central_caveat() -> None:
    """Extended in Phase 5 (§15.5). The rules match phrases, not meaning, so they cannot
    tell a claim from its denial. Without this the project could not write down the one
    sentence CLAUDE.md D3 requires it to write down, and the pressure would be to soften
    the disclaimer to appease the linter - exactly backwards."""
    from pipeline.quality.copy_lint import lint_text

    caveat = "Ground truth for optimal siting does not exist."
    assert lint_text(caveat, Path("docs/VALIDATION.md")) == []


def test_a_real_optimality_claim_is_still_caught() -> None:
    """The disclaimer list must not become a way to smuggle a claim through."""
    from pipeline.quality.copy_lint import lint_text

    violations = lint_text("This is the optimal site for a charger.",
                           Path("docs/VALIDATION.md"))
    assert [v.rule_id for v in violations] == ["D3-OPT-01"]


def test_a_claim_on_the_same_line_as_a_disclaimer_is_still_caught() -> None:
    """Stripping the sanctioned phrase must leave the rest of the line under scrutiny,
    or a caveat would become a shield for whatever sits beside it."""
    from pipeline.quality.copy_lint import lint_text

    line = ("Ground truth for optimal siting does not exist, but this is the optimal "
            "site anyway.")
    assert [v.rule_id for v in lint_text(line, Path("docs/x.md"))] == ["D3-OPT-01"]


def test_every_sanctioned_disclaimer_is_actually_needed() -> None:
    """A phrase that trips no rule does not belong on the list: it would be dead weight
    that a reader would mistake for a permitted claim."""
    from pipeline.quality.copy_lint import RULES, SANCTIONED_DISCLAIMERS

    for phrase in SANCTIONED_DISCLAIMERS:
        assert any(rule.pattern.search(phrase) for rule in RULES), phrase


def test_stripping_replaces_rather_than_deletes_so_offsets_survive() -> None:
    from pipeline.quality.copy_lint import strip_sanctioned

    phrase = "Ground truth for optimal siting does not exist"
    line = f"a {phrase} b"
    stripped = strip_sanctioned(line)
    assert len(stripped) == len(line), "offsets must survive so messages stay accurate"
    assert stripped == "a " + " " * len(phrase) + " b"


def test_a_disclaimer_repeated_on_one_line_is_stripped_every_time() -> None:
    from pipeline.quality.copy_lint import lint_text

    line = ("Ground truth for optimal siting does not exist. "
            "Ground truth for optimal siting does not exist.")
    assert lint_text(line, Path("docs/x.md")) == []
