"""Phase 2 preflight investigations (CLAUDE.md 15.5.1 and 15.5.2, amendment A24).

Two bounded questions that must be answered before Phase 2 publishes national results:

1. **The 22 station reconciliation exceptions.** Phase 1 measured charging-unit row
   count against each station's reported ``L1 + L2 + DCFC`` and found agreement for
   89,665 of 89,687 stations. That is **99.975%, not 100%** — the one-decimal display
   rounded it up. The exceptions must be classified before Phase 2 relies on the
   equivalence.

2. **The site-resolution diagnostic.** DBSCAN connectivity is *transitive*: if A-B is
   40 m and B-C is 40 m, all three join one component even though A-C is 80 m. So
   ``eps = 50 m`` does not bound cluster diameter, and Phase 2 access metrics depend on
   ``site_id``. This measures the clusters rather than assuming they are sound.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pipeline.spatial.clustering import haversine_m

STATION_LEVEL_FIELDS = ("ev_level1_evse_num", "ev_level2_evse_num", "ev_dc_fast_num")


class ReconciliationClass(StrEnum):
    """Why a station's unit rows disagree with its reported EVSE totals."""

    RECONCILES = "reconciles"
    LEGACY_CHARGING_LEVEL = "legacy_charging_level"
    MISSING_STATION_AGGREGATE = "missing_station_aggregate"
    UPSTREAM_COUNT_MISMATCH = "upstream_count_mismatch"
    NO_UNIT_RECORDS = "no_unit_records"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class ReconciliationException:
    """One station whose unit rows do not match its reported EVSE totals."""

    station_id: str
    status_code: str
    access_code: str
    network: str
    unit_row_count: int
    reported_l1: int | None
    reported_l2: int | None
    reported_dcfc: int | None
    reported_total: int | None
    difference: int | None
    charging_levels: tuple[str, ...]
    connector_types: tuple[str, ...]
    classification: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "station_id": self.station_id,
            "status_code": self.status_code,
            "access_code": self.access_code,
            "network": self.network,
            "unit_row_count": self.unit_row_count,
            "reported_l1": self.reported_l1,
            "reported_l2": self.reported_l2,
            "reported_dcfc": self.reported_dcfc,
            "reported_total": self.reported_total,
            "difference": self.difference,
            "charging_levels": list(self.charging_levels),
            "connector_types": list(self.connector_types),
            "classification": self.classification,
        }


def _int_or_none(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def classify_exception(
    unit_row_count: int,
    reported_total: int | None,
    reported_parts: Sequence[int | None],
    charging_levels: Sequence[str],
) -> ReconciliationClass:
    """Assign a documented classification. Never discards an exception silently."""
    if reported_total is not None and unit_row_count == reported_total:
        return ReconciliationClass.RECONCILES
    if unit_row_count == 0:
        return ReconciliationClass.NO_UNIT_RECORDS
    if all(part is None for part in reported_parts):
        return ReconciliationClass.MISSING_STATION_AGGREGATE
    if "legacy" in charging_levels:
        # `legacy` units are not counted in any of L1/L2/DCFC, so a station holding
        # them reports fewer EVSE than it has unit rows. Benign and explainable.
        return ReconciliationClass.LEGACY_CHARGING_LEVEL
    if reported_total is not None:
        return ReconciliationClass.UPSTREAM_COUNT_MISMATCH
    return ReconciliationClass.UNRESOLVED


def reconcile_stations(stations: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Compare unit-row count against reported EVSE totals for every station.

    Each station mapping must carry ``id``, the three level fields, and a list of
    nested ``ev_charging_units``.
    """
    exceptions: list[ReconciliationException] = []
    total = 0
    reconciling = 0
    for station in stations:
        total += 1
        units = station.get("ev_charging_units") or []
        parts = [_int_or_none(station.get(f)) for f in STATION_LEVEL_FIELDS]
        reported = None if all(p is None for p in parts) else sum(p or 0 for p in parts)
        levels = tuple(sorted({str(u.get("charging_level", "")) for u in units}))
        if reported is not None and len(units) == reported:
            reconciling += 1
            continue
        connectors = sorted({
            name for u in units
            for name, spec in (u.get("connectors") or {}).items()
            if int((spec or {}).get("port_count") or 0) > 0
        })
        exceptions.append(ReconciliationException(
            station_id=str(station.get("id", "")),
            status_code=str(station.get("status_code", "")),
            access_code=str(station.get("access_code", "")),
            network=str(station.get("ev_network", "")),
            unit_row_count=len(units),
            reported_l1=parts[0], reported_l2=parts[1], reported_dcfc=parts[2],
            reported_total=reported,
            difference=None if reported is None else len(units) - reported,
            charging_levels=levels,
            connector_types=tuple(connectors),
            classification=str(classify_exception(len(units), reported, parts, levels)),
        ))
    tally: dict[str, int] = {}
    for exception in exceptions:
        tally[exception.classification] = tally.get(exception.classification, 0) + 1
    return {
        "stations_examined": total,
        "stations_reconciling": reconciling,
        "exception_count": len(exceptions),
        "reconciliation_rate": round(reconciling / total, 6) if total else 0.0,
        "classification_tally": dict(sorted(tally.items())),
        "exceptions": [e.to_dict() for e in exceptions],
        "note": (
            "Reconciliation rate is reported to six decimal places. It must never be "
            "described as 100% unless it is literally 1.0 after a documented scope "
            "definition is applied (CLAUDE.md 15.5.1)."
        ),
    }


# --- site-resolution diagnostic ------------------------------------------------------

@dataclass(frozen=True)
class ClusterDiagnostic:
    """Measured geometry of one resolved site."""

    site_id: str
    station_count: int
    diameter_m: float
    network_count: int
    distinct_names: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "site_id": self.site_id, "station_count": self.station_count,
            "diameter_m": round(self.diameter_m, 2), "network_count": self.network_count,
            "distinct_names": self.distinct_names,
        }


# Diameter bands used for reporting. eps is 50 m, but transitive connectivity means a
# cluster can legitimately exceed it, so the bands go well beyond.
DIAMETER_BANDS_M: tuple[float, ...] = (50.0, 100.0, 200.0, 500.0)
# Above this, a cluster is called out for individual review. Two stations 200 m apart
# are unlikely to be one physical site.
SUSPICIOUS_DIAMETER_M = 200.0
# Sampling cap: cluster diameter is O(n^2) in stations, and a handful of very large
# clusters would otherwise dominate runtime for no extra signal.
MAX_EXACT_DIAMETER_STATIONS = 60


def cluster_diameter_m(points: Sequence[tuple[float, float]]) -> float:
    """Maximum pairwise great-circle distance within a cluster."""
    if len(points) < 2:
        return 0.0
    sample = points[:MAX_EXACT_DIAMETER_STATIONS]
    return max(haversine_m(a[0], a[1], b[0], b[1])
               for a, b in itertools.combinations(sample, 2))


def diagnose_sites(assignments: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Measure cluster size and diameter distributions.

    Each mapping carries ``site_id``, ``station_id``, ``latitude``, ``longitude``, and
    optionally ``ev_network`` and ``station_name``.
    """
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in assignments:
        grouped.setdefault(str(row["site_id"]), []).append(row)

    diagnostics: list[ClusterDiagnostic] = []
    for site_id, members in grouped.items():
        points = [
            (float(m["latitude"]), float(m["longitude"]))
            for m in members
            if m.get("latitude") is not None and m.get("longitude") is not None
            and str(m["latitude"]) not in ("nan", "None")
        ]
        diagnostics.append(ClusterDiagnostic(
            site_id=site_id,
            station_count=len(members),
            diameter_m=cluster_diameter_m(points),
            network_count=len({str(m.get("ev_network", "")) for m in members}),
            distinct_names=len({str(m.get("station_name", "")) for m in members}),
        ))

    multi = [d for d in diagnostics if d.station_count > 1]
    diameters = sorted(d.diameter_m for d in multi)
    suspicious = sorted((d for d in multi if d.diameter_m > SUSPICIOUS_DIAMETER_M),
                        key=lambda d: -d.diameter_m)
    return {
        "clusters": len(diagnostics),
        "stations": sum(d.station_count for d in diagnostics),
        "singleton_clusters": sum(1 for d in diagnostics if d.station_count == 1),
        "singleton_share": round(
            sum(1 for d in diagnostics if d.station_count == 1) / len(diagnostics), 6
        ) if diagnostics else 0.0,
        "clusters_with_at_least": {
            str(n): sum(1 for d in diagnostics if d.station_count >= n)
            for n in (2, 5, 10)
        },
        "max_station_count": max((d.station_count for d in diagnostics), default=0),
        "multi_station_clusters": len(multi),
        "diameter_m": {
            "min": round(diameters[0], 2) if diameters else 0.0,
            "median": round(diameters[len(diameters) // 2], 2) if diameters else 0.0,
            "max": round(diameters[-1], 2) if diameters else 0.0,
        },
        "clusters_exceeding_diameter": {
            str(int(band)): sum(1 for d in multi if d.diameter_m > band)
            for band in DIAMETER_BANDS_M
        },
        "suspicious_cluster_count": len(suspicious),
        "suspicious_share_of_multi": round(len(suspicious) / len(multi), 6) if multi else 0.0,
        "suspicious_clusters": [d.to_dict() for d in suspicious[:25]],
        "note": (
            "DBSCAN connectivity is transitive, so eps = 50 m does not bound cluster "
            "diameter: A-B 40 m and B-C 40 m puts A and C (80 m apart) in one cluster. "
            "Clusters exceeding the suspicious threshold are listed for review "
            "(CLAUDE.md 15.5.2)."
        ),
    }
