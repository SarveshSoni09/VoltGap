"""Phase 2 gate checks P2-A to P2-H (CLAUDE.md 15.5, amendment A22).

Each is an executable check of a rule that exists because Phase 1 discovered
something about the source, not because it seemed like good practice.
"""

from __future__ import annotations

import json

import pytest

from pipeline.config.settings import PATHS
from pipeline.model.build_supply_access import (
    FORBIDDEN_INPUT_TABLES,
    PHASE_2_INPUT_TABLES,
    read_connector_observations,
)
from pipeline.model.supply import (
    CapacityBasis,
    ResolvedPower,
    aggregate_site_capacity,
    aggregate_unit_capacity,
    load_connectors,
    load_power_defaults,
    normalize_connector,
)
from pipeline.schemas.canonical import check_port_count_drift
from pipeline.transform.runner import Warehouse

EVIDENCE = PATHS.root / "docs" / "evidence"


def reported(raw: str, normalized: str, level: str, count: int,
             power: float) -> ResolvedPower:
    return ResolvedPower(raw, normalized, level, count, power, "reported", "high")


# --- P2-A: no connector double counting ---------------------------------------------

def test_p2a_dual_standard_dc_unit_does_not_sum_alternative_connectors() -> None:
    """Fixture 1 from the specification: one port, CCS 200 kW, CHAdeMO 100 kW."""
    unit = aggregate_unit_capacity(
        "u1", "dc_fast", 1,
        [reported("J1772COMBO", "CCS", "dc_fast", 1, 200.0),
         reported("CHADEMO", "CHAdeMO", "dc_fast", 1, 100.0)],
    )
    assert unit.simultaneous_service_ports == 1
    assert unit.generic_service_capacity_kw != 300.0, "summing alternatives double counts"
    assert unit.generic_service_capacity_kw == 200.0
    assert unit.connector_compatible_kw["CCS"] == 200.0
    assert unit.connector_compatible_kw["CHAdeMO"] == 100.0
    assert unit.generic_capacity_basis == CapacityBasis.SINGLE_PORT_CONNECTOR_MAXIMUM


def test_p2a_ccs_plus_nacs_one_port_unit_follows_the_same_rule() -> None:
    """Fixture 2 from the specification."""
    unit = aggregate_unit_capacity(
        "u2", "dc_fast", 1,
        [reported("J1772COMBO", "CCS", "dc_fast", 1, 250.0),
         reported("TESLA", "J3400/NACS", "dc_fast", 1, 250.0)],
    )
    assert unit.generic_service_capacity_kw == 250.0, "not 500"
    assert unit.simultaneous_service_ports == 1


def test_p2a_connector_count_is_not_simultaneous_service_count() -> None:
    """Fixture 3: two connector standards must not become two serviceable ports."""
    unit = aggregate_unit_capacity(
        "u3", "dc_fast", 1,
        [reported("J1772COMBO", "CCS", "dc_fast", 1, 150.0),
         reported("CHADEMO", "CHAdeMO", "dc_fast", 1, 50.0)],
    )
    assert unit.simultaneous_service_ports == 1
    assert len(unit.connector_standards_available) == 2
    assert unit.is_multi_connector_port is True


def test_p2a_a_source_provided_unit_maximum_takes_precedence() -> None:
    unit = aggregate_unit_capacity(
        "u4", "dc_fast", 1,
        [reported("J1772COMBO", "CCS", "dc_fast", 1, 200.0)],
        unit_reported_maximum_kw=180.0,
    )
    assert unit.generic_service_capacity_kw == 180.0
    assert unit.generic_capacity_basis == CapacityBasis.UNIT_REPORTED_MAXIMUM


def test_p2a_a_multi_port_unit_does_not_inherit_the_one_port_rule() -> None:
    """port_count > 1 is legitimate future data; the max rule does not generalise."""
    unit = aggregate_unit_capacity(
        "u5", "dc_fast", 4,
        [reported("J1772COMBO", "CCS", "dc_fast", 4, 150.0)],
    )
    assert unit.generic_service_capacity_kw is None
    assert unit.generic_capacity_basis == CapacityBasis.MULTI_PORT_UNRESOLVED
    assert unit.simultaneous_service_ports == 4


def test_p2a_site_capacity_sums_across_units_but_never_across_connectors() -> None:
    unit = aggregate_unit_capacity(
        "u6", "dc_fast", 1,
        [reported("J1772COMBO", "CCS", "dc_fast", 1, 200.0),
         reported("CHADEMO", "CHAdeMO", "dc_fast", 1, 100.0)],
    )
    site = aggregate_site_capacity("s1", [unit, unit, unit])
    assert site.generic_service_capacity_kw == 600.0, "3 units x 200 kW"
    assert site.simultaneous_service_ports == 3
    assert sum(site.connector_compatible_kw.values()) == 900.0
    assert sum(site.connector_compatible_kw.values()) > site.generic_service_capacity_kw


# --- P2-B: charging level comes from the source ---------------------------------------

def test_p2b_charging_level_is_taken_from_the_record_not_the_connector_name() -> None:
    """NEMA 14-50 classified Level 2 by the source stays Level 2."""
    unit = aggregate_unit_capacity(
        "u7", "2", 1, [reported("NEMA1450", "NEMA 14-50", "2", 1, 9.6)]
    )
    assert unit.charging_level == "2"


def test_p2b_the_same_connector_at_two_levels_keeps_its_source_level() -> None:
    """TESLA appears on AC destination chargers and on DC Superchargers."""
    ac = aggregate_unit_capacity("u8", "2", 1,
                                 [reported("TESLA", "J3400/NACS", "2", 1, 11.5)])
    dc = aggregate_unit_capacity("u9", "dc_fast", 1,
                                 [reported("TESLA", "J3400/NACS", "dc_fast", 1, 250.0)])
    assert ac.charging_level == "2"
    assert dc.charging_level == "dc_fast"
    assert ac.generic_service_capacity_kw != dc.generic_service_capacity_kw


def test_p2b_no_module_infers_level_from_a_connector_name() -> None:
    """A source scan: `typical_levels` is descriptive and must never drive logic."""
    for module in (PATHS.root / "pipeline" / "model").rglob("*.py"):
        text = module.read_text(encoding="utf-8")
        assert "typical_levels" not in text or "supply.py" in module.name, (
            f"{module.name} references typical_levels, which is documentation only"
        )


def test_p2b_the_connector_config_declares_levels_as_descriptive_only() -> None:
    import yaml

    document = yaml.safe_load(
        (PATHS.root / "pipeline" / "config" / "connectors.yml").read_text(encoding="utf-8")
    )
    assert "DESCRIPTIVE ONLY" in (PATHS.root / "pipeline" / "config" / "connectors.yml"
                                  ).read_text(encoding="utf-8")
    # NEMA 14-50 is the concrete counter-example to "NEMA means Level 1".
    assert "2" in document["connectors"]["NEMA1450"]["typical_levels"]


# --- P2-C: normalisation preserves raw provenance ---------------------------------------

def test_p2c_every_normalised_connector_retains_its_raw_value() -> None:
    table = load_connectors()
    for raw, spec in table.items():
        assert spec.raw == raw
    assert table["TESLA"].normalized == "J3400/NACS"
    assert table["TESLA"].raw == "TESLA", "terminology has changed; the raw value stays"
    assert table["J1772COMBO"].normalized == "CCS"


def test_p2c_an_unknown_connector_passes_through_rather_than_being_dropped() -> None:
    spec = normalize_connector("SOME_NEW_STANDARD", load_connectors())
    assert spec.raw == spec.normalized == "SOME_NEW_STANDARD"
    assert spec.standard_family == "unknown"


def test_p2c_resolved_rows_carry_both_forms() -> None:
    entry = reported("TESLA", "J3400/NACS", "dc_fast", 1, 250.0).to_dict()
    assert entry["connector_type_raw"] == "TESLA"
    assert entry["connector_type_normalized"] == "J3400/NACS"


# --- P2-D: port_count observation is monitored, not ontology -----------------------------

def test_p2d_the_schema_permits_more_than_one_port() -> None:
    """A future AFDC record with several ports is data, not corruption (A19)."""
    import pandas as pd

    from pipeline.schemas.canonical import MART_UNIT_CAPACITY

    frame = pd.DataFrame({
        "charging_unit_record_key": ["u1"], "charging_level": ["dc_fast"],
        "port_count": [4], "simultaneous_service_ports": [4],
        "generic_service_capacity_kw": [None], "generic_capacity_basis": ["multi_port_unresolved"],
        "connector_standards_available": ["CCS"], "is_multi_connector_port": [False],
        "power_source": ["reported"], "power_confidence": ["high"],
        "computed_at": ["T"], "source_vintages": ["{}"],
    })
    MART_UNIT_CAPACITY.validate(frame, lazy=True)


def test_p2d_a_port_count_of_zero_is_rejected_as_structurally_invalid() -> None:
    import pandas as pd
    import pandera.pandas as pa

    from pipeline.schemas.canonical import MART_UNIT_CAPACITY

    frame = pd.DataFrame({
        "charging_unit_record_key": ["u1"], "charging_level": ["dc_fast"],
        "port_count": [0], "simultaneous_service_ports": [1],
        "generic_service_capacity_kw": [1.0], "generic_capacity_basis": ["unresolved"],
        "connector_standards_available": [""], "is_multi_connector_port": [False],
        "power_source": ["reported"], "power_confidence": ["high"],
        "computed_at": ["T"], "source_vintages": ["{}"],
    })
    with pytest.raises(pa.errors.SchemaErrors):
        MART_UNIT_CAPACITY.validate(frame, lazy=True)


def test_p2d_drift_is_surfaced_for_review_not_raised_as_a_failure() -> None:
    import pandas as pd

    drift = check_port_count_drift(pd.DataFrame({"port_count": [1, 1, 3]}))
    assert drift.matches_phase_1_observation is False
    assert drift.units_with_multiple_ports == 1
    assert drift.max_port_count == 3
    assert "source-drift review" in str(drift.to_dict()["note"])


def test_p2d_the_current_snapshot_still_shows_one_port_per_record(
    phase2_warehouse: Warehouse,
) -> None:
    """A regression observation, not a schema rule."""
    drift = check_port_count_drift(phase2_warehouse.fetch_df("mart_unit_capacity"))
    assert drift.matches_phase_1_observation is True
    assert drift.max_port_count == 1


# --- P2-E: the 22 reconciliation exceptions ----------------------------------------------

def test_p2e_reconciliation_exceptions_are_all_classified() -> None:
    payload = json.loads((EVIDENCE / "P2-1_station_reconciliation.json").read_text())
    assert payload["exception_count"] == 22
    assert payload["resolution"]["unresolved_count"] == 0
    tally = payload["classification_tally"]
    assert tally == {"legacy_charging_level": 8, "missing_station_aggregate": 2,
                     "no_unit_records": 12}
    assert sum(tally.values()) == 22
    for exception in payload["exceptions"]:
        assert exception["classification"] != "unresolved"


def test_p2e_the_unscoped_rate_is_never_described_as_one_hundred_percent() -> None:
    payload = json.loads((EVIDENCE / "P2-1_station_reconciliation.json").read_text())
    assert payload["unscoped_reconciliation_rate"] < 1.0
    assert abs(payload["unscoped_reconciliation_rate"] - 0.999755) < 1e-6
    assert "100%" in payload["resolution"]["scoped_reconciliation"]
    assert payload["resolution"]["documented_scope_definition"]


def test_p2e_every_no_unit_record_exception_is_a_planned_station() -> None:
    payload = json.loads((EVIDENCE / "P2-1_station_reconciliation.json").read_text())
    planned = [e for e in payload["exceptions"] if e["classification"] == "no_unit_records"]
    assert len(planned) == 12
    assert all(e["status_code"] == "P" for e in planned), (
        "planned stations carry no units because nothing is built yet; G2 already "
        "excludes them from operational supply"
    )


def test_p2e_every_legacy_exception_actually_contains_a_legacy_unit() -> None:
    payload = json.loads((EVIDENCE / "P2-1_station_reconciliation.json").read_text())
    legacy = [e for e in payload["exceptions"]
              if e["classification"] in ("legacy_charging_level", "missing_station_aggregate")]
    assert len(legacy) == 10
    assert all("legacy" in e["charging_levels"] for e in legacy)


# --- P2-F: site-clustering diagnostic ------------------------------------------------------

def test_p2f_the_site_diagnostic_is_complete() -> None:
    payload = json.loads((EVIDENCE / "P2-2_site_resolution_diagnostic.json").read_text())
    measurements = payload["measurements"]
    for key in ("clusters", "stations", "singleton_clusters", "singleton_share",
                "clusters_with_at_least", "max_station_count", "multi_station_clusters",
                "diameter_m", "clusters_exceeding_diameter", "suspicious_cluster_count"):
        assert key in measurements, key
    assert set(measurements["clusters_with_at_least"]) == {"2", "5", "10"}
    assert set(measurements["clusters_exceeding_diameter"]) == {"50", "100", "200", "500"}


def test_p2f_transitive_chaining_is_measured_not_assumed_away() -> None:
    """eps = 50 m does not bound cluster diameter; the diagnostic must show that."""
    payload = json.loads((EVIDENCE / "P2-2_site_resolution_diagnostic.json").read_text())
    exceeding = payload["measurements"]["clusters_exceeding_diameter"]
    assert exceeding["50"] > 0, "chaining beyond eps is real and must be visible"
    assert payload["measurements"]["diameter_m"]["max"] > 50.0


def test_p2f_pathological_clusters_are_rare_and_the_verdict_is_recorded() -> None:
    payload = json.loads((EVIDENCE / "P2-2_site_resolution_diagnostic.json").read_text())
    assert payload["measurements"]["suspicious_share_of_multi"] < 0.01
    assert payload["measurements"]["clusters_exceeding_diameter"]["500"] == 0
    assert payload["resolution"]["verdict"]
    assert payload["resolution"]["effect_on_phase_2_outputs"]


# --- P2-G: no registration allocations in the Phase 2 dependency graph -----------------------

def test_p2g_phase_2_does_not_read_any_registration_table() -> None:
    """Supply and access must not consume land-area-weighted allocations (A21)."""
    module = (PATHS.root / "pipeline" / "model" / "build_supply_access.py").read_text(
        encoding="utf-8")
    body = module.split("FORBIDDEN_INPUT_TABLES")[-1]
    for table in FORBIDDEN_INPUT_TABLES:
        assert f'"{table}"' not in body.replace(
            '"mart_observed_subregion_ev", "int_observed_subregion_ev",', ""
        ).replace('"stg_atlas_registrations", "raw_atlas_registrations",', ""), table


def test_p2g_the_permitted_and_forbidden_input_sets_are_disjoint() -> None:
    assert not (PHASE_2_INPUT_TABLES & FORBIDDEN_INPUT_TABLES)
    assert "mart_observed_subregion_ev" in FORBIDDEN_INPUT_TABLES


def test_p2g_no_phase_2_module_imports_the_crosswalk(
) -> None:
    """The crosswalk is Phase 1 machinery that Phase 3 validates; Phase 2 must not use it."""
    for name in ("supply.py", "access.py", "build_supply_access.py"):
        text = (PATHS.root / "pipeline" / "model" / name).read_text(encoding="utf-8")
        assert "spatial.crosswalk" not in text, name
        assert "allocate_by_population" not in text or name == "access.py", name


def test_p2g_access_reads_only_population_and_supply(
    phase2_warehouse: Warehouse,
) -> None:
    observations = read_connector_observations(phase2_warehouse)
    assert observations
    assert all("ev_count" not in row for row in observations)
    assert all("evidence_grain" not in row for row in observations)


# --- P2-H: the two capacity concepts are separate ---------------------------------------------

def test_p2h_generic_and_connector_compatible_capacity_are_separate_columns(
    phase2_warehouse: Warehouse,
) -> None:
    columns = {
        str(row[0]) for row in
        phase2_warehouse.connection.execute("DESCRIBE mart_site_supply").fetchall()
    }
    assert "generic_service_capacity_kw" in columns
    assert "connector_compatible_kw_json" in columns


def test_p2h_the_two_quantities_genuinely_differ_on_real_data(
    phase2_warehouse: Warehouse,
) -> None:
    """If they never diverged, the distinction would be decorative."""
    rows = phase2_warehouse.connection.execute(
        "SELECT generic_service_capacity_kw, connector_compatible_kw_json "
        "FROM mart_site_supply"
    ).fetchall()
    generic_total = sum(float(r[0]) for r in rows)
    compatible_total = sum(sum(json.loads(r[1]).values()) for r in rows)
    assert compatible_total > generic_total, (
        "on real multi-connector data, summing connector-compatible capacity must "
        "overstate physical capacity"
    )
    overstatement = compatible_total / generic_total - 1.0
    assert overstatement > 0.01, f"overstatement is only {overstatement:.4%}"


def test_p2h_neither_field_silently_substitutes_for_the_other() -> None:
    unit = aggregate_unit_capacity(
        "u", "dc_fast", 1,
        [reported("J1772COMBO", "CCS", "dc_fast", 1, 200.0),
         reported("CHADEMO", "CHAdeMO", "dc_fast", 1, 100.0)],
    )
    assert unit.generic_service_capacity_kw == 200.0
    assert dict(unit.connector_compatible_kw) == {"CCS": 200.0, "CHAdeMO": 100.0}
    assert sum(unit.connector_compatible_kw.values()) != unit.generic_service_capacity_kw


def test_p2h_power_defaults_are_configured_not_hard_coded() -> None:
    defaults = load_power_defaults()
    assert defaults.defaults
    for key, justification in defaults.justifications.items():
        assert len(justification) > 20, f"{key} has no cited justification"
    source = (PATHS.root / "pipeline" / "model" / "supply.py").read_text(encoding="utf-8")
    assert "150.0" not in source and "250.0" not in source, (
        "rung-3 default values must live in power_defaults.yml, never in Python"
    )


# --- P2-I: mixed public/private sites -------------------------------------------------

def test_p2i_private_capacity_is_never_added_to_public_capacity() -> None:
    """G4 aggregates co-located stations, so a site can mix public and private."""
    public_l2 = aggregate_unit_capacity("l2", "2", 1,
                                        [reported("J1772", "J1772", "2", 1, 7.2)])
    private_dc = aggregate_unit_capacity(
        "dc", "dc_fast", 1, [reported("J1772COMBO", "CCS", "dc_fast", 1, 350.0)])
    site = aggregate_site_capacity("mixed", [public_l2, private_dc], [True, False])
    assert site.generic_service_capacity_kw == 357.2, "all-units total is unchanged"
    assert site.public_generic_service_capacity_kw == 7.2, "private 350 kW excluded"
    assert site.public_unit_count == 1


def test_p2i_a_public_station_plus_a_private_dcfc_is_not_a_public_dcfc_site() -> None:
    """The specific inference the correction forbids."""
    public_l2 = aggregate_unit_capacity("l2", "2", 1,
                                        [reported("J1772", "J1772", "2", 1, 7.2)])
    private_dc = aggregate_unit_capacity(
        "dc", "dc_fast", 1, [reported("J1772COMBO", "CCS", "dc_fast", 1, 350.0)])
    site = aggregate_site_capacity("mixed", [public_l2, private_dc], [True, False])
    assert site.has_public_operational_service is True, "it does offer public service"
    assert site.qualifies_for_level({"dc_fast"}) is False, (
        "but not PUBLIC DC fast service: those are different stations"
    )
    assert site.qualifies_for_level({"2"}) is True


def test_p2i_a_genuinely_public_dcfc_unit_does_qualify() -> None:
    unit = aggregate_unit_capacity(
        "dc", "dc_fast", 1, [reported("J1772COMBO", "CCS", "dc_fast", 1, 350.0)])
    site = aggregate_site_capacity("public", [unit], [True])
    assert site.qualifies_for_level({"dc_fast"}) is True
    assert site.public_generic_service_capacity_kw == 350.0


def test_p2i_the_mart_carries_public_and_all_unit_columns_separately(
    phase2_warehouse: Warehouse,
) -> None:
    columns = {str(r[0]) for r in
               phase2_warehouse.connection.execute("DESCRIBE mart_site_supply").fetchall()}
    assert {"generic_service_capacity_kw", "public_generic_service_capacity_kw",
            "public_ports_dcfc", "has_public_operational_service"} <= columns
    row = phase2_warehouse.connection.execute(
        "SELECT sum(generic_service_capacity_kw), sum(public_generic_service_capacity_kw) "
        "FROM mart_site_supply").fetchone()
    assert row is not None
    assert row[0] >= row[1], "public capacity can never exceed all-units capacity"


def test_p2i_access_qualification_uses_public_ports_only(
    phase2_warehouse: Warehouse,
) -> None:
    mismatched = phase2_warehouse.connection.execute(
        "SELECT count(*) FROM mart_site_supply "
        "WHERE public_ports_dcfc > ports_dcfc OR public_ports_l2 > ports_l2"
    ).fetchone()
    assert mismatched is not None and mismatched[0] == 0
