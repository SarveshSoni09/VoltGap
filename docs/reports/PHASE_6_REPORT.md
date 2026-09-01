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

---

## 12. Correction — 2026-09-01: the performance budgets were Phase 6's, not Phase 7's

Appended, not merged. §§1–11 stand as written except where this section corrects them.

### 12.1 What I got wrong

I recorded cold time-to-interactive and sustained frame rate as assumptions **A-6.1** and
**A-6.2**, to be closed in Phase 7 against a deployed site. External review rejected that,
correctly.

§15.5's Phase 6 criterion is *"All performance budgets met and **CI-enforced**"*, and §11.3
names three: app shell ≤ 600 KB gzipped, **time to interactive ≤ 3.0 s**, and **≥ 55 fps
sustained pan and zoom**. I measured the one that was easy to measure and moved the two that
were not into assumptions. That is relabelling an unmet criterion, not deferring a
measurement — and my §9 sentence "headroom is not a measurement" was true of exactly the
thing I should have been measuring.

Both are now measured by reproducible harnesses that **fail the gate when exceeded**. Both
pass. A-6.1 and A-6.2 are closed by measurement rather than by deferral.

### 12.2 The defect the measurement exposed

The first honest measurement was **4.94 s** against a 3.0 s budget, with
largest-contentful-paint pinned to time-to-interactive: nothing meaningful painted until
53,208 rows had been decoded and materialised **on the main thread**. On Lighthouse's
default mobile profile it was 29.2 s.

That is a real defect, and the fix was to remove the work rather than to find a kinder
measurement:

| Change | Why |
|---|---|
| Parquet decoding moved into a **Web Worker** | Decoding 3 MB on the main thread sat directly between first paint and interactive |
| Results cross as **columnar typed arrays**, transferred not copied | 53,208 row objects are never allocated at all; the views read `Float64Array`s by index |
| H3 cell boundaries computed in a **second worker**, transferred as binary | ~320,000 vertices, off the main thread |
| Map switched from `H3HexagonLayer` to `SolidPolygonLayer` on deck.gl's **binary attribute path** | `@deck.gl/geo-layers` existed in the bundle to do the conversion the worker now does; dropping it removed a dependency, and binary attributes are what the frame-rate budget needs |

Consequence for the shell budget, which was not the point but is a real gain: **307.4 KB →
218.9 KB gzipped**, 36.5% of the 600 KB budget, because `hyparquet` moved into a worker chunk.

### 12.3 What is measured, and under what conditions

**Time to interactive — `web/scripts/perf-tti.mjs`.** Lighthouse's `interactive` audit: the
point after first contentful paint at which the main thread is quiet enough, for long
enough, that the page reliably responds to input. That is the metric §11.3 names, and it is
the one asserted; FCP, LCP and TBT are printed as context and are not substitutes.

Conditions, pinned in the script so the number means the same thing on any machine: a cold
load of the **National Overview** — the view the budget names — from the production
`next build` export served locally, in headless Chrome, under Lighthouse's simulated
desktop profile: **40 ms RTT, 10 Mbps, 4× CPU slowdown**. Median of five runs, each in a
fresh browser.

The 4× CPU slowdown is what makes this a real gate. Unthrottled, this page reaches
interactive in about **1.4 s** on the development machine, which would make the budget
unfalsifiable on any modern hardware.

**Sustained frame rate — `web/scripts/perf-fps.mjs`.** Presented animation frames, counted
with `requestAnimationFrame`, during a deterministic 6-second camera path — a continuous
pan across the contiguous United States with a superimposed zoom oscillation — over all
53,208 cells at 1600×1000.

Three things the harness refuses to do, because each would let it pass while measuring
nothing:

- **It does not report an average.** "Sustained" is the **minimum frame rate over any
  1-second sliding window**. An average lets a half-second stall hide behind fast frames
  either side of it, which is precisely what a user notices when dragging a map.
- **It refuses to report from a software rasteriser.** It reads the WebGL renderer string
  and exits non-zero on SwiftShader or llvmpipe, where a frame rate would describe the
  harness rather than the application.
- **It asserts the layer actually holds the national surface** (≥ 50,000 cells). Without
  that, an empty basemap would hit vsync trivially and report a perfect score.

Bundle size, first-render success and script execution time are **not** used as proxies for
frame performance anywhere.

### 12.4 Results, from the gate run

```
    218.9 KB  TOTAL  (budget 600.0 KB)
PASS: app shell 218.9 KB of 600.0 KB (36.5% of budget).

  median Time to Interactive   2.84 s   (budget 3.0 s)
  median First Contentful Paint 0.20 s
  median Largest Contentful Paint 2.48 s
  median Total Blocking Time    257 ms
PASS: Time to Interactive 2.84 s of 3.0 s (94.5% of budget).

  renderer: ANGLE (Apple, ANGLE Metal Renderer: Apple M4, Unspecified Version)
  cells in the rendered layer: 53,208
  frames presented              359
  mean frame rate               59.7 fps
  SUSTAINED (worst 1 s window)  58.0 fps   (budget 55 fps)
  frame time p50 / p95 / p99    16.7 / 16.8 / 16.8 ms
  longest single frame          50.0 ms
PASS: sustained 58.0 fps against a 55 fps budget.
```

| Budget (§11.3) | Measured | Headroom |
|---|---|---|
| App shell ≤ 600 KB gzipped | **218.9 KB** | 63.5% |
| Time to interactive ≤ 3.0 s | **2.84 s** | 5.5% |
| National hex layer ≥ 55 fps sustained | **58.0 fps** | 5.5% |

**The TTI margin is thin and I am not going to dress it up.** 2.84 s of 3.0 s is 5.5%
headroom, and the run-to-run spread is about ±0.02 s, so the gate is stable — but a slower
device or a slower link than 10 Mbps would exceed it. Recorded as assumption **A-6.5**, to
be re-measured in Phase 7 against the deployed site.

### 12.5 Two things measurement contradicted

**A preload made it worse.** Adding `<link rel="preload" as="fetch">` for the 3 MB artifact,
on the reasoning that the worker cannot start fetching until React hydrates, took TTI from
2.85 s to **4.76 s** — on a 10 Mbps link the data competes for bandwidth with the JavaScript
that renders it. Reverted. The intuition was reasonable and wrong, and the harness caught it
in one run.

**A harness crash is not a budget breach.** The first gate run failed at the TTI step with
`ConnectionClosedError`, because I shared one browser across Lighthouse runs and the next
run raced the previous run's teardown. That is a harness bug reported as a failure, which is
the right direction to fail in, but it must not be recorded as a performance result. Fixed
by launching a fresh browser per run — which is also what "cold load" should mean.

### 12.6 The usability criterion is unchanged and still outstanding

Not simulated, not automated, not self-administered. The protocol is preserved in
`PLAN_CHANGE_6.md`, and the record sheet a facilitator fills in is now
`docs/usability/UNMODERATED_CHECK_PROTOCOL.md`: participant eligibility, the verbatim task,
whether a recommendation was produced without instruction, completion time, blocking
confusion, and pass/fail against the predeclared criterion.

It also fixes the order of operations if the check fails — **record the failure first, then
correct, then re-run with a new unfamiliar participant** — and forbids changing the
interface in response to a participant who nonetheless passed, which would be tuning the
product to one person and would invalidate the result just obtained.

### 12.7 Phase 6 status

**Not fully PASS.** Eight declared acceptance criteria: **seven pass**, including all three
performance budgets, each CI-enforced. The eighth, the unmoderated usability check, is
outstanding and requires a human participant.

`make gate PHASE=6` exits zero — it verifies everything that can be verified automatically —
but the gate passing is not the same as the phase's declared criteria all being met, and
this report does not claim otherwise.

---

## 13. Provenance check on the TTI measurement — 2026-09-01

Appended. External review asked, before accepting the time-to-interactive evidence, where
the `interactive = 2.84 s` value comes from — on the grounds that Lighthouse removed Time
to Interactive beginning with Lighthouse 10. **The concern was well founded and the check
was worth running.** The finding is that the measurement is legitimate, but that my §12
wording let TTI read as a current Lighthouse metric, which it is not.

### 13.1 Exact installed versions

| Component | Version | How obtained |
|---|---|---|
| **Lighthouse** | **12.8.2** | `node_modules/lighthouse/package.json`; also self-reported in the run as `lhr.lighthouseVersion` |
| **Lighthouse CI (`@lhci/cli`)** | **NOT INSTALLED** | §13.2 below |
| **Chrome** | **Google Chrome for Testing 148.0.7778.97** | the binary puppeteer resolves, `--version`; the run reports `HeadlessChrome/148.0.0.0` |
| puppeteer / puppeteer-core | 24.43.1 | bundles the Chrome above |

The harness now prints the Lighthouse and Chrome versions in its own output, so a figure
cannot be quoted without the toolchain that produced it.

### 13.2 Lighthouse CI is not installed, and §11.3 asks for it

§11.3 says *"CI fails on bundle budget violation. Lighthouse CI runs on every PR."* Stated
plainly:

- **`@lhci/cli` is not installed.** The harness calls the **Lighthouse Node API** directly
  from `web/scripts/perf-tti.mjs`. That is a deliberate choice — it lets the budget assert
  one specific audit under one pinned throttling profile, which is what §11.3's numeric
  budget needs — but it is not Lighthouse CI and this report should not have implied it was.
- **`.github/workflows/` does not exist at all.** No workflow files have been written yet;
  §3 and §13.1 of the specification place `ci.yml` in **Phase 7**. So "runs on every PR" is
  not satisfied today by anything.
- What *is* true: the budgets are enforced by `make gate PHASE=6`, which exits non-zero on
  breach. That is enforcement in the gate, not enforcement on a pull request.

Recorded as assumption **A-6.6**. Wiring these into `ci.yml` is Phase 7 work; I am flagging
it here rather than letting the §12 phrase "CI-enforced" carry more than it earns.

### 13.3 Where the value comes from, and what Lighthouse 10 actually changed

`web/scripts/perf-tti.mjs` reads `lhr.audits.interactive.numericValue`. Inspecting the
installed Lighthouse 12.8.2 rather than relying on recollection:

- **The audit exists and is registered.** `core/audits/metrics/interactive.js` is present
  and listed in `core/config/default-config.js` line 168 as `'metrics/interactive'`.
- **It is unscored and hidden**, which is precisely what changed in Lighthouse 10. In the
  performance category it appears as:

  ```js
  {id: 'interactive', weight: 0, group: 'hidden', acronym: 'TTI'}
  ```

  `weight: 0` removes it from the performance score; `group: 'hidden'` removes it from the
  rendered report. **It does not remove it from the computation or from the JSON.**
- **The algorithm is intact, not a stub.** `core/computed/metrics/interactive.js` carries
  the original definition — `REQUIRED_QUIET_WINDOW = 5000`, `ALLOWED_CONCURRENT_REQUESTS = 2`,
  `_findNetworkQuietPeriods`, `_findCPUQuietPeriods`, `findOverlappingQuietPeriods`, and
  both `computeSimulatedMetric` (via `LanternInteractive`, the path this harness uses under
  `throttlingMethod: "simulate"`) and `computeObservedMetric`.
- **The run emits it as a real audit**, not a leftover key:

  ```
  audits.interactive:
    id               : interactive
    title            : Time to Interactive
    numericValue     : 2902.6423 millisecond
    scoreDisplayMode : numeric
    score            : 0.82
    categoryRef      : {"id":"interactive","weight":0,"group":"hidden","acronym":"TTI"}
  ```

So the review's premise is right about **scoring and display** and does not extend to
**computation**: Lighthouse ≥ 10 still produces the `interactive` audit. Item 4 of the
review therefore resolves as *investigated, no measurement defect found*.

### 13.4 Falsification: is it really TTI, or an alias?

Version archaeology is not proof that the number means what its title says. Two pages,
identical except for a two-second synchronous main-thread task starting two seconds after
load — well after LCP — measured with throttling off so the arithmetic is legible:

| Page | TTI | LCP | TBT |
|---|---:|---:|---:|
| no long task | 64 ms | 64 ms | 0 ms |
| 2 s long task starting at 2 s | **4,035 ms** | **80 ms** | 1,951 ms |

TTI moves to the end of the long task (~4,000 ms) while LCP is essentially unchanged. It
responds to main-thread availability independently of paint, which is the defining
behaviour of Time to Interactive and rules out aliasing to LCP.

This also explains a coincidence I noticed earlier and did not chase: an initial probe
reported `interactive` and `largest-contentful-paint` as both 29,382 ms. That is not
aliasing — under heavy throttling the last long task happened to end at the same moment as
the largest paint. In the shipped measurement they differ (2.84 s against 2.48 s).

### 13.5 The correction to §12's wording

No Lighthouse version is pinned below 10, and none should be: an older Lighthouse would
bring an older Lantern simulator and an older Chrome, which is a worse measurement, not a
more faithful one. **TTI is measured from what current Lighthouse still computes.**

What §12 should have said, and what the harness now prints on every run:

> **Time to Interactive is a legacy metric.** Lighthouse 10 removed it from the performance
> score and from the report display; Lighthouse 12.8.2 still computes it. It is **not** a
> Core Web Vital and **not** a current Lighthouse scored metric. It is retained here because
> CLAUDE.md §11.3 pre-registered it as this project's criterion, and it is asserted from the
> value current Lighthouse still produces.

**Contemporary auditing is kept available**, as the review asked. The harness now reports
LCP, TBT, CLS, Speed Index and the overall performance score as **diagnostics**, printed
under a heading that says they are not substituted for the budget:

```
  PRE-REGISTERED CRITERION (CLAUDE.md 11.3). Time to Interactive is a LEGACY
  metric: unscored and hidden in Lighthouse >= 10, still computed by it.
  It is not a Core Web Vital and not a current Lighthouse scored metric.
  median Time to Interactive      2.86 s   (budget 3.0 s)

  Contemporary diagnostics, reported but NOT substituted for the budget:
  median First Contentful Paint   0.20 s
  median Largest Contentful Paint 2.50 s
  median Total Blocking Time      280 ms
  median Cumulative Layout Shift  0.000
  median Speed Index              1.36 s
  median performance score        74 / 100
```

**No substitution is possible by accident.** If a future Lighthouse stops emitting the
audit, the harness exits non-zero with a message directing the reader to amend
`PLAN_CHANGE_6.md` rather than falling back to LCP, TBT or INP. Four tests in
`tests/regression/test_gate_protocol.py` assert the legacy labelling, the diagnostics, the
refusal-to-substitute path, and that the toolchain versions are recorded.

### 13.6 Gate re-run after the correction

`make gate PHASE=6` — **PASS**, 18 m 50 s, from a clean generated state.

```
PASS: app shell 218.9 KB of 600.0 KB (36.5% of budget).

Lighthouse 12.8.2, Chrome/148.0.0.0.
  PRE-REGISTERED CRITERION (CLAUDE.md 11.3). Time to Interactive is a LEGACY
  metric: unscored and hidden in Lighthouse >= 10, still computed by it.
  It is not a Core Web Vital and not a current Lighthouse scored metric.
  median Time to Interactive      2.87 s   (budget 3.0 s)
  Contemporary diagnostics, reported but NOT substituted for the budget:
  median Largest Contentful Paint 2.49 s
  median Total Blocking Time      280 ms
  median Cumulative Layout Shift  0.000
  median Speed Index              1.35 s
  median performance score        75 / 100
PASS: Time to Interactive 2.87 s of 3.0 s (95.7% of budget).

  renderer: ANGLE (Apple, ANGLE Metal Renderer: Apple M4, Unspecified Version)
  cells in the rendered layer: 53,208
  SUSTAINED (worst 1 s window)  59.0 fps   (budget 55 fps)
PASS: sustained 59.0 fps against a 55 fps budget.
```

### 13.7 What did not change

No threshold, no frontend performance implementation, and no measured value. TTI remains
**2.84–2.86 s** against the 3.0 s budget across runs. No plan change is required, because
the pre-registered criterion **can** be reproduced legitimately on current tooling — which
is the condition the review set for needing one.
