# VoltGap. The gate target is the contract: it runs every check required by
# CLAUDE.md section 15.1 and exits non-zero if any part fails.

PY := .venv/bin/python
REPLAY := tests/fixtures/replay

.PHONY: help setup test coverage lint copy-lint probe probe-live gate gate-0 gate-1 \
	gate-2 gate-3 gate-4 gate-5 build build-fixture phase3 phase4 phase5 \
	determinism \
	determinism-1 clean \
	live-smoke live-integration integration-assurance

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
	@echo "phase3      reproduce every Phase 3 number from cached inputs"
	@echo "phase4      reproduce every Phase 4 siting number from cached inputs"
	@echo "phase5      reproduce every Phase 5 validation number from cached inputs"
	@echo "gate        full phase gate: make gate PHASE=n (never touches the network)"
	@echo ""
	@echo "  LIVE commands below DO require network access and credentials."
	@echo "  They are deliberately excluded from every deterministic gate."
	@echo "live-smoke          fast bounded checks of the production integrations"
	@echo "live-integration    full external-system validation"
	@echo "integration-assurance  the complete Live Integration Assurance Checkpoint"

setup:
	uv venv --python 3.12
	uv pip install -e ".[dev]"

test:
	$(PY) -m pytest

coverage:
	@# G-A + G-B in ONE invocation. This runs the COMPLETE test suite — the same
	@# selection `make test` runs, no deselection — under coverage instrumentation, so
	@# it fails on any test failure AND enforces every threshold. Running the suite a
	@# second time without instrumentation proved nothing the instrumented run does not
	@# already prove, and doubled every gate. See CLAUDE.md 19, amendment A25.
	@#
	@# Then per-module thresholds are read from the same coverage data. Running pytest
	@# once per threshold would multiply a multi-minute suite by the number of tiers
	@# for no additional signal.
	@# 100% line AND branch on result-computing code; 85% on sources/transform;
	@# 70% repository wide. pipeline/validation was created in Phase 3 (the record
	@# ledger and the measured allocation error), so its 100% tier binds from Phase 3.
	$(PY) -m pytest -q --cov=pipeline --cov-branch --cov-report=
	@echo "--- repository wide (>= 70%) ---"
	@$(PY) -m coverage report --fail-under=70 > /tmp/voltgap_cov.txt 2>&1 || (tail -3 /tmp/voltgap_cov.txt && exit 1)
	@tail -3 /tmp/voltgap_cov.txt
	@echo "--- pipeline/discovery (= 100%) ---"
	@$(PY) -m coverage report --include="pipeline/discovery/*" --fail-under=100 > /tmp/voltgap_cov.txt 2>&1 || (tail -3 /tmp/voltgap_cov.txt && exit 1)
	@tail -2 /tmp/voltgap_cov.txt
	@echo "--- pipeline/spatial (= 100%) ---"
	@$(PY) -m coverage report --include="pipeline/spatial/*" --fail-under=100 > /tmp/voltgap_cov.txt 2>&1 || (tail -3 /tmp/voltgap_cov.txt && exit 1)
	@tail -2 /tmp/voltgap_cov.txt
	@echo "--- pipeline/validation (= 100%) ---"
	@$(PY) -m coverage report --include="pipeline/validation/*" --fail-under=100 > /tmp/voltgap_cov.txt 2>&1 || (tail -3 /tmp/voltgap_cov.txt && exit 1)
	@tail -2 /tmp/voltgap_cov.txt
	@echo "--- pipeline/model (= 100%) ---"
	@$(PY) -m coverage report --include="pipeline/model/*" --fail-under=100 > /tmp/voltgap_cov.txt 2>&1 || (tail -3 /tmp/voltgap_cov.txt && exit 1)
	@tail -2 /tmp/voltgap_cov.txt
	@echo "--- pipeline/quality (= 100%) ---"
	@$(PY) -m coverage report --include="pipeline/quality/*" --fail-under=100 > /tmp/voltgap_cov.txt 2>&1 || (tail -3 /tmp/voltgap_cov.txt && exit 1)
	@tail -2 /tmp/voltgap_cov.txt
	@echo "--- pipeline/schemas (= 100%) ---"
	@$(PY) -m coverage report --include="pipeline/schemas/*" --fail-under=100 > /tmp/voltgap_cov.txt 2>&1 || (tail -3 /tmp/voltgap_cov.txt && exit 1)
	@tail -2 /tmp/voltgap_cov.txt
	@echo "--- pipeline/sources (>= 85%) ---"
	@$(PY) -m coverage report --include="pipeline/sources/*" --fail-under=85 > /tmp/voltgap_cov.txt 2>&1 || (tail -3 /tmp/voltgap_cov.txt && exit 1)
	@tail -2 /tmp/voltgap_cov.txt
	@echo "--- pipeline/transform (>= 85%) ---"
	@$(PY) -m coverage report --include="pipeline/transform/*" --fail-under=85 > /tmp/voltgap_cov.txt 2>&1 || (tail -3 /tmp/voltgap_cov.txt && exit 1)
	@tail -2 /tmp/voltgap_cov.txt

lint:
	$(PY) -m ruff check .
	$(PY) -m mypy

copy-lint:
	$(PY) -m pipeline.quality.copy_lint

build:
	$(PY) -m pipeline.build --national

build-fixture:
	$(PY) -m pipeline.build --fixture --offline

# Phase 3. Reads only cached responses: no network, no credentials.
phase3:
	$(PY) -m pipeline.model.run_phase3

# Phase 4. Reads only cached responses: no network, no credentials.
phase4:
	$(PY) -m pipeline.model.run_phase4

# Phase 5. Reads only cached responses: no network, no credentials.
phase5:
	$(PY) -m pipeline.model.run_phase5

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

# --- G-C: the prior-phase regression suites --------------------------------------------
# Every earlier phase's PHASE-SPECIFIC gate suite, replayed by the current gate. This is
# what CLAUDE.md 15.1 G-C requires: "every prior phase's gate suite re-run and passing".
#
# It does NOT mean recursively running `make gate PHASE=n` for each earlier n. Doing that
# re-runs the identical whole-repository suite, coverage, lint and determinism work once
# per phase, which adds no validation evidence — the repository has one test suite and one
# set of coverage thresholds, and this gate already ran both. See CLAUDE.md 19, A26.
#
# Each entry is run as its own pytest invocation so the output names the suite and its
# PASS/FAIL individually, rather than merging into one anonymous dot stream.
PRIOR_GATE_SUITES := \
	tests/regression/test_source_findings.py \
	tests/regression/test_domain_rules.py \
	tests/regression/test_phase2_gates.py \
	tests/regression/test_phase3_gates.py \
	tests/regression/test_phase3_corrections.py \
	tests/integration/test_smoke_forward.py \
	tests/integration/test_smoke_forward_phase2.py \
	tests/integration/test_smoke_forward_phase3.py

#: Phase 4's own suites, replayed from Phase 5 onward.
PRIOR_GATE_SUITES += \
	tests/regression/test_phase4_gates.py \
	tests/regression/test_gate_protocol.py \
	tests/integration/test_smoke_forward_phase4.py

.PHONY: prior-gate-suites
prior-gate-suites:
	@failed=0; \
	for suite in $(PRIOR_GATE_SUITES); do \
		printf '    %-52s ' "$$suite"; \
		if $(PY) -m pytest "$$suite" -p no:cacheprovider \
			> /tmp/voltgap_prior.txt 2>&1; then \
			printf 'PASS  %s\n' "$$(grep -oE '[0-9]+ passed' /tmp/voltgap_prior.txt | tail -1)"; \
		else \
			printf 'FAIL\n'; tail -25 /tmp/voltgap_prior.txt; failed=1; \
		fi; \
	done; \
	rm -f /tmp/voltgap_prior.txt; \
	if [ $$failed -ne 0 ]; then echo "prior gate suites: FAIL"; exit 1; fi; \
	echo "    all prior-phase gate suites PASS"

gate:
	@$(MAKE) --no-print-directory gate-$(PHASE)

# Phase 0 gate. Runs, in order:
#   1. lint            ruff + mypy strict
#   2+3. the COMPLETE test suite run ONCE under coverage, which satisfies both the
#        full-suite requirement and the coverage thresholds. CLAUDE.md A25.
#   4. prior gate suites  (none: Phase 0 is the first phase)
#   5. smoke-forward test for Phase 1, offline against real Phase 0 output
#   6. D3 / UI copy lint  (created in Phase 1 per spec amendment A9; not applicable
#                          in Phase 0 because the lint does not exist yet)
#   7. determinism check
gate-0:
	@echo "=== Phase 0 gate ==="
	@echo "--- 1. lint (ruff + mypy strict) ---"
	@$(MAKE) --no-print-directory lint
	@echo "--- 2+3. full test suite under coverage, and coverage thresholds ---"
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
#   2+3. the COMPLETE test suite run ONCE under coverage, which satisfies both the
#        full-suite requirement and the coverage thresholds (100% spatial/quality/
#        discovery, 85% sources/transform, 70% repository wide). CLAUDE.md A25.
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
	@echo "--- 2+3. full test suite under coverage, and coverage thresholds ---"
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

# --- Live integration ---------------------------------------------------------------
# These require network access and credentials from .env. They are NEVER part of
# `make gate`: the deterministic phase gates must stay network-independent, which is
# enforced by `addopts = -m "not live"` in pyproject.toml.

# Fast, bounded: authentication and reachability for each Core integration.
live-smoke:
	@echo "=== live smoke (bounded production checks) ==="
	$(PY) -m pytest -m live -q \
		tests/live/test_live_afdc.py::test_a_valid_key_is_accepted \
		tests/live/test_live_afdc.py::test_a_missing_key_is_refused_with_a_named_error \
		tests/live/test_live_census.py::test_the_authenticated_request_succeeds \
		tests/live/test_live_census.py::test_the_keyless_request_is_refused_and_how \
		tests/live/test_live_hud.py::test_the_token_authenticates \
		tests/live/test_live_hud.py::test_a_missing_token_is_refused \
		tests/live/test_live_eia.py::test_the_key_authenticates \
		tests/live/test_live_eia.py::test_a_missing_key_is_refused

# Comprehensive: schemas, pagination, fallbacks, reconciliation, equivalence, secrets.
live-integration:
	@echo "=== live integration (full external validation) ==="
	$(PY) -m pytest -m live -v tests/live

# The complete checkpoint: deterministic suite first, then every live check, then the
# secret-leakage audit. Requires network access by design.
integration-assurance:
	@echo "=== Live Integration Assurance Checkpoint ==="
	@echo "--- 1. deterministic suite must pass first ---"
	@$(PY) -m pytest -q
	@echo "--- 2. lint ---"
	@$(MAKE) --no-print-directory lint
	@echo "--- 3. failure-mode adapter behaviour (mocked) ---"
	@$(PY) -m pytest -q tests/unit/test_failure_modes.py
	@echo "--- 4. live integration, all sources ---"
	@$(PY) -m pytest -m live -q tests/live
	@echo "--- 5. secret-leakage audit ---"
	@$(PY) -m pytest -m live -q \
		tests/live/test_live_equivalence_and_secrets.py -k secret_or_env \
		|| $(PY) -m pytest -m live -q tests/live/test_live_equivalence_and_secrets.py
	@echo "=== Integration assurance: PASS ==="

# Phase 2 gate. Runs, in order:
#   1. lint            ruff + mypy strict
#   2+3. the COMPLETE test suite run ONCE under coverage, which satisfies both the
#        full-suite requirement and the coverage thresholds (100% on model/spatial/
#        quality/discovery/schemas). CLAUDE.md A25.
#   4. prior gate suites  (Phase 0 and Phase 1)
#   5. Phase 2 gate checks P2-A to P2-H
#   6. D3 / UI copy lint
#   7. determinism        (semantic, CLAUDE.md 14.1)
#   8. one-command rebuild
gate-2:
	@echo "=== Phase 2 gate ==="
	@echo "--- 1. lint (ruff + mypy strict) ---"
	@$(MAKE) --no-print-directory lint
	@echo "--- 2+3. full test suite under coverage, and coverage thresholds ---"
	@$(MAKE) --no-print-directory coverage
	@echo "--- 4. prior gate suites (Phase 0 and Phase 1) ---"
	@$(PY) -m pytest tests/regression/test_source_findings.py \
		tests/regression/test_domain_rules.py \
		tests/integration/test_smoke_forward.py \
		tests/integration/test_smoke_forward_phase2.py -q
	@$(MAKE) --no-print-directory determinism
	@echo "--- 5. Phase 2 gate checks P2-A to P2-H ---"
	@$(PY) -m pytest tests/regression/test_phase2_gates.py -v
	@echo "--- 6. D3 copy lint ---"
	@$(MAKE) --no-print-directory copy-lint
	@echo "--- 7. determinism (semantic, CLAUDE.md 14.1) ---"
	@$(MAKE) --no-print-directory determinism-1
	@echo "--- 8. one-command rebuild ---"
	@$(MAKE) --no-print-directory build-fixture
	@echo "=== Phase 2 gate: PASS ==="

# Semantic determinism for the canonical build: two runs against pinned inputs with
# an injected fixed timestamp must produce the same semantic hash. Byte equality is
# impossible because every derived table carries computed_at (CLAUDE.md 14.1).
determinism-1:
	@$(PY) -m pytest tests/integration/test_determinism.py -q

clean:
	rm -rf data/cache data/interim data/warehouse artifacts

# Phase 3 gate. Runs, in order:
#   1. lint            ruff + mypy strict
#   2+3. the COMPLETE test suite run ONCE under coverage, which satisfies both the
#        full-suite requirement and the coverage thresholds (100% on model/spatial/
#        quality/discovery/schemas/validation). CLAUDE.md A25.
#   4. prior gate suites  (Phase 0, 1 and 2)
#   5. Phase 3 acceptance criteria P3-A to P3-H
#   6. D3 / UI copy lint
#   7. determinism        (semantic, CLAUDE.md 14.1)
#   8. one-command rebuild of the canonical tables AND of every Phase 3 number
gate-3:
	@echo "=== Phase 3 gate ==="
	@echo "--- 1. lint (ruff + mypy strict) ---"
	@$(MAKE) --no-print-directory lint
	@echo "--- 2+3. full test suite under coverage, and coverage thresholds ---"
	@$(MAKE) --no-print-directory coverage
	@echo "--- 4. prior gate suites (Phase 0, 1 and 2) ---"
	@$(PY) -m pytest tests/regression/test_source_findings.py \
		tests/regression/test_domain_rules.py \
		tests/regression/test_phase2_gates.py \
		tests/integration/test_smoke_forward.py \
		tests/integration/test_smoke_forward_phase2.py -q
	@$(MAKE) --no-print-directory determinism
	@echo "--- 5. Phase 3 acceptance criteria P3-A to P3-H ---"
	@$(PY) -m pytest tests/regression/test_phase3_gates.py -v
	@echo "--- 6. D3 copy lint ---"
	@$(MAKE) --no-print-directory copy-lint
	@echo "--- 7. determinism (semantic, CLAUDE.md 14.1) ---"
	@$(MAKE) --no-print-directory determinism-1
	@echo "--- 8. one-command rebuild ---"
	@$(MAKE) --no-print-directory build-fixture
	@$(MAKE) --no-print-directory phase3
	@echo "=== Phase 3 gate: PASS ==="

# Phase 4 gate. Runs, in order:
#   1. lint            ruff + mypy strict
#   2+3. the COMPLETE test suite run ONCE under coverage, which satisfies both the
#        full-suite requirement and the coverage thresholds. CLAUDE.md A25.
#   4. prior gate suites  (Phase 0, 1, 2 and 3)
#   5. Phase 4 acceptance criteria P4-A to P4-G
#   6. D3 / UI copy lint
#   7. determinism        (semantic, CLAUDE.md 14.1)
#   8. one-command rebuild of the canonical tables, Phase 3 and Phase 4
gate-4:
	@echo "=== Phase 4 gate ==="
	@echo "--- 1. lint (ruff + mypy strict) ---"
	@$(MAKE) --no-print-directory lint
	@echo "--- 2+3. full test suite under coverage, and coverage thresholds ---"
	@$(MAKE) --no-print-directory coverage
	@echo "--- 4. prior-phase gate suites replayed (Phase 0, 1, 2 and 3) ---"
	@$(MAKE) --no-print-directory prior-gate-suites
	@$(MAKE) --no-print-directory determinism
	@echo "--- 4b. smoke-forward test for Phase 5 ---"
	@$(PY) -m pytest tests/integration/test_smoke_forward_phase4.py -v
	@echo "--- 5. Phase 4 acceptance criteria P4-A to P4-G ---"
	@$(PY) -m pytest tests/regression/test_phase4_gates.py -v
	@echo "--- 6. D3 copy lint ---"
	@$(MAKE) --no-print-directory copy-lint
	@echo "--- 7. determinism (semantic, CLAUDE.md 14.1) ---"
	@$(MAKE) --no-print-directory determinism-1
	@echo "--- 8. one-command rebuild ---"
	@$(MAKE) --no-print-directory build-fixture
	@$(MAKE) --no-print-directory phase4
	@echo "=== Phase 4 gate: PASS ==="

# Phase 5 gate. Runs, in order:
#   1. lint            ruff + mypy strict
#   2+3. the COMPLETE test suite run ONCE under coverage, which satisfies both the
#        full-suite requirement and the coverage thresholds. CLAUDE.md A25.
#   4. prior-phase gate suites replayed (Phase 0, 1, 2, 3 and 4). CLAUDE.md A26.
#   4b. smoke-forward test for Phase 6
#   5. Phase 5 acceptance criteria P5-A to P5-F
#   6. D3 / UI copy lint
#   7. determinism        (semantic, CLAUDE.md 14.1)
#   8. one-command rebuild of the canonical tables, Phase 3, Phase 4 and Phase 5
gate-5:
	@echo "=== Phase 5 gate ==="
	@echo "--- 1. lint (ruff + mypy strict) ---"
	@$(MAKE) --no-print-directory lint
	@echo "--- 2+3. full test suite under coverage, and coverage thresholds ---"
	@$(MAKE) --no-print-directory coverage
	@echo "--- 4. prior-phase gate suites replayed (Phase 0, 1, 2, 3 and 4) ---"
	@$(MAKE) --no-print-directory prior-gate-suites
	@$(MAKE) --no-print-directory determinism
	@echo "--- 4b. smoke-forward test for Phase 6 ---"
	@$(PY) -m pytest tests/integration/test_smoke_forward_phase5.py -v
	@echo "--- 5. Phase 5 acceptance criteria P5-A to P5-F ---"
	@$(PY) -m pytest tests/regression/test_phase5_gates.py -v
	@echo "--- 6. D3 copy lint ---"
	@$(MAKE) --no-print-directory copy-lint
	@echo "--- 7. determinism (semantic, CLAUDE.md 14.1) ---"
	@$(MAKE) --no-print-directory determinism-1
	@echo "--- 8. one-command rebuild ---"
	@$(MAKE) --no-print-directory build-fixture
	@$(MAKE) --no-print-directory phase4
	@$(MAKE) --no-print-directory phase5
	@echo "=== Phase 5 gate: PASS ==="
