"""TIGER/Line roads: the Core road-network source for candidate filtering.

CLAUDE.md §7.8 requires siting candidates to be "within a configured distance of the road
network". Phase 4 first shipped without this, on the stated grounds that no road dataset
had been retrieved, and substituted a resident-population filter. **That premise was
wrong.** The Census Bureau publishes TIGER/Line road products, free and keyless, and a
population filter is not a road filter.

**Primary and secondary roads only** (MTFCC ``S1100`` and ``S1200``). At H3 resolution 6 —
38.2 km² per cell — almost every inhabited cell in the country contains some local street,
so including ``S1400`` would make the filter a near no-op rather than the siting constraint
the specification asks for. A public charging site needs arterial access. The consequence,
recorded rather than hidden: a cell served only by local streets is excluded even though
something could physically be built there.

**Geometry is parsed from WKB directly.** The vertices of a LineString are all this needs,
and WKB LineString is a fixed, trivially checkable layout: byte order, geometry type, point
count, then that many little-endian double pairs. Reading it here avoids adding geopandas,
shapely or pyarrow to a project whose first constraint is zero recurring cost and a
reproducible offline build.
"""

from __future__ import annotations

import struct
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from pipeline.config.settings import PATHS

TIGER_YEAR = 2024
TIGER_BASE = f"https://www2.census.gov/geo/tiger/TIGER{TIGER_YEAR}/PRISECROADS"
ROADS_CACHE = PATHS.root / "data" / "cache" / "raw" / "tiger_roads"

#: The road classes the filter includes, and only these. Pre-registered in
#: docs/evidence/P4-0_road_filter_preregistration.md before any result was recomputed.
PRIMARY_ROAD = "S1100"
SECONDARY_ROAD = "S1200"
INCLUDED_MTFCC: frozenset[str] = frozenset({PRIMARY_ROAD, SECONDARY_ROAD})

#: WKB constants. Little-endian byte order, geometry type 2 = LineString.
_WKB_LITTLE_ENDIAN = 1
_WKB_LINESTRING = 2
_WKB_HEADER = struct.Struct("<BII")
_WKB_POINT = struct.Struct("<dd")


class RoadSourceError(ValueError):
    """The road network could not be read, and no silent fallback is permitted."""


@dataclass(frozen=True)
class RoadVertices:
    """Every vertex of the included road classes in one state."""

    state_fips: str
    vintage: str
    latitudes: tuple[float, ...]
    longitudes: tuple[float, ...]
    features: int
    excluded_classes: dict[str, int]

    def __len__(self) -> int:
        return len(self.latitudes)

    def to_dict(self) -> dict[str, object]:
        return {
            "state_fips": self.state_fips,
            "vintage": self.vintage,
            "road_classes_included": sorted(INCLUDED_MTFCC),
            "features_included": self.features,
            "vertices": len(self),
            "features_excluded_by_class": dict(sorted(self.excluded_classes.items())),
        }


def roads_url(state_fips: str) -> str:
    return f"{TIGER_BASE}/tl_{TIGER_YEAR}_{state_fips}_prisecroads.zip"


def roads_path(state_fips: str, cache_root: Path | None = None) -> Path:
    root = cache_root or ROADS_CACHE
    return root / f"tl_{TIGER_YEAR}_{state_fips}_prisecroads.zip"


def parse_wkb_linestring(payload: bytes) -> Iterator[tuple[float, float]]:
    """Yield (latitude, longitude) for every vertex of a WKB LineString.

    Raises rather than guessing on anything unexpected: a silently mis-parsed geometry
    would put roads in the wrong place, and a candidate filter built on it would look
    perfectly plausible while being wrong. Validation is **eager** — the header is
    checked before any iterator is returned — so a malformed payload cannot slip past a
    caller that builds the generator and consumes it somewhere else.
    """
    if len(payload) < _WKB_HEADER.size:
        raise RoadSourceError(f"WKB payload is {len(payload)} bytes, too short to parse")
    order, geometry_type, count = _WKB_HEADER.unpack_from(payload, 0)
    if order != _WKB_LITTLE_ENDIAN:
        raise RoadSourceError(
            f"WKB byte order {order} is not little-endian; this reader does not "
            "byte-swap, and guessing would misplace every road"
        )
    if geometry_type != _WKB_LINESTRING:
        raise RoadSourceError(
            f"WKB geometry type {geometry_type} is not LineString ({_WKB_LINESTRING}); "
            "TIGER road features are LineStrings and anything else is unexpected"
        )
    expected = _WKB_HEADER.size + count * _WKB_POINT.size
    if len(payload) != expected:
        raise RoadSourceError(
            f"WKB LineString claims {count} points, which needs {expected} bytes, but "
            f"the payload is {len(payload)}"
        )
    return _wkb_points(payload, count)


def _wkb_points(payload: bytes, count: int) -> Iterator[tuple[float, float]]:
    for index in range(count):
        longitude, latitude = _WKB_POINT.unpack_from(
            payload, _WKB_HEADER.size + index * _WKB_POINT.size)
        yield latitude, longitude


def read_road_vertices(
    state_fips: str,
    cache_root: Path | None = None,
    included: Sequence[str] = tuple(sorted(INCLUDED_MTFCC)),
) -> RoadVertices:
    """Read one state's cached TIGER primary/secondary roads into vertices.

    **Raises if the artifact is missing.** Directive D8: candidate construction must not
    silently pass every cell through, and must not fall back to a different filter.
    """
    import pyogrio.raw

    path = roads_path(state_fips, cache_root)
    if not path.exists():
        raise RoadSourceError(
            f"TIGER road artifact missing at {path}. Fetch it from "
            f"{roads_url(state_fips)}. Candidate filtering must not proceed without the "
            "road network: passing every cell through would silently drop the filter, "
            "and falling back to a population filter is what this source exists to "
            "replace."
        )
    wanted = frozenset(included)
    try:
        _meta, _fids, geometries, fields = pyogrio.raw.read(
            f"zip://{path}", columns=["MTFCC"])
    except Exception as error:  # pragma: no cover - defensive, corrupt archive
        raise RoadSourceError(f"{path} could not be read: {error}") from error

    classes = fields[0]
    latitudes: list[float] = []
    longitudes: list[float] = []
    excluded: dict[str, int] = {}
    kept = 0
    for mtfcc, geometry in zip(classes, geometries, strict=True):
        code = str(mtfcc)
        if code not in wanted:
            excluded[code] = excluded.get(code, 0) + 1
            continue
        if geometry is None:
            excluded["missing_geometry"] = excluded.get("missing_geometry", 0) + 1
            continue
        kept += 1
        for latitude, longitude in parse_wkb_linestring(bytes(geometry)):
            latitudes.append(latitude)
            longitudes.append(longitude)

    if not latitudes:
        raise RoadSourceError(
            f"{path} yielded no vertices for classes {sorted(wanted)}. A state with no "
            "primary or secondary roads is not plausible; this is a retrieval or "
            "parsing failure, not an empty road network."
        )
    return RoadVertices(
        state_fips=state_fips, vintage=str(TIGER_YEAR),
        latitudes=tuple(latitudes), longitudes=tuple(longitudes),
        features=kept, excluded_classes=excluded,
    )
