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

---

## 14. PR CI integration — 2026-09-01

Appended. `.github/workflows/ci.yml` now exists and runs on pull requests. Every job invokes
an existing accepted `make` target rather than reimplementing its logic; a test asserts no
threshold is restated in the workflow, so the two cannot drift.

**Scope:** Phase 6 acceptance plumbing only. No `etl.yml`, no schedule, no keepalive, no
deployment, no health monitoring — `test_no_phase_7_automation_has_crept_in` and
`test_no_other_workflow_files_exist` enforce that.

### 14.1 On "Lighthouse CI"

§11.3 says *"Lighthouse CI runs on every PR"*. This uses the Lighthouse **Node API** through
`web/scripts/perf-tti.mjs`, **not `@lhci/cli`**, and that choice is deliberate rather than
incidental: the budget is one specific audit under one pinned throttling profile asserted
with a non-zero exit, which the Node API gives directly. `lhci` would wrap it in a second
configuration surface carrying its own thresholds to drift from ours. The requirement it has
to satisfy is *runs automatically on PRs and fails the PR on breach*.

### 14.2 What PR CI enforces, and what it does not

Two prerequisites are absent from a GitHub-hosted runner. **Both were measured, not
assumed**, and the evidence is in `PLAN_CHANGE_6.md` under "CI runner limits".

| Check | GitHub-hosted PR | Gate |
|---|---|---|
| ruff, `mypy --strict`, D3 copy lint | **enforced** | yes |
| Gate-protocol + CI-workflow regression suites | **enforced** | yes |
| Frontend typecheck, build, tests | **enforced** | yes |
| Greedy port vs the Python reference; 2 s solve budget | **enforced** | yes |
| **App shell ≤ 600 KB gzipped** | **enforced** — deterministic gzip, identical semantics | yes |
| **TTI ≤ 3.0 s** | skipped unless `PERF_DATA_RUNNER` is set | yes |
| **Sustained ≥ 55 fps** | skipped unless `PERF_GPU_RUNNER` is set | yes |
| Full Python suite + coverage thresholds | not run | yes |

The two host-dependent jobs are **skipped rather than faked**, and an always-running
`performance-enforcement-status` job prints on every PR exactly which budgets that PR did and
did not enforce, so a green CI cannot be read as more than it is. It also fails if the
limitation stops being documented.

### 14.3 Three findings from building it

**A GPU-less Chrome here serves no WebGL at all** — not a SwiftShader fallback:

```
--use-gl=swiftshader     => NO WEBGL AT ALL
--disable-gpu            => NO WEBGL AT ALL
```

So the frame-rate harness's name-based software check would have missed exactly the case CI
produces, and the run would have failed later as an opaque timeout. It now refuses
`renderer === "none"` explicitly. **The harness is unweakened**: ≥50,000 rendered cells still
required, software rendering still rejected, worst 1-second window still the measured
quantity.

**The TTI harness would have passed on a page with no data.** `data/cache/` is git-ignored
and 4.4 GB, so a CI runner cannot build the artifacts the National Overview fetches. Measured
with them absent: the page renders its error state and the harness reported **0.96 s — a
comfortable PASS against a 3.0 s budget — while measuring a page with no map and no data.**
That is a defect in the harness, found by this investigation and fixed independently of CI:
it now refuses unless the page under test holds ≥50,000 cells, the same guard the frame-rate
harness carried. Verified in both directions.

**§12's claim that the pinned profile made TTI machine-independent was wrong.** Lighthouse's
`simulate` normalises the *network* but derives CPU task durations from a trace taken on the
host. Same code, same page, this machine:

| `cpuSlowdownMultiplier` | TTI | vs the 3.0 s budget |
|---|---:|---|
| 1 | 2.38 s | within |
| **4 (shipped)** | **2.86 s** | **within** |
| 8 | 3.40 s | over |
| 12 | 3.96 s | over |

A shared CI runner is materially slower than this machine, so even with the identical profile
its absolute figure would not be interchangeable with the accepted one.

### 14.4 The literal requirement is not yet met, and I stopped rather than weakening it

§11.3 says *"All performance budgets met and CI-enforced"*. One of three — the app-shell
budget — is enforced on a GitHub-hosted PR. The other two are enforced by
`make gate PHASE=6` and are skipped on PRs unless a runner with the prerequisites is
provided.

`PLAN_CHANGE_6.md` sets out the narrowest truthful distinction the review asked for —
**(a)** a CI-enforced reproducible performance regression check versus **(b)** the
hardware-rendered acceptance benchmark — with three options. Option A (point the two
repository variables at a self-hosted runner with a GPU and the source cache) is the only one
under which the literal requirement becomes true, needs no code change, and is what I
recommend. **The workflow as committed is Option C: it enforces what it can, skips what it
cannot, and says so on every PR.** I have not chosen between them.

### 14.5 An honest limit on this evidence

**I cannot execute the workflow.** Pushing to the remote is blocked in this environment, so
no CI run exists to point at. What I verified locally is that every command the workflow
invokes succeeds, and that the frontend jobs pass with `web/public/data/` removed — the state
a clean runner is in. The workflow's *behaviour on GitHub* is therefore reasoned from
measured local evidence, not observed.

### 14.6 Gate re-run

`make gate PHASE=6` — **PASS**, 22 m 08 s, from a clean generated state.

```
PASS: app shell 218.9 KB of 600.0 KB (36.5% of budget).

  page under test holds 53,208 cells
Lighthouse 12.8.2, Chrome/148.0.0.0.
  median Time to Interactive      2.87 s   (budget 3.0 s)
PASS: Time to Interactive 2.87 s of 3.0 s (95.7% of budget).

  renderer: ANGLE (Apple, ANGLE Metal Renderer: Apple M4, Unspecified Version)
  cells in the rendered layer: 53,208
  SUSTAINED (worst 1 s window)  59.0 fps   (budget 55 fps)
PASS: sustained 59.0 fps against a 55 fps budget.
```

No threshold, implementation or measured result changed. The unmoderated usability check
remains outstanding.

---

## 15. Approved specification amendment and the enforcement split — 2026-09-01

Appended. The owner reviewed `PLAN_CHANGE_6.md`, **declined to provision a self-hosted
GPU/data runner**, and approved a bounded specification amendment instead — on the finding
that the original wording *"all performance budgets CI-enforced"* conflated two different
classes of measurement.

**CLAUDE.md §11.3 is amended, formally and dated, as §19 amendments A27 and A28.** No
budget, threshold, harness, profile or measured value changed. What changed is where each
budget is enforced and what PR CI does about the ones it cannot measure.

### 15.1 The two enforcement classes

| Budget | Enforcement |
|---|---|
| App shell ≤ 600 KB gzipped | **PR CI hard gate** |
| Greedy state solve ≤ 2.0 s | **PR CI hard gate**, on the accepted real Texas fixture (3,532 published cells) |
| TTI ≤ 3.0 s | **Reference-environment hard gate.** An arbitrary runner's absolute figure is never compared against the 3.0 s threshold |
| National hex render ≥ 55 fps | **Hardware-rendered reference-environment hard gate.** Never run or passed under software rendering, absent WebGL, or an empty or degraded layer |

PR CI **protects** the two environment-dependent budgets with the seven assertions §11.3
now requires — `make web-perf-guards`, 27 checks in
`tests/regression/test_performance_guards.py`, none of which is a performance measurement.
The PR status prints them as **"NOT EXECUTED ON THIS RUNNER — this is not a PASS. Nothing
was measured."** `PERF_DATA_RUNNER` and `PERF_GPU_RUNNER` are retained as an optional path
and are not a Core dependency.

### 15.2 The gate failed first, and what that exposed

The first gate run after the amendment **failed**: TTI 3.20 s against the 3.0 s budget, with
the page confirmed holding 53,208 cells — so a genuine breach, not a harness fault.

Investigated rather than re-run until green. Two measurements settled it:

- **Induced load reproduces it.** Same code, same page, same profile: **2.91 s quiescent,
  3.84 s under eight competing CPU burners.**
- **Lighthouse's own `benchmarkIndex` detects it**: ~4092 quiescent, **2840** under the same
  load.

The gate runs roughly twenty minutes of full-load work — the whole suite under coverage, a
national artifact rebuild, a production frontend build — and then measured immediately. It
was measuring its own load.

**Two things were wrong, and both were fixed without touching a threshold, the harness
semantics, or the application:**

1. **No machine-validity guard.** The TTI harness now refuses to report against the budget
   when the median `benchmarkIndex` falls below **3500** — about 85% of the observed
   quiescent range 4032–4136, and comfortably above the 2840 the loaded case produced. It
   exits with a distinct status and the message **"NOT MEASURED … This is a validity guard,
   not a budget failure."** It is the same class of check as refusing software rendering or
   a page with no data: it governs which measurements may be reported, never the budget they
   are reported against. Verified firing: an invocation at `benchmarkIndex` 3388 was refused
   while ones at 4016 and 3616 reported 2.90 s and 2.93 s.
2. **No quiescence step.** `web/scripts/perf-settle.mjs` waits for load per core to fall to
   0.6 before the environment-dependent benchmarks. This is part of establishing the
   reference conditions, not part of any measurement, and the `benchmarkIndex` guard
   independently verifies that it worked.

I am recording that **this machine is a developer laptop, not a controlled benchmark rig** —
during this investigation `mediaanalysisd` alone reached 234% CPU unprompted. The
validity guard exists because that is the honest state of the reference environment.

### 15.3 Gate re-run

`make gate PHASE=6` — **PASS**, 32 m 44 s, from a clean generated state.

```
PASS: app shell 218.9 KB of 600.0 KB (36.5% of budget).
      greedy state solve: 2 passed          (portable class)
      environment-dependent protection: 27 passed

  settled after 75 s, load 5.85
  page under test holds 53,208 cells
Machine validity: median benchmarkIndex 4076 (floor 3500).
  median Time to Interactive      2.89 s   (budget 3.0 s)
PASS: Time to Interactive 2.89 s of 3.0 s (96.3% of budget).

  settled after 25 s, load 5.94
  renderer: ANGLE (Apple, ANGLE Metal Renderer: Apple M4, Unspecified Version)
  cells in the rendered layer: 53,208
  SUSTAINED (worst 1 s window)  59.0 fps   (budget 55 fps)
PASS: sustained 59.0 fps against a 55 fps budget.
```

`docs/evidence/P6-1_performance.json` records each figure with the reference environment
that produced it — platform, CPU model and cores, Node, Lighthouse and Chrome versions,
throttling profile, `benchmarkIndex` and its floor, renderer string and cells rendered.

### 15.4 The margin, stated plainly

TTI sits at **2.89–2.93 s against a 3.0 s budget** on valid measurements: **a 2–4% margin.**
That is smaller than the run-to-run variation an uncontrolled machine produces, which is
exactly why the validity guard had to exist. On a machine that is genuinely quiescent the
budget is met consistently; on one that is not, the harness now says so rather than
reporting a number. Assumption **A-6.5** remains open and this is its evidence.

### 15.5 Status

**Phase 6 has one unmet acceptance criterion: the unmoderated human usability check.**
Every other criterion, including all four performance budgets under the amended §11.3
semantics, is met and enforced. **A-6.8 remains open**: the workflow is locally validated
but has never been observed running on GitHub, and I do not claim otherwise.

---

## 16. The analytical layer rendered nothing — 2026-09-01

Appended. Manual inspection by the project owner found that the National Overview drew the
basemap, reported 53,208 cells, populated every sidebar statistic and the legend, and drew
**no analytical polygons at all**. Severity **S1**: the primary output of the application
was invisible.

**No automated check caught it, and I had verified the map visually exactly once — before
the binary refactor — and never looked again after changing the rendering path.** That
process failure is the reason a three-part rendering bug shipped behind a green gate.

### 16.1 Three defects, all from the object-to-binary refactor

Isolated by changing one variable at a time against identical coordinate buffers:

| # | Defect | Symptom |
|---|---|---|
| 1 | `_normalize: false` on `SolidPolygonLayer` | The whole surface drew in **white** — invisible on a light basemap |
| 2 | Colour buffer built **per polygon**, where deck.gl's binary path reads **per vertex** | One seventh of the expected length; colours read from wrong offsets |
| 3 | Map created before its CSS grid column resolved | deck.gl's drawing buffer stuck at **34×420**, the size of the "Loading map…" placeholder, for the life of the page. Neither `map.resize()` nor `deck.setProps({width, height})` recovered it |

### 16.2 Why everything passed

- `__voltgapLayerCells` reported **53,208** throughout. It counts cells *handed to* the
  layer, not cells *drawn* — the distinction this defect exists to teach.
- The frame-rate harness required ≥50,000 cells and got them, so it measured 58–60 fps
  over an **invisible** layer.
- The geometry was **correct**: 7 vertices per cell, rings closed, first cell at
  (−158.21, 64.64) in Alaska, bounds −175.6..−84.1 lon and 31.5..71.3 lat.
- Every cell carried **non-zero alpha**; the layer was attached, `visible: true`,
  `opacity: 1`, on a correctly sized CSS box.
- The frontend unit tests exercise the solver, exporters and vocabulary. None renders.

### 16.3 Frontend only — proven, not assumed

The same coordinate buffers pushed through deck.gl's **non-binary object path** rendered
the national surface correctly on the first attempt. The published parquet artifacts are
unaffected; no pipeline output changed.

### 16.4 The regression, and why a pixel count is not enough

`web/scripts/render-check.mjs` renders the same view twice — with the analytical layer and
with `?layer=off` — and compares the output.

**A pixel count alone passes the real defect.** The white rendering still changed **5.22%**
of map pixels. So the check also asserts the changed pixels carry the layer's *palette*:
viridis is saturated or dark throughout, and white is neither.

| | pixels changed | of those, chromatic |
|---|---:|---:|
| Defective (`_normalize: false`) | 5.22% | **0.9%** |
| Correct | 9.97% | **51.6%** |

A 57-fold separation, threshold at 20%.

**Verified to fail on the real defects, not merely to pass on the fix.** Reintroducing
`_normalize: false` fails it on the palette assertion; reintroducing the per-polygon colour
buffer fails it on the structural buffer-length assertion.

Structural guards retained: ≥50,000 polygons, all geometry within US bounds, a
continental-US spot check with a closed ring, per-vertex colour buffer length, and visible
alpha. **A golden screenshot was deliberately not used** — it would break on a basemap tile
change or a browser update and be quietly re-blessed.

The frame-rate harness now also requires a per-vertex colour buffer, because a frame rate
measured over an invisible layer measures an idle GPU.

### 16.5 Every map surface revalidated

Confirmed visibly rendering, not inferred from sidebar values: **National Overview** on all
four metrics — estimated BEV demand, existing DCFC ports, DCFC access gap, and priority
score with the weight slider — and the **Siting Studio** for Washington, showing 674
candidates with the selected portfolio highlighted and the ranked table populated. Access &
Equity is a table-and-curve view with no map surface.

### 16.6 Gate re-run, thresholds unchanged

`make gate PHASE=6` — **PASS**, 35 m 06 s, from a clean generated state.

```
PASS: app shell 219.1 KB of 600.0 KB (36.5% of budget).

  continental-US spot check: cell 183, 7 vertices,
    lon -112.094..-111.998, lat 48.831..48.895 — within -125..-66 / 24..50
  rendered difference: 89,539 of 897,820 pixels changed (9.97%), threshold 2%
  of those, 51.6% carry the layer's palette (threshold 20%)
PASS: the analytical layer is visibly rendered.

Machine validity: median benchmarkIndex 3911 (floor 3500).
  median Time to Interactive      2.92 s   (budget 3.0 s)
PASS: Time to Interactive 2.92 s of 3.0 s (97.2% of budget).

  cells in the rendered layer: 53,208
  colour buffer: 1,489,824 bytes for 372,456 vertices (per-vertex, correct)
  SUSTAINED (worst 1 s window)  59.0 fps   (budget 55 fps)
PASS: sustained 59.0 fps against a 55 fps budget.
```

**No threshold was changed because visible rendering is more expensive.** The frame rate
with the layer genuinely visible is 58–59 fps against the same 55 fps budget.

Impact-log entry **I-29**, severity **S1**.

### 16.7 Status

**Phase 6 has one unmet acceptance criterion: the unmoderated human usability check**,
which must not be attempted until now — the map was not functional when the protocol was
written. It remains outstanding and requires an unfamiliar participant. **A-6.8** remains
open: the workflow is locally validated but has never been observed running on GitHub.

---

## 17. UX and visual-communication pass — 2026-09-01

Appended. A presentation pass, bounded to the frontend. **No model, threshold, objective,
candidate rule, confidence calculation or validation result changed.** Confirmed
numerically in §17.6.

### 17.1 What the blank areas of the national map actually meant

Measured over all published cells **before** changing any rendering:

| | |
|---|---:|
| Published cells | 53,208 |
| With a modelled demand value | **53,208 (100%)** |
| Demand missing / NULL | **0** |
| Demand exactly zero | 390 |
| Cells excluded from rendering | **0** |
| Cells drawn at alpha ≤ 0.1 | **0** (faintest in use was 0.41) |
| Tier A / B / C | 4,678 / 36,396 / 12,134 |
| Land area covered by published cells | 1,937,726 km² of 9,147,590 km² |
| **US landmass with no published cell at all** | **78.8%** |

**The white space was none of the ambiguous readings.** Not missing data, not zero demand,
not low confidence, not excluded, not near-transparent. A cell exists only where census
population sits inside it, so unpopulated terrain — desert, mountain, forest, federal land —
produces no cell. The interface now says exactly that, in the legend and in a disclosure.

### 17.2 Confidence no longer disappears demand

Reliability was encoded as opacity: tier C drew at 41% alpha. On a light basemap a
low-reliability estimate faded toward the background, which is also what the 78.8% with no
cell looks like — so "we are unsure" and "nobody lives here" were visually the same thing.

Colour now carries the metric and nothing else, at one constant alpha. Reliability is
reported separately: a plain three-way breakdown in the sidebar, a per-row rating in the
candidate table, and the precise wording on hover. **The underlying values are untouched.**

### 17.3 The national map is legible at national scale

53,208 resolution-6 cells at national zoom read as scattered dots. A **presentation-only**
aggregation rolls them to a coarser H3 resolution for drawing: resolution 4 below zoom 5,
5 below zoom 7, native 6 above.

**Conservation is proven, not asserted.** `cellToParent` is exact containment, so summing
over children conserves exactly. `tests/aggregate.test.ts` (19 tests) checks on the real
published surface, at resolutions 3, 4 and 5, that demand, population, underserved
population and port counts all match the native totals to six decimal places, that every
native cell is accounted for exactly once, and that every cell lands under its own H3
parent. Quantities that are **not** additive are not summed: distance is a
population-weighted mean, bounded by the native range, and labelled a display summary.

Resolution 4 rather than 3 was chosen deliberately. A parent is drawn if any child has
population, so an over-coarse grouping paints a large hexagon for one small town and makes
the country look uniformly covered — hiding the very gaps §17.1 measured.

The performance harnesses use `?resolution=native`, which disables aggregation, so their
≥50,000-cell guards keep their original meaning rather than being satisfied by ~4,000
aggregated parents.

### 17.4 Terminology

| Was | Now | Precise wording kept in |
|---|---|---|
| National Overview | **Where is EV demand highest?** (nav: EV demand) | — |
| Access & Equity | **Where is charging access weakest?** (nav: Charging gaps) | — |
| Siting Studio | **Plan new charging locations** (nav: Plan locations) | — |
| Methodology & Validation | **How it works** | heading only; content unchanged |
| Estimated BEV demand | **Estimated EV demand** | data dictionary |
| Sub-state anchored | **Higher reliability** | tooltip, details panel, exports, Methodology |
| Modeled | **Modelled** | as above |
| Low confidence | **Lower reliability** | as above |
| Confidence tier | **Estimate reliability** | as above |
| DCFC access gap (km to nearest site) | **Distance to fast charging** | Methodology |
| Existing DC fast ports | **Existing fast charging** | exports |
| Equity coverage | **Underserved population reached** | Methodology (the named ACS indicator) |
| `CELL` / `8628d5407ffffff` | **Area** → *King County, WA* | Technical details panel, CSV, GeoJSON |
| Uncertainty 0.223 | removed from the default table | Technical details panel |
| Demand 0.60 · equity 0.40 | **Demand / Balanced / Underserved communities** | Advanced weighting |
| Budget: 20 sites | **How many new locations can you fund? → 20 areas** | — |
| excluded: beyond primary secondary road network | **outside the road-proximity range** | exact counts kept, one click away |

**"Higher reliability" does not mean observed.** The plain labels are a presentation layer;
`sub-state anchored` and its full definition remain reachable and are what the exports and
Methodology use. A test asserts no page ever *claims* an estimate is directly observed.

Area names come from a new **display-only** artifact column: the county contributing the
most population to each cell, derived from geography the pipeline already held. All 53,208
cells have one, mean dominant-county share 0.999. Where no county resolves, the label falls
back to `Area NN` — **no address or place is invented**, because an H3 centroid is not a
property.

### 17.5 The Siting Studio reads as a planning tool

The journey is now input → result → map → table → detail. A portfolio summary appears
before any raw output: candidate areas, estimated EVs in range, underserved population
reached, and how many have no fast charging today.

**Selection is unmistakable.** The 20 selected areas draw as haloed markers over faint grey
eligible areas, with a three-state legend — selected, other eligible, not a candidate. It is
a shape difference, not a shade difference, so it survives at any zoom.

**Each area explains itself.** Reasons are assembled only from that area's own published
values and are ranked by how *unusual* the area is on each dimension, not by a fixed
importance — otherwise every row leads with the same sentence. A test asserts the reasons
vary between rows.

### 17.6 Nothing analytical changed

| | Before the pass | After |
|---|---|---|
| National demand total | 5,568,123.0027 | **5,568,123.0027** |
| Tier A / B / C cells | 4,678 / 36,396 / 12,134 | **4,678 / 36,396 / 12,134** |
| Mean uncertainty, tier A / B / C | — | 0.164801 / 0.140926 / 0.252962 |
| Washington candidates | 674 | **674** |

Copy lint: **clean, 229 files, 15 rules**, with every §11.5 rule intact. It caught one of my
own strings during this pass — a plain-language line that used a banned superlative inside a
denial — and I reworded rather than allow-marking it.

### 17.7 Cold-user regression

`web/scripts/ux-check.mjs` drives a real browser, opens every collapsed section and expands
a candidate row, and reads `innerText` — because these views are client-rendered and a check
against the emitted HTML would pass while the visible page said something else. It asserts
the product states its question, each view leads with what it answers, the first read does
not open with methodology, the map explains its colours and its blank areas, no snake_case
column name or raw H3 index is visible, reliability is plain but never overstated, the
reasons vary, and every claim safeguard survived.

Three of its checks were false positives on first run, flagging phrases that appear inside
the interface's own *denials* — the same trap the copy lint has. It now tests whether the
text **asserts** a phrase rather than merely contains it.

### 17.8 Gate

`make gate PHASE=6` — **PASS**, 21 m 14 s, from a clean generated state.

```
PASS: app shell 222.4 KB of 600.0 KB (37.1% of budget)
  rendered difference: 89,845 of 897,820 pixels (10.01%), palette 69.9%
PASS: the analytical layer is visibly rendered
PASS: the interface reads correctly to someone who knows nothing about it
  page under test holds 53,208 cells (represented)
  Machine validity: median benchmarkIndex 4152 (floor 3500)
PASS: Time to Interactive 2.92 s of 3.0 s (97.5% of budget)
  cells in the rendered layer: 53,208
PASS: sustained 59.0 fps against a 55 fps budget
```

Performance is unchanged by the visual work, and **no threshold was adjusted** to
accommodate it.

### 17.9 Status

**The unmoderated human usability check remains the one unmet criterion**, and it must now
be run against this frozen UX rather than the earlier interface. It still requires a
participant who has not seen the project.

---

## 18. Map explorability pass — 2026-09-05

Appended. A second presentation pass, bounded to the frontend and to one published label
column. **No model, threshold, objective function, candidate rule, uncertainty component
or validation result changed.** One genuine data defect was found while doing it and is
recorded as impact-log entry **I-30**; it touched only the county-name label.

### 18.1 What was wrong

After §17 the three views were legible but not **explorable**. A reader could see that
somewhere mattered and could not ask *which* somewhere:

| View | State before this pass |
|---|---|
| **EV demand** (national) | A choropleth with no hover and no click. A hexagon could not be identified geographically or quantitatively. |
| **Charging gaps** | **No map at all.** The `.canvas` element held a table. The threshold control drove four summary figures and a sensitivity table; there was nothing spatial for it to move. |
| **Plan locations** (Studio) | A map and a table describing the same twenty areas, with no connection between them. Portfolio markers were undifferentiated dots — "which one is candidate #4" was unanswerable. |

The Charging Gaps finding is worth stating precisely, because the brief asked for the cause
to be established before any redesign. Four causes were considered: (1) the map reads a
different dataset from the summary; (2) it reads the same data but ignores the threshold;
(3) it applies the threshold to a different column; (4) there is no map. **The cause was
(4), literally.** `grep` over `web/app/access/page.tsx` found no `HexMap` import, no
maplibre and no deck.gl reference; `threshold` was consumed by exactly two call sites,
`gapAtThreshold(points, threshold)` for the headline figures and the same function inside
the sensitivity curve. Causes (1)–(3) were excluded by construction: there was nothing to
disagree.

### 18.2 One information pattern, not three

Every map now answers a hover and a click through the **same component**,
`web/components/FeatureCard.tsx`, positioned by `web/components/CardAnchor.tsx`. The order
is fixed so a reader learns it once:

```
place  →  the metric this page is about  →  2–4 supporting facts
       →  why this area (Studio only)     →  reliability
       →  ▸ Technical details              →  what to do next
```

Its interface is deliberately narrow:

```ts
export interface FeatureCardProps {
  readonly place: string;
  readonly near?: string;
  readonly primaryLabel: string;
  readonly primaryValue: string;
  readonly facts: readonly FeatureFact[];
  readonly reliability?: { readonly label: string; readonly tier?: "A" | "B" | "C" };
  readonly reasons?: readonly string[];
  readonly technical?: readonly FeatureFact[];
  readonly actions?: React.ReactNode;
  readonly rank?: number;
}
```

Hovering floats the card beside the cursor and shows the compact form. Clicking pins it to
the bottom-right — where the map's own zoom controls (top-right) and the legend
(bottom-left) are not — and reveals **Technical details** and any action. H3 indexes,
uncertainty scores, H3 resolution and the measure definition live only in that disclosure.

The primary value is the metric the reader selected. On the national view:

| Selected metric | Dominant card value | Supporting facts |
|---|---|---|
| Estimated EV demand | Estimated EVs | People, fast-charging ports, nearest fast charging |
| Existing fast charging | Fast-charging ports | Estimated EVs, people, nearest fast charging |
| Distance to fast charging | To nearest fast charging | Estimated EVs, people, ports |
| Priority score | Priority at *n*% demand | Estimated EVs, underserved population, nearest fast charging |

The selected metric never repeats as a supporting fact, which is what made the earlier
draft of this card read as a data dump.

### 18.3 Geography that can be defended

Every card and every table row names a place with `placeName(county, state)` —
`"Kootenai County, ID"` — from the `county_name` and `state_code` columns the pipeline
publishes as the **population-weighted dominant county** of the cell. Coverage after the
I-30 fix: **53,208 of 53,208 rows labelled, 0 blank, 0 naming a county in another state.**

Three things were deliberately not done:

- **No street address, no city, no "near X".** An H3 resolution-6 cell is about 38 km² and
  its centroid is not a location anyone lives at. A reverse-geocoded address would be an
  invention, and the `near` field of the card is left unset everywhere for that reason.
- **No place name where the pipeline has none.** `placeName` returns `null` and the card
  says "Unnamed area" rather than falling back to coordinates or an H3 index.
- **No overselling of a grouped area.** At national zoom the display groups cells, and a
  group can span several counties. `groupedPlaceName` says so explicitly:
  `"Mitchell County, IA and 3 nearby counties"`. The name goes to the county contributing
  the most demand, so the label points at where the number actually is.

### 18.4 The Charging Gaps map derives from the same pass as the figures

`gapCells(table, thresholdKm, column)` in `web/lib/data/access.ts` rolls the block-group
points up to H3 cells using **the same points, the same threshold and the same comparison**
as `gapAtThreshold`, which produces the headline figures. They cannot disagree, and
`web/tests/access.test.ts` asserts it at 1, 5, 16.1, 30 and 50 km — population, affected
lower-income population and point count all reconcile exactly.

Two honesty details surfaced while testing it:

- **230 of the 20,781 cells beyond 16.1 km hold no population.** They are genuinely beyond
  the distance, so they stay in "neighbourhoods affected"; they are not shaded on a map
  whose colour means *people affected*. Both facts are asserted.
- Their distance was being reported as **0 km**, because a population-weighted mean over
  zero weight is undefined. That would have said the opposite of what is true about an
  empty place with no charging near it. It now falls back to the plain mean, and a test
  requires every mapped cell's reported distance to exceed the threshold.

### 18.5 "Areas worth investigating" is a filter, not a new model

The four lenses on the Charging Gaps view sort and trim the areas the threshold already
selected, using quantities that are already published and already exported:

| Lens | Ranking quantity | Limit |
|---|---|---|
| All gap areas | population beyond the threshold | none |
| Most people affected | population beyond the threshold | top 100 |
| Lower-income households | affected population in households under $35k | top 100 |
| Furthest from charging | population-weighted distance | top 100 |

There is **no composite score, no hidden weighting and no new index.** The sidebar says so
in those words, and a reader can reproduce every list from the exported columns. The lens
selects *which* areas; display grouping then decides how they are drawn — in that order,
because trimming after grouping would silently answer a different question (the top hundred
*groups*, not the top hundred *areas*).

### 18.6 The Studio's map and table are one list

Four bindings, all through one `hover` state holding an H3 index:

| Action | Effect |
|---|---|
| Hover a map cell or marker | Row highlights (`tr.linked`), card describes the area |
| Hover a table row | Marker enlarges and inverts to white, card appears in the corner |
| Click either | Map flies to the area, marker highlights, row scrolls into view and expands, card pins |
| Close the card | Selection clears on both sides |

Rank markers carry their rank as a `TextLayer` label, so the numbered dot on the map and
the Rank column in the table are the same identity. Any re-solve — a change of state,
budget or priority — clears the selection, because a rank means nothing across a re-solve.

Two defects were found and fixed while verifying this by hand rather than by reading the
code:

- A card summoned by hovering a **table row** appeared at the last position the mouse had
  been on the **map**, which is meaningless. It now parks in the same corner a pinned card
  uses, so the reader's eye has one place to look.
- Clicking a marker opened the right row but the table stayed at the top: measured
  `scrollTop` was **7.5 px** when it should have been ~81 px. Two causes — the scroll was
  issued in the same tick as the row expansion, so it aimed at the pre-expansion position;
  and React replacing the rows on that re-render cancelled the smooth-scroll animation. It
  now scrolls the table's own container after the committed layout, instantly.

### 18.7 Cross-page state is carried, and says why

`Plan locations in Montana` on a Charging Gaps card links to
`/studio/?state=30&from=gaps&threshold=45.5`. The Studio selects that state and shows:

> **CHARGING GAPS** — You came from the charging-gaps map, where "far" was set to 45.5 km.
> That setting describes the gap; it is not used to choose these areas.

**The link carries only where to look.** The threshold travels as a sentence, never as a
solver input: nothing about the optimiser's objective, weights, budget or candidate
filtering changed, and the greedy solver never sees the value. The action appears only for
the six states the published frontier covers, rather than sending a reader somewhere that
cannot answer them.

### 18.8 A confidence tier is never invented in the interface

The first draft of the national card derived a tier in the browser from
`sub_state_anchored_share` and `uncertainty_score`. That is a **second classification rule
living beside §7.4.2's**, and it was removed before it shipped.

The card now reports the pipeline's published `confidence_tier` for a single cell. Where
cells are grouped for display and their published tiers disagree, there is no published
tier for the group and **none is manufactured** — the card reports the sub-state-anchored
share instead, a quantity that is published and that means the same thing at any grouping.
`aggregate()` returns `confidence_tier: null` in exactly that case, and
`web/tests/aggregate.test.ts` asserts the rule in both directions.

Per §11.5 nothing here is called "observed": the wording is *"0% of demand here is
sub-state anchored"*.

### 18.9 The defect this pass found in the published data — I-30

Joining county labels into a test fixture returned **6,046 rows for 6,000 requested
cells**, which is only possible if the key is not unique.

`mart_hex6_national`'s grain is **`(h3_index, state_fips)`**, not `h3_index`.
`build_national` assembles the surface state by state and asserts demand conservation per
state, so a cell straddling a state line is published **once per state**, each row holding
that state's share. Measured: **53,208 rows over 52,912 distinct cells** — 292 cells twice,
2 cells three times.

The place-name lookup was keyed by cell alone and merged across states, so the last state
processed overwrote both rows. **301 of 53,208 rows (0.57%)** named a county in a different
state; the Idaho part of the cell on the Spokane border was published as *"Spokane County,
WA"*. Fixed by keying the lookup by `(state, cell)`. After rebuild: **0 mislabelled, 0
unlabelled**, and cell `8612db31fffffff` reads `16 → Kootenai County, ID` and
`53 → Spokane County, WA`.

Classified **S2**, not S1: `county_name` and `state_code` are presentation labels added in
this phase and no model, optimiser or validation reads them, so no published result
changed.

The same assumption was in the browser. At native resolution `aggregate()` returned its
input unchanged, so a split cell was drawn as two stacked hexagons and hover answered with
whichever was on top. Native resolution now goes through the same grouping as the display
roll-up, so one hexagon gives one answer and every additive quantity survives the merge
exactly. Two consequences a reader will see: the view reports **52,912 distinct areas**
rather than 53,208 rows, and the ≥50,000-cell TTI guard counts distinct cells.

### 18.10 Evidence

New and changed automated checks:

| Check | Asserts |
|---|---|
| `web/tests/access.test.ts` (18 tests) | Map and summary agree at five thresholds; the threshold moves the geography; DCFC and L2 are different maps; every mapped cell's distance exceeds the threshold; uninhabited cells counted but not shaded; grouping conserves people and affected population |
| `web/tests/aggregate.test.ts` (+3) | State parts of a border cell merge into one hexagon with conservation; every cell carries a county; a grouped area reports how many counties it spans; no tier is invented for a group |
| `tests/unit/test_export.py` (+1) | Every published row's `state_code` matches its own `state_fips`, on the real Idaho/Washington border cell |
| `web/scripts/ux-check.mjs` (§7–§9, +23 assertions) | Drives the real hover and click paths on all three maps: a card appears, names a place as `County, ST`, carries no raw H3 index in the hover form, pins with Technical details, and puts the H3 index only there. The gaps threshold changes the mapped geography. The Studio's row hover highlights, describes, shares one identity with the card, and brings the row into view |

### 18.11 A frame-rate regression I introduced, and the harness gap that let it be misread

The gate caught a real regression: **23.8 fps sustained against the 55 fps budget**, down
from 58–59 fps. It was mine, and diagnosing it exposed a weakness in the harness.

**The defect.** Adding hover and click meant passing `onHoverCell` and `onPickCell` into
`HexMap`, and I listed them in the layer-building effect's dependency array. They arrive as
inline arrow functions, so they are new objects on every render of the parent — and the
national view re-renders on every zoom change, which during a pan is **every frame**. The
effect rebuilt all three layers and re-uploaded the 370,384-vertex buffer once per frame.

The callbacks were already read through a ref refreshed on every render, so they never
belonged in the deps. Only the boolean *whether picking is enabled* can change what the
layer must be rebuilt for. After the fix: **60.0 fps sustained, frame time p50 16.7 ms** —
one frame per vsync, matching the pre-pass baseline exactly.

**The harness gap.** `perf-fps.mjs` had strong guards on *what was rendered* — ≥50,000
cells, a per-vertex colour buffer, no software rasteriser, no missing WebGL context — and
**no guard on whether the environment could render at all.** The TTI harness has exactly
that guard, a `benchmarkIndex` floor added under amendment A27. The frame-rate harness had
no counterpart, so it reported `FAIL: 23.8 fps` with no evidence about whether the figure
described the application or the machine.

That is not a hypothetical distinction. On this run it misled the author: a follow-up
measurement taken while another browser held 43% CPU returned 7.1 fps, and was read as
proof that the machine rather than the code was at fault. It was not.

**The guard now added.** Before measuring, the harness drives the identical camera path
over the identical page with the analytical layer turned off — the measured scene minus the
thing being measured, and therefore strictly cheaper. If that cannot hold the budget, the
environment cannot demonstrate anything about the more expensive scene, and the run reports
**NOT MEASURED** rather than FAIL.

Measured immediately, on the same machine, minutes apart:

| Scene | Sustained (worst 1 s window) |
|---|---:|
| Basemap only, layer off (calibration) | **60.0 fps** |
| Full layer, before the fix | 26.3 fps |
| Full layer, picking disabled | 22.4 fps (so picking was not the cause) |
| Committed baseline `e970c50`, built in a clean worktree from the same data | **60.0 fps** |
| Full layer, after the fix | **60.0 fps** |

The baseline comparison is what settled it: the previous commit's build reached 60.0 fps on
the same machine within minutes of the failing run, so the machine was not the variable.

**The guard cannot launder a regression.** Calibration renders a strictly cheaper scene, so
a genuine per-frame cost still fails — calibration holds vsync while the measured run does
not, which is precisely what happened here. The guard can only ever convert a FAIL into
NOT MEASURED, never a FAIL into a PASS, and it did not prevent this defect from having to
be fixed.

No previously reported frame-rate figure is affected: every one was a PASS, and a validity
guard cannot turn a pass into anything else.

### 18.12 Gate evidence — `make gate PHASE=6`, 2026-09-05

```
--- 1. lint (ruff + mypy strict + frontend typecheck) ---
ruff: All checks passed!
mypy: Success: no issues found in 148 source files

--- 2+3. full test suite under coverage, and coverage thresholds ---
144 tests passed
repository wide                                6270 stmts  0 miss  1482 branch  100%
pipeline/model      100%    pipeline/spatial    100%    pipeline/validation  100%
pipeline/quality    100%    pipeline/schemas    100%    pipeline/discovery   100%
pipeline/export     100%    pipeline/sources    100%    pipeline/transform   100%

--- 4. prior-phase gate suites replayed (Phase 0 through 5) ---
  test_source_findings.py        PASS  23 passed
  test_domain_rules.py           PASS  39 passed
  test_phase2_gates.py           PASS  37 passed
  test_phase3_gates.py           PASS  20 passed
  test_phase3_corrections.py     PASS  32 passed
  test_phase4_gates.py           PASS  23 passed
  test_phase5_gates.py           PASS  33 passed
  test_gate_protocol.py          PASS  91 passed
  test_smoke_forward.py          PASS  11 passed
  test_smoke_forward_phase2.py   PASS   5 passed
  test_smoke_forward_phase3.py   PASS   5 passed
  test_smoke_forward_phase4.py   PASS   5 passed
  test_smoke_forward_phase5.py   PASS   7 passed

--- 6. D3 copy lint (source and frontend) ---
copy lint: clean (233 files, 15 rules)

--- 7. determinism (semantic, CLAUDE.md 14.1) ---
determinism: identical

--- frontend ---
88 tests passed (7 files)
slowest greedy re-solve   0.0334 s   (budget 2.0 s)
PASS: app shell 225.8 KB of 600.0 KB (37.6% of budget)
  rendered difference: 89,796 of 897,820 pixels changed (10.00%), palette 69.9%
PASS: the analytical layer is visibly rendered
PASS: the interface reads correctly to someone who knows nothing about it

--- environment-dependent class: reference-environment hard gate ---
  page under test holds 52,912 cells (represented)
  machine validity: median benchmarkIndex 4147 (floor 3500)
  median Time to Interactive      2.91 s   (budget 3.0 s)
  median FCP 0.20 s   LCP 1.61 s   TBT 273 ms   CLS 0.031   SI 1.33 s
PASS: Time to Interactive 2.91 s of 3.0 s (96.9% of budget)

  machine validity: basemap-only calibration 58.9 fps sustained (floor 55)
  cells in the rendered layer: 52,912
  colour buffer: 1,481,536 bytes for 370,384 vertices (per-vertex, correct)
  frames presented 362   frame time p50/p95/p99  16.7 / 16.7 / 16.8 ms
PASS: sustained 60.0 fps against a 55 fps budget

=== Phase 6 gate: PASS ===
```

**Two diagnostics moved, and neither is a budget.** Largest Contentful Paint went from
0.90 s to 1.61 s and Cumulative Layout Shift from 0.002 to 0.031, both measured on the
same reference environment. The gated metric, Time to Interactive, improved slightly
(2.93 s → 2.91 s), and the frame rate is unchanged at the vsync ceiling.

The LCP change is the largest painted element changing identity: the map summary panel and
the map surface now paint later and larger than the sidebar text that previously held the
title. The CLS change is a fifteen-fold increase from a very small base and remains an
order of magnitude inside the 0.1 "good" boundary; it was not chased further because CLS is
not a §11.3 budget and no threshold anywhere depends on it. Both are recorded here so the
movement is on the record rather than discovered later as an unexplained drift.

Screenshots of the interactions are in `docs/evidence/ux/`, captured by
`web/scripts/shots.mjs` from the production static export:
`explore-national-hover.png`, `explore-gaps-map.png`, `explore-gaps-pinned.png`,
`explore-studio-row-hover.png`.

### 18.13 What this pass did not do, and what is still not known

- **The unmoderated usability check remains the one unmet Phase 6 criterion.** It was not
  run, not simulated and not self-administered, and it must now be run against this
  interface rather than the earlier one.
- **Several portfolio rows can carry the same place name.** A Washington portfolio of 20
  areas contains four separate cells in King County, all shown as "King County, WA". The
  rank number disambiguates them and appears in both the table and on the map marker, so
  the identity is recoverable — but the *name* alone is not unique. Adding a directional or
  neighbourhood qualifier would require a place dataset the project does not have, and
  inventing one from a centroid is exactly what §18.3 refuses to do.
- **The `near` field of the feature card is unused.** It exists for finer context that a
  future place dataset could supply; nothing populates it today, and nothing guesses.
- **Hover requires a pointer.** Keyboard and touch access to the per-cell detail was not
  built. The information is reachable in the Studio's table on any device, and on the two
  map-only views it currently is not.
- **The lens filters and the display grouping are presentation.** No exported artifact, no
  optimiser input and no published figure changes with them, which is the property that
  makes them safe to add; it also means they cannot be cited as analysis.

---

## 19. The map as a map — layer hierarchy, zoom-dependent styling, gap-category audit, and geographic navigation

This section covers a correction pass raised after manual review of the interface built in
§18. The finding was that the analytical overlay had become visually dominant enough to
erase the geography underneath it: city and place names, state borders, major roads and
coastline detail were not readable through the coloured H3 surface. A map that renders
53,208 polygons correctly and still cannot tell the reader where they are looking has
failed at being a map, which is a different failure from the WebGL defect fixed in §18.7
and is not caught by any check that existed.

Three further questions were raised in the same review: whether the Charging Gaps
categories were sparse because of a defect or by design, whether the specialised categories
should hide the rest of the gap, and how a reader is supposed to reach a particular state.

### 19.1 Item 43 — why the overlay erased the geography

**Root cause, established by reading the render configuration rather than by adjusting
opacity until it looked better.**

The deck.gl overlay was constructed in `web/components/HexMap.tsx` as:

```js
const deck = new MapboxOverlay({ interleaved: false, layers: [] });
```

`interleaved: false` gives deck.gl **its own canvas, composited over the finished basemap
canvas**. Under that arrangement there is no layer ordering to adjust: every analytical
polygon is above every basemap feature, because the two are not in the same render pass at
all. Fill opacity was the only remaining lever, and the requirement — "do not solve this by
making the analytical layer so faint that the metric becomes unreadable" — correctly rules
that lever out.

So the four candidate causes offered in the review resolve as:

| Candidate | Finding |
|---|---|
| Analytical polygons render above basemap symbol/label layers | **Yes — necessarily, and not adjustably.** Separate canvases |
| Fill opacity | 215/255 (84%). A contributing factor, not the cause |
| Polygon outline opacity | Not applicable; the layer is `stroked: false` |
| Blending behaviour | Standard alpha. Not the cause |

**The fix is the render mode, not the opacity.** The overlay is now interleaved, and the
analytical layer is inserted into the basemap's own layer stack by id:

```js
const deck = new MapboxOverlay({ interleaved: true, layers: [] });
// ...
new SolidPolygonLayer({ id: "hex6", beforeId: beforeId.current, opacity: fillOpacity, ... })
```

The insertion point was chosen by reading the published OpenFreeMap Positron style rather
than by guessing. Its 55 layers are ordered:

```
[  0] background
[  1] fill    park, water, landcover_ice_shelf, landcover_glacier,
              landuse_residential, landcover_wood
[  7] line    waterway
[  8] fill    building
[  9] line    tunnel_motorway_casing   <-- analytical surface inserted HERE
     ...      tunnels, aeroway, road_pier, highway_*, railway_*,
              boundary_3, boundary_2, boundary_disputed
[ 36] symbol  waterway_line_label ... place labels, 19 layers
```

Inserting before `tunnel_motorway_casing` produces exactly the stack the review asked for:

```
water, landcover, buildings          (below — the ground the metric sits on)
ANALYTICAL POLYGON FILL
roads, railways, state and county boundaries
place labels                         (above — always readable)
hover outline, selection, rank markers   (above everything)
```

The id is verified against the loaded style before use, because `beforeId` naming an absent
layer makes MapLibre throw:

```js
instance.on("load", () => {
  const present = instance.getStyle().layers.some((l) => l.id === ANALYTICAL_BEFORE_ID);
  beforeId.current = present ? ANALYTICAL_BEFORE_ID : null;
  if (!present) console.warn(`basemap has no layer "${ANALYTICAL_BEFORE_ID}": ...`);
```

If the basemap changes shape the overlay degrades to drawing on top — a worse map, not a
broken one, which is directive **D8** applied to presentation.

### 19.2 A second cause, found only by looking: the basemap does not draw state borders

Fixing the layer order made place labels and roads readable, and **state borders still did
not appear at national zoom**. That is not an ordering problem. Positron's boundary layer
is defined as:

```json
{ "id": "boundary_3", "type": "line", "source-layer": "boundary",
  "minzoom": 8,
  "filter": ["all", [">=", ["get","admin_level"], 3], ["<=", ["get","admin_level"], 6], ...] }
```

`minzoom: 8`. US state boundaries are `admin_level` 4, so between the national view and
city zoom — the range this product is actually read at — the basemap draws **no state
borders at all**.

The features themselves are present in the tiles well below zoom 8. Measured directly in
the running page at the default camera:

```js
map.querySourceFeatures("openmaptiles", { sourceLayer: "boundary" })
// { zoom: 3.4, levels: { "2": 6, "4": 5 }, total: 11 }
```

`admin_level: 4` features are returned at zoom 3.4. So nothing new needs fetching — only a
layer that draws them. `addStateBoundaries()` adds one against the basemap's own source,
filtered to `admin_level === 4`, capped at `maxzoom: 8` where Positron's own layer takes
over, inserted before the first label layer. **No new artifact, no new request, no new
dependency** (directive D4).

### 19.3 Item 44 — zoom-dependent styling

A single fill treatment cannot serve national through local. `analyticalOpacity(zoom)` in
`web/lib/scales.ts`:

```ts
export function analyticalOpacity(zoom: number): number {
  if (!Number.isFinite(zoom)) return 0.72;
  if (zoom <= 4) return 0.55;
  if (zoom >= 9) return 0.88;
  return 0.55 + ((zoom - 4) / 5) * (0.88 - 0.55);
}
```

| Band | Opacity | What it serves |
|---|---:|---|
| National, zoom ≤ 4 | 0.55 | Regional pattern is primary; state borders and large-city labels stay legible |
| Regional, 4–9 | 0.55 → 0.88 | Individual cells resolve while county and city context remains |
| Local, zoom ≥ 9 | 0.88 | The individual cell dominates; roads and place names still read through |

Applied as a deck.gl **layer uniform**, never baked into the colour buffer — re-expanding
370,384 vertices on a zoom change is exactly the per-frame work that cost 26 fps in §18.11.
The floor is 0.55 rather than something fainter because the instruction was explicit that
the metric must stay readable; the fix for an overpowering overlay is the layer order, not
fading the data out.

The hovered or selected cell additionally receives a ring (`PathLayer`, 2.2 px, drawn above
the fill and below the markers), so the reader can see precisely which cell the feature
card describes.

### 19.4 Items 45–47 — the Charging Gaps category audit

**This was audited before anything was redesigned, and computed independently of the
frontend** — the numbers below come from DuckDB over the published
`web/public/data/access_points.parquet` (239,780 block-group access points), not from
re-running the browser's own code.

**The exact implemented predicates**, at the default 16.1 km threshold:

| View | Predicate | Ranking | Cutoff |
|---|---|---|---|
| All gap areas | `km_to_nearest_dcfc_site > threshold`, rolled up to H3 res 6, `population > 0` for drawing | by population, no trim | none |
| Most people affected | the same gap universe | by cell population, descending | **top 100** |
| Lower-income households | the same gap universe | by `Σ population × income_share_under_35k` | **top 100** |
| Furthest from charging | the same gap universe | by population-weighted distance | **top 100** |

**The universe, measured:**

```
access points                       239,780
total population                331,449,281
gap cells at 16.1 km                 20,781
  of which populated                 20,551
  of which uninhabited                  230
gap population                   32,142,103   (9.7% of the US)
```

**Per category, as item 45 requires:**

| View | Cells | % of gap cells | Population | % of gap population | Lower-income pop |
|---|---:|---:|---:|---:|---:|
| All gaps | 20,551 | 100.00% | 32,142,103 | 100.00% | 8,644,390 |
| Most people affected | 100 | 0.49% | 1,485,137 | 4.62% | 434,460 |
| Lower-income households | 100 | 0.49% | 1,351,435 | 4.20% | 480,515 |
| Furthest from charging | 100 | 0.49% | 156,105 | **0.49%** | 33,602 |

**Set relationships:**

```
                people    equity  distance
people             100        66         0
equity              66       100         0
distance             0         0       100

union of the three specialised views       234 cells
in exactly one                             168
in exactly two                              66
in all three                                 0
```

**Cells in none of the three specialised views: 20,317 — 98.86% of populated gap cells,
holding 30,210,939 people, 94.0% of the affected population.** Their median population
(1,133) and median distance (25.2 km) are indistinguishable from the gap population as a
whole (1,138 and 25.2 km): they are not a residue of odd cells, they are the ordinary body
of the problem.

**Ties, nulls and exclusions.** No ties at any cutoff (exactly one cell sits at each of
10,433 people, 3,220 lower-income people, 150.1 km). Zero nulls in population, income
share, distance or state across all 239,780 rows. Distance range 0.01–1918.82 km, income
share 0.000–1.000 — no unit mismatch, no out-of-range value. Uninhabited cells (230) are
counted in the headline figures, which are about distance, but excluded from the map, whose
colour means people.

**Defect probes named in item 47, each checked:**

| Probe | Finding |
|---|---|
| Filtering before vs after geographic selection | Was national-only before this pass; now scoped, and tested both ways |
| Percentile using national vs state denominator | No percentiles are used; it is a top-N |
| Top-N truncation | **Present and intended: `limit: 100`. This is the cause of the sparsity** |
| `AND` where `OR` intended | Single predicate per view; no compound condition exists |
| Missing population/income fields | Zero nulls across 239,780 rows |
| Null propagation | None to propagate |
| Confidence filters | None applied on this page |
| Numeric unit mismatch, miles vs km | Kilometres throughout; range is plausible for both |
| Inequality direction | `> threshold` selects the far side; verified against the summary at five thresholds |
| Sorting followed by unintended slice | The slice is intended and is the documented rule |
| Frontend filtering vs artifact semantics | The audit above reproduces the frontend result from the artifact independently |
| H3 identifier mismatch between artifacts | **45 of 20,781 gap cells (0.22%), holding 0.13% of gap population**, have no row in the demand artifact and so cannot be named from it. They fall back to "Unnamed area". Recorded as assumption A-6.14 |
| Filters applied to already-filtered subsets | Each view ranks the full gap universe, not another view's output |
| Global vs state-local thresholds | Was global; item 51 addresses it — see §19.6 |

**Verdict, stated plainly as item 54 requires: the original sparsity was correct by design
and simultaneously a visualization problem.** There is no filtering or data bug. The
categories really are a top-100 truncation of a 20,551-area universe, and the three of them
together cover 234 areas — 1.1%. What was wrong is that the interface drew only those 100
and removed the other 20,451 from the map, so a page about a 32-million-person problem
displayed it as a hundred dots, and the word "most" was doing work no stated rule
supported.

### 19.5 Items 46 and 48 — stating the rule, and keeping the subset attached to the whole

Every view now states its own predicate with the live cutoff, for example:

> The 100 areas with the largest population beyond that distance — every highlighted area
> holds at least 10,433 people.

and carries a subset statement computed from the data being displayed:

> These **100** areas are 0.5% of the **20.6k** gap areas in the United States, and hold
> 4.6% of the affected people. The rest stay on the map in grey.

The map now draws **the entire gap universe**, with the selected view highlighted:

- other gap areas — flat desaturated grey-purple, `rgba(150,142,168,90)`;
- the selected view's areas — the full colour ramp, painted last so they sit above.

Both treatments live in one `SolidPolygonLayer` and one colour buffer, so the second
treatment costs four bytes per vertex rather than a second geometry upload. The quantile
breaks are computed over the highlighted areas only; scaling them against the whole gap
would compress the top hundred into one indistinguishable colour, which is the opposite of
what selecting the view asked for. The legend states the relationship:

> other gap areas — a much larger problem this view is a subset of

### 19.6 Items 49–52 — geographic navigation, and what selecting a state means

**Semantics: option B — analytical filtering plus visual zoom.** Chosen deliberately and
stated in the interface on both pages:

> Selecting a state narrows the estimates on this page to that state, not just the map
> view. Every figure here describes Washington.

Under option A the figures beside the map would keep describing the country while the map
showed one state, and every denominator on the page would silently mean something other
than what the reader sees.

Consistently updated on selection: the drawn cells, the demand total, the populated-area
count, the reliability tier mix, the evidence-grain breakdown, the colour scale's quantile
breaks, the gap population, the gap share, the affected lower-income population, the
neighbourhood count, the specialised view rankings, and the leading-counties line.

The scoping is applied inside the arithmetic rather than to its output, because a ratio
whose numerator and denominator describe different geographies is a wrong number:

```ts
export function gapAtThreshold(table, thresholdKm, column, stateFips?): GapSummary {
  for (let i = 0; i < table.length; i += 1) {
    if (stateFips !== undefined && states[i] !== stateFips) continue;
    const people = population[i] ?? 0;
    total += people;                       // denominator scoped too
    if ((distance[i] ?? 0) > thresholdKm) { inGap += people; ... }
```

**Item 51 — ranking scope. This was measured, and it decided the design.**

| Ranked nationally, top 100 | States represented | States that would show an EMPTY map |
|---|---:|---:|
| Most people affected | 29 of 49 | **20** |
| Lower-income households | 24 of 49 | **25** |
| Furthest from charging | **4 of 49** (Alaska 71, Montana 17, Hawaii 10, North Dakota 2) | **45** |

Washington has 262 populated gap areas and **zero** of them appear in the national hundred
furthest. A reader who selected Washington and kept a national ranking would be shown an
empty map, which is the specific failure item 51 anticipates.

**Rankings are therefore recomputed within the selected geography, and the interface says
which geography it ranked within** — the map heading reads "Most people affected in
Washington", produced by `scopedLabel()`, and "Most people affected nationally" when
nothing is selected. Washington's own hundred furthest have a 26.2 km cutoff against the
national 150.1 km, and are 38.2% of that state's gap areas rather than 0.49% — the same
control, a different and explicitly named question.

**Navigation.** Both map pages carry a `Geography` select as their first control, listing
only states the loaded artifact actually contains (built from the data, so a state with no
published cells cannot be offered), with a `Reset to U.S.` beside it. Selecting a state
fits the camera to that state's published cell extent, computed from the cells themselves
rather than from a boundary file, so the frame and the analysis describe the same set.
The distance threshold and the selected metric are preserved across a geography change.
Where the Studio covers the selected state, a hand-off appears — "Explore candidate areas
in Washington →" — carrying `?state=`, which the Studio already reads.

### 19.7 A frame-rate regression this pass introduced, caught by the gate

`perf-fps.mjs` reported **21.0 fps against the 55 fps budget**, with the basemap-only
calibration passing at 60.0 fps — so, unlike the episode in §18.11, the harness itself
established immediately that the environment was sound and the code was not.

**The obvious suspects were both wrong, and were eliminated by measurement rather than by
reasoning:**

| Isolation | Sustained |
|---|---:|
| Full change as written | 21.0 fps |
| Interleaved, state-boundary layer removed | 21.4 fps |
| **Overlay mode restored (`interleaved: false`)**, boundaries present | **21.4 fps** |

Neither the new render mode nor the new boundary layer was responsible.

**The actual cause.** The binary payload was constructed inline inside the layer-building
effect:

```js
new SolidPolygonLayer({
  id: "hex6",
  data: { length, startIndices, attributes: { getPolygon: {...}, getFillColor: {...} } },
```

That object's **identity** is what deck.gl diffs to decide whether to re-upload 370,384
vertices and a 1.48 MB colour buffer. Building it inline made every layer rebuild a full
GPU upload. That was harmless while the effect only re-ran when the buffers themselves
changed — and became a defect the moment `fillOpacity`, which varies continuously with
zoom, entered the same effect's dependencies. A routine zoom then re-uploaded the entire
national surface.

The payload is now memoised on the buffers:

```js
const binary = useMemo(() => { ... }, [boundaries, colors]);
```

so a rebuild for opacity, outline or picking reuses the identical reference and deck.gl
skips the upload. **60.0 fps sustained, p50/p95/p99 frame time 16.7/16.7/16.8 ms** — one
frame per vsync, matching the baseline exactly.

This is the second regression in this area from the same underlying shape: work that is
cheap when a dependency is stable becomes per-interaction work when a new dependency is
added. The fix applied here is the general one — the expensive payload is now stable by
construction, so future props can be added to that effect without re-introducing it.

### 19.7b Interleaved rendering broke the rendering regression check, twice

The gate failed after the layer-order change, in the check added under **I-29** to prove
the analytical layer is visibly drawn. Both failures were real consequences of interleaving
and neither was worked around.

**First: the check assumed two canvases.** In overlay mode deck.gl has its own canvas
stacked over MapLibre's, and the check screenshotted `canvas[1]`. Interleaved, deck.gl
draws into MapLibre's canvas and creates none of its own, so the wait condition
(`canvas.length >= 2`) timed out silently and the next line crashed on `undefined`. The
check now waits for at least one canvas and measures the largest, which is the map in
either mode — in overlay mode the two were the same size and stacked, so the compared
region is unchanged.

**Second, and more serious: `Page.captureScreenshot` becomes unusable.** Measured on this
machine, same page, same viewport:

| Page | Cells drawn | `Page.captureScreenshot` |
|---|---:|---:|
| `?resolution=native` | 52,912 | **208,775 ms** |
| `?resolution=native&layer=off` | 0 | 102 ms |
| default (display aggregation) | 4,012 | 94 ms |

Two thousand times slower, and only with the interleaved layer at full resolution. The
map itself is not slow — the same page sustains 60.0 fps with p99 frame time 16.8 ms — so
this is specific to Chrome's screenshot path re-rendering a large custom layer inside
MapLibre's render pass.

**Resolution: read the drawing buffer directly.** A `?preserve=1` test affordance — the
third, alongside the existing `?layer=off` and `?resolution=native` — asks MapLibre for a
context whose drawing buffer survives the frame:

```ts
canvasContextAttributes: {
  preserveDrawingBuffer:
    new URLSearchParams(window.location.search).get("preserve") === "1",
},
```

The check then reads `canvas.toDataURL("image/png")`: **38 ms**, identical pixels. The flag
is off in production, because preserving the buffer costs memory bandwidth on every frame
and the §11.3 frame-rate budget is measured without it.

**The check was not weakened, and this was verified rather than asserted.** Its thresholds
are unchanged (≥2% of pixels changed, ≥20% of those carrying the layer palette), and it was
re-tested against a deliberately near-invisible layer (`opacity: 0.02`):

```
rendered difference: 51,416 of 897,820 pixels changed (5.73%), threshold 2%
of those, 0.0% carry the layer's palette (threshold 20%)
FAIL: only 0.0% of the changed pixels carry the layer's palette. The layer is drawing
geometry but not its colours - the symptom of a colour-attribute defect...
```

Note that 5.73% of pixels still changed with the layer effectively invisible, which is
exactly why the palette assertion was added under I-29 and why a pixel count alone is not
sufficient evidence of rendering.

**Passing figures after the change: 54,947 of 897,820 pixels changed (6.12%), of which
94.3% carry the palette.** Against the previous run's 10.00% and 69.9%: fewer pixels change
because the fill is now 0.55 opaque at national zoom with roads and labels punching through
it, and a higher share of what does change is pure palette because the fill no longer sits
on top of grey basemap linework.

### 19.8 Item 53 — the map reviewed as a map

Checked at national (zoom 3.4), state (6.2) and local (9.5) zoom on both map pages, against
the screenshots listed in §19.9.

| Question | Before | After |
|---|---|---|
| Can I read important city labels? | No — washed out at every zoom | Yes. At national: Seattle, Portland, Denver, Chicago, Dallas, Houston, Atlanta, Miami, New York, Boston. At local: Seattle, Bellevue, Renton, Kirkland, Bremerton |
| Can I identify state boundaries? | No | Yes, at every zoom — added, since the basemap gates its own at zoom 8 |
| Can I understand which state or county I am in? | Only by hovering | Yes: labels, borders, the map heading, and the hover card |
| Can I distinguish analytical colour from basemap geography? | Poorly | Yes — the basemap is grey, the surface is the viridis ramp, and geography draws above it |
| Can I identify the hovered or selected feature? | Card only | Card plus a ring drawn on the cell |
| Can I understand what blank space means? | Legend | Legend, unchanged: "no estimate — nobody lives here" |
| Can I see what changed after selecting a filter? | No — the rest of the gap vanished | Yes — the context remains in grey and the subset line quantifies the change |
| Can I return to the national context easily? | No control existed | `Reset to U.S.` |

**Major roads at local zoom are the clearest single demonstration.** In
`geo-before-demand-local.png` neither I-5 nor I-405 is visible anywhere in the Seattle
metro; in `geo-demand-local.png` both are crisp white lines through the surface.

### 19.9 Item 54 — evidence

Screenshots in `docs/evidence/ux/`, captured by `web/scripts/shots-geo.mjs` from the
production static export at 1440×900 on the host GPU. The "before" images were produced by
building commit `011528c` in a separate git worktree against the identical published data,
so the comparison is of two builds and not of two descriptions:

| File | What it shows |
|---|---|
| `geo-before-demand-national.png` | Before: national, labels washed out |
| `geo-before-demand-local.png` | Before: Seattle at zoom 9.5 — **no roads visible at all** |
| `geo-before-gaps-people.png` | Before: 100 dots, the rest of the gap absent |
| `geo-demand-national.png` | After: national, city labels and state borders readable |
| `geo-demand-state.png` | After: Washington at zoom 6.2 |
| `geo-demand-local.png` | After: Seattle at zoom 9.5, highways and place names through the surface |
| `geo-demand-washington.png` | U.S. → Washington |
| `geo-demand-texas.png` | Washington → Texas |
| `geo-demand-reset.png` | Reset to national |
| `geo-gaps-all.png` | The whole gap universe |
| `geo-gaps-people-national.png` | Highlighted subset over grey context, nationally |
| `geo-gaps-people-washington.png` | The same view scoped to Washington |

**Drawn-cell counts through the state-filter sequence**, read from `__voltgapLayerCells`
during the capture run, confirming the filter changes the analysis and not only the camera:

```
United States -> Washington -> Texas -> reset
   4,012            401        1,303      4,012      (display-aggregated parents)
```

**Three interface defects found by looking at the screenshots, and fixed:**

1. **Raw FIPS codes leaked as place names.** The gaps summary read "Mostly in Texas
   (195.3k), 39 (139.9k), 20 (121.8k), 22 (119.2k)" — `lib/data/states.ts` covers only the
   six states the frontier publishes, so every other FIPS fell through to its digits. Now
   resolved through `nameByFips()`, built from the loaded artifact, covering all 51.
2. **The geography select collapsed to a chevron** when a state was selected, because the
   `Reset to U.S.` label out-competed it for flex width.
3. **A denominator label contradicted its own number.** With Washington selected the page
   showed "5.6% — of the US population". The figure was correctly state-scoped; the label
   was not. Now "of Washington's population". This is precisely the mismatch item 50 warns
   about, and it survived until a screenshot was read.

A fourth was found in the demand view: the map heading said "Highest here:" while listing
the leaders of the whole selected geography, so zoomed into Seattle it named three
California counties. It now reads "Highest in the United States:" or "Highest in
Washington:", matching what it computes.

### 19.10 Tests added

`web/tests/geography.test.ts` (18 tests) and additions to `web/tests/access.test.ts`
(bringing it to 35), run against the 4,000-point real published fixture:

- the control offers only geographies present in the data; a FIPS with no nameable code is
  skipped rather than shown as a bare number;
- state parts sum exactly to the national whole at 16.1 km;
- a state-scoped summary equals the national result restricted to that state;
- **the share's denominator is scoped too** — asserted as equal to the state's own
  population, with an explicit assertion that it differs from the national share, so a
  future change that scoped only the numerator would fail rather than silently pass;
- the specialised views select exactly the top N, and nothing outside beats the cutoff;
- the context set is retained, not deleted, and context plus highlighted equals the whole;
- no nulls, no negative distances, income share within [0, 1];
- zoom-dependent opacity is monotonic between anchors, never below 0.55, never above 0.88,
  and degrades to a usable value on a non-finite zoom.

### 19.11 What this pass did not do

- **No model, threshold, objective, candidate rule, uncertainty component or validation
  result changed.** The state filter and the display grouping are presentation and
  selection over published quantities; the specialised views sort and trim columns that are
  in the data dictionary. No new score exists, hidden or otherwise.
- **The unmoderated usability check remains the one unmet Phase 6 criterion (A-6.4).** It
  was not run and must be run against this interface.
- **State outlines come from the basemap's vector tiles, not from a project artifact.**
  They are cartographic context, and no analysis depends on them. If OpenFreeMap stops
  serving the `boundary` source layer they disappear and the map degrades; nothing computed
  changes.
- **Hover and the ring remain pointer interactions** (A-6.13, still open). The geography
  select is keyboard-reachable; the per-cell detail on the two map-only views is not.
- **45 gap cells cannot be named** and read "Unnamed area" (A-6.14).
- **The three specialised views are still a top-100 truncation.** That was found to be
  correct by design and is now stated rather than implied; it is not a claim that 100 is
  the right number, and no evidence here establishes that it is.

### 19.12 Gate evidence — `make gate PHASE=6`, 2026-09-06

```
--- 1. lint (ruff + mypy strict + frontend typecheck) ---
ruff: All checks passed!
mypy: Success: no issues found in 148 source files

--- 2+3. full test suite under coverage, and coverage thresholds ---
repository wide                        6270 stmts  0 miss  1482 branch  100%
model 100%   spatial 100%   validation 100%   quality 100%   schemas 100%
discovery 100%   export 100%   sources 100%   transform 100%

--- 4. prior-phase gate suites replayed (Phase 0 through 5) ---
  test_source_findings.py   PASS 23     test_domain_rules.py         PASS 39
  test_phase2_gates.py      PASS 37     test_phase3_gates.py         PASS 20
  test_phase3_corrections.py PASS 32    test_phase4_gates.py         PASS 23
  test_phase5_gates.py      PASS 33     test_gate_protocol.py        PASS 91
  test_smoke_forward.py     PASS 11     ...phase2 5  ...phase3 5
  ...phase4 5               ...phase5 7

--- 6. D3 copy lint (source and frontend) ---
copy lint: clean (235 files, 15 rules)

--- 7. determinism (semantic, CLAUDE.md 14.1) ---
determinism: identical

--- frontend ---
124 tests passed (8 files)          [was 88; +18 geography, +18 access]
slowest greedy re-solve   0.0235 s   (budget 2.0 s)
PASS: app shell 229.4 KB of 600.0 KB (38.2% of budget)
  rendered difference: 54,947 of 897,820 pixels changed (6.12%), threshold 2%
  of those, 94.3% carry the layer's palette (threshold 20%)
PASS: the analytical layer is visibly rendered
PASS: the interface reads correctly to someone who knows nothing about it

--- environment-dependent class: reference-environment hard gate ---
  run 1/5  TTI 2.86s   run 2/5  2.91s   run 3/5  2.93s
  run 4/5  2.93s       run 5/5  2.92s
  Machine validity: median benchmarkIndex 4147 (floor 3500)
  median TTI 2.92 s (budget 3.0 s)
  median FCP 0.20 s   LCP 2.64 s   TBT 297 ms   CLS 0.031   SI 1.41 s
PASS: Time to Interactive 2.92 s of 3.0 s (97.4% of budget)

  cells in the rendered layer: 52,912
  colour buffer: 1,481,536 bytes for 370,384 vertices (per-vertex, correct)
  machine validity: basemap-only calibration 60.0 fps sustained (floor 55)
PASS: sustained 60.0 fps against a 55 fps budget

=== Phase 6 gate: PASS ===
```

**Movement against the §18.12 run, and why.** The app shell grew 225.8 → 229.4 KB (3.6 KB,
38.2% of budget) for the geography module, the state-boundary layer and the new controls.
Largest Contentful Paint rose 1.61 → 2.64 s: the largest painted element is now the map
surface itself, which paints later and larger than the sidebar text that previously held
the title. TTI, the gated metric, is unchanged within noise (2.91 → 2.92 s), and the frame
rate is unchanged at the vsync ceiling. The rendering-check figures moved as explained in
§19.7b. Greedy re-solve improved 0.0334 → 0.0235 s; nothing in this pass touched the
solver, so that is machine variance on a measurement with two orders of magnitude of
headroom.

### 19.13 Two gaps in the §19 pass, closed — 2026-09-06

A status review of §19 against items 43–54 found two places where the work was reported as
done but was only partly done. Both are now closed. Recorded here as a new section rather
than by editing §19.9 and §19.11, so the earlier claim and its correction both stay
visible.

**Gap 1 — item 52's "click a location, zoom to that area" was only implemented in the
Studio.** The `focus` camera prop existed on `HexMap` and the Siting Studio used it for row
and marker clicks, but the EV Demand and Charging Gaps maps were never wired to it: clicking
a cell pinned its card and moved nothing.

Both map pages now carry a **Zoom to this area** action in the pinned card, beside the
existing hand-off to the Studio. Verified in the built export rather than asserted:

```
national: button=true  zoom 3.40 -> 8.00, centre moved 3.53 deg
gaps:     button=true  zoom 3.40 -> 8.00, centre moved 3.53 deg
```

It centres and never zooms out (`Math.max(zoom, 8)`), because a reader who is already close
is asking to centre, not to be pulled back to a fixed level. The selected geography, metric,
distance threshold and view are all left untouched — confirmed in
`geo-gaps-zoom-to-area.png`, which shows the map at a Colorado/Kansas border area with
"United States", 16.1 km and "All gap areas" still set.

**One consequence, stated rather than hidden: the card closes when the zoom changes the
display grouping.** Pins are held by index into the drawn set, and a zoom that regroups
areas would leave that index pointing at a *different* cell. Clearing it is the existing
guard against showing the reader the wrong area's numbers, and it is the right trade;
carrying a pin across a regrouping would need pinning by H3 index instead, which is a
change to the pinning model and not part of this correction.

**Gap 2 — item 47's tests ran against the fixture, not the published artifact.** The audit
figures in §19.4 came from a one-off DuckDB query. The committed regressions in
`web/tests/access.test.ts` recompute independently of the browser's helpers, but over the
4,000-point fixture, so a change to the *artifact* would not have re-verified any published
count.

Seven tests are now in `tests/regression/test_phase6_gates.py`, reading the shipped
239,780-point `access_points.parquet` and re-deriving the quantities in SQL:

| Test | Locks |
|---|---|
| `test_p6_h_the_gap_universe_matches_the_figures_the_report_publishes` | 20,781 gap cells, 20,551 populated, 230 uninhabited, 32,142,103 people |
| `test_p6_h_each_specialised_view_is_the_documented_top_n` (×3) | 100 cells and the exact population of each view, plus that nothing outside beats the cutoff |
| `test_p6_h_the_specialised_views_are_a_small_subset_of_a_much_larger_gap` | union 234, people ∩ equity 66, distance disjoint from both, 20,317 uncovered, >98% of cells and >93% of population outside all three |
| `test_p6_h_a_national_ranking_would_leave_most_states_with_an_empty_map` | 49 states in the gap, 4 in the national furthest hundred, Washington's 262 areas and its absence from that hundred |
| `test_p6_h_no_gap_point_carries_a_null_that_could_silently_drop_a_cell` | zero nulls, no negative distance, income share within [0, 1] |

Asserting each view's **population** and not only its count is what makes these checks on
the *ranking* rather than on the slice: any list trimmed to 100 has 100 entries, but only
the correct ordering has that population. The `test_p6_h_a_national_ranking...` test exists
so that if the fact underpinning §19.6's design decision ever stops holding, the reasoning
is revisited rather than silently surviving in the report.

### 19.14 Gate evidence for §19.13 — `make gate PHASE=6`, 2026-09-06

```
ruff: All checks passed!    mypy: Success: no issues found in 148 source files
repository wide                    6270 stmts  0 miss  1482 branch  100%
model / spatial / validation / quality / schemas / discovery / export /
sources / transform                                            all 100%

prior-phase gate suites replayed (Phase 0 through 5): 13 suites, all PASS
  source_findings 23   domain_rules 39   phase2 37   phase3 20
  phase3_corrections 32   phase4 23   phase5 33   gate_protocol 91
  smoke_forward 11 / 5 / 5 / 5 / 7

Phase 6 acceptance criteria:  26 passed   [was 19; +7 published-artifact gap tests]
copy lint: clean (235 files, 15 rules)
determinism: identical

frontend:                    124 tests passed (8 files)
slowest greedy re-solve      0.0288 s  (budget 2.0 s)
PASS: app shell 229.6 KB of 600.0 KB (38.3% of budget)
  rendered difference: 54,947 of 897,820 pixels changed (6.12%), threshold 2%
  of those, 94.3% carry the layer's palette (threshold 20%)
PASS: the analytical layer is visibly rendered
PASS: the interface reads correctly to someone who knows nothing about it

Machine validity: median benchmarkIndex 4135 (floor 3500)
  median TTI 2.94 s (budget 3.0 s)
  median FCP 0.20 s  LCP 2.66 s  TBT 303 ms  CLS 0.031  SI 1.42 s
PASS: Time to Interactive 2.94 s of 3.0 s (98.0% of budget)

  cells in the rendered layer: 52,912
  machine validity: basemap-only calibration 58.9 fps sustained (floor 55)
  frame time p50 / p95 / p99   16.7 / 16.8 / 16.8 ms
PASS: sustained 60.0 fps against a 55 fps budget

=== Phase 6 gate: PASS ===
```

**Two gate runs preceded this one and neither is reported as a pass.**

The first failed `mypy --strict` on the new tests themselves: `tests/regression/
test_phase6_gates.py:282: Unsupported operand types for <= ("str" and "float")`. Indexing a
`tuple[str, float, float, float, str]` with a variable makes every field the union of all
of them. The tests passed `pytest` and had not been run through the linter, which is the
author's process error, not a tooling gap — the gate caught it, and the fix (a `NamedTuple`
plus a `RANKED_BY` map of typed accessors) also made the ranking tests say which column
they rank by instead of writing `c[1]`, `c[2]`, `c[3]`.

The second failed on the environment, and is recorded because it identifies a real property
of this reference machine:

```
NOT MEASURED: median Lighthouse benchmarkIndex 2190 is below the 3500 floor for this
reference environment (quiescent range 4032-4136), so the machine was contended.
```

**Cause: the repository sits on the macOS Desktop with iCloud "Desktop & Documents" sync
enabled.** `~/Library/Mobile Documents/com~apple~CloudDocs/Desktop` exists,
`fileproviderd` was measured at 18.5% CPU with `bird` at 3%, and `brctl status` hung. A gate
run writes ~12 MB of parquet artifacts, a full Next build, twelve screenshots and coverage
data, iCloud begins uploading them, and the performance benchmarks — which run at the end of
that same gate — execute straight into the sync the gate itself triggered. **The gate
contends with itself.**

Re-measured once the sync drained, with the machine otherwise in normal interactive use
(browser and chat applications open): median `benchmarkIndex` **4135**, inside the
documented quiescent range, TTI 2.94 s. So the 2190 was the sync burst and not a property
of the hardware.

Two things this establishes, both worth carrying forward:

1. **The layered guards work, and a single one would not have.** `perf-settle` passed — load
   was under its 0.6/core target — and the `benchmarkIndex` floor still caught the
   contention. Assumption **A-6.9** is the reason a wrong number was not published.
2. **Normal interactive use does not invalidate a measurement on this machine; a large
   iCloud sync does.** An attempt to wait for one-minute load below 1.2 would have waited
   indefinitely, because the desktop applications alone hold it near 6. The load target is
   not the arbiter; `benchmarkIndex` is.

Recorded as assumption **A-6.17**.

## Release candidate — scope freeze, 2026-09-07

Three deliverables, no new analytical behaviour: the plain-language entry point was
rewritten, a full Methodology & Architecture page was built, and the repository was audited
and prepared for manual deployment. No model, threshold, objective, candidate rule,
uncertainty component or validation result changed.

### 20.1 The deployment blocker, which was real

`web/public/data/` — every file the browser fetches — was git-ignored. Measured:

```
$ git archive HEAD | tar -t | grep -c '^web/public/'
0
```

A clean clone contained **no runtime data at all**. A static host would have cloned,
installed, built successfully, exported every route, and served an application whose every
data fetch returned 404, with **nothing failing in the build log**. It survived because
local development and the gate both run `make artifacts` first, so the directory was always
populated on any machine that had ever run the pipeline. A build host has not.

The artifacts are now committed: **11 MB across 10 files, largest 7.07 MB**. Object storage
was considered and rejected at this size — it would add a bucket, a CORS policy and an
environment variable to misconfigure in exchange for nothing, and committing guarantees the
deployed site serves byte-for-byte what the gate verified.

Verified by extracting the committed tree to an empty directory and running
`npm ci && npm run build` with no pipeline and no source cache present: `out/data/` came
out fully populated, 17 MB export.

### 20.2 The test that forbade this was replaced, not deleted

`test_the_generated_artifacts_are_not_committed` asserted the opposite policy, reasoning
that *"committing them would make a stale copy indistinguishable from a fresh build."*

That concern is correct, and deleting the test would have discarded a real guarantee to let
a change pass. But git-ignoring never actually **detected** staleness — it avoided the
question, at the cost of an empty deployment.

The guarantee is now enforced instead. The gate rebuilds artifacts before the test runs, so
a stale committed copy is overwritten and the comparison fails. Comparison is **semantic**,
exactly as §14.1 defines determinism: `solve_seconds` and `computed_at` are wall-clock facts
about when a run happened, not about what the data are.

Measured before writing it: the parquet files are **byte-identical** across rebuilds; only
timings and the build timestamp move.

The new test was initially **vacuous** — nothing was in `HEAD` yet, so every file hit its
`continue` branch and it passed while proving nothing. Verified after committing, one
mutation at a time:

| Mutation | Expected | Result |
|---|---|---|
| `demand_covered` changed on a frontier point | FAIL | **FAIL**, naming `Vermont.json` |
| `solve_seconds` changed, nothing else | PASS | **PASS** |
| One byte flipped in `sites.parquet` | FAIL | **FAIL**, naming `sites.parquet` |

### 20.3 A second defect: the freshness indicator was not truthful

Past its threshold the interface would have said **"The scheduled refresh may have
stopped"** — asserting an automation this release does not have, and it would have started
saying so on the fourteenth day after publication. Separately, "Data refreshed today"
conflated *artifacts built* with *data refreshed*, when the registration and census inputs
are considerably older and carry their own vintages in the manifest.

Both corrected. A test now asserts neither claim can return in either branch of the
threshold.

### 20.4 Gate evidence — `make gate PHASE=6`, 2026-09-07

```
ruff: All checks passed!    mypy: Success: no issues found in 148 source files
repository wide                    6270 stmts  0 miss  1482 branch  100%
all nine result-computing packages                                   100%
prior-phase gate suites (Phase 0-5): 13 suites, all PASS
Phase 6 acceptance criteria:  27 passed
copy lint: clean (239 files, 15 rules)      determinism: identical
frontend:  125 tests passed
slowest greedy re-solve   0.0291 s  (budget 2.0 s)
PASS: app shell 230.6 KB of 600.0 KB (38.4% of budget)
  rendered difference 6.12%, of which 94.3% carry the layer's palette
PASS: the analytical layer is visibly rendered
PASS: the interface reads correctly to someone who knows nothing about it
PASS: Time to Interactive 2.99 s of 3.0 s (99.7% of budget)
PASS: sustained 60.0 fps against a 55 fps budget
=== Phase 6 gate: PASS ===
```

### 20.5 The interactivity budget is effectively exhausted

The gate passed, and this figure should not be read as comfortable. Median TTI is
**2.99 s against 3.0 s — 0.01 s of headroom**, and the five runs behind that median were:

```
3.00 s   3.09 s   2.99 s   2.95 s   2.95 s     benchmarkIndex 4120-4145
```

**Two of the five individual runs exceeded the budget.** The median is what §11.3 gates on
and the median passed, so this is a pass rather than a failure — but it is a pass by
0.3%, and the machine was demonstrably valid throughout (the benchmark index sat inside the
documented quiescent range of 4032–4136 on every run, so contention does not explain it).

The trajectory across this phase is one direction only:

| | TTI | Shell |
|---|---:|---:|
| After the worker optimization | 2.84 s | 218.9 KB |
| After the map-explorability pass | 2.91 s | 225.8 KB |
| After the geography-legibility pass | 2.94 s | 229.6 KB |
| **This release** | **2.99 s** | **230.6 KB** |

The shell grew 11.7 KB across the phase and TTI grew 0.15 s. The next feature of any size
will breach the budget on the median, not merely on individual runs.

This is stated rather than absorbed because the honest reading is that **the budget is
spent, not that there is room**. Recorded as assumption **A-6.18**. No threshold was
relaxed and no measurement was re-run to obtain a better number — the first five-run median
is the reported one.
