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
from dataclasses import dataclass, field
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
    #: NON-OVERLAPPING generic service capacity in kW (§7.1.1), summed over the station's
    #: charging units from Phase 2's own power ladder. §10.2.4 requires capacity captured
    #: and not only station counts, because a station record is one network's presence at
    #: a site rather than a unit of capacity (G1).
    capacity_kw: float = 0.0


@dataclass(frozen=True)
class GainPoint:
    """One decile of a gain curve."""

    decile: float
    cells: int
    #: Share of subsequent deployments captured by the top `decile` of ranked cells.
    stations_captured: float
    ports_captured: float
    dcfc_ports_captured: float
    #: Share of subsequent non-overlapping generic service capacity, in kW (§7.1.1).
    capacity_kw_captured: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "decile": self.decile,
            "cells_in_decile_cumulative": self.cells,
            "share_of_subsequent_stations_captured": round(self.stations_captured, 6),
            "share_of_subsequent_ports_captured": round(self.ports_captured, 6),
            "share_of_subsequent_dcfc_ports_captured":
                round(self.dcfc_ports_captured, 6),
            "share_of_subsequent_capacity_kw_captured":
                round(self.capacity_kw_captured, 6),
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

    @property
    def top_decile_capacity_kw(self) -> float:
        return self.gain[0].capacity_kw_captured if self.gain else 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "ranking": self.name,
            "cells_ranked": self.cells_ranked,
            "top_decile_capture_stations": round(self.top_decile_stations, 6),
            "top_decile_capture_ports": round(self.top_decile_ports, 6),
            "top_decile_capture_capacity_kw": round(self.top_decile_capacity_kw, 6),
            "gain_curve": [p.to_dict() for p in self.gain],
        }


def score_ranking(
    name: str,
    ranking: Sequence[str],
    stations: Mapping[str, float],
    ports: Mapping[str, float],
    dcfc: Mapping[str, float],
    capacity_kw: Mapping[str, float] | None = None,
) -> RankingResult:
    """Build the full gain curve for one ranking.

    §10.2.4 requires **ports and capacity** captured, not only station counts, because a
    station record is a site of one network's presence and not a unit of capacity (G1).
    All four quantities are scored over the same ranking.
    """
    by_station = gain_curve(ranking, stations)
    by_ports = gain_curve(ranking, ports)
    by_dcfc = gain_curve(ranking, dcfc)
    by_capacity = gain_curve(ranking, capacity_kw or {})
    points = tuple(
        GainPoint(decile=d, cells=cells, stations_captured=s, ports_captured=p,
                  dcfc_ports_captured=f, capacity_kw_captured=k)
        for (d, cells, s), (_, _, p), (_, _, f), (_, _, k) in zip(
            by_station, by_ports, by_dcfc, by_capacity, strict=True)
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
    #: How the capture denominator and the ranked support were constructed, so a reader
    #: can check a lift figure rather than trust it.
    eligible_support: Mapping[str, object] = field(default_factory=dict)
    #: The random baseline's sampling noise (§ external review item 2).
    random_baseline_spread: Mapping[str, object] = field(default_factory=dict)
    deployment_capacity_kw: float = 0.0

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
            "subsequent_deployment_capacity_kw": round(self.deployment_capacity_kw, 2),
            "eligible_support": dict(self.eligible_support),
            "random_baseline_spread": dict(self.random_baseline_spread),
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


#: Draws behind the random baseline. ONE permutation is an unbiased but high-variance
#: estimate: deployment counts are heavily concentrated, so a single draw either does or
#: does not happen to land on the busy cells. Measured over 400 draws at the 2020 origin
#: the top-decile capture has mean 0.0976 and standard deviation 0.0137, and the
#: single-seed draw originally reported, 0.0687, sat at **percentile 0** - below the 5th
#: percentile of 0.0759. Reporting it as "the" random baseline overstated the model's
#: lift at that origin. The mean over many draws is still an EMPIRICAL random baseline,
#: not a theoretical value; it is simply a far less noisy one.
RANDOM_DRAWS = 200


@dataclass(frozen=True)
class RandomBaselineSpread:
    """How much a single random permutation could have varied.

    Published so a reader can see the estimator's noise rather than infer precision the
    single-draw number does not have.
    """

    draws: int
    mean: float
    standard_deviation: float
    p5: float
    p95: float
    single_seeded_draw: float
    single_draw_percentile: float

    def to_dict(self) -> dict[str, object]:
        return {
            "draws": self.draws,
            "top_decile_stations_mean": round(self.mean, 6),
            "top_decile_stations_sd": round(self.standard_deviation, 6),
            "top_decile_stations_p5": round(self.p5, 6),
            "top_decile_stations_p95": round(self.p95, 6),
            "single_seeded_draw": round(self.single_seeded_draw, 6),
            "single_seeded_draw_percentile_among_draws": round(
                self.single_draw_percentile, 4),
            "why_a_mean": (
                "one permutation is unbiased but high-variance, because deployment "
                "counts are heavily concentrated. The reported random baseline is the "
                "mean over these draws, which is still empirical - not a theoretical "
                "1/10th - and is what lift is computed against."
            ),
        }


def score_random_baseline(
    cells: Sequence[str],
    stations: Mapping[str, float],
    ports: Mapping[str, float],
    dcfc: Mapping[str, float],
    capacity_kw: Mapping[str, float],
    seed: int,
    draws: int = RANDOM_DRAWS,
) -> tuple[RankingResult, RandomBaselineSpread]:
    """The random baseline as a mean over many permutations, plus its spread.

    Each draw is scored on its own gain curve and the curves are averaged decile by
    decile, so the reported baseline is the expected capture of a random ranking rather
    than whatever one particular shuffle happened to do.
    """
    curves: list[RankingResult] = []
    tops: list[float] = []
    for offset in range(draws):
        ranking = random_ranking(cells, seed * 100003 + offset)
        result = score_ranking("random", ranking, stations, ports, dcfc, capacity_kw)
        curves.append(result)
        tops.append(result.top_decile_stations)

    averaged = tuple(
        GainPoint(
            decile=curves[0].gain[i].decile,
            cells=curves[0].gain[i].cells,
            stations_captured=float(np.mean([c.gain[i].stations_captured for c in curves])),
            ports_captured=float(np.mean([c.gain[i].ports_captured for c in curves])),
            dcfc_ports_captured=float(
                np.mean([c.gain[i].dcfc_ports_captured for c in curves])),
            capacity_kw_captured=float(
                np.mean([c.gain[i].capacity_kw_captured for c in curves])),
        )
        for i in range(len(curves[0].gain))
    )
    single = score_ranking("random", random_ranking(cells, seed), stations, ports, dcfc,
                           capacity_kw).top_decile_stations
    array = np.array(tops)
    spread = RandomBaselineSpread(
        draws=draws, mean=float(array.mean()), standard_deviation=float(array.std()),
        p5=float(np.percentile(array, 5)), p95=float(np.percentile(array, 95)),
        single_seeded_draw=single,
        single_draw_percentile=float((array < single).mean()))
    return RankingResult("random", len(cells), averaged), spread


def ranked_by(values: Mapping[str, float], cells: Sequence[str]) -> list[str]:
    """Descending by value, ties broken by cell id so the order is deterministic."""
    return sorted(cells, key=lambda c: (-values.get(c, 0.0), c))
