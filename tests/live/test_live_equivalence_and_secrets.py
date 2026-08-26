"""Live-to-replay semantic equivalence, and the secret-leakage audit.

**Equivalence** proves the deterministic gate exercises the same parser behaviour as
production: a live response is fetched, parsed, recorded through the normal cache, then
replayed offline, and the two parses must agree. Without this, 100% coverage could be
100% coverage of a parser that never sees a real payload.

**Leakage** scans repository files, caches, evidence and reports for the configured
secret values, held in memory only. It reports PASS or the offending path, never the
value.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.config.settings import PATHS, ApiKeys
from pipeline.discovery.cache import LiveFetcher, ReplayFetcher
from pipeline.discovery.measure import measure_delimited, measure_json_records
from tests.live.conftest import (
    AFDC_BASE,
    CENSUS_ACS,
    EIA_RETAIL,
    HUD_USPS,
    SMALL_STATE,
    TEST_TRACT,
    TEST_ZIP,
    require,
)

pytestmark = pytest.mark.live


def round_trip(
    tmp_path: Path, source_id: str, url: str, params: dict[str, str],
    headers: dict[str, str] | None = None,
) -> tuple[bytes, bytes]:
    """Fetch live through the cache, then replay, returning both payloads."""
    live = LiveFetcher(tmp_path).get(source_id, url, params, headers or {})
    replayed = ReplayFetcher(tmp_path).get(source_id, url, params, headers or {})
    return live.content, replayed.content


def test_afdc_live_parse_equals_replay_parse(tmp_path: Path, keys: ApiKeys) -> None:
    require(not keys.nrel_is_demo, "NREL_API_KEY")
    live, replayed = round_trip(
        tmp_path, "afdc_stations", f"{AFDC_BASE}.json",
        {"fuel_type": "ELEC", "state": SMALL_STATE, "limit": "25",
         "api_key": keys.nrel})
    a = measure_json_records(live, ("fuel_stations",))
    b = measure_json_records(replayed, ("fuel_stations",))
    assert a.row_count == b.row_count > 0
    assert a.fields == b.fields
    assert a.schema_hash == b.schema_hash


def test_census_live_parse_equals_replay_parse(tmp_path: Path, keys: ApiKeys) -> None:
    require(bool(keys.census), "CENSUS_API_KEY")
    live, replayed = round_trip(
        tmp_path, "census_acs_api", CENSUS_ACS,
        {"get": "NAME,B25003_001E", "for": f"tract:{TEST_TRACT['tract']}",
         "in": f"state:{TEST_TRACT['state']} county:{TEST_TRACT['county']}",
         "key": keys.census})
    assert json.loads(live) == json.loads(replayed)


def test_hud_live_parse_equals_replay_parse(tmp_path: Path, keys: ApiKeys) -> None:
    require(bool(keys.hud), "HUD_USER_TOKEN")
    live, replayed = round_trip(
        tmp_path, "hud_usps_zip_tract", HUD_USPS, {"type": "1", "query": TEST_ZIP},
        {"Authorization": f"Bearer {keys.hud}"})
    a = json.loads(live)["data"]["results"]
    b = json.loads(replayed)["data"]["results"]
    assert a == b and a


def test_eia_live_parse_equals_replay_parse(tmp_path: Path, keys: ApiKeys) -> None:
    require(bool(keys.eia), "EIA_API_KEY")
    live, replayed = round_trip(
        tmp_path, "eia_prices_api", EIA_RETAIL,
        {"frequency": "monthly", "data[0]": "price", "facets[stateid][]": "WA",
         "facets[sectorid][]": "COM", "start": "2024-01", "end": "2024-02",
         "api_key": keys.eia})
    assert json.loads(live)["response"]["data"] == json.loads(replayed)["response"]["data"]


def test_a_csv_source_round_trips_identically(tmp_path: Path, keys: ApiKeys) -> None:
    require(not keys.nrel_is_demo, "NREL_API_KEY")
    live, replayed = round_trip(
        tmp_path, "afdc_charging_units_csv_fallback",
        f"{AFDC_BASE}/ev-charging-units.csv",
        {"fuel_type": "ELEC", "state": SMALL_STATE, "limit": "all",
         "api_key": keys.nrel})
    a, b = measure_delimited(live), measure_delimited(replayed)
    assert a.row_count == b.row_count > 0
    assert a.schema_hash == b.schema_hash


# --- secret-leakage audit -----------------------------------------------------------------

SCAN_ROOTS = ("SOURCES.yml", "SOURCES.observed.json", "docs", "tests/fixtures",
              "data/cache", "pipeline", "Makefile", ".env.example")
SKIP_SUFFIXES = {".body", ".pyc"}


def scan_for(values: tuple[str, ...], root: Path) -> list[str]:
    """Return offending paths. Never returns or logs the matched value itself."""
    offenders: list[str] = []
    for name in SCAN_ROOTS:
        target = root / name
        candidates = ([target] if target.is_file()
                      else sorted(target.rglob("*")) if target.is_dir() else [])
        for path in candidates:
            if not path.is_file() or path.suffix in SKIP_SUFFIXES:
                continue
            try:
                text = path.read_text(errors="replace")
            except OSError:  # pragma: no cover - unreadable file
                continue
            if any(secret in text for secret in values):
                offenders.append(str(path.relative_to(root)))
    return offenders


def test_no_configured_secret_appears_in_any_tracked_or_generated_artifact(
    keys: ApiKeys,
) -> None:
    secrets = keys.secret_values()
    assert secrets, "no credentials configured; the scan would be vacuous"
    offenders = scan_for(secrets, PATHS.root)
    assert offenders == [], f"secret leakage scan: FAIL in {offenders}"


def test_response_bodies_are_scanned_too(keys: ApiKeys) -> None:
    """Cached response bodies are excluded above by suffix; check them explicitly."""
    secrets = keys.secret_values()
    offenders: list[str] = []
    for path in sorted((PATHS.root / "tests" / "fixtures").rglob("*.body")):
        if any(s in path.read_text(errors="replace") for s in secrets):
            offenders.append(str(path.relative_to(PATHS.root)))
    assert offenders == [], f"secret leakage scan: FAIL in {offenders}"


def test_dotenv_is_git_ignored_and_untracked() -> None:
    import subprocess

    ignored = subprocess.run(["git", "check-ignore", ".env"], cwd=PATHS.root,
                             capture_output=True, text=True)
    assert ignored.returncode == 0, ".env must be git-ignored"
    tracked = subprocess.run(["git", "ls-files", ".env"], cwd=PATHS.root,
                             capture_output=True, text=True).stdout.strip()
    assert tracked == "", ".env must never be tracked"


def test_the_example_env_contains_no_values() -> None:
    text = (PATHS.root / ".env.example").read_text(encoding="utf-8")
    assignments = [line for line in text.splitlines()
                   if "=" in line and not line.strip().startswith("#")]
    filled = [line.split("=", 1)[0] for line in assignments if line.split("=", 1)[1].strip()]
    assert filled == [], f"{filled} carry a value; .env.example must hold placeholders only"
