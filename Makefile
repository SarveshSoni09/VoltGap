# Targets are stubs. Claude Code implements them in Phase 0 and extends them each phase.
# The gate target is the contract: it must run every check required by CLAUDE.md 15.1.

.PHONY: help setup test coverage lint gate build clean

help:
	@echo "setup     install dependencies"
	@echo "test      run the full test suite"
	@echo "coverage  run tests with coverage thresholds enforced"
	@echo "lint      ruff + mypy strict + UI copy lint"
	@echo "gate      full phase gate: make gate PHASE=n"
	@echo "build     run the pipeline end to end"

setup:
	@echo "TODO: implement in Phase 0"

test:
	@echo "TODO: implement in Phase 0"

coverage:
	@echo "TODO: implement in Phase 0"

lint:
	@echo "TODO: implement in Phase 0"

# Gate must execute, in order:
#   1. full test suite
#   2. coverage thresholds (100% on model/validation/spatial, 85% transform/sources, 70% total)
#   3. all prior phase gate suites (regression)
#   4. smoke-forward test for phase N+1
#   5. UI copy lint (where applicable)
#   6. determinism check (two runs, identical checksums)
# It must exit non-zero if any part fails.
gate:
	@echo "TODO: implement in Phase 0 for PHASE=$(PHASE)"

build:
	@echo "TODO: implement in Phase 1"

clean:
	rm -rf data/cache data/interim data/warehouse artifacts
