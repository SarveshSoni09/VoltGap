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
from pipeline.spatial.distance import PolylineIndex

TIGER_YEAR = 2024
TIGER_BASE = f"https://www2.census.gov/geo/tiger/TIGER{TIGER_YEAR}/PRISECROADS"
ROADS_CACHE = PATHS.root / "data" / "cache" / "raw" / "tiger_roads"

#: The road classes the filter includes, and only these. Pre-registered in
#: docs/evidence/P4-0_road_filter_preregistration.md before any result was recomputed.
PRIMARY_ROAD = "S1100"
SECONDARY_ROAD = "S1200"
INCLUDED_MTFCC: frozenset[str] = frozenset({PRIMARY_ROAD, SECONDARY_ROAD})

#: WKB constants. Little-endian byte order, geometry type 2 = LineString,
#: type 5 = MultiLineString.
#:
#: MultiLineString appears rarely and only in some states: nationally, **3 of Ohio's
#: 10,350 included features (0.029%)** are MultiLineString and every other state is pure
#: LineString. Phase 4's six frontier states contain none, which is why this reader
#: shipped handling only type 2 — and it *raised* on the unexpected type rather than
#: mis-parsing it, so no Phase 4 result was ever affected. Found when Phase 6 first read
#: all 51 states. Impact-log entry I-27.
_WKB_LITTLE_ENDIAN = 1
_WKB_LINESTRING = 2
_WKB_MULTILINESTRING = 5
_WKB_HEADER = struct.Struct("<BII")
_WKB_POINT = struct.Struct("<dd")


class RoadSourceError(ValueError):
    """The road network could not be read, and no silent fallback is permitted."""


@dataclass(frozen=True)
class RoadVertices:
    """The road geometry of one state: vertices, plus where each feature starts.

    ``offsets`` is CSR-style — ``offsets[i]`` to ``offsets[i+1]`` are one feature's
    vertices — so segments are only ever formed *within* a feature. Flattening the
    vertices without it would join the end of one road to the start of the next and
    invent a segment that does not exist.
    """

    state_fips: str
    vintage: str
    latitudes: tuple[float, ...]
    longitudes: tuple[float, ...]
    offsets: tuple[int, ...]
    features: int
    excluded_classes: dict[str, int]

    def __len__(self) -> int:
        return len(self.latitudes)

    def index(self) -> PolylineIndex:
        """The searchable geometry: nearest point on a road, not nearest vertex."""
        return PolylineIndex(self.latitudes, self.longitudes, self.offsets)

    @property
    def segments(self) -> int:
        """Vertices minus one per feature: a run of n vertices makes n-1 segments."""
        return max(len(self) - (len(self.offsets) - 1), 0)

    def to_dict(self) -> dict[str, object]:
        return {
            "state_fips": self.state_fips,
            "vintage": self.vintage,
            "road_classes_included": sorted(INCLUDED_MTFCC),
            "features_included": self.features,
            "vertices": len(self),
            "segments": self.segments,
            "features_excluded_by_class": dict(sorted(self.excluded_classes.items())),
        }


def roads_url(state_fips: str) -> str:
    return f"{TIGER_BASE}/tl_{TIGER_YEAR}_{state_fips}_prisecroads.zip"


def roads_path(state_fips: str, cache_root: Path | None = None) -> Path:
    root = cache_root or ROADS_CACHE
    return root / f"tl_{TIGER_YEAR}_{state_fips}_prisecroads.zip"


def parse_wkb_linestring(payload: bytes, offset: int = 0) -> Iterator[tuple[float, float]]:
    """Yield (latitude, longitude) for every vertex of a WKB LineString.

    Raises rather than guessing on anything unexpected: a silently mis-parsed geometry
    would put roads in the wrong place, and a candidate filter built on it would look
    perfectly plausible while being wrong. Validation is **eager** — the header is
    checked before any iterator is returned — so a malformed payload cannot slip past a
    caller that builds the generator and consumes it somewhere else.
    """
    count, start = _linestring_header(payload, offset)
    if offset == 0 and len(payload) != start + count * _WKB_POINT.size:
        raise RoadSourceError(
            f"WKB LineString claims {count} points, which needs "
            f"{start + count * _WKB_POINT.size} bytes, but the payload is {len(payload)}"
        )
    return _wkb_points(payload, count, start)


def _linestring_header(payload: bytes, offset: int) -> tuple[int, int]:
    """Validate a LineString header at `offset`; return (point count, points offset)."""
    if len(payload) < offset + _WKB_HEADER.size:
        raise RoadSourceError(
            f"WKB payload is {len(payload)} bytes, too short to parse")
    order, geometry_type, count = _WKB_HEADER.unpack_from(payload, offset)
    if order != _WKB_LITTLE_ENDIAN:
        raise RoadSourceError(
            f"WKB byte order {order} is not little-endian; this reader does not "
            "byte-swap, and guessing would misplace every road"
        )
    if geometry_type != _WKB_LINESTRING:
        raise RoadSourceError(
            f"WKB geometry type {geometry_type} is not LineString ({_WKB_LINESTRING})"
        )
    return count, offset + _WKB_HEADER.size


def parse_wkb_geometry(payload: bytes) -> list[list[tuple[float, float]]]:
    """Every polyline in a WKB LineString or MultiLineString, as separate runs.

    **A MultiLineString's parts are returned separately and must stay separate.** Joining
    them into one run would invent a segment connecting the end of one part to the start
    of the next — a road that does not exist — which is the same error that feature
    offsets exist to prevent between features.
    """
    if len(payload) < _WKB_HEADER.size:
        raise RoadSourceError(
            f"WKB payload is {len(payload)} bytes, too short to parse")
    order, geometry_type, count = _WKB_HEADER.unpack_from(payload, 0)
    if order != _WKB_LITTLE_ENDIAN:
        raise RoadSourceError(
            f"WKB byte order {order} is not little-endian; this reader does not "
            "byte-swap, and guessing would misplace every road"
        )
    if geometry_type == _WKB_LINESTRING:
        return [list(parse_wkb_linestring(payload))]
    if geometry_type != _WKB_MULTILINESTRING:
        raise RoadSourceError(
            f"WKB geometry type {geometry_type} is neither LineString "
            f"({_WKB_LINESTRING}) nor MultiLineString ({_WKB_MULTILINESTRING}); "
            "TIGER road features are one or the other and anything else is unexpected"
        )
    parts: list[list[tuple[float, float]]] = []
    offset = _WKB_HEADER.size
    for _ in range(count):
        points, start = _linestring_header(payload, offset)
        needed = start + points * _WKB_POINT.size
        if len(payload) < needed:
            raise RoadSourceError(
                f"WKB MultiLineString part claims {points} points, needing {needed} "
                f"bytes, but the payload is {len(payload)}"
            )
        parts.append(list(_wkb_points(payload, points, start)))
        offset = needed
    return parts


def _wkb_points(payload: bytes, count: int, start: int) -> Iterator[tuple[float, float]]:
    for index in range(count):
        longitude, latitude = _WKB_POINT.unpack_from(
            payload, start + index * _WKB_POINT.size)
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
    offsets: list[int] = [0]
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
        # Each part of a MultiLineString gets its own offset run, so no segment is ever
        # formed between two parts that are not actually connected.
        for part in parse_wkb_geometry(bytes(geometry)):
            for latitude, longitude in part:
                latitudes.append(latitude)
                longitudes.append(longitude)
            offsets.append(len(latitudes))

    if not latitudes:
        raise RoadSourceError(
            f"{path} yielded no vertices for classes {sorted(wanted)}. A state with no "
            "primary or secondary roads is not plausible; this is a retrieval or "
            "parsing failure, not an empty road network."
        )
    return RoadVertices(
        state_fips=state_fips, vintage=str(TIGER_YEAR),
        latitudes=tuple(latitudes), longitudes=tuple(longitudes),
        offsets=tuple(offsets), features=kept, excluded_classes=excluded,
    )
