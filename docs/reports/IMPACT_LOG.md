# Impact log

Records every instance where a later phase invalidates an earlier one, per the
cross-phase impact protocol in CLAUDE.md §15.3.

Severity: **S1 Blocking** (an earlier phase's published output is wrong and downstream
results are invalid), **S2 Degrading** (usable but weaker than claimed), **S3 Cosmetic**
(documentation, naming or presentation only).

---

## Open entries

None.

### I-18 — the §7.8 road-proximity filter was omitted on a false premise

| Field | Value |
|---|---|
| Opened | 2026-08-31, external review of the Phase 4 submission |
| Affected phase | 4 (`pipeline/model/siting.py`, `docs/reports/PHASE_4_REPORT.md`) |
| Severity | **S1 Blocking** — the published candidate universe omitted a filter the specification mandates, so every candidate set, frontier point and optimality gap in the first submission was computed over the wrong universe |
| Status | **RESOLVED 2026-08-31** |

**Assumed.** That no road-network dataset was available to the project, and that
explicitly degrading — substituting a resident-population filter and labelling it a
degradation under D8 — was therefore the correct response. Recorded as assumption A-4.1.

**Actually true.** The premise was wrong. The Census Bureau publishes TIGER/Line
`PRISECROADS`, one zipped shapefile of primary and secondary roads per state, free,
keyless and on the same host as the TIGER tract and block products the pipeline already
retrieves. D8 governs what to do when a source is genuinely unavailable; it does not
license omitting a mandatory filter when the source exists and was not looked for.
Separately, resident population is not a road proxy in either direction: an uninhabited
cell can sit on an interstate, and an inhabited one can be far from any arterial.

**Evidence.** `https://www2.census.gov/geo/tiger/TIGER2024/PRISECROADS/tl_2024_53_prisecroads.zip`
retrieves 3,006 Washington features carrying 376,007 vertices — 2,800 MTFCC `S1200`
(secondary) and 206 `S1100` (primary).

**What was wrong in the published output.** Candidate counts in all six frontier states,
and therefore every downstream number:

| State | Published (no road filter) | Corrected | Removed |
|---|---:|---:|---:|
| Washington | 856 | **674** | −182 |
| Tennessee | 1,479 | **1,425** | −54 |
| Montana | 400 | **297** | −103 |
| Vermont | 258 | **250** | −8 |
| Texas | 3,073 | **2,417** | −656 |
| California | 1,611 | **1,253** | −358 |

The frontier, the greedy portfolios and the empirical optimality gaps all moved with them:
the worst measured gap changed from 3.06% to **3.14%**, and the slowest greedy solve from
0.0288 s to **0.0229 s** on the smaller candidate sets.

**Response taken.** The threshold, road classes and distance method were pre-registered in
`docs/evidence/P4-0_road_filter_preregistration.md` **before** any result was recomputed,
so none could be chosen after seeing which value gave a convenient answer. New modules
`pipeline/sources/tiger_roads.py` and `pipeline/spatial/road_proximity.py` ship the source
and the measurement; `build_candidates` now **raises** without road distances rather than
passing every cell through, and degraded mode must be requested explicitly and is counted
in the published artifact. Assumption A-4.1 is withdrawn and closed; A-4.6 (vertex versus
segment distance) and A-4.7 (road-class choice) are opened in its place. A dated
correction is appended to `docs/reports/PHASE_4_REPORT.md`. The full Phase 4 gate and all
prior gates were re-run.

---

### I-19 — A-2.1 was closed by a geometric argument, not by a measurement

| Field | Value |
|---|---|
| Opened | 2026-08-31, external review of the Phase 4 submission |
| Affected phase | 4 (`docs/reports/ASSUMPTION_LEDGER.md`, `docs/reports/PHASE_4_REPORT.md`) |
| Severity | **S2 Degrading** — the conclusion turned out to be right, but it was asserted rather than shown, so the assumption was not in fact resolved |
| Status | **RESOLVED 2026-08-31** |

**Assumed.** That the ratio of the largest DBSCAN cluster diameter (500 m) to the H3
resolution-6 cell edge (3,834 m) — 13.0% — established that station clustering does not
materially distort candidate siting.

**Actually true.** It does not. The ratio establishes that a cluster is small relative to a
cell. It says nothing about whether a cluster straddling a cell boundary changes a cell's
saturation classification, its candidate status, or the portfolio selected from it. A
boundary effect does not scale with the ratio of the object to the cell; it depends on
where the boundary falls.

**Response taken.** The argument is withdrawn. `pipeline/model/clustering_sensitivity.py`
now runs three conditions per state — shipped (no clustering), DBSCAN eps 50 m, DBSCAN eps
200 m — and reports candidate-set Jaccard, saturation reclassifications, portfolio overlap
at 5, 20 and 50 sites, and the demand and equity objective deltas.

**What the measurement found.** At the shipped Phase 1 configuration (**eps 50 m**) the
effect is **exactly zero in all six states**: Jaccard 1.000, zero saturation
reclassifications. At a deliberately coarser **eps 200 m**, two states move — Washington
reclassifies 1 cell (Jaccard 0.998519), Texas 2 (0.999173) — and **no portfolio changes at
any budget in any state**: overlap 1.000 at every budget, demand and equity deltas exactly
0.00. A-2.1 is resolved, now on evidence.

---

### I-17 — zero-by-absence was assumed, and gated by a test that could not establish it

| Field | Value |
|---|---|
| Opened | 2026-08-31, external review |
| Affected phase | 3 (`pipeline/model/precedence.py`, `pipeline/model/observed.py`) |
| Severity | **S3 Cosmetic** — the 15 published zeros were correct, but the reasoning behind them did not hold and the gate protecting them tested the wrong thing |
| Status | **RESOLVED 2026-08-31** |

**Assumed.** Two things, neither established. First, that a tract with no source row holds
zero (assumption A-3.13). Second, that agreement with the AFDC total within 10% showed the
source was complete enough to license that.

**Actually true.** Neither followed. Absence of a row means zero only if every
in-jurisdiction record was actually placed — otherwise an unplaced vehicle might belong to
the absent tract. And external agreement establishes completeness in neither direction: a
source can agree closely while omitting a region, or disagree widely while being exhaustive
over a differently-defined population.

**What the investigation found.** The claim happens to be **true**, and is now proven:
236,994 BEV records carry `state == 'WA'` and all 236,994 are placed in a valid in-state
Census tract; the 573 unplaced records are all non-WA-addressed, with **zero** null
jurisdictions. The eight null-tract rows that first looked like unresolved records carry
non-Washington states (BC, QC, AE, NH). `unresolved_in_jurisdiction = 0`.

**Response.** A published `GeographyResolution` ledger per native source. Completeness
rebuilt on declared publisher scope plus explicit record and geography accounting, with
external agreement demoted to a reported diagnostic that gates nothing. A separate
**zero-completion licence** requiring `unresolved_in_jurisdiction == 0`, and superseding
now requires it — a source that cannot place every record falls back entirely rather than
needing an invented residual. A `value_provenance` field distinguishes
`native_registry_zero_by_absence` from a modelled value and from an observed count.

**No published number changed.** National total remains 5,616,923; the 15 zeros remain
zero, now on proof rather than assumption.

### I-16 — the published surface stopped reconciling to its own constraints

| Field | Value |
|---|---|
| Opened | 2026-08-31, external review of the corrected national accounting |
| Affected phase | 3 (`pipeline/model/build_demand.py`) |
| Severity | **S2 Degrading** — the national and Washington figures were defensible numbers, but the surface violated the exact-reconciliation contract it claimed to satisfy |
| Status | **RESOLVED 2026-08-31** |

**Assumed.** That publishing a directly observed tract count in place of a modelled one,
*after* reconciliation, was a harmless improvement — the observation is better evidence
than the estimate, so substituting it can only help.

**Actually true.** It left the surface reconciled to one set of totals and then altered so
it no longer summed to them. Washington published **237,011.0328** against a stated
operative constraint of **236,400**: a **+611.0328** term sitting outside the constraint
system with no authority behind it. CLAUDE.md's exact-reconciliation contract is not
satisfied by a number that is merely defensible; it requires the published surface to
equal the totals it reconciles to.

**The decomposition, proven rather than assumed.** Walking every tract and grouping the
observed-minus-displaced difference by state produced **exactly one contributing state**:
Washington, 1,769 tracts, observed 236,994.0000 against displaced 236,382.9672. Every
other jurisdiction contributed zero.

**Root cause.** Precedence was being applied at the wrong point in the pipeline. Deciding
that observed tract counts outrank an external state total is correct; applying that
decision *after* reconciliation instead of *as a constraint* is what broke the identity.

**Response.** An explicit, ordered, testable precedence policy
(`pipeline/model/precedence.py`): `native tract registry > county observations > external
state total`. Observed values now enter as constraints **before** reconciliation, so they
sit inside the system. Superseding is earned against four checked conditions - tract
grain, balanced ledger, containment in the jurisdiction, and agreement with the external
total within 10% - so a partial extract cannot silently become a constraint. Superseded
totals are kept as provenance and never summed. Each jurisdiction publishes its chosen
source, vintage, total and precedence reason.

Result: `national == sum(chosen authoritative constraints)` with **exactly zero**
imbalance, no substitution term, and a per-jurisdiction identity checked on every build.
National 5,616,940.0328 → **5,616,923.0000**; Washington 237,011.0328 → **236,994.0000**;
no other jurisdiction moved.

**This does not change I-15**, which remains correct and separately tested: Montana and
Virginia have *partial* county coverage, so their counties still decompose the state total
rather than superseding it.

**A negative test guards the regression.** `test_a_poisoned_post_reconciliation_substitution_is_caught`
injects a +611.0328 alteration and requires the per-jurisdiction identity to fail.

### I-15 — partial county coverage double counted two states

| Field | Value |
|---|---|
| Opened | 2026-08-31, during the external-review audit of the national total |
| Affected phase | 3 (`pipeline/model/build_demand.py`) |
| Severity | **S1 Blocking** — a published national output was wrong by 138,749 vehicles, about **2.5%** of the national total, and two states' tract estimates were roughly doubled |
| Status | **RESOLVED 2026-08-31**, before the surface reached any downstream phase |

**Assumed.** That "reconcile to county totals where they exist, else to the state total"
partitions a state's tracts cleanly.

**Actually true.** It does only when county coverage is **complete**. Where a state's DMV
reports *some* of its counties, the remaining tracts fall through to a group keyed by the
state whose total was the **full state total** — which the observed counties had already
claimed. Both were then counted:

| State | Counties observed | Published before | Should be |
|---|---|---:|---:|
| Montana | 51 of 56 | **13,673** | 6,900 |
| Virginia | 129 of 133 | **266,876** | 134,900 |
| Tennessee | 95 of 95 (complete) | 53,029 | 53,029 — unaffected |

National estimate before **5,755,689**, after **5,616,940**: an overstatement of
**138,749**. Every Montana and Virginia tract outside an observed county carried roughly
twice the demand it should have.

**How it surfaced.** External review asked for an exact accounting of a **two-vehicle**
national difference between ACS vintages, refusing "floating-point noise" as an answer
when the reconciliation residual is 2.3e-10. Building that accounting showed the national
total exceeding the sum of its constraints by 141,816, and the per-state breakdown named
Montana and Virginia immediately. **The two-vehicle question found a 138,749-vehicle
defect.**

**Why the existing checks missed it.** `ProportionalReconciler` was working perfectly:
every constraint was satisfied exactly, the residual really was 2.3e-10, and no constraint
overlapped another — the tracts *were* partitioned. The defect was in the **totals handed
to it**, not in the reconciliation. `_check_partition` verifies that no area is bound
twice; nothing verified that the constraint totals themselves summed to the intended
national figure.

**Response.** The state-level fallback is now the **residual** — state total minus the
county totals already claimed — and a state whose county totals *exceed* its state total
raises rather than clamping to a negative residual. A new `ConstraintAccounting` proves
the identity on every build and raises if it does not hold:

```
national_published == constraint_sum + observed_substitution_delta + unconstrained_sum
```

Four regression tests cover it: the residual case, the complete-coverage case, the
negative-residual refusal, and the balanced national identity.

**The completed identity found a second gap in my own first attempt.** The initial
accounting omitted `unconstrained_sum` — the raw values of tracts no constraint binds —
and its own assertion caught that during testing. That term is now reported rather than
absorbed, because it is the share of the national figure resting on no observed total at
all (currently 0.0: every jurisdiction has a published total).

### I-14 — the ACS vintage could not be selected by patching its constant

| Field | Value |
|---|---|
| Opened | 2026-08-29, during the external-review correction pass |
| Affected phase | 3 (`pipeline/sources/census_acs.py`, `pipeline/model/panel.py`), and **Phase 5 had it survived** |
| Severity | **S2 Degrading** — nothing published was wrong, but it would have handed Phase 5 a D1 violation that looked like a passing test |
| Status | **RESOLVED 2026-08-29** |

**Assumed.** That setting `census_acs.ACS_YEAR` selects which ACS vintage loads, so a
caller wanting a historical vintage could patch the module attribute.

**Actually true.** `AcsSource.__init__` binds `year: int = ACS_YEAR` as a **default
argument, evaluated once at class-definition time**. Patching the module attribute
afterwards has no effect: the source silently keeps loading the **production** vintage.

**How it surfaced.** The first attempt at decomposing the ACS 2023 → 2024 improvement
(Phase 3 report §14.4) patched the constant and produced four rows in which the 2023 and
2024 results were **byte-identical** — `poisson=0.321982` in both. Identical results across
two different vintages is not a plausible measurement, and that is what exposed it.

**Why it matters beyond this phase.** Directive D1 requires
`feature_vintage <= prediction_cutoff`. Phase 5's rolling origins at 2020, 2021 and 2022
must load the contemporaneous ACS release. Had Phase 5 selected a vintage the way the
decomposition first did, every origin would silently have been fed **current** features —
textbook temporal leakage — and the leakage guard would not have caught it, because the
features would have carried the vintage stamp the caller *asked* for while holding the data
it did not.

**Response.** `load_area_tables` takes an explicit `year` parameter, documented with the
reason it is a parameter rather than a patched constant. Two regression tests: one that the
historical vintage still replays, and one that the two vintages return **genuinely different
values**, so a loader ignoring its year argument cannot pass vacuously.

**Nothing published was wrong.** Every Phase 3 number, before and after the refresh, was
produced through the normal path with the correct vintage.

### Risks closed by Phase 3

Two open risks recorded in `docs/reports/LIVE_INTEGRATION_AUDIT.md` §I are closed. That
report is frozen, so the closures are recorded here and in
`docs/reports/PHASE_3_REPORT.md` §8.2 rather than by editing it.

| Risk | As recorded | Closed how |
|---|---|---|
| **R-5** (S3) | "HUD's 60/min rate limit makes a national ZIP sweep slow (~34,000 ZIPs ≈ 9.5 hours serially). Phase 3 needs a cached bulk strategy" | The crosswalk API accepts a **state abbreviation**, so the twelve states Phase 3 needs cost **twelve requests**. Validated against the known-good per-ZIP Washington cache: the state route is a strict superset (700 ZIPs against 438), every shared ZIP matches to **0.0** absolute difference in `res_ratio`, no tract is missing, and the Washington comparison scope is unchanged — same six zero-residential ZIPs, same 404 ZIP 98504 |
| **R-3** (S2) | "HUD and land-area allocation disagree materially, and even HUD misallocates 17.94% of EV mass in Washington. Allocation error must feed the uncertainty score" | It does, as uncertainty component `c4`, derived from a **measurement** rather than a chosen penalty: statewide tract TVD 0.0000 (`native_tract`), 0.1621 (`zip_anchored`, HUD `res_ratio`), 0.2367 (`county_anchored`), 0.3049 (`state_total_only`) |

### I-11 — a like-numbered ZCTA join imported out-of-state households as exposure

| Field | Value |
|---|---|
| Opened | 2026-08-28, during Phase 3 model development |
| Affected phase | 3 (`pipeline/model/panel.py`); **no earlier phase published anything from this path** |
| Severity | **S1 Blocking had it shipped** — every ZIP-grain state's demand estimate would have been wrong. Caught before any Phase 3 output was published |
| Status | **RESOLVED 2026-08-28** |

**Assumed.** That a USPS ZIP Code appearing in a state's DMV export belongs to that
state, so matching it to the like-numbered ZCTA yields that ZIP's households.

**Actually true.** State DMV exports carry **out-of-state mailing ZIPs**. Oregon's latest
snapshot contains ZIP 00907 (Puerto Rico), 01742 (Massachusetts), 02852 (Rhode Island),
07054 (New Jersey) and 10010 (Manhattan), each holding one or two vehicles. Matching
those to their like-numbered ZCTA imported **3,541,636 households — 62% of Oregon's
matched exposure — behind ZIPs holding 378 vehicles between them.** The model then
predicted large EV counts where the state has no residents. Oregon's rank correlation
between predicted and observed went **negative (−0.177)**, and Vermont's was **−0.365**.

Scale across the eleven ZIP-grain states: 333 such ZIPs in Colorado, 327 in New York,
310 in Oregon, 170 in Vermont, 116 in North Carolina (5,040 vehicles, 7.6% of the state
total), 1 in Texas, none in New Jersey or New Mexico.

**Response.** Every ZIP is checked against a ZCTA-to-state index built from the Census
2020 relationship file, and one lying wholly outside the registering state is excluded
**by name**, with its vehicles counted in the panel ledger rather than dropped: they are
real, they belong in the state total, and they cannot be attributed to any in-state area.
Aggregate leave-one-state-out WAPE moved from **0.72 to 0.33**.

**Why this is not an earlier-phase impact.** Phase 1 built the allocation machinery but
amendment A21 forbade Phase 2 from consuming registration allocations at all, and Phase 2
did not. No published number from any earlier phase passed through this path.

### I-12 — a within-group TVD is not comparable across geographic grains

| Field | Value |
|---|---|
| Opened | 2026-08-28, while measuring the transformation ladder |
| Affected phase | 3 (`pipeline/validation/washington.py`) |
| Severity | **S2 Degrading** — it produced a measurement that appeared to falsify the specification |
| Status | **RESOLVED 2026-08-28** |

**Assumed.** That the EV-weighted mean of per-group total variation distances measures
"how far a tract value is from directly observed evidence", and can be compared between
ZIP, county and state rungs.

**Actually true.** It cannot, for two independent reasons. First, the initial
implementation derived each group's tract membership **from the observed records**, which
hands every method perfect knowledge of which tracts actually hold vehicles — the hardest
part of the problem. Second, a within-group mean averages many small separate problems
whose scales differ: a ZIP's residual error spreads over a few adjacent tracts while a
state's spreads over every tract in the state.

Measured that way, the ladder read `county_anchored` 0.2367 **better than** `zip_anchored`
0.3461, which would have been reported as falsifying the ordering CLAUDE.md §7.4
component 5 predicts.

**Response.** Membership now comes from geography alone — GEOID nesting for county and
state, the HUD crosswalk for ZIP — and the metric is the **statewide tract-level TVD**:
rebuild the whole state's tract vector from each transformation and compare it against the
observed one. On that metric the specification's ordering holds:
`native_tract` 0.0000 < `zip_anchored` 0.1621 < `county_anchored` 0.2367 <
`state_total_only` 0.3049. `assert_ladder_ordering` now checks the result against the
specification's claim rather than assuming it.

**Nothing published was wrong**, because the flawed metric was never released; it is
recorded because it nearly produced a false finding against the specification.

### I-13 — the population-share baseline was algebraically the household baseline

| Field | Value |
|---|---|
| Opened | 2026-08-28, during Phase 3 model development |
| Affected phase | 3 (`pipeline/model/demand.py`) |
| Severity | **S3 Cosmetic** — a second baseline that was secretly the first |
| Status | **RESOLVED 2026-08-28** |

**Assumed.** That fitting a per-person rate and converting it to a per-household rate
gave a baseline distinct from the household-share baseline.

**Actually true.** `(Σcount / Σpopulation) × (Σpopulation / Σhouseholds)` is
`Σcount / Σhouseholds` — exactly the household baseline. The two reported **identical
WAPE to four decimal places for every state**, which is what exposed it.

**Response.** An `exposure_kind` on every estimator, so the population baseline predicts
from population and the rest from households. The two now differ (0.7096 against 0.7119
in the aggregate), and a test asserts they are not equal.

### I-7 — two checkpoint documents published a test count that was never true

| Field | Value |
|---|---|
| Opened | 2026-08-28, owner review of the Live Integration Assurance Checkpoint |
| Affected phase | Live Integration Assurance Checkpoint (`LIVE_INTEGRATION_AUDIT.md`, `LIVE_INTEGRATION_STATUS.md`) |
| Severity | **S3 Cosmetic** — reporting only; no measurement or gate result was wrong |
| Status | **RESOLVED 2026-08-28** |

**Assumed.** That the suite held 585 deterministic tests and 46 live tests.

**Actually true.** At the commit both documents describe (`39f5bbf`, clean tree) the
suite collects **563** deterministic tests, **47** carrying the `live` marker, **610**
in total. 585 matches no committed state: at the Phase 2 gate commit `3330e79` the suite
collected 529, and `git show --stat 39f5bbf -- tests pyproject.toml Makefile` is empty,
so nothing about the tests changed between `95d7ecf` and `39f5bbf`.

The 46-versus-47 half is a real distinction rather than a typo: 46 is the `tests/live/`
**directory** count and 47 is the **marker** count, because
`tests/integration/test_determinism.py::test_live_refresh_is_not_expected_to_be_byte_identical`
is deliberately marked `live` so it stays out of the deterministic gate.

**Response.** Both documents corrected with the original figures struck through and the
derivation shown (`LIVE_INTEGRATION_AUDIT.md` §K.1). `tests/unit/test_suite_composition.py`
now asserts the structure instead of a total: every test under `tests/live/` carries the
marker, the live-marked tests outside that directory are exactly one enumerated entry,
and `pyproject.toml` still deselects `live` by default.

### I-8 — the Washington comparison published a denominator it did not account for

| Field | Value |
|---|---|
| Opened | 2026-08-28, owner review of the Live Integration Assurance Checkpoint |
| Affected phase | Live Integration Assurance Checkpoint (§E.1), Phase 3 inputs |
| Severity | **S3 Cosmetic** — the measurement was right; the accounting for it was absent |
| Status | **RESOLVED 2026-08-28** |

**Assumed.** That reporting the comparison over 292,581 EVs, against 294,193 records
retrieved, was self-explanatory.

**Actually true.** The 1,612-record gap was defensible but unpublished, so a reader could
not distinguish deliberate exclusion from silent loss — the quiet form of the failure
directive D8 forbids.

**Response.** The comparison is now reproducible code
(`pipeline/validation/allocation_error.py`, `pipeline/validation/washington.py`) over the
full 294,193-record retrieval, classifying every record through an ordered,
first-match-wins rule list so reasons are mutually exclusive by construction, with
`ExclusionLedger.assert_balanced()` raising unless
`retrieved == included + sum(excluded_by_reason)`. The published table is 15 + 746 + 535
+ 233 + 71 + 12 = 1,612 excluded, 292,581 included.

**The decision did not change.** Weighted mean TVD 0.179354 (HUD) against 0.257865 (land
area), win share 0.645012, all four complexity strata identical to §E.1. Two secondary
metrics moved: top-tract accuracy by exactly `1/431` for both methods, because ZIP 98586
is the one included ZIP with a tied observed top tract and ties now break deterministically
on the lowest tract id; and weighted mean MAE, because the denominator is now stated
explicitly as the union of observed and estimated tracts.

### I-9 — Washington was used to select a preprocessing method and could have been reused as independent validation

| Field | Value |
|---|---|
| Opened | 2026-08-28, owner review before Phase 3 model fitting |
| Affected phase | 3 (validation design) |
| Severity | **S2 Degrading** — a Washington LOSO figure inside a headline aggregate would have been weaker than the label claimed |
| Status | **RESOLVED 2026-08-28**, before any model was fitted |

**Assumed.** That Washington could serve both as the holdout that chose HUD over
land-area weighting and as a state in the independent leave-one-state-out aggregate.

**Actually true.** A preprocessing method tuned on Washington makes any later Washington
result tuning-influenced. Reporting it inside an aggregate described as independent
validation would overstate the evidence.

**Response.** Fixed in `docs/evidence/P3-0_phase3_preregistration.md`, written and
committed before any Phase 3 fitting: Washington carries the status
`non_independent_preprocessing_selection_state`, is excluded from any headline aggregate
described as independent, and is still run and reported in its own labelled row. Every
held-out state is scored at its own native observed granularity, and crosswalk-generated
tract values are never used as observed tract labels. The cost — no tract-native state
remains in the independent aggregate — is recorded rather than avoided.

### I-10 — "acceptability floor" inverted the sense of the 0.35 threshold

| Field | Value |
|---|---|
| Opened | 2026-08-28, owner review |
| Affected phase | Live Integration Assurance Checkpoint, `L1-0`, `L1-1` |
| Severity | **S3 Cosmetic** — wording only; the number, the direction of the test and the outcome were all correct |
| Status | **RESOLVED 2026-08-28** |

**Assumed.** That "floor" described a threshold whose failing direction is upward.

**Actually true.** 0.35 is a **maximum acceptable TVD** — an acceptability **ceiling**.
Exceeding it is what triggers a plan change.

**Response.** The repository now says "maximum acceptable TVD" or "acceptability
ceiling", encoded as `pipeline.validation.allocation_error.MAX_ACCEPTABLE_TVD = 0.35`. A
dated terminology note is appended to `L1-0` rather than editing a pre-registration in
place; `L1-1` is left frozen and is superseded by
`docs/evidence/P3-1_wa_allocation_scope_and_error.json`.

### I-5 — the probe attached a measurement to failed responses

| Field | Value |
|---|---|
| Opened | 2026-08-26, Live Integration Assurance Checkpoint |
| Affected phase | 0, 1, 2 (`pipeline/discovery/probe.py`) |
| Severity | **S2 Degrading** — a failure was reportable as an empty dataset |
| Status | **RESOLVED 2026-08-26** |

**Assumed.** That measuring a response was harmless regardless of its status.

**Actually true.** A 4xx or 5xx body was measured like any other payload, producing a
measurement with `row_count: 0`. A downstream reader could take that as "this source has
no rows" rather than "this request failed" — precisely the silent-empty-dataset outcome
directive D8 forbids. Found by a mocked failure-mode test, not by live traffic.

**Response.** Non-OK and credential-gated responses are no longer measured; the
observation carries `measurement: None` and a status of `unavailable` or `gated`. All
prior gates re-run and passing. No published number changes: every real probe run to date
returned 200 for the sources whose measurements were used.

### I-6 — request headers were persisted to the cache unredacted

| Field | Value |
|---|---|
| Opened | 2026-08-26, before any live credential was used |
| Affected phase | 1, 2 (`pipeline/discovery/cache.py`) |
| Severity | **S2 Degrading** — a credential could have been written to disk |
| Status | **RESOLVED 2026-08-26** |

**Assumed.** That redacting query parameters was sufficient, because every credential up
to this point was a query parameter.

**Actually true.** `_record` wrote `request_headers` verbatim into cache metadata. HUD
authenticates with `Authorization: Bearer <jwt>`, so the first HUD fetch would have
written a live token to disk in plain text — and `tests/fixtures/replay/` is tracked by
git.

**Caught before any exposure.** The hole was found and closed during the mandatory
secret-hygiene step, before the first authenticated request. No credential was ever
written: the HUD cache records `"Authorization": "<redacted>"`.

**Response.** `REDACTED_HEADERS` added covering `authorization`, `x-api-key`, `api-key`,
`token`, `x-auth-token`, `cookie` and `proxy-authorization`; `REDACTED_PARAMS` widened
and matched case-insensitively; redaction applied before the metadata write. Cache keys
hash the *redacted* form, so a fixture recorded under one credential replays under
another. A leakage scan over tracked files, caches, evidence, reports and `.body`
payloads passes.

### I-2 — the Phase 1 report described a rounded 99.975% as "100.0%"

| Field | Value |
|---|---|
| Opened | 2026-08-24, project owner review of the Phase 1 report |
| Affected phase | 1 (`docs/reports/PHASE_1_REPORT.md` §9.1) |
| Severity | **S3 Cosmetic** — presentation only; no measurement was wrong |
| Status | **RESOLVED 2026-08-24** |

**Assumed.** That `89,665 / 89,687` stations reconciling could be written as 100.0%.

**Actually true.** The ratio is 99.9755%. The 22 exceptions are real and were unexamined.

**Response.** Phase 2 preflight (CLAUDE.md 15.5.1) classified all 22 with zero
unresolved: 12 planned stations with no unit records, 8 containing `legacy`-level units
the L1/L2/DCFC aggregate does not count, and 2 holding only legacy units. Under the
documented scope "at least one unit record and no legacy-level unit", reconciliation is
89,736 / 89,736 = exactly 100.0000%. A dated correction was appended to the Phase 1
report and a test now asserts the unscoped rate is never called 100%.

### I-3 — `port_count == 1` was published as a guaranteed invariant

| Field | Value |
|---|---|
| Opened | 2026-08-24, project owner review of the Phase 1 report |
| Affected phase | 1 (`pipeline/schemas/canonical.py`, report §7.1) |
| Severity | **S2 Degrading** — usable but claimed more than the source supports |
| Status | **RESOLVED 2026-08-24** |

**Assumed.** That every AFDC charging unit has exactly one port, permanently.

**Actually true.** It holds for all 292,756 units in the 2026-08 snapshot, but it is a
current-source property. Charging unit and port remain conceptually distinct entities,
and a future record with several ports would be legitimate data. A schema pinned at
`== 1` would have rejected it as corruption.

**Response.** Amendment A19. The schema now requires `port_count >= 1`;
`check_port_count_drift` monitors the `== 1` observation and reports a higher value as
source drift requiring review, never raising. Gate check P2-D covers both directions,
including that the schema accepts a 4-port record.

### I-4 — the gate's coverage thresholds could not fail

| Field | Value |
|---|---|
| Opened | 2026-08-24, during the Phase 2 gate run |
| Affected phase | 1 (`Makefile`, `gate-1` and `coverage`) |
| Severity | **S2 Degrading** — the gate reported a threshold it was not enforcing |
| Status | **RESOLVED 2026-08-24** |

**Assumed.** That `coverage report --fail-under=N | tail -2` fails when coverage is
below N.

**Actually true.** A shell pipeline returns the last command's exit status, so `tail`
masked every coverage failure. The threshold could never fail the gate. It was caught
because `pipeline/discovery/` reported 99% while the Phase 2 gate still passed.

**What this did NOT invalidate.** The Phase 1 coverage figures were correct as measured
and reported — 100% line and branch at that time. The defect meant a *future* regression
would have gone unnoticed, not that the reported numbers were wrong.

**Response.** Each check now captures output to a file and tests the exit status
explicitly. The two statements the defect had hidden (the new nested-JSON probe branch)
are now covered, and both the Phase 1 and Phase 2 gates were re-run and pass.

## Resolved entries

### I-1 — `afdc_charging_units` was published with `stable_keys: true` and a station-level join key

| Field | Value |
|---|---|
| Opened | 2026-08-19, during Phase 1 planning review |
| Discovered by | Project owner review of the Phase 1 plan |
| Affected phase | 0 (`SOURCES.yml`, `docs/reports/PHASE_0_REPORT.md`) |
| Severity | **S2 Degrading** — the contract entry is usable but claims more than the source supports |
| Status | **RESOLVED 2026-08-19**, same day, within the correction window §15.3 allows for S2 |

**What was assumed.** The Phase 0 contract recorded, for `afdc_charging_units`:

```yaml
    schema:
      join_keys: [id]
      stable_keys: true
```

`stable_keys: true` is defined in the contract as meaning the join keys are stable across
refreshes. Read together with a one-row-per-charging-unit source, it implies row-level
identity that can be followed over time.

**What is actually true.** Measured over the full national export, 292,435 rows:

| Measurement | Value |
|---|---|
| Rows | 292,435 |
| Distinct station `ID` values | 89,687 |
| Columns resembling a unit identifier | **none** — `ID` is the station, `Federal Agency ID` and `NPS Unit Name` are unrelated |
| Distinct full-row values | 99,639 |
| Rows participating in an identical-row group | 265,836 (**90.9%**) |
| Redundant rows (n−1 per identical group) | 192,796 (**65.9%**) |
| Largest identical-row group | 410 rows (station 225833, Viejas Casino and Resort) |
| Stations where row count == reported L1+L2+DCFC | **89,665 / 89,687 (100.0%)** |

`ID` is the **station parent key**, not row identity. There is no charging-unit identifier
column of any kind. Two-thirds of rows are byte-identical to another row, so rows are not
distinguishable from one another by their content, and row *order* is the only thing
separating them — which no refresh guarantees.

**These duplicates are not data errors.** The last row of the table above is the key finding:
row count reconciles exactly to the station's reported EVSE totals for 100.0% of stations. The
export emits one row per EVSE, and identical units produce identical rows. This is the same
logic as domain rule G4 for coordinate duplicates — real distinct physical objects that are
indistinguishable in every reported attribute.

**What is invalidated, and what is not.**

- **Invalidated:** `stable_keys: true` for this source, and the implication that
  `charging_unit_id` could be a stable physical identifier. Corrected in `SOURCES.yml` to
  `stable_keys: false` with `parent_key` and `row_identity` stated separately.
- **NOT invalidated:** every quantitative Phase 0 finding. The rung-1 power coverage figures
  (82.76% all rows, 88.11% public+operational, port-weighted) aggregate counts across rows and
  never rely on row identity. The 100.0% reconciliation above independently corroborates that
  the port totals are trustworthy. Finding F-1 and its evidence artifact stand unchanged.

**Response taken.** Contract corrected; specification §6.1.1 extended from ports to
charging-unit and connector identity; the Phase 1 identifiability investigation widened to
three levels; a dated correction appended to `docs/reports/PHASE_0_REPORT.md`; Phase 0 gate
re-run and passing. No Phase 0 measurement required recomputation.

### I-20 — road distance was measured to the nearest vertex, not the nearest point on a road

| Field | Value |
|---|---|
| Opened | 2026-08-31, external review of the Phase 4 blocker corrections |
| Discovering phase | 4 (external review) |
| Affected phase | 4 (`pipeline/spatial/road_proximity.py`, `docs/evidence/P4-1_siting.json`) |
| Severity | **S2 Degrading** — the candidate filter used a method that can overestimate distance and falsely exclude cells. Measurement afterwards showed it changed no published value on this data, which is why this is S2 and not S1 |
| Status | **RESOLVED 2026-08-31** |

**Assumed.** That distance from a cell centroid to the nearest TIGER **vertex** was an
adequate measure of distance to the road network, on the reasoning that TIGER geometries
are densely vertexed. This was recorded as assumption **A-4.6** and deferred to Phase 6.

**Actually true.** A LineString's nearest vertex is not generally its nearest point. A cell
beside the middle of a long straight segment is close to the road and far from both of its
endpoints, so the vertex measurement **overestimates**, and the error is bounded by half
the segment length — up to **2.96 km** against the measured 5.928 km longest segment in
California, on a filter whose threshold is **5.0 km**. Deferring that to a later phase was
wrong: it is an error in a **hard candidate filter**, where an overestimate does not
degrade a number, it removes a cell from consideration entirely.

The synthetic regression fixture makes the failure concrete: a two-vertex road ~76 km long
and a cell whose centroid sits 2.22 km from its middle. Nearest-vertex distance reports
**37.98 km** — a **17x** overestimate — and excludes the cell from the 5 km filter, which
the corrected method admits. `test_a_long_segment_is_not_reduced_to_its_endpoints` asserts
both halves of that, and `test_the_refinement_is_not_skipped_just_because_vertices_are_far`
guards the pruning shortcut that a first implementation of the correction got wrong.

**Response taken.** `pipeline.spatial.distance.PolylineIndex` computes distance to the
nearest **point on** the nearest segment. The nearest point along each segment is located
in a tangent plane centred on the query point, then its distance is measured with the same
haversine used everywhere else, so the reported value is a genuine great-circle distance to
a real location on a road — and therefore never greater than the vertex distance, since a
vertex is itself a point on the segment. `RoadVertices` now carries CSR-style feature
offsets so a segment is only ever formed **within** one road: flattening the vertices
without them would join the end of one road to the start of the next and invent a segment
that does not exist (`test_segments_are_never_formed_between_two_different_roads`).

**What the measurement found — the correction changes nothing published.** Across all six
frontier states: **zero** cells change side of the 5.0 km threshold, candidate-set Jaccard
is **1.000000** in every state, and every portfolio at 5, 20 and 50 sites is identical.

| State | Candidates, vertex | Candidates, corrected | Cells changing side | Max distance error | Cells overstated >100 m |
|---|---:|---:|---:|---:|---:|
| Washington | 674 | 674 | 0 | 193.2 m | 3 |
| Tennessee | 1,425 | 1,425 | 0 | 169.1 m | 2 |
| Montana | 297 | 297 | 0 | 138.0 m | 1 |
| Vermont | 250 | 250 | 0 | 53.4 m | 0 |
| Texas | 2,417 | 2,417 | 0 | 666.9 m | 18 |
| California | 1,253 | 1,253 | 0 | 394.2 m | 10 |

The frontier (96/96 optimal, every CBC gap 0.0) and the greedy shortfalls are **byte-identical
after the field renames**, verified by comparing the regenerated artifact against the
committed one key by key. So no downstream value needed regenerating on its merits — but the
artifact was regenerated anyway, because it now carries the corrected distances and the
comparison itself.

The practical error is far below the 2.96 km theoretical worst case because the longest
segments happen not to lie near candidate cells. That is a property of this snapshot, not a
guarantee, which is exactly why the method rather than the outcome was fixed.

**A-4.6 is closed.** It was opened as "vertex distance is close enough" and deferred; it is
closed by replacing the method rather than by confirming the assumption.

### I-21 — a positional read of the retained-vintage list changed what Phase 3 compared

| Field | Value |
|---|---|
| Opened | 2026-08-31, during Phase 5 |
| Discovering phase | 5 |
| Affected phase | 3 (`pipeline/model/run_phase3.py`, `docs/evidence/P3-2_demand_model.json`) |
| Severity | **S3 Cosmetic** — caught before anything was published in the broken form; the Phase 3 artifact on disk had always been correct |
| Status | **RESOLVED 2026-08-31** |

**Assumed.** That `HISTORICAL_ACS_YEARS[0]` was "the ACS release preceding the production
one". It was, while the list held only `(2023,)`.

**Actually true.** The list is ordered oldest-first and grows at the *front*. Phase 5 added
the 2018 and 2019 vintages for its rolling origins, and Phase 3's "account for every tract
that entered or left the surface between ACS vintages" diagnostic silently became a
**2018-against-2024** comparison — spanning the 2010/2020 census tract-geography break, so
instead of the one-tract change it was written to report, it produced a **250,264-line**
artifact diff enumerating essentially the whole national tract set twice.

**Response taken.** `ACS_PREVIOUS_YEAR = 2023` is now declared explicitly and the diagnostic
reads that, with a comment saying why a positional read is wrong. Phase 3 regenerated: the
artifact diff is back to **two lines**, the two vintages Phase 5 added to the retained list.
A prior-gate regression test (`test_check_04_historical_acs_vintages_are_still_replayable`)
also hard-coded 250 Rhode Island tracts; it now carries per-geography expected counts —
244 for the 2010-geography vintages, 250 for 2020 — which documents the break rather than
hiding it.

---

### I-22 — the copy lint could not permit the project's own central caveat

| Field | Value |
|---|---|
| Opened | 2026-08-31, during Phase 5 |
| Discovering phase | 5 |
| Affected phase | 1 (`pipeline/quality/copy_lint.py`, created there; §15.5 anticipates Phase 5 extending it) |
| Severity | **S2 Degrading** — the lint worked as specified, but its incentive ran backwards |
| Status | **RESOLVED 2026-08-31** |

**Assumed.** That phrase-matching rules could police optimality language without needing to
distinguish a claim from its denial.

**Actually true.** They cannot. "Ground truth for optimal siting does not exist" contains
"optimal siting" and trips D3-OPT-01. CLAUDE.md D3 *requires* the project to be able to write
that sentence, so the lint made its own specification unsatisfiable — and the pressure it
created was to soften the disclaimer until the linter stopped complaining, which is the
opposite of what it exists for.

**Response taken.** Extended with `SANCTIONED_DISCLAIMERS`, a **three-entry exact-phrase
list**, deliberately not a negation detector: a negation detector would have to understand
scope ("not only is this the optimal site") and would quietly widen over time, whereas adding
an exact phrase is a visible, reviewable edit to a named list. A match is forgiven only when
it falls *inside* one of those phrases, and the stripping preserves offsets so a claim sitting
beside a caveat is still caught — asserted by
`test_a_claim_on_the_same_line_as_a_disclaimer_is_still_caught`.

A second test asserts every listed phrase actually trips a rule. It found **nine dead entries
in the first draft** — phrases I had added defensively that no rule matched — which would have
sat in the file reading like permitted claims. They were removed, leaving three.

### I-23 — the random baseline was one draw, and 2020's draw was an outlier

| Field | Value |
|---|---|
| Opened | 2026-08-31, external review of the Phase 5 submission |
| Discovering phase | 5 (external review) |
| Affected phase | 5 (`pipeline/validation/deployment_alignment.py`, `docs/evidence/P5-1_validation.json`) |
| Severity | **S2 Degrading** — a published headline figure was overstated by a noisy comparator; the model and its ranking were never affected |
| Status | **RESOLVED 2026-08-31** |

**Assumed.** That a single seeded permutation is an adequate random baseline.

**Actually true.** It is unbiased but high-variance. Subsequent-deployment counts are heavily
concentrated across cells, so one shuffle either does or does not land on the busy ones.
Review spotted the symptom: a 2020 top-decile capture of 0.645 with lift 9.40x implies a
random capture of ~0.0686, against ~10% at the other two origins.

**What it was not.** Not a support difference. Every ranking is scored over exactly the same
eligible cells — asserted in the gate — and the share of deployments falling inside that
support barely moves between origins: 0.9754 / 0.9718 / 0.9681.

**What it was.** Over 400 draws at the 2020 origin the top-decile capture has mean **0.0976**
and standard deviation **0.0137**, with a 5th percentile of 0.0759. The shipped single-seed
draw, **0.0687**, sat at **percentile 0** — outside the band. The 2021 and 2022 draws sat at
percentiles 76 and 64, which is why only 2020 looked wrong.

**Response taken.** The random baseline is the **mean over 200 draws**, with its spread
(`draws`, mean, sd, p5, p95, the original single-seed value and its percentile) published in
the artifact. It remains an **empirical** baseline, not a theoretical one-tenth, which is what
the review required. Six gate checks were added, including one asserting random capture is now
consistent across origins and one asserting all four rankings share an identical support.

**Effect on published numbers.** Lift against random falls to **6.72 / 6.39 / 5.89** from
9.40 / 5.92 / 5.77 — the correction **reduces** the model's headline advantage, most at the
origin that looked best. Lift against population is unchanged at **0.83 / 0.82 / 0.81** and
the negative alignment result stands.

---

### I-24 — the population result was over-interpreted as evidence about D2

| Field | Value |
|---|---|
| Opened | 2026-08-31, external review of the Phase 5 submission |
| Discovering phase | 5 (external review) |
| Affected phase | 5 (`docs/VALIDATION.md`, `docs/reports/PHASE_5_REPORT.md`) |
| Severity | **S3 Cosmetic** — interpretation only; no number, model or metric was involved |
| Status | **RESOLVED 2026-08-31** |

**Claimed.** That a model *beating* the population baseline would have been evidence it had
learned industry deployment habits, and that losing to population therefore vindicated
directive D2.

**Actually true.** The inference does not hold in either direction. D2 constrains which
**features** may enter the demand model and is enforced by a test on the feature set, not by
a ranking outcome. A model could outperform population for many reasons unrelated to
reproducing industry behaviour, and underperform it for reasons unrelated to D2. The argument
dressed a comfortable reading of a negative result as a design vindication.

**Response taken.** The claim is withdrawn and replaced with the narrow conclusion: the model
strongly outperforms random and the existing-network baseline but does not outperform
population for reproducing subsequent industry deployment locations at any origin; this is a
negative historical-deployment-alignment result, not evidence of siting failure and not itself
evidence for or against D2.

---

## Phase 0 note

Phase 0 is the first phase, so there is no earlier phase for it to invalidate and this
log is correctly empty.

Two findings from Phase 0 concern the *specification and the delivered documentation*
rather than a prior phase's output, so they do not belong here:

- Domain rule **G9** is factually wrong against the delivered data. Escalated through
  `docs/reports/PLAN_CHANGE_0.md`, awaiting a decision. Would become an impact-log
  entry only if a later phase had already published something depending on it.
- `SETUP.md` names a retired NREL host and describes the Census API key as optional.
  Recorded as corrections in `docs/SOURCE_VERIFICATION.md` §3.
