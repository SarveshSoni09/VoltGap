"""Aggregating the tract demand surface onto the national H3 grid.

**Uncertainty and evidence provenance must survive this step.** A hex that reports only a
demand number has thrown away everything Phase 3 built: how well evidenced that demand is,
what kind of observation supports it, and which tier it falls in. Directive D7 makes
uncertainty a first-class output, and §11.1 requires every aggregate to report its
sub-state-anchored versus modelled share with the `evidence_grain` breakdown beneath it. So
each cell carries, alongside its demand:

* the demand-weighted mean uncertainty **and all five of its components**, so a
  weight-sensitivity control still works at this layer;
* the share of its demand by `evidence_grain`, by `confidence_tier`, and by
  `value_provenance`;
* how many tracts contributed and what share of its demand came from the largest one.

Weighting is by **demand**, not by tract count or area: a cell whose demand is 95% from a
well-evidenced tract and 5% from a poorly evidenced one is mostly well evidenced, and a
plain mean over tracts would say otherwise.

**A zero-demand cell is not dropped.** It is a legitimate candidate location - somewhere
with no EVs today may still be worth serving - and it carries its provenance like any
other.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.model.build_demand import TractEstimate
from pipeline.model.uncertainty import COMPONENT_NAMES
from pipeline.spatial.h3_grid import (
    RESOLUTION_NATIONAL,
    TractCellWeights,
    cell_area_km2,
    cell_centroid,
)


class HexAggregationError(ValueError):
    """The hex layer cannot be built as specified."""


@dataclass(frozen=True)
class HexSupply:
    """Existing public operational supply in a cell. Used for saturation, never for demand.

    **Port COUNTS only, deliberately: no resolved capacity in kW.** Assumption A-2.2 makes
    a masked-power validation of the rung-2 empirical median a prerequisite for any phase
    that consumes *imputed* capacity, and 19.85% of all resolved power comes from that
    rung. Phase 4 sidesteps the question entirely by never reading a kW figure: port
    counts are reported directly by the source and involve no power-resolution ladder at
    all. There is no ``capacity_kw`` field here, so the prerequisite cannot be violated by
    accident - only by someone adding one, which a test forbids.
    """

    #: Distinct AFDC **stations**, not DBSCAN sites. ``load_hex_supply`` places each
    #: station at its own reported coordinates and never clusters, so calling this a
    #: site count would misname it. Whether clustering would change anything is measured
    #: by the A-2.1 sensitivity rather than assumed either way.
    station_count: int = 0
    dcfc_ports: float = 0.0
    l2_ports: float = 0.0


@dataclass(frozen=True)
class HexCell:
    """One H3 cell, carrying its demand and everything needed to judge it."""

    h3_index: str
    resolution: int
    latitude: float
    longitude: float
    area_km2: float
    demand_bev: float
    population: float
    households: float
    equity_population: float
    tracts_contributing: int
    largest_tract_share: float
    uncertainty_score: float
    uncertainty_components: Mapping[str, float]
    evidence_grain_share: Mapping[str, float]
    confidence_tier_share: Mapping[str, float]
    value_provenance_share: Mapping[str, float]
    supply: HexSupply = field(default_factory=HexSupply)

    @property
    def sub_state_anchored_share(self) -> float:
        """Share of this cell's demand resting on observed sub-state evidence (§11.1).

        Clamped to [0, 1]: floating-point accumulation over many tracts can put the
        complement a hair outside, and a share of -0.0000001 published as "-0.000" reads
        as a defect rather than as rounding.
        """
        share = 1.0 - self.evidence_grain_share.get("state_total_only", 0.0)
        return min(1.0, max(0.0, share))

    @property
    def dominant_evidence_grain(self) -> str:
        if not self.evidence_grain_share:
            return "none"
        return max(sorted(self.evidence_grain_share),
                   key=lambda k: self.evidence_grain_share[k])

    def to_dict(self) -> dict[str, object]:
        return {
            "h3_index": self.h3_index,
            "resolution": self.resolution,
            "latitude": round(self.latitude, 6),
            "longitude": round(self.longitude, 6),
            "area_km2": round(self.area_km2, 4),
            "demand_bev": round(self.demand_bev, 4),
            "population": round(self.population, 1),
            "households": round(self.households, 1),
            "equity_population": round(self.equity_population, 2),
            "tracts_contributing": self.tracts_contributing,
            "largest_tract_share": round(self.largest_tract_share, 6),
            "uncertainty_score": round(self.uncertainty_score, 6),
            "uncertainty_components": {
                k: round(v, 6) for k, v in sorted(self.uncertainty_components.items())},
            "evidence_grain_share": {
                k: round(v, 6) for k, v in sorted(self.evidence_grain_share.items())},
            "confidence_tier_share": {
                k: round(v, 6) for k, v in sorted(self.confidence_tier_share.items())},
            "value_provenance_share": {
                k: round(v, 6) for k, v in sorted(self.value_provenance_share.items())},
            "sub_state_anchored_share": round(self.sub_state_anchored_share, 6),
            "dominant_evidence_grain": self.dominant_evidence_grain,
            "station_count": self.supply.station_count,
            "dcfc_ports": round(self.supply.dcfc_ports, 2),
            "l2_ports": round(self.supply.l2_ports, 2),
        }


def _weighted_shares(pairs: Sequence[tuple[str, float]]) -> dict[str, float]:
    """Category -> share of total weight. Empty when nothing carries weight."""
    total = sum(weight for _, weight in pairs)
    if total <= 0:
        return {}
    out: dict[str, float] = {}
    for label, weight in pairs:
        out[label] = out.get(label, 0.0) + weight / total
    return out


def build_hexes(
    estimates: Sequence[TractEstimate],
    weights: Mapping[str, TractCellWeights],
    supply: Mapping[str, HexSupply] | None = None,
    resolution: int = RESOLUTION_NATIONAL,
) -> tuple[list[HexCell], dict[str, float]]:
    """Aggregate the tract surface onto cells. Returns (cells, unallocated demand).

    Tracts with no population weights are returned separately rather than dropped, so
    the caller can report the gap instead of discovering a quiet shortfall later.
    """
    supply = supply or {}
    contributions: dict[str, list[tuple[TractEstimate, float]]] = {}
    unallocated: dict[str, float] = {}

    for row in estimates:
        entry = weights.get(row.geoid)
        if entry is None:
            unallocated[row.geoid] = row.estimate
            continue
        for cell, share in entry.weights.items():
            if share > 0.0:
                contributions.setdefault(cell, []).append((row, share))

    cells: list[HexCell] = []
    for cell, members in sorted(contributions.items()):
        demand = sum(row.estimate * share for row, share in members)
        population = sum(row.population * share for row, share in members)
        households = sum(row.households * share for row, share in members)
        equity = sum(row.equity_population * share for row, share in members)
        # Weight the qualitative fields by DEMAND where there is any, and by population
        # otherwise, so a cell with no EVs still reports whose evidence it rests on.
        basis = [(row, row.estimate * share) for row, share in members]
        if sum(w for _, w in basis) <= 0:
            basis = [(row, row.population * share) for row, share in members]
        if sum(w for _, w in basis) <= 0:
            basis = [(row, share) for row, share in members]
        total_basis = sum(w for _, w in basis)

        components = {
            name: sum(row.uncertainty_components[name] * w for row, w in basis)
            / total_basis
            for name in COMPONENT_NAMES
        }
        latitude, longitude = cell_centroid(cell)
        largest = max(w for _, w in basis) / total_basis if total_basis > 0 else 0.0
        cells.append(HexCell(
            h3_index=cell,
            resolution=resolution,
            latitude=latitude,
            longitude=longitude,
            area_km2=cell_area_km2(cell),
            demand_bev=demand,
            population=population,
            households=households,
            equity_population=equity,
            tracts_contributing=len(members),
            largest_tract_share=largest,
            uncertainty_score=sum(
                row.uncertainty_score * w for row, w in basis) / total_basis,
            uncertainty_components=components,
            evidence_grain_share=_weighted_shares(
                [(row.evidence_grain, w) for row, w in basis]),
            confidence_tier_share=_weighted_shares(
                [(row.confidence_tier, w) for row, w in basis]),
            value_provenance_share=_weighted_shares(
                [(row.value_provenance, w) for row, w in basis]),
            supply=supply.get(cell, HexSupply()),
        ))
    return cells, unallocated


def assert_demand_conserved(
    estimates: Sequence[TractEstimate], cells: Sequence[HexCell],
    unallocated: Mapping[str, float], tolerance: float = 1e-6,
) -> None:
    """Aggregation must not create or destroy demand."""
    before = sum(row.estimate for row in estimates)
    after = sum(cell.demand_bev for cell in cells) + sum(unallocated.values())
    if abs(before - after) > tolerance:
        raise HexAggregationError(
            f"hex aggregation lost demand: {before:,.6f} in, {after:,.6f} out "
            f"(difference {before - after:,.6f}). Allocation must conserve mass."
        )


def assert_provenance_survived(cells: Sequence[HexCell]) -> None:
    """Every cell must still say how well evidenced it is (D7, §11.1).

    A hex layer that reported demand alone would have thrown away the entire point of
    Phase 3's uncertainty and evidence-grain work.
    """
    for cell in cells:
        if not cell.evidence_grain_share:
            raise HexAggregationError(
                f"{cell.h3_index} carries no evidence-grain breakdown; demand without "
                "its provenance must never reach the siting layer"
            )
        if set(cell.uncertainty_components) != set(COMPONENT_NAMES):
            raise HexAggregationError(
                f"{cell.h3_index} is missing uncertainty components "
                f"{sorted(set(COMPONENT_NAMES) - set(cell.uncertainty_components))}"
            )
        for name, shares in (("evidence grain", cell.evidence_grain_share),
                             ("confidence tier", cell.confidence_tier_share),
                             ("value provenance", cell.value_provenance_share)):
            total = sum(shares.values())
            if abs(total - 1.0) > 1e-6:
                raise HexAggregationError(
                    f"{cell.h3_index}: {name} shares sum to {total}, not 1.0"
                )


def load_hex_supply(
    path: Path | None = None, resolution: int = RESOLUTION_NATIONAL,
    cluster_eps_m: float | None = None,
) -> dict[str, HexSupply]:
    """Existing public operational supply, placed on the grid by site coordinates.

    The filters are Phase 2's, imported rather than restated so the two cannot drift:
    operational status ``E`` only (domain rule G2), public access only (G3), and charging
    level read from the source's own ``charging_level`` field rather than inferred from a
    connector name (§7.1.2).

    **This is the only place supply enters siting, and it is a saturation filter, not a
    demand feature.** Directive D2 governs the demand model; where capacity already
    exists is exactly what a siting decision must know.
    """
    from pipeline.model.ablation import (
        DCFC_LEVEL,
        L2_LEVEL,
        OPERATIONAL_STATUS,
        PUBLIC_ACCESS,
        STATIONS_SNAPSHOT,
    )
    from pipeline.sources.catalog import local_json_source
    from pipeline.spatial.h3_grid import cells_for_points

    table = local_json_source("afdc_charging_units", path or STATIONS_SNAPSHOT).load()
    rows: list[tuple[float, float, str, float, str]] = []
    for row in table.rows:
        if row.get("station_status_code") != OPERATIONAL_STATUS:
            continue
        if row.get("station_access_code") != PUBLIC_ACCESS:
            continue
        try:
            latitude = float(row.get("station_latitude") or "")
            longitude = float(row.get("station_longitude") or "")
            ports = float(row.get("unit_port_count") or 0.0)
        except ValueError:
            continue
        rows.append((latitude, longitude, str(row.get("unit_charging_level") or ""),
                     ports, str(row.get("station_id"))))

    if not rows:
        return {}
    if cluster_eps_m is not None:
        rows = _assign_to_site_centroids(rows, cluster_eps_m)
    cells = cells_for_points([r[0] for r in rows], [r[1] for r in rows], resolution)
    dcfc: dict[str, float] = {}
    l2: dict[str, float] = {}
    stations: dict[str, set[str]] = {}
    for cell, (_lat, _lon, level, ports, station) in zip(cells, rows, strict=True):
        if level == DCFC_LEVEL:
            dcfc[cell] = dcfc.get(cell, 0.0) + ports
        elif level == L2_LEVEL:
            l2[cell] = l2.get(cell, 0.0) + ports
        stations.setdefault(cell, set()).add(station)
    return {
        cell: HexSupply(station_count=len(members),
                        dcfc_ports=dcfc.get(cell, 0.0),
                        l2_ports=l2.get(cell, 0.0))
        for cell, members in stations.items()
    }


def _assign_to_site_centroids(
    rows: Sequence[tuple[float, float, str, float, str]], eps_m: float
) -> list[tuple[float, float, str, float, str]]:
    """Move every station's ports to its DBSCAN site centroid.

    Used **only** by the A-2.1 sensitivity analysis, which asks whether clustering
    stations into sites and placing a whole site at one point could move ports across an
    H3 boundary and change a cell's saturation status. The shipped path does not cluster:
    each station sits at its own reported coordinates.
    """
    from pipeline.spatial.clustering import cluster_sites

    assignments = cluster_sites(
        [f"{index}" for index in range(len(rows))],
        [row[0] for row in rows], [row[1] for row in rows], eps_m=eps_m,
    )
    centroid = {a.station_id: (a.site_latitude, a.site_longitude) for a in assignments}
    moved: list[tuple[float, float, str, float, str]] = []
    for index, row in enumerate(rows):
        latitude, longitude = centroid.get(f"{index}", (row[0], row[1]))
        moved.append((latitude, longitude, row[2], row[3], row[4]))
    return moved
