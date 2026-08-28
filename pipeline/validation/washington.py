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
from dataclasses import dataclass
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


# --- the transformation ladder ------------------------------------------------------
# CLAUDE.md §7.4 component 5 orders the geographic transformation penalty
#     native tract < ZIP -> tract < county -> tract < state-total-only
# and forbids hard-coding it: the penalty must be DERIVED FROM A MEASUREMENT of
# transformation quality. Washington is the only state whose vehicle rows carry a ZIP,
# a county and a tract together, so all three rungs can be measured by the same paired
# protocol, on the same vehicles, in one file.
#
# The ladder deliberately holds the DISTRIBUTION METHOD constant - household share from
# ACS - across all three rungs, so what it measures is the effect of the GRAIN rather
# than a mixture of grain and crosswalk. The ZIP rung is also measured with HUD
# res_ratio, because that is the method Phase 3 actually uses at that grain, and the
# uncertainty model takes its ZIP value from the method actually applied.

COUNTY_FIELD = "county"
STATE_FIELD = "state"
HOUSEHOLD_SHARE = "household_share"

GRAIN_ORDER: tuple[str, ...] = ("native_tract", "zip_anchored", "county_anchored",
                                "state_total_only")


def household_share_links(
    tract_households: Mapping[str, float], groups: Mapping[str, Sequence[str]]
) -> dict[str, dict[str, float]]:
    """Distribute each group's total across its tracts in proportion to households.

    A group whose tracts report no households at all gets an even split rather than a
    vector of zeros: the alternative would silently discard the group's observed total.
    """
    links: dict[str, dict[str, float]] = {}
    for group, tracts in groups.items():
        weights = {t: max(float(tract_households.get(t, 0.0)), 0.0) for t in tracts}
        total = sum(weights.values())
        if total > 0:
            links[group] = {t: w / total for t, w in weights.items()}
        elif tracts:
            links[group] = {t: 1.0 / len(tracts) for t in tracts}
    return links


def tract_groups(
    all_tracts: Sequence[str],
    grain: str,
    zip_crosswalk: Mapping[str, Mapping[str, float]] | None = None,
) -> dict[str, list[str]]:
    """Which tracts a coarse area is understood to contain, **before** seeing the data.

    This is the part that has to be got right for the ladder to mean anything. An
    earlier version derived each group's tract list from the paired records themselves,
    which hands the method perfect knowledge of which tracts actually hold vehicles -
    the hardest part of the problem - and flattered every rung. The membership now comes
    from geography alone:

    * **county** and **state** from the tract GEOID, since a tract GEOID *is* its state
      and county codes followed by the tract code, so the nesting is exact and complete;
    * **ZIP** from the HUD crosswalk, which is the mapping a deployment would actually
      have. Only tracts the crosswalk names are candidates, and a ZIP the crosswalk does
      not cover has no group at all.
    """
    if grain == "county_anchored":
        groups: dict[str, list[str]] = {}
        for tract in all_tracts:
            groups.setdefault(tract[:5], []).append(tract)
        return {k: sorted(v) for k, v in groups.items()}
    if grain == "state_total_only":
        return {WASHINGTON_FIPS: sorted(all_tracts)}
    if grain == "zip_anchored":
        if zip_crosswalk is None:
            raise ValueError("the ZIP rung needs the crosswalk a deployment would use")
        known = set(all_tracts)
        return {
            zip_code: sorted(t for t in weights if t in known)
            for zip_code, weights in zip_crosswalk.items()
            if any(t in known for t in weights)
        }
    raise ValueError(f"no tract grouping defined for grain {grain!r}")


@dataclass(frozen=True)
class LadderRung:
    """One rung of the geographic transformation ladder, measured not assumed."""

    grain: str
    method: str
    groups: int
    evs_placed: float
    statewide_tract_tvd: float
    unplaced_evs: float

    def to_dict(self) -> dict[str, object]:
        return {
            "grain": self.grain,
            "method": self.method,
            "groups": self.groups,
            "evs_placed": int(self.evs_placed),
            "unplaced_evs": int(self.unplaced_evs),
            "statewide_tract_tvd": round(self.statewide_tract_tvd, 6),
        }


def observed_tract_shares(
    records: Sequence[Mapping[str, object]], state_fips: str = WASHINGTON_FIPS
) -> tuple[dict[str, float], float]:
    """The observed statewide distribution of vehicles across tracts."""
    from pipeline.validation.allocation_error import TRACT_FIELD, normalise_digits

    counts: dict[str, float] = {}
    total = 0.0
    for record in records:
        tract = normalise_digits(record.get(TRACT_FIELD), 11)
        if tract and tract.startswith(state_fips):
            counts[tract] = counts.get(tract, 0.0) + 1.0
            total += 1.0
    if total <= 0:
        raise ValueError("no in-state records to build an observed distribution from")
    return {tract: n / total for tract, n in counts.items()}, total


def statewide_tvd(
    records: Sequence[Mapping[str, object]],
    links: Mapping[str, Mapping[str, float]],
    source_field: str,
    state_fips: str = WASHINGTON_FIPS,
) -> tuple[float, float, float]:
    """Statewide tract-level TVD for one transformation. Returns (tvd, placed, unplaced).

    **This is the metric the uncertainty model needs, and the within-group mean is not.**
    A within-group TVD averages many small separate problems and is not comparable
    across grains: a ZIP's residual error is spread over a few adjacent tracts while a
    state's is spread over every tract in the state, and the two numbers do not mean the
    same thing. Rebuilding the whole statewide tract vector from each transformation and
    comparing it against the observed one asks the question CLAUDE.md §7.4 component 5
    actually poses - how far is this tract value from directly observed evidence - and
    puts every rung on one scale.
    """
    from pipeline.validation.allocation_error import (
        TRACT_FIELD,
        normalise_digits,
        source_key,
    )

    observed, _ = observed_tract_shares(records, state_fips)
    group_totals: dict[str, float] = {}
    unplaced = 0.0
    for record in records:
        tract = normalise_digits(record.get(TRACT_FIELD), 11)
        if not (tract and tract.startswith(state_fips)):
            continue
        key = source_key(record, source_field)
        if key is None or key not in links:
            unplaced += 1.0
            continue
        group_totals[key] = group_totals.get(key, 0.0) + 1.0

    predicted: dict[str, float] = {}
    for key, total in group_totals.items():
        for tract, weight in links[key].items():
            predicted[tract] = predicted.get(tract, 0.0) + total * weight
    placed = sum(predicted.values())
    shares = ({tract: value / placed for tract, value in predicted.items()}
              if placed > 0 else {})
    tracts = set(observed) | set(shares)
    tvd = 0.5 * sum(abs(observed.get(t, 0.0) - shares.get(t, 0.0)) for t in tracts)
    return tvd, placed, unplaced


def measure_transformation_ladder(
    records_path: Path = DEFAULT_RECORDS,
    tract_households: Mapping[str, float] | None = None,
    hud_path: Path | None = DEFAULT_HUD,
) -> list[LadderRung]:
    """The measured geographic transformation penalty, rung by rung.

    CLAUDE.md §7.4 component 5 orders the rungs
    ``native tract < ZIP -> tract < county -> tract < state-total-only`` and states the
    ordering is "subject to empirical validation". This measures it rather than
    assuming it, and :func:`assert_ladder_ordering` checks the result against the
    specification's claim instead of quietly re-sorting.
    """
    records = json.loads(records_path.read_text(encoding="utf-8"))
    households = (tract_households if tract_households is not None
                  else _washington_tract_households())
    crosswalk = load_hud_links(hud_path) if hud_path else None
    all_tracts = sorted(households)

    rungs = [LadderRung("native_tract", "identity", len(all_tracts),
                        float(len(records)), 0.0, 0.0)]
    for grain, field in (("zip_anchored", "zip_code"),
                         ("county_anchored", COUNTY_FIELD),
                         ("state_total_only", STATE_FIELD)):
        if grain == "zip_anchored" and crosswalk is None:
            # Without the crosswalk a deployment would have, the ZIP rung cannot be
            # measured. It is omitted and says so, rather than being approximated by
            # some other grouping and reported as if it had been measured (D8).
            continue
        groups = _rekey(tract_groups(all_tracts, grain, crosswalk), grain)
        methods: dict[str, Mapping[str, Mapping[str, float]]] = {
            HOUSEHOLD_SHARE: household_share_links(households, groups)
        }
        if grain == "zip_anchored" and crosswalk is not None:
            # The method Phase 3 actually applies at this grain, restricted to the
            # tracts the crosswalk names. Ratios are never renormalised.
            methods[HUD_METHOD] = {
                zip_code: dict(weights) for zip_code, weights in crosswalk.items()
            }
        for method, links in methods.items():
            tvd, placed, unplaced = statewide_tvd(records, links, field)
            rungs.append(LadderRung(grain, method, len(links), placed, tvd, unplaced))
    return rungs


def assert_ladder_ordering(rungs: Sequence[LadderRung],
                           method: str = HOUSEHOLD_SHARE) -> None:
    """Check the measured ladder against the ordering CLAUDE.md §7.4 predicts.

    Raises with the measured values if the ordering does not hold. The specification
    calls the ordering "subject to empirical validation", so a violation is a **finding
    to report**, not something to fix by re-sorting the numbers.
    """
    by_grain = {r.grain: r.statewide_tract_tvd
                for r in rungs if r.method in (method, "identity")}
    ordered = [g for g in GRAIN_ORDER if g in by_grain]
    values = [by_grain[g] for g in ordered]
    if values != sorted(values):
        raise AssertionError(
            "the measured geographic transformation ladder does not respect the "
            "ordering CLAUDE.md §7.4 component 5 predicts: "
            + ", ".join(f"{g}={by_grain[g]:.4f}" for g in ordered)
        )


def run_grain_ladder(
    records_path: Path = DEFAULT_RECORDS,
    tract_households: Mapping[str, float] | None = None,
    hud_path: Path | None = DEFAULT_HUD,
) -> dict[str, AllocationErrorResult]:
    """Within-group paired comparison at each grain, kept as a secondary diagnostic.

    Reported alongside :func:`measure_transformation_ladder` but **not** used for the
    uncertainty component: a within-group mean is not comparable across grains. See
    :func:`statewide_tvd`.
    """
    records = json.loads(records_path.read_text(encoding="utf-8"))
    households = (tract_households if tract_households is not None
                  else _washington_tract_households())
    crosswalk = load_hud_links(hud_path) if hud_path else None
    all_tracts = sorted(households)
    out: dict[str, AllocationErrorResult] = {}
    for grain, field in (("zip_anchored", "zip_code"),
                         ("county_anchored", COUNTY_FIELD),
                         ("state_total_only", STATE_FIELD)):
        groups = tract_groups(all_tracts, grain, crosswalk)
        # The records name their county ("King") and state ("WA") in words, while a
        # tract GEOID names them in FIPS codes. Re-keying the groups to the words the
        # source actually uses is a rename; resolving it the other way would mean
        # rewriting the observed records, which is not this function's business.
        groups = _rekey(groups, grain)
        links = household_share_links(households, groups)
        # The whole-state rung is one group, so the minimum-EV rule that protects a
        # ZIP-level share vector from noise excludes nothing there. It is left in place
        # unchanged at every rung, for comparability.
        out[grain] = compare_methods(
            records, {HOUSEHOLD_SHARE: links}, state_fips=WASHINGTON_FIPS,
            source_field=field,
        )
    return out


def _rekey(groups: Mapping[str, Sequence[str]], grain: str) -> dict[str, list[str]]:
    """Match group keys to the vocabulary the observed records use."""
    if grain == "county_anchored":
        names = county_names_by_fips(WASHINGTON_FIPS)
        return {names[fips]: list(tracts) for fips, tracts in groups.items()
                if fips in names}
    if grain == "state_total_only":
        return {"WA": list(next(iter(groups.values())))}
    return {key: list(value) for key, value in groups.items()}


def county_names_by_fips(state_fips: str) -> dict[str, str]:
    """5-digit county FIPS -> the county name Washington's records use.

    Washington's vehicle rows carry a bare county name with no "County" suffix, so the
    Census reference name is trimmed to match. The join is still on FIPS underneath,
    which is what domain rule G13 requires: county names collide across states, and
    this mapping is only ever built within one state.
    """
    from pipeline.spatial.geography import county_fips_lookup

    out: dict[str, str] = {}
    for (_state, name), fips in county_fips_lookup().items():
        if fips.startswith(state_fips):
            out[fips] = name.removesuffix(" County").strip()
    return out


def _washington_tract_households() -> dict[str, float]:
    from pipeline.config.settings import PATHS as _PATHS
    from pipeline.discovery.cache import ReplayFetcher
    from pipeline.model.features import EXPOSURE_VARIABLE
    from pipeline.sources.census_acs import TRACT, AcsSource

    staged = AcsSource(TRACT, WASHINGTON_FIPS).load(ReplayFetcher(_PATHS.cache)).rows
    out: dict[str, float] = {}
    for row in staged:
        try:
            out[str(row["geoid"])] = float(row[EXPOSURE_VARIABLE] or 0.0)
        except ValueError:  # pragma: no cover - ACS households are never non-numeric
            out[str(row["geoid"])] = 0.0
    return out
