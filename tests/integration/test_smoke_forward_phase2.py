"""Forward-viability smoke test for Phase 2 (gate part G-D).

Phase 2's core operation is the supply power-resolution ladder (CLAUDE.md section
7.1): every port carries ``power_kw``, ``power_source`` and ``power_confidence``,
resolved through three rungs.

    rung 1  reported connector or unit power        power_source = reported     high
    rung 2  empirical median for (network, type)    empirical_fallback          medium
    rung 3  documented type default                 type_default                low

This test exercises **rung 1 only**, against the real canonical tables produced by
Phase 1 on the two-state fixture. It proves the data shape works. It does not
implement rungs 2 or 3, and it proves nothing about aggregation correctness, site
collapsing, or the accuracy of any power value.
"""

from __future__ import annotations

import pandas as pd

from pipeline.transform.runner import Warehouse

CONNECTOR_LEVELS = {
    "J1772": "2", "NEMA515": "1", "NEMA520": "1", "NEMA1450": "1",
    "J1772COMBO": "dc_fast", "CHADEMO": "dc_fast", "TESLA": "dc_fast", "J3271": "dc_fast",
}


def resolve_rung_one(connectors: pd.DataFrame) -> pd.DataFrame:
    """The minimal Phase 2 operation: assign rung-1 power where it is reported."""
    frame = connectors.reset_index(drop=True).copy()
    reported = frame["power_kw"].notna() & (frame["power_kw"] > 0)
    frame["resolved_power_kw"] = frame["power_kw"].where(reported)
    frame["power_source"] = pd.Series("reported", index=frame.index).where(reported)
    frame["power_confidence"] = pd.Series("high", index=frame.index).where(reported)
    return frame


def test_rung_one_resolves_against_the_real_canonical_tables(
    fixture_warehouse: Warehouse,
) -> None:
    connectors = fixture_warehouse.fetch_df("mart_charging_unit_connectors")
    present = connectors[connectors["connector_count"] > 0]
    assert len(present) > 0, "the fixture must contain connectors"

    resolved = resolve_rung_one(present)
    reported = resolved[resolved["power_source"] == "reported"]
    assert len(reported) > 0, "some rung-1 power must resolve"
    assert (reported["resolved_power_kw"] > 0).all()
    assert set(reported["power_confidence"]) == {"high"}

    share = len(reported) / len(resolved)
    assert 0.0 < share < 1.0, (
        f"rung-1 coverage is {share:.1%}; rungs 2 and 3 exist precisely because it "
        "is neither zero nor complete"
    )


def test_the_entity_hierarchy_joins_without_orphans(
    fixture_warehouse: Warehouse,
) -> None:
    """site -> station -> charging_unit -> (unit, connector_type) must resolve."""
    orphan_units = fixture_warehouse.connection.execute(
        "SELECT count(*) FROM mart_charging_units u "
        "LEFT JOIN mart_stations s USING (station_id) WHERE s.station_id IS NULL"
    ).fetchone()
    assert orphan_units is not None and orphan_units[0] == 0

    orphan_connectors = fixture_warehouse.connection.execute(
        "SELECT count(*) FROM mart_charging_unit_connectors c "
        "LEFT JOIN mart_charging_units u USING (charging_unit_record_key) "
        "WHERE u.charging_unit_record_key IS NULL"
    ).fetchone()
    assert orphan_connectors is not None and orphan_connectors[0] == 0

    orphan_stations = fixture_warehouse.connection.execute(
        "SELECT count(*) FROM mart_stations s "
        "LEFT JOIN mart_sites x USING (site_id) WHERE x.site_id IS NULL"
    ).fetchone()
    assert orphan_stations is not None and orphan_stations[0] == 0


def test_no_ports_table_was_fabricated(fixture_warehouse: Warehouse) -> None:
    """CLAUDE.md 6.1.1: no `ports` row may exist whose identity the source lacks.

    The Phase 1 identifiability analysis found no stable port identifier, so the
    canonical model stops at charging_unit and the ports table is not populated. This
    is the gate criterion that stops Phase 2 inventing one.
    """
    tables = fixture_warehouse.table_names()
    assert "mart_ports" not in tables
    assert "ports" not in tables

    units = fixture_warehouse.fetch_df("mart_charging_units")
    assert units["key_is_synthetic"].all()
    assert not units["has_longitudinal_identity"].any()
    # Every unit is exactly one port, which is why capacity is still computable.
    assert set(units["port_count"].unique()) == {1}


def test_capacity_is_computable_from_units_despite_absent_identity(
    fixture_warehouse: Warehouse,
) -> None:
    """The finding that makes Phase 2 viable at all."""
    row = fixture_warehouse.connection.execute(
        "SELECT sum(port_count) FROM mart_charging_units WHERE is_public_operational"
    ).fetchone()
    assert row is not None and row[0] > 0


def test_power_confidence_share_can_be_computed_per_site(
    fixture_warehouse: Warehouse,
) -> None:
    """Section 7.1 requires `power_confidence_share` per hex; per site is the input."""
    frame = fixture_warehouse.connection.execute(
        "SELECT u.site_id, "
        "  sum(CASE WHEN c.has_reported_power THEN c.connector_count ELSE 0 END) AS rung1, "
        "  sum(c.connector_count) AS total "
        "FROM mart_charging_unit_connectors c "
        "JOIN mart_charging_units u USING (charging_unit_record_key) "
        "WHERE c.connector_count > 0 GROUP BY u.site_id"
    ).df()
    assert len(frame) > 0
    frame["share"] = frame["rung1"] / frame["total"]
    assert frame["share"].between(0.0, 1.0).all()
