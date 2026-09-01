# Phase 5 Report — Validation

**Status: gate PASS.** Phase 6 not started.

---

## 1. Context, for a reader who has read nothing else

**VoltGap** is an open, statically hosted decision-support application answering: *given a
budget and a set of policy priorities, where should the next EV charging infrastructure be
built in the United States, and how confident should we be in that answer?* It is built in
gated phases against an authoritative specification (`CLAUDE.md`), and no phase begins until
the previous one's gate passes.

**What the previous phases produced.** Phase 0 established the source contract. Phase 1
ingested every source and froze the canonical tables. Phase 2 built supply and access.
Phase 3 built the tract-level demand model — a Poisson GLM on 14 ACS demographic features,
reconciled to observed totals, with a continuous uncertainty score. Phase 4 built candidate
siting and the ε-constraint frontier over H3 resolution-6 cells, and was accepted by
external review after two rounds of corrections.

**What Phase 5 was for.** To complete the three validation tracks the specification defines,
under a hard temporal-leakage constraint.

**The three terms, which directive D3 forbids blurring:**

| Term | What it evaluates | Method |
|---|---|---|
| **Demand model validation** | Whether tract-level EV estimates are accurate | Leave-one-state-out against observed states |
| **Historical deployment alignment** | Whether priority areas match where industry actually built | Vintage-enforced rolling-origin backtest |
| **Cross-objective robustness** | Whether a portfolio optimised for one objective also performs on others | ε-constraint analysis and cross-scoring |

**None of these demonstrates that a site is optimal.**
Ground truth for optimal siting does not exist.

Everything below is reproduced by `make phase5`, which reads only cached responses and needs
no network or credentials. It writes `docs/evidence/P5-1_validation.json` in 57 seconds.

---

## 2. The eleven questions the brief required this report to answer

Answered here in order; the evidence for each is in the sections that follow.

**1. What exact dates are the historical prediction cutoffs?**
2020-01-01, 2021-01-01, 2022-01-01. Each predicts the following 24 months, so the evaluation
windows end 2022-01-01, 2023-01-01 and 2024-01-01.

**2. What data vintages were available at each cutoff?**

| Origin | ACS vintage | Released | Tract geography | State registrations | Released |
|---|---|---|---|---|---|
| 2020 | ACS 2018 5-year (2014-2018) | 2019-12-19 | **2010** | AFDC 2019 | 2020-01-01 |
| 2021 | ACS 2019 5-year (2015-2019) | 2020-12-10 | **2010** | AFDC 2020 | 2021-01-01 |
| 2022 | ACS 2019 5-year (2015-2019) | 2020-12-10 | **2010** | AFDC 2021 | 2022-01-01 |

**3. What data were deliberately excluded to prevent leakage?** Nine enumerated exclusions —
three later ACS releases, home charging access, every sub-state registration panel, all
supply-derived features, the current HUD crosswalk and the TIGER 2024 road network. §5.3.

**4. Did the negative leakage test fail as expected?** Yes. `LeakageError` is raised naming
the poisoned feature. §4.3.

**5. How many later charger deployments were available at each origin?** 18,189 / 22,168 /
20,533 stations, carrying 46,220 / 58,962 / 63,616 ports, across 52 jurisdictions. §5.6.

**6. How much better or worse was the model ranking than random and population baselines?**
Better than random by **5.77× to 9.40×**. **Worse than the population baseline at every
origin**, by 0.81× to 0.83×. §5.7.

**7. How sensitive are conclusions across historical origins?** Stable. The ordering
population > model > existing-network > random holds at all three, and every figure moves
mildly and monotonically. §5.8.

**8. How do Phase 4 portfolios perform on objectives not optimized directly?** They lead the
baselines on all six, but trade off against each other: a demand-first portfolio reaches only
79.6% of the best equity coverage, and an equity-first portfolio only 81.9% of the best demand
coverage. §6.

**9. Where do those portfolios lose to simple baselines?** At budget 20 in the six frontier
states, they do not lose to any baseline on any of the six objectives — which is the least
interesting part of the table and is not reported as a finding. They lose to *each other*.
§6.3.

**10. Which conclusions are independent validation versus diagnostic evidence?** §8.

**11. What confounding prevents stronger causal/siting claims?** §5.9.

---

## 3. What was built

| Module | Purpose |
|---|---|
| `pipeline/validation/vintage.py` | The D1 leakage guard: `SourceVintage`, `VintagedFeature`, `assert_no_leakage`, `LeakageError`, `VintageLedger` |
| `pipeline/validation/origins.py` | The three origins, every declared source vintage with its release evidence, and the resolution of what each origin may see |
| `pipeline/validation/backtest.py` | Builds a demand surface from only what existed at a cutoff |
| `pipeline/validation/deployment_alignment.py` | Gain curves, lift, baselines |
| `pipeline/validation/robustness.py` | Six objectives, four baselines, tradeoff detection |
| `pipeline/model/run_phase5.py` | The driver: all three tracks, offline |
| `docs/VALIDATION.md` | The validation document §16 requires |

New tests: 15 (vintage guard) + 25 (origins and backtest) + 16 (alignment) + 15 (robustness)
+ 20 (driver) + 25 (Phase 5 gate) + 7 (smoke-forward) + 6 (copy-lint extension) + 3
(population-weight vintages).

New source contracted: `census_cenpop_blockgroup_2010`, the 2010 decennial
population-weighted block-group centroid product, with a probe spec, a recorded live
observation and an entry in `SOURCES.yml`. Its `backtest_eligible` is **false** in the
contract's sense — there are no historical vintages *of* it to reconstruct — but it is
nonetheless used by the backtest, because it is a fixed 2010 edition that already predates
every cutoff. That distinction is recorded on the entry rather than resolved by relaxing
the contract rule.

---

## 4. Temporal leakage — the primary correctness constraint

### 4.1 Two dates, not one

A data product has a **period** — what span of reality it describes — and a **release date** —
when a person could first have obtained it. The ACS 2019 5-year estimates describe 2015–2019
but were not published until 10 December 2020. A backtest at a 2020-01-01 cutoff using them
would be using information nobody had, even though the period ends before the cutoff.

**Availability is governed by the release date.** `SourceVintage` refuses to exist without
one, and refuses a release date earlier than the period it describes:

```python
def __post_init__(self) -> None:
    if self.released < self.period_end:
        raise ValueError(
            f"{self.source_id} {self.label}: released {self.released} before its "
            f"period ends {self.period_end}, which is not possible")

def available_at(self, cutoff: date) -> bool:
    return self.released <= cutoff and self.period_end <= cutoff
```

### 4.2 The guard

```python
def assert_no_leakage(
    features: Sequence[VintagedFeature], prediction_cutoff: date
) -> None:
    late = [f for f in features if f.feature_vintage > prediction_cutoff]
    if late:
        raise LeakageError(...)
```

`LeakageError` subclasses `AssertionError`, so nothing in the pipeline can catch it and
continue. It is called **before every fit**, on the actual feature columns, inside
`build_historical_surface` — so a mis-declared vintage stops the run rather than producing a
plausible number. It names **every** offending feature, not only the first: a harness
reporting one violation per run takes one run per mistake to clean up.

### 4.3 The negative test — required, and it passes

`tests/unit/test_vintage_guard.py::test_a_deliberately_poisoned_feature_set_raises`:

```python
clean = [feature("income", date(2019, 12, 31)),
         feature("tenure", date(2019, 12, 31))]
assert_no_leakage(clean, CUTOFF)          # the honest set passes

poisoned = [*clean, feature("income_from_the_future", date(2024, 12, 31))]
with pytest.raises(LeakageError, match="income_from_the_future"):
    assert_no_leakage(poisoned, CUTOFF)
```

It is re-run inside the Phase 5 gate suite
(`test_p5_a_the_negative_leakage_test_exists_and_passes`) so the gate covers it directly
rather than trusting the unit suite included it.

### 4.4 Uncertainty resolves toward exclusion

Where a release date is not established with confidence, the harness uses the **older**
vintage whose date is certain. Erring older cannot manufacture leakage; erring newer can.

This binds once, on the **ACS 2020 5-year** release. It is widely reported to have slipped
from December 2021 to March 2022 because of pandemic collection problems, which would put it
on the wrong side of the 2022-01-01 cutoff — but **this project did not verify that date
against a primary source**. Rather than rest a leakage claim on a remembered date, the
vintage is declared `release_date_certain: false` and the 2022 origin falls back to ACS 2019.

---

## 5. Historical deployment alignment

### 5.1 What this asks, and what it does not

**Asks:** did the model assign higher priority to locations where charging infrastructure was
subsequently deployed?

**Does not establish:** that historical deployments were optimal; that the model identifies
causally correct siting decisions; that operators should have followed the model; or that any
future selected site is validated as optimal.

**High alignment may mean the model reproduces industry behaviour including its biases** —
the opposite of a good result for a system whose purpose is to find underserved areas
(§18 anti-pattern 2). That caveat ships inside every alignment record in the artifact, and
`test_p5_e_alignment_never_claims_optimality_or_causality` asserts it is there.

### 5.2 The tract-geography break, and why the backtest is scored on cells

ACS releases **through 2019** are published on **2010** census tract boundaries; the **2020**
release onward uses **2020** boundaries. Measured on the live API, Vermont returns 184 tracts
for the 2018 and 2019 vintages and 193 for 2020 and 2021. Nationally: **74,001** tracts in the
2019 gazetteer against **85,396** in the 2023 one.

All three origins resolve to 2010-geography releases, while the production surface is 2020
geography. The backtest is therefore scored on **H3 resolution-6 cells**, which do not move
when the Census redraws tracts, using contemporaneous **CenPop2010** block-group population
weights and the contemporaneous **2019 gazetteer** for land area. Every §10.2.4 metric is a
cell-ranking metric, so nothing is lost by this.

Retrieved for this phase: ACS 2018 and 2019 tract features for all 51 jurisdictions, the 2010
block-group centroid product for all 51, and the 2019 national gazetteer.

### 5.3 Every feature excluded, and why

| Feature / source | Reason |
|---|---|
| ACS 2019 5-year at the 2020 origin | Period ends before the cutoff; not released until 2020-12-10 |
| ACS 2020 5-year at the 2021 and 2022 origins | Same, and its release date is not established by this project |
| ACS 2021 5-year at the 2022 origin | Not released until 2022-12-08 |
| Home charging access (`nrel_home_charging`) | Single undated NREL vintage, and Phase 0 established it is a parametric scenario surface rather than a dated observation |
| Sub-state registration panels (Atlas, WA) | Every one is a *current* download with no retrievable 2019–2021 edition; fitting on them would learn coefficients from post-cutoff outcomes |
| Existing charger features (`afdc_charging_units`) | Forbidden by **D2** at every cutoff — not by vintage |
| Current HUD ZIP→tract crosswalk | **Not used at any historical origin** |
| TIGER 2024 road network | The Phase 4 road filter is **not** applied to any historical ranking; TIGER 2024 postdates every cutoff |

On the two the brief singled out:

- **HUD crosswalk.** Rather than justify the current crosswalk as stable geography
  infrastructure, the backtest is built so the question does not arise: it fits at state level
  and allocates tracts to cells directly, so no ZIP→tract transformation happens at any origin.
- **Present-day supply.** Excluded by directive, not by vintage. The recorded reason says so,
  and `test_p5_c_supply_features_are_excluded_by_directive_not_only_by_vintage` asserts it —
  because excluding them "because of vintage" would be the wrong reason and would silently
  permit them at an origin where a contemporaneous edition existed.

### 5.4 The backtested model is not the deployed model

§10.2.3 requires this stated with every difference listed.

| | Deployed (Phase 3) | Backtest (Phase 5) |
|---|---|---|
| Fitted on | sub-state panels: 1 tract-native, 11 ZIP-grain, 4 county-grain states | **51 state-level observations** |
| Feature vintage | ACS 2024 5-year | ACS 2018 or 2019 |
| Tract geography | 2020 census tracts | **2010** census tracts |
| Reconciliation | county totals where complete, else state totals | cutoff-valid state totals only |
| Evidence grain | four values | **`state_total_only` everywhere** |
| Population weights | CenPop2020 block group | **CenPop2010** block group |

**Why the fit is at state level.** The deployed model learns its coefficients from sub-state
registration panels, every one of which is a current download with no retrievable 2019–2021
edition. Fitting the backtest on them would hand it the answer. What *does* exist at each
cutoff is the AFDC annual state registration series, so the backtest fits the same Poisson
specification on 51 state observations — features aggregated household-weighted to state
level — and applies it at tract grain, then reconciles.

That is a weaker model than the deployed one, and it should be: it is the model a person
standing at that cutoff could actually have built. Its weakness is a property of the
historical record, not a shortcut. Reconciliation is exact at every origin: maximum absolute
error per state **0.0**.

### 5.5 The target is an approximate reconstruction

Domain rules **G10** and **G11**. From 292,756 charging-unit rows: 82,056 distinct public
operational stations, **81,836 placed** on the grid. Dropped and counted by reason: 6,649 rows
not operational, 29,649 not public, 220 stations with no open date, 0 unparseable, 0 without
coordinates.

A current snapshot plus `Open Date` cannot recover stations that closed, left the feed, or
changed port counts. Survivorship bias grows with age, so the 2020 origin is the least
trustworthy of the three.

### 5.6 How much there was to predict

| Origin | Deployments in window | Ports | DCFC ports | Jurisdictions | Cells ranked |
|---|---:|---:|---:|---:|---:|
| 2020 | 18,189 | 46,220 | 9,633 | 52 | 50,756 |
| 2021 | 22,168 | 58,962 | 12,015 | 52 | 50,756 |
| 2022 | 20,533 | 63,616 | 17,622 | 52 | 50,756 |

### 5.7 Results

**Top-decile capture — share of subsequent stations falling in the top 10% of ranked cells:**

| Ranking | 2020 | 2021 | 2022 |
|---|---:|---:|---:|
| **Model** (cutoff-valid demand) | 0.6452 | 0.6216 | 0.5713 |
| Population baseline | **0.7766** | **0.7554** | **0.7063** |
| Existing-network baseline | 0.4236 | 0.4694 | 0.4472 |
| Random baseline | 0.0687 | 0.1050 | 0.0991 |

**Lift:**

| Origin | vs random (stations) | vs population (stations) | vs random (ports) | vs population (ports) |
|---|---:|---:|---:|---:|
| 2020 | **9.40** | **0.83** | 9.19 | 0.82 |
| 2021 | **5.92** | **0.82** | 5.49 | 0.79 |
| 2022 | **5.77** | **0.81** | 5.94 | 0.78 |

**Full gain curve, model, 2020 origin** (stations / ports / DCFC ports captured):

| Decile | Cells | Stations | Ports | DCFC ports |
|---:|---:|---:|---:|---:|
| 0.1 | 5,076 | 0.6452 | 0.6307 | 0.4539 |
| 0.2 | 10,151 | 0.7044 | 0.6877 | 0.5330 |
| 0.3 | 15,227 | 0.7327 | 0.7140 | 0.5719 |
| 0.5 | 25,378 | 0.7634 | 0.7442 | 0.6210 |
| 0.7 | 35,529 | 0.8282 | 0.8119 | 0.7204 |
| 1.0 | 50,756 | 0.9754 | 0.9697 | 0.9170 |

Ports and DCFC ports are reported alongside station counts because a station record is one
network's presence at a site, not a unit of capacity (**G1**).

### 5.8 The headline finding is negative, and it is reported as such

**The model beats random by 5.8–9.4× and loses to a plain population ranking at every one of
the three origins**, by a consistent margin. Ranking cells by resident population predicts
where chargers actually got built better than the cutoff-valid demand model does.

Nothing was tuned in response to this. Reading it carefully:

- **It does not mean the demand model is worthless.** It means that for the question *"where
  did industry build next"*, population is the stronger predictor. Operators build where
  people are.
- **It is consistent with the project's purpose.** A model that *beat* population here would
  be evidence it had learned industry's deployment habits — which is what D2 exists to
  prevent, and what §18 anti-pattern 2 warns to expect.
- **It is not a measurement of the deployed model's accuracy.** The backtested model is
  deliberately weaker (§5.4). Demand model validation is §7.
- **What the model does beat** is the existing-network baseline — 0.57–0.65 against
  0.42–0.47 — which is the ranking that says "build where infrastructure already is".

**Sensitivity across origins:** stable. The ordering holds at all three; lift against random
falls from 9.40 to 5.77 as the window moves later, reflecting deployments spreading into more
cells as the network grew rather than a change in model quality. Weight conclusions toward the
**2022** origin: least survivorship bias.

### 5.9 Confounding that prevents stronger claims

- Deployment is driven by real estate, grant programmes, utility relationships and network
  strategy. None is in the model; none is observable in this data.
- The NEVI programme allocated federal funding along designated corridors during the 2022
  window. Corridor deployment is a policy artefact, not a demand signal.
- Survivorship bias grows with age (G11).
- **A-0.5 remains unresolved.** Phase 1 established the AFDC annual registration pages are
  *stable* — 52 of 52 jurisdictions identical between 2022-08-18 and 2026-08-24 for both the
  2020 and 2021 vintages — but **not** that they are *contemporaneous*, because no capture
  predates 2022-08-18. If AFDC reconstructed the annual series retrospectively from later VIN
  data, a "2019 vintage" used at a 2020 cutoff carries information that did not exist in 2020.
  This cannot be ruled out and is not claimed to be. The caveat is carried on every
  registration vintage in the artifact, and `test_p5_c_the_a_0_5_contemporaneity_limitation_is_stated`
  asserts it is published.
- The full ranking captures 0.9754 rather than 1.0 at the 2020 origin: about 2.5% of
  deployments landed in cells with no resident population, which are excluded from every
  ranking because an uninhabited cell is not a siting candidate under any model.

---

## 6. Cross-objective robustness

Six objectives, four baselines, six frontier states, three budgets — 18 scored problems.

### 6.1 The six objectives

`population_served`, `demand_covered`, `equity_coverage`, `accessibility_improvement`,
`estimated_utilisation`, `cost_efficiency`. Each ships its **definition** in the artifact, not
only its name, so a reader can check what was measured rather than trust a label. Two carry
explicit disclaimers: `equity_coverage` states it is one named ACS indicator and **not** a
composite index; `estimated_utilisation` states it is a crude throughput proxy and **not** a
queueing result.

### 6.2 The four baselines

`population_weighted`, `demand_only`, `existing_network_proximity`, `random` — all fixed
before any result was seen, `random` seeded so it reproduces.

### 6.3 Result: an exposed tradeoff

Washington at 20 sites, as a share of the best portfolio's score on each objective:

| Portfolio | population | demand | equity | accessibility | utilisation | cost-eff |
|---|---:|---:|---:|---:|---:|---:|
| `epsilon_demand_first` | 0.970 | **1.000** | 0.796 | **1.000** | **1.000** | **1.000** |
| `epsilon_equity_first` | **1.000** | 0.819 | **1.000** | 0.746 | 0.819 | 0.819 |
| `greedy_demand` | 0.955 | 0.991 | 0.788 | 0.987 | 0.991 | 0.991 |
| `baseline_population_weighted` | 0.827 | 0.745 | 0.774 | 0.638 | 0.745 | 0.745 |
| `baseline_demand_only` | 0.600 | 0.759 | 0.505 | 0.645 | 0.759 | 0.759 |
| `baseline_existing_network_proximity` | 0.424 | 0.528 | 0.395 | 0.303 | 0.528 | 0.528 |
| `baseline_random` | 0.209 | 0.109 | 0.214 | 0.161 | 0.109 | 0.109 |

**The tradeoff is the finding.** A demand-first portfolio reaches only **79.6%** of the best
equity coverage; an equity-first portfolio reaches only **81.9%** of the best demand coverage.
Neither dominates. Tennessee is starker: demand-first reaches 72.9% of best accessibility,
equity-first 58.0% of best demand.

**"The optimiser wins on its own objective" is circular and is not reported as a finding.**
The interesting cells are the ones the optimiser never saw, and they show a real cost.

### 6.4 Where the optimised portfolios lose

They do not lose to any of the four baselines on any of the six objectives at budget 20 —
which is the least interesting part of the table. They lose to **each other**, which is the
tradeoff above. The ε-constraint frontier *is* that surface, and this project does not declare
a winner on it; that is why the interactive surface exposes weight sliders rather than
shipping one blessed portfolio.

---

## 7. Demand model validation

**Restated from Phase 3, not re-fitted.** Phase 5 validates the model; it is not licence for a
post-hoc bakeoff, and re-running estimator selection here would be exactly that. The figures
are read from `docs/evidence/P3-2_demand_model.json` so the two cannot drift.

**Aggregate weighted WAPE**, reported both unreconciled and reconciled, as the brief required:

| Estimator | Unreconciled | State-total reconciled |
|---|---:|---:|
| **`poisson_glm`** (selected) | **0.380904** | **0.320309** |
| `boosted_poisson` | 0.416467 | 0.329409 |
| `ridge_log_rate` | 0.433045 | 0.376324 |
| `baseline_population_share` | 0.800568 | 0.705842 |
| `baseline_household_share` | 0.802679 | 0.708315 |

**Independent validation states (14):** CO, CT, ME, MN, MT, NC, NJ, NM, NY, OR, TN, TX, VA,
VT. **Washington is excluded** from the independent headline aggregate as
`non_independent_preprocessing_selection_state`: it is the only tract-native registry and the
model saw it during development. Its uncertainty calibration curve is a **diagnostic**, marked
`is_empirical_calibration: false` in the artifact's own key.

**No supply-derived feature is in the primary feature set** — enforced structurally by
execution, not by name matching. The supply-feature ablation is run and reported separately.

---

## 8. Independent validation versus diagnostic evidence

| Conclusion | Status |
|---|---|
| Leave-one-state-out accuracy across the 14 states excluding Washington | **Independent validation** |
| Washington uncertainty calibration curve | **Diagnostic.** Washington is training evidence |
| Historical deployment alignment | **Independent** of the deployed model's fit, but it validates a *different, weaker* model (§5.4) and measures agreement with industry behaviour, not correctness |
| Cross-objective robustness | **Diagnostic of tradeoff structure.** Not evidence any portfolio is correct |
| Any statement that a site is optimal | **Not supported by anything here** |

---

## 9. Two defects found and fixed during Phase 5

Neither is an upstream Phase 0–4 correctness defect; both are recorded in
`docs/reports/IMPACT_LOG.md`.

**I-21 — a positional read of the retained-vintage list.** Phase 3's "what changed between
consecutive ACS releases" diagnostic took the preceding vintage as
`HISTORICAL_ACS_YEARS[0]`. That list is ordered oldest-first, so when Phase 5 added the 2018
and 2019 vintages, the diagnostic silently became a 2018-against-2024 comparison spanning the
2010/2020 tract-geography break — a different question, with a 250,000-line answer. Fixed by
naming `ACS_PREVIOUS_YEAR = 2023` explicitly. The Phase 3 artifact returned to a two-line diff.
Severity **S3**: the diagnostic had not been published in its broken form.

**I-22 — the copy lint could not permit the project's own caveat.** The D3 rules match
phrases, not meaning, so "ground truth for optimal siting does not exist" trips the rule
forbidding optimality claims. The pressure that creates is to soften the disclaimer to appease
the linter, which is exactly backwards. Extended in Phase 5 (§15.5 anticipates this) with a
**three-entry exact-phrase list** of sanctioned disclaimers, not a negation detector — a
negation detector would have to understand scope and would quietly widen over time. A match is
forgiven only when it falls *inside* one of those phrases, and
`test_a_claim_on_the_same_line_as_a_disclaimer_is_still_caught` proves a caveat cannot shield
a claim beside it. A further test asserts every listed phrase actually trips a rule — it found
nine dead entries in my first draft, which were removed.

---

## 10. Gate

`make gate PHASE=5`, the authoritative Phase 5 gate, under the optimised protocol accepted in
Phase 4 (amendments A25/A26): one coverage-instrumented full-suite run satisfying both G-A and
G-B, then every prior phase's gate suite replayed individually.

**G-C, prior-phase suites replayed:**

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
    tests/regression/test_gate_protocol.py               PASS  49 passed
    tests/integration/test_smoke_forward_phase4.py       PASS  5 passed
    all prior-phase gate suites PASS
```

**G-D forward viability.** `tests/integration/test_smoke_forward_phase5.py` proves Phase 6's
Methodology and Validation view can be rendered from `P5-1_validation.json` alone: gain curves
plot as ten ready (x, y) pairs per ranking, the robustness table renders as portfolios ×
objectives already normalised to the best score, every alignment number carries the caveat it
must be displayed with, and the copy lint passes over the artifact's own strings — checked by
importing the lint's rules rather than restating them, so the test cannot drift from them.

---

## 11. Assumptions and limitations introduced

| ID | Statement | Status |
|---|---|---|
| **A-5.1** | The AFDC annual state registration page for year Y was available in January Y+1 | OPEN — assumed, not verified; and A-0.5's contemporaneity question sits underneath it |
| **A-5.2** | A state-level Poisson fit on 51 observations is a fair reconstruction of what a modeller could have built at each cutoff | OPEN — it is *a* defensible reconstruction, not the only one |
| **A-5.3** | Scoring on H3 cells makes the 2010/2020 tract-geography break immaterial to the ranking metrics | OPEN — argued from cell stability; not measured against a 2020-geography backtest, which cannot be built at these cutoffs |
| **A-0.5** | AFDC annual pages are contemporaneous snapshots | **STILL OPEN.** Phase 5 states the limitation as §15.5 requires |

**Known limitation, stated plainly:** the ACS 2020 5-year release date was not verified
against a primary source. The conservative choice was taken, so this cannot have caused
leakage — but it means the 2022 origin uses features two years older than it might legitimately
have been allowed.

---

## Correction — 2026-08-31

Appended, not merged: §§1–11 above are the original submission and are left as written, so
the audit trail survives. Five bounded external-review items. **No model, metric, ranking or
parameter was changed**, and the negative population-baseline result stands.

Where a number below differs from one above, **the number below is the current one**.

### C.1 The interpretation of the population result — corrected

**Withdrawn.** §5.8 argued that a model *beating* population would have shown it had learned
industry deployment habits, and that losing to population therefore vindicated directive D2.
That inference does not hold. D2 is a constraint on which **features** may enter the demand
model, and it is enforced by a test on the feature set — not by a ranking outcome. A model
could outperform population for many reasons unrelated to reproducing industry behaviour, and
underperform it for reasons unrelated to D2.

**The narrow conclusion, which is the only one this result supports:**

> The model strongly outperforms random and the existing-network baseline but does not
> outperform population for reproducing subsequent industry deployment locations at any
> origin. This is a negative historical-deployment-alignment result, not evidence of siting
> failure and not itself evidence for or against D2.

`docs/VALIDATION.md` §2.7 carries the corrected wording.

### C.2 The 2020 random lift — reconciled, and a real defect found

**The question.** A 2020 top-decile capture of 0.645 with random lift 9.40× implies random
capture ≈ 0.0686, against ≈ 10% at 2021/2022. Why?

**Capture mechanics, as asked:**

| | |
|---|---|
| **Capture denominator** | *All* subsequent deployments in the window, including any landing outside the ranked cells. A deployment in an unranked cell is a **miss for every ranking**, not an exclusion for some — which is why full-ranking capture is below 1.0 by exactly the share that fell outside |
| **Top-decile construction** | `round(0.1 × len(ranked_cells))` cells from the head of the ranking; ties broken by cell id, so deterministic. 5,076 of 50,756 cells |
| **Random sampling universe** | The same ranked cells, permuted |
| **Same support for every baseline?** | **Yes.** Asserted in the gate: all four rankings have identical full-ranking capture |
| **Deployments inside the ranked universe** | 0.9754 / 0.9718 / 0.9681 at 2020 / 2021 / 2022 |
| **Cells dropped as uninhabited** | 382 at every origin, leaving 50,756 |

**So it was not support coverage** — the support barely moves between origins.

**It was sampling noise in the baseline itself.** Each random baseline was a **single seeded
permutation**. That is unbiased but high-variance, because deployment counts are heavily
concentrated. Measured over 400 draws at the 2020 origin: mean **0.0976**, standard deviation
**0.0137**, 5th percentile 0.0759. The shipped single-seed draw of **0.0687 sat at percentile
0** — outside the 5–95 band. The 2021 and 2022 draws sat at percentiles 76 and 64.

**Repair.** The random baseline is now the **mean over 200 draws**, with its spread published
alongside. This is still an *empirical* random baseline — not a theoretical one-tenth — as the
review required; it is simply a far less noisy estimator of the same quantity.

| Origin | Random capture (was, 1 draw) | Random capture (now, 200-draw mean) | Lift vs random (was) | **Lift vs random (now)** |
|---|---:|---:|---:|---:|
| 2020 | 0.0687 | 0.0961 | 9.40 | **6.72** |
| 2021 | 0.1050 | 0.0973 | 5.92 | **6.39** |
| 2022 | 0.0991 | 0.0969 | 5.77 | **5.89** |

Random capture is now consistent across origins, as the near-identical support implies it
should be, and the trend in lift is smooth. **This reduced the model's headline advantage at
2020 from 9.40× to 6.72×.** The model, its features and its ranking are untouched; only a
noisy baseline was replaced with a better-estimated one.

**Lift against population is unchanged: 0.83 / 0.82 / 0.81.** The negative result stands.

Since the cause was baseline variance rather than candidate coverage, it does **not** enter
the per-origin reconstruction-confidence discussion, which remains about survivorship bias.

### C.3 §10.2.4 infrastructure quantities — ports were present, capacity was not

Ports and DCFC ports were already reported per decile and per ranking
(`share_of_subsequent_ports_captured`, `share_of_subsequent_dcfc_ports_captured`).
**Capacity in kW was absent**, so it was added under existing G1 semantics: non-overlapping
generic service capacity (§7.1.1), resolved through Phase 2's own power ladder — reported →
empirical median → documented type default — with a unit's capacity the **maximum** of its
mutually alternative connector outputs, never their sum. Phase 2's `resolve_all` and
`build_unit_capacities` are reused rather than restated, so the two cannot drift.

New artifact fields: `subsequent_deployment_capacity_kw` per origin,
`top_decile_capture_capacity_kw` per ranking, and
`share_of_subsequent_capacity_kw_captured` at every decile.

| Origin | Capacity deployed (kW) | Model | Population | Existing-network | Random |
|---|---:|---:|---:|---:|---:|
| 2020 | 2,471,663 | 0.4797 | 0.6365 | 0.3231 | 0.0924 |
| 2021 | 3,142,231 | 0.4842 | 0.6235 | 0.3795 | 0.0938 |
| 2022 | 4,370,222 | 0.4944 | 0.6149 | 0.4149 | 0.0941 |

**This is retrospectively reconstructed capacity, not known installation-time capacity.**
The power values are read from the **current** AFDC snapshot and attributed to each station's
open date. A station later upgraded — 50 kW to 350 kW, or ports added — carries its *present*
power here, not the power it had when it opened, because the snapshot records no history
(**G10**, **G11**). Stations that closed or left the feed are absent entirely. The bias runs
toward **overstating** the capacity of older deployments and grows with age — the same
direction and the same cause as the survivorship bias on the station count itself, so the 2020
origin's capacity figures are the least trustworthy of the three. Every published capacity
figure carries this basis string in the artifact.

A `capacity_kw_basis` string carrying that statement is attached to every capacity figure in
the artifact — the per-origin total, each ranking's top-decile capture, and every decile of
every gain curve — so a reader of the JSON alone cannot mistake it for installed-at-the-time
capacity. `test_p5_g_capacity_is_labelled_retrospectively_reconstructed` asserts it is present
on all of them.

**A finding this exposed:** the model captures materially less **capacity** than **station
count** — 0.48–0.49 against 0.57–0.65. Its top decile skews toward cells that received many
small stations rather than high-power sites. The ordering against the baselines is unchanged,
and population still leads on capacity too. Because the reconstruction overstates older
capacity, this gap is a lower bound on the effect rather than a precise measure of it.

### C.4 Historical road-filter vintage — audited, no leakage

**No road geometry of any vintage enters any historical origin.** For each of 2020, 2021 and
2022 the artifact now carries `road_filter_vintage: "none - no road geometry enters this
origin"` and a `road_filter_audit` string.

The Phase 4 candidate road-proximity filter uses **TIGER/Line 2024**, which postdates every
cutoff, and no earlier TIGER edition was retrieved. The filter is therefore **not applied**
and **no substitute is used**: the historical ranking scores every inhabited cell by
cutoff-valid modelled demand. Current or future road geometry cannot enter a historical origin
by any path — `historical_cells` and `align_origin` import nothing from
`pipeline.sources.tiger_roads` or `pipeline.spatial.road_proximity`.

This is now enumerated as a **backtest-versus-production difference** in the §2.4 table of
`docs/VALIDATION.md`, alongside the feature-vintage, geography, fit and reconciliation
differences. Two tests assert it:
`test_no_road_geometry_of_any_vintage_enters_a_historical_origin` and
`test_p5_g_no_road_geometry_enters_any_historical_origin`.

### C.5 ACS 2020 release date — closed

Recorded: the 2016–2020 ACS 5-year estimates were released **2022-03-17**.
`release_date_certain` is now **true**.

This is after the 2022-01-01 cutoff, so **vintage selection and every result are unchanged**:
the origins still resolve to ACS 2018 / 2019 / 2019. What changed is the *reason* the edition
is excluded — it demonstrably did not exist at the cutoff, rather than its availability being
unshowable. The conservative "resolve toward the older vintage" fallback remains in the code
for any vintage whose date is genuinely unestablished; **A-5.4 is now CLOSED**.

The stable-H3 treatment of the 2010→2020 tract-geography break is retained. The absolute
wording is replaced throughout with:

> 2020 tract geography was not contemporaneously available for these prediction cutoffs;
> retrospective harmonization would require later boundary/crosswalk information, so Core
> evaluates stable H3 cells using cutoff-appropriate 2010-geography inputs.

A harmonised comparison is possible in principle using a later crosswalk — but that crosswalk
is itself post-cutoff information, so it would answer a different question than the one D1
permits at these origins. A-5.3 stays **OPEN** with that reasoning recorded.

**A-0.5 was not reopened and no new source research was conducted.**

### C.6 What was re-run

`make gate PHASE=5`, the single authoritative gate, with the Phase 5 validation artifact
regenerated. Six new gate checks (`test_p5_g_*`) cover the corrections.
