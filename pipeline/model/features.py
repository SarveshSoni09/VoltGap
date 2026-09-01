"""Demand model features: derived from ACS demographics and nothing else.

**Directive D2 is the whole point of this module.** Charger counts, port counts,
charger density, network presence and distance to the nearest charger are forbidden in
the primary feature set, because existing infrastructure is an outcome of prior
investment decisions. Predicting demand from it and then siting from that demand
launders historical deployment into "need". CLAUDE.md §18 anti-pattern 5 records the
reason the rule needs enforcing rather than documenting: supply features *do* improve
fit, so the pressure to admit one is real. :func:`assert_primary_feature_set_is_clean`
raises if one ever appears.

**One definition, three geographies.** Every feature below is computed from raw ACS
variables by the same code whether the row is a tract, a ZCTA or a county. That matters
because the Phase 3 pre-registration scores each held-out state at its own native
observed granularity: a ZIP-grain state is fitted and scored on ZCTA rows, a
county-grain state on county rows, and predictions are made on tracts. If the feature
definitions drifted between grains, that comparison would be measuring the drift.

**Missing data is recorded, never silently defaulted (D8).** The Census "not available"
jam value ``-666666666`` and an empty string both become ``None``; a share whose
denominator is zero becomes ``None``. Imputation happens once, explicitly, in
:func:`impute`, which records how many features it filled for each row so the
uncertainty model can see it.
"""

from __future__ import annotations

import csv
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from pipeline.config.settings import PATHS

#: Census publishes "not available" as a large negative jam value rather than a null.
#: Reading it as a number would put -666,666,666 dollars of median income into a model.
ACS_JAM_VALUES: frozenset[str] = frozenset({
    "-666666666", "-999999999", "-888888888", "-222222222", "-333333333",
    "-555555555", "*", "**", "-",
})

_RAW = PATHS.root / "data" / "cache" / "raw"

GAZETTEER = {
    "tracts": _RAW / "gaz_tracts_2023.txt",
    "zcta": _RAW / "gaz_zcta_2023.txt",
    "county": _RAW / "gaz_counties_2023.txt",
}

#: Land area by CENSUS TRACT GEOGRAPHY, not by release year. ACS releases through 2019
#: are published on 2010 tract boundaries and the 2020 release onward on 2020 boundaries,
#: so Phase 5's rolling origins - which all resolve to 2010-geography ACS - need the
#: contemporaneous gazetteer. The two files describe different tract sets entirely:
#: 74,001 tracts in the 2019 edition against 85,396 in the 2023 one. Using the current
#: file for a 2010-geography surface would leave most tracts with no land area and
#: silently break population density.
GAZETTEER_BY_TRACT_GEOGRAPHY = {
    "2020": _RAW / "gaz_tracts_2023.txt",
    "2010": _RAW / "gaz_tracts_2019.txt",
}

Row = Mapping[str, float | None]


class FeatureError(ValueError):
    """A feature could not be computed and the failure must not be papered over."""


def numeric(value: str | float | None) -> float | None:
    """Parse an ACS cell. Jam values and blanks become ``None``, never a number."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text in ACS_JAM_VALUES:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def share(numerator: Sequence[float | None], denominator: float | None) -> float | None:
    """A share, or ``None`` if the denominator is absent or zero.

    Returning 0.0 for a zero denominator would assert that no households own their home
    in a tract with no households, which is a statement the data does not make.
    """
    if denominator is None or denominator <= 0:
        return None
    parts = [part for part in numerator if part is not None]
    if len(parts) != len(numerator):
        return None
    return sum(float(part) for part in parts) / denominator


def weighted_mean(
    counts: Sequence[float | None], midpoints: Sequence[float], total: float | None
) -> float | None:
    """Mean over binned counts using documented bin midpoints."""
    present = [c for c in counts if c is not None]
    if total is None or total <= 0 or len(present) != len(counts):
        return None
    return sum(c * m for c, m in zip(present, midpoints, strict=True)) / total


@dataclass(frozen=True)
class Feature:
    """One model input, with the reason it is admissible under D2."""

    name: str
    description: str
    rationale: str
    compute: Callable[[Row], float | None]


def _get(row: Row, name: str) -> float | None:
    return row.get(name)


def _many(row: Row, names: Sequence[str]) -> list[float | None]:
    return [row.get(name) for name in names]


# B25024 units-in-structure categories: 002 one-detached, 003 one-attached,
# 004 two, 005 three-or-four, 006 five-to-nine, 007 ten-to-nineteen,
# 008 twenty-to-fortynine, 009 fifty-or-more, 010 mobile home, 011 boat/RV/van.
_MULTIFAMILY = ("B25024_004E", "B25024_005E", "B25024_006E", "B25024_007E",
                "B25024_008E", "B25024_009E")
# B19001 household income brackets: 002 under 10k ... 013 75-100k, 014 100-125k,
# 015 125-150k, 016 150-200k, 017 200k or more.
_INCOME_HIGH = ("B19001_014E", "B19001_015E", "B19001_016E", "B19001_017E")
_INCOME_LOW = ("B19001_002E", "B19001_003E", "B19001_004E", "B19001_005E",
               "B19001_006E", "B19001_007E")
# B25044: 003 owner no vehicle, 010 renter no vehicle.
_NO_VEHICLE = ("B25044_003E", "B25044_010E")
# B25044 vehicle counts, owner then renter, with the top category read as 5.
_VEHICLE_BINS = ("B25044_003E", "B25044_004E", "B25044_005E", "B25044_006E",
                 "B25044_007E", "B25044_008E", "B25044_010E", "B25044_011E",
                 "B25044_012E", "B25044_013E", "B25044_014E", "B25044_015E")
_VEHICLE_MIDPOINTS = (0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 0.0, 1.0, 2.0, 3.0, 4.0, 5.0)
# B08303 travel-time bins, in minutes, using the interval midpoint. The open top
# category (90 or more) is read as 100, which is a documented choice, not a measurement.
_COMMUTE_BINS = tuple(f"B08303_{i:03d}E" for i in range(2, 14))
_COMMUTE_MIDPOINTS = (2.5, 7.0, 12.0, 17.0, 22.0, 27.0, 32.0, 37.0, 42.0, 52.0,
                      74.5, 100.0)
# B15003: 022 bachelor's, 023 master's, 024 professional, 025 doctorate.
_BACHELORS_PLUS = ("B15003_022E", "B15003_023E", "B15003_024E", "B15003_025E")


FEATURES: tuple[Feature, ...] = (
    Feature(
        "log_population_density_km2",
        "Natural log of resident population per square kilometre of land area.",
        "Density separates urban from rural without needing a separate classification, "
        "and enters as a log because the national distribution spans five orders of "
        "magnitude.",
        lambda r: _density(r),
    ),
    Feature(
        "median_household_income_k",
        "Median household income in thousands of dollars.",
        "Ability to pay is the most-cited determinant of EV adoption.",
        lambda r: None if _get(r, "B19013_001E") is None
        else float(_get(r, "B19013_001E") or 0.0) / 1000.0,
    ),
    Feature(
        "income_share_over_100k",
        "Share of households with income of $100,000 or more.",
        "A median hides dispersion; two areas with equal medians and different upper "
        "tails have different adoption capacity.",
        lambda r: share(_many(r, _INCOME_HIGH), _get(r, "B19001_001E")),
    ),
    Feature(
        "income_share_under_35k",
        "Share of households with income below $35,000.",
        "The lower tail is where a new-vehicle purchase is out of reach, and it is not "
        "the mirror image of the upper tail.",
        lambda r: share(_many(r, _INCOME_LOW), _get(r, "B19001_001E")),
    ),
    Feature(
        "owner_occupied_share",
        "Share of occupied housing units that are owner occupied.",
        "Owners can install home charging; renters usually cannot. This is the "
        "strongest housing-side constraint ACS reports directly.",
        lambda r: share([_get(r, "B25003_002E")], _get(r, "B25003_001E")),
    ),
    Feature(
        "single_family_share",
        "Share of housing units that are one-unit detached or attached.",
        "A dedicated parking space and a circuit are what home charging needs, and "
        "single-family housing is the ACS proxy for both.",
        lambda r: share(_many(r, ("B25024_002E", "B25024_003E")),
                        _get(r, "B25024_001E")),
    ),
    Feature(
        "multifamily_share",
        "Share of housing units in structures of two or more units.",
        "Multifamily parking is usually shared or absent, which is a different "
        "charging problem from the single-family case rather than its complement.",
        lambda r: share(_many(r, _MULTIFAMILY), _get(r, "B25024_001E")),
    ),
    Feature(
        "zero_vehicle_household_share",
        "Share of occupied housing units with no vehicle available.",
        "A household with no vehicle is not an EV prospect at all.",
        lambda r: share(_many(r, _NO_VEHICLE), _get(r, "B25044_001E")),
    ),
    Feature(
        "vehicles_per_household",
        "Mean vehicles available per occupied housing unit.",
        "A household with several vehicles can replace one with an EV without losing "
        "mobility, which is a materially easier adoption decision.",
        lambda r: weighted_mean(_many(r, _VEHICLE_BINS), _VEHICLE_MIDPOINTS,
                                _get(r, "B25044_001E")),
    ),
    Feature(
        "drove_alone_share",
        "Share of workers who commute by driving alone.",
        "Car-dependent areas have both the need and the parking pattern that support "
        "private charging.",
        lambda r: share([_get(r, "B08301_003E")], _get(r, "B08301_001E")),
    ),
    Feature(
        "public_transit_share",
        "Share of workers who commute by public transport.",
        "Transit-dependent areas have lower vehicle demand and different parking.",
        lambda r: share([_get(r, "B08301_010E")], _get(r, "B08301_001E")),
    ),
    Feature(
        "worked_from_home_share",
        "Share of workers who worked from home.",
        "Home working shifts charging demand toward the residence and away from the "
        "commute corridor.",
        lambda r: share([_get(r, "B08301_021E")], _get(r, "B08301_001E")),
    ),
    Feature(
        "mean_commute_minutes",
        "Mean one-way commute duration in minutes, from binned counts.",
        "Commute duration proxies daily driving distance, which drives both energy "
        "demand and range anxiety.",
        lambda r: weighted_mean(_many(r, _COMMUTE_BINS), _COMMUTE_MIDPOINTS,
                                _get(r, "B08303_001E")),
    ),
    Feature(
        "bachelors_plus_share",
        "Share of the population aged 25 and over holding a bachelor's degree or above.",
        "Educational attainment is a consistent correlate of early EV adoption in the "
        "published literature and is not collinear with income at this grain.",
        lambda r: share(_many(r, _BACHELORS_PLUS), _get(r, "B15003_001E")),
    ),
)

FEATURE_NAMES: tuple[str, ...] = tuple(f.name for f in FEATURES)

#: The model target is a rate, not a count: EVs per household. Households is the
#: exposure, so an area with more households is expected to hold more EVs by
#: construction and the model explains the rate rather than rediscovering size.
EXPOSURE_VARIABLE = "B25003_001E"
POPULATION_VARIABLE = "B01003_001E"


def _density(row: Row) -> float | None:
    from math import log

    population = _get(row, POPULATION_VARIABLE)
    land_km2 = _get(row, "land_area_km2")
    if population is None or land_km2 is None or land_km2 <= 0:
        return None
    return log(max(population, 0.0) / land_km2 + 1.0)


def load_land_area_km2(geography: str, path: Path | None = None) -> dict[str, float]:
    """GEOID -> land area in square kilometres, from the Census gazetteer.

    Land area, not total area: a coastal tract that is mostly water would otherwise
    report a density near zero and read as rural.
    """
    source = path or GAZETTEER[geography]
    if not source.exists():
        raise FeatureError(
            f"gazetteer file missing at {source}. Population density cannot be "
            "computed without land area, and substituting total area or a constant "
            "would be a silent default (directive D8)."
        )
    areas: dict[str, float] = {}
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        for record in csv.DictReader(handle, delimiter="\t"):
            clean = {k.strip(): (v or "").strip() for k, v in record.items() if k}
            geoid = clean.get("GEOID", "")
            land = numeric(clean.get("ALAND"))
            if geoid and land is not None:
                areas[geoid] = land / 1_000_000.0
    if not areas:
        raise FeatureError(f"{source} parsed to zero areas")
    return areas


def to_numeric_row(
    raw: Mapping[str, str], land_area_km2: float | None = None
) -> dict[str, float | None]:
    """Parse one staged ACS row into numbers, attaching land area."""
    row: dict[str, float | None] = {
        name: numeric(value) for name, value in raw.items() if name != "geoid"
    }
    row["land_area_km2"] = land_area_km2
    return row


def compute_features(row: Row) -> dict[str, float | None]:
    """Every declared feature for one area. A feature that cannot be computed is None."""
    return {feature.name: feature.compute(row) for feature in FEATURES}


@dataclass(frozen=True)
class FeatureRow:
    """One area, ready for a model: identity, exposure, features, and what was missing."""

    geoid: str
    geography: str
    state_fips: str
    population: float
    households: float
    features: dict[str, float | None]

    @property
    def missing_features(self) -> tuple[str, ...]:
        return tuple(sorted(n for n, v in self.features.items() if v is None))


def build_feature_rows(
    staged: Iterable[Mapping[str, str]],
    geography: str,
    land_areas: Mapping[str, float],
    state_fips_of: Callable[[str], str],
) -> list[FeatureRow]:
    """Turn staged ACS rows into model-ready rows, preserving every input area.

    No row is dropped here. An area with no households is still emitted, with its
    exposure of zero visible, so that the decision to exclude it is taken once and
    recorded in a ledger rather than happening quietly inside a feature builder.
    """
    rows: list[FeatureRow] = []
    for raw in staged:
        geoid = str(raw["geoid"])
        numeric_row = to_numeric_row(raw, land_areas.get(geoid))
        rows.append(
            FeatureRow(
                geoid=geoid,
                geography=geography,
                state_fips=state_fips_of(geoid),
                population=float(numeric_row.get(POPULATION_VARIABLE) or 0.0),
                households=float(numeric_row.get(EXPOSURE_VARIABLE) or 0.0),
                features=compute_features(numeric_row),
            )
        )
    return rows


def impute(
    rows: Sequence[FeatureRow], names: Sequence[str] = FEATURE_NAMES
) -> tuple[list[dict[str, float]], list[int], dict[str, float]]:
    """Fill missing features with the national median, and count what was filled.

    Returns the filled feature dictionaries, a per-row count of how many features were
    imputed, and the medians used. The count is not decoration: it feeds the
    uncertainty score, so a row assembled largely from national medians cannot present
    itself as being as well evidenced as one with complete data.
    """
    medians: dict[str, float] = {}
    for name in names:
        present = sorted(
            value for row in rows
            if (value := row.features.get(name)) is not None
        )
        medians[name] = (present[len(present) // 2] if present else 0.0)
    filled: list[dict[str, float]] = []
    counts: list[int] = []
    for row in rows:
        record: dict[str, float] = {}
        missing = 0
        for name in names:
            value = row.features.get(name)
            if value is None:
                value = medians[name]
                missing += 1
            record[name] = float(value)
        filled.append(record)
        counts.append(missing)
    return filled, counts, medians


class _RecordingRow(dict):  # type: ignore[type-arg]
    """A row that answers every lookup and remembers what was asked for.

    Used to discover, by execution rather than by reading the source, exactly which
    inputs a feature consumes.
    """

    def __init__(self) -> None:
        super().__init__()
        self.accessed: set[str] = set()

    def get(self, key, default=None):  # type: ignore[no-untyped-def]
        self.accessed.add(str(key))
        # A value that is positive and non-zero keeps every denominator valid, so the
        # probe exercises the real code path rather than an early None return.
        return 1.0


def feature_inputs(feature: Feature) -> frozenset[str]:
    """Every input key a feature actually reads, discovered by running it."""
    probe = _RecordingRow()
    feature.compute(probe)
    return frozenset(probe.accessed)


def assert_primary_feature_set_is_clean(
    features: Sequence[Feature] = FEATURES,
) -> None:
    """Enforce D2 structurally: features may read ACS demographics and land area only.

    Checking prose would be theatre - the rationales legitimately discuss *home
    charging behaviour*, which is a property of housing, not a supply feature. What
    actually guarantees D2 is that no feature can reach a supply quantity, so this
    executes every feature against a recording row and asserts that the set of inputs
    it touched is a subset of the declared ACS variables plus land area. A feature that
    tried to read a charger count would fail here even if its name and description said
    nothing.
    """
    from pipeline.sources.census_acs import (
        ACS_VARIABLES,
        FORBIDDEN_WORD_PATTERN,
        assert_no_supply_features,
    )

    assert_no_supply_features(ACS_VARIABLES)
    allowed = set(ACS_VARIABLES) | {"land_area_km2"}
    for feature in features:
        used = feature_inputs(feature)
        stray = sorted(used - allowed)
        if stray:
            raise FeatureError(
                f"D2 violation: feature {feature.name!r} reads {stray}, which is not a "
                "declared ACS demographic variable. Supply-derived inputs belong only "
                "in the labelled ablation (CLAUDE.md D2 and §7.3)."
            )
    # Underscores are word characters, so "charger_density" does not match a \bcharger\b
    # pattern as written. Feature names are snake_case, so they are matched as words.
    named = sorted(f.name for f in features
                   if FORBIDDEN_WORD_PATTERN.search(f.name.replace("_", " ")))
    if named:
        raise FeatureError(
            f"D2 violation: feature name(s) {named} describe infrastructure."
        )
