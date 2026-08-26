"""Unit tests for the access model, distance, population allocation, and preflights."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.model.access import (
    AccessConfigError,
    AccessResult,
    compute_access,
    load_thresholds,
    qualifying_sites,
)
from pipeline.model.preflight import (
    DIAMETER_BANDS_M,
    MAX_EXACT_DIAMETER_STATIONS,
    ReconciliationClass,
    _int_or_none,
    classify_exception,
    cluster_diameter_m,
    diagnose_sites,
    reconcile_stations,
)
from pipeline.spatial.allocation import (
    AllocationError,
    PopulationPoint,
    allocate_by_population,
    allocate_many,
    conservation_error,
    population_weights,
)
from pipeline.spatial.distance import nearest_site_distances

# --- distance ----------------------------------------------------------------------

def test_nearest_returns_the_closest_site_and_its_index() -> None:
    result = nearest_site_distances([44.9], [-93.0], [45.5, 44.95], [-93.0, -93.0])
    assert result.indices[0] == 1
    assert result.distances_m[0] == pytest.approx(5560, abs=50)
    assert len(result) == 1


def test_no_sites_anywhere_is_an_infinite_gap_not_missing_data() -> None:
    """Directive D8: the strongest possible access gap, not a dropped record."""
    result = nearest_site_distances([44.9, 45.0], [-93.0, -93.0], [], [])
    assert result.distances_m == (float("inf"), float("inf"))
    assert result.indices == (-1, -1)


def test_no_query_points_returns_nothing() -> None:
    assert len(nearest_site_distances([], [], [44.9], [-93.0])) == 0


def test_mismatched_input_lengths_raise() -> None:
    with pytest.raises(ValueError, match="query latitude"):
        nearest_site_distances([1.0], [1.0, 2.0], [1.0], [1.0])
    with pytest.raises(ValueError, match="site latitude"):
        nearest_site_distances([1.0], [1.0], [1.0, 2.0], [1.0])


# --- population allocation ------------------------------------------------------------

def rural_tract() -> list[PopulationPoint]:
    """A large rural tract whose population sits in one corner.

    This is the fixture CLAUDE.md 7.6 exists for: area weighting would spread the
    tract's quantity evenly across its cells, when in fact 95.7% of the people are in
    one of them.
    """
    return [
        PopulationPoint("blk_town", "27001770100", 4500, 46.70, -93.40),
        PopulationPoint("blk_farm1", "27001770100", 120, 46.90, -93.90),
        PopulationPoint("blk_farm2", "27001770100", 80, 46.60, -93.10),
    ]


def test_population_weighting_beats_area_weighting_on_a_hand_computed_rural_fixture(
) -> None:
    points = rural_tract()
    targets = {"blk_town": "cell_A", "blk_farm1": "cell_B", "blk_farm2": "cell_C"}
    allocated = allocate_by_population("27001770100", 1000.0, points, targets)
    by_cell = {a.target_id: a for a in allocated}

    # Hand-computed: 4500/4700 = 0.9574468..., 120/4700, 80/4700.
    assert by_cell["cell_A"].value == pytest.approx(957.4468, abs=1e-3)
    assert by_cell["cell_B"].value == pytest.approx(25.5319, abs=1e-3)
    assert by_cell["cell_C"].value == pytest.approx(17.0213, abs=1e-3)
    # Area weighting would have given each cell 333.33.
    assert by_cell["cell_A"].value > 900.0
    assert conservation_error(allocated, 1000.0) == pytest.approx(0.0, abs=1e-9)
    assert all(a.weight_basis == "population" for a in allocated)


def test_points_sharing_a_target_are_combined() -> None:
    points = rural_tract()
    targets = {"blk_town": "cell_A", "blk_farm1": "cell_A", "blk_farm2": "cell_B"}
    allocated = allocate_by_population("27001770100", 1000.0, points, targets)
    assert len(allocated) == 2
    combined = next(a for a in allocated if a.target_id == "cell_A")
    assert combined.population == 4620
    assert combined.value == pytest.approx(4620 / 4700 * 1000.0)


def test_weights_sum_to_one() -> None:
    weights = population_weights(rural_tract())
    assert sum(weights.values()) == pytest.approx(1.0)


def test_a_zero_population_geography_cannot_be_population_weighted() -> None:
    """An equal split would silently reintroduce the uniform-density assumption."""
    points = [PopulationPoint("a", "geo", 0, 1.0, 1.0),
              PopulationPoint("b", "geo", 0, 2.0, 2.0)]
    with pytest.raises(AllocationError, match="zero total population"):
        population_weights(points)


def test_allocating_a_geography_with_no_points_raises() -> None:
    with pytest.raises(AllocationError, match="no population points"):
        allocate_by_population("geo", 1.0, [], {})


def test_a_point_without_a_target_raises_rather_than_defaulting() -> None:
    with pytest.raises(AllocationError, match="no target cell"):
        allocate_by_population("geo", 1.0, rural_tract(), {"blk_town": "cell_A"})


def test_allocate_many_reports_unallocatable_geographies() -> None:
    points = {"good": rural_tract(), "empty": []}
    targets = {p.point_id: "cell" for p in rural_tract()}
    allocated, unallocatable = allocate_many(
        [("good", 100.0), ("empty", 50.0)], points, targets)
    assert len(allocated) == 1
    assert unallocatable[0][0] == "empty"


def test_allocated_quantity_serialises() -> None:
    allocated = allocate_by_population(
        "geo", 10.0, rural_tract(),
        {p.point_id: "cell" for p in rural_tract()})[0].to_dict()
    assert allocated["weight_basis"] == "population"
    assert allocated["population"] == 4700


# --- access thresholds ------------------------------------------------------------------

def test_the_shipped_thresholds_load() -> None:
    thresholds = load_thresholds()
    assert thresholds.dcfc_gap_km == 16.1
    assert thresholds.l2_gap_km == 8.05
    assert len(thresholds.sensitivity_km) == 80
    assert thresholds.dcfc_levels == {"dc_fast"}


def test_missing_thresholds_config_raises(tmp_path: Path) -> None:
    with pytest.raises(AccessConfigError, match="thresholds configuration missing"):
        load_thresholds(tmp_path / "absent.yml")


def test_thresholds_without_both_sections_raise(tmp_path: Path) -> None:
    path = tmp_path / "t.yml"
    path.write_text("access: {}\n", encoding="utf-8")
    with pytest.raises(AccessConfigError, match="must declare both"):
        load_thresholds(path)


def test_a_non_advancing_sensitivity_range_raises(tmp_path: Path) -> None:
    path = tmp_path / "t.yml"
    path.write_text(
        "access:\n  dcfc_gap_km: 16.1\n  l2_gap_km: 8.0\n"
        "  sensitivity_km: {start: 1.0, stop: 1.0, step: 0.0}\n"
        "supply:\n  dcfc_levels: [dc_fast]\n  l2_levels: ['2']\n"
        "  operational_status_codes: [E]\n  public_access_codes: [public]\n",
        encoding="utf-8",
    )
    with pytest.raises(AccessConfigError, match="empty or non-advancing"):
        load_thresholds(path)


# --- site eligibility ---------------------------------------------------------------------

def site(**kw: object) -> dict[str, object]:
    base = {"site_id": "s", "latitude": 44.9, "longitude": -93.0, "status_code": "E",
            "access_code": "public", "ports_by_level": {"dc_fast": 2}}
    base.update(kw)
    return base


def test_only_public_operational_sites_qualify() -> None:
    """Domain rules G2 and G3, applied in the access path."""
    thresholds = load_thresholds()
    candidates = [site(), site(status_code="T"), site(access_code="private")]
    assert len(qualifying_sites(candidates, thresholds.dcfc_levels, thresholds)) == 1


def test_a_site_without_the_required_level_does_not_qualify() -> None:
    thresholds = load_thresholds()
    l2_only = site(ports_by_level={"2": 4})
    assert qualifying_sites([l2_only], thresholds.dcfc_levels, thresholds) == []
    assert len(qualifying_sites([l2_only], thresholds.l2_levels, thresholds)) == 1


def test_a_site_with_no_level_breakdown_does_not_qualify() -> None:
    thresholds = load_thresholds()
    assert qualifying_sites([site(ports_by_level={})], thresholds.dcfc_levels,
                            thresholds) == []


# --- access computation ---------------------------------------------------------------------

def population(n: int = 3) -> list[PopulationPoint]:
    return [PopulationPoint(f"p{i}", "geo", 1000, 44.9 + i * 0.5, -93.0)
            for i in range(n)]


def test_access_measures_population_beyond_the_threshold() -> None:
    thresholds = load_thresholds()
    result = compute_access(population(), [site()], thresholds, "DCFC")
    assert result.population_total == 3000
    assert result.sites_considered == 1
    # Points at +0.5 and +1.0 degrees latitude are ~55 km and ~111 km away.
    assert result.population_in_gap == 2000
    assert result.share_in_gap == pytest.approx(2 / 3)
    assert result.points_in_gap == 2


def test_the_metric_is_named_for_what_it_measures() -> None:
    """A DCFC-only measure is never called a desert (CLAUDE.md 11.5). copy-lint: allow"""
    thresholds = load_thresholds()
    dcfc = compute_access(population(1), [site()], thresholds, "DCFC")
    l2 = compute_access(population(1), [site()], thresholds, "L2")
    assert dcfc.metric_name == "DCFC access gap"
    assert l2.metric_name == "L2 access gap"
    assert "desert" not in dcfc.metric_name.lower()


def test_the_sensitivity_curve_is_produced_and_monotonic() -> None:
    """A threshold never ships without its curve."""
    thresholds = load_thresholds()
    result = compute_access(population(5), [site()], thresholds, "DCFC")
    curve = [pop for _, pop in result.sensitivity_curve]
    assert len(curve) == 80
    assert curve == sorted(curve, reverse=True), (
        "population in gap must fall monotonically as the threshold widens"
    )


def test_access_with_no_sites_puts_everyone_in_the_gap() -> None:
    thresholds = load_thresholds()
    result = compute_access(population(4), [], thresholds, "DCFC")
    assert result.population_in_gap == result.population_total
    assert result.median_distance_km == float("inf")


def test_access_with_no_population_does_not_divide_by_zero() -> None:
    thresholds = load_thresholds()
    result = compute_access([], [site()], thresholds, "DCFC")
    assert result.population_total == 0
    assert result.share_in_gap == 0.0


def test_access_result_serialises_with_its_interpretation() -> None:
    thresholds = load_thresholds()
    payload = compute_access(population(2), [site()], thresholds, "DCFC").to_dict()
    assert payload["distance_basis"] == "straight_line_haversine"
    assert "LOWER BOUND" in payload["interpretation"]
    assert len(payload["sensitivity_curve"]) == 80


def test_access_result_dataclass_is_immutable() -> None:
    result = AccessResult("DCFC", 16.1, 1, 0, 1, 0, 1, 1.0, ())
    with pytest.raises(AttributeError):
        result.threshold_km = 2.0  # type: ignore[misc]


# --- preflight: reconciliation -----------------------------------------------------------------

def station(units: int = 2, l1: object = None, l2: object = 2, dcfc: object = None,
            levels: tuple[str, ...] = ("2", "2"), status: str = "E") -> dict[str, object]:
    return {
        "id": 1, "status_code": status, "access_code": "public", "ev_network": "N",
        "ev_level1_evse_num": l1, "ev_level2_evse_num": l2, "ev_dc_fast_num": dcfc,
        "ev_charging_units": [
            {"charging_level": levels[i] if i < len(levels) else "2",
             "connectors": {"J1772": {"port_count": 1}}}
            for i in range(units)
        ],
    }


def test_a_reconciling_station_produces_no_exception() -> None:
    result = reconcile_stations([station()])
    assert result["exception_count"] == 0
    assert result["reconciliation_rate"] == 1.0


def test_a_legacy_unit_explains_a_count_mismatch() -> None:
    result = reconcile_stations([station(units=3, l2=2, levels=("2", "2", "legacy"))])
    assert result["exception_count"] == 1
    assert result["exceptions"][0]["classification"] == "legacy_charging_level"
    assert result["exceptions"][0]["difference"] == 1


def test_a_planned_station_with_no_units_is_classified() -> None:
    result = reconcile_stations([station(units=0, l1=None, l2=None, dcfc=None,
                                         levels=(), status="P")])
    assert result["exceptions"][0]["classification"] == "no_unit_records"


def test_a_station_with_no_aggregate_at_all_is_classified() -> None:
    result = reconcile_stations([station(units=2, l1=None, l2=None, dcfc=None)])
    assert result["exceptions"][0]["classification"] == "missing_station_aggregate"


def test_an_unexplained_mismatch_is_classified_as_upstream() -> None:
    result = reconcile_stations([station(units=5, l2=2)])
    assert result["exceptions"][0]["classification"] == "upstream_count_mismatch"


def test_the_unresolved_classification_exists_for_genuinely_unexplained_cases() -> None:
    assert classify_exception(3, None, [1, None, None], ("2",)) is (
        ReconciliationClass.UNRESOLVED)


def test_reconcile_records_the_never_call_it_100_percent_note() -> None:
    assert "100%" in reconcile_stations([station()])["note"]


def test_reconcile_handles_zero_stations() -> None:
    result = reconcile_stations([])
    assert result["stations_examined"] == 0
    assert result["reconciliation_rate"] == 0.0


@pytest.mark.parametrize(("value", "expected"),
                         [("5", 5), (5, 5), (5.0, 5), (None, None), ("", None), ("x", None)])
def test_int_or_none_helper(value: object, expected: int | None) -> None:
    assert _int_or_none(value) == expected


# --- preflight: site diagnostic -------------------------------------------------------------------

def test_cluster_diameter_is_the_maximum_pairwise_distance() -> None:
    """Transitive chaining: A-B 40 m, B-C 40 m, but the cluster spans 80 m."""
    points = [(44.9, -93.0), (44.90036, -93.0), (44.90072, -93.0)]
    assert cluster_diameter_m(points) == pytest.approx(80.0, abs=1.0)


def test_a_singleton_cluster_has_zero_diameter() -> None:
    assert cluster_diameter_m([(44.9, -93.0)]) == 0.0
    assert cluster_diameter_m([]) == 0.0


def test_diameter_sampling_is_capped() -> None:
    points = [(44.9 + i * 0.0001, -93.0) for i in range(MAX_EXACT_DIAMETER_STATIONS + 40)]
    assert cluster_diameter_m(points) > 0.0


def assignment(site_id: str, station_id: str, lat: float, lon: float,
               network: str = "N", name: str = "x") -> dict[str, object]:
    return {"site_id": site_id, "station_id": station_id, "latitude": lat,
            "longitude": lon, "ev_network": network, "station_name": name}


def test_the_diagnostic_reports_size_and_diameter_distributions() -> None:
    rows = [
        assignment("s1", "a", 44.9, -93.0),
        assignment("s1", "b", 44.90036, -93.0, network="M", name="y"),
        assignment("s2", "c", 45.5, -93.0),
    ]
    result = diagnose_sites(rows)
    assert result["clusters"] == 2
    assert result["stations"] == 3
    assert result["singleton_clusters"] == 1
    assert result["multi_station_clusters"] == 1
    assert result["clusters_with_at_least"]["2"] == 1
    assert result["diameter_m"]["max"] == pytest.approx(40.0, abs=1.0)
    assert set(result["clusters_exceeding_diameter"]) == {
        str(int(b)) for b in DIAMETER_BANDS_M}


def test_a_pathological_cluster_is_listed_for_review() -> None:
    rows = [assignment("s1", str(i), 44.9 + i * 0.002, -93.0) for i in range(3)]
    result = diagnose_sites(rows)
    assert result["suspicious_cluster_count"] == 1
    assert result["suspicious_clusters"][0]["diameter_m"] > 200.0


def test_the_diagnostic_skips_points_without_coordinates() -> None:
    rows: list[dict[str, object]] = [
        assignment("s1", "a", 44.9, -93.0),
        {"site_id": "s1", "station_id": "b", "latitude": None, "longitude": None},
    ]
    result = diagnose_sites(rows)
    assert result["clusters"] == 1
    assert result["diameter_m"]["max"] == 0.0


def test_the_diagnostic_handles_no_clusters() -> None:
    result = diagnose_sites([])
    assert result["clusters"] == 0
    assert result["singleton_share"] == 0.0
    assert result["diameter_m"]["max"] == 0.0
    assert result["suspicious_share_of_multi"] == 0.0


def test_the_diagnostic_explains_transitive_connectivity() -> None:
    assert "transitive" in diagnose_sites([])["note"]


def test_classify_returns_reconciles_when_counts_match() -> None:
    """The non-exception path, reachable directly as well as through reconcile."""
    assert classify_exception(3, 3, [None, 3, None], ("2",)) is (
        ReconciliationClass.RECONCILES)
