# VoltGap. The gate target is the contract: it runs every check required by
# CLAUDE.md section 15.1 and exits non-zero if any part fails.

PY := .venv/bin/python
REPLAY := tests/fixtures/replay

.PHONY: help setup test coverage lint copy-lint probe probe-live gate gate-0 gate-1 \
	build build-fixture determinism determinism-1 clean

help:
	@echo "setup       create the venv and install dependencies"
	@echo "test        run the full test suite"
	@echo "coverage    run tests with coverage thresholds enforced"
	@echo "lint        ruff + mypy strict"
	@echo "probe       replay the committed fixtures (offline, deterministic)"
	@echo "probe-live  refresh data/cache from the live sources"
	@echo "copy-lint   D3 / UI terminology guard (CLAUDE.md 11.5)"
	@echo "build       rebuild every canonical table (national)"
	@echo "build-fixture  rebuild the MN + IL two-state fixture"
	@echo "gate        full phase gate: make gate PHASE=n"

setup:
	uv venv --python 3.12
	uv pip install -e ".[dev]"

test:
	$(PY) -m pytest

coverage:
	@# G-B. One instrumented test run, then per-module thresholds read from the same
	@# coverage data. Running pytest once per threshold would multiply a multi-minute
	@# suite by the number of tiers for no additional signal.
	@# 100% line AND branch on result-computing code; 85% on sources/transform;
	@# 70% repository wide. pipeline/model and pipeline/validation do not exist yet;
	@# their 100% requirement first binds in the phase that creates them.
	$(PY) -m pytest -q --cov=pipeline --cov-branch --cov-report=
	@echo "--- repository wide (>= 70%) ---"
	@$(PY) -m coverage report --fail-under=70 | tail -3
	@echo "--- pipeline/discovery (= 100%) ---"
	@$(PY) -m coverage report --include="pipeline/discovery/*" --fail-under=100 | tail -2
	@echo "--- pipeline/spatial (= 100%) ---"
	@$(PY) -m coverage report --include="pipeline/spatial/*" --fail-under=100 | tail -2
	@echo "--- pipeline/quality (= 100%) ---"
	@$(PY) -m coverage report --include="pipeline/quality/*" --fail-under=100 | tail -2
	@echo "--- pipeline/schemas (= 100%) ---"
	@$(PY) -m coverage report --include="pipeline/schemas/*" --fail-under=100 | tail -2
	@echo "--- pipeline/sources (>= 85%) ---"
	@$(PY) -m coverage report --include="pipeline/sources/*" --fail-under=85 | tail -2
	@echo "--- pipeline/transform (>= 85%) ---"
	@$(PY) -m coverage report --include="pipeline/transform/*" --fail-under=85 | tail -2

lint:
	$(PY) -m ruff check .
	$(PY) -m mypy

copy-lint:
	$(PY) -m pipeline.quality.copy_lint

build:
	$(PY) -m pipeline.build --national

build-fixture:
	$(PY) -m pipeline.build --fixture --offline

probe:
	$(PY) -m pipeline.discovery.probe --offline --cache-root $(REPLAY)

probe-live:
	$(PY) -m pipeline.discovery.probe --live

# Determinism: two offline probe runs must produce byte-identical output.
determinism:
	@$(PY) -m pipeline.discovery.probe --offline --cache-root $(REPLAY) \
		--out /tmp/voltgap_det_a.json > /dev/null
	@$(PY) -m pipeline.discovery.probe --offline --cache-root $(REPLAY) \
		--out /tmp/voltgap_det_b.json > /dev/null
	@cmp /tmp/voltgap_det_a.json /tmp/voltgap_det_b.json \
		&& echo "determinism: identical" \
		|| (echo "determinism: OUTPUT DIFFERS" && exit 1)
	@rm -f /tmp/voltgap_det_a.json /tmp/voltgap_det_b.json

gate:
	@$(MAKE) --no-print-directory gate-$(PHASE)

# Phase 0 gate. Runs, in order:
#   1. lint            ruff + mypy strict
#   2. full test suite
#   3. coverage thresholds
#   4. prior gate suites  (none: Phase 0 is the first phase)
#   5. smoke-forward test for Phase 1, offline against real Phase 0 output
#   6. D3 / UI copy lint  (created in Phase 1 per spec amendment A9; not applicable
#                          in Phase 0 because the lint does not exist yet)
#   7. determinism check
gate-0:
	@echo "=== Phase 0 gate ==="
	@echo "--- 1. lint (ruff + mypy strict) ---"
	@$(MAKE) --no-print-directory lint
	@echo "--- 2. full test suite ---"
	@$(PY) -m pytest
	@echo "--- 3. coverage thresholds ---"
	@$(MAKE) --no-print-directory coverage
	@echo "--- 4. prior gate suites: none, Phase 0 is the first phase ---"
	@echo "--- 5. smoke-forward test for Phase 1 ---"
	@$(PY) -m pytest tests/integration/test_smoke_forward.py -v
	@echo "--- 6. D3 copy lint: created in Phase 1 (amendment A9); N/A in Phase 0 ---"
	@echo "--- 7. determinism ---"
	@$(MAKE) --no-print-directory determinism
	@echo "=== Phase 0 gate: PASS ==="

# Phase 1 gate. Runs, in order:
#   1. lint            ruff + mypy strict
#   2. full test suite
#   3. coverage thresholds (100% spatial/quality/discovery, 85% sources/transform,
#                           70% repository wide)
#   4. prior gate suites  (Phase 0: probe replay, contract validity, findings)
#   5. smoke-forward test for Phase 2, offline against real Phase 1 output
#   6. D3 / UI copy lint  (created this phase, amendment A9)
#   7. determinism        (semantic, per CLAUDE.md 14.1; replay reproducibility
#                          separated from live-refresh behaviour)
#   8. one-command rebuild from the canonical build entry point
gate-1:
	@echo "=== Phase 1 gate ==="
	@echo "--- 1. lint (ruff + mypy strict) ---"
	@$(MAKE) --no-print-directory lint
	@echo "--- 2. full test suite ---"
	@$(PY) -m pytest
	@echo "--- 3. coverage thresholds ---"
	@$(MAKE) --no-print-directory coverage
	@echo "--- 4. prior gate suite (Phase 0) ---"
	@$(PY) -m pytest tests/regression/test_source_findings.py \
		tests/integration/test_smoke_forward.py -q
	@$(MAKE) --no-print-directory determinism
	@echo "--- 5. smoke-forward test for Phase 2 ---"
	@$(PY) -m pytest tests/integration/test_smoke_forward_phase2.py -v
	@echo "--- 6. D3 copy lint ---"
	@$(MAKE) --no-print-directory copy-lint
	@echo "--- 7. determinism (semantic, CLAUDE.md 14.1) ---"
	@$(MAKE) --no-print-directory determinism-1
	@echo "--- 8. one-command rebuild ---"
	@$(MAKE) --no-print-directory build-fixture
	@echo "=== Phase 1 gate: PASS ==="

# Semantic determinism for the canonical build: two runs against pinned inputs with
# an injected fixed timestamp must produce the same semantic hash. Byte equality is
# impossible because every derived table carries computed_at (CLAUDE.md 14.1).
determinism-1:
	@$(PY) -m pytest tests/integration/test_determinism.py -q

clean:
	rm -rf data/cache data/interim data/warehouse artifacts
