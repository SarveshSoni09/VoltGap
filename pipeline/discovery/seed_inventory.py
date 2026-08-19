"""Provenance and integrity inventory for the supplied seed files.

The raw seed filenames are preserved exactly as received (spaces and parentheses
included): raw-source immutability outranks shell convenience. This module is the
mapping layer between those raw names and clean canonical identifiers used
everywhere else in the pipeline.

Every supplied file is inventoried, including files excluded from version control
by .gitignore, so that a file whose bytes are not tracked remains verifiable.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from pipeline.config.settings import PATHS

# Raw filename -> (canonical_id, role/provenance).
# Provenance text is taken from data/seed/MANIFEST.md as delivered; Phase 0 verifies
# the claims against live sources and records findings in SOURCES.observed.json.
SEED_PROVENANCE: dict[str, tuple[str, str]] = {
    "alt_fuel_stations (Dec 11 2024).csv": (
        "seed_afdc_stations_national_20241211",
        "AFDC national alternative fuel stations snapshot, 11 Dec 2024, all rows "
        "Fuel Type Code = ELEC. Frozen regression fixture for domain rules G1-G4, "
        "G10, G11, G14.",
    ),
    "alt_fuel_stations (Dec 10 2024).csv": (
        "seed_afdc_stations_mn_20241210",
        "AFDC Minnesota-scoped extract, 10 Dec 2024, same 75-column schema as the "
        "national file. Two-state integration fixture.",
    ),
    "EV_Registration_Counts_by_State.csv": (
        "seed_state_ev_registrations",
        "State-level EV registration counts (stock, not sales, per G8). Contains a "
        "Total row that must be excluded before aggregation. Vintage undated as "
        "delivered; Phase 0 attempts to establish it.",
    ),
    "County_EV_Registrations_Summary.csv": (
        "seed_mn_county_ev_registrations",
        "Minnesota county EV registrations, single point in time. Tier A candidate "
        "evidence for Minnesota at county granularity.",
    ),
    "county_ev_counts.csv": (
        "seed_il_county_ev_monthly_panel",
        "Illinois monthly county panel, 2017-11 to 2024-11, wide format one column "
        "per county. Trailing columns Chicago / Unknown County / Total Count are not "
        "counties. Longitudinal basis for the Extension-tier forecast bakeoff.",
    ),
    "IL_StationsData.csv": (
        "seed_il_stations",
        "Illinois charging stations, reduced column set relative to the AFDC schema.",
    ),
    "Simplified_EV_Charging_Stations.csv": (
        "seed_mn_stations_simplified",
        "Minnesota charging stations, six columns. Overlaps the 10 Dec 2024 AFDC "
        "Minnesota extract.",
    ),
    "IEA Global EV Data 2024.csv": (
        "seed_iea_global_ev_2024",
        "IEA Global EV Data 2024. category has three values (Historical, "
        "Projection-STEPS, Projection-APS) which are alternative scenarios and must "
        "never be summed (G5). Projection years are 2025/2030/2035 only (G6).",
    ),
    "ev_launch_data.csv": (
        "seed_ev_model_launch",
        "EV model specifications with launch year. Currency fields are strings "
        "containing $ and thousands separators.",
    ),
    "Electric__Power_Transmission_Lines.geojson": (
        "seed_hifld_transmission_lines",
        "HIFLD electric power transmission lines, MultiLineString geometry with "
        "VOLTAGE / VOLT_CLASS / OWNER / STATUS properties. Excluded from version "
        "control by size; must never be loaded as GeoJSON in a browser (G12).",
    ),
}

CHUNK_BYTES = 1 << 20


@dataclass(frozen=True)
class SeedFile:
    """One supplied source file, identified by content rather than by name."""

    raw_filename: str
    canonical_id: str
    size_bytes: int
    sha256: str
    provenance: str
    version_controlled: bool


def sha256_of(path: Path, chunk_bytes: int = CHUNK_BYTES) -> str:
    """Streaming SHA-256 so a 137 MiB file never lands in memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_bytes)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def build_inventory(
    seed_dir: Path | None = None,
    ignored_filenames: frozenset[str] = frozenset(
        {"Electric__Power_Transmission_Lines.geojson"}
    ),
) -> list[SeedFile]:
    """Inventory every file in the seed directory, deterministically ordered by name.

    Files not present in SEED_PROVENANCE are still inventoried, with an
    ``unmapped_*`` canonical id, so an unexpected file cannot pass unnoticed.
    """
    directory = seed_dir if seed_dir is not None else PATHS.seed
    entries: list[SeedFile] = []
    for path in sorted(directory.iterdir(), key=lambda p: p.name):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.suffix.lower() in {".md", ".json"}:
            continue
        canonical_id, provenance = SEED_PROVENANCE.get(
            path.name,
            (f"unmapped_{path.stem}", "UNMAPPED: file present in data/seed/ but not "
                                      "declared in SEED_PROVENANCE."),
        )
        entries.append(
            SeedFile(
                raw_filename=path.name,
                canonical_id=canonical_id,
                size_bytes=path.stat().st_size,
                sha256=sha256_of(path),
                provenance=provenance,
                version_controlled=path.name not in ignored_filenames,
            )
        )
    return entries


def inventory_to_json(entries: list[SeedFile]) -> str:
    """Deterministic JSON: stable key order, stable entry order, trailing newline."""
    payload = {"seed_files": [asdict(entry) for entry in entries]}
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def inventory_to_markdown(entries: list[SeedFile]) -> str:
    """Human-readable inventory table."""
    lines = [
        "# Seed file inventory (provenance and integrity)",
        "",
        "Generated by `pipeline/discovery/seed_inventory.py`. Raw filenames are preserved",
        "exactly as delivered. `version_controlled = false` means the bytes are excluded",
        "by `.gitignore`; the SHA-256 below remains the record of what was received.",
        "",
        "| Canonical ID | Raw filename | Bytes | SHA-256 | In git | Provenance |",
        "|---|---|---:|---|---|---|",
    ]
    for entry in entries:
        lines.append(
            f"| `{entry.canonical_id}` | `{entry.raw_filename}` | {entry.size_bytes:,} | "
            f"`{entry.sha256}` | {'yes' if entry.version_controlled else 'no'} | "
            f"{entry.provenance} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_inventory(seed_dir: Path | None = None) -> list[SeedFile]:
    """Build the inventory and write both artifacts. Idempotent."""
    entries = build_inventory(seed_dir)
    PATHS.seed_inventory_json.write_text(inventory_to_json(entries), encoding="utf-8")
    PATHS.seed_inventory_md.write_text(inventory_to_markdown(entries), encoding="utf-8")
    return entries


def main() -> int:  # pragma: no cover - thin CLI wrapper, exercised via write_inventory
    entries = write_inventory()
    print(f"inventoried {len(entries)} seed files -> {PATHS.seed_inventory_json}")
    return 0
