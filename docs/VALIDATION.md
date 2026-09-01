# Validation

Three validation terms. They are distinct, they answer different questions, and CLAUDE.md
directive **D3** forbids blurring them in code, docs, UI copy or commit messages.

| Term | What it evaluates | Method |
|---|---|---|
| **Demand model validation** | Whether tract-level EV estimates are accurate | Leave-one-state-out against observed states |
| **Historical deployment alignment** | Whether priority areas match where industry actually built | Vintage-enforced rolling-origin backtest |
| **Cross-objective robustness** | Whether a portfolio optimised for one objective also performs on others | ε-constraint Pareto analysis and cross-scoring |

**None of these demonstrates that a site is optimal.** Ground truth for optimal siting does
not exist. No code comment, docstring or UI string may claim optimality validation.

Every number below is reproduced by `make phase5`, which reads only cached responses and
writes `docs/evidence/P5-1_validation.json`.

---

## 1. Temporal leakage is the primary correctness constraint

Directive **D1**: any feature used in a backtest carries a `feature_vintage`, and the
harness asserts `feature_vintage <= prediction_cutoff` at runtime, raising on violation.

### 1.1 Two dates, not one

A data product has a **period** — what span of reality it describes — and a **release
date** — when a person could first have obtained it. The ACS 2019 5-year estimates describe
2015–2019 but were not published until 10 December 2020. A backtest at a 2020-01-01 cutoff
that used them would be using information nobody had, even though the period ends before
the cutoff.

**Availability is governed by the release date.** `SourceVintage` refuses to exist without
one, and refuses a release date earlier than the period it describes.

### 1.2 Uncertainty resolves toward exclusion

Where a release date is not established with confidence, the harness uses the **older**
vintage whose date is certain. Choosing the older edition can never manufacture leakage;
choosing the newer one can. Each such decision is recorded on the vintage itself.

This binds once, on the ACS 2020 5-year release. It is widely reported to have slipped from
December 2021 to March 2022 because of pandemic collection problems, which would put it on
the wrong side of the 2022-01-01 cutoff — but **this project has not verified that date
against a primary source**, so it is declared `release_date_certain: false` and the 2022
origin falls back to ACS 2019.

### 1.3 The negative test

`tests/unit/test_vintage_guard.py::test_a_deliberately_poisoned_feature_set_raises`
constructs a clean feature set, asserts it passes, then appends one feature dated
2024-12-31 against a 2021-01-01 cutoff and asserts `LeakageError` is raised naming that
feature. `LeakageError` subclasses `AssertionError` so nothing in the pipeline can catch it
and continue. **It passes.**

---

## 2. Historical deployment alignment

### 2.1 What this asks, and what it does not

**Asks:** did the model assign higher priority to locations where charging infrastructure
was subsequently deployed?

**Does not establish:**

- that historical deployments were optimal;
- that the model identifies causally correct siting decisions;
- that operators should have followed the model;
- that any future selected site is validated as optimal.

Charge point operators build on real-estate availability, grant programmes, utility
relationships, commercial strategy, highway contracts and network expansion plans. **High
alignment may mean the model reproduces industry behaviour including its biases** — the
opposite of a good result for a system whose purpose is to find underserved areas. That
caveat ships inside every alignment record in the artifact, not only in this document.

### 2.2 The origins, and what each was allowed to see

| Origin | Prediction cutoff | Evaluation window | ACS vintage | Released | Tract geography | State registrations |
|---|---|---|---|---|---|---|
| 2020 | 2020-01-01 | 2020-01-01 → 2022-01-01 | ACS 2018 5-year (2014-2018) | 2019-12-19 | **2010** | AFDC 2019 |
| 2021 | 2021-01-01 | 2021-01-01 → 2023-01-01 | ACS 2019 5-year (2015-2019) | 2020-12-10 | **2010** | AFDC 2020 |
| 2022 | 2022-01-01 | 2022-01-01 → 2024-01-01 | ACS 2019 5-year (2015-2019) | 2020-12-10 | **2010** | AFDC 2021 |

**All three origins land on 2010 census tract geography**, while the production surface is
2020 geography. ACS releases through 2019 are published on 2010 boundaries and the 2020
release onward on 2020 boundaries — measured on the live API, Vermont returns 184 tracts for
2018 and 2019 and 193 for 2020 and 2021; nationally, 74,001 tracts in the 2019 gazetteer
against 85,396 in the 2023 one.

The backtest is therefore scored on **H3 resolution-6 cells**, which do not move when the
Census redraws tracts, using contemporaneous **CenPop2010** block-group population weights
and the contemporaneous 2019 gazetteer for land area. Every §10.2.4 metric is a cell-ranking
metric, so nothing is lost.

### 2.3 Features excluded from every historical origin

| Feature / source | Reason |
|---|---|
| **ACS 2019 5-year** at the 2020 origin | Period ends before the cutoff, but not released until 2020-12-10 — nobody had it |
| **ACS 2020 5-year** at the 2021 and 2022 origins | Same, and its release date is not established by this project (§1.2) |
| **ACS 2021 5-year** at the 2022 origin | Not released until 2022-12-08 |
| **Home charging access** (`nrel_home_charging`) | Single undated NREL vintage, and Phase 0 established it is a parametric scenario surface rather than a dated observation, so no cutoff-appropriate edition exists |
| **Sub-state registration panels** (Atlas, WA) | Every one is a *current* download; none publishes a 2019–2021 edition. Fitting on them would learn coefficients from post-cutoff outcomes |
| **Existing charger features** (`afdc_charging_units`) | Forbidden by directive **D2** at every cutoff — not by vintage. Supply is an outcome of prior investment; predicting demand from it launders historical deployment into "need" |
| **Current HUD ZIP→tract crosswalk** | **Not used at any historical origin.** The backtest fits at state level and allocates tracts to cells directly, so no ZIP→tract transformation occurs and the question of whether a current crosswalk counts as stable geography infrastructure does not arise |
| **TIGER 2024 road network** | The Phase 4 road-proximity candidate filter is **not** applied to any historical ranking. TIGER 2024 postdates every cutoff |

### 2.4 The backtested model is not the deployed model

§10.2.3 requires this stated with every difference listed.

| | Deployed (Phase 3) | Backtest (Phase 5) |
|---|---|---|
| Fitted on | sub-state panels: 1 tract-native, 11 ZIP-grain, 4 county-grain states | **51 state-level observations** |
| Feature vintage | ACS 2024 5-year | ACS 2018 or 2019 |
| Tract geography | 2020 census tracts | **2010** census tracts |
| Reconciliation | county totals where complete, else state totals | cutoff-valid state totals only |
| Evidence grain | `native_tract` / `zip_anchored` / `county_anchored` / `state_total_only` | **`state_total_only` everywhere** |
| Population weights | CenPop2020 block group | **CenPop2010** block group |

**Why the fit is at state level.** The deployed model learns coefficients from sub-state
registration panels, every one of which is a current download with no retrievable 2019–2021
edition. Fitting the backtest on them would hand it the answer. What *does* exist at each
cutoff is the AFDC annual state registration series, so the backtest fits the same Poisson
specification on 51 state observations and applies it at tract grain. That is a weaker model
than the deployed one, and it should be: it is the model a person standing at that cutoff
could actually have built.

### 2.5 The target is an approximate reconstruction

Domain rules **G10** and **G11**. A current snapshot plus `Open Date` cannot recover stations
that closed, left the feed, or changed port counts, so the reconstructed pre-cutoff network is
survivorship-biased and the bias grows with age. `Open Date` is documented as approximate and,
for automated network feeds, may record first appearance in the Station Locator rather than
actual opening.

From 292,756 charging-unit rows: 82,056 distinct public operational stations, of which
**81,836 were placed** on the grid. Dropped and counted: 6,649 rows not operational, 29,649
not public, 220 stations with no open date, 0 unparseable, 0 without coordinates.

### 2.6 Results

Top-decile capture of subsequent deployments, and lift against each baseline.

| Origin | Deployments in window | Ports | DCFC ports | States |
|---|---:|---:|---:|---:|
| 2020 | 18,189 | 46,220 | 9,633 | 52 |
| 2021 | 22,168 | 58,962 | 12,015 | 52 |
| 2022 | 20,533 | 63,616 | 17,622 | 52 |

**Top-decile capture (share of subsequent stations in the top 10% of ranked cells):**

| Ranking | 2020 | 2021 | 2022 |
|---|---:|---:|---:|
| **Model** (cutoff-valid demand) | 0.6452 | 0.6216 | 0.5713 |
| Population baseline | **0.7766** | **0.7554** | **0.7063** |
| Existing-network baseline | 0.4236 | 0.4694 | 0.4472 |
| Random baseline | 0.0687 | 0.1050 | 0.0991 |

**Lift (stations):**

| Origin | vs random | vs population |
|---|---:|---:|
| 2020 | **9.40** | **0.83** |
| 2021 | **5.92** | **0.82** |
| 2022 | **5.77** | **0.81** |

### 2.7 The headline finding is negative, and it is reported as such

**The model beats random by 5.8–9.4×, and loses to a plain population ranking at every one
of the three origins**, by a consistent margin (lift 0.81–0.83 on stations, 0.78–0.82 on
ports). Ranking cells by resident population predicts where chargers actually got built
better than the cutoff-valid demand model does.

This is a result, not a failure to hide, and nothing was tuned in response to it. Reading it
carefully:

- **It does not mean the demand model is worthless.** It means that for the question *"where
  did industry build next"*, population is a stronger predictor than modelled BEV demand. That
  is unsurprising: operators build where people are, and a demand model that merely reproduced
  population would have no reason to exist.
- **It is consistent with the project's stated purpose.** §18 anti-pattern 2 warns that high
  alignment may mean the model reproduces industry bias. A model that *beat* population here
  would be evidence it had learned industry's deployment habits, which is what directive D2
  exists to prevent.
- **The backtested model is deliberately weaker than the deployed one** (§2.4). It is fit on
  51 state observations rather than sub-state panels. This result is not a measurement of the
  deployed model's accuracy — that is §3.
- **What the model does beat** is the existing-network baseline (0.57–0.65 against 0.42–0.47),
  which is the ranking that says "build where infrastructure already is".

### 2.8 Sensitivity across origins, and confounding

Conclusions are **stable across all three origins**: the ordering (population > model >
existing-network > random) holds at every one, and every figure moves monotonically and
mildly with the cutoff. Lift against random falls from 9.40 to 5.77 as the window moves later,
which reflects deployments spreading into more cells as the network grew rather than a change
in model quality.

Weight conclusions toward the **2022** origin: it has the least survivorship bias.

**Confounding that prevents stronger causal claims:**

- Deployment is driven by real estate, grants, utility relationships and network strategy.
  None is in the model, and none is observable in this data.
- The NEVI programme allocated federal funding along designated corridors during the 2022
  window. Corridor deployment is a policy artefact, not a demand signal.
- Survivorship bias grows with age (G11), so the 2020 origin's pre-cutoff network is the
  least trustworthy.
- **A-0.5 is unresolved.** Phase 1 established the AFDC annual registration pages are
  *stable* — 52 of 52 jurisdictions identical between 2022-08-18 and 2026-08-24 for both the
  2020 and 2021 vintages — but **not** that they are *contemporaneous*, because no capture
  predates 2022-08-18. If AFDC reconstructed the annual series retrospectively from later VIN
  data, a "2019 vintage" used at a 2020 cutoff carries information that did not exist in 2020.
  This cannot be ruled out and is not claimed to be.
- The full ranking captures 0.9754 of 2020 deployments rather than 1.0: about 2.5% landed in
  cells carrying no resident population, which are excluded from every ranking because an
  uninhabited cell is not a siting candidate under any model.

---

## 3. Demand model validation

**Restated from Phase 3, not re-fitted.** Phase 5 validates the model; it is not licence for
a post-hoc bakeoff, and re-running estimator selection here would be exactly that. The
figures are read from `docs/evidence/P3-2_demand_model.json` so the two cannot drift.

- **Protocol:** leave-one-state-out across every sub-state anchored state, reported at each
  held-out state's **native** observed granularity. A ZIP→tract allocation is not tract-level
  ground truth and is not reported as if it were.
- **Washington** is development/training evidence and is **excluded from the independent
  headline validation aggregate**: it is the only tract-native registry and the model saw it
  during development. Its calibration curve is a **diagnostic**, not empirical calibration,
  and is labelled that way in the artifact's own key.
- **No supply-derived feature is in the primary feature set.** Enforced structurally by
  execution rather than by name matching: the feature functions are run against a recording
  row that reports every key they touch, and any key outside the ACS variable list plus
  `land_area_km2` fails the check.
- The supply-feature **ablation** is run and reported separately, never mixed into the
  primary result.

---

## 4. Cross-objective robustness

Optimise a portfolio on **one** objective, then score it on objectives that were **never in
the loss function**.

**"The optimiser wins on its own objective" is not a result.** It is circular, and §10.3
forbids reporting it as a finding. What is informative is either cross-objective robustness
or an exposed tradeoff, and **both are publishable**.

### 4.1 The six objectives

| Objective | Definition |
|---|---|
| `population_served` | Resident population of every covered cell, counted once per cell |
| `demand_covered` | Modelled BEV demand in every covered cell |
| `equity_coverage` | Population in households under $35,000/year — **one named ACS indicator, not a composite index and not a general measure of disadvantage** |
| `accessibility_improvement` | Demand in covered cells that had **no** existing public operational DCFC port; the part of coverage that changes access rather than reinforcing it |
| `estimated_utilisation` | Covered demand per selected site. A crude throughput proxy, **not a queueing result** — Erlang C and the discrete-event check are Extension tier E1 |
| `cost_efficiency` | Demand covered per unit of portfolio cost. Cost is uniform per site because no cost model exists (§7.11 Optional), so this is currently demand per site; assumption A-4.4 applies |

### 4.2 The four baselines

`population_weighted`, `demand_only`, `existing_network_proximity`, `random`. All four were
fixed before any result was seen, and `random` is seeded so it reproduces.

### 4.3 Result: an exposed tradeoff, not blanket robustness

Six frontier states × three budgets (5, 20, 50) = 18 scored problems. Taking Washington at 20
sites, as a share of the best portfolio's score on each objective:

| Portfolio | population | demand | equity | accessibility | utilisation | cost-eff |
|---|---:|---:|---:|---:|---:|---:|
| `epsilon_demand_first` | 0.970 | **1.000** | 0.796 | **1.000** | **1.000** | **1.000** |
| `epsilon_equity_first` | **1.000** | 0.819 | **1.000** | 0.746 | 0.819 | 0.819 |
| `greedy_demand` | 0.955 | 0.991 | 0.788 | 0.987 | 0.991 | 0.991 |
| `baseline_population_weighted` | 0.827 | 0.745 | 0.774 | 0.638 | 0.745 | 0.745 |
| `baseline_demand_only` | 0.600 | 0.759 | 0.505 | 0.645 | 0.759 | 0.759 |
| `baseline_existing_network_proximity` | 0.424 | 0.528 | 0.395 | 0.303 | 0.528 | 0.528 |
| `baseline_random` | 0.209 | 0.109 | 0.214 | 0.161 | 0.109 | 0.109 |

**The tradeoff is real and it is the finding.** A demand-first portfolio reaches only 79.6%
of the best equity coverage; an equity-first portfolio reaches only 81.9% of the best demand
coverage. Neither dominates. The ε-constraint frontier *is* that tradeoff surface, and this
project does not declare a winner on it — which is why the interactive surface exposes weight
sliders rather than shipping one blessed portfolio.

**Where optimised portfolios lose to simple baselines:** `epsilon_demand_first` loses
population served to `epsilon_equity_first` (0.970 vs 1.000), and every optimised portfolio
loses equity coverage to the equity-first solve. Against the *baselines*, the optimised
portfolios lead on all six objectives at this budget — which is the least interesting part of
the table and is not a finding.

**This is cross-objective robustness, not proof of siting correctness or real-world
optimality.**

---

## 5. Which conclusions are independent validation, and which are diagnostic

| Conclusion | Status |
|---|---|
| Leave-one-state-out accuracy on states excluding Washington | **Independent validation** |
| Washington uncertainty calibration curve | **Diagnostic.** Washington is training evidence; the artifact key says `is_empirical_calibration: false` |
| Historical deployment alignment | **Independent** of the deployed model's fit, but it validates a *different, weaker* model (§2.4), and it measures agreement with industry behaviour rather than correctness |
| Cross-objective robustness | **Diagnostic of tradeoff structure.** Not evidence that any portfolio is correct |
| Any statement that a site is optimal | **Not supported by anything here.** Ground truth for optimal siting does not exist |
