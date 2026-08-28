# Limitations

What this project cannot do, and why. Written so a reader can tell the difference
between a limit of the data, a limit of the method, and a decision that is open to
revision.

---

## 1. Identity limits (Phase 1)

### No longitudinal charging-unit identity exists anywhere in this project

AFDC exposes **no charging-unit identifier** in either of its representations. `ID` is
the station parent key. Measured over the full national export:

```
CSV   292,435 rows, 65.9% byte-identical duplicates of another row
JSON  292,756 unit objects, 1,752 distinct, 99.4% redundant
      unit object keys: charging_level, connectors, funding_sources, network, port_count
      largest identical group: 69,100 objects
```

Rows cannot be told apart by their content; only row order separates them, and no
refresh guarantees row order. `charging_unit_record_key` is therefore **synthetic and
per-snapshot**, and no longitudinal physical-unit identity is claimed anywhere — not in
code, not in a schema comment, not in the UI. The canonical table carries
`key_is_synthetic = True` and `has_longitudinal_identity = False` on every row, and the
pandera schema asserts both as constants.

**Consequence.** No charger can be tracked across refreshes. "This unit was upgraded
from 50 kW to 150 kW" is not answerable from this source, and any future analysis
needing it must find another source rather than assume this one supports it.

**Not a consequence.** Aggregate counts and capacity are unaffected. Row count
reconciles to each station's reported L1+L2+DCFC total for **100.0% of stations**
(89,665 of 89,687), so the export is genuinely one row per EVSE and the duplicates are
real distinct physical units that happen to be indistinguishable in every reported
attribute — the same situation as domain rule G4 for coordinate duplicates.

### No physical port or connector identity

`ports` and `connectors` canonical tables are **not populated**. No stable port
identifier exists, and connector counts do not map unambiguously to ports: 16,610 units
report connector port counts exceeding their own `port_count`, meaning one physical port
exposes more than one connector standard. Connectors are modelled at
`(charging_unit_record_key, connector_type)` grain. No `port_001`-style rows are
manufactured anywhere.

### The five-level hierarchy has four levels in practice

`port_count` is **1 for all 292,756 units**: an AFDC charging unit *is* one port, and
there is no EVSE-cabinet grain in the source at all. The specification's
`site → station → charging_unit → port → connector` is implemented as
`site → station → charging_unit → (unit, connector_type)`.

---

## 2. Geographic allocation limits (Phase 1, measured in Phase 3)

### ZIP Codes are not areas

A USPS ZIP Code is a mail-delivery route collection; a Census ZCTA is an approximating
area. They are **not interchangeable**. Allocating a ZIP-keyed registration count to
tracts takes two declared steps — approximate identity from USPS ZIP to the
like-numbered ZCTA, then a weighted split from ZCTA to tract — and both are recorded on
every output row. ZIPs with no areal equivalent (point ZIPs, PO-Box-only ZIPs) are
returned as **unallocatable**, never dropped.

### Allocation weights are land area, which is the weakest defensible basis

```
ZCTAs with tract links              33,791
ZCTAs spanning more than one tract  25,770   (76.3%)
```

Land-area weighting assumes population is uniform within a ZCTA, which §7.6 says is
badly wrong in large rural areas. It is used because it is the only free,
unauthenticated national weight available, it is declared on every row as
`allocation_weight_basis`, and Phase 3 measures the resulting error via the Washington
round-trip (aggregate native tract data up to ZIP, allocate back down, measure) and may
replace it. Until that measurement exists, **the magnitude of this error is unknown**.

### No tract value from a ZIP or county source is directly observed

Only Washington publishes registrations at census-tract grain. Every other sub-state
source is ZIP or county. A tract estimate built from those is *anchored* to observed
data but is not itself observed, and carries `estimate_method = crosswalked` with
`evidence_grain` of `zip_anchored` or `county_anchored`. Tier A is labelled **sub-state
anchored**, never "observed".

---

## 3. Temporal provenance limits (Phase 1, A-0.5)

AFDC's `year=` registration pages are **stable but of unverified contemporaneity**.

```
vintage 2021, captured 2022-08-18 vs live 2026-08-24:  52/52 identical
vintage 2020, captured 2023-09-12 vs live 2026-08-24:  52/52 identical
earliest Internet Archive capture of the page:         2022-08-18
captures before 2022:                                  0
```

The series is not retrospectively revised within the observable window. But no capture
predates 2022-08-18, and that earliest capture already offered a full back-series to
2016, so the archive cannot show whether any given year page existed during that year.

**Consequence for the backtest.** The 2020 and 2021 rolling origins rest on a technical
vintage *label* whose information-availability semantics are unverified; the 2022 origin
is supported by an archived capture predating it. Phase 5's `docs/VALIDATION.md` must
state this. The D1 runtime guard `feature_vintage <= prediction_cutoff` is unaffected —
what is unverified is the meaning of the label, not the mechanics of the check.

---

## 4. Source availability limits (Phase 0)

| Source | Status | Consequence |
|---|---|---|
| National electric substations | **Not found.** Five searches failed; best candidate held 128 features against a national figure of 55,000–80,000 | National substation proximity is not a Core candidate filter. Core siting functions without it (amendment A6) |
| CEJST | Live host has no DNS record; retrieved from the Internet Archive | Archived historical equity classification only, vintage-labelled. EO 14008 was revoked on 20 January 2025 |
| NREL county home charging | A parametric scenario surface: 3,142 counties × 3 scenarios × 100 EV-share levels | Exploratory index only, excluded from the primary siting objective (amendment A7) |
| Census ACS API | Now requires a key | The keyless bulk summary file is the primary path |
| EIA API | Requires a key; no demo credential | Optional tier; keyless bulk workbook is the fallback |
| AFDC DEMO_KEY | Rate limited to 10 requests per window | A free personal key is required for repeated probing or scheduled refresh |
| Block-level population-weighted centroids | Do not exist. CenPop publishes county, tract and block group only | Genuine block-level weighting must be constructed from TIGER blocks + P.L. 94-171 |

Live HIFLD transmission holds **52,244** features against **94,216** in the delivered
seed GeoJSON. The two extracts do not agree and the publisher does not document why.

---

## 5. Method and tooling limits

### The copy lint is rule-based, and phase reports are allowlisted

It matches prohibited phrases; it does not understand paraphrase. Phase reports and
plan-change documents are allowlisted so they can quote a prohibition in order to
record that it is prohibited, which means a genuine optimality claim inside a report
would not be caught. Accepted because the places a false claim would actually ship —
UI strings, docstrings, published artifact fields — are **not** allowlisted.

### Determinism is semantic, not byte-level

Every derived table carries `computed_at`, so byte-identical checksums across
independent runs are impossible. Determinism means *same pinned snapshots + same code +
same configuration ⇒ same semantic output*, with volatile metadata normalised out. A
live refresh producing different artifacts is **not** a determinism failure.

### The Phase 1 gate builds a two-state fixture, not the nation

National Atlas retrieval is roughly 3.4 GB across 14 states. The gate proves the
pipeline works end to end, not that it scales to national volume. `make build` runs
nationally.

---

## 6. Hosting and cost limits

- **Cloudflare R2** free tier has no egress charge but does have Class A and Class B
  operation quotas. Zero cost is not guaranteed indefinitely at arbitrary traffic.
- **Vercel Hobby** is restricted to personal, non-commercial use. Appropriate for a
  portfolio project; noted so the restriction is not discovered later.
- **OpenFreeMap's** public instance requires no key and states no request limits, but
  it is a single point of failure. A self-hosted Protomaps basemap on R2 ships as the
  fallback.
- **GitHub scheduled workflows** on public repositories are automatically disabled
  after 60 days without repository activity. Hence `keepalive.yml` and, more
  importantly, a refresh health indicator in the UI.
- **CEJST via the Internet Archive** is a third-party dependency and a single point of
  failure. A local mirror should be taken before Phase 6.

## 7. Demand model limits (Phase 3)

- **No tract-native state validates the headline result.** Washington is the only source
  reporting registrations at census-tract grain, and it was used to *select* the ZIP→tract
  allocation method, so any Washington validation result is tuning-influenced. It is
  excluded from the independent leave-one-state-out aggregate and reported separately.
  The consequence is that **every independent validation figure is scored at ZIP or county
  grain**, and tract-level accuracy is not directly validated by an independent state.
- **Uncertainty calibration rests on one state, and is mixed.** Washington is the only
  place a tract-level error can be computed. Mean absolute error by uncertainty quintile
  is 54.04, 57.69, 50.96, 50.72, 74.92: the top quintile behaves as intended, the middle
  three are flat. The weights were fixed before fitting and have not been retuned in
  response.
- **The geographic transformation penalty is extrapolated from one state.** The measured
  ladder (`native_tract` 0.0000, `zip_anchored` 0.1621, `county_anchored` 0.2367,
  `state_total_only` 0.3049) comes entirely from Washington and is applied nationally.
- **Reconciliation constraints are rounded.** AFDC publishes state registration counts
  rounded to the nearest 100, so every reconciled tract estimate inherits a constraint
  precise to about ±50 vehicles per state.
- **Sub-state observations are not contemporaneous with one another.** State DMV snapshots
  span 2024-06 (North Carolina) to 2026-07 (New Mexico). Each state is reconciled to the
  AFDC vintage nearest its own snapshot, which contains the problem but does not remove it.
- **The target is battery-electric vehicles only.** Plug-in hybrids are counted separately
  and never added in, because the AFDC state series that supplies every constraint counts
  BEVs only.
- **Vehicles registered to out-of-state mailing ZIPs cannot be placed sub-state.** They are
  real, they belong in the state total, and they are excluded from the panel by name with
  their counts recorded — 6,922 in New York, 5,040 in North Carolina, 1,316 in Connecticut,
  1,253 in Oregon.
- **Texas loses 15,405 BEV (3.9% of its observed total) to ZIPs with no like-numbered
  ZCTA**, which are typically point or PO-Box ZIPs with no areal equivalent.
- **Urban/rural is a continuous proxy, not a classification.** CLAUDE.md §7.3 names
  urban/rural among the primary features; Phase 3 represents it by logged population
  density because no keyless tract-level Census classification was retrieved.
- **New Jersey's observed total is 21.65% below the AFDC figure at the same vintage** and
  is flagged for review rather than marked low-confidence, per corrected domain rule G9.
