"""The supply-feature ablation: the ONE place Phase 2 supply outputs may enter a model.

Directive D2 forbids charger counts, port counts, charger density, network presence and
distance-to-charger from the **primary** demand model, because existing infrastructure
is an outcome of prior investment decisions: predicting demand from it and then siting
from that demand launders historical deployment patterns into "need" and suppresses
exactly the underserved areas the project exists to find. CLAUDE.md §7.3 permits them in
one place only - an explicitly labelled ablation, logged and reported separately - and
§15.5 makes running it a Phase 3 acceptance criterion.

**This module is not part of the published surface and must never become one.** Nothing
here feeds ``pipeline.model.build_demand``. Its output is a comparison, published under
its own heading, whose purpose is to show *how much* fit supply features buy - because
CLAUDE.md §18 anti-pattern 5 is precisely that they buy a lot, and a number is a better
argument for the prohibition than a paragraph.

**Scope: the ZIP-grain states only.** AFDC station records carry a postal ZIP, so supply
aggregates to that geography directly from the source. They carry no county, and
deriving one would need a spatial join whose error would be mixed into the comparison.
Restricting the ablation to the eleven ZIP-grain states keeps it a clean like-for-like
against the same states' primary result.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from pipeline.config.settings import PATHS
from pipeline.model.demand import ModelRow
from pipeline.model.features import FEATURE_NAMES
from pipeline.model.panel import StatePanel
from pipeline.sources.catalog import local_json_source
from pipeline.spatial.geography import GeographyError, SourceGeography, normalise_zip

STATIONS_SNAPSHOT = PATHS.root / "data" / "cache" / "raw" / "afdc_stations_national.json"

#: Phase 2's public-operational filter, restated here rather than imported so the
#: ablation cannot drift from what it claims to be measuring. G2: operational supply is
#: status code E only. G3: private stations are not public supply.
OPERATIONAL_STATUS = "E"
PUBLIC_ACCESS = "public"

#: Charging level comes from the source's own field, never from a connector name
#: (CLAUDE.md §7.1.2). NEMA types are connector standards, not level designations.
DCFC_LEVEL = "dc_fast"
L2_LEVEL = "2"

SUPPLY_FEATURE_NAMES: tuple[str, ...] = (
    "dcfc_ports_per_1k_households",
    "l2_ports_per_1k_households",
    "public_stations_per_1k_households",
)

ABLATION_FEATURE_NAMES: tuple[str, ...] = (*FEATURE_NAMES, *SUPPLY_FEATURE_NAMES)


@dataclass(frozen=True)
class SupplyByZip:
    """Public operational supply, aggregated to the postal ZIP the source reports."""

    dcfc_ports: Mapping[str, float]
    l2_ports: Mapping[str, float]
    stations: Mapping[str, float]

    def features_for(self, zip_code: str, households: float) -> dict[str, float]:
        per_1k = 1000.0 / households if households > 0 else 0.0
        return {
            "dcfc_ports_per_1k_households": self.dcfc_ports.get(zip_code, 0.0) * per_1k,
            "l2_ports_per_1k_households": self.l2_ports.get(zip_code, 0.0) * per_1k,
            "public_stations_per_1k_households": (
                self.stations.get(zip_code, 0.0) * per_1k
            ),
        }


def load_supply_by_zip(path: Path | None = None) -> SupplyByZip:
    """Aggregate public operational charging supply to ZIP from the AFDC snapshot."""
    source = path or STATIONS_SNAPSHOT
    table = local_json_source("afdc_charging_units", source).load()
    dcfc: dict[str, float] = {}
    l2: dict[str, float] = {}
    stations: dict[str, float] = {}
    seen: set[tuple[str, str]] = set()
    for row in table.rows:
        if row.get("station_status_code") != OPERATIONAL_STATUS:
            continue
        if row.get("station_access_code") != PUBLIC_ACCESS:
            continue
        try:
            zip_code = normalise_zip(row.get("station_zip", ""))
        except GeographyError:
            continue
        try:
            ports = float(row.get("unit_port_count") or 0.0)
        except ValueError:  # pragma: no cover - port_count is always numeric
            ports = 0.0
        level = row.get("unit_charging_level", "")
        if level == DCFC_LEVEL:
            dcfc[zip_code] = dcfc.get(zip_code, 0.0) + ports
        elif level == L2_LEVEL:
            l2[zip_code] = l2.get(zip_code, 0.0) + ports
        key = (zip_code, str(row.get("station_id")))
        if key not in seen:
            seen.add(key)
            stations[zip_code] = stations.get(zip_code, 0.0) + 1.0
    return SupplyByZip(dcfc, l2, stations)


def with_supply_features(
    panel: StatePanel, supply: SupplyByZip
) -> StatePanel:
    """A copy of a ZIP-grain panel whose rows also carry supply features.

    **Labelled at the point of use.** The returned panel's rows are only ever passed to
    an estimator fitted over :data:`ABLATION_FEATURE_NAMES`, and the caller reports the
    result under its own heading.
    """
    if panel.source_geography is not SourceGeography.USPS_ZIP:
        raise ValueError(
            f"{panel.state}: the supply ablation covers ZIP-grain states only, because "
            "AFDC station records carry a postal ZIP and no county"
        )
    rows = tuple(
        ModelRow(
            state=row.state, geography=row.geography, geoid=row.geoid,
            households=row.households, population=row.population,
            features={**row.features,
                      **supply.features_for(row.geoid, row.households)},
            observed_bev=row.observed_bev,
        )
        for row in panel.rows
    )
    return StatePanel(
        state=panel.state, source_geography=panel.source_geography,
        vintage_label=panel.vintage_label, rows=rows, ledger=panel.ledger,
        is_independent=panel.is_independent,
    )


def zip_grain_panels(
    panels: Mapping[str, StatePanel], supply: SupplyByZip
) -> tuple[dict[str, StatePanel], dict[str, StatePanel]]:
    """(primary, ablation) panel sets over the same ZIP-grain states."""
    primary = {
        state: panel for state, panel in panels.items()
        if panel.source_geography is SourceGeography.USPS_ZIP and panel.is_independent
    }
    return primary, {state: with_supply_features(panel, supply)
                     for state, panel in primary.items()}


def assert_supply_features_are_absent(names: Sequence[str] = FEATURE_NAMES) -> None:
    """The primary feature set must never contain a supply feature. Enforced by test."""
    intruders = sorted(set(names) & set(SUPPLY_FEATURE_NAMES))
    if intruders:
        raise ValueError(
            f"D2 violation: supply feature(s) {intruders} reached the primary demand "
            "feature set. They belong only in this labelled ablation."
        )
