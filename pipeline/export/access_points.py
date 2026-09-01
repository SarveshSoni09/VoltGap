"""Block-group access points: the artifact behind the live threshold control.

§11.1's Access and Equity view needs a **live** threshold control with a sensitivity curve,
and §7.5 requires access to be measured from population-weighted points rather than tract
geometric centroids — in a large rural tract the population often occupies one corner.

Shipping the per-point distances rather than a precomputed curve is what makes the control
genuinely live: the browser recomputes the affected population at any threshold the user
picks, instead of interpolating between server-chosen points.

**On the filename.** §11.4 calls this artifact `tract_access.parquet`. What Phase 2 actually
measured, and what this ships, is **block-group** population-weighted points — a finer grain
than tract and the one §7.6 asks for. Naming the file `tract_access` would misdescribe its
grain, which is exactly the kind of quiet imprecision §7.4.1 and §11.5 exist to prevent, so
it ships as `access_points.parquet` and the deviation is recorded in the Phase 6 report.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pipeline.model.access import AccessThresholds
from pipeline.spatial.distance import nearest_site_distances
from pipeline.spatial.h3_grid import PopulationPoint, cells_for_points

ACCESS_COLUMNS: tuple[str, ...] = (
    "block_group_geoid",
    "tract_geoid",
    "state_fips",
    "h3_index",
    "latitude",
    "longitude",
    "population",
    "km_to_nearest_dcfc_site",
    "km_to_nearest_l2_site",
    "income_share_under_35k",
)


def build_access_points(
    points_by_state: Mapping[str, Sequence[PopulationPoint]],
    dcfc_sites: Sequence[tuple[float, float]],
    l2_sites: Sequence[tuple[float, float]],
    income_share_by_tract: Mapping[str, float],
    resolution: int,
) -> list[dict[str, Any]]:
    """One row per block-group population-weighted point, with both access distances.

    The equity indicator is the tract's, attached to each of its block groups: it is an
    ACS five-year tract-level share, and block groups nest inside tracts. That is an
    attribution, not a measurement at block-group grain, and the column name says which
    indicator it is rather than calling itself a disadvantage score (§8, A-4.3).
    """
    flat: list[PopulationPoint] = []
    states: list[str] = []
    for state, points in sorted(points_by_state.items()):
        for point in points:
            flat.append(point)
            states.append(state)
    if not flat:
        return []

    latitudes = [p.latitude for p in flat]
    longitudes = [p.longitude for p in flat]
    cells = cells_for_points(latitudes, longitudes, resolution)
    dcfc = nearest_site_distances(latitudes, longitudes,
                                  [lat for lat, _ in dcfc_sites],
                                  [lon for _, lon in dcfc_sites])
    l2 = nearest_site_distances(latitudes, longitudes,
                                [lat for lat, _ in l2_sites],
                                [lon for _, lon in l2_sites])

    rows: list[dict[str, Any]] = []
    for point, state, cell, dcfc_m, l2_m in zip(
            flat, states, cells, dcfc.distances_m, l2.distances_m, strict=True):
        tract = point.tract_geoid
        rows.append({
            "block_group_geoid": f"{tract}{point.block_group}",
            "tract_geoid": tract,
            "state_fips": state,
            "h3_index": cell,
            "latitude": round(point.latitude, 6),
            "longitude": round(point.longitude, 6),
            "population": float(point.population),
            "km_to_nearest_dcfc_site": _km(dcfc_m),
            "km_to_nearest_l2_site": _km(l2_m),
            "income_share_under_35k": round(
                float(income_share_by_tract.get(tract, 0.0)), 6),
        })
    rows.sort(key=lambda r: str(r["block_group_geoid"]))
    return rows


def _km(metres: float) -> float:
    return float("inf") if metres == float("inf") else round(metres / 1000.0, 4)


def gap_population(rows: Sequence[Mapping[str, Any]], threshold_km: float,
                   column: str = "km_to_nearest_dcfc_site") -> float:
    """Population beyond the threshold. The same arithmetic the browser control runs."""
    return sum(float(r["population"]) for r in rows
               if float(r[column]) > threshold_km)


def sensitivity_curve(
    rows: Sequence[Mapping[str, Any]], thresholds: AccessThresholds,
    column: str = "km_to_nearest_dcfc_site",
) -> list[dict[str, float]]:
    """The published curve, so the shipped artifact and the live control can be compared."""
    return [{"threshold_km": float(t),
             "population_in_gap": gap_population(rows, float(t), column)}
            for t in thresholds.sensitivity_km]
