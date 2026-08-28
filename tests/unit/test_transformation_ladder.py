"""The measured geographic transformation ladder, and the ZCTA-to-state index."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.spatial.crosswalk import zcta_state_index
from pipeline.spatial.geography import GeographyError
from pipeline.validation.washington import (
    GRAIN_ORDER,
    HOUSEHOLD_SHARE,
    HUD_METHOD,
    LadderRung,
    assert_ladder_ordering,
    county_names_by_fips,
    household_share_links,
    measure_transformation_ladder,
    observed_tract_shares,
    run_grain_ladder,
    statewide_tvd,
    tract_groups,
)

T1, T2, T3 = "53033000100", "53033000200", "53061000100"


def record(zip_code: str, county: str, tract: str) -> dict[str, str]:
    return {"zip_code": zip_code, "county": county, "state": "WA",
            "_2020_census_tract": tract}


# --- the ZCTA to state index --------------------------------------------------------

def test_a_zcta_reports_every_state_it_intersects(tmp_path: Path) -> None:
    path = tmp_path / "rel.txt"
    path.write_text(
        "GEOID_ZCTA5_20|GEOID_TRACT_20\n"
        "97229|41051000100\n97229|41067000100\n"
        "97635|41045000100\n97635|06093000100\n"
        "99999|\n",
        encoding="utf-8",
    )
    index = zcta_state_index(path)
    assert index["97229"] == frozenset({"41"})
    assert index["97635"] == frozenset({"41", "06"})
    assert "99999" not in index


def test_a_missing_relationship_file_raises_rather_than_guessing(tmp_path: Path) -> None:
    """Without it an out-of-state mailing ZIP cannot be told from a local one."""
    with pytest.raises(GeographyError, match="out-of-state mailing ZIP"):
        zcta_state_index(tmp_path / "absent.txt")


def test_a_relationship_file_with_no_links_raises(tmp_path: Path) -> None:
    path = tmp_path / "rel.txt"
    path.write_text("GEOID_ZCTA5_20|GEOID_TRACT_20\n", encoding="utf-8")
    with pytest.raises(GeographyError, match="zero ZCTA-state links"):
        zcta_state_index(path)


def test_the_national_index_matches_the_published_shape() -> None:
    index = zcta_state_index()
    assert len(index) == 33791
    assert sum(1 for states in index.values() if len(states) > 1) == 137
    assert index["00907"] == frozenset({"72"})  # Puerto Rico, seen in Oregon's export


# --- group membership ---------------------------------------------------------------

def test_county_and_state_groups_come_from_geoid_nesting() -> None:
    counties = tract_groups([T1, T2, T3], "county_anchored")
    assert counties == {"53033": [T1, T2], "53061": [T3]}
    assert tract_groups([T1, T2, T3], "state_total_only") == {"53": [T1, T2, T3]}


def test_zip_groups_come_from_the_crosswalk_a_deployment_would_have() -> None:
    """Deriving them from the observed records hands the method the answer."""
    crosswalk = {"98101": {T1: 0.5, T2: 0.5}, "99999": {"41051000100": 1.0}}
    groups = tract_groups([T1, T2, T3], "zip_anchored", crosswalk)
    assert groups == {"98101": [T1, T2]}


def test_the_zip_rung_needs_a_crosswalk() -> None:
    with pytest.raises(ValueError, match="crosswalk a deployment would use"):
        tract_groups([T1], "zip_anchored")


def test_an_unknown_grain_has_no_grouping() -> None:
    with pytest.raises(ValueError, match="no tract grouping"):
        tract_groups([T1], "invented")


def test_county_names_are_matched_to_the_words_the_records_use() -> None:
    names = county_names_by_fips("53")
    assert names["53033"] == "King"
    assert all(not n.endswith(" County") for n in names.values())


# --- weights ------------------------------------------------------------------------

def test_household_share_weights_sum_to_one_within_each_group() -> None:
    links = household_share_links({T1: 30.0, T2: 10.0}, {"g": [T1, T2]})
    assert links["g"] == pytest.approx({T1: 0.75, T2: 0.25})


def test_a_group_with_no_households_is_split_evenly_not_zeroed() -> None:
    """Zeroing it would silently discard the group's observed total."""
    links = household_share_links({T1: 0.0, T2: 0.0}, {"g": [T1, T2]})
    assert links["g"] == {T1: 0.5, T2: 0.5}


def test_a_group_with_no_tracts_at_all_produces_no_links() -> None:
    assert household_share_links({}, {"g": []}) == {}


# --- the statewide metric -----------------------------------------------------------

def test_observed_shares_cover_only_in_state_tracts() -> None:
    shares, total = observed_tract_shares(
        [record("98101", "King", T1), record("98101", "King", "41051000100")])
    assert shares == {T1: 1.0}
    assert total == 1.0


def test_an_empty_observation_set_is_refused() -> None:
    with pytest.raises(ValueError, match="no in-state records"):
        observed_tract_shares([])


def test_a_perfect_transformation_scores_zero() -> None:
    records = [record("98101", "King", T1)] * 3 + [record("98102", "King", T2)]
    links = {"98101": {T1: 1.0}, "98102": {T2: 1.0}}
    tvd, placed, unplaced = statewide_tvd(records, links, "zip_code")
    assert tvd == pytest.approx(0.0)
    assert (placed, unplaced) == (4.0, 0.0)


def test_a_transformation_that_misplaces_everything_scores_one() -> None:
    records = [record("98101", "King", T1)]
    tvd, _, _ = statewide_tvd(records, {"98101": {T2: 1.0}}, "zip_code")
    assert tvd == pytest.approx(1.0)


def test_records_the_transformation_cannot_place_are_counted_not_ignored() -> None:
    records = [record("98101", "King", T1), record("99999", "King", T2)]
    tvd, placed, unplaced = statewide_tvd(records, {"98101": {T1: 1.0}}, "zip_code")
    assert (placed, unplaced) == (1.0, 1.0)
    assert tvd == pytest.approx(0.5)


def test_a_transformation_that_places_nothing_reports_it_as_unplaced() -> None:
    """TVD against an all-zero vector is 0.5 by construction, which understates a total
    failure, so ``unplaced`` is the field that reports it."""
    tvd, placed, unplaced = statewide_tvd([record("98101", "King", T1)], {}, "zip_code")
    assert (placed, unplaced) == (0.0, 1.0)
    assert tvd == pytest.approx(0.5)


# --- the ladder ---------------------------------------------------------------------

def test_the_grain_order_is_the_one_the_specification_predicts() -> None:
    assert GRAIN_ORDER == ("native_tract", "zip_anchored", "county_anchored",
                           "state_total_only")


def test_a_ladder_that_respects_the_predicted_ordering_passes() -> None:
    rungs = [
        LadderRung("native_tract", "identity", 1, 1.0, 0.0, 0.0),
        LadderRung("zip_anchored", HOUSEHOLD_SHARE, 1, 1.0, 0.21, 0.0),
        LadderRung("county_anchored", HOUSEHOLD_SHARE, 1, 1.0, 0.24, 0.0),
        LadderRung("state_total_only", HOUSEHOLD_SHARE, 1, 1.0, 0.30, 0.0),
    ]
    assert_ladder_ordering(rungs)
    assert rungs[1].to_dict()["statewide_tract_tvd"] == 0.21


def test_a_ladder_that_violates_the_ordering_raises_with_the_numbers() -> None:
    """CLAUDE.md calls the ordering 'subject to empirical validation', so a violation
    is a finding to report, not something to fix by re-sorting."""
    rungs = [
        LadderRung("zip_anchored", HOUSEHOLD_SHARE, 1, 1.0, 0.35, 0.0),
        LadderRung("county_anchored", HOUSEHOLD_SHARE, 1, 1.0, 0.24, 0.0),
    ]
    with pytest.raises(AssertionError, match=r"zip_anchored=0\.3500"):
        assert_ladder_ordering(rungs)


def wa_fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, float]]:
    # T3 sits in county 53061, which is Snohomish. Naming it anything else would
    # leave its vehicles unplaced and quietly weaken every rung below.
    records = ([record("98101", "King", T1)] * 60
               + [record("98101", "King", T2)] * 20
               + [record("98301", "Snohomish", T3)] * 20)
    records_path = tmp_path / "wa.json"
    records_path.write_text(json.dumps(records), encoding="utf-8")
    hud_path = tmp_path / "hud.json"
    hud_path.write_text(json.dumps({
        "98101": [{"geoid": T1, "res_ratio": 0.75}, {"geoid": T2, "res_ratio": 0.25}],
        "98301": [{"geoid": T3, "res_ratio": 1.0}],
    }), encoding="utf-8")
    # Households deliberately do NOT match the observed EV distribution, so a
    # household-share transformation has real error to measure.
    return records_path, hud_path, {T1: 40.0, T2: 40.0, T3: 20.0}


def test_the_ladder_measures_every_rung_including_the_method_actually_used(
    tmp_path: Path,
) -> None:
    records_path, hud_path, households = wa_fixture(tmp_path)
    rungs = measure_transformation_ladder(records_path, households, hud_path)
    keys = {(r.grain, r.method) for r in rungs}
    assert ("native_tract", "identity") in keys
    assert ("zip_anchored", HUD_METHOD) in keys
    assert ("zip_anchored", HOUSEHOLD_SHARE) in keys
    assert ("county_anchored", HOUSEHOLD_SHARE) in keys
    assert ("state_total_only", HOUSEHOLD_SHARE) in keys
    assert all(r.unplaced_evs == 0.0 for r in rungs), "every vehicle must be placed"
    assert_ladder_ordering(rungs)
    by_key = {(r.grain, r.method): r.statewide_tract_tvd for r in rungs}
    # The HUD weights reproduce the observed split exactly here, and household share
    # does not, so the method actually used must score better at the same grain.
    assert by_key[("zip_anchored", HUD_METHOD)] < by_key[
        ("zip_anchored", HOUSEHOLD_SHARE)]
    assert by_key[("state_total_only", HOUSEHOLD_SHARE)] > 0.0


def test_the_ladder_runs_without_a_crosswalk_by_dropping_the_zip_rung(
    tmp_path: Path,
) -> None:
    records_path, _, households = wa_fixture(tmp_path)
    rungs = measure_transformation_ladder(records_path, households, hud_path=None)
    assert not any(r.grain == "zip_anchored" for r in rungs)


def test_the_within_group_diagnostic_still_runs_alongside(tmp_path: Path) -> None:
    records_path, hud_path, households = wa_fixture(tmp_path)
    out = run_grain_ladder(records_path, households, hud_path)
    assert set(out) == {"zip_anchored", "county_anchored", "state_total_only"}
    for result in out.values():
        result.ledger.assert_balanced()
