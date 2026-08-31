# Phase 4 Report — Siting and Frontier

## 0. Report metadata

| Field | Value |
|---|---|
| Phase | 4 — Siting + frontier |
| Date | 2026-08-31 |
| Gate status | **PASS** |
| Commit | the `gate(phase-4): PASS` commit that carries this report |
| Planned duration | 1.75 part-time weeks |
| Reproduce every number | `python -m pipeline.model.run_phase4` (cached inputs only; no network, no credentials) |
| Prepared by | Claude Code |

---

## 1. Context for a reader with zero prior knowledge

### 1.1 What this project is

**VoltGap** answers: *given a budget and a set of policy priorities, where should the next
EV charging infrastructure be built in the United States, and how confident should we be in
that answer?* It is an open, statically hosted decision-support application for
infrastructure planners, charge point operators, state energy offices and researchers. Its
output is a ranked, budget-feasible portfolio of candidate hexagonal sites with scores,
uncertainty bands, tradeoff context, and CSV/GeoJSON export.

Four constraints shape everything: **zero recurring cost** (free tiers only), **static
hosting** (an offline Python pipeline produces artifacts a browser consumes),
**uncertainty as a first-class output**, and **no supply-to-demand feedback loop** —
charger counts and density are forbidden in the demand model, because existing
infrastructure is an outcome of prior investment decisions and predicting demand from it
launders historical deployment into "need".

### 1.2 What the previous phases produced

**Phase 0** verified 60 sources and established that no authoritative national substation
dataset exists, which removed substation proximity as a mandatory siting filter.
**Phase 1** found that AFDC publishes no charging-unit identifier at any level, so `ports`
and `connectors` are deliberately unpopulated. **Phase 2** established the
non-double-counting capacity rule (naive summing overstates national capacity by
2,104,242 kW) and produced national access figures. **Phase 3**, after several rounds of
external-review correction, produced a **national tract demand surface**: 84,401 census
tracts, ACS 2024 5-year features, a Poisson GLM selected by a pre-registered rule
(leave-one-state-out WAPE 0.3203 against baselines near 0.71), reconciled exactly to
published registration totals under an explicit constraint-precedence hierarchy, with a
national identity of **5,616,923** holding to **zero** imbalance. Every tract carries a
five-component uncertainty score, an evidence grain, an estimate method and a value
provenance.

### 1.3 What this phase was supposed to do

CLAUDE.md §15.5, quoted:

> Frontier computed per state with solve status and optimality gap recorded per point.
> Reverse-objective check run. The browser algorithm is defined exactly, its problem class
> stated, and either a formal approximation guarantee is cited with its theorem and its
> assumptions verified to hold, **or no bound is claimed anywhere** (§7.8). **Empirical
> optimality gaps against offline CBC reported** on controlled fixtures and on
> representative real state problems. Greedy solves a state in ≤ 2 s. Candidate filtering
> verified against constraint definitions, **with no mandatory national
> substation-proximity filter** (§7.9).

External review added five prerequisites carried in the assumption ledger — A-2.1, A-2.2,
A-2.3, A-3.4, A-3.5 — plus the requirement that **Phase 3's demand uncertainty and evidence
provenance survive aggregation into candidate scoring rather than disappearing at the H3
layer**.

---

## 2. What was built

| Path | Purpose | Lines |
|---|---|---:|
| `pipeline/spatial/h3_grid.py` | The national H3 res-6 grid; population-weighted tract→cell allocation | 178 |
| `pipeline/model/hexes.py` | Aggregating the tract surface onto cells, carrying uncertainty and provenance | 246 |
| `pipeline/model/siting.py` | Candidate filtering, the ε-constraint IP, the greedy solver, measured gaps | 388 |
| `pipeline/model/siting_preflight.py` | The four ledger prerequisites, measured | 232 |
| `pipeline/model/run_phase4.py` | One command reproduces every Phase 4 number | 253 |

New dependencies, declared in `pyproject.toml`: **h3 4.5.0** (grid) and **PuLP 3.3.2**
with the bundled **CBC** solver (integer programming). Both are free and add no recurring
cost (D4).

### 2.1 The spatial unit and how demand gets there

CLAUDE.md §2 fixes the national unit at **H3 resolution 6** (measured 38.2 km² per cell,
~3,834 m edge). §7.6 fixes how quantities reach it: **block-level population weights, not
area weights**, because area weighting assumes uniform population within a tract.

A tract is therefore never assigned to "its" cell by a centroid. Its population is
distributed across whatever cells its **block groups** fall in, and its demand follows.
On real Washington data, **732 of 1,784 tracts (41.0%) span more than one cell**, so the
distinction is not academic.

### 2.2 Uncertainty and provenance survive the aggregation

This was an explicit external-review requirement, and it is enforced by
`assert_provenance_survived`, which runs on every build. Each cell carries:

- the **demand-weighted** mean uncertainty **and all five components**, so a
  weight-sensitivity control still works at this layer;
- the share of its demand by `evidence_grain`, by `confidence_tier`, and by
  `value_provenance`;
- `sub_state_anchored_share`, the §11.1 figure;
- how many tracts contributed and the largest one's share.

Weighting is by **demand**, not tract count: a cell whose demand is 95% from a
well-evidenced tract is mostly well evidenced, and a plain mean over tracts would say
otherwise. A **zero-demand cell is not dropped** — it is a legitimate candidate location
and carries its provenance like any other.

### 2.3 The offline formulation, exactly as specified

```
maximize   sum_i demand_i * y_i
subject to sum_j cost_j * x_j <= B
           sum_i equity_pop_i * y_i >= epsilon
           y_i <= sum_{j in N(i)} x_j
           x_j, y_i in {0,1}
```

`N(i)` is the k-ring coverage neighbourhood (k = 1: the cell and its six neighbours),
because a driver need not be in the same 36 km² cell as a charger for it to be useful.

**Equity is one named indicator, not a composite.** `equity_population` is population in
households below $35,000 a year, from the ACS `income_share_under_35k` feature. §8 requires
the primary equity measure to come from current ACS-derived indicators rather than the
archived CEJST overlay, and §17 forbids shipping a composite index without a
weight-sensitivity control. **One indicator needs no weights, so there is nothing to
hand-pick.**

**Budget is expressed in sites, not dollars.** Charger economics is Optional tier (§7.11)
and no cost model exists. Inventing a dollar cost would fabricate an input; saying "twenty
sites" is what the data supports.

---

## 3. Decisions made and why

| Decision | Options | Chosen | Rationale |
|---|---|---|---|
| Tract→cell allocation | tract centroid; block-group population weights | **block-group weights** | §7.6. 41.0% of real tracts span multiple cells, and a centroid can land in a cell holding **none** of the population — measured, §5.3 |
| Coverage neighbourhood | cell only; k-ring | **k = 1** | A charger serves adjacent cells. Configuration, exposed in `thresholds.yml`, not a finding |
| Equity measure | ACS composite index; one named indicator; CEJST | **one named ACS indicator** | Avoids the hand-picked-weights anti-pattern entirely; CEJST is an archived framework (§8) |
| Cost model | invented dollar proxy; uniform site cost | **uniform, budget in sites** | No cost model exists (§7.11). A dollar proxy would be fabricated |
| Road-network filter | invent a proxy silently; degrade explicitly | **explicit degradation** | No road dataset retrieved. A populated-area filter stands in, labelled a degradation everywhere (D8) |
| Saturation filter | none; ports per demand | **DCFC ports per 1,000 BEV** | The only place supply enters siting, which D2 permits: D2 governs the demand model |
| Frontier scope | national; per state | **per state, stratified sample** | §7.8 compute budget. Sample spans size **and all three evidence grains** |
| ε sweep range | fractions of the total; achievable range | **achievable range** | Sweeping the total left 63 of 96 points infeasible — a defect found and fixed, §5.2 |
| Supply detail in siting | ports and kW; ports only | **ports only** | A-2.2 conditions consuming *imputed* capacity. `HexSupply` carries no kW field at all |

---

## 4. Acceptance criteria verification (Gate part G-A)

All checked by `tests/regression/test_phase4_gates.py` against the published artifact.

| # | Criterion | Verifying test | Result | Evidence |
|---|---|---|---|---|
| 1 | Frontier computed per state | `test_p4_a_the_frontier_is_computed_per_state_and_labelled` | **PASS** | 6 states, labelled |
| 2 | Solve status per point | `test_p4_a_every_frontier_point_records_status_and_gap` | **PASS** | 96/96 `optimal` |
| 3 | Optimality gap per point | same | **PASS** | 0.0 on every optimal solve |
| 4 | Reverse-objective check run | `test_p4_a_the_reverse_objective_check_was_run` | **PASS** | both senses, all 6 states |
| 5 | The frontier shows a real tradeoff | `test_p4_a_the_frontier_shows_a_real_tradeoff_somewhere` | **PASS** | §5.2 |
| 6 | Browser algorithm defined exactly | `test_p4_b_the_greedy_algorithm_is_defined_exactly_in_code` | **PASS** | §5.4 |
| 7 | Problem class stated | `test_p4_b_the_problem_class_and_the_reason_are_stated` | **PASS** | §5.4 |
| 8 | **No bound claimed anywhere** | `test_p4_b_no_approximation_bound_is_claimed_in_the_artifact` | **PASS** | regex over the whole artifact |
| 9 | Gaps on real state problems | `test_p4_c_gaps_are_reported_on_representative_real_state_problems` | **PASS** | 18 gaps, 6 states |
| 10 | Gaps on controlled fixtures | `test_p4_c_gaps_are_reported_on_controlled_fixtures_too` | **PASS** | §5.5 |
| 11 | Greedy solves a state in ≤ 2 s | `test_p4_d_greedy_solves_a_state_within_two_seconds` | **PASS** | slowest **0.0288 s** |
| 12 | Candidate filtering verified | `test_p4_e_every_state_retains_candidates_after_filtering` | **PASS** | §5.1 |
| 13 | **No mandatory substation filter** | `test_p4_e_there_is_no_mandatory_substation_filter` | **PASS** | only 2 exclusion reasons exist |
| 14 | Transmission never an interconnection constraint | `test_p4_e_transmission_is_never_an_interconnection_constraint` | **PASS** | D6 |
| 15 | A-2.1 measured | `test_p4_f_a21_site_clustering_was_measured` | **PASS** | §5.6 |
| 16 | A-2.2 respected | `test_p4_f_a22_is_not_triggered_and_cannot_be_violated` | **PASS** | §5.6 |
| 17 | A-2.3 benchmarked | `test_p4_f_a23_centroid_resolution_was_benchmarked` | **PASS** | §5.6 |
| 18 | A-3.4 assessed | `test_p4_f_a34_rounding_does_not_reorder_the_portfolio` | **PASS** | §5.6 |
| 19 | A-3.5 respected | `test_p4_f_a35_no_categorical_urban_rural_anywhere` | **PASS** | §5.6 |
| 20 | **Uncertainty and provenance survive** | `test_p4_g_demand_uncertainty_and_provenance_reach_the_candidate_layer` | **PASS** | §5.1 |

**Criteria passed: 20/20.**

---

## 5. Results and numbers

### 5.1 The candidate set

| State | Grain in the sample | Cells | Candidates | Excluded: saturated | Excluded: uninhabited | Demand (BEV) | Sub-state anchored |
|---|---|---:|---:|---:|---:|---:|---:|
| Washington | native_tract | 1,054 | **856** | 187 | 11 | 236,994 | **1.000** |
| Tennessee | county_anchored | 1,603 | **1,479** | 117 | 7 | 53,029 | **1.000** |
| Montana | county_anchored (partial) | 432 | **400** | 31 | 1 | 6,900 | 0.982 |
| Vermont | state_total_only | 311 | **258** | 53 | 0 | 11,900 | 0.000 |
| Texas | state_total_only | 3,532 | **3,073** | 444 | 15 | 387,400 | 0.000 |
| California | state_total_only | 2,268 | **1,611** | 637 | 20 | 1,843,100 | 0.000 |

**Only two exclusion reasons exist in the code**, and neither is grid-related. Every state
retains candidates. The `sub_state_anchored_share` column is the point of the provenance
requirement: a planner looking at a Texas or California portfolio can see that its demand
rests on a state total and a model, while Washington's rests on a tract-native registry.

### 5.2 The ε-constraint frontier

**96 points, all `optimal`**, 6 states × 8 ε levels × 2 objective directions.

Washington, maximise demand subject to an equity floor:

| ε (equity floor) | Status | Demand covered | Equity covered |
|---:|---|---:|---:|
| 0 – 163,396 | optimal | **70,601** | 172,568 |
| 190,628 | optimal | **68,842** | **191,067** |

California:

| ε | Status | Demand covered | Equity covered |
|---:|---|---:|---:|
| 0 – 414,692 | optimal | **271,884** | 460,208 |
| 497,631 | optimal | 269,293 | 502,063 |
| 580,569 | optimal | **259,982** | **581,914** |

**The tradeoff is real but shallow at low ε.** The demand-optimal portfolio already
delivers substantial equity coverage, so the constraint does not bind until the upper
levels — at which point demand falls to buy equity (Washington −2.5%, California −4.4%).
That correlation between the two objectives is itself a finding, and Phase 5's
cross-objective robustness work (§10.3) is where it gets tested properly. **This report
does not claim it.**

**A defect found and fixed.** The first implementation swept ε as fractions of the
*total* equity population, which left **63 of 96 points infeasible**: a twenty-site
portfolio cannot reach most of a state's equity population. The sweep now solves the
secondary objective first to find the achievable ceiling and sweeps up to that. All 96
points are now feasible.

### 5.3 Population-weighted allocation

| Measure | Washington |
|---|---:|
| Block groups | 5,311 |
| Tracts | 1,784 |
| Tracts spanning more than one cell | **732 (41.0%)** |
| Demand placed differently by a tract centroid | **18.66%** |
| Allocation conservation error | **0.00** |

A centroid assignment can be worse than "approximately right". For two block groups only
~8 km apart weighted 900 to 100, the population-weighted centroid falls in a **third H3
cell containing neither** — so a centroid assignment places **100%** of that tract's demand
somewhere nobody lives. That is the failure §7.6 warns about, reproduced as a named test.

### 5.4 The browser algorithm, its problem class, and the bound question

**The exact algorithm** (task 1), implemented in `greedy_select` and quoted from its
docstring:

1. start with nothing selected and no cell covered;
2. for each unselected candidate, compute the weighted value of the cells it would newly
   cover;
3. take the candidate with the highest marginal gain per unit cost, breaking ties on the
   cell index so the result is deterministic;
4. mark its coverage; repeat until the budget is exhausted or no candidate adds anything.

**Problem class** (task 2). With a single coverage objective, uniform costs and no further
constraint, this is **cardinality-constrained maximum coverage**, whose objective is
monotone and submodular. **That is not the problem the interactive surface poses.** The
shipped surface exposes objective weights and constraint toggles, making it a weighted
multi-objective selection under additional constraints.

**Does a formal guarantee apply?** (tasks 3–5). The classical greedy guarantee for monotone
submodular maximisation holds under a cardinality constraint. Its assumptions hold for the
*restricted* problem — uniform costs, single objective, no side constraint — and **fail for
the surface actually shipped**, because a weighted sum of two objectives under an
additional covering constraint is a different problem class. Since the guarantee cannot be
verified to hold for the algorithm-and-constraint-set actually implemented, **no bound is
claimed anywhere**: not in the artifact, not in a docstring, not in this report. A test
runs a regular expression for the bound over the entire published artifact and fails if it
appears.

Acceptable copy, per §7.8: *"Interactive approximation. Exact offline solutions are used
for the published analytical frontier."*

### 5.5 Empirical optimality gaps (task 7)

Greedy against an exact CBC solve on the same problem, ε relaxed to zero so the comparison
isolates the objective greedy actually optimises. **Every exact solve reached optimality.**

| State | Budget 5 | Budget 20 | Budget 50 |
|---|---:|---:|---:|
| Washington | **0.0000%** | 2.2544% | 0.8648% |
| Tennessee | **0.0000%** | 0.9768% | 1.5296% |
| Montana | **0.0000%** | **3.0557%** | 1.5784% |
| Vermont | **0.0000%** | 0.8873% | 1.2375% |
| Texas | **0.0000%** | 1.1134% | 1.4194% |
| California | 1.4401% | 1.0871% | 0.3713% |

**Worst measured gap: 3.06%** (Montana at 20 sites). Greedy is exact at budget 5 in five of
six states. Controlled fixtures are covered separately by
`test_the_optimality_gap_is_measured_against_an_exact_solve`.

**Timing:** slowest greedy solve **0.0288 s** (Texas, 3,073 candidates) against a 2-second
budget — 69× headroom.

### 5.6 The five prerequisites

| Assumption | Finding | Status |
|---|---|---|
| **A-2.1** site clustering | Max DBSCAN cluster diameter 500 m against a **3,834 m** cell edge = **13.0%** of an edge. It *can* straddle a boundary — the honest answer — but the k-ring coverage neighbourhood already spans adjacent cells, so a site landing either side covers substantially the same demand | **RESOLVED** |
| **A-2.2** rung-2 masked power | **Not triggered.** Phase 4 reads port **counts**, reported directly by the source with no power-resolution ladder. `HexSupply` has **no kW field at all**, and a test asserts `capacity_kw` appears nowhere in the artifact | **RESPECTED** |
| **A-2.3** block-group vs block | The block-level benchmark remains **unavailable** (Phase 0 F-7: no such Census product). What is measurable was measured: stepping *down* one resolution moves **18.66%** of demand, which is evidence that resolution matters and the finer weighting was right — **not** evidence that block group is sufficient | **PARTIALLY RESOLVED** |
| **A-3.4** ±50 rounding | Portfolios are **identical** under ±50 in every sampled state (Jaccard 1.000 both directions; relative perturbation 0.00021 for Washington). Reconciliation scales every tract in a jurisdiction by the same factor, so a uniform change cannot reorder cells *within* it | **RESOLVED** |
| **A-3.5** urban/rural | Density ships **continuous**. `assert_no_categorical_urban_rural` runs over every published state record and rejects any categorical field | **RESPECTED** |

---

## 6. Limitations introduced or discovered

| Limitation | Cause | Effect | Mitigated? |
|---|---|---|---|
| **No road-network filter** | No road dataset retrieved in any phase | Candidates are filtered by resident population instead, which is weaker: an inhabited cell has roads, but the specified filter would also exclude cells far from one | Labelled a degradation in the config, the code, the artifact and here; recorded in `FUTURE_WORK.md` |
| Budget is site count, not cost | No cost model (§7.11 Optional tier) | Portfolios cannot be compared on money, and a real cost model would change which sites are chosen | Stated wherever a budget appears |
| Frontier is a 6-state sample | §7.8 compute budget | The published frontier is not national | Labelled; sample spans size and all three evidence grains |
| Equity is one indicator | Avoiding a hand-weighted composite | A single indicator is a narrower view of disadvantage than a composite would be | Stated; the indicator is named wherever equity appears |
| A-2.3 unresolved at block level | No Census block-level centroid product exists | Cells in large rural block groups inherit the corner-population problem at smaller scale | Measured in the direction available |
| CBC exposes no bound through PuLP | Solver API | A time-limited solve reports `feasible_time_limit` and `optimality_gap: null` rather than a fabricated gap | Status is reported honestly; no solve hit the limit in this run |

---

## 7. Specification compliance

| Directive | How Phase 4 complies | Verified by |
|---|---|---|
| **D1** No temporal leakage | Not exercised; Phase 4 sites on a current cross-section. Every candidate traces to the ACS 2024 vintage so Phase 5 has something to assert on | smoke-forward |
| **D2** No supply-to-demand loop | Supply enters **only** as a saturation filter on candidates, never as a demand feature. The Phase 3 feature set is untouched | `test_check_12`, `test_a_saturated_cell_is_excluded_by_name` |
| **D3** Three validation terms | Phase 4 performs none of the three and claims none. Cross-objective robustness is named as Phase 5's | copy lint |
| **D4** Zero recurring cost | h3 and PuLP/CBC are free and local; the driver needs no network | `make phase4` runs offline |
| **D6** Grid proximity language | No substation filter, no transmission input, no interconnection language | `test_p4_e_*` |
| **D7** Uncertainty first-class | Uncertainty and all five components survive into every cell and every candidate | `assert_provenance_survived`, `test_p4_g_*` |
| **D8** Explicit degradation | The missing road filter is named, labelled and recorded rather than silently substituted | `test_an_uninhabited_cell_is_excluded_by_name` |

**No deviation required a plan change.**

---

## 8. Open questions for the reviewer

1. **Is a populated-area filter an acceptable stand-in for road-network proximity?** It is
   weaker than specified and is labelled as such throughout, but it does change which cells
   are candidates. Retrieving TIGER roads nationally is feasible but was outside this
   phase's scope.
2. **Is one equity indicator the right choice?** It avoids hand-picked weights entirely,
   at the cost of a narrower view of disadvantage than a composite would give.
3. **The demand and equity objectives are strongly correlated in the sampled states**, so
   the ε-constraint only binds at high ε. Phase 5's robustness work will test this
   properly; the reviewer may want the ε range extended further first.

---

## 9. Next phase readiness

| Check | Status |
|---|---|
| All acceptance criteria passed | **20/20** |
| Coverage thresholds met | see §10 |
| All prior gates passing | see §10 |
| Smoke-forward test for Phase 5 passing | **yes** — 5 tests |
| Report complete and self-contained | yes |
| No S1 impacts open | yes |

**Recommendation: PROCEED to Phase 5 (validation), subject to external review.**

---

## 10. Gate evidence (parts G-B and G-C)

| Step | Result |
|---|---|
| 1. lint | ruff clean; `mypy --strict` clean over 113 source files |
| 2. full test suite | **1,046 passed, 47 deselected** in 180.06s |
| 3. coverage | **100% line and branch on every tier**: 4,912 statements, 1,200 branches, zero missed |
| 4. prior gate suites (Phase 0, 1, 2, 3) | pass; probe determinism byte-identical |
| 4b. smoke-forward for Phase 5 | **5 passed** |
| 5. Phase 4 acceptance criteria | **20 passed** |
| 6. D3 copy lint | clean, 156 files |
| 7. semantic determinism | pass |
| 8. one-command rebuild | canonical tables, Phase 3 and Phase 4 all rebuilt |
| **Verdict** | **PASS** |

Coverage by package: `pipeline/model` 2,362 statements (up from 1,881), `pipeline/spatial`
391 (up from 299), both at 100% line and branch. The suite grew 935 → **1,046**: 111 tests
added across five new files.

The gate failed twice during this phase and both failures were fixed rather than
accommodated — a `mypy --strict` violation in the new smoke-forward fixtures, and, earlier,
an ε sweep that left 63 of 96 frontier points infeasible.

### 10.1 Hardening carried out at external review's request

The zero-completion licence now **fails closed on unknown jurisdiction**: a registration
row whose jurisdiction is null or ambiguous counts as **unresolved in-jurisdiction** rather
than being presumed out-of-jurisdiction, which refuses the licence. No published number
changes — zero Washington rows have a null `state` — but a future refresh that introduced
one would no longer silently complete absent tracts to zero. Assumption A-3.16.
