"""Unit tests for the supply model: configuration, the ladder, and aggregation."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.model.supply import (
    CONFIDENCE_FOR_SOURCE,
    CapacityBasis,
    ConnectorSpec,
    EmpiricalGroup,
    EmpiricalTable,
    PowerConfidence,
    PowerSource,
    ResolvedPower,
    SupplyConfigError,
    _as_float,
    aggregate_site_capacity,
    aggregate_unit_capacity,
    build_empirical_table,
    is_valid_reported_power,
    load_connectors,
    load_power_defaults,
    normalize_connector,
    resolve_power,
)

# --- configuration --------------------------------------------------------------------

def test_the_shipped_connector_table_loads() -> None:
    table = load_connectors()
    assert len(table) == 8
    assert {s.normalized for s in table.values()} >= {"CCS", "CHAdeMO", "J3400/NACS"}


def test_missing_connector_config_raises(tmp_path: Path) -> None:
    with pytest.raises(SupplyConfigError, match="connector configuration missing"):
        load_connectors(tmp_path / "absent.yml")


def test_empty_connector_config_raises(tmp_path: Path) -> None:
    path = tmp_path / "c.yml"
    path.write_text("connectors:\n", encoding="utf-8")
    with pytest.raises(SupplyConfigError, match="declares no connectors"):
        load_connectors(path)


def test_the_shipped_power_defaults_load_with_justifications() -> None:
    defaults = load_power_defaults()
    assert defaults.rung_2_minimum_sample == 30
    assert len(defaults.rung_2_hierarchy) == 3
    assert defaults.default_for("CCS", "dc_fast") == 150.0
    assert defaults.default_for("nonexistent", "dc_fast") is None


def test_missing_power_defaults_raise(tmp_path: Path) -> None:
    with pytest.raises(SupplyConfigError, match="power defaults missing"):
        load_power_defaults(tmp_path / "absent.yml")


def test_power_defaults_without_entries_raise(tmp_path: Path) -> None:
    path = tmp_path / "p.yml"
    path.write_text("rung_2_minimum_sample: 30\nrung_2_hierarchy: []\n", encoding="utf-8")
    with pytest.raises(SupplyConfigError, match="declares no defaults"):
        load_power_defaults(path)


def test_a_default_without_a_justification_is_rejected(tmp_path: Path) -> None:
    """Every rung-3 number must carry a cited reason (CLAUDE.md 7.1)."""
    path = tmp_path / "p.yml"
    path.write_text(
        "rung_2_minimum_sample: 30\nrung_2_hierarchy: [[charging_level]]\n"
        "defaults:\n  - connector: CCS\n    charging_level: dc_fast\n"
        "    power_kw: 150.0\n    justification: '  '\n",
        encoding="utf-8",
    )
    with pytest.raises(SupplyConfigError, match="no justification"):
        load_power_defaults(path)


def test_normalisation_preserves_raw_and_passes_unknowns_through() -> None:
    table = load_connectors()
    assert normalize_connector("TESLA", table).normalized == "J3400/NACS"
    unknown = normalize_connector("MCS", table)
    assert unknown.raw == unknown.normalized == "MCS"
    assert unknown.standard_family == "unknown"


def test_connector_spec_serialises() -> None:
    payload = ConnectorSpec("TESLA", "J3400/NACS", "d", "mixed", ("2",)).to_dict()
    assert payload["connector_type_raw"] == "TESLA"
    assert payload["connector_type_normalized"] == "J3400/NACS"


# --- rung 1 ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("value", "valid"),
    [(150.0, True), ("7.2", True), (0.0, False), ("0", False), (-5.0, False),
     (None, False), ("", False), ("abc", False)],
)
def test_zero_and_unparseable_power_are_not_valid_reported_values(
    value: object, valid: bool
) -> None:
    """Exactly 0.00 kW is an anomaly; 55 such cells exist nationally."""
    assert is_valid_reported_power(value) is valid


def test_as_float_helper() -> None:
    assert _as_float("1.5") == 1.5
    assert _as_float(None) is None
    assert _as_float("x") is None


# --- rung 2 ---------------------------------------------------------------------------

def observation(**kw: object) -> dict[str, object]:
    base = {"connector_type_raw": "J1772COMBO", "connector_count": 1,
            "charging_level": "dc_fast", "network": "Net", "power_kw": 150.0,
            "connector_normalized": "CCS"}
    base.update(kw)
    return base


def test_empirical_medians_are_built_from_rung_1_records_only() -> None:
    defaults = load_power_defaults()
    records = [observation(power_kw=p) for p in (100.0, 200.0, 300.0)]
    records.append(observation(power_kw=None))
    records.append(observation(power_kw=0.0))
    table = build_empirical_table(records, defaults)
    group = table.groups[("network|connector_normalized|charging_level",
                          ("Net", "CCS", "dc_fast"))]
    assert group.sample_size == 3, "null and zero-power records must not contribute"
    assert group.median_kw == 200.0


def test_a_group_below_the_minimum_sample_is_recorded_but_not_used() -> None:
    defaults = load_power_defaults()
    table = build_empirical_table([observation()] * 5, defaults)
    assert table.summary()[0]["usable"] is False
    assert table.lookup({"network": "Net", "connector_normalized": "CCS",
                         "charging_level": "dc_fast"}) is None


def test_the_most_specific_sufficiently_populated_group_wins() -> None:
    defaults = load_power_defaults()
    records = [observation(power_kw=100.0) for _ in range(40)]
    records += [observation(network="Other", power_kw=500.0) for _ in range(40)]
    table = build_empirical_table(records, defaults)
    group = table.lookup({"network": "Net", "connector_normalized": "CCS",
                          "charging_level": "dc_fast"})
    assert group is not None
    assert group.median_kw == 100.0
    assert "network=Net" in group.label


def test_lookup_falls_back_to_a_broader_group() -> None:
    defaults = load_power_defaults()
    records = [observation(network=f"N{i}", power_kw=120.0) for i in range(40)]
    table = build_empirical_table(records, defaults)
    group = table.lookup({"network": "Unseen", "connector_normalized": "CCS",
                          "charging_level": "dc_fast"})
    assert group is not None
    assert group.keys == ("connector_normalized", "charging_level")


def test_empirical_group_label() -> None:
    assert EmpiricalGroup(("a", "b"), ("1", "2"), 5, 1.0).label == "a=1+b=2"


def test_an_empty_empirical_table_looks_up_nothing() -> None:
    assert EmpiricalTable(30, (("charging_level",),)).lookup({"charging_level": "2"}) is None


# --- the ladder -------------------------------------------------------------------------

def resolve(record: dict[str, object], table: EmpiricalTable | None = None) -> ResolvedPower:
    return resolve_power(record, load_connectors(),
                         table or EmpiricalTable(30, (("charging_level",),)),
                         load_power_defaults())


def test_rung_1_reported_power_wins() -> None:
    entry = resolve(observation(power_kw=333.0))
    assert entry.power_kw == 333.0
    assert entry.power_source == PowerSource.REPORTED
    assert entry.power_confidence == PowerConfidence.HIGH


def test_rung_2_is_used_when_no_power_is_reported() -> None:
    defaults = load_power_defaults()
    table = build_empirical_table([observation(power_kw=175.0)] * 40, defaults)
    entry = resolve(observation(power_kw=None), table)
    assert entry.power_kw == 175.0
    assert entry.power_source == PowerSource.EMPIRICAL_FALLBACK
    assert entry.power_confidence == PowerConfidence.MEDIUM
    assert entry.fallback_group is not None


def test_rung_3_is_used_when_no_peer_group_qualifies() -> None:
    entry = resolve(observation(power_kw=None))
    assert entry.power_kw == 150.0
    assert entry.power_source == PowerSource.TYPE_DEFAULT
    assert entry.power_confidence == PowerConfidence.LOW


def test_an_unresolvable_connector_is_reported_not_filled_with_a_guess() -> None:
    """Directive D8: degrade explicitly."""
    entry = resolve(observation(connector_type_raw="MCS", charging_level="unknown",
                                power_kw=None))
    assert entry.power_kw is None
    assert entry.power_source == PowerSource.UNRESOLVED
    assert entry.power_confidence == PowerConfidence.NONE


def test_a_zero_power_cell_is_flagged_and_falls_through_the_ladder() -> None:
    entry = resolve(observation(power_kw=0.0))
    assert entry.is_zero_power_anomaly is True
    assert entry.power_source != PowerSource.REPORTED


def test_resolved_power_serialises() -> None:
    payload = resolve(observation()).to_dict()
    assert payload["power_source"] == "reported"
    assert payload["connector_type_normalized"] == "CCS"


def test_every_power_source_has_a_confidence() -> None:
    assert set(CONFIDENCE_FOR_SOURCE) == set(PowerSource)


# --- aggregation ---------------------------------------------------------------------------

def reported(normalized: str, power: float | None, count: int = 1,
             source: str = "reported") -> ResolvedPower:
    return ResolvedPower("raw", normalized, "dc_fast", count, power, source, "high")


def test_a_unit_with_no_present_connectors_is_unresolved() -> None:
    unit = aggregate_unit_capacity("u", "dc_fast", 1, [reported("CCS", 200.0, count=0)])
    assert unit.generic_service_capacity_kw is None
    assert unit.generic_capacity_basis == CapacityBasis.UNRESOLVED
    assert unit.connector_standards_available == ()


def test_a_unit_whose_connectors_have_no_resolved_power_is_unresolved() -> None:
    unit = aggregate_unit_capacity("u", "dc_fast", 1, [reported("CCS", None)])
    assert unit.generic_service_capacity_kw is None
    assert unit.generic_capacity_basis == CapacityBasis.UNRESOLVED


def test_the_weakest_resolution_governs_the_unit() -> None:
    """A capacity is only as trustworthy as its least trustworthy input."""
    unit = aggregate_unit_capacity(
        "u", "dc_fast", 1,
        [reported("CCS", 200.0, source="reported"),
         reported("CHAdeMO", 100.0, source="type_default")],
    )
    assert unit.power_source == PowerSource.TYPE_DEFAULT
    assert unit.power_confidence == PowerConfidence.LOW


def test_a_zero_unit_maximum_does_not_take_precedence() -> None:
    unit = aggregate_unit_capacity("u", "dc_fast", 1, [reported("CCS", 200.0)],
                                   unit_reported_maximum_kw=0.0)
    assert unit.generic_service_capacity_kw == 200.0
    assert unit.generic_capacity_basis == CapacityBasis.SINGLE_PORT_CONNECTOR_MAXIMUM


def test_the_best_power_per_standard_is_kept() -> None:
    unit = aggregate_unit_capacity(
        "u", "dc_fast", 1, [reported("CCS", 150.0), reported("CCS", 350.0)]
    )
    assert unit.connector_compatible_kw == {"CCS": 350.0}


def test_unit_capacity_serialises() -> None:
    payload = aggregate_unit_capacity("u", "dc_fast", 1, [reported("CCS", 200.0)]).to_dict()
    assert payload["generic_capacity_basis"] == "single_port_connector_maximum"
    assert payload["simultaneous_service_ports"] == 1


def test_site_capacity_tracks_unresolved_units_and_rung_1_share() -> None:
    resolved_unit = aggregate_unit_capacity("a", "dc_fast", 1, [reported("CCS", 200.0)])
    default_unit = aggregate_unit_capacity(
        "b", "dc_fast", 1, [reported("CCS", 150.0, source="type_default")])
    unresolved_unit = aggregate_unit_capacity("c", "dc_fast", 1, [reported("CCS", None)])
    site = aggregate_site_capacity("s", [resolved_unit, default_unit, unresolved_unit])
    assert site.unit_count == 3
    assert site.units_unresolved_capacity == 1
    assert site.generic_service_capacity_kw == 350.0
    assert site.rung_1_capacity_share == pytest.approx(200.0 / 350.0)
    assert site.ports_by_level == {"dc_fast": 3}


def test_an_empty_site_has_a_zero_confidence_share() -> None:
    site = aggregate_site_capacity("s", [])
    assert site.generic_service_capacity_kw == 0.0
    assert site.rung_1_capacity_share == 0.0
    assert site.to_dict()["site_id"] == "s"


def test_qualifies_for_level_uses_the_public_breakdown_only() -> None:
    """A private DC charger must not make a site a public DCFC site."""
    public_l2 = aggregate_unit_capacity("l2", "2", 1, [reported("J1772", 7.2)])
    private_dc = aggregate_unit_capacity("dc", "dc_fast", 1, [reported("CCS", 350.0)])
    site = aggregate_site_capacity("mixed", [public_l2, private_dc], [True, False])
    assert site.qualifies_for_level({"2"}) is True
    assert site.qualifies_for_level({"dc_fast"}) is False
    assert site.has_public_operational_service is True
    assert site.public_generic_service_capacity_kw == 7.2
    assert site.generic_service_capacity_kw == 357.2


def test_a_public_unit_with_unresolved_capacity_still_counts_as_public_service() -> None:
    """Presence of service and amount of capacity are separate questions."""
    unresolved = aggregate_unit_capacity("u", "dc_fast", 1, [reported("CCS", None)])
    site = aggregate_site_capacity("s", [unresolved], [True])
    assert site.has_public_operational_service is True
    assert site.public_unit_count == 1
    assert site.public_generic_service_capacity_kw == 0.0
    assert site.public_ports_by_level == {"dc_fast": 1}


def test_mismatched_public_flags_are_rejected() -> None:
    unit = aggregate_unit_capacity("u", "dc_fast", 1, [reported("CCS", 100.0)])
    with pytest.raises(ValueError, match="same length as units"):
        aggregate_site_capacity("s", [unit, unit], [True])


def test_omitting_the_public_flags_treats_every_unit_as_non_public() -> None:
    """A caller that has not established public status must not get public capacity."""
    unit = aggregate_unit_capacity("u", "dc_fast", 1, [reported("CCS", 100.0)])
    site = aggregate_site_capacity("s", [unit])
    assert site.generic_service_capacity_kw == 100.0
    assert site.public_generic_service_capacity_kw == 0.0
    assert site.has_public_operational_service is False
