"""Historical deployment alignment: a vintage-enforced rolling-origin backtest.

**What this measures.** Whether the model assigned higher priority to locations where
charging infrastructure was *subsequently* deployed.

**What it does not measure, and no code, chart, docstring or report copy may imply.**
CLAUDE.md §10.2 is explicit and D3 forbids blurring the three validation terms:

* it does **not** establish that historical deployments were optimal;
* it does **not** establish that the model identifies causally correct siting decisions;
* it does **not** establish that operators should have followed the model;
* it does **not** validate any future selected site as optimal.

Charge point operators build on real-estate availability, grant programmes, utility
relationships, commercial strategy, highway contracts and network expansion plans. **High
alignment may mean the model reproduces industry behaviour including its biases** — which
is the opposite of a good result for a system whose stated purpose is to find underserved
areas. §18 anti-pattern 2. The number is reported with that caveat every time it appears.

**The target is an approximate reconstruction** (G10, G11). Stations that closed, left the
feed, or changed port counts are invisible in a current snapshot, and `Open Date` is
imprecise and for automated network feeds may record first appearance in the Station
Locator rather than actual opening. Survivorship bias grows with age, so the 2020 origin is
the least trustworthy of the three.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np

#: The deciles §10.2.4 requires a gain curve across.
DECILES = tuple(round(0.1 * i, 1) for i in range(1, 11))


@dataclass(frozen=True)
class Deployment:
    """One station that opened inside an evaluation window."""

    station_id: str
    cell: str
    opened: date
    ports: float
    dcfc_ports: float
    #: USPS state code from the AFDC record. Carried because geographic coverage is a
    #: required Phase 5 report field and an H3 index does not encode a jurisdiction.
    state: str = ""


@dataclass(frozen=True)
class GainPoint:
    """One decile of a gain curve."""

    decile: float
    cells: int
    #: Share of subsequent deployments captured by the top `decile` of ranked cells.
    stations_captured: float
    ports_captured: float
    dcfc_ports_captured: float

    def to_dict(self) -> dict[str, object]:
        return {
            "decile": self.decile,
            "cells_in_decile_cumulative": self.cells,
            "share_of_subsequent_stations_captured": round(self.stations_captured, 6),
            "share_of_subsequent_ports_captured": round(self.ports_captured, 6),
            "share_of_subsequent_dcfc_ports_captured":
                round(self.dcfc_ports_captured, 6),
        }


def gain_curve(
    ranking: Sequence[str],
    weight_by_cell: Mapping[str, float],
    deciles: Sequence[float] = DECILES,
) -> list[tuple[float, int, float]]:
    """Cumulative share of `weight_by_cell` captured by the top decile of `ranking`.

    Returns (decile, cells, captured_share). A cell absent from the ranking captures
    nothing: it was not a candidate, so a deployment there is a miss, not an exclusion.
    """
    total = sum(weight_by_cell.values())
    if total <= 0:
        return [(d, round(d * len(ranking)), 0.0) for d in deciles]
    out = []
    for d in deciles:
        take = round(d * len(ranking))
        captured = sum(weight_by_cell.get(c, 0.0) for c in ranking[:take])
        out.append((d, take, captured / total))
    return out


@dataclass(frozen=True)
class RankingResult:
    """One ranking (the model, or a baseline) scored against one origin's window."""

    name: str
    cells_ranked: int
    gain: tuple[GainPoint, ...]

    @property
    def top_decile_stations(self) -> float:
        return self.gain[0].stations_captured if self.gain else 0.0

    @property
    def top_decile_ports(self) -> float:
        return self.gain[0].ports_captured if self.gain else 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "ranking": self.name,
            "cells_ranked": self.cells_ranked,
            "top_decile_capture_stations": round(self.top_decile_stations, 6),
            "top_decile_capture_ports": round(self.top_decile_ports, 6),
            "gain_curve": [p.to_dict() for p in self.gain],
        }


def score_ranking(
    name: str,
    ranking: Sequence[str],
    stations: Mapping[str, float],
    ports: Mapping[str, float],
    dcfc: Mapping[str, float],
) -> RankingResult:
    """Build the full gain curve for one ranking.

    §10.2.4 requires ports and capacity captured, not only station counts, because a
    station record is a site of one network's presence and not a unit of capacity (G1).
    """
    by_station = gain_curve(ranking, stations)
    by_ports = gain_curve(ranking, ports)
    by_dcfc = gain_curve(ranking, dcfc)
    points = tuple(
        GainPoint(decile=d, cells=cells, stations_captured=s,
                  ports_captured=p, dcfc_ports_captured=f)
        for (d, cells, s), (_, _, p), (_, _, f) in zip(
            by_station, by_ports, by_dcfc, strict=True)
    )
    return RankingResult(name=name, cells_ranked=len(ranking), gain=points)


@dataclass(frozen=True)
class OriginAlignment:
    """One rolling origin, fully scored, with every baseline alongside the model."""

    origin: str
    cutoff: date
    window_end: date
    cells_evaluated: int
    deployments: int
    deployment_ports: float
    deployment_dcfc_ports: float
    states_covered: int
    model: RankingResult
    baselines: tuple[RankingResult, ...]
    reconstruction_confidence: str
    vintages: Mapping[str, object]

    def lift(self, baseline: str, metric: str = "stations") -> float:
        """Model top-decile capture divided by a baseline's. 1.0 means no advantage."""
        other = next(b for b in self.baselines if b.name == baseline)
        mine = (self.model.top_decile_stations if metric == "stations"
                else self.model.top_decile_ports)
        theirs = (other.top_decile_stations if metric == "stations"
                  else other.top_decile_ports)
        if theirs <= 0:
            return float("inf") if mine > 0 else 1.0
        return mine / theirs

    def to_dict(self) -> dict[str, object]:
        return {
            "origin": self.origin,
            "prediction_cutoff": self.cutoff.isoformat(),
            "evaluation_window_end": self.window_end.isoformat(),
            "cells_evaluated": self.cells_evaluated,
            "subsequent_deployments_available": self.deployments,
            "subsequent_deployment_ports": round(self.deployment_ports, 2),
            "subsequent_deployment_dcfc_ports": round(self.deployment_dcfc_ports, 2),
            "geographic_coverage_states": self.states_covered,
            "reconstruction_confidence": self.reconstruction_confidence,
            "vintages_used": dict(self.vintages),
            "model": self.model.to_dict(),
            "baselines": [b.to_dict() for b in self.baselines],
            "lift_vs_random_stations": round(self.lift("random"), 6),
            "lift_vs_population_stations": round(self.lift("population"), 6),
            "lift_vs_random_ports": round(self.lift("random", "ports"), 6),
            "lift_vs_population_ports": round(self.lift("population", "ports"), 6),
            "what_this_measures": (
                "whether the model assigned higher priority to locations where charging "
                "infrastructure was subsequently deployed"),
            "what_this_does_not_measure": [
                "that historical deployments were optimal",
                "that the model identifies causally correct siting decisions",
                "that operators should have followed the model",
                "that any future selected site is validated as optimal",
                "high alignment may mean the model reproduces industry deployment "
                "behaviour including its biases",
            ],
        }


def random_ranking(cells: Sequence[str], seed: int) -> list[str]:
    """A seeded shuffle. Seeded so the baseline is reproducible, not so it is flattering:
    the seed is fixed from the origin year before any result is seen."""
    generator = np.random.default_rng(seed)
    order = generator.permutation(len(cells))
    return [cells[i] for i in order]


def ranked_by(values: Mapping[str, float], cells: Sequence[str]) -> list[str]:
    """Descending by value, ties broken by cell id so the order is deterministic."""
    return sorted(cells, key=lambda c: (-values.get(c, 0.0), c))
