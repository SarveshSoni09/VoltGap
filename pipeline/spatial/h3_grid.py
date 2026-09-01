"""The national H3 grid, and population-weighted allocation of tract quantities onto it.

CLAUDE.md §2 fixes the national spatial unit at **H3 resolution 6** (~36 km² per cell) and
§7.6 fixes how quantities get there:

> Allocate tract quantities to H3 cells using **block-level population weights**, not area
> weights. Area-weighted apportionment assumes uniform population within a tract, which is
> badly wrong in large rural tracts.

So a tract is never assigned to "its" cell by a centroid. Its population is distributed
across whatever cells its **block groups** fall in, and its demand follows that
distribution. A tract straddling a cell boundary contributes to both, in the proportion its
people actually sit.

**Block group, not block.** Phase 0 finding F-7 established that the Census publishes no
block-level population-weighted centroid product; block group is the finest ready-made one.
A block group averages ~1,380 people, so the corner-population problem §7.6 warns about
recurs at smaller scale. That is assumption **A-2.3**, and Phase 4 benchmarks it rather
than restating it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import h3

from pipeline.config.settings import PATHS
from pipeline.discovery.cache import Fetcher, ReplayFetcher
from pipeline.sources.base import DelimitedSource

#: CLAUDE.md §2: the national spatial unit. Resolution 8 is the metro unit (Phase 6).
RESOLUTION_NATIONAL = 6
RESOLUTION_METRO = 8

CENPOP_BASE = "https://www2.census.gov/geo/docs/reference/cenpop2020"


class GridError(ValueError):
    """A grid operation cannot be performed as specified."""


@dataclass(frozen=True)
class PopulationPoint:
    """One block group's population-weighted centroid."""

    tract_geoid: str
    block_group: str
    population: float
    latitude: float
    longitude: float

    def cell(self, resolution: int = RESOLUTION_NATIONAL) -> str:
        return str(h3.latlng_to_cell(self.latitude, self.longitude, resolution))


#: Census decennial vintages of the population-weighted centroid product. The 2020
#: edition is the production one; the 2010 edition exists because Phase 5's rolling
#: origins all resolve to ACS releases published on **2010** tract boundaries, and
#: allocating 2010-geography tract values with 2020 population weights would mix two
#: incompatible geographies. Directive D1 also applies: the 2020 centroids are a 2021
#: product and postdate every Phase 5 cutoff.
CENPOP_VINTAGES: dict[str, str] = {
    "2020": "https://www2.census.gov/geo/docs/reference/cenpop2020",
    "2010": "https://www2.census.gov/geo/docs/reference/cenpop2010",
}


def block_group_source(
    state_fips: str, census_vintage: str = "2020"
) -> DelimitedSource:
    """The cached per-state block-group centroid file for one decennial vintage.

    The 2020 source id matches what Phase 2 recorded, so the national cache replays
    offline unchanged; the 2010 edition takes its own id and its own cache entries.
    """
    if census_vintage not in CENPOP_VINTAGES:
        raise GridError(
            f"no population-weighted centroid product is declared for census vintage "
            f"{census_vintage!r}; known: {sorted(CENPOP_VINTAGES)}")
    base = CENPOP_VINTAGES[census_vintage]
    suffix = "" if census_vintage == "2020" else f"_{census_vintage}"
    url = f"{base}/blkgrp/CenPop{census_vintage}_Mean_BG{state_fips}.txt"
    params: dict[str, str] = {}
    if census_vintage != "2020":
        # The Census web application firewall rejects the BARE 2010 block-group URL for
        # Oklahoma (state 40) with an HTML "Request Rejected" page under HTTP 200, while
        # serving every other state, and serving Oklahoma's own tract and county files
        # normally. Any query string defeats whatever it is matching and returns the
        # identical 129,300-byte file.
        #
        # It is passed as a PARAMETER rather than spliced into the endpoint because the
        # fetcher calls httpx with `params=...`, and httpx REPLACES a URL's existing
        # query string when params are supplied - so an inline "?x=1" would be silently
        # stripped and the request would go out bare again.
        #
        # Applied to every state rather than only the one that needs it: a per-state
        # exception is a trap for whoever meets the next quirk. The parameter is inert,
        # and it is part of the cache key, so replay stays stable.
        params["product"] = f"cenpop{census_vintage}_blkgrp"
    return DelimitedSource(f"cenpop_bg{suffix}_{state_fips}", endpoint=url,
                           params=params)


def load_population_points(
    state_fips: str, fetcher: Fetcher | None = None,
    census_vintage: str = "2020",
) -> list[PopulationPoint]:
    """Every block-group population point in one state, for one decennial vintage."""
    table = block_group_source(state_fips, census_vintage).load(
        fetcher or ReplayFetcher(PATHS.cache))
    points: list[PopulationPoint] = []
    for row in table.rows:
        state = (row.get("STATEFP") or "").strip()
        county = (row.get("COUNTYFP") or "").strip()
        tract = (row.get("TRACTCE") or "").strip()
        if not (len(state) == 2 and len(county) == 3 and len(tract) == 6):
            continue
        try:
            population = float((row.get("POPULATION") or "0").strip())
            latitude = float((row.get("LATITUDE") or "").strip())
            longitude = float((row.get("LONGITUDE") or "").strip())
        except ValueError:
            continue
        points.append(PopulationPoint(
            tract_geoid=f"{state}{county}{tract}",
            block_group=(row.get("BLKGRPCE") or "").strip(),
            population=population, latitude=latitude, longitude=longitude,
        ))
    if not points:
        raise GridError(
            f"state {state_fips} (census {census_vintage}) yielded no block-group "
            "population points; a tract "
            "quantity cannot be allocated to cells without population weights, and "
            "falling back to area weights is what §7.6 forbids"
        )
    return points


@dataclass(frozen=True)
class TractCellWeights:
    """How one tract's population splits across H3 cells."""

    tract_geoid: str
    weights: Mapping[str, float]
    population: float

    def assert_normalised(self, tolerance: float = 1e-9) -> None:
        total = sum(self.weights.values())
        if abs(total - 1.0) > tolerance:
            raise GridError(
                f"{self.tract_geoid}: cell weights sum to {total}, not 1.0. An "
                "allocation that does not conserve mass silently creates or destroys "
                "vehicles."
            )


def tract_cell_weights(
    points: Iterable[PopulationPoint], resolution: int = RESOLUTION_NATIONAL
) -> dict[str, TractCellWeights]:
    """Population-weighted tract -> cell weights.

    A tract whose block groups report **no population at all** cannot be weighted by
    population. Its weight is split evenly across the cells its block groups sit in,
    which is recorded rather than hidden: an unpopulated tract carries no demand anyway,
    so the choice moves nothing, but pretending it was population-weighted would be a
    small lie in a provenance field.
    """
    grouped: dict[str, list[PopulationPoint]] = {}
    for point in points:
        grouped.setdefault(point.tract_geoid, []).append(point)

    out: dict[str, TractCellWeights] = {}
    for tract, members in grouped.items():
        cells: dict[str, float] = {}
        total = sum(p.population for p in members)
        if total > 0:
            for point in members:
                cell = point.cell(resolution)
                cells[cell] = cells.get(cell, 0.0) + point.population / total
        else:
            distinct = sorted({p.cell(resolution) for p in members})
            for cell in distinct:
                cells[cell] = 1.0 / len(distinct)
            total = 0.0
        weights = TractCellWeights(tract, cells, total)
        weights.assert_normalised()
        out[tract] = weights
    return out


def allocate_to_cells(
    values: Mapping[str, float], weights: Mapping[str, TractCellWeights]
) -> tuple[dict[str, float], dict[str, float]]:
    """Spread tract values onto cells. Returns (cell totals, values with no weights).

    A tract with no population weights is **returned, not dropped** (directive D8): it is
    a reportable gap, not something to make disappear.
    """
    cells: dict[str, float] = {}
    unallocated: dict[str, float] = {}
    for tract, value in values.items():
        entry = weights.get(tract)
        if entry is None:
            unallocated[tract] = value
            continue
        for cell, share in entry.weights.items():
            cells[cell] = cells.get(cell, 0.0) + value * share
    return cells, unallocated


def conservation_error(
    values: Mapping[str, float], cells: Mapping[str, float],
    unallocated: Mapping[str, float],
) -> float:
    """Allocation must conserve mass: what went in comes out, or is reported missing."""
    return abs(sum(values.values()) - sum(cells.values()) - sum(unallocated.values()))


def cell_centroid(cell: str) -> tuple[float, float]:
    latitude, longitude = h3.cell_to_latlng(cell)
    return float(latitude), float(longitude)


def cell_area_km2(cell: str) -> float:
    return float(h3.cell_area(cell, unit="km^2"))


def cells_for_points(
    latitudes: Sequence[float], longitudes: Sequence[float],
    resolution: int = RESOLUTION_NATIONAL,
) -> list[str]:
    """Cell index for each (lat, lon), used to place sites and stations on the grid."""
    if len(latitudes) != len(longitudes):
        raise GridError("latitude and longitude sequences must be the same length")
    return [str(h3.latlng_to_cell(lat, lon, resolution))
            for lat, lon in zip(latitudes, longitudes, strict=True)]
