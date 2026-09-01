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

This mechanism was built for the ACS 2020 5-year release, whose date is now recorded. The
2016-2020 ACS 5-year estimates were released **2022-03-17**, after the 2022-01-01 cutoff, so
the 2022 origin resolves to ACS 2019 either way and no result changes. What changed on
external review is the *reason*: the edition is excluded because it demonstrably did not
exist at the cutoff, rather than because its availability could not be shown.

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

2020 tract geography was not contemporaneously available for these prediction cutoffs; retrospective harmonization would require later boundary/crosswalk information, so Core evaluates stable H3 cells using cutoff-appropriate 2010-geography inputs. The backtest is scored on **H3 resolution-6 cells**, which do not move when the
Census redraws tracts, using contemporaneous **CenPop2010** block-group population weights and
the contemporaneous 2019 gazetteer for land area. Every §10.2.4 metric is a cell-ranking
metric, so nothing is lost by this.

A harmonised 2020-geography comparison is possible in principle using a later boundary
crosswalk — but that crosswalk is itself post-cutoff information, so it would answer a
different question than the one directive D1 permits at these origins.

### 2.3 Features excluded from every historical origin

| Feature / source | Reason |
|---|---|
| **ACS 2019 5-year** at the 2020 origin | Period ends before the cutoff, but not released until 2020-12-10 — nobody had it |
| **ACS 2020 5-year** at the 2021 and 2022 origins | Released 2022-03-17, after both cutoffs |
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
| Road-proximity filter | TIGER/Line 2024 primary + secondary, 5.0 km | **not applied at any origin** — TIGER 2024 postdates every cutoff and no earlier edition was retrieved, so no road geometry of any vintage enters a historical ranking |

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

**Capacity is reconstructed on the same terms as the network itself** — see §2.6.3: power
comes from the current snapshot and is attributed to each station's open date, so an upgraded
station carries its present power.

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
| Random baseline (mean of 200 draws) | 0.0961 | 0.0973 | 0.0969 |

**Lift (stations):**

| Origin | vs random | vs population |
|---|---:|---:|
| 2020 | **6.72** | **0.83** |
| 2021 | **6.39** | **0.82** |
| 2022 | **5.89** | **0.81** |

### 2.6.1 How capture is computed, and the eligible support

Asked on external review, because the 2020 random figure originally looked anomalous.

- **Capture denominator:** *all* subsequent deployments in the window, including any landing
  outside the ranked cells. A deployment in an unranked cell is a **miss for every ranking**,
  not an exclusion for some, which is why the full-ranking capture is below 1.0 by exactly the
  share that fell outside.
- **Top decile:** `round(0.1 × len(ranked_cells))` cells from the head of the ranking; ties
  broken by cell id so the order is deterministic. At 50,756 ranked cells that is 5,076 cells.
- **Ranked support:** every cell carrying at least one resident. 382 cells are dropped as
  uninhabited at every origin, leaving **50,756**. An uninhabited cell is not a siting
  candidate under any model.
- **Every ranking — model, random, population, existing-network — is scored over exactly this
  support**, and the artifact asserts their full-ranking captures are identical.
- **Share of deployments inside the ranked cells:** 0.9754 / 0.9718 / 0.9681 for 2020 / 2021 /
  2022. The support barely moves between origins, so it does **not** explain the original
  2020 random figure.

### 2.6.2 Why the 2020 random baseline looked anomalous

The originally reported random captures — 0.0687 / 0.1050 / 0.0991 — came from a **single
seeded permutation** each. That is unbiased but high-variance: deployment counts are heavily
concentrated, so one shuffle either does or does not land on the busy cells.

Measured over 400 draws at the 2020 origin, the top-decile capture has mean **0.0976** and
standard deviation **0.0137**, with a 5th percentile of 0.0759. The single-seed draw of
**0.0687 sat at percentile 0** — outside the 5–95 band. The 2021 and 2022 draws sat at
percentiles 76 and 64, close to their means. So the anomaly was **sampling noise in the
baseline**, not a difference in eligible support or candidate coverage.

The random baseline is now the **mean over 200 draws**, which is still an *empirical* random
baseline rather than a theoretical one-tenth, and its spread ships alongside. Random capture
becomes 0.0961 / 0.0973 / 0.0969 — consistent across origins, as the near-identical support
implies it should be — and lift against random becomes 6.72 / 6.39 / 5.89. **This reduced the
model's headline advantage** at 2020 from 9.40× to 6.72×; the model and its ranking are
unchanged.

### 2.6.3 Capacity captured, not only station counts

§10.2.4 requires ports **and capacity**. Capacity is non-overlapping generic service capacity
in kW (§7.1.1), resolved through Phase 2's own power ladder — reported → empirical median →
documented type default — with a unit's capacity the **maximum** of its mutually alternative
connector outputs, never their sum.

| Origin | Reconstructed capacity associated with deployments (current-snapshot kW) | Model top-decile capacity | Population | Existing-network | Random |
|---|---:|---:|---:|---:|---:|
| 2020 | 2,471,663 | 0.4797 | 0.6365 | 0.3231 | 0.0924 |
| 2021 | 3,142,231 | 0.4842 | 0.6235 | 0.3795 | 0.0938 |
| 2022 | 4,370,222 | 0.4944 | 0.6149 | 0.4149 | 0.0941 |

**This is reconstructed capacity in current-snapshot kW, not known installation-time
capacity.** The power values are read from the **current** AFDC snapshot and attributed to
each station's open date, because the snapshot records no history (**G10**, **G11**).

**The biases compete, and their net direction is unknown.** Three effects pull against each
other:

- a surviving station may carry **higher** power now than when it was installed, which would
  inflate the reconstructed figure;
- stations that **closed or left the feed** are absent entirely, which would deflate it;
- upgrades and closures need **not** be distributed equally between model-selected and
  non-selected cells, so even the capture *fraction* — a ratio, where a uniform bias would
  cancel — has no guaranteed direction.

So neither the reconstructed total nor the model's capacity-capture fraction has a guaranteed
upward or downward bias relative to true installation-time capacity. Every published capacity
figure carries this basis string in the artifact.

**Interpretation.** Within the survivorship-biased current-snapshot reconstruction, the
model's top-decile cells capture **48–49% of reconstructed capacity** compared with **57–65%
of subsequent deployment events**. This indicates **weaker alignment with reconstructed
charging capacity than with deployment counts**. Because historical power changes and closed
stations cannot be reconstructed, the direction and magnitude of bias relative to
installation-time capacity are **unknown**, and are more consequential for older origins.

Stated narrowly: the deployments the model's top decile selects have **lower reconstructed
(current-snapshot) capacity on average** than deployments overall. Original installation-time
capacity is unavailable, so this cannot be restated as a claim about the size of the stations
that were actually built at the time. The ordering against the baselines is unchanged, and
population leads on capacity as it does on station count.

### 2.7 The headline finding is negative, and it is reported as such

**The model beats random by 5.9–6.7×, and loses to a plain population ranking at every one
of the three origins**, by a consistent margin (lift 0.81–0.83 on stations, 0.78–0.82 on
ports). Ranking cells by resident population predicts where chargers actually got built
better than the cutoff-valid demand model does.

**The narrow conclusion, and it is the only one this result supports.** The model strongly
outperforms random and the existing-network baseline, but does not outperform population for
reproducing subsequent industry deployment locations at any origin. This is a **negative
historical-deployment-alignment result**. It is **not** evidence of siting failure, and it is
**not** itself evidence for or against directive D2.

Nothing was tuned in response to it. What it does and does not license:

- **It does not mean the demand model is inaccurate.** Whether tract-level estimates are
  accurate is *demand model validation*, a different term with a different method. Alignment
  measures agreement with where industry built, which is not the same question.
- **It says nothing about D2 either way.** An earlier draft of this document argued that
  beating population would have shown the model had learned industry deployment habits, and
  that losing to population therefore vindicated D2. That inference does not hold: D2 is a
  constraint on which *features* may enter the demand model, and it is enforced by a test on
  the feature set, not by a ranking outcome. A model could outperform population for many
  reasons unrelated to reproducing industry behaviour, and could underperform it for reasons
  unrelated to D2. The claim is withdrawn.
- **It is not a measurement of the deployed model.** The backtested model is deliberately
  weaker: 51 state-level observations rather than sub-state panels.
- **What the model does beat** is the existing-network baseline, the ranking that says "build
  where infrastructure already is".

### 2.8 Sensitivity across origins, and confounding

Conclusions are **stable across all three origins**: the ordering (population > model >
existing-network > random) holds at every one, and every figure moves monotonically and
mildly with the cutoff. Lift against random falls from 6.72 to 5.89 as the window moves later,
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
