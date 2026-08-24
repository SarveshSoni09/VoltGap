"""Terminology guard for directive D3 and the CLAUDE.md section 11.5 copy rules.

Created in Phase 1 (specification amendment A9) and run in CI from this phase onward;
Phase 5 extends it. It is deliberately rule-based: it does not attempt to understand
arbitrary prose, only to catch the specific prohibited phrases and the D3 conflations.

Three things this exists to prevent shipping:

* **Optimality claims.** No ground truth for optimal siting exists, so nothing may be
  described as optimal, validated-optimal or proven best.
* **Grid feasibility claims.** Substation or line proximity says nothing about hosting
  capacity, feeder availability, transformer headroom or make-ready cost (D6).
* **Validation-term conflation.** Demand model validation, historical deployment
  alignment and cross-objective robustness are three different things (D3).

**Allowlisting.** Documents that quote a prohibited phrase in order to forbid it - the
specification itself, this module, its tests, the phase reports - would otherwise trip
the lint on their own prohibitions. Two mechanisms handle that: whole-file allowlisting
by path, and an inline ``copy-lint: allow`` marker on the offending line.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from pipeline.config.settings import PATHS

INLINE_ALLOW = "copy-lint: allow"

# Hyphen-like characters that appear in real prose for the (1 - 1/e) bound:
# ASCII hyphen, U+2212 MINUS SIGN, U+2013 EN DASH. Written as escapes so this
# source file contains no ambiguous Unicode of its own.
DASHES = "[-\u2212\u2013]"

# Files whose job is to define or discuss the prohibitions themselves.
ALLOWLISTED_PATHS: frozenset[str] = frozenset({
    "CLAUDE.md",
    "pipeline/quality/copy_lint.py",
    "tests/unit/test_copy_lint.py",
    "docs/reports/PHASE_1_PLAN.md",
    "docs/reports/PLAN_CHANGE_0.md",
    "docs/reports/IMPACT_LOG.md",
    "docs/reports/ASSUMPTION_LEDGER.md",
    "docs/DATA_GOTCHAS.md",
    "docs/LIMITATIONS.md",
    "docs/VALIDATION.md",
    "STARTER_PROMPT.md",
    "SETUP.md",
})

# Globs allowlisted for the same reason. Phase reports must be able to quote a
# prohibited phrase in order to record that it is prohibited, or to document that a
# claim was removed. This is a real weakening: a genuine optimality claim inside a
# report would not be caught. It is accepted because reports are prose reviewed by a
# person, while the places a false claim would actually ship - UI strings, docstrings,
# published artifact fields - are NOT allowlisted. Tracked as assumption A-1.3.
ALLOWLISTED_GLOBS: tuple[str, ...] = (
    "docs/reports/PHASE_*_REPORT.md",
    "docs/reports/PLAN_CHANGE_*.md",
)

EXTENSIONS: frozenset[str] = frozenset({".md", ".py", ".sql", ".ts", ".tsx", ".yml", ".yaml"})
SKIP_DIRECTORIES: frozenset[str] = frozenset({
    ".git", ".venv", "node_modules", "data", "__pycache__", ".mypy_cache",
    ".ruff_cache", ".pytest_cache", "htmlcov", "artifacts",
})


@dataclass(frozen=True)
class Rule:
    """One prohibited pattern."""

    rule_id: str
    pattern: re.Pattern[str]
    message: str

    @classmethod
    def of(cls, rule_id: str, pattern: str, message: str) -> Rule:
        return cls(rule_id, re.compile(pattern, re.IGNORECASE), message)


@dataclass(frozen=True)
class Violation:
    path: Path
    line_number: int
    rule_id: str
    message: str
    line: str

    def render(self, root: Path) -> str:
        try:
            shown = self.path.relative_to(root)
        except ValueError:  # pragma: no cover - defensive, paths are repo-relative
            shown = self.path
        return (f"{shown}:{self.line_number}: [{self.rule_id}] {self.message}\n"
                f"    {self.line.strip()[:160]}")


RULES: tuple[Rule, ...] = (
    # --- optimality (CLAUDE.md 11.5, D3) ---
    Rule.of("D3-OPT-01", r"\boptimal sit(e|es|ing)\b",
            "no ground truth for optimal siting exists; describe the output as a "
            "ranked, budget-feasible portfolio"),
    Rule.of("D3-OPT-02", r"\bvalidated[- ]optimal\b|\bvalidated as optimal\b",
            "no validation in this project demonstrates optimality"),
    Rule.of("D3-OPT-03", r"\boptimal siting accuracy\b",
            "conflates siting with an accuracy measure that does not exist"),
    Rule.of("D3-OPT-04", r"\bproven best\b|\bprovably best\b|\bthe best sites?\b",
            "unsupported superlative"),
    # --- grid feasibility (D6) ---
    Rule.of("D6-GRID-01", r"\bgrid[- ]feasib(le|ility)\b",
            "proximity is not feasibility; use 'grid proximity'"),
    Rule.of("D6-GRID-02", r"\binterconnection[- ]read(y|iness)\b",
            "proximity says nothing about interconnection readiness"),
    Rule.of("D6-GRID-03", r"\bavailable grid capacity\b|\bgrid capacity available\b",
            "hosting capacity is not measured by this project"),
    Rule.of("D6-GRID-04", r"\bfeeder capacity\b",
            "feeder availability is not measured by this project"),
    Rule.of("D6-GRID-05", r"\btransformer headroom\b",
            "transformer headroom is not measured by this project"),
    # --- access terminology (11.5) ---
    Rule.of("UI-GAP-01", r"\bcharging desert\b",
            "use 'DCFC access gap' unless the measure includes Level 2"),
    # --- equity (section 8) ---
    Rule.of("UI-J40-01", r"\bJustice40 complian(t|ce)\b",
            "EO 14008 was revoked on 20 January 2025; CEJST is an archived overlay"),
    # --- evidence terminology (A3) ---
    Rule.of("UI-TIER-01", r"Tier A \(observed\)|\bTier A[, ]+observed\b",
            "Tier A is 'sub-state anchored'; most Tier A tracts are ZIP- or "
            "county-anchored, not directly observed"),
    # --- approximation bound (A11) ---
    Rule.of("MATH-BOUND-01", rf"\(1\s*{DASHES}\s*1/e\)|\b1\s*{DASHES}\s*1/e\b",
            "the (1 - 1/e) bound does not apply to budgeted maximum coverage; state "
            "no formal bound unless it provably applies to the implemented algorithm"),
    # --- D3 conflation ---
    Rule.of("D3-CONFLATE-01", r"\bdeployment alignment\b[^.\n]{0,40}\bvalidat(es|ed|ion)\b",
            "historical deployment alignment is not demand model validation"),
    Rule.of("D3-CONFLATE-02", r"\bbacktest\b[^.\n]{0,30}\bproves\b",
            "alignment with past industry deployment does not prove correctness"),
)


def is_allowlisted(path: Path, root: Path) -> bool:
    try:
        relative = PurePosixPath(path.relative_to(root).as_posix())
    except ValueError:  # pragma: no cover - defensive
        return False
    if relative.as_posix() in ALLOWLISTED_PATHS:
        return True
    return any(relative.match(glob) for glob in ALLOWLISTED_GLOBS)


def iter_files(root: Path) -> Iterable[Path]:
    """Every lintable file under root, skipping vendored and generated trees."""
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in EXTENSIONS:
            continue
        if any(part in SKIP_DIRECTORIES for part in path.relative_to(root).parts):
            continue
        yield path


def lint_text(text: str, path: Path, rules: Sequence[Rule] = RULES) -> list[Violation]:
    """Apply every rule to every line, honouring the inline allow marker."""
    violations: list[Violation] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if INLINE_ALLOW in line:
            continue
        for rule in rules:
            if rule.pattern.search(line):
                violations.append(Violation(path, number, rule.rule_id, rule.message, line))
    return violations


def lint_paths(paths: Iterable[Path], root: Path,
               rules: Sequence[Rule] = RULES) -> list[Violation]:
    violations: list[Violation] = []
    for path in paths:
        if is_allowlisted(path, root):
            continue
        violations.extend(
            lint_text(path.read_text(encoding="utf-8", errors="replace"), path, rules)
        )
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="VoltGap D3 / UI terminology lint")
    parser.add_argument("--root", type=Path, default=PATHS.root)
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args(argv)

    targets = args.paths if args.paths else list(iter_files(args.root))
    violations = lint_paths(targets, args.root)
    for violation in violations:
        print(violation.render(args.root), file=sys.stderr)
    scanned = len(targets)
    if violations:
        print(f"copy lint: {len(violations)} violation(s) across {scanned} files",
              file=sys.stderr)
        return 1
    print(f"copy lint: clean ({scanned} files, {len(RULES)} rules)")
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
