"""Hex aggregation: demand is conserved and Phase 3's provenance survives the step."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.model.build_demand import TractEstimate
from pipeline.model.hexes import (
    HexAggregationError,
    HexCell,
    HexSupply,
    assert_demand_conserved,
    assert_provenance_survived,
    build_hexes,
    load_hex_supply,
)
from pipeline.model.uncertainty import COMPONENT_NAMES
from pipeline.spatial.h3_grid import PopulationPoint, tract_cell_weights

SEATTLE = (47.6062, -122.3321)
SPOKANE = (47.6588, -117.4260)


def components(value: float = 0.2) -> dict[str, float]:
    return dict.fromkeys(COMPONENT_NAMES, value)


def estimate(geoid: str, demand: float, grain: str = "native_tract",
             tier: str = "A", provenance: str = "native_registry_observed_count",
             uncertainty: float = 0.2, population: float = 1000.0) -> TractEstimate:
    return TractEstimate(
        geoid=geoid, state_fips=geoid[:2], households=400.0, population=population,
        equity_population=population * 0.25, raw_estimate=demand, estimate=demand,
        evidence_grain=grain, estimate_method="modeled",
        uncertainty_score=uncertainty, uncertainty_components=components(uncertainty),
        confidence_tier=tier, constraint_name="c", constraint_vintage="v",
        value_provenance=provenance,
    )


def point(tract: str, population: float, latlon: tuple[float, float],
          bg: str = "1") -> PopulationPoint:
    return PopulationPoint(tract, bg, population, latlon[0], latlon[1])


# --- conservation --------------------------------------------------------------------

def test_demand_is_conserved_across_the_aggregation() -> None:
    weights = tract_cell_weights([point("53033000100", 900.0, SEATTLE),
                                  point("53033000100", 100.0, SPOKANE, "2")])
    rows = [estimate("53033000100", 100.0)]
    cells, unallocated = build_hexes(rows, weights)
    assert_demand_conserved(rows, cells, unallocated)
    assert len(cells) == 2
    assert sum(c.demand_bev for c in cells) == pytest.approx(100.0)
    assert max(c.demand_bev for c in cells) == pytest.approx(90.0)


def test_a_tract_with_no_weights_is_reported_not_dropped() -> None:
    weights = tract_cell_weights([point("53033000100", 10.0, SEATTLE)])
    rows = [estimate("53033000100", 5.0), estimate("53999999999", 7.0)]
    cells, unallocated = build_hexes(rows, weights)
    assert unallocated == {"53999999999": 7.0}
    assert_demand_conserved(rows, cells, unallocated)


def test_lost_demand_is_refused() -> None:
    rows = [estimate("53033000100", 100.0)]
    with pytest.raises(HexAggregationError, match="lost demand"):
        assert_demand_conserved(rows, [], {})


# --- provenance survives -------------------------------------------------------------

def test_evidence_grain_and_tier_shares_survive_aggregation() -> None:
    """A hex reporting demand alone would throw away all of Phase 3's work."""
    weights = tract_cell_weights([point("53033000100", 1.0, SEATTLE),
                                  point("53033000200", 1.0, SEATTLE)])
    rows = [estimate("53033000100", 75.0, "native_tract", "A"),
            estimate("53033000200", 25.0, "state_total_only", "C")]
    cells, _ = build_hexes(rows, weights)
    assert len(cells) == 1
    cell = cells[0]
    assert cell.evidence_grain_share["native_tract"] == pytest.approx(0.75)
    assert cell.evidence_grain_share["state_total_only"] == pytest.approx(0.25)
    assert cell.confidence_tier_share["A"] == pytest.approx(0.75)
    assert cell.sub_state_anchored_share == pytest.approx(0.75)
    assert cell.dominant_evidence_grain == "native_tract"
    assert_provenance_survived(cells)


def test_shares_are_weighted_by_demand_not_by_tract_count() -> None:
    """A cell 95% of whose demand is well evidenced is mostly well evidenced."""
    weights = tract_cell_weights([point("53033000100", 1.0, SEATTLE),
                                  point("53033000200", 1.0, SEATTLE)])
    rows = [estimate("53033000100", 95.0, "native_tract"),
            estimate("53033000200", 5.0, "state_total_only")]
    cell = build_hexes(rows, weights)[0][0]
    assert cell.evidence_grain_share["native_tract"] == pytest.approx(0.95)
    assert cell.tracts_contributing == 2


def test_a_zero_demand_cell_still_reports_whose_evidence_it_rests_on() -> None:
    """It is a legitimate candidate location and must not lose its provenance."""
    weights = tract_cell_weights([point("53033000100", 500.0, SEATTLE)])
    cells, _ = build_hexes([estimate("53033000100", 0.0)], weights)
    assert cells[0].demand_bev == 0.0
    assert cells[0].evidence_grain_share == {"native_tract": pytest.approx(1.0)}
    assert_provenance_survived(cells)


def test_a_cell_with_neither_demand_nor_population_still_carries_shares() -> None:
    weights = tract_cell_weights([point("53033000100", 0.0, SEATTLE)])
    cells, _ = build_hexes([estimate("53033000100", 0.0, population=0.0)], weights)
    assert_provenance_survived(cells)
    assert cells[0].evidence_grain_share == {"native_tract": pytest.approx(1.0)}


def test_all_five_uncertainty_components_survive() -> None:
    weights = tract_cell_weights([point("53033000100", 1.0, SEATTLE)])
    cell = build_hexes([estimate("53033000100", 10.0, uncertainty=0.4)], weights)[0][0]
    assert set(cell.uncertainty_components) == set(COMPONENT_NAMES)
    assert cell.uncertainty_score == pytest.approx(0.4)
    assert all(v == pytest.approx(0.4) for v in cell.uncertainty_components.values())


def test_a_cell_missing_its_provenance_is_refused() -> None:
    bare = HexCell("x", 6, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1, 1.0, 0.1,
                   components(), {}, {"A": 1.0}, {"p": 1.0})
    with pytest.raises(HexAggregationError, match="no evidence-grain breakdown"):
        assert_provenance_survived([bare])


def test_a_cell_missing_an_uncertainty_component_is_refused() -> None:
    partial = HexCell("x", 6, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1, 1.0, 0.1,
                      {"prediction_interval": 0.1}, {"native_tract": 1.0},
                      {"A": 1.0}, {"p": 1.0})
    with pytest.raises(HexAggregationError, match="missing uncertainty components"):
        assert_provenance_survived([partial])


def test_shares_that_do_not_sum_to_one_are_refused() -> None:
    broken = HexCell("x", 6, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1, 1.0, 0.1,
                     components(), {"native_tract": 0.5}, {"A": 1.0}, {"p": 1.0})
    with pytest.raises(HexAggregationError, match="shares sum to"):
        assert_provenance_survived([broken])


def test_the_published_row_carries_everything_a_reader_needs() -> None:
    weights = tract_cell_weights([point("53033000100", 1.0, SEATTLE)])
    payload = build_hexes([estimate("53033000100", 10.0)], weights)[0][0].to_dict()
    for key in ("h3_index", "demand_bev", "equity_population", "uncertainty_score",
                "uncertainty_components", "evidence_grain_share",
                "confidence_tier_share", "value_provenance_share",
                "sub_state_anchored_share", "dominant_evidence_grain"):
        assert key in payload, key
    # A-2.2: no imputed capacity reaches the siting layer.
    assert "capacity_kw" not in payload


def test_a_cell_with_no_shares_reports_no_dominant_grain() -> None:
    bare = HexCell("x", 6, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0, 0.0, 0.0,
                   components(), {}, {}, {})
    assert bare.dominant_evidence_grain == "none"
    assert bare.sub_state_anchored_share == pytest.approx(1.0)


# --- supply --------------------------------------------------------------------------

def test_supply_attaches_to_cells_and_carries_no_kilowatt_figure(
    tmp_path: Path,
) -> None:
    """A-2.2 is respected structurally: HexSupply has no capacity field at all."""
    assert not hasattr(HexSupply(), "capacity_kw")
    snapshot = tmp_path / "stations.json"
    snapshot.write_text(json.dumps({"fuel_stations": [{
        "id": 1, "latitude": SEATTLE[0], "longitude": SEATTLE[1],
        "status_code": "E", "access_code": "public",
        "ev_charging_units": [
            {"port_count": 4, "charging_level": "dc_fast", "connectors": {}},
            {"port_count": 2, "charging_level": "2", "connectors": {}},
        ]}]}), encoding="utf-8")
    supply = load_hex_supply(snapshot)
    assert len(supply) == 1
    entry = next(iter(supply.values()))
    assert entry.dcfc_ports == 4.0
    assert entry.l2_ports == 2.0
    assert entry.site_count == 1


def test_private_and_non_operational_supply_is_excluded(tmp_path: Path) -> None:
    """Domain rules G2 and G3, imported from Phase 2 rather than restated."""
    snapshot = tmp_path / "stations.json"
    snapshot.write_text(json.dumps({"fuel_stations": [
        {"id": 1, "latitude": SEATTLE[0], "longitude": SEATTLE[1],
         "status_code": "T", "access_code": "public",
         "ev_charging_units": [{"port_count": 9, "charging_level": "dc_fast",
                                "connectors": {}}]},
        {"id": 2, "latitude": SEATTLE[0], "longitude": SEATTLE[1],
         "status_code": "E", "access_code": "private",
         "ev_charging_units": [{"port_count": 9, "charging_level": "dc_fast",
                                "connectors": {}}]},
    ]}), encoding="utf-8")
    assert load_hex_supply(snapshot) == {}


def test_a_station_with_unusable_coordinates_is_skipped(tmp_path: Path) -> None:
    snapshot = tmp_path / "stations.json"
    snapshot.write_text(json.dumps({"fuel_stations": [{
        "id": 1, "latitude": None, "longitude": None,
        "status_code": "E", "access_code": "public",
        "ev_charging_units": [{"port_count": 4, "charging_level": "dc_fast",
                               "connectors": {}}]}]}), encoding="utf-8")
    assert load_hex_supply(snapshot) == {}


def test_the_national_supply_snapshot_places_real_sites() -> None:
    supply = load_hex_supply()
    assert len(supply) > 5000
    assert sum(v.dcfc_ports for v in supply.values()) > 50_000


def test_weighted_shares_is_empty_when_nothing_carries_weight() -> None:
    from pipeline.model.hexes import _weighted_shares

    assert _weighted_shares([("a", 0.0), ("b", 0.0)]) == {}
    assert _weighted_shares([("a", 1.0), ("a", 3.0)]) == {"a": pytest.approx(1.0)}


def test_a_block_group_with_no_population_contributes_no_cell() -> None:
    """One empty block group in an otherwise populated tract yields a zero weight, and a
    zero-weight cell must not appear in the output at all."""
    weights = tract_cell_weights([point("53033000100", 0.0, SPOKANE),
                                  point("53033000100", 100.0, SEATTLE, "2")])
    assert weights["53033000100"].weights[
        next(iter(k for k, v in weights["53033000100"].weights.items() if v == 0.0))
    ] == 0.0
    cells, _ = build_hexes([estimate("53033000100", 50.0)], weights)
    assert len(cells) == 1
    assert cells[0].demand_bev == pytest.approx(50.0)
