"""Forward-viability smoke test (gate part G-D).

Phase 1's core operation is: read a source's contract, retrieve it, and land its rows
in a typed staging frame keyed on the contract's declared join keys, using ONLY the
field names Phase 0 discovered.

This exercise runs that operation end to end against Phase 0's real outputs, on a
two-state fixture (Minnesota and Illinois), entirely offline from the committed replay
cache. It deliberately does no entity resolution, no filtering, and no modelling.

What it proves: SOURCES.yml is machine-consumable, the discovered schemas are real,
the declared join keys exist in the data, and a typed staging load succeeds on the
shapes Phase 1 will meet.

What it does NOT prove: anything about the site / station / charging unit / port
entity hierarchy, about deduplication, about spatial joins, or about correctness of
any modelled quantity. Those are Phase 1 and Phase 2 concerns.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

import pandas as pd

from pipeline.config.settings import PATHS
from pipeline.discovery.cache import ReplayFetcher
from pipeline.discovery.contract import load_contract
from pipeline.discovery.probe import request_params
from pipeline.discovery.registry import ProbeSpec, all_specs

CONTRACT = load_contract(PATHS.contract)
SOURCES = {entry["id"]: entry for entry in CONTRACT["sources"]}
SPECS = {spec.source_id: spec for spec in all_specs()}

# The two-state fixture required by CLAUDE.md section 14 ("Full pipeline on a fixture
# subset (2 states)"). Minnesota and Illinois are the two states the delivered seed
# data covers at sub-state grain.
TWO_STATE_FIXTURE = (
    "seed_afdc_stations_mn_20241210",   # Minnesota, 75-column AFDC station schema
    "seed_il_stations",                 # Illinois, reduced station schema
    "seed_mn_county_ev_registrations",  # Minnesota, county EV registrations
    "seed_il_county_ev_monthly_panel",  # Illinois, monthly county panel
)


def stage(source_id: str) -> pd.DataFrame:
    """The minimal Phase 1 staging operation, driven entirely by the contract.

    Staging models must not filter rows (CLAUDE.md section 9): this only types and
    loads. Every column is read as a string, which is what a staging layer does before
    the intermediate layer applies business logic.
    """
    spec = SPECS[source_id]
    if spec.kind == "local_csv":
        assert spec.local_path is not None
        with spec.local_path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
            rows = list(csv.DictReader(fh, delimiter=spec.delimiter))
    else:
        response = ReplayFetcher(PATHS.replay_fixtures).get(
            source_id, spec.url, request_params(spec), spec.headers
        )
        text = response.content.decode("utf-8", errors="replace")
        rows = list(csv.DictReader(io.StringIO(text), delimiter=spec.delimiter))
    frame = pd.DataFrame(rows, dtype="string")
    frame["source_id"] = source_id
    frame["source_vintage"] = str(SOURCES[source_id]["coverage"]["temporal"])
    return frame


def test_every_two_state_fixture_source_stages_with_its_declared_schema() -> None:
    for source_id in TWO_STATE_FIXTURE:
        entry = SOURCES[source_id]
        frame = stage(source_id)
        expected_rows = entry["quality"]["expected_row_count"]
        expected_fields = entry["schema"]["expected_field_count"]

        assert len(frame) == expected_rows[0] == expected_rows[1], source_id
        # Two provenance columns are added by the staging step itself.
        assert len(frame.columns) == expected_fields + 2, source_id
        assert (frame["source_id"] == source_id).all()
        assert frame["source_vintage"].notna().all()


def test_declared_join_keys_exist_in_the_staged_data() -> None:
    """A contract that names a join key which is not in the data is unusable."""
    for source_id in TWO_STATE_FIXTURE:
        keys: list[Any] = list(SOURCES[source_id]["schema"]["join_keys"])
        if not keys:
            continue
        frame = stage(source_id)
        for key in keys:
            assert key in frame.columns, f"{source_id}: join key {key!r} absent"


def test_a_remote_source_stages_from_the_replay_cache_without_network() -> None:
    """The gate must never depend on the live network."""
    frame = stage("afdc_charging_units")
    assert len(frame) == 2951
    assert "EV CCS Power Output (kW)" in frame.columns
    assert "Snapshot Date" in frame.columns


def test_the_two_afdc_extracts_share_one_schema_so_they_can_be_unioned() -> None:
    """Phase 1 must be able to stack state extracts into one canonical table."""
    national = SOURCES["seed_afdc_stations_national_20241211"]["schema"]["schema_version"]
    minnesota = SOURCES["seed_afdc_stations_mn_20241210"]["schema"]["schema_version"]
    assert national == minnesota == "f6860736f1304654"

    stacked = pd.concat([stage("seed_afdc_stations_mn_20241210")], ignore_index=True)
    assert len(stacked) == 985


def test_the_power_ladder_input_columns_survive_staging() -> None:
    """Phase 2's power-resolution ladder needs rung-1 columns to arrive intact."""
    frame = stage("afdc_charging_units")
    for connector in ("J1772", "CCS", "CHAdeMO", "J3400", "J3271"):
        assert f"EV {connector} Connector Count" in frame.columns
        assert f"EV {connector} Power Output (kW)" in frame.columns
    reported = pd.to_numeric(frame["EV CCS Power Output (kW)"], errors="coerce")
    assert reported.notna().sum() > 0, "at least some rung-1 power must be present"


def test_a_source_spec_can_be_reconstructed_from_the_contract_alone() -> None:
    """The registry and the contract must not disagree about where a source lives."""
    for source_id, entry in SOURCES.items():
        spec: ProbeSpec = SPECS[source_id]
        if spec.kind.startswith("local_"):
            continue
        endpoint = str(entry["retrieval"]["endpoint"])
        if "{" in endpoint:  # templated endpoint; the spec fills the placeholders
            continue
        assert spec.url == endpoint, source_id


# --- contract-wide checks the two-state exercise generalises to --------------------

# rest_json specs with no record_path probe an endpoint's *metadata* (an ArcGIS layer
# description, a Socrata view), whose fields are service properties rather than record
# attributes. Their contract join keys describe the underlying records, so they are not
# expected to appear in the metadata payload.
def _is_record_grain(source_id: str) -> bool:
    spec = SPECS[source_id]
    return not (spec.kind == "rest_json" and not spec.record_path)


def test_every_declared_join_key_exists_in_the_observed_schema() -> None:
    """A contract naming a join key that is not in the data is unusable in Phase 1."""
    observed = {
        o["source_id"]: o
        for o in json.loads(PATHS.observations.read_text(encoding="utf-8"))["observations"]
    }
    missing: list[str] = []
    for source_id, entry in SOURCES.items():
        record = observed[source_id]
        if record["status"] != "confirmed" or not record["measurement"]:
            continue
        if not _is_record_grain(source_id):
            continue
        # CenPop files begin with a UTF-8 byte order mark; the contract records the
        # logical column name and flags the BOM as a known limitation.
        fields = {str(f).lstrip("\ufeff") for f in record["measurement"]["fields"]}
        missing += [
            f"{source_id}: {key!r}"
            for key in entry["schema"]["join_keys"]
            if key not in fields
        ]
    assert missing == [], f"contract join keys absent from the data: {missing}"


def test_expected_field_counts_match_the_observed_schema() -> None:
    observed = {
        o["source_id"]: o
        for o in json.loads(PATHS.observations.read_text(encoding="utf-8"))["observations"]
    }
    for source_id, entry in SOURCES.items():
        declared = entry["schema"].get("expected_field_count")
        record = observed[source_id]
        if declared is None or record["status"] != "confirmed" or not record["measurement"]:
            continue
        assert record["measurement"]["field_count"] == declared, source_id


def test_declared_schema_versions_match_the_observed_schema_hashes() -> None:
    observed = {
        o["source_id"]: o
        for o in json.loads(PATHS.observations.read_text(encoding="utf-8"))["observations"]
    }
    for source_id, entry in SOURCES.items():
        declared = entry["schema"].get("schema_version")
        record = observed[source_id]
        if declared is None or not record["measurement"]:
            continue
        assert record["measurement"]["schema_hash"] == declared, source_id
