"""Unit tests for geography identification, crosswalking and site clustering."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.spatial.clustering import (
    DEFAULT_EPS_M,
    EARTH_RADIUS_M,
    SiteAssignment,
    cluster_sites,
    haversine_m,
)
from pipeline.spatial.crosswalk import (
    CROSSWALK_SOURCE,
    AllocationLink,
    WeightBasis,
    allocate,
    allocate_many,
    conservation_error,
    load_zcta_tract_links,
    zip_to_zcta,
)
from pipeline.spatial.geography import (
    COUNTY_REFERENCE,
    EstimateMethod,
    EvidenceGrain,
    GeographyError,
    SourceGeography,
    county_fips_lookup,
    estimate_method_for,
    evidence_grain_for,
    normalise_zip,
    resolve_county_fips,
)

# --- geography ---------------------------------------------------------------------

def test_county_lookup_is_keyed_by_state_and_name(tmp_path: Path) -> None:
    reference = tmp_path / "counties.txt"
    reference.write_text(
        "STATE|STATEFP|COUNTYFP|COUNTYNS|COUNTYNAME|CLASSFP|FUNCSTAT\n"
        "MN|27|031|00659461|Cook County|H1|A\n"
        "IL|17|031|01784766|Cook County|H1|A\n",
        encoding="utf-8",
    )
    lookup = county_fips_lookup.__wrapped__(reference)
    assert lookup[("MN", "Cook County")] == "27031"
    assert lookup[("IL", "Cook County")] == "17031"


def test_g13_same_county_code_in_two_states_is_only_separated_by_the_state_prefix(
    tmp_path: Path,
) -> None:
    """MN and IL Cook are both county 031; a bare county code would collide."""
    reference = tmp_path / "counties.txt"
    reference.write_text(
        "STATE|STATEFP|COUNTYFP|COUNTYNS|COUNTYNAME|CLASSFP|FUNCSTAT\n"
        "MN|27|031|1|Cook County|H1|A\nIL|17|031|2|Cook County|H1|A\n", encoding="utf-8")
    lookup = county_fips_lookup.__wrapped__(reference)
    assert lookup[("MN", "Cook County")][2:] == lookup[("IL", "Cook County")][2:] == "031"
    assert lookup[("MN", "Cook County")] != lookup[("IL", "Cook County")]


def test_resolve_county_fips_accepts_a_missing_county_suffix() -> None:
    lookup = {("MN", "Cook County"): "27031"}
    assert resolve_county_fips("MN", "Cook", lookup) == "27031"
    assert resolve_county_fips("mn", " Cook County ", lookup) == "27031"


def test_resolve_county_fips_raises_rather_than_guessing() -> None:
    with pytest.raises(GeographyError, match="collide across states"):
        resolve_county_fips("MN", "Nowhere County", {("MN", "Cook County"): "27031"})


def test_missing_county_reference_raises_with_the_fetch_url(tmp_path: Path) -> None:
    with pytest.raises(GeographyError, match="national_county2020"):
        county_fips_lookup.__wrapped__(tmp_path / "absent.txt")


def test_empty_county_reference_raises(tmp_path: Path) -> None:
    reference = tmp_path / "counties.txt"
    reference.write_text("STATE|STATEFP|COUNTYFP|COUNTYNS|COUNTYNAME\n", encoding="utf-8")
    with pytest.raises(GeographyError, match="zero counties"):
        county_fips_lookup.__wrapped__(reference)


def test_the_real_county_reference_is_present_and_holds_the_cook_collision() -> None:
    if not COUNTY_REFERENCE.exists():  # pragma: no cover - fetched into the cache
        pytest.skip("county reference not cached")
    lookup = county_fips_lookup()
    assert lookup[("MN", "Cook County")] == "27031"
    assert lookup[("IL", "Cook County")] == "17031"
    assert lookup[("GA", "Cook County")] == "13075"


@pytest.mark.parametrize(
    ("source", "grain", "method"),
    [
        (SourceGeography.TRACT, EvidenceGrain.NATIVE_TRACT, EstimateMethod.DIRECTLY_OBSERVED),
        (SourceGeography.USPS_ZIP, EvidenceGrain.ZIP_ANCHORED, EstimateMethod.CROSSWALKED),
        (SourceGeography.ZCTA, EvidenceGrain.ZIP_ANCHORED, EstimateMethod.CROSSWALKED),
        (SourceGeography.COUNTY, EvidenceGrain.COUNTY_ANCHORED, EstimateMethod.CROSSWALKED),
        (SourceGeography.STATE, EvidenceGrain.STATE_TOTAL_ONLY, EstimateMethod.CROSSWALKED),
    ],
)
def test_grain_and_method_are_derived_not_assumed(
    source: SourceGeography, grain: EvidenceGrain, method: EstimateMethod
) -> None:
    assert evidence_grain_for(source) is grain
    assert estimate_method_for(source) is method


def test_only_a_tract_source_earns_directly_observed() -> None:
    """CLAUDE.md 7.4.1: no ZIP- or county-derived tract value may be directly observed."""
    for source in SourceGeography:
        method = estimate_method_for(source, SourceGeography.TRACT)
        if source is not SourceGeography.TRACT:
            assert method is not EstimateMethod.DIRECTLY_OBSERVED, source


def test_normalise_zip_preserves_leading_zeros_and_rejects_short_input() -> None:
    assert normalise_zip("00601") == "00601"
    assert normalise_zip("55410-1234") == "55410"
    with pytest.raises(GeographyError, match="not a 5-digit ZIP"):
        normalise_zip("123")


# --- crosswalk ---------------------------------------------------------------------

def relationship_file(tmp_path: Path, rows: str) -> Path:
    path = tmp_path / "rel.txt"
    path.write_text(
        "GEOID_ZCTA5_20|GEOID_TRACT_20|AREALAND_PART\n" + rows, encoding="utf-8"
    )
    return path


def test_links_are_normalised_to_sum_to_one(tmp_path: Path) -> None:
    path = relationship_file(tmp_path, "55410|27053001|300\n55410|27053002|100\n")
    links = load_zcta_tract_links(path)
    weights = [edge.weight for edge in links["55410"]]
    assert weights == [0.75, 0.25]
    assert sum(weights) == pytest.approx(1.0)


def test_rows_without_a_zcta_or_tract_are_skipped(tmp_path: Path) -> None:
    path = relationship_file(tmp_path, "|27053001|300\n55410||100\n55410|27053002|50\n")
    links = load_zcta_tract_links(path)
    assert list(links) == ["55410"]
    assert len(links["55410"]) == 1


def test_zero_land_area_falls_back_to_an_equal_split(tmp_path: Path) -> None:
    path = relationship_file(tmp_path, "55410|27053001|0\n55410|27053002|0\n")
    links = load_zcta_tract_links(path)
    assert [edge.weight for edge in links["55410"]] == [0.5, 0.5]


def test_unparseable_area_is_treated_as_zero(tmp_path: Path) -> None:
    path = relationship_file(tmp_path, "55410|27053001|not-a-number\n55410|27053002|100\n")
    links = load_zcta_tract_links(path)
    assert [edge.weight for edge in links["55410"]] == [0.0, 1.0]


def test_missing_relationship_file_raises_with_the_fetch_url(tmp_path: Path) -> None:
    with pytest.raises(GeographyError, match="named, versioned crosswalk"):
        load_zcta_tract_links(tmp_path / "absent.txt")


def test_weight_basis_is_recorded_on_every_link(tmp_path: Path) -> None:
    path = relationship_file(tmp_path, "55410|27053001|100\n")
    links = load_zcta_tract_links(path, WeightBasis.LAND_AREA)
    assert links["55410"][0].weight_basis == "land_area"


def test_zip_to_zcta_is_an_approximation_that_fails_loudly() -> None:
    assert zip_to_zcta("55410", {"55410": []}) == "55410"
    with pytest.raises(GeographyError, match="no like-numbered ZCTA"):
        zip_to_zcta("00000", {"55410": []})


def sample_links() -> dict[str, list[AllocationLink]]:
    return {
        "55410": [
            AllocationLink("zcta", "55410", "27053001", 0.75, "land_area"),
            AllocationLink("zcta", "55410", "27053002", 0.25, "land_area"),
        ]
    }


def test_allocation_splits_by_weight_and_conserves_mass() -> None:
    allocated = allocate(SourceGeography.USPS_ZIP, "55410", 100.0, sample_links())
    assert [a.value for a in allocated] == [75.0, 25.0]
    assert conservation_error(allocated, 100.0) == 0.0


def test_allocation_stamps_full_transformation_provenance() -> None:
    allocated = allocate(SourceGeography.USPS_ZIP, "55410", 100.0, sample_links())
    row = allocated[0].to_dict()
    assert row["evidence_grain"] == "zip_anchored"
    assert row["estimate_method"] == "crosswalked"
    assert row["crosswalk_source"] == CROSSWALK_SOURCE
    assert row["crosswalk_vintage"] == "2020"
    assert row["allocation_weight_basis"] == "land_area"
    assert row["source_geography_type"] == "usps_zip"


def test_a_tract_source_passes_through_unweighted_and_is_directly_observed() -> None:
    allocated = allocate(SourceGeography.TRACT, "27053001", 42.0, {})
    assert len(allocated) == 1
    assert allocated[0].value == 42.0
    assert allocated[0].estimate_method == "directly_observed"
    assert allocated[0].evidence_grain == "native_tract"
    assert allocated[0].crosswalk_source == "none"


def test_a_county_source_allocates_without_the_zcta_step() -> None:
    links = {"27031": [AllocationLink("county", "27031", "27031001", 1.0, "land_area")]}
    allocated = allocate(SourceGeography.COUNTY, "27031", 10.0, links)
    assert allocated[0].evidence_grain == "county_anchored"
    assert allocated[0].value == 10.0


def test_allocation_without_edges_raises() -> None:
    with pytest.raises(GeographyError, match="no crosswalk edges"):
        allocate(SourceGeography.COUNTY, "99999", 1.0, {})


def test_allocate_many_returns_unallocatable_records_rather_than_dropping_them() -> None:
    """Directive D8: a ZIP with no areal equivalent is a reportable fact."""
    records = [
        (SourceGeography.USPS_ZIP, "55410", 100.0),
        (SourceGeography.USPS_ZIP, "00000", 5.0),
    ]
    allocated, unallocatable = allocate_many(records, sample_links())
    assert len(allocated) == 2
    assert len(unallocatable) == 1
    assert unallocatable[0][0] == "00000"
    assert conservation_error(allocated, 100.0) == 0.0, (
        "only the allocatable input is conserved; the rest is reported, not hidden"
    )


def test_conservation_error_detects_a_leak() -> None:
    allocated = allocate(SourceGeography.USPS_ZIP, "55410", 100.0, sample_links())
    assert conservation_error(allocated, 90.0) == pytest.approx(10.0)


# --- clustering ---------------------------------------------------------------------

def test_haversine_matches_a_known_short_distance() -> None:
    assert haversine_m(44.9, -93.0, 44.90009, -93.0) == pytest.approx(10.0, abs=0.5)
    assert haversine_m(0.0, 0.0, 0.0, 0.0) == 0.0


def test_stations_within_eps_share_a_site() -> None:
    assignments = cluster_sites(["a", "b"], [44.9, 44.90009], [-93.0, -93.0])
    assert assignments[0].site_id == assignments[1].site_id
    assert assignments[0].site_station_count == 2


def test_stations_beyond_eps_get_separate_sites() -> None:
    assignments = cluster_sites(["a", "b"], [44.9, 44.95], [-93.0, -93.0])
    assert assignments[0].site_id != assignments[1].site_id


def test_the_site_centroid_is_the_mean_of_its_members() -> None:
    assignments = cluster_sites(["a", "b"], [44.9, 44.90009], [-93.0, -93.0])
    assert assignments[0].site_latitude == pytest.approx((44.9 + 44.90009) / 2)


def test_empty_input_returns_no_assignments() -> None:
    assert cluster_sites([], [], []) == []


def test_mismatched_input_lengths_raise() -> None:
    with pytest.raises(ValueError, match="same length"):
        cluster_sites(["a"], [1.0, 2.0], [3.0])


@pytest.mark.parametrize(
    ("lat", "lon"),
    [(None, None), (float("nan"), 0.0), (0.0, float("inf")), (91.0, 0.0), (0.0, 181.0)],
)
def test_unusable_coordinates_get_a_singleton_site_rather_than_being_dropped(
    lat: object, lon: object
) -> None:
    """Directive D8: degrade explicitly, never snap to a default location."""
    assignments = cluster_sites(["x"], [lat], [lon])  # type: ignore[list-item]
    assert len(assignments) == 1
    assert assignments[0].site_id == "site_nogeo_x"
    assert assignments[0].site_station_count == 1


def test_a_mix_of_usable_and_unusable_coordinates_is_handled() -> None:
    latitudes: list[float | None] = [44.9, None, 44.90009]
    longitudes: list[float | None] = [-93.0, None, -93.0]
    assignments = cluster_sites(["a", "bad", "b"], latitudes,  # type: ignore[arg-type]
                                longitudes)  # type: ignore[arg-type]
    by_id = {a.station_id: a for a in assignments}
    assert by_id["a"].site_id == by_id["b"].site_id
    assert by_id["bad"].site_id == "site_nogeo_bad"


def test_assignments_are_sorted_for_deterministic_output() -> None:
    assignments = cluster_sites(["c", "a", "b"], [1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
    assert [a.station_id for a in assignments] == ["a", "b", "c"]


def test_eps_is_expressed_in_metres_and_converted_to_radians() -> None:
    assert DEFAULT_EPS_M == 50.0
    assert pytest.approx(6_371_008.8) == EARTH_RADIUS_M


def test_site_assignment_is_immutable() -> None:
    assignment = SiteAssignment("a", "site_1", 1.0, 2.0, 1)
    with pytest.raises(AttributeError):
        assignment.site_id = "other"  # type: ignore[misc]


def test_incomplete_county_rows_are_skipped_not_half_loaded(tmp_path: Path) -> None:
    reference = tmp_path / "counties.txt"
    reference.write_text(
        "STATE|STATEFP|COUNTYFP|COUNTYNS|COUNTYNAME|CLASSFP|FUNCSTAT\n"
        "|27|031|1|Cook County|H1|A\n"        # no state
        "MN|||1|Cook County|H1|A\n"           # no FIPS parts
        "MN|27|031|1||H1|A\n"                 # no name
        "MN|27|031|1|Cook County|H1|A\n",     # complete
        encoding="utf-8",
    )
    lookup = county_fips_lookup.__wrapped__(reference)
    assert lookup == {("MN", "Cook County"): "27031"}
