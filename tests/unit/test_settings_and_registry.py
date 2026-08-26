"""Unit tests for settings and the declarative probe registry."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from pipeline.config.settings import PATHS, PROBE, ApiKeys, api_keys
from pipeline.discovery.registry import AFDC_REGISTRATION_YEARS, ATLAS_STATES, all_specs


def test_paths_are_absolute_and_rooted_at_the_repository() -> None:
    assert PATHS.contract.name == "SOURCES.yml"
    assert PATHS.observations.name == "SOURCES.observed.json"
    assert PATHS.seed.is_absolute()
    assert PATHS.seed.parent.parent == PATHS.root


def test_probe_defaults_match_the_agreed_provisional_tolerance() -> None:
    assert PROBE.default_drift_tolerance == 0.20


def test_api_keys_read_the_environment_at_call_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolated from any real .env, so the test asserts environment behaviour only."""
    monkeypatch.setattr("pipeline.config.settings.load_dotenv", lambda *a, **k: {})
    monkeypatch.delenv("NREL_API_KEY", raising=False)
    monkeypatch.setenv("EIA_API_KEY", "e")
    keys = api_keys()
    assert keys.nrel == "DEMO_KEY"
    assert keys.nrel_is_demo is True
    assert keys.eia == "e"

    monkeypatch.setenv("NREL_API_KEY", "personal")
    assert api_keys().nrel_is_demo is False


def test_dotenv_supplies_a_credential_when_the_environment_does_not(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from pipeline.config.settings import load_dotenv

    env_file = tmp_path / ".env"
    env_file.write_text('NREL_API_KEY="from-dotenv"\n# comment\nEMPTY=\n',
                        encoding="utf-8")
    values = load_dotenv(env_file)
    assert values["NREL_API_KEY"] == "from-dotenv", "quotes are stripped"
    assert values["EMPTY"] == ""
    assert "# comment" not in values


def test_a_missing_dotenv_is_normal_and_yields_nothing(tmp_path: Path) -> None:
    from pipeline.config.settings import load_dotenv

    assert load_dotenv(tmp_path / "absent") == {}


def test_credential_presence_is_reportable_but_values_are_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("pipeline.config.settings.load_dotenv", lambda *a, **k: {})
    monkeypatch.setenv("HUD_USER_TOKEN", "a-token")
    monkeypatch.delenv("CENSUS_API_KEY", raising=False)
    keys = api_keys()
    presence = keys.presence()
    assert presence["HUD_USER_TOKEN"] is True
    assert presence["CENSUS_API_KEY"] is False
    assert all(isinstance(v, bool) for v in presence.values()), (
        "presence() must report booleans, never values"
    )
    assert "a-token" in keys.secret_values(), "held in memory for the leakage scan"


def test_api_keys_default_construction() -> None:
    assert isinstance(ApiKeys().nrel, str)


def test_every_spec_has_a_unique_id_and_a_known_kind() -> None:
    specs = all_specs()
    ids = [s.source_id for s in specs]
    assert len(ids) == len(set(ids))
    assert {s.kind for s in specs} <= {
        "rest_json", "remote_csv", "remote_html_table", "availability",
        "local_csv", "local_geojson", "nested_json_units",
    }


def test_specs_are_sorted_for_stable_output() -> None:
    ids = [s.source_id for s in all_specs()]
    assert ids == sorted(ids)


def test_local_specs_carry_a_path_and_remote_specs_carry_a_url() -> None:
    for spec in all_specs():
        if spec.kind.startswith("local_"):
            assert spec.local_path is not None, spec.source_id
        else:
            assert spec.url.startswith("http"), spec.source_id


def test_the_registry_covers_the_verified_tier_a_states() -> None:
    """Phase 0 finding F-4: 14 Atlas states, 11 at ZIP grain and 3 at county grain."""
    grains = Counter(grain for _, _, grain in ATLAS_STATES)
    assert grains == {"zip": 11, "county": 3}
    assert {code for code, _, _ in ATLAS_STATES} == {
        "CO", "CT", "ME", "MN", "MT", "NC", "NJ", "NM", "NY", "OR", "TN", "TX", "VA", "VT"
    }


def test_the_registry_covers_ten_state_registration_vintages() -> None:
    """Phase 0 finding F-3: AFDC publishes 2016 through 2025."""
    assert tuple(range(2016, 2026)) == AFDC_REGISTRATION_YEARS
    ids = {s.source_id for s in all_specs()}
    for year in range(2016, 2026):
        assert f"afdc_state_ev_registrations_{year}" in ids


def test_no_spec_targets_the_retired_nrel_host() -> None:
    """Phase 0 finding F-5: developer.nrel.gov was retired on 29 May 2026."""
    for spec in all_specs():
        assert "developer.nrel.gov" not in spec.url, spec.source_id
