"""ACS 5-year tract features: the primary demand model's entire input.

**Directive D2 governs this file.** The Phase 3 primary demand model may use
demographics and nothing else. Charger counts, port counts, charger density, network
presence, distance to the nearest charger and any transform of them are forbidden,
because existing infrastructure is an *outcome* of prior investment decisions:
predicting demand from it and then siting from that demand launders historical
deployment patterns into "need" and suppresses exactly the underserved areas this
project exists to find. Every variable below is a property of people and housing. The
file contains no supply-derived quantity, and a test asserts that.

**Retrieval path.** The keyed JSON API rather than the bulk summary file. The Live
Integration Assurance Checkpoint established that the two agree exactly for the same
tract, variable and vintage, that they name the same variable differently
(``B25003_001E`` on the API against ``B25003_E001`` in the bulk file), and that a
keyless API request returns **HTTP 200 with an HTML "Missing Key" page** rather than a
4xx. The API is used because it serves tract grain directly; the bulk files carry every
geography level in one 17-63 MB download per table.

**Losslessness (A15).** The API caps a request at 50 variables, so a state needs several
requests. Joining those batches on the tract's own geography keys is a mechanical
reshape, not a filter: the adapter asserts that every batch returns the same tract set
and that the staged row count equals the number of tracts retrieved.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pipeline.discovery.cache import Fetcher
from pipeline.sources.base import LossyStagingError, Source, StagedTable

ACS_YEAR = 2023
ACS_DATASET = "acs/acs5"
ACS_BASE = "https://api.census.gov/data"

# The API refuses more than 50 variables in one `get`. Three geography columns come
# back automatically and do not count, but NAME does, so batches stay below the cap.
MAX_VARIABLES_PER_REQUEST = 48


@dataclass(frozen=True)
class FeatureTable:
    """One ACS table and why the demand model is allowed to use it."""

    table_id: str
    concept: str
    variables: tuple[str, ...]
    rationale: str


def _range(table: str, start: int, stop: int) -> tuple[str, ...]:
    return tuple(f"{table}_{i:03d}E" for i in range(start, stop + 1))


# CLAUDE.md 7.3 names the primary feature set: median household income, income
# distribution, housing tenure, units in structure, vehicles available per household,
# population density, commute distance and mode, urban/rural classification,
# educational attainment. Home charging access is EXCLUDED (amendment A7: the NREL
# dataset is a parametric scenario surface, not a dated observation).
FEATURE_TABLES: tuple[FeatureTable, ...] = (
    FeatureTable(
        "B01003", "total population", ("B01003_001E",),
        "Population is the denominator for the per-capita target and, with tract land "
        "area, gives population density.",
    ),
    FeatureTable(
        "B19013", "median household income", ("B19013_001E",),
        "Purchase price is the most-cited determinant of EV adoption; median income is "
        "the standard tract-level summary of ability to pay.",
    ),
    FeatureTable(
        "B19001", "household income distribution", _range("B19001", 1, 17),
        "A median hides the shape of the distribution. Two tracts with the same median "
        "and different dispersion have different adoption capacity.",
    ),
    FeatureTable(
        "B25003", "housing tenure", _range("B25003", 1, 3),
        "Owners can install home charging; renters usually cannot. Tenure is the "
        "strongest housing-side constraint on adoption that ACS reports directly.",
    ),
    FeatureTable(
        "B25024", "units in structure", _range("B25024", 1, 11),
        "Single-family detached housing supports a dedicated parking space and a "
        "circuit; multifamily typically does not.",
    ),
    FeatureTable(
        "B25044", "vehicles available", _range("B25044", 1, 15),
        "A household with no vehicle is not an EV prospect; a household with several "
        "can replace one without losing mobility.",
    ),
    FeatureTable(
        "B08301", "means of transportation to work",
        ("B08301_001E", "B08301_002E", "B08301_003E", "B08301_004E",
         "B08301_010E", "B08301_019E", "B08301_021E"),
        "Commute mode separates car-dependent tracts from transit- and "
        "walking-dependent ones, which face different charging needs.",
    ),
    FeatureTable(
        "B08303", "travel time to work", _range("B08303", 1, 13),
        "Commute duration proxies daily driving distance, which drives both energy "
        "demand and range anxiety.",
    ),
    FeatureTable(
        "B15003", "educational attainment",
        ("B15003_001E", *_range("B15003", 17, 25)),
        "Educational attainment is a consistent correlate of early EV adoption in the "
        "published literature and is not collinear with income at tract grain.",
    ),
)

ACS_VARIABLES: tuple[str, ...] = tuple(
    variable for table in FEATURE_TABLES for variable in table.variables
)

# Every word a supply-derived feature would have to arrive through. Asserted absent.
# Matched on WHOLE WORDS: "means of transportation to work" is a commute-mode concept
# and must not be rejected because "transportation" contains "port".
FORBIDDEN_FEATURE_WORDS: tuple[str, ...] = (
    "charger", "chargers", "charging", "port", "ports", "evse", "station", "stations",
    "network", "networks", "plug", "plugs", "connector", "connectors", "charge",
)
FORBIDDEN_WORD_PATTERN = re.compile(
    r"\b(" + "|".join(FORBIDDEN_FEATURE_WORDS) + r")\b", re.IGNORECASE
)

def batches(
    variables: Sequence[str], size: int = MAX_VARIABLES_PER_REQUEST
) -> list[tuple[str, ...]]:
    """Split the variable list into request-sized groups, order preserved."""
    return [tuple(variables[i:i + size]) for i in range(0, len(variables), size)]


@dataclass(frozen=True)
class AcsGeography:
    """One ACS summary level, and how to ask the API for it.

    The geography is declared here rather than inferred from a column name, for the
    same reason CLAUDE.md §7.5.1 requires it of registration sources: a column called
    ``zip code tabulation area`` is a **ZCTA**, an approximating *area* built from
    census blocks, and is not a USPS ZIP Code. Conflating them is the error the
    specification names explicitly.
    """

    name: str
    for_clause: str
    key_columns: tuple[str, ...]
    per_state: bool
    in_clause: str | None = None

    def source_id(self, state_fips: str | None) -> str:
        return (f"census_acs_{self.name}_{state_fips}" if self.per_state
                else f"census_acs_{self.name}")


#: Tract is the prediction grain. ZCTA and county are the grains at which sub-state
#: registration counts are actually observed, so a model can be fitted against observed
#: counts WITHOUT manufacturing tract-level pseudo-labels first (see the Phase 3
#: pre-registration §3). ACS publishes all three directly, so no crosswalk touches the
#: feature side at all.
TRACT = AcsGeography("tracts", "tract:*", ("state", "county", "tract"), True,
                     "state:{state_fips}")
ZCTA = AcsGeography("zcta", "zip code tabulation area:*",
                    ("zip code tabulation area",), False)
COUNTY = AcsGeography("county", "county:*", ("state", "county"), False, "state:*")


class AcsSource(Source):
    """Every ACS feature variable for every area of one summary level."""

    def __init__(
        self,
        geography: AcsGeography = TRACT,
        state_fips: str | None = None,
        variables: Sequence[str] = ACS_VARIABLES,
        year: int = ACS_YEAR,
        dataset: str = ACS_DATASET,
        api_key: str = "",
    ) -> None:
        if geography.per_state and state_fips is None:
            raise ValueError(f"{geography.name} must be requested one state at a time")
        super().__init__(geography.source_id(state_fips),
                         f"{ACS_BASE}/{year}/{dataset}")
        self.geography = geography
        self.state_fips = state_fips
        self.variables = tuple(variables)
        self.year = year
        self.api_key = api_key

    def _params(self, group: Sequence[str]) -> dict[str, str]:
        """Request parameters, with ``key`` ALWAYS present.

        The cache key hashes the *redacted* parameter map, which replaces a secret's
        value but keeps its name. A request carrying ``key`` therefore hashes
        differently from one omitting it, so a source that only adds ``key`` when a
        credential happens to be configured would record under one identity and replay
        under another - and the deterministic gate, which runs without credentials,
        would miss every cached response. Emitting the name unconditionally keeps the
        identity stable; the value is still never written to disk.
        """
        params = {"get": ",".join(group), "for": self.geography.for_clause,
                  "key": self.api_key}
        if self.geography.in_clause:
            params["in"] = self.geography.in_clause.format(state_fips=self.state_fips)
        return params

    def load(self, fetcher: Fetcher | None = None) -> StagedTable:
        if fetcher is None:
            raise ValueError(f"{self.source_id}: remote source needs a fetcher")

        keys = self.geography.key_columns
        merged: dict[str, dict[str, str]] = {}
        order: list[str] = []
        seen: list[frozenset[str]] = []
        last_response = None
        for group in batches(self.variables):
            response = fetcher.get(self.source_id, self.endpoint, self._params(group))
            last_response = response
            payload = self._decode(response.content)
            header, rows = payload[0], payload[1:]
            index = {name: position for position, name in enumerate(header)}
            for column in keys:
                if column not in index:
                    raise LossyStagingError(
                        f"{self.source_id}: response is missing geography column "
                        f"{column!r}; an area cannot be identified without it"
                    )
            batch_keys: set[str] = set()
            for row in rows:
                geoid = "".join(row[index[c]] for c in keys)
                batch_keys.add(geoid)
                if geoid not in merged:
                    merged[geoid] = {"geoid": geoid,
                                     **{c: row[index[c]] for c in keys}}
                    order.append(geoid)
                for name in group:
                    merged[geoid][name] = row[index[name]]
            seen.append(frozenset(batch_keys))

        for position, batch in enumerate(seen[1:], start=1):
            if batch != seen[0]:
                raise LossyStagingError(
                    f"{self.source_id}: request batch {position} returned "
                    f"{len(batch)} areas against {len(seen[0])} in batch 0. "
                    "Batches must cover the same areas or the join loses rows."
                )

        columns = ("geoid", *keys, *self.variables)
        staged = [{name: merged[geoid].get(name, "") for name in columns}
                  for geoid in order]
        return StagedTable(
            self.source_id, columns, staged,
            self._vintage(last_response, vintage=f"ACS {self.year} 5-year"),
            len(seen[0]),
        ).assert_lossless()

    def _decode(self, content: bytes) -> list[list[str]]:
        """Parse the API's array-of-arrays, refusing the HTML credential page.

        A keyless request answers HTTP 200 with an HTML "Missing Key" page, so a status
        check alone would treat a credential failure as success. This is the trap the
        Live Integration Assurance Checkpoint found.
        """
        text = content.decode("utf-8", errors="replace").lstrip()
        if text.startswith("<"):
            raise LossyStagingError(
                f"{self.source_id}: the Census API returned HTML rather than JSON, "
                "which is how it reports a missing or invalid key even under HTTP 200. "
                "Set CENSUS_API_KEY."
            )
        document = json.loads(text)
        if not isinstance(document, list) or not document:
            raise LossyStagingError(
                f"{self.source_id}: expected a non-empty array of arrays, got "
                f"{type(document).__name__}"
            )
        return [[("" if v is None else str(v)) for v in row] for row in document]


def AcsTractSource(state_fips: str, **kwargs: object) -> AcsSource:  # noqa: N802
    """Backwards-compatible constructor for the tract-grain source."""
    return AcsSource(TRACT, state_fips, **kwargs)  # type: ignore[arg-type]


def assert_no_supply_features(variables: Sequence[str],
                              concepts: Mapping[str, str] | None = None) -> None:
    """Enforce D2 over the declared feature set.

    Raises if any variable id or concept mentions infrastructure. This is a runtime
    assertion rather than a comment because CLAUDE.md §18 anti-pattern 5 is precisely
    that supply features *improve fit*, so the pressure to admit one is real.
    """
    text = {v: v.lower() for v in variables}
    if concepts:
        for variable, concept in concepts.items():
            text[variable] = f"{text.get(variable, variable.lower())} {concept.lower()}"
    offending = sorted(
        variable for variable, blob in text.items()
        if FORBIDDEN_WORD_PATTERN.search(blob)
    )
    if offending:
        raise ValueError(
            f"D2 violation: supply-derived feature(s) {offending} in the primary "
            "demand feature set. Supply features belong only in the labelled ablation."
        )
