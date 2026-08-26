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


def load_dotenv(path: Path | None = None) -> dict[str, str]:
    """Read ``.env`` into a dict WITHOUT mutating os.environ or logging anything.

    Values are returned to the caller and never printed, cached or serialised. The
    file itself is git-ignored; a missing file is normal and yields an empty mapping.
    """
    source = path if path is not None else REPO_ROOT / ".env"
    values: dict[str, str] = {}
    if not source.exists():
        return values
    for line in source.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, raw = stripped.split("=", 1)
        values[name.strip()] = raw.strip().strip('"').strip("'")
    return values


def _credential(name: str, default: str = "") -> str:
    """Environment first, then .env. Never raises and never logs."""
    return os.environ.get(name) or load_dotenv().get(name, "") or default


@dataclass(frozen=True)
class ApiKeys:
    """Free-tier API credentials, read from the environment or .env only.

    Never persisted, never defaulted to a real value, never printed. ``DEMO_KEY`` is
    NREL/NLR's published shared demo credential and is used only when no key is
    supplied. Presence is reportable; the value never is.
    """

    nrel: str = field(default_factory=lambda: _credential("NREL_API_KEY", "DEMO_KEY"))
    census: str = field(default_factory=lambda: _credential("CENSUS_API_KEY"))
    eia: str = field(default_factory=lambda: _credential("EIA_API_KEY"))
    hud: str = field(default_factory=lambda: _credential("HUD_USER_TOKEN"))

    @property
    def nrel_is_demo(self) -> bool:
        return self.nrel == "DEMO_KEY"

    def presence(self) -> dict[str, bool]:
        """Which credentials are configured. Reports booleans, never values."""
        return {"NREL_API_KEY": not self.nrel_is_demo, "CENSUS_API_KEY": bool(self.census),
                "EIA_API_KEY": bool(self.eia), "HUD_USER_TOKEN": bool(self.hud)}

    def secret_values(self) -> tuple[str, ...]:
        """Every configured secret, for in-memory leak scanning ONLY.

        Callers must never print, log or persist the result. It exists so the leakage
        audit can search artifacts for these strings without a human ever seeing them.
        """
        return tuple(v for v in (self.nrel, self.census, self.eia, self.hud)
                     if v and v != "DEMO_KEY")


PATHS = Paths()
PROBE = ProbeSettings()


def api_keys() -> ApiKeys:
    """Read API keys from the environment at call time (not import time)."""
    return ApiKeys()
