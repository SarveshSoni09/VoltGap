"""D1: the temporal leakage guard. A runtime assertion, not documentation.

CLAUDE.md directive D1:

    Any feature used in a backtest must carry a ``feature_vintage`` and the harness must
    assert ``feature_vintage <= prediction_cutoff`` at runtime, raising on violation.

**Two dates, not one.** A data product has a *period* — what span of reality it describes
— and a *release date* — when a person could first have obtained it. The ACS 2019 5-year
estimates describe 2015-2019 but were not published until December 2020. A backtest at a
2020-01-01 cutoff that used them would be using information nobody had, even though the
period ends before the cutoff. **Availability is governed by the release date**, and this
module refuses to accept a vintage that does not carry one.

Period end is kept as well, and checked too: a release cannot describe the future either.
Both must precede the cutoff.

**Uncertainty resolves toward exclusion.** Where a release date is not established with
confidence, the honest response is to use the older vintage whose date *is* certain.
Choosing the older one can never manufacture leakage; choosing the newer one can. Every
such decision is recorded on the vintage itself rather than argued in prose.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date

import pandas as pd


class LeakageError(AssertionError):
    """A feature postdates the cutoff it was going to be used at.

    Deliberately an ``AssertionError``: this is a correctness invariant of the harness,
    not a recoverable condition, and nothing in the pipeline may catch and continue.
    """


@dataclass(frozen=True)
class SourceVintage:
    """One dated edition of a source, and when a person could first have had it."""

    source_id: str
    label: str
    #: Last date the data describes. A release cannot describe the future.
    period_end: date
    #: When it was first published. This is what governs availability.
    released: date
    #: Why this release date is believed, so a reviewer can check it rather than trust it.
    release_evidence: str
    #: Set when the release date is not established with confidence. Such a vintage is
    #: never selected as "latest available"; the previous one is used instead.
    release_date_certain: bool = True

    def __post_init__(self) -> None:
        if self.released < self.period_end:
            raise ValueError(
                f"{self.source_id} {self.label}: released {self.released} before its "
                f"period ends {self.period_end}, which is not possible")

    def available_at(self, cutoff: date) -> bool:
        return self.released <= cutoff and self.period_end <= cutoff


@dataclass(frozen=True)
class VintagedFeature:
    """A feature column that knows when it came from.

    CLAUDE.md §10.2.1 specifies this shape verbatim. ``values`` is a pandas Series so a
    feature matrix can be assembled from these without unwrapping them first.
    """

    name: str
    values: pd.Series
    feature_vintage: date
    source_id: str
    #: Free text carried into the report, e.g. which ACS release this came from.
    provenance: str = ""


@dataclass(frozen=True)
class ExcludedFeature:
    """A feature deliberately kept out of an origin, and why.

    §10.2.1 requires every exclusion to be enumerated in ``docs/VALIDATION.md``. Recording
    them as data rather than prose means the report cannot drift from what ran.
    """

    name: str
    source_id: str
    reason: str
    #: The vintage that would have been used, where one exists.
    would_have_used: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "feature": self.name,
            "source_id": self.source_id,
            "reason": self.reason,
            "would_have_used": self.would_have_used,
        }


def assert_no_leakage(
    features: Sequence[VintagedFeature], prediction_cutoff: date
) -> None:
    """Raise :class:`LeakageError` if any feature postdates the cutoff.

    Called by the harness before **every** backtest fit. §10.2.1 requires this to be a
    runtime assertion rather than a convention, so it raises rather than warning, and the
    message names every offending feature rather than only the first — a harness that
    reported one violation per run would take one run per mistake to clean up.
    """
    late = [f for f in features if f.feature_vintage > prediction_cutoff]
    if late:
        detail = "; ".join(
            f"{f.name} (source {f.source_id}, vintage {f.feature_vintage.isoformat()}"
            + (f", {f.provenance}" if f.provenance else "") + ")"
            for f in sorted(late, key=lambda f: f.name)
        )
        raise LeakageError(
            f"{len(late)} feature(s) postdate the prediction cutoff "
            f"{prediction_cutoff.isoformat()}: {detail}. Directive D1 requires "
            "feature_vintage <= prediction_cutoff for every feature in a retrospective "
            "evaluation. Use the contemporaneous vintage, or exclude the feature and "
            "record it in the exclusion ledger."
        )


@dataclass
class VintageLedger:
    """Every vintage the harness knows about, and what it chose at each cutoff.

    The ledger is what the report quotes. It is built from declarations rather than from
    whatever happened to be on disk, so a cache that silently holds a newer file cannot
    change which vintage an origin uses.
    """

    vintages: tuple[SourceVintage, ...]
    exclusions: list[ExcludedFeature] = field(default_factory=list)

    def for_source(self, source_id: str) -> tuple[SourceVintage, ...]:
        return tuple(v for v in self.vintages if v.source_id == source_id)

    def latest_available(self, source_id: str, cutoff: date) -> SourceVintage:
        """The newest edition of a source a person could have had at the cutoff.

        A vintage whose release date is not certain is **skipped**, not used: erring
        toward the older edition cannot create leakage, and erring toward the newer one
        can. The skip is recorded as an exclusion so the report shows the decision.
        """
        known = self.for_source(source_id)
        if not known:
            raise LeakageError(
                f"no vintages are declared for source {source_id!r}, so nothing can be "
                "shown to predate the cutoff. Declare them rather than assuming.")
        usable = [v for v in known if v.available_at(cutoff) and v.release_date_certain]
        if not usable:
            raise LeakageError(
                f"no vintage of {source_id!r} is known to have been available at "
                f"{cutoff.isoformat()}. Declared: "
                + ", ".join(f"{v.label} released {v.released.isoformat()}"
                            for v in known))
        chosen = max(usable, key=lambda v: (v.released, v.period_end))
        # Enumerate every edition whose PERIOD ends before the cutoff but which was still
        # not used. These are the interesting exclusions: an edition describing only the
        # past that a person nonetheless could not have held yet. §10.2.1 requires them
        # listed, so they are recorded as data rather than described in prose.
        for other in known:
            if other is chosen or other.period_end > cutoff:
                continue
            if other.released > cutoff:
                reason = (f"period ends {other.period_end.isoformat()}, before the "
                          f"cutoff, but it was not released until "
                          f"{other.released.isoformat()}, so nobody had it")
            elif not other.release_date_certain:
                reason = ("release date not established with confidence; the older "
                          "edition is used instead, because erring toward the older "
                          "one cannot manufacture leakage and erring newer can")
            else:
                continue  # simply superseded by a newer available edition
            self.exclusions.append(ExcludedFeature(
                name=other.label, source_id=source_id, reason=reason,
                would_have_used=chosen.label))
        return chosen

    def exclude(self, feature: ExcludedFeature) -> None:
        self.exclusions.append(feature)

    def to_dict(self) -> dict[str, object]:
        return {
            "declared_vintages": [
                {
                    "source_id": v.source_id, "label": v.label,
                    "period_end": v.period_end.isoformat(),
                    "released": v.released.isoformat(),
                    "release_date_certain": v.release_date_certain,
                    "release_evidence": v.release_evidence,
                }
                for v in sorted(self.vintages, key=lambda v: (v.source_id, v.released))
            ],
            "exclusions": [e.to_dict() for e in self.exclusions],
        }


def vintaged(
    name: str, values: Iterable[float], vintage: SourceVintage
) -> VintagedFeature:
    """Wrap a column with the vintage it actually came from."""
    return VintagedFeature(
        name=name, values=pd.Series(list(values), dtype=float),
        feature_vintage=vintage.period_end, source_id=vintage.source_id,
        provenance=f"{vintage.label}, released {vintage.released.isoformat()}")
