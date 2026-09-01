"""D1: the temporal leakage guard, including the mandatory negative test.

CLAUDE.md §14 requires: "``assert_no_leakage`` raises on a deliberately poisoned feature
set". §15.5 Phase 5 repeats it as an acceptance criterion. That test is
``test_a_deliberately_poisoned_feature_set_raises`` below, and it is the reason this
module exists at all.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from pipeline.validation.vintage import (
    ExcludedFeature,
    LeakageError,
    SourceVintage,
    VintagedFeature,
    VintageLedger,
    assert_no_leakage,
    vintaged,
)

CUTOFF = date(2021, 1, 1)


def feature(name: str, vintage: date) -> VintagedFeature:
    return VintagedFeature(name=name, values=pd.Series([1.0, 2.0]),
                           feature_vintage=vintage, source_id="test_source")


# --- the mandatory negative test ------------------------------------------------------

def test_a_deliberately_poisoned_feature_set_raises() -> None:
    """THE negative test §14 and §15.5 both require. A feature dated after the cutoff
    must stop the run, not warn and continue."""
    clean = [feature("income", date(2019, 12, 31)),
             feature("tenure", date(2019, 12, 31))]
    assert_no_leakage(clean, CUTOFF)          # the honest set passes

    poisoned = [*clean, feature("income_from_the_future", date(2024, 12, 31))]
    with pytest.raises(LeakageError, match="income_from_the_future"):
        assert_no_leakage(poisoned, CUTOFF)


def test_the_error_is_an_assertion_error_so_nothing_catches_it_as_recoverable() -> None:
    """A correctness invariant of the harness, not a condition to handle."""
    assert issubclass(LeakageError, AssertionError)
    assert not issubclass(LeakageError, KeyError)


def test_every_offending_feature_is_named_not_only_the_first() -> None:
    """A harness reporting one violation per run takes one run per mistake to clean."""
    poisoned = [feature("a_late", date(2023, 1, 1)), feature("b_ok", date(2019, 1, 1)),
                feature("c_late", date(2022, 6, 1))]
    with pytest.raises(LeakageError) as caught:
        assert_no_leakage(poisoned, CUTOFF)
    message = str(caught.value)
    assert "a_late" in message and "c_late" in message
    assert "b_ok" not in message
    assert "2 feature(s)" in message


def test_a_feature_dated_exactly_on_the_cutoff_is_allowed() -> None:
    """The rule is feature_vintage <= prediction_cutoff, inclusive."""
    assert_no_leakage([feature("same_day", CUTOFF)], CUTOFF)


def test_an_empty_feature_set_does_not_pass_by_accident() -> None:
    """It genuinely has nothing late in it; this documents that, rather than leaving a
    reader to wonder whether emptiness is a silent skip."""
    assert_no_leakage([], CUTOFF)


# --- vintages ------------------------------------------------------------------------

def vintage(label: str, end: date, released: date, certain: bool = True) -> SourceVintage:
    return SourceVintage("src", label, end, released, "test", certain)


def test_availability_is_governed_by_the_release_date_not_the_period() -> None:
    """The whole point of carrying two dates. ACS 2019 describes 2015-2019 but was not
    published until December 2020; using it at a 2020-01-01 cutoff would be using
    information nobody had."""
    acs2019 = vintage("acs2019", date(2019, 12, 31), date(2020, 12, 10))
    assert acs2019.period_end < date(2020, 1, 1)      # period looks fine
    assert not acs2019.available_at(date(2020, 1, 1))  # but nobody had it
    assert acs2019.available_at(date(2021, 1, 1))


def test_a_release_cannot_predate_the_period_it_describes() -> None:
    with pytest.raises(ValueError, match="not possible"):
        SourceVintage("src", "impossible", date(2020, 12, 31), date(2019, 1, 1), "test")


def test_the_ledger_picks_the_newest_edition_that_was_actually_available() -> None:
    book = VintageLedger((
        vintage("2018", date(2018, 12, 31), date(2019, 12, 19)),
        vintage("2019", date(2019, 12, 31), date(2020, 12, 10)),
        vintage("2021", date(2021, 12, 31), date(2022, 12, 8)),
    ))
    assert book.latest_available("src", date(2021, 1, 1)).label == "2019"
    assert book.latest_available("src", date(2020, 1, 1)).label == "2018"


def test_an_edition_that_only_describes_the_past_is_still_excluded_if_unpublished(
) -> None:
    """And the exclusion is recorded, because §10.2.1 requires them enumerated."""
    book = VintageLedger((
        vintage("2018", date(2018, 12, 31), date(2019, 12, 19)),
        vintage("2019", date(2019, 12, 31), date(2020, 12, 10)),
    ))
    assert book.latest_available("src", date(2020, 1, 1)).label == "2018"
    assert len(book.exclusions) == 1
    assert book.exclusions[0].name == "2019"
    assert "not released until" in book.exclusions[0].reason


def test_an_uncertain_release_date_resolves_toward_the_older_edition() -> None:
    """Erring older cannot manufacture leakage; erring newer can."""
    book = VintageLedger((
        vintage("2019", date(2019, 12, 31), date(2020, 12, 10)),
        vintage("2020", date(2020, 12, 31), date(2021, 12, 1), certain=False),
    ))
    chosen = book.latest_available("src", date(2022, 1, 1))
    assert chosen.label == "2019"
    assert any("not established with confidence" in e.reason for e in book.exclusions)


def test_a_source_with_no_declared_vintages_raises_rather_than_assuming() -> None:
    book = VintageLedger(())
    with pytest.raises(LeakageError, match="no vintages are declared"):
        book.latest_available("unknown_source", CUTOFF)


def test_a_cutoff_before_every_declared_release_raises() -> None:
    book = VintageLedger((vintage("2019", date(2019, 12, 31), date(2020, 12, 10)),))
    with pytest.raises(LeakageError, match="no vintage of"):
        book.latest_available("src", date(2015, 1, 1))


def test_a_merely_superseded_edition_is_not_reported_as_an_exclusion() -> None:
    """Only editions a person could NOT have had are interesting. Listing every older
    release as "excluded" would bury the real ones."""
    book = VintageLedger((
        vintage("2018", date(2018, 12, 31), date(2019, 12, 19)),
        vintage("2019", date(2019, 12, 31), date(2020, 12, 10)),
    ))
    assert book.latest_available("src", date(2021, 6, 1)).label == "2019"
    assert book.exclusions == []


def test_the_ledger_publishes_its_declarations_and_its_exclusions() -> None:
    book = VintageLedger((vintage("2018", date(2018, 12, 31), date(2019, 12, 19)),))
    book.exclude(ExcludedFeature("home_charging", "nrel", "no dated edition exists"))
    payload = book.to_dict()
    declared = payload["declared_vintages"]
    assert isinstance(declared, list)
    assert declared[0]["released"] == "2019-12-19"
    assert declared[0]["release_date_certain"] is True
    exclusions = payload["exclusions"]
    assert isinstance(exclusions, list)
    assert exclusions[0]["feature"] == "home_charging"


def test_wrapping_a_column_carries_its_provenance_into_the_guard() -> None:
    edition = vintage("acs2018", date(2018, 12, 31), date(2019, 12, 19))
    wrapped = vintaged("median_income", [1.0, 2.0, 3.0], edition)
    assert wrapped.feature_vintage == date(2018, 12, 31)
    assert "released 2019-12-19" in wrapped.provenance
    assert list(wrapped.values) == [1.0, 2.0, 3.0]
    assert_no_leakage([wrapped], date(2020, 1, 1))
