# VoltGap. The gate target is the contract: it runs every check required by
# CLAUDE.md section 15.1 and exits non-zero if any part fails.

PY := .venv/bin/python
REPLAY := tests/fixtures/replay

.PHONY: help setup test coverage lint probe probe-live gate gate-0 build clean

help:
	@echo "setup       create the venv and install dependencies"
	@echo "test        run the full test suite"
	@echo "coverage    run tests with coverage thresholds enforced"
	@echo "lint        ruff + mypy strict"
	@echo "probe       replay the committed fixtures (offline, deterministic)"
	@echo "probe-live  refresh data/cache from the live sources"
	@echo "gate        full phase gate: make gate PHASE=n"

setup:
	uv venv --python 3.12
	uv pip install -e ".[dev]"

test:
	$(PY) -m pytest

coverage:
	@# G-B. 100% line AND branch on result-computing code; 70% repository wide.
	@# pipeline/model, pipeline/validation and pipeline/spatial do not exist yet;
	@# their 100% requirement first binds in the phase that creates them.
	$(PY) -m pytest --cov=pipeline --cov-branch \
		--cov-report=term-missing --cov-fail-under=70
	$(PY) -m pytest -q --cov=pipeline/discovery --cov-branch \
		--cov-report=term-missing --cov-fail-under=100
	$(PY) -m pytest -q --cov=pipeline/sources --cov-branch \
		--cov-report=term:skip-covered --cov-fail-under=85

lint:
	$(PY) -m ruff check .
	$(PY) -m mypy

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
#   6. UI copy lint    (not applicable: no UI exists before Phase 6)
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
	@echo "--- 6. UI copy lint: not applicable before Phase 6 ---"
	@echo "--- 7. determinism ---"
	@$(MAKE) --no-print-directory determinism
	@echo "=== Phase 0 gate: PASS ==="

build:
	@echo "TODO: implement in Phase 1"

clean:
	rm -rf data/cache data/interim data/warehouse artifacts
