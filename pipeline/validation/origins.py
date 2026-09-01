"""The rolling origins, and exactly what data each one is allowed to see.

CLAUDE.md §10.2.2 requires at least three origins - **2020, 2021, 2022** - each predicting
the following 24 months. This module declares them, declares every source vintage the
harness knows about with the evidence for its release date, and resolves what each origin
may use. Nothing here reads the disk: a cache that happens to hold a newer file must not be
able to change which vintage an origin uses.

**The tract-geography break.** ACS 5-year releases through 2019 are published on **2010**
census tract boundaries; the 2020 release onward uses **2020** boundaries. Measured on the
live API: Vermont returns 184 tracts for the 2018 and 2019 vintages and 193 for 2020 and
2021. Every one of the three origins resolves to a 2010-geography vintage, while the
production surface is 2020-geography — so the backtest is scored on **H3 cells**, which do
not move when the Census redraws tracts, using contemporaneous 2010 block-group population
weights. §10.2.4's metrics are all cell-ranking metrics, so nothing is lost by this.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from pipeline.validation.vintage import SourceVintage, VintageLedger

ACS_SOURCE = "census_acs_tracts"
REGISTRATION_SOURCE = "afdc_state_ev_registrations"

#: ACS 5-year editions, with the release date that governs availability.
#:
#: The 2020 edition is marked **uncertain**. It is widely reported to have slipped from
#: December 2021 into March 2022 because of pandemic collection problems, which would put
#: it on the wrong side of the 2022-01-01 cutoff — but this project has not established
#: that date from a primary source. Rather than rest a leakage claim on a remembered date,
#: it is declared uncertain, and the guard therefore falls back to the 2019 edition at the
#: 2022 origin. That is the conservative direction: using an older vintage cannot
#: manufacture leakage, using a newer one can.
ACS_VINTAGES: tuple[SourceVintage, ...] = (
    SourceVintage(
        ACS_SOURCE, "ACS 2018 5-year (2014-2018)", date(2018, 12, 31), date(2019, 12, 19),
        "standard December release, one year after the period ends"),
    SourceVintage(
        ACS_SOURCE, "ACS 2019 5-year (2015-2019)", date(2019, 12, 31), date(2020, 12, 10),
        "standard December release, one year after the period ends"),
    SourceVintage(
        ACS_SOURCE, "ACS 2020 5-year (2016-2020)", date(2020, 12, 31), date(2022, 3, 17),
        "reported to have slipped from December 2021 to March 2022 because of pandemic "
        "collection problems; NOT verified against a primary source by this project",
        release_date_certain=False),
    SourceVintage(
        ACS_SOURCE, "ACS 2021 5-year (2017-2021)", date(2021, 12, 31), date(2022, 12, 8),
        "standard December release, one year after the period ends"),
)

#: AFDC annual state registration pages. The label year is the stock year; the page for
#: year Y is treated as available from the following January.
#:
#: **A-0.5 remains open and this is where it bites.** Phase 1 established that these pages
#: are *stable* — 52 of 52 jurisdictions identical between 2022-08-18 and 2026-08-24 for
#: both the 2020 and 2021 vintages — but **not** that they are contemporaneous, because no
#: capture predates 2022-08-18. If AFDC reconstructed the annual series retrospectively
#: from later VIN data, then a "2019 vintage" used at a 2020 cutoff carries information
#: that did not exist in 2020. The backtest cannot rule this out and does not claim to.
REGISTRATION_VINTAGES: tuple[SourceVintage, ...] = tuple(
    SourceVintage(
        REGISTRATION_SOURCE, f"AFDC state EV registrations {year}",
        date(year, 12, 31), date(year + 1, 1, 1),
        "annual stock page labelled for the year; availability assumed from the "
        "following January. Contemporaneity UNRESOLVED (assumption A-0.5): stability "
        "was established over 2022-2026 but no capture predates 2022-08-18")
    for year in range(2016, 2026)
)

ALL_VINTAGES: tuple[SourceVintage, ...] = ACS_VINTAGES + REGISTRATION_VINTAGES


@dataclass(frozen=True)
class Origin:
    """One rolling origin: a cutoff, and the window it is scored over."""

    name: str
    cutoff: date
    horizon_months: int = 24

    @property
    def window_end(self) -> date:
        return date(self.cutoff.year + self.horizon_months // 12,
                    self.cutoff.month, self.cutoff.day)

    def contains(self, opened: date) -> bool:
        return self.cutoff <= opened < self.window_end

    #: §10.2.2: reconstruction confidence degrades with age because of survivorship bias
    #: (G11), so conclusions are weighted toward the most recent origin.
    @property
    def reconstruction_confidence(self) -> str:
        return {
            "2020": "lowest - five to six years of station churn is invisible in a "
                    "current snapshot, so the reconstructed pre-cutoff network is the "
                    "most survivorship-biased of the three",
            "2021": "middle",
            "2022": "highest of the three, though still an approximate reconstruction",
        }.get(self.name,
              f"undeclared origin {self.name}: reconstruction confidence has not been "
              "assessed for it, and the older the cutoff the more survivorship bias "
              "the reconstruction carries (G11)")


ORIGINS: tuple[Origin, ...] = (
    Origin("2020", date(2020, 1, 1)),
    Origin("2021", date(2021, 1, 1)),
    Origin("2022", date(2022, 1, 1)),
)


@dataclass(frozen=True)
class OriginPlan:
    """What one origin is permitted to use, resolved from the ledger."""

    origin: Origin
    acs: SourceVintage
    registrations: SourceVintage
    acs_year: int
    tract_geography: str

    def to_dict(self) -> dict[str, object]:
        return {
            "origin": self.origin.name,
            "prediction_cutoff": self.origin.cutoff.isoformat(),
            "evaluation_window": (
                f"{self.origin.cutoff.isoformat()} to "
                f"{self.origin.window_end.isoformat()} (24 months)"),
            "acs_vintage": self.acs.label,
            "acs_released": self.acs.released.isoformat(),
            "acs_api_year": self.acs_year,
            "tract_geography": self.tract_geography,
            "state_registration_vintage": self.registrations.label,
            "state_registration_released": self.registrations.released.isoformat(),
            "reconstruction_confidence": self.origin.reconstruction_confidence,
        }


def plan_origins(
    origins: Sequence[Origin] = ORIGINS,
    ledger: VintageLedger | None = None,
) -> tuple[list[OriginPlan], VintageLedger]:
    """Resolve each origin to the newest vintages it could legitimately have used."""
    book = ledger or VintageLedger(ALL_VINTAGES)
    plans = []
    for origin in origins:
        acs = book.latest_available(ACS_SOURCE, origin.cutoff)
        registrations = book.latest_available(REGISTRATION_SOURCE, origin.cutoff)
        year = int(acs.period_end.year)
        plans.append(OriginPlan(
            origin=origin, acs=acs, registrations=registrations, acs_year=year,
            tract_geography="2010" if year <= 2019 else "2020"))
    return plans, book
