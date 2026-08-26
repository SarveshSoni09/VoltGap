"""Phase 0 acceptance criteria, as executable checks.

Each test here corresponds to a criterion in CLAUDE.md section 15.5 for Phase 0, or
locks a finding recorded in SOURCES.yml. None of them claims to verify an external
truth: where a finding is a research conclusion, the test verifies that it was
resolved and is supported by preserved, hashed evidence.

Everything runs offline from committed fixtures.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from typing import Any

import pytest

from pipeline.config.settings import PATHS
from pipeline.discovery.cache import ReplayFetcher
from pipeline.discovery.contract import load_contract, validate_contract
from pipeline.discovery.registry import all_specs
from pipeline.discovery.seed_inventory import build_inventory

CONTRACT = load_contract(PATHS.contract)
SOURCES = {entry["id"]: entry for entry in CONTRACT["sources"]}
FINDINGS = {finding["id"]: finding for finding in CONTRACT["findings"]}


def evidence(finding_id: str) -> dict[str, Any]:
    path = PATHS.root / str(FINDINGS[finding_id]["evidence_artifact"])
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return payload


# --- criterion: every source has all contract fields populated ---------------------

def test_the_contract_validates_completely() -> None:
    validate_contract(CONTRACT)


def test_every_probe_spec_has_a_contract_entry_and_the_reverse() -> None:
    assert {s.source_id for s in all_specs()} == set(SOURCES)


def test_the_phase_0_sources_and_findings_are_all_still_present() -> None:
    """Later phases may ADD findings; none of Phase 0's may disappear.

    Phase 1 added F-11 (the A-0.5 vintage-provenance investigation), so this asserts
    the Phase 0 set is intact rather than pinning a total that every later phase would
    have to edit.
    """
    assert len(SOURCES) >= 57
    phase_0 = {f"F-{n}" for n in range(1, 11)}
    assert phase_0 <= set(FINDINGS), f"missing {sorted(phase_0 - set(FINDINGS))}"
    assert len(FINDINGS) >= 10


# --- criterion: every Core model has a data path or a documented fallback ----------

def test_every_source_declares_a_fallback_or_states_it_has_none() -> None:
    for source_id, entry in SOURCES.items():
        fallback = entry["fallback_source"]
        assert isinstance(fallback, str) and fallback, source_id
        if fallback != "none":
            assert fallback in SOURCES, f"{source_id} names an unknown fallback {fallback!r}"


def test_every_source_that_is_not_confirmed_documents_why() -> None:
    """Directive D8: degrade explicitly, never substitute a plausible default."""
    observed = {
        o["source_id"]: o
        for o in json.loads(PATHS.observations.read_text(encoding="utf-8"))["observations"]
    }
    for source_id, entry in SOURCES.items():
        if observed[source_id]["status"] != "confirmed":
            assert entry["known_limitations"], source_id
            assert entry["fallback_source"], source_id


# --- criterion: evidence for research findings is preserved and auditable ----------

def test_every_finding_evidence_artifact_still_matches_its_recorded_hash() -> None:
    for finding_id, finding in FINDINGS.items():
        path = PATHS.root / str(finding["evidence_artifact"])
        assert path.exists(), f"{finding_id}: evidence artifact missing"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == finding["evidence_sha256"], (
            f"{finding_id}: evidence artifact changed since the finding was recorded"
        )


def test_every_finding_carries_a_url_a_timestamp_and_a_quote() -> None:
    for finding_id, finding in FINDINGS.items():
        assert str(finding["evidence_url"]).strip(), finding_id
        assert str(finding["retrieved_at"]).startswith("2026-"), finding_id
        assert len(str(finding["evidence_quote"]).strip()) > 10, finding_id


# --- F-1: AFDC per-connector power and port counts ---------------------------------

def test_afdc_exposes_per_connector_power_and_count_columns() -> None:
    columns: list[str] = evidence("F-1")["per_connector_columns_present"]
    for connector in ("J1772", "CCS", "CHAdeMO", "J3400", "J3271"):
        assert f"EV {connector} Connector Count" in columns
        assert f"EV {connector} Power Output (kW)" in columns


def test_afdc_power_missingness_is_measured_numerically() -> None:
    """CLAUDE.md 15.5 Phase 0: 'AFDC connector power missingness measured numerically'."""
    payload = evidence("F-1")
    for scope in ("all_rows", "public_operational_only"):
        block: dict[str, Any] = payload[scope]
        assert isinstance(block["rung1_port_coverage"], float)
        assert block["total_ports"] > 0
        for connector in block["per_connector"]:
            assert isinstance(connector["port_coverage"], float)
            assert 0.0 <= connector["port_coverage"] <= 1.0


def test_rung1_coverage_clears_the_forty_percent_threshold() -> None:
    """CLAUDE.md 7.1 requires a prominent LIMITATIONS entry below 40% rung-1 coverage."""
    payload = evidence("F-1")
    assert payload["all_rows"]["rung1_port_coverage"] == pytest.approx(0.827561, abs=1e-6)
    assert payload["public_operational_only"]["rung1_port_coverage"] == pytest.approx(
        0.881099, abs=1e-6
    )
    assert payload["public_operational_only"]["rung1_port_coverage"] > 0.40


def test_zero_kilowatt_reported_values_are_recorded_as_a_data_fault() -> None:
    assert evidence("F-1")["all_rows"]["reported_power_equal_zero_cells"] == 55


# --- F-2: NREL home charging vintage semantics -------------------------------------

def test_nrel_home_charging_is_recorded_as_not_current_values() -> None:
    """CLAUDE.md 15.5 Phase 0: 'NREL home charging vintage determined'."""
    entry = SOURCES["nrel_home_charging"]
    semantics = str(entry["coverage"]["vintage_semantics"])
    assert "NOT current values" in semantics
    assert "942,600" in semantics
    assert entry["coverage"]["historical_vintages_available"] is False


def test_home_charging_is_excluded_from_the_primary_siting_objective() -> None:
    """CLAUDE.md 7.2 fallback path, triggered because the shares are not current."""
    entry = SOURCES["nrel_home_charging"]
    assert entry["used_by"] == ["home_charging_exploratory_index"]
    assert any("EXCLUDED from the primary siting objective" in str(limitation)
               for limitation in entry["known_limitations"])


# --- F-3: historical state registration vintages -----------------------------------

def test_historical_state_registration_vintage_availability_is_resolved_yes() -> None:
    """CLAUDE.md 15.5 Phase 0: 'Historical registration vintage availability resolved'."""
    years = evidence("F-3")["years_available"]
    assert years == list(range(2016, 2026))
    for year in range(2016, 2026):
        entry = SOURCES[f"afdc_state_ev_registrations_{year}"]
        assert entry["coverage"]["historical_vintages_available"] is True
        assert entry["backtest_eligible"] is True


def test_the_undated_seed_registration_file_was_dated_to_2023() -> None:
    dating: dict[str, Any] = evidence("F-3")["seed_file_dating"]
    assert dating["half_up_rounded_matches_against_2023_vintage"] == "51/51"
    assert dating["total_row"] == dating["sum_of_jurisdictions"] == 3555445


def test_the_reconciliation_constraint_is_available_at_the_backtest_cutoffs() -> None:
    """CLAUDE.md 10.2.3: the unconstrained-propensity fallback is NOT triggered."""
    for origin in (2020, 2021, 2022):
        assert f"afdc_state_ev_registrations_{origin}" in SOURCES


# --- F-4: Tier A states -------------------------------------------------------------

def test_tier_a_states_are_enumerated_with_granularity_and_coverage() -> None:
    """CLAUDE.md 15.5 Phase 0: 'Tier A states enumerated with granularity ... each'."""
    payload = evidence("F-4")
    atlas: dict[str, Any] = payload["atlas_ev_hub"]
    assert atlas["states"] == 14
    assert len(atlas["zip_grain"]) == 11
    assert len(atlas["county_grain"]) == 3
    assert atlas["login_required"] is False
    assert payload["washington"]["granularity"] == "census tract (_2020_census_tract)"
    assert len(payload["distinct_states_with_substate_data"]) == 16


def test_every_atlas_state_entry_declares_its_granularity() -> None:
    atlas = [e for i, e in SOURCES.items() if i.startswith("atlas_ev_registrations_")]
    assert len(atlas) == 14
    grains = [entry["schema"]["granularity"] for entry in atlas]
    assert grains.count("zip") == 11
    assert grains.count("county") == 3


def test_washington_is_the_only_tract_granularity_registration_source() -> None:
    tract_grain = [
        source_id for source_id, entry in SOURCES.items()
        if entry["schema"].get("granularity") == "tract"
    ]
    assert tract_grain == ["wa_ev_population"]
    assert SOURCES["wa_ev_population"]["backtest_eligible"] is False


# --- F-8: HIFLD substations ---------------------------------------------------------

def test_hifld_substations_service_is_not_national() -> None:
    """Named in SOURCES.yml as the enforcement point for the substation expectation."""
    response = ReplayFetcher(PATHS.replay_fixtures).get(
        "hifld_substations_count",
        "https://services.arcgis.com/G4S1dGvn7PIgYd6Y/ArcGIS/rest/services/"
        "HIFLD_electric_power_substations/FeatureServer/0/query",
        {"where": "1=1", "returnCountOnly": "true", "f": "json"},
    )
    count = json.loads(response.content)["count"]
    assert count == 128
    assert count < 55000, "a national HIFLD substation layer holds tens of thousands"
    assert any("DEGRADED" in str(limitation)
               for limitation in SOURCES["hifld_substations"]["known_limitations"])


# --- seed provenance -----------------------------------------------------------------

def test_the_seed_inventory_still_matches_the_delivered_bytes() -> None:
    recorded = {
        entry["canonical_id"]: entry
        for entry in json.loads(PATHS.seed_inventory_json.read_text())["seed_files"]
    }
    for entry in build_inventory():
        if not (PATHS.seed / entry.raw_filename).exists():  # pragma: no cover
            continue
        assert entry.sha256 == recorded[entry.canonical_id]["sha256"], entry.raw_filename
        assert entry.size_bytes == recorded[entry.canonical_id]["size_bytes"]


def test_the_large_transmission_geojson_is_excluded_from_version_control() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "data/seed/Electric__Power_Transmission_Lines.geojson"],
        cwd=PATHS.root, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, "the 137 MiB GeoJSON must be gitignored"


# --- idempotency ----------------------------------------------------------------------

def test_the_probe_is_idempotent_in_replay_mode(tmp_path: object) -> None:
    """CLAUDE.md 4.2 acceptance: 'probe.py is re-runnable and idempotent'."""
    outputs = []
    for name in ("first.json", "second.json"):
        target = PATHS.root / "data" / "cache" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [sys.executable, "-m", "pipeline.discovery.probe", "--offline",
             "--cache-root", str(PATHS.replay_fixtures), "--out", str(target)],
            cwd=PATHS.root, check=True, capture_output=True,
        )
        outputs.append(target.read_bytes())
        target.unlink()
    assert outputs[0] == outputs[1]
