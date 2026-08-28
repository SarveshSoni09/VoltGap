"""Record accounting: no retrieved record may vanish without a named reason.

These lock the identity ``retrieved == included + sum(excluded_by_reason)`` that the
Washington comparison originally published only half of.
"""

from __future__ import annotations

import pytest

from pipeline.validation.scope import (
    ExclusionLedger,
    ExclusionRule,
    ScopeError,
    classify,
    merge,
)


def negatives() -> ExclusionRule[int]:
    return ExclusionRule("negative", "value below zero", lambda x: x < 0)


def large() -> ExclusionRule[int]:
    return ExclusionRule("too_large", "value above ten", lambda x: x > 10)


def test_a_rule_without_a_reason_key_is_refused() -> None:
    with pytest.raises(ScopeError, match="non-empty reason"):
        ExclusionRule("  ", "described", lambda x: True)


def test_a_rule_without_a_description_is_refused() -> None:
    """An exclusion with no stated justification is what this module exists to stop."""
    with pytest.raises(ScopeError, match="no description"):
        ExclusionRule("mystery", "   ", lambda x: True)


def test_classify_assigns_exactly_one_reason_per_record() -> None:
    kept, ledger = classify([1, -2, 20, 3, -4], [negatives(), large()])
    assert kept == [1, 3]
    assert ledger.retrieved == 5
    assert ledger.included == 2
    assert ledger.excluded == {"negative": 2, "too_large": 1}
    assert ledger.excluded_total == 3


def test_first_matching_rule_wins_so_reasons_cannot_overlap() -> None:
    """A record matching two predicates is counted once, under the earlier rule."""
    both: ExclusionRule[int] = ExclusionRule(
        "either", "negative or large", lambda x: x < 0 or x > 10
    )
    kept, ledger = classify([-5, 50, 1], [both, negatives(), large()])
    assert kept == [1]
    assert ledger.excluded == {"either": 2}
    assert "negative" not in ledger.excluded


def test_duplicate_reason_keys_are_refused() -> None:
    with pytest.raises(ScopeError, match="duplicate exclusion reason"):
        classify([1], [negatives(), negatives()])


def test_reasons_that_matched_nothing_are_omitted_from_the_ledger() -> None:
    _, ledger = classify([1, 2, 3], [negatives(), large()])
    assert ledger.excluded == {}
    assert ledger.descriptions == {}


def test_to_dict_publishes_the_reasons_and_their_descriptions() -> None:
    _, ledger = classify([1, -2], [negatives()])
    payload = ledger.to_dict()
    assert payload["retrieved"] == 2
    assert payload["included"] == 1
    assert payload["excluded_by_reason"] == {"negative": 1}
    assert payload["exclusion_descriptions"] == {"negative": "value below zero"}
    assert payload["balances"] is True


def test_an_unbalanced_ledger_raises_rather_than_publishing() -> None:
    broken = ExclusionLedger(retrieved=100, included=90, excluded={"a": 5},
                             descriptions={"a": "reason"})
    with pytest.raises(ScopeError, match="does not balance"):
        broken.assert_balanced()
    with pytest.raises(ScopeError, match="Unaccounted records: 5"):
        broken.to_dict()


def test_merge_chains_two_stages_over_one_population() -> None:
    first = ExclusionLedger(10, 8, {"bad_row": 2}, {"bad_row": "unparseable"})
    second = ExclusionLedger(8, 6, {"too_small": 2}, {"too_small": "below minimum"})
    merged = merge(first, second)
    assert merged.retrieved == 10
    assert merged.included == 6
    assert merged.excluded == {"bad_row": 2, "too_small": 2}
    merged.assert_balanced()


def test_merge_refuses_stages_that_describe_different_populations() -> None:
    first = ExclusionLedger(10, 8, {"bad_row": 2}, {"bad_row": "unparseable"})
    second = ExclusionLedger(7, 7, {}, {})
    with pytest.raises(ScopeError, match="do not describe one population"):
        merge(first, second)


def test_merge_refuses_colliding_reason_keys_across_stages() -> None:
    first = ExclusionLedger(10, 8, {"shared": 2}, {"shared": "stage one"})
    second = ExclusionLedger(8, 6, {"shared": 2}, {"shared": "stage two"})
    with pytest.raises(ScopeError, match="collide across stages"):
        merge(first, second)


def test_classify_detailed_returns_the_excluded_records_not_only_counts() -> None:
    from pipeline.validation.scope import classify_detailed

    kept, excluded, descriptions = classify_detailed([1, -2, 20, -4], [negatives(), large()])
    assert kept == [1]
    assert excluded == {"negative": [-2, -4], "too_large": [20]}
    assert descriptions == {"negative": "value below zero", "too_large": "value above ten"}


def test_ledger_from_can_count_a_weight_instead_of_records() -> None:
    """A disposition decided about ZIPs still has to be published in vehicles."""
    from pipeline.validation.scope import classify_detailed, ledger_from

    evs = {"98101": 100, "98102": 40, "98109": 3}
    rules: list[ExclusionRule[str]] = [
        ExclusionRule("tiny", "fewer than 10 EVs", lambda z: evs[z] < 10)
    ]
    kept, excluded, descriptions = classify_detailed(sorted(evs), rules)
    by_zip = ledger_from(kept, excluded, descriptions)
    by_ev = ledger_from(kept, excluded, descriptions, weight=lambda z: evs[z])
    assert (by_zip.retrieved, by_zip.included, by_zip.excluded) == (3, 2, {"tiny": 1})
    assert (by_ev.retrieved, by_ev.included, by_ev.excluded) == (143, 140, {"tiny": 3})
