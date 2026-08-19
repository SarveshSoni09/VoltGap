"""The source contract (stable, human-reviewed) and its observation sidecar (generated).

CLAUDE.md 4.1 originally specified a single ``SOURCES.yml`` holding both the contract
and the live measurements. That was split by an approved deviation: every live refresh
would otherwise dirty the human-reviewed file and make expectation indistinguishable
from observation.

* ``SOURCES.yml`` — stable contract. Hand-reviewed. Changes only by deliberate edit.
* ``SOURCES.observed.json`` — generated. Row counts, discovered schema, missingness,
  retrieval metadata, and the probe-assigned status.

``SOURCES.yml`` also carries a ``findings`` block: the Phase 0 research conclusions
that no test can prove true, each required to carry a resolved value, an evidence URL,
a retrieval timestamp, a supporting quote, and the SHA-256 of a cached evidence
artifact so the claim stays auditable if the page later changes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# Every contract entry must populate all of these. A source missing any one of them
# cannot be used by a Core model; the Phase 0 gate asserts this over every entry.
REQUIRED_CONTRACT_FIELDS: tuple[str, ...] = (
    "id",
    "name",
    "tier",
    "retrieval",
    "coverage",
    "schema",
    "quality",
    "license",
    "update_cadence",
    "fallback_source",
    "used_by",
    "backtest_eligible",
    "known_limitations",
)
REQUIRED_RETRIEVAL_FIELDS: tuple[str, ...] = ("method", "endpoint", "auth", "rate_limit")
REQUIRED_COVERAGE_FIELDS: tuple[str, ...] = (
    "geographic",
    "temporal",
    "historical_vintages_available",
    "vintage_field",
    "vintage_semantics",
)
REQUIRED_SCHEMA_FIELDS: tuple[str, ...] = ("join_keys", "stable_keys", "schema_version")
REQUIRED_QUALITY_FIELDS: tuple[str, ...] = (
    "expected_row_count",
    "drift_tolerance",
    "expected_range_derivation",
)
REQUIRED_FINDING_FIELDS: tuple[str, ...] = (
    "question",
    "resolved_value",
    "evidence_url",
    "retrieved_at",
    "evidence_quote",
    "evidence_artifact",
    "evidence_sha256",
)

VALID_TIERS: frozenset[str] = frozenset({"core", "extension", "optional"})
VALID_STATUSES: frozenset[str] = frozenset({"confirmed", "degraded", "unavailable", "gated"})


class ContractError(ValueError):
    """Raised when SOURCES.yml is incomplete. Blocks the Phase 0 gate."""


@dataclass(frozen=True)
class Observation:
    """One probe result. Written to SOURCES.observed.json, never to SOURCES.yml."""

    source_id: str
    status: str
    url: str
    http_status: int | None
    retrieved_at: str
    elapsed_ms: float | None
    content_bytes: int | None
    content_sha256: str | None
    measurement: dict[str, Any] | None
    rate_limit_headers: dict[str, str]
    vintage: str | None
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "status": self.status,
            "url": self.url,
            "http_status": self.http_status,
            "retrieved_at": self.retrieved_at,
            "elapsed_ms": self.elapsed_ms,
            "content_bytes": self.content_bytes,
            "content_sha256": self.content_sha256,
            "measurement": self.measurement,
            "rate_limit_headers": self.rate_limit_headers,
            "vintage": self.vintage,
            "note": self.note,
        }


@dataclass(frozen=True)
class Drift:
    """Comparison of one observation against its contract expectation."""

    source_id: str
    within_expected_row_count: bool | None
    observed_row_count: int | None
    expected_row_count: list[int] | None
    tolerance_band: list[int] | None
    schema_hash_changed: bool | None
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "within_expected_row_count": self.within_expected_row_count,
            "observed_row_count": self.observed_row_count,
            "expected_row_count": self.expected_row_count,
            "tolerance_band": self.tolerance_band,
            "schema_hash_changed": self.schema_hash_changed,
            "note": self.note,
        }


def load_contract(path: Path) -> dict[str, Any]:
    """Read SOURCES.yml. Returns the whole document (``sources`` and ``findings``)."""
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ContractError(f"{path} did not parse to a mapping")
    return document


def _missing(entry: dict[str, Any], required: tuple[str, ...]) -> list[str]:
    return [name for name in required if entry.get(name) is None]


def validate_contract(document: dict[str, Any]) -> None:
    """Raise ContractError listing every incomplete entry. The Phase 0 gate calls this.

    Checked: all top-level contract fields present and non-null; all required
    sub-fields of retrieval/coverage/schema/quality present; tier in the allowed set;
    expected_row_count a two-element ascending pair; backtest_eligible consistent with
    coverage.historical_vintages_available; every finding fully evidenced.
    """
    problems: list[str] = []
    sources = document.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ContractError("SOURCES.yml has no 'sources' list")

    seen: set[str] = set()
    for index, entry in enumerate(sources):
        label = entry.get("id", f"<entry {index}>")
        if label in seen:
            problems.append(f"{label}: duplicate source id")
        seen.add(label)
        for name in _missing(entry, REQUIRED_CONTRACT_FIELDS):
            problems.append(f"{label}: missing required field '{name}'")
        if entry.get("tier") not in VALID_TIERS and entry.get("tier") is not None:
            problems.append(f"{label}: tier '{entry['tier']}' not in {sorted(VALID_TIERS)}")
        for group, required in (
            ("retrieval", REQUIRED_RETRIEVAL_FIELDS),
            ("coverage", REQUIRED_COVERAGE_FIELDS),
            ("schema", REQUIRED_SCHEMA_FIELDS),
            ("quality", REQUIRED_QUALITY_FIELDS),
        ):
            block = entry.get(group)
            if not isinstance(block, dict):
                continue
            for name in required:
                if name not in block:
                    problems.append(f"{label}: {group}.{name} is absent")
        quality = entry.get("quality")
        if isinstance(quality, dict):
            expected = quality.get("expected_row_count")
            if expected is not None:
                if not (isinstance(expected, list) and len(expected) == 2):
                    problems.append(f"{label}: quality.expected_row_count must be [lo, hi]")
                elif expected[0] > expected[1]:
                    problems.append(f"{label}: quality.expected_row_count is descending")
        coverage = entry.get("coverage")
        if (
            isinstance(coverage, dict)
            and entry.get("backtest_eligible") is True
            and coverage.get("historical_vintages_available") is not True
        ):
            problems.append(
                f"{label}: backtest_eligible is true but "
                "coverage.historical_vintages_available is not true"
            )

    findings = document.get("findings")
    if not isinstance(findings, list) or not findings:
        problems.append("SOURCES.yml has no 'findings' list")
    else:
        for finding in findings:
            label = finding.get("id", "<finding>")
            for name in _missing(finding, REQUIRED_FINDING_FIELDS):
                problems.append(f"finding {label}: missing required field '{name}'")

    if problems:
        raise ContractError("SOURCES.yml is incomplete:\n  - " + "\n  - ".join(problems))


def tolerance_band(expected: list[int], tolerance: float) -> list[int]:
    """Widen an expected [lo, hi] range by the source's drift tolerance."""
    low, high = expected
    return [int(low * (1.0 - tolerance)), int(high * (1.0 + tolerance))]


def evaluate_drift(entry: dict[str, Any], observation: Observation) -> Drift:
    """Compare one observation against its contract expectation.

    Returns ``within_expected_row_count = None`` when the source produced no row count
    (an unavailable source, or a binary artifact), rather than guessing.
    """
    quality = entry.get("quality") or {}
    expected = quality.get("expected_row_count")
    tolerance = quality.get("drift_tolerance")
    measurement = observation.measurement
    observed = measurement.get("row_count") if measurement else None

    within: bool | None = None
    band: list[int] | None = None
    if expected is not None and observed is not None and tolerance is not None:
        band = tolerance_band(list(expected), float(tolerance))
        within = band[0] <= observed <= band[1]

    expected_hash = (entry.get("schema") or {}).get("schema_version")
    observed_hash = measurement.get("schema_hash") if measurement else None
    changed: bool | None = None
    if expected_hash is not None and observed_hash is not None:
        changed = expected_hash != observed_hash

    note = "not evaluated: no row count observed" if within is None else (
        "within tolerance" if within else "OUTSIDE tolerance band"
    )
    return Drift(
        source_id=observation.source_id,
        within_expected_row_count=within,
        observed_row_count=observed,
        expected_row_count=list(expected) if expected is not None else None,
        tolerance_band=band,
        schema_hash_changed=changed,
        note=note,
    )


def observations_document(
    observations: list[Observation], drifts: list[Drift], generator: str
) -> dict[str, Any]:
    """Assemble the generated sidecar. Entry order follows source id, so diffs are stable."""
    return {
        "generated_by": generator,
        "schema_note": (
            "Generated file. Volatile measurements only. The stable, human-reviewed "
            "contract is SOURCES.yml. Do not hand-edit this file."
        ),
        "observations": [o.to_dict() for o in sorted(observations, key=lambda o: o.source_id)],
        "drift": [d.to_dict() for d in sorted(drifts, key=lambda d: d.source_id)],
    }


def write_observations(path: Path, document: dict[str, Any]) -> None:
    """Write the sidecar deterministically: sorted keys, 2-space indent, trailing newline."""
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
