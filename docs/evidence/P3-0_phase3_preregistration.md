# Phase 3 pre-registration — validation protocol, estimator selection, uncertainty model

**Status: written and committed BEFORE any Phase 3 model was fitted, before any
estimator was compared, and before any validation metric was computed.**

This document exists so that four decisions cannot be made after seeing which choice
flatters the result:

1. how a held-out state is scored, and which states may enter the headline aggregate;
2. which candidate estimator wins, and by what rule;
3. how allocation error enters the continuous uncertainty score;
4. where the confidence-tier boundary sits.

Nothing below may be revised on the basis of Phase 3 model performance. If a rule here
turns out to be unworkable, the response is `docs/reports/PLAN_CHANGE_3.md` under
CLAUDE.md §15.6 — a recorded, reviewed plan change — never a quiet edit.

---

## 1. Terminology correction carried into Phase 3

The Live Integration Assurance Checkpoint described 0.35 as an "acceptability floor".
The sense was inverted: 0.35 is the **maximum acceptable total variation distance**, an
**acceptability ceiling**, and *exceeding* it is the failing direction that triggers a
plan change. The number and the test are unchanged; only the wording was wrong.

From this point the repository says **"maximum acceptable TVD"** or **"acceptability
ceiling"**. `pipeline/validation/allocation_error.MAX_ACCEPTABLE_TVD = 0.35`.

---

## 2. Washington is preprocessing-method-selection data, not independent validation

Washington's paired ZIP-and-tract records were used to **select** HUD `res_ratio` over
land-area weighting as the Phase 3 ZIP→tract allocation method (decision rule
pre-registered at commit `66f1bfb`, result in
`docs/evidence/P3-1_wa_allocation_scope_and_error.json`). A preprocessing choice that
was tuned on Washington makes any subsequent Washington leave-one-state-out result
**tuning-influenced**, not independent.

Therefore, fixed now:

| Rule | Statement |
|---|---|
| **W1** | Washington carries the status `non_independent_preprocessing_selection_state` on every validation record it produces. |
| **W2** | Washington is **excluded from the headline aggregate** whenever that aggregate is described as independent leave-one-state-out demand model validation. |
| **W3** | Washington **is still run and still reported**, in its own clearly labelled row, because it is the only tract-native state and its result is informative. It is never silently folded into the independent aggregate. |
| **W4** | Any figure quoting a Washington LOSO metric states the non-independence in the same table or sentence, not in a distant footnote. |

**Consequence accepted in advance.** Excluding Washington removes the only tract-native
state from the independent aggregate. The independent aggregate is therefore scored
entirely at ZIP or county grain. This is a real weakening of the evidence and is
recorded as such; it is not a reason to readmit Washington.

---

## 3. Every held-out state is validated at its own native observed granularity

Fixed now, before any state has been scored:

| Native grain of the held-out state | What is compared |
|---|---|
| **tract** | Tract predictions against the observed tract counts, directly. |
| **ZIP** | Tract predictions are **aggregated back up to the ZIP** using the same crosswalk that produced them, and compared against the state's original observed ZIP counts. |
| **county** | Tract predictions are **aggregated back up to the county** and compared against the state's original observed county counts. |

**Prohibited, explicitly.** Crosswalk-generated tract values must never be used as
though they were observed tract labels. A ZIP-grain state has no observed tract truth;
scoring tract predictions against tract pseudo-labels manufactured by the same crosswalk
would measure the crosswalk against itself and report the result as accuracy.

The aggregation-back step is the honest version: it asks whether the model reproduces
the quantity that was actually observed.

**Metrics per held-out state, at that state's native grain:** WAPE, MAE, R², plus the
count of observed units, the evidence grain, and the allocation method used. Reported
per state; the headline aggregate is the EV-weighted mean across the independent states
only.

---

## 4. Which states are usable, and the plan-change trigger

Usability is decided by the rules above, not by which states improve the result. A state
is usable for independent LOSO validation when all of the following hold:

- it has sub-state registration observations at ZIP, county or tract grain;
- its source geography is declared (never inferred from a column name);
- an allocation path exists from that geography to tracts, with provenance;
- it is not Washington (rule **W2**).

**Trigger, fixed now:** if the count of genuinely usable independent states is **three or
fewer**, or if native-granularity validation cannot be constructed honestly for a state,
Phase 3 stops and writes `PLAN_CHANGE_3.md`. It does not weaken the definition of
validation to keep the count up.

---

## 5. Candidate estimators and the selection rule

CLAUDE.md §7.3 forbids hard-coding the estimator. The candidates fixed now, all fitted on
the **demographics-only** primary feature set (D2: no supply-derived feature of any kind):

| Candidate | Why it is in the set |
|---|---|
| **Ridge regression on a log-rate target** | Linear baseline; interpretable coefficients; stable under collinear ACS features. |
| **Poisson / Tweedie generalised linear model** | The target is a count with many small values; a count model is the natural specification. |
| **Gradient-boosted trees** | Captures non-linearity and interaction without manual specification. |
| **Population-share baseline** | Not a model. Present so that any candidate failing to beat "EVs are distributed like people" is exposed as such. |
| **Household-share baseline** | Same role, using households rather than people. |

**Selection rule, fixed now.** The winner is the candidate with the lowest
**EV-weighted WAPE** in leave-one-state-out validation across the independent states,
each scored at its native grain (§3). Ties within **1 percentage point of WAPE** are
broken in favour of the *simpler* model, in the order listed above (ridge before GLM
before boosted trees). A candidate that fails to beat both baselines is reported as
failing, and that finding is published rather than suppressed.

**Not permitted:** selecting on Washington, selecting on a subset of states chosen after
seeing results, or adding a candidate after seeing the leaderboard.

---

## 6. The continuous uncertainty score

Five components, each normalised to `[0, 1]`, combined as a **weighted arithmetic mean**:

```
U_i  =  sum_k ( w_k * c_k(i) )        with   sum_k w_k = 1
```

| k | Component | Definition (fixed now) |
|---|---|---|
| `c1` | **Prediction interval width** | Bootstrap prediction interval half-width for tract *i*, expressed relative to the estimate: `h_i / (h_i + max(estimate_i, 1))`. Bounded in `[0, 1)` and scale-free. |
| `c2` | **Out-of-distribution** | Mahalanobis distance of tract *i*'s standardised feature vector from the sub-state-anchored training distribution, mapped to `[0, 1]` by its empirical CDF over all tracts. |
| `c3` | **Constraint slack** | Symmetric relative movement caused by reconciliation: `abs(reconciled_i - raw_i) / (reconciled_i + raw_i + 1)`. |
| `c4` | **Geographic transformation / allocation error** | The **measured** expected share of EV mass misallocated by the transformation that produced this tract's evidence. Values come from measurement, never from hand-picked penalties — see §7. |
| `c5` | **Source degradation** | Share of the sources feeding tract *i* whose contract status is `degraded` or `unavailable`. |

**Weights.** `w_1 = w_2 = w_3 = w_4 = w_5 = 0.2`, **equal by declaration, not by
calibration.** This is stated wherever the score is published, the weights live in
`pipeline/config/thresholds.yml`, and a weight-sensitivity control ships with the score
(D7). Presenting hand-chosen weights as calibrated is CLAUDE.md §18 anti-pattern 4; the
defence is to say plainly that they are not calibrated.

**Fixed now: the weights will NOT be tuned against validation results.** If the
uncertainty-calibration curve (do high-uncertainty tracts really have larger error?) is
flat or non-monotonic, that is published as a negative finding. Tuning weights until the
calibration curve looks good would make the calibration check meaningless.

**Components overlap.** `c1` and `c4` both capture error for a `state_total_only` tract.
The arithmetic mean therefore under-penalises no case but double-counts some. This is
stated in `docs/METHODOLOGY.md` rather than hidden behind a more elaborate combination
rule that would be no better justified.

---

## 7. Component `c4` is derived from measurement, not chosen

CLAUDE.md §7.4 component 5 requires the ordering
`native tract < ZIP→tract < county→tract < state-total-only` and forbids hard-coded
numeric penalties: the penalty must be **derived from a measurement of transformation
quality**. The measurement is the Washington paired holdout.

**Already measured** (`docs/evidence/P3-1_wa_allocation_scope_and_error.json`,
294,193 records fully accounted for, 292,581 included). EV-weighted mean TVD by ZIP
complexity:

| Observed tracts per ZIP | HUD `res_ratio` | land area |
|---:|---:|---:|
| 1 | 0.0046 | 0.0212 |
| 2–3 | 0.1076 | 0.2351 |
| 4–7 | 0.1715 | 0.2576 |
| 8+ | 0.1872 | 0.2619 |
| **all** | **0.1794** | 0.2579 |

**To be measured in Phase 3, by the same protocol, before `c4` is finalised:** the
**county→tract** transformation error in Washington, using the county field on the same
paired records, banded by tracts-per-county. This replaces what would otherwise be a
guessed county penalty with a number.

**Assignment rule for `c4`, fixed now:**

| `evidence_grain` | `c4` |
|---|---|
| `native_tract` | `0.0` — the transformation is the identity. |
| `zip_anchored` | The measured band value for the **method actually used on that ZIP** and that ZIP's tract count. HUD bands where HUD supplied the weights; land-area bands where the documented degraded fallback was used. |
| `county_anchored` | The measured county band value for that county's tract count, from the Phase 3 Washington county measurement. |
| `state_total_only` | The measured **state→tract** transformation error in Washington under the same protocol: the largest of the measured transformations, and labelled as such. |

**The ordering is asserted, not assumed.** A test checks that the measured values
respect `native_tract <= zip_anchored <= county_anchored <= state_total_only`. If the
measurement violates that ordering, it is reported as a finding — the specification's
ordering was "subject to empirical validation" — and not quietly re-sorted.

**Washington-derived error values are applied nationally.** That is an extrapolation from
one state, and every published `c4` value says so.

---

## 8. Confidence tiers

Tiers are presentation over the continuous score (§7.4.2) and are **never
geography-based**.

| Tier | Label | Rule |
|---|---|---|
| A | **sub-state anchored** | `evidence_grain != state_total_only`. Never labelled "observed". |
| B | modeled | `evidence_grain == state_total_only` and `U_i` below the B/C threshold. |
| C | low confidence | `U_i` at or above the B/C threshold. |

**B/C threshold, fixed now: the 0.75 quantile of `U_i` computed over the tracts whose
`evidence_grain == state_total_only`.** Declared in advance, recorded in
`pipeline/config/thresholds.yml`, and shipped with a sensitivity control. It is a
reporting convention, not a finding, and it will not be moved to change how many tracts
land in each tier.

---

## 9. HUD crosswalk operational rule

The HUD USER USPS ZIP Code Crosswalk API is rate-limited to 60 requests per minute, and
a national ZIP sweep would take hours. Fixed now:

| Rule | Statement |
|---|---|
| **H1** | A **versioned cached crosswalk artifact** is built **once**, covering exactly the ZIPs the ZIP-grain source states actually use, keyed by `(crosswalk vintage, ZIP)`. The vintage in use is **2026 Q2**. |
| **H2** | **No HUD API call occurs inside training, reconciliation, bootstrap, leave-one-state-out or model-selection loops.** A test asserts the model path performs no network access. |
| **H3** | Unallocatable ZIPs and zero-residential ZIPs keep their behaviour exactly: a ZIP whose `res_ratio` sums to zero (documented example **99546**) is reported unallocatable; a ZIP the API 404s (documented example **98504**, PO-Box-only) is reported unallocatable. **Neither is ever renormalised.** |
| **H4** | Every allocated tract value keeps `evidence_grain`, `estimate_method`, the crosswalk source and its vintage, and the weight basis. A ZIP- or county-derived tract value is **never** `directly_observed`. |

---

## 10. Record accounting

Every validation population publishes a balanced ledger:

```
retrieved == included + sum(excluded_by_reason)
```

enforced in code by `pipeline.validation.scope.ExclusionLedger.assert_balanced`, with
mutually exclusive reasons produced by first-match-wins classification. A denominator
that shrinks without a named reason is the quiet form of the silent-default failure D8
forbids.

---

## 11. What this document forbids, restated

- Readmitting Washington to the independent aggregate.
- Scoring a ZIP- or county-grain state against crosswalk-generated tract pseudo-labels.
- Choosing the estimator on anything other than the §5 rule.
- Tuning uncertainty weights against validation results.
- Replacing a measured `c4` value with a chosen one.
- Moving the B/C threshold to change the tier mix.
- Calling any ZIP- or county-derived tract value directly observed.
