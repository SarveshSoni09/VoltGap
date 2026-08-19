"""Typed settings for the VoltGap pipeline.

CLAUDE.md section 2 forbids magic numbers outside this package. Every path, every
environment variable name, and every Phase 0 tuning constant is declared here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Repository root: this file is <root>/pipeline/config/settings.py
REPO_ROOT: Path = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Paths:
    """Filesystem locations. All are absolute and derived from REPO_ROOT."""

    root: Path = REPO_ROOT
    seed: Path = REPO_ROOT / "data" / "seed"
    cache: Path = REPO_ROOT / "data" / "cache"
    replay_fixtures: Path = REPO_ROOT / "tests" / "fixtures" / "replay"
    evidence: Path = REPO_ROOT / "docs" / "evidence"
    contract: Path = REPO_ROOT / "SOURCES.yml"
    observations: Path = REPO_ROOT / "SOURCES.observed.json"
    seed_inventory_json: Path = REPO_ROOT / "data" / "seed" / "seed_inventory.json"
    seed_inventory_md: Path = REPO_ROOT / "data" / "seed" / "SEED_INVENTORY.md"


@dataclass(frozen=True)
class ProbeSettings:
    """Phase 0 probe behaviour.

    ``default_drift_tolerance`` implements the provisional +/-20% expected row-count
    band agreed for previously unseen sources. Per-source tolerances declared in
    SOURCES.yml override it; see CLAUDE.md section 4.1 quality.expected_row_count.
    """

    default_drift_tolerance: float = 0.20
    http_timeout_s: float = 60.0
    max_retries: int = 3
    retry_backoff_s: float = 2.0
    # Sample size for REST schema discovery. Bounded per CLAUDE.md 4.2 task 1
    # ("fetch a bounded sample"); large enough that per-field missingness is stable.
    rest_sample_limit: int = 200
    # Number of back-to-back requests used to measure rate-limit headers empirically.
    rate_limit_probe_requests: int = 3
    # Bytes read from a large local file when only the header/first records are needed.
    stream_chunk_bytes: int = 1 << 20


@dataclass(frozen=True)
class ApiKeys:
    """Free-tier API keys, read from the environment only.

    Never persisted, never defaulted to a real value. ``DEMO_KEY`` is NREL/NLR's
    published shared demo credential and is used only when no key is supplied.
    """

    nrel: str = field(default_factory=lambda: os.environ.get("NREL_API_KEY", "") or "DEMO_KEY")
    census: str = field(default_factory=lambda: os.environ.get("CENSUS_API_KEY", ""))
    eia: str = field(default_factory=lambda: os.environ.get("EIA_API_KEY", ""))

    @property
    def nrel_is_demo(self) -> bool:
        return self.nrel == "DEMO_KEY"


PATHS = Paths()
PROBE = ProbeSettings()


def api_keys() -> ApiKeys:
    """Read API keys from the environment at call time (not import time)."""
    return ApiKeys()
