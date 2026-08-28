"""Driver for the Washington paired ZIP-to-tract allocation measurement.

Loads the two candidate crosswalks, scores them against Washington's observed paired
records through :mod:`pipeline.validation.allocation_error`, and writes a reproducible
evidence artifact. The measurement itself lives in the sibling module; this file is only
input assembly and serialisation, so the numbers can be re-derived from source rather
than trusted from a one-off script.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from pipeline.config.settings import PATHS
from pipeline.spatial.crosswalk import AllocationLink, load_zcta_tract_links
from pipeline.validation.allocation_error import (
    AllocationErrorResult,
    compare_methods,
    normalise_digits,
)

WASHINGTON_FIPS = "53"
HUD_METHOD = "hud_res_ratio"
LAND_AREA_METHOD = "land_area"

DEFAULT_RECORDS = PATHS.root / "data" / "cache" / "raw" / "wa_ev_population_full.json"
DEFAULT_HUD = PATHS.root / "data" / "cache" / "raw" / "hud_wa_zip_tract.json"
DEFAULT_OUT = PATHS.evidence / "P3-1_wa_allocation_scope_and_error.json"


def load_hud_links(path: Path) -> dict[str, dict[str, float]]:
    """HUD USPS ZIP Code Crosswalk records -> ZIP -> tract -> ``res_ratio``.

    ``res_ratio`` is the share of the ZIP's **residential** addresses falling in that
    tract. It is used exactly as published: a ZIP whose ratios sum to zero keeps its
    zero and is reported unallocatable rather than renormalised.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    links: dict[str, dict[str, float]] = {}
    for zip_code, rows in payload.items():
        key = normalise_digits(zip_code, 5)
        if key is None:
            continue
        weights: dict[str, float] = {}
        for row in rows:
            tract = normalise_digits(row.get("geoid"), 11)
            if tract is None:
                continue
            weights[tract] = weights.get(tract, 0.0) + float(row.get("res_ratio") or 0.0)
        links[key] = weights
    return links


def land_area_links_for(
    zips: Sequence[str],
    zcta_links: Mapping[str, Sequence[AllocationLink]] | None = None,
) -> dict[str, dict[str, float]]:
    """ZIP -> tract -> land-area weight, via the USPS ZIP → like-numbered ZCTA step.

    A ZIP with no like-numbered ZCTA gets no entry at all, which the ZIP-level rules
    then report as unallocatable by this method. That is the honest outcome: a point or
    PO-Box ZIP has no areal equivalent to allocate through.
    """
    table = zcta_links if zcta_links is not None else load_zcta_tract_links()
    out: dict[str, dict[str, float]] = {}
    for zip_code in zips:
        edges = table.get(zip_code)
        if not edges:
            continue
        out[zip_code] = {edge.tract_geoid: edge.weight for edge in edges}
    return out


def run(
    records_path: Path = DEFAULT_RECORDS,
    hud_path: Path = DEFAULT_HUD,
    zcta_links: Mapping[str, Sequence[AllocationLink]] | None = None,
) -> AllocationErrorResult:
    records = json.loads(records_path.read_text(encoding="utf-8"))
    hud = load_hud_links(hud_path)
    observed_zips = sorted(
        {
            z
            for z in (normalise_digits(r.get("zip_code"), 5) for r in records)
            if z is not None
        }
    )
    land_area = land_area_links_for(observed_zips, zcta_links)
    return compare_methods(
        records,
        {HUD_METHOD: hud, LAND_AREA_METHOD: land_area},
        state_fips=WASHINGTON_FIPS,
    )


def to_evidence(result: AllocationErrorResult) -> dict[str, object]:
    payload = result.to_dict()
    payload["investigation"] = (
        "Washington paired ZIP-to-tract allocation: scope reconciliation and measured "
        "allocation error"
    )
    payload["why_washington"] = (
        "Washington EV registration records carry both a postal ZIP Code and a 2020 "
        "census tract on the same observed vehicle row, so the observed ZIP-to-tract "
        "EV distribution is directly measurable. This is NOT national ground truth."
    )
    payload["decision_rule_preregistered_at"] = (
        "commit 66f1bfb, docs/evidence/L1-0_wa_decision_rule_preregistered.md"
    )
    payload["supersedes"] = (
        "docs/evidence/L1-1_washington_allocation_validation.json, which reported the "
        "same comparison but published only the included denominator (292,581) without "
        "accounting for the 1,612 excluded records by reason"
    )
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, default=DEFAULT_RECORDS)
    parser.add_argument("--hud", type=Path, default=DEFAULT_HUD)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    result = run(args.records, args.hud)
    args.out.write_text(
        json.dumps(to_evidence(result), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
