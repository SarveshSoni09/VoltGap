"""`manifest.json`: what the frontend reads first.

§12 requires per-artifact checksums, row counts, `computed_at`, and the full
`source_vintages` map, and §13.3 requires the UI to render a refresh-health indicator from
`computed_at`. Both are served from here.

**Staleness is a published number, not a UI opinion.** The manifest carries the threshold
in days alongside the timestamp, so the page and any other consumer agree on when the data
is stale rather than each applying its own rule.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pipeline.export.parquet import WrittenArtifact

#: §13.3. GitHub disables scheduled workflows on public repositories after 60 days without
#: repository activity, so data older than this is plausibly a dead refresh rather than a
#: quiet week. The UI says so plainly rather than showing a stale number as if it were live.
STALE_AFTER_DAYS = 14


@dataclass(frozen=True)
class Manifest:
    """The index the static frontend loads before anything else."""

    computed_at: str
    artifacts: tuple[WrittenArtifact, ...]
    source_vintages: Mapping[str, str]
    pipeline_phases: Mapping[str, str]
    notes: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "computed_at": self.computed_at,
            "stale_after_days": STALE_AFTER_DAYS,
            "artifacts": {a.name: a.to_dict() for a in
                          sorted(self.artifacts, key=lambda x: x.name)},
            "source_vintages": dict(sorted(self.source_vintages.items())),
            "pipeline_phases": dict(sorted(self.pipeline_phases.items())),
            "notes": dict(self.notes),
        }

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=False) + "\n",
                        encoding="utf-8")
        return path


def build_manifest(
    artifacts: Sequence[WrittenArtifact],
    source_vintages: Mapping[str, str],
    pipeline_phases: Mapping[str, str],
    notes: Mapping[str, Any],
    computed_at: str | None = None,
) -> Manifest:
    """Assemble the manifest. `computed_at` is injectable so replay runs are comparable."""
    return Manifest(
        computed_at=computed_at or datetime.now(UTC).isoformat(),
        artifacts=tuple(artifacts),
        source_vintages=dict(source_vintages),
        pipeline_phases=dict(pipeline_phases),
        notes=dict(notes),
    )
