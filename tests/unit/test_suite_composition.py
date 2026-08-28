"""Structural invariants of the test suite itself.

These exist because two checkpoint documents disagreed about how many tests this
repository has (``585 deterministic / 46 live`` against a measured
``563 deterministic / 47 live``), and the 46-versus-47 half of that gap has a real,
reproducible cause: **one ``live``-marked test lives outside ``tests/live/``**, so the
directory count and the marker count are genuinely different numbers.

Nothing here asserts a total. Totals change every time a test is added, and a gate that
fails on that would be noise. What is asserted is the structure that made the two counts
diverge, so the same confusion cannot recur silently:

1. every test under ``tests/live/`` carries the ``live`` marker;
2. the ``live``-marked tests *outside* ``tests/live/`` are exactly the enumerated set
   below, so adding another one forces this list, and the documentation, to be updated;
3. the default pytest invocation deselects every ``live`` test, which is what keeps
   ``make gate`` network-independent.
"""

from __future__ import annotations

import ast
import tomllib

from pipeline.config.settings import PATHS

TESTS_ROOT = PATHS.root / "tests"

# The complete set of live-marked tests that do NOT live in tests/live/. This is the
# entire reason the marker count exceeds the tests/live/ file count.
LIVE_MARKED_OUTSIDE_TESTS_LIVE: set[tuple[str, str]] = {
    (
        "tests/integration/test_determinism.py",
        "test_live_refresh_is_not_expected_to_be_byte_identical",
    ),
}


def _module_is_live_marked(tree: ast.Module) -> bool:
    """True when the module sets ``pytestmark = pytest.mark.live``."""
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "pytestmark" not in targets:
            continue
        if "live" in ast.unparse(node.value):
            return True
    return False


def _decorated_live(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any("pytest.mark.live" in ast.unparse(d) for d in node.decorator_list)


def _collect() -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """Return (all test functions, live-marked test functions) as (relpath, name)."""
    every: set[tuple[str, str]] = set()
    live: set[tuple[str, str]] = set()
    for path in sorted(TESTS_ROOT.rglob("test_*.py")):
        relative = path.relative_to(PATHS.root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module_live = _module_is_live_marked(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if not node.name.startswith("test_"):
                continue
            every.add((relative, node.name))
            if module_live or _decorated_live(node):
                live.add((relative, node.name))
    return every, live


def test_every_test_under_tests_live_carries_the_live_marker() -> None:
    every, live = _collect()
    in_directory = {item for item in every if item[0].startswith("tests/live/")}
    unmarked = in_directory - live
    assert unmarked == set(), (
        f"{len(unmarked)} test(s) under tests/live/ are not marked live and would "
        f"therefore run inside the deterministic gate: {sorted(unmarked)}"
    )
    assert in_directory, "tests/live/ collected no tests at all"


def test_the_live_marked_tests_outside_tests_live_are_exactly_enumerated() -> None:
    """The marker count and the tests/live/ file count are not the same number.

    This is the discrepancy that produced the '46 live tests' claim: 46 is the count of
    tests in ``tests/live/``, while 47 is the count carrying the ``live`` marker.
    """
    _, live = _collect()
    outside = {item for item in live if not item[0].startswith("tests/live/")}
    assert outside == LIVE_MARKED_OUTSIDE_TESTS_LIVE, (
        "the set of live-marked tests outside tests/live/ changed. Update "
        "LIVE_MARKED_OUTSIDE_TESTS_LIVE and any document that quotes a live test "
        f"count. Found: {sorted(outside)}"
    )


def test_the_default_pytest_invocation_deselects_every_live_test() -> None:
    """``make gate`` runs a bare ``pytest``; it must never open a socket."""
    config = tomllib.loads((PATHS.root / "pyproject.toml").read_text(encoding="utf-8"))
    addopts = config["tool"]["pytest"]["ini_options"]["addopts"]
    assert '-m "not live"' in addopts, (
        "pyproject.toml no longer deselects live tests by default, so the "
        f"deterministic gate would hit production endpoints. addopts = {addopts!r}"
    )


def test_the_live_marker_is_registered_so_strict_markers_accepts_it() -> None:
    config = tomllib.loads((PATHS.root / "pyproject.toml").read_text(encoding="utf-8"))
    markers = config["tool"]["pytest"]["ini_options"]["markers"]
    assert any(marker.startswith("live:") for marker in markers), markers


def test_the_collection_helper_sees_both_marker_styles() -> None:
    """Guards the AST walk itself: module-level pytestmark and per-test decorator."""
    every, live = _collect()
    # tests/live/ uses module-level `pytestmark = pytest.mark.live`.
    assert ("tests/live/test_live_hud.py", "test_the_token_authenticates") in live
    # tests/integration/ uses a per-function decorator.
    assert next(iter(LIVE_MARKED_OUTSIDE_TESTS_LIVE)) in live
    # And an ordinary deterministic test is not marked.
    assert ("tests/unit/test_suite_composition.py", "test_the_collection_helper_sees_"
            "both_marker_styles") in every - live
