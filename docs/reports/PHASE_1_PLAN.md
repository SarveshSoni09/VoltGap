# Phase 1 plan — Ingestion + canonical model

| Field | Value |
|---|---|
| Phase | 1 — Ingestion + canonical |
| Planned effort | 2.25 part-time weeks (of 13.5 Core weeks remaining) |
| Status | **AWAITING APPROVAL — no Phase 1 code written** |
| Prerequisite | `CLAUDE.md` amendments A0–A12 applied (§19); `PLAN_CHANGE_0.md` resolved |
| Phase 0 gate | Re-run after amendments: **PASS**, no artifact invalidated |

Phase 1's job is ingestion, canonical entities, schemas, transformation contracts,
reproducibility, and source/domain-rule enforcement. **No model fitting.** No propensity
model, no reconciliation, no siting, no uncertainty scoring.

---

## 1. Modules and files to be created

### 1.1 Source adapters — `pipeline/sources/`

| File | Purpose |
|---|---|
| `base.py` | `Source` ABC over the Phase 0 fetcher: caching, retry, vintage stamping, `--offline` replay. Reuses `pipeline/discovery/cache.py` rather than reimplementing it |
| `afdc_stations.py` | 75-column station records, schema `f6860736f1304654` |
| `afdc_charging_units.py` | 86-column unit records including the ten per-connector columns |
| `afdc_state_registrations.py` | Ten annual HTML vintages 2016–2025; excludes the `United States` total row (G8) |
| `atlas_registrations.py` | 14 states, one adapter parameterised by state; ZIP vs county grain from the contract, never inferred |
| `wa_ev_population.py` | Socrata, the only natively tract-grain source |
| `census_acs.py` | Keyless bulk summary file primary, API fallback |
| `census_tiger.py` | Tract and 2020 block geometry |
| `census_blocks.py` | Block population from P.L. 94-171 + block-group population-weighted centroids |
| `nrel_home_charging.py` | XLSX parsed from raw XML (the workbook's non-standard namespace defeats openpyxl); loads the scenario surface, **not** a single slice |
| `hifld_transmission.py` | Streamed, voltage-filtered, tiled. Never parsed whole (G12) |
| `cejst_archive.py` | Internet Archive copy, vintage-labelled |
| `seed_files.py` | The ten frozen fixtures, loaded by canonical id from `SEED_PROVENANCE` |

Deferred, with reasons: `eia_prices.py` (Optional tier, §7.11), `egrid.py` (**not built** —
demoted to Optional/Future Work by amendment A8), `hifld_substations.py` (**not built** — no
national dataset exists, amendment A6), `fhwa_traffic.py` (Phase 5 need, no stable URL yet).

### 1.2 Transform — `pipeline/transform/`

`runner.py` executes DuckDB SQL in dependency order across three layers:

```
models/staging/       stg_*.sql    one per source; typing and renaming only, NO filtering
models/intermediate/  int_*.sql    joins, entity resolution, geographic allocation
models/marts/         mart_*.sql   published tables
```

Staging must not filter rows — filtering is business logic and belongs in intermediate
(`CLAUDE.md` §9). Every mart carries `computed_at` and `source_vintages`.

### 1.3 Schemas — `pipeline/schemas/`

One pandera schema per canonical table. **A schema violation fails the build and blocks
publication.**

### 1.4 Spatial — `pipeline/spatial/`

| File | Purpose |
|---|---|
| `geography.py` | Geography identification and the crosswalk registry (§7.5.1) |
| `crosswalk.py` | Weighted ZIP/ZCTA→tract and county→tract allocation, method preserved per row |

`h3_grid.py`, `allocation.py` and `distance.py` are Phase 2. Note this creates
`pipeline/spatial/`, so its **100% line and branch coverage requirement begins in Phase 1**
for whatever lands there.

### 1.5 Quality and lint — `pipeline/quality/`

| File | Purpose |
|---|---|
| `registration_checks.py` | The corrected G9 checks: vintage resolution, coverage, non-negativity, total reconciliation, per-capita and year-over-year anomaly screening |
| `port_identifiability.py` | The §6.1.1 analysis (see §3 below) |
| `copy_lint.py` | D3 and §11.5 terminology guard (see §4 below) |

---

## 2. Canonical tables

Grain and key. `charging_units` is elevated to a first-class table by amendment A5; `ports` is
now **conditional on measured identifiability**.

| Table | Grain | Key | Notes |
|---|---|---|---|
| `sites` | one physical location | `site_id` | DBSCAN on station coordinates, eps ≈ 50 m. **Never coordinate rounding** |
| `stations` | one AFDC record | `station_id` | A row is one network's presence, never capacity (G1) |
| `charging_units` | one EVSE cabinet | `charging_unit_id` | Carries `port_count`, per-connector counts, reported power, `power_source`, aggregate capacity |
| `ports` | one physical port | `port_id` | **Created only where source identity supports it** (§6.1.1). May be empty or partial; that is an honest outcome, not a failure |
| `connectors` | one connector | `connector_id` | J1772 / CCS / CHAdeMO / J3400 / J3271 |
| `tracts` | census tract | `geoid` | |
| `blocks_pop` | block population + internal point | `block_geoid` | TIGER `TABBLOCK20` joined to P.L. 94-171 |
| `state_totals` | EV stock by state and vintage | `(state, vintage)` | Ten AFDC vintages |
| `observed_subregion_ev` | sub-state registrations | `(source_geography, geo_id, vintage)` | Carries `source_geography_type` ∈ {usps_zip, zcta, county, tract} |
| `tract_ev_evidence` | registration evidence allocated to tracts | `(geoid, vintage)` | Carries `evidence_grain`, `estimate_method`, `crosswalk_source`, `crosswalk_vintage`, `allocation_weight_basis` |
| `substations` | — | — | **Not built.** No national dataset exists (A6) |

Every derived table carries `computed_at` and `source_vintages`.

---

## 3. Port-identifiability investigation (amendment A5)

**Runs before the canonical schema is frozen.** Six measurements over the national
charging-units export, reported both nationally and for the public + operational subset
(`Status Code == 'E'`, `Access Code == 'public'`):

1. availability of unit-level `port_count`;
2. availability of stable network-provided port identifiers;
3. whether connector-specific counts map unambiguously to physical ports;
4. frequency of `sum(connector-specific counts) > charging_unit.port_count` — evidence that
   one physical port exposes multiple connector types;
5. share of national infrastructure supporting true individual port identity;
6. share supporting only aggregate charging-unit capacity.

**Decision rule, fixed in advance so the result cannot be rationalised afterwards.** If (2) is
unavailable and (3) is ambiguous for the majority of public operational capacity, the
canonical hierarchy stops at `charging_unit` and `ports` is populated only for the identifiable
minority. No `port_001`-style rows are manufactured anywhere. Any row-per-port expansion
needed for arithmetic is labelled a *computational representation* and kept out of published
tables.

Assumptions A-0.16 and A-0.17 are settled here.

---

## 4. D3 / UI copy lint (amendment A9)

Rule-based phrase guard over Markdown, Python, SQL and (from Phase 6) TypeScript. Run in CI
from Phase 1 onward. Prohibited phrases, at minimum:

`validated optimal` · `optimal siting accuracy` · `optimal site` · `proven best` ·
`grid feasible` · `interconnection ready` · `available grid capacity` · `feeder capacity` ·
`transformer headroom` · `Justice40 compliance` · `charging desert` where only DCFC is
measured · `Tier A (observed)` and any labelling of Tier A as "observed"

Plus conflation checks on the three D3 terms — demand model validation, historical deployment
alignment, cross-objective robustness — so one is never used for another.

Two mechanics matter. The lint needs an **allowlist mechanism** so that documents which quote
a prohibited phrase in order to forbid it (this plan, `CLAUDE.md` §11.5, the amendment log) do
not self-trip. And it must exit non-zero, wired into `make lint` and `make gate`.

---

## 5. A-0.5 provenance investigation (amendment A10)

**Question:** are AFDC's `year=` registration pages contemporaneous annual snapshots, or
retrospective reconstructions from later VIN data? This bears directly on D1: a page labelled
2020 is not proof the numbers were available as of a 2020 cutoff.

**Bounded budget: one working session.** Sources to check, in order: AFDC/NLR publisher
documentation and methodology notes; Experian methodology statements; release notes; Internet
Archive captures of the registration pages at several dates, compared against today's values
for the same year; contemporaneous reports citing those figures.

**The decisive test** is cheap: if an archived 2021 capture of `?year=2020` shows the same
numbers as today's `?year=2020`, the series is stable and plausibly contemporaneous. If they
differ, it is retrospectively revised, and that is a finding with real consequences for
Phase 5.

**Outcomes.** Resolved → record the classification with preserved, hashed evidence and update
`backtest_eligible` accordingly. Unresolved → record
`historical_vintage_semantics: unresolved`, do **not** block Phase 1, and require Phase 5's
backtest methodology to state the limitation explicitly. Either way, the D1 runtime check
`feature_vintage <= prediction_cutoff` remains mandatory, and documentation must distinguish
the *technical vintage label* from *verified information-availability semantics*.

---

## 6. Geographic transformation boundary (amendment A4)

**In Phase 1:** declare each source's geography type explicitly in `SOURCES.yml`
(`usps_zip` | `zcta` | `county` | `tract`), acquire and version the crosswalk, implement
weighted allocation, stamp `evidence_grain`, `estimate_method`, `crosswalk_source`,
`crosswalk_vintage` and `allocation_weight_basis` on every produced row, and land
`tract_ev_evidence`.

**Deferred to Phase 3:** measuring allocation *error* (the Washington round-trip test),
converting that error into an uncertainty contribution, and deciding how many states are
genuinely usable for tract-level validation. Phase 1 builds the machinery and the provenance;
Phase 3 measures how well it works.

**Hard rule enforced by test in Phase 1:** no ZIP-derived or county-derived tract value may
carry `estimate_method == directly_observed`.

---

## 7. G1–G14 regression suite

One test per rule, against the frozen seed fixtures whose expectations never drift.

| Rule | What the test asserts |
|---|---|
| G1 | 79,618 station records represent 228,662 ports; a row is never counted as capacity |
| G2 | `Status Code` ∈ {E, T, P}; E=73,972, T=5,217, P=429; only E is operational supply |
| G3 | `Access Code` private = 4,662; excluded from public supply |
| G4 | 1,756 exact coordinate-duplicate rows aggregate to one site with summed ports, and are not deleted |
| G5 | IEA `category` has three USA values; a summing query is rejected |
| G6 | USA projection years are exactly {2025, 2030, 2035}; no silent interpolation |
| G7 | IEA `mode` has four values; stacking is valid only for total fleet |
| G8 | Registration counts are stock, never labelled sales; the `Total` / `United States` row is excluded before aggregation |
| **G9 (corrected)** | **Seven properties — see below** |
| G10 | `Open Date` may reflect first Station Locator appearance; approximate-date flag preserved |
| G11 | Any reconstructed historical network is labelled an approximate reconstruction |
| G12 | The transmission GeoJSON is never parsed as one object; a test asserts the streaming path is used |
| G13 | County joins use FIPS, never name; a Cook County MN/IL collision fixture proves it |
| G14 | `EV Connector Types` is parsed as a space-delimited concatenated string |

**G9's seven properties**, per `PLAN_CHANGE_0.md` §8:

1. registration vintage is resolved;
2. claimed jurisdiction coverage is present (51 jurisdictions for the seed file);
3. counts are non-negative and valid;
4. published totals reconcile where available (seed `Total` = 3,555,445 = sum of jurisdictions);
5. anomaly screening executes;
6. anomalies surface as **diagnostic review flags**;
7. **a low-confidence label cannot be assigned solely because a value is statistically or
   geographically unusual** — a negative test, and the one that encodes the correction.

---

## 8. Tests and gate criteria

### 8.1 Test layers

| Layer | Content |
|---|---|
| Unit | Every adapter, crosswalk function, quality check and lint rule |
| Regression | G1–G14 plus the Phase 0 suite (23 tests) re-run unchanged |
| Schema | Every canonical table against its pandera schema |
| Integration | Full pipeline on the MN + IL two-state fixture, end to end |
| Determinism | Two runs from a clean clone produce identical artifact checksums |
| Copy lint | Runs over the whole repository |

### 8.2 Gate criteria (all executable)

1. One command rebuilds every canonical table from a clean clone.
2. All G1–G14 pass, including the seven corrected-G9 properties.
3. Every canonical table validates against its pandera schema.
4. Entity hierarchy resolves with no orphans.
5. **No `ports` row exists whose identity the source does not support.**
6. Port-identifiability analysis complete, all six measurements reported numerically.
7. Every registration observation carries `evidence_grain` and `estimate_method`.
8. **No ZIP- or county-derived tract value is labelled `directly_observed`.**
9. Source geography declared explicitly per source; no USPS ZIP treated as a ZCTA.
10. D3 copy lint exists and passes repository-wide.
11. A-0.5 investigation yields a classification **or** an explicitly recorded unresolved
    status with preserved evidence.
12. Row counts within `SOURCES.yml` expected ranges.
13. Determinism: identical checksums across two runs.
14. Coverage: 100% line and branch on `pipeline/spatial/`; ≥85% on `pipeline/sources/` and
    `pipeline/transform/`; ≥70% repository-wide. `pipeline/model/` and `pipeline/validation/`
    remain not applicable.
15. Phase 0 gate suite re-run and passing (G-C).

### 8.3 Smoke-forward for Phase 2

Phase 2's core operation is the supply power ladder. The smoke-forward test will run a trivial
rung-1 power resolution over the **real** canonical `charging_units` table on the two-state
fixture, proving the entity hierarchy joins correctly and that `power_kw`, `power_source` and
`power_confidence` can be populated from canonical data. It will not implement rungs 2 or 3,
and will prove nothing about aggregation correctness or site collapsing.

---

## 9. Scope boundaries

**Explicitly in scope:** ingestion, canonical entities, staging/intermediate/marts, pandera
schemas, G1–G14, port-identifiability measurement, geographic provenance plumbing, the copy
lint, the A-0.5 investigation, determinism.

**Explicitly out of scope, deferred with its phase:** any model fitting (2, 3); H3 gridding
and access (2); the power ladder itself (2); allocation *error measurement* and uncertainty
scoring (3); siting (4); the leakage guard (5); anything frontend (6).

New ideas encountered during Phase 1 go to `docs/FUTURE_WORK.md`. Only a genuine correctness
blocker — a wrong source assumption, temporal leakage, an impossible schema, a canonical
entity that cannot be identified — triggers a plan change.

### Estimated scope

~2.25 part-time weeks. The two largest risks are the port-identifiability outcome, which could
force a canonical-schema shape decision late in the phase, and crosswalk acquisition, whose
licensing and vintage need checking before it is relied on.
