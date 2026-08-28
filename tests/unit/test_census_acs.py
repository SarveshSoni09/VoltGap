"""The ACS feature source: D2 enforcement, request batching, and the HTML key trap."""

from __future__ import annotations

import json

import pytest

from pipeline.sources.base import LossyStagingError
from pipeline.sources.census_acs import (
    ACS_VARIABLES,
    COUNTY,
    FEATURE_TABLES,
    MAX_VARIABLES_PER_REQUEST,
    TRACT,
    ZCTA,
    AcsSource,
    AcsTractSource,
    assert_no_supply_features,
    batches,
)
from tests.conftest import FakeFetcher


def response(header: list[str], rows: list[list[str]]) -> bytes:
    return json.dumps([header, *rows]).encode("utf-8")


# --- the declared feature set -------------------------------------------------------

def test_every_declared_variable_is_reachable_and_unique() -> None:
    assert len(ACS_VARIABLES) == len(set(ACS_VARIABLES))
    assert len(ACS_VARIABLES) == 78
    assert {t.table_id for t in FEATURE_TABLES} == {
        "B01003", "B19013", "B19001", "B25003", "B25024", "B25044",
        "B08301", "B08303", "B15003",
    }


def test_every_feature_table_states_why_it_is_admissible() -> None:
    for table in FEATURE_TABLES:
        assert len(table.rationale) > 40, table.table_id
        assert table.variables


def test_the_declared_variables_contain_no_supply_feature() -> None:
    assert_no_supply_features(ACS_VARIABLES)


def test_a_supply_derived_variable_is_rejected_by_name_or_concept() -> None:
    with pytest.raises(ValueError, match="D2 violation"):
        assert_no_supply_features(("X_001E",), {"X_001E": "distance to nearest charger"})


def test_commute_mode_is_not_rejected_because_transportation_contains_port() -> None:
    """A substring check made this fail; whole-word matching is the fix."""
    assert_no_supply_features(("B08301_001E",),
                              {"B08301_001E": "means of transportation to work"})


# --- request batching ---------------------------------------------------------------

def test_batches_respect_the_api_cap_and_preserve_order() -> None:
    groups = batches(ACS_VARIABLES)
    assert [len(g) for g in groups] == [48, 30]
    assert max(len(g) for g in groups) <= MAX_VARIABLES_PER_REQUEST
    assert [v for group in groups for v in group] == list(ACS_VARIABLES)


def test_a_short_variable_list_is_a_single_batch() -> None:
    assert batches(["A", "B"], size=48) == [("A", "B")]


# --- geographies --------------------------------------------------------------------

def test_each_geography_asks_the_api_for_its_own_summary_level() -> None:
    assert AcsSource(TRACT, "53")._params(["V"])["for"] == "tract:*"
    assert AcsSource(TRACT, "53")._params(["V"])["in"] == "state:53"
    assert AcsSource(ZCTA)._params(["V"])["for"] == "zip code tabulation area:*"
    assert "in" not in AcsSource(ZCTA)._params(["V"])
    assert AcsSource(COUNTY)._params(["V"])["in"] == "state:*"


def test_the_key_parameter_is_always_present_so_the_cache_identity_is_stable() -> None:
    """The cache key hashes the redacted params, which keep the NAME of a secret.

    A source that added ``key`` only when a credential happened to be configured would
    record under one identity and replay under another, and the deterministic gate runs
    without credentials.
    """
    with_key = AcsSource(ZCTA, api_key="secret")._params(["V"])
    without = AcsSource(ZCTA)._params(["V"])
    assert set(with_key) == set(without)
    assert "key" in without


def test_a_per_state_geography_refuses_to_be_asked_for_nationally() -> None:
    with pytest.raises(ValueError, match="one state at a time"):
        AcsSource(TRACT)


def test_the_tract_helper_builds_the_same_source() -> None:
    assert AcsTractSource("06").source_id == AcsSource(TRACT, "06").source_id


# --- loading ------------------------------------------------------------------------

def small_source(**kwargs: object) -> AcsSource:
    return AcsSource(TRACT, "53", variables=("B01003_001E", "B19013_001E"),
                     **kwargs)  # type: ignore[arg-type]


def test_load_joins_request_batches_on_the_geography_keys() -> None:
    source = AcsSource(TRACT, "53", variables=tuple(f"V{i}" for i in range(50)))
    first = response(["V" + str(i) for i in range(48)] + ["state", "county", "tract"],
                     [[str(i) for i in range(48)] + ["53", "033", "000100"]])
    second = response(["V48", "V49", "state", "county", "tract"],
                      [["48", "49", "53", "033", "000100"]])
    table = AcsSource.load(source, FakeFetcher([first, second]))
    assert len(table.rows) == 1
    assert table.rows[0]["geoid"] == "53033000100"
    assert table.rows[0]["V0"] == "0"
    assert table.rows[0]["V49"] == "49"


def test_load_needs_a_fetcher() -> None:
    with pytest.raises(ValueError, match="needs a fetcher"):
        small_source().load(None)


def test_an_html_body_is_refused_even_under_http_200() -> None:
    """A keyless Census request answers 200 with a 'Missing Key' page."""
    fetcher = FakeFetcher([b"<html><head><title>Missing Key</title></head></html>"])
    with pytest.raises(LossyStagingError, match="returned HTML rather than JSON"):
        small_source().load(fetcher)


def test_a_non_array_body_is_refused() -> None:
    with pytest.raises(LossyStagingError, match="non-empty array"):
        small_source().load(FakeFetcher([b'{"error": "nope"}']))


def test_an_empty_array_body_is_refused() -> None:
    with pytest.raises(LossyStagingError, match="non-empty array"):
        small_source().load(FakeFetcher([b"[]"]))


def test_a_response_missing_a_geography_column_is_refused() -> None:
    body = response(["B01003_001E", "B19013_001E", "state", "county"],
                    [["1", "2", "53", "033"]])
    with pytest.raises(LossyStagingError, match="missing geography column 'tract'"):
        small_source().load(FakeFetcher([body]))


def test_batches_covering_different_areas_are_refused_rather_than_joined() -> None:
    """A silent inner join would lose rows, which amendment A15 forbids."""
    source = AcsSource(TRACT, "53", variables=tuple(f"V{i}" for i in range(50)))
    keys = ["state", "county", "tract"]
    first = response([f"V{i}" for i in range(48)] + keys,
                     [[str(i) for i in range(48)] + ["53", "033", "000100"],
                      [str(i) for i in range(48)] + ["53", "033", "000200"]])
    second = response(["V48", "V49", *keys], [["1", "2", "53", "033", "000100"]])
    with pytest.raises(LossyStagingError, match="Batches must cover the same areas"):
        source.load(FakeFetcher([first, second]))


def test_a_null_cell_becomes_an_empty_string_not_the_word_none() -> None:
    body = json.dumps([["B01003_001E", "B19013_001E", "state", "county", "tract"],
                       [None, "5", "53", "033", "000100"]]).encode()
    table = small_source().load(FakeFetcher([body]))
    assert table.rows[0]["B01003_001E"] == ""


def test_the_staged_vintage_names_the_acs_release() -> None:
    body = response(["B01003_001E", "B19013_001E", "state", "county", "tract"],
                    [["1", "2", "53", "033", "000100"]])
    table = small_source().load(FakeFetcher([body]))
    assert table.vintage.vintage == "ACS 2023 5-year"
    assert table.source_row_count == len(table.rows)


def test_a_zcta_row_is_keyed_by_its_single_geography_column() -> None:
    body = response(["B01003_001E", "zip code tabulation area"], [["10", "98101"]])
    source = AcsSource(ZCTA, variables=("B01003_001E",))
    table = source.load(FakeFetcher([body]))
    assert table.rows[0]["geoid"] == "98101"
