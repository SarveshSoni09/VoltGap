# Phase 6 report — Frontend Core

**Gate: PASS with one criterion outstanding and escalated.** Run `make gate PHASE=6`,
**27 m 38 s**, from a clean generated state — `web/out/` and `web/public/data/` deleted
first, so nothing was tested against leftovers from an earlier run. Reviewed by an external model with no repository access, so every number,
schema, test name and code excerpt is quoted inline.

---

## 1. Context, for a reader who has read nothing

**VoltGap** answers: *given a budget and a set of policy priorities, where should the next
EV charging infrastructure be built in the United States, and how confident should we be in
that answer?* It is a statically hosted, zero-recurring-cost decision-support application.

**What the previous phases produced, all frozen and accepted before this phase began:**

| Phase | Produced |
|---|---|
| 0 | The source contract: every data source verified, with its schema, coverage and fallback |
| 1 | Ingestion and the canonical tables; domain rules G1–G14 as regression tests |
| 2 | Supply with a power-resolution ladder, and block-group-weighted access |
| 3 | A tract-level demand surface: 84,401 tracts, each with a continuous uncertainty score, an `evidence_grain`, an `estimate_method` and a confidence tier |
| 4 | Siting: candidate filtering, an exact ε-constraint frontier per state, and a greedy solver |
| 5 | Three validations: demand model validation, historical deployment alignment (**negative** against a population baseline), and cross-objective robustness |

**Phase 6 builds the frontend and the artifacts it loads.** It adds no model. Every number
it displays comes from an accepted phase.

---

## 2. What was built

### 2.1 The publication layer — `pipeline/export/`

New. Turns the accepted pipeline outputs into the files a static site can load.

| Artifact | Rows | Bytes | §12 budget | Purpose |
|---|---:|---:|---|---|
| `hex6_national.parquet` | 53,208 | 3,007,913 (3.01 MB) | 8–15 MB | The national cell surface; the only data file the first view needs |
| `access_points.parquet` | 239,780 | 7,413,590 (7.41 MB) | 5–10 MB | Block-group access points, for the live threshold control |
| `sites.parquet` | 82,056 | 1,120,664 (1.12 MB) | 3–6 MB | Public operational sites as a point layer |
| `frontier/{state}.json` × 6 | 16 each | ~6 KB each | small | Phase 4's published analytical frontier, unchanged |
| `manifest.json` | — | 13 KB | small | Checksums, row counts, `computed_at`, source vintages, degradations |

The national surface is assembled from Phase 3's estimates with **demand conservation and
provenance survival asserted per state**, exactly as Phase 4 asserts them — a cell cannot
reach an artifact having silently lost the evidence behind it.

**National totals, as published:** 53,208 populated cells across 51 jurisdictions;
5,568,123 estimated BEV; **7.70%** of that demand sub-state anchored, 92.30% modeled from
state totals.

**48,800 BEV (0.88%) are unallocated** — demand in tracts with no block-group population
weight. It is carried into `manifest.json` as `notes.unallocated_demand_bev` rather than
dropped, so the national total a reader sums from the cells and the total the model produced
differ by a number that is published rather than mysterious.

### 2.2 The frontend — `web/`

Next.js 15.5.25 with `output: "export"`, React 19.2.8, TypeScript strict, MapLibre GL JS
5.24.0, deck.gl 9.3.11, h3-js 4.5.0 — the same H3 version as the Python `h3` 4.5.0, so cell
indexes mean the same thing on both sides.

Four views, all statically exported:

1. **National Overview** — H3 res-6 choropleth, metric selector (demand, existing DCFC
   ports, DCFC access gap, priority score), confidence tier always visible as opacity, and
   a panel reporting sub-state anchored versus modeled share with the evidence-grain
   breakdown beneath it.
2. **Access & Equity** — a live DCFC access gap threshold control with its sensitivity
   curve, recomputed in the browser from 239,780 per-point distances rather than
   interpolated between server-chosen points; population affected, broken out by the named
   ACS income indicator; opt-in archived CEJST context.
3. **Siting Studio** — state, budget and objective-weight controls; a greedy solve in a Web
   Worker; a ranked candidate table carrying every row's confidence tier; CSV and GeoJSON
   export; the candidate universe reported with each exclusion named and counted.
4. **Methodology & Validation** — a first-class view, not a footer link.

---

## 3. Acceptance criteria

> Static export deploys. All performance budgets met and CI-enforced. Exports produce valid
> CSV and GeoJSON verified by parse. UI copy lint passes (§11.5 rules). Confidence tier
> renders on every modeled value. Unmoderated usability check: one person unfamiliar with
> the project produces a siting recommendation without instructions.

| # | Criterion | Test | Status | Evidence |
|---|---|---|---|---|
| 1 | Static export deploys | `test_p6_a_the_static_export_produced_every_core_view` | **PASS** | 4 views exported; served over HTTP and loaded in a real browser |
| 2 | No server runtime in Core | `test_p6_a_no_server_runtime_is_required` | **PASS** | No `api/`, `_next/server`, `middleware.js` or `proxy.js` in `out/` |
| 3 | Bundle budget met, **CI-enforced** | `test_p6_b_the_bundle_budget_script_passes_and_is_enforceable` | **PASS** | **307.4 KB of 600 KB (51.2%)**; script exits non-zero on breach |
| 4 | Greedy re-solve ≤ 2 s | `performance budget (§11.3...)` in `studio.test.ts` | **PASS** | Texas, the largest frontier state, across the whole budget slider range |
| 5 | Exports valid, **verified by parse** | `tests/exporters.test.ts` (10 tests) | **PASS** | CSV parsed by an independent reader; GeoJSON by `JSON.parse` |
| 6 | UI copy lint passes | `make copy-lint` in the gate | **PASS** | **clean, 216 files, 15 rules** — now covering `web/` |
| 7 | Confidence tier on every modeled value | `test_p6_d_every_published_cell_carries_a_tier_and_evidence_grain` | **PASS** | 0 rows of 53,208 missing a tier, grain, uncertainty or anchored share |
| 8 | Unmoderated usability check | — | **OUTSTANDING** | Cannot be executed by an automated gate. §5 below |

### 3.1 The strongest check: the browser sites on Phase 4's cells

`test_p6_c_the_published_artifact_reproduces_phase_4s_candidate_universe`, parameterised
over all six frontier states, applies Phase 4's filter rules to the published artifact and
compares against Phase 4's own published counts — exclusion by exclusion.

| State | Candidates | beyond road | saturated | uninhabited |
|---|---:|---:|---:|---:|
| Washington | 674 | 185 | 184 | 11 |
| Tennessee | 1,425 | 54 | 117 | 7 |
| Montana | 297 | 103 | 31 | 1 |
| Vermont | 250 | 8 | 53 | 0 |
| Texas | 2,417 | 659 | 441 | 15 |
| California | 1,253 | 366 | 629 | 20 |

**Every figure matches `docs/evidence/P4-1_siting.json` exactly.** A mismatch would mean the
Studio offers candidates the accepted pipeline excluded, which no amount of interface polish
would make acceptable.

This required carrying Phase 4's road filter into the artifact. The browser cannot run it —
TIGER carries ~380,000 vertices for one state — so `attach_road_filter` runs Phase 4's own
code path unchanged and ships the verdict as `passes_road_filter`. Nationally, **5,415 of
53,208 cells (10.2%) fail it.** Without this the browser's candidate universe would have
silently diverged, and my own TypeScript docstring would have described a filter that was
not there.

### 3.2 The greedy solver is a port, checked against the original

`web/lib/optimizer/greedy.ts` is a port of `greedy_select` in `pipeline/model/siting.py`.
The expected values in `web/tests/fixtures/greedy_cases.json` were **generated by that
Python function**, not written by hand. Five cases, and the fixtures deliberately include
adjacent cells whose k-ring coverage overlaps — a fixture of isolated cells would pass for
a solver that ignored coverage entirely. 30 candidates in the fixture set have multi-cell
coverage, asserted by a test so that property cannot quietly disappear.

Ten tests, including determinism, order-independence, and that the budget is never exceeded.

---

## 4. What Phase 6 found upstream

### 4.1 I-27 — the road reader handled only LineString

The first national road read failed:

```
RoadSourceError: WKB geometry type 5 is not LineString (2);
TIGER road features are LineStrings and anything else is unexpected
```

Measured across all 51 cached state files: **Ohio carries 3 MultiLineString features out of
10,350 included features (0.029%). Every other state is pure LineString.**

**No Phase 4 result is affected**, and this is worth being precise about rather than
reassuring: Phase 4's six frontier states contain none, and the reader **raised** rather
than mis-parsing — the failure mode was a hard stop, which is the behaviour it was written
to have. P6-C re-verifies Phase 4's candidate counts cell for cell above.

Fixed by `parse_wkb_geometry`, which handles both types and returns **each part as its own
polyline**. That separation is the point: joining a MultiLineString's parts would invent a
segment running between them, and a cell beside that phantom road would pass the proximity
filter. `test_multilinestring_parts_never_become_one_connected_road` asserts the joined and
separated readings differ by more than 45 km at the midpoint between two parts.

Seven new tests; `pipeline/sources/tiger_roads.py` back at 100% line and branch coverage.
Severity **S3** against published output, but a hard blocker for national use.

### 4.2 Two things I got wrong while building, and how they surfaced

**The copy lint caught my own prose twice.** Once in the Phase 6 plan document, once in
`web/lib/vocabulary.ts` — where the offending string was the D6 grid disclaimer, which
denies the claim it was flagged for. I reworded both rather than reaching for the inline
allow-marker, because an allow on a user-visible string is how a lint quietly stops
protecting the thing it was written for. The two places I did use the marker are test
assertions that must contain a prohibited phrase in order to search for it.

**My `buildCandidates` docstring described a road filter that did not exist.** I wrote the
comment before the data supported it. Caught by reading my own code back; fixed by adding
the column to the pipeline (§3.1) rather than deleting the claim.

---

## 5. The criterion I could not execute

> *Unmoderated usability check: one person unfamiliar with the project produces a siting
> recommendation without instructions.*

**This requires a human participant. I cannot recruit one, and I cannot simulate one** — the
whole value of the check is that a person unfamiliar with the design meets the interface
cold, and anything I produce is by construction familiar with it. §15.1 G-A forbids marking
a criterion passed by inspection.

Escalated under §15.6 in **`docs/reports/PLAN_CHANGE_6.md`**, with a runnable protocol (one
participant, ~15 minutes, verbatim task), three options with a recommendation, and an honest
account of what the automated checks do and do not establish.
`test_p6_g_the_unmoderated_usability_check_is_recorded_as_outstanding` asserts that document
exists with its options and protocol — it does **not** assert the check passed.

**I have not claimed this criterion.** Phase 6's gate passes on the other seven; this one is
outstanding and owner-owned.

One thing in the protocol is worth surfacing here: it asks the facilitator to record whether
the participant came away believing the tool told them the *best* places to build. A
participant who completes the task but leaves thinking the output is optimal has exposed a
real failure of the §11.5 language rules, and that finding would matter more than the
completion.

---

## 6. Language constraints, carried forward unchanged

Every §11.5 rule is machine-checked, and the lint now reads `.ts`/`.tsx` so UI strings are
covered — the place a false claim would actually reach a user.

The user-facing vocabulary lives in one file, `web/lib/vocabulary.ts`, so a careless label
cannot undo work five phases deep. `tests/vocabulary.test.ts` (16 tests) checks the half a
lint cannot: that the required caveats are **present** and correct.

| Rule | How it is enforced |
|---|---|
| Tier A is "sub-state anchored", never "observed" | `TIER_LABELS.A`, asserted in TypeScript **and** against the built HTML and JavaScript in `test_p6_d_tier_a_is_never_called_observed_anywhere_in_the_exported_site` — a constant renamed in source but stale in a bundle would pass a source-only check |
| No approximation bound for the interactive solver | `INTERACTIVE_SOLVER_NOTE`, asserted to contain no guarantee language |
| Nothing is optimal | `NOT_OPTIMALITY_NOTE`, shown on both ranking surfaces and written into every export |
| A DCFC-only measure is a DCFC access gap | Separate columns for DCFC and L2 distance; the view says so |
| Grid proximity, never feasibility | `GRID_PROXIMITY_NOTE`, asserted to contain no feasibility language |
| CEJST is archived, with its vintage | `CEJST_NOTE`, naming the 20 January 2025 revocation |
| The three D3 terms never conflated | `VALIDATION_TERMS`, asserted to have three distinct names and methods |

**Phase 5's negative result is presented as negative.** The Methodology view states that the
model does **not** outperform a population baseline at any origin, that this is a negative
historical-deployment-alignment result, and that it is neither evidence of siting failure
nor evidence for or against excluding supply features. Reconstructed capacity carries its
unknown-direction caveat. **No validation claim was strengthened for presentation.**

---

## 7. Gate evidence

```
=== Phase 6 gate: PASS ===
make gate PHASE=6  1603.19s user 294.71s system 114% cpu 27:38.11 total
```

Run after deleting `web/out/` and `web/public/data/`, both git-ignored and generated. The
gate builds them at **step 0**, before the acceptance tests read them, which is what makes
it reproducible from a clean clone rather than passing on leftovers. An earlier run of this
gate did test against leftovers; that ordering was wrong and is now asserted against by
`test_the_phase_6_gate_builds_generated_inputs_before_it_tests_them`.

**Coverage — 100% line and branch on every result-computing package, and 100% repository
wide:**

| Package | Statements | Branches | Coverage | Threshold |
|---|---:|---:|---:|---|
| repository wide | 6,233 | 1,468 | **100%** | ≥ 70% |
| `pipeline/model` | 2,722 | 632 | **100%** | = 100% |
| `pipeline/validation` | 970 | 212 | **100%** | = 100% |
| `pipeline/discovery` | 691 | 202 | **100%** | = 100% |
| `pipeline/spatial` | 509 | 138 | **100%** | = 100% |
| `pipeline/sources` | 429 | 114 | **100%** | ≥ 85% |
| `pipeline/quality` | 298 | 68 | **100%** | = 100% |
| **`pipeline/export`** | **278** | **48** | **100%** | **= 100% (new tier)** |
| `pipeline/transform` | 100 | 14 | **100%** | ≥ 85% |
| `pipeline/schemas` | 52 | 2 | **100%** | = 100% |

**G-C — thirteen prior-phase suites replayed, each as its own invocation:**

```
    tests/regression/test_source_findings.py             PASS  23 passed
    tests/regression/test_domain_rules.py                PASS  39 passed
    tests/regression/test_phase2_gates.py                PASS  37 passed
    tests/regression/test_phase3_gates.py                PASS  20 passed
    tests/regression/test_phase3_corrections.py          PASS  32 passed
    tests/integration/test_smoke_forward.py              PASS  11 passed
    tests/integration/test_smoke_forward_phase2.py       PASS  5 passed
    tests/integration/test_smoke_forward_phase3.py       PASS  5 passed
    tests/regression/test_phase4_gates.py                PASS  23 passed
    tests/regression/test_gate_protocol.py               PASS  70 passed
    tests/integration/test_smoke_forward_phase4.py       PASS  5 passed
    tests/regression/test_phase5_gates.py                PASS  33 passed
    tests/integration/test_smoke_forward_phase5.py       PASS  7 passed
    all prior-phase gate suites PASS
```

Phase 6 acceptance: **19 passed**. Phase 7 smoke-forward: **6 passed**. Frontend suite:
**45 passed** across 4 files. Copy lint: **clean, 216 files, 15 rules**. Determinism: semantic
hash unchanged. Rebuild: canonical tables, Phases 3–5, all artifacts, and the static export.

---

## 8. Forward viability (G-D)

**Contract.** `manifest.json` is the single index Phase 7's ETL republishes: every artifact
with its `sha256`, `bytes`, `rows` and columns, plus `computed_at`, `stale_after_days` and
the full `source_vintages` map. `tests/integration/test_smoke_forward_phase6.py` (6 tests)
exercises the shape Phase 7 needs — including that a manifest can be rewritten with a new
timestamp **without rebuilding artifacts**, which is exactly what §13.2's failure path
requires when a refresh fails and prior artifacts must stay live.

**Staleness is computable by moving the clock only**, because the threshold ships inside the
manifest. That is what makes §15.5 Phase 7's "verified by clock manipulation" a test rather
than a code change.

**The data base URL is configurable** (`NEXT_PUBLIC_DATA_BASE`), so pointing the site at R2
is configuration, not a code change.

**Assumption ledger.** Four assumptions opened: **A-6.1** (cold-load budget measured
locally, not on a deployed site), **A-6.2** (frame rate not measured — the headless browser
here reports no frame timing worth quoting), **A-6.3** (parquet point layer substituting for
vector tiles), **A-6.4** (the usability check, gate-blocking). A-6.1 and A-6.2 close in
Phase 7 against the deployed site.

---

## 9. What is not known

- **Whether anyone unfamiliar with this can use it.** The single most important thing this
  phase did not establish. §5.
- **Time-to-interactive and frame rate on a real device over a real network.** Measured
  locally from localhost. The artifact is 3.01 MB against an 8–15 MB budget and the shell is
  51% of its budget, so there is headroom — but headroom is not a measurement, and I have
  not quoted a TTI or fps figure because I do not have an honest one.
- **Whether the parquet point layer is adequate at high zoom.** No vector tiles;
  `tippecanoe` is unavailable here.
- **Whether the basemap is reliable.** OpenFreeMap's public instance is a single point of
  failure (§12) and the self-hosted fallback is Phase 7 infrastructure. A basemap failure is
  now *surfaced in the interface* — the data layer still renders and the page says the
  geographic context is missing — rather than showing an empty country.

## 10. Impact log delta

**Opened and resolved this phase:** I-27 (road reader handled only LineString; Ohio has
MultiLineString; no Phase 4 result affected).

**Still open from earlier phases:** A-0.5 and A-5.3 remain documented limitations, untouched.
A-5.6 remains open. No prior-phase output was changed by Phase 6.
