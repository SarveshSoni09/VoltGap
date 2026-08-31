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
| `pipeline/sources/tiger_roads.py` | TIGER/Line primary and secondary roads; WKB LineString parsing (added by the 2026-08-31 correction, §11) | 186 |
| `pipeline/spatial/road_proximity.py` | Cell-to-road distance and the threshold sensitivity curve (§11) | 96 |
| `pipeline/model/clustering_sensitivity.py` | The A-2.1 clustering experiment (§11) | 159 |

New dependencies, declared in `pyproject.toml`: **h3 4.5.0** (grid) and **PuLP 3.3.2**
with the bundled **CBC** solver (integer programming). Both are free and add no recurring
cost (D4).

### 2.1 The spatial unit and how demand gets there

CLAUDE.md §2 fixes the national unit at **H3 resolution 6** (measured 38.2 km² per cell,
~3,834 m edge). §7.6 fixes how quantities reach it: **population weights, not area weights**, because area
weighting assumes uniform population within a tract. The finest *prebuilt* population-weighted
centroid the Census publishes is block group, so that is the grain used; the block inputs from
which a finer one could be built exist but constructing that artifact was out of scope (A-2.3).

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
| Road-network filter | TIGER/Line primary+secondary; all road classes; degrade explicitly | **TIGER/Line 2024 PRISECROADS, MTFCC S1100+S1200, 5.0 km** | §7.8. Corrected 2026-08-31 — see §11. The first submission degraded on the false premise that no road dataset existed |
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
| 11 | Greedy solves a state in ≤ 2 s | `test_p4_d_greedy_solves_a_state_within_two_seconds` | **PASS** | slowest **0.023 s** |
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

| State | Grain in the sample | Cells | Candidates | Excl: uninhabited | Excl: beyond road | Excl: saturated | Demand (BEV) | Sub-state anchored |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Washington | native_tract | 1,054 | **674** | 11 | 185 | 184 | 236,994 | **1.000** |
| Tennessee | county_anchored | 1,603 | **1,425** | 7 | 54 | 117 | 53,029 | **1.000** |
| Montana | county_anchored (partial) | 432 | **297** | 1 | 103 | 31 | 6,900 | 0.982 |
| Vermont | state_total_only | 311 | **250** | 0 | 8 | 53 | 11,900 | 0.000 |
| Texas | state_total_only | 3,532 | **2,417** | 15 | 659 | 441 | 387,400 | 0.000 |
| California | state_total_only | 2,268 | **1,253** | 20 | 366 | 629 | 1,843,100 | 0.000 |

**Three exclusion reasons exist in the code, and none is grid-related.** They are applied
in a fixed order — uninhabited, then beyond the road network, then already saturated — and
each cell is counted under the **first** reason that applies, so the columns sum to cells
minus candidates with no double counting. That ordering is why the saturated column moved
when the road filter was added: Washington's saturated count fell 187 → 184 because three
saturated cells were already excluded as beyond the road network.

**The road filter's own before/after** is therefore reported separately, holding every
other filter fixed and varying only the road threshold between 5.0 km and infinity:

| State | Candidates before road filter | After | Removed by roads | Road features | Road vertices |
|---|---:|---:|---:|---:|---:|
| Washington | 856 | **674** | **−182** | 3,006 | 376,007 |
| Tennessee | 1,479 | **1,425** | **−54** | 9,184 | 1,392,729 |
| Montana | 400 | **297** | **−103** | 1,251 | 252,599 |
| Vermont | 258 | **250** | **−8** | 1,432 | 178,596 |
| Texas | 3,073 | **2,417** | **−656** | 15,290 | 1,115,704 |
| California | 1,611 | **1,253** | **−358** | 7,351 | 1,246,491 |

The filter is consequential and its effect tracks geography as it should: Montana loses
**25.8%** of its candidates and Texas **21.3%**, while Vermont — small, dense and
comprehensively roaded — loses **3.1%**.

**The threshold ships with its sensitivity curve**, so 5.0 km is visible as a choice
rather than presented as a finding. Cells within the threshold, Washington:

| Threshold (km) | 1 | 2 | 3 | **5** | 8 | 12 | 20 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Cells qualifying | 313 | 521 | 684 | **859** | 979 | 1,022 | 1,040 |

The `sub_state_anchored_share` column is the point of the provenance requirement: a
planner looking at a Texas or California portfolio can see that its demand rests on a
state total and a model, while Washington's rests on a tract-native registry.

### 5.2 The ε-constraint frontier

**96 points, all `optimal`**, 6 states × 8 ε levels × 2 objective directions.

Washington, maximise demand subject to an equity floor:

| ε (equity floor) | Status | Demand covered | Equity covered |
|---:|---|---:|---:|
| 0 – 157,612 | optimal | **67,523** | 167,294 |
| 183,881 | optimal | **66,847** | **184,024** |

California:

| ε | Status | Demand covered | Equity covered |
|---:|---|---:|---:|
| 0 – 405,558 | optimal | **256,713** | 454,966 |
| 486,670 | optimal | 256,697 | 489,030 |
| 567,782 | optimal | **249,546** | **569,489** |

**The tradeoff is real but shallow at low ε.** The demand-optimal portfolio already
delivers substantial equity coverage, so the constraint does not bind until the upper
levels — at which point demand falls to buy equity (Washington −1.0%, California −2.8%).
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
| Washington | **0.0000%** | 0.8756% | 0.3753% |
| Tennessee | **0.0000%** | 0.4771% | 1.1501% |
| Montana | **0.0000%** | **3.1411%** | 1.0855% |
| Vermont | **0.0000%** | 0.8894% | 1.0564% |
| Texas | **0.0000%** | **0.0000%** | 0.6372% |
| California | 1.6549% | 1.0947% | **0.0000%** |

**Worst measured gap: 3.14%** (Montana at 20 sites). Greedy is exact at budget 5 in five of
six states, and exact in three further cells of this table. Controlled fixtures are covered
separately by `test_the_optimality_gap_is_measured_against_an_exact_solve`.

**Timing:** slowest greedy solve **0.023 s** (Texas, 2,417 candidates) against a 2-second
budget — roughly 87× headroom. This is wall-clock time on the build machine and it moves a
millisecond or two between runs, so the **test asserts the 2-second budget, not this
figure** (`assert state["greedy"]["seconds"] <= GREEDY_BUDGET_SECONDS`). The quoted number
is the value carried by the committed `docs/evidence/P4-1_siting.json`.

### 5.6 The five prerequisites

| Assumption | Finding | Status |
|---|---|---|
| **A-2.1** site clustering | **Measured, not argued from geometry** (the 500 m / 3,834 m ratio argument was withdrawn — see §11). Three conditions per state: shipped (no clustering), DBSCAN eps 50 m, DBSCAN eps 200 m. At the shipped Phase 1 configuration (**50 m**) the effect is **zero in all six states**: candidate Jaccard 1.000, 0 saturation reclassifications. At a deliberately coarser **200 m** two states move — Washington 1 cell (Jaccard 0.998519) and Texas 2 cells (Jaccard 0.999173) — and **no portfolio changes at any budget in any state**: overlap 1.000 at 5, 20 and 50 sites, demand and equity deltas exactly 0.00 | **RESOLVED** |
| **A-2.2** rung-2 masked power | **Not triggered.** Phase 4 reads port **counts**, reported directly by the source with no power-resolution ladder. `HexSupply` has **no kW field at all**, and a test asserts `capacity_kw` appears nowhere in the artifact | **RESPECTED** |
| **A-2.3** block-group vs block | The block-level benchmark remains **unbuilt**: Census publishes no prebuilt population-weighted centroid at block grain (Phase 0 F-7), though the TIGER block geometry and P.L. 94-171 block counts that would let one be constructed both exist and both carry source-contract entries. What is measurable was measured: stepping *down* one resolution moves **18.66%** of demand, which is evidence that resolution matters and the finer weighting was right — **not** evidence that block group is sufficient | **PARTIALLY RESOLVED** |
| **A-3.4** ±50 rounding | Portfolios are **identical** under ±50 in every sampled state (Jaccard 1.000 both directions; relative perturbation 0.00021 for Washington). Reconciliation scales every tract in a jurisdiction by the same factor, so a uniform change cannot reorder cells *within* it | **RESOLVED** |
| **A-3.5** urban/rural | Density ships **continuous**. `assert_no_categorical_urban_rural` runs over every published state record and rejects any categorical field | **RESPECTED** |

---

## 6. Limitations introduced or discovered

| Limitation | Cause | Effect | Mitigated? |
|---|---|---|---|
| **Road proximity is not road access** | The filter measures distance from a cell centroid to a road vertex | A cell within 5.0 km of an arterial may still have no legal, physical or commercially available site on it. This is a proximity proxy in exactly the sense D6 applies to grid proximity | Named as proximity everywhere; never described as buildability |
| **Only primary and secondary roads count** | MTFCC S1100 and S1200; local streets (S1400) excluded | A cell served only by local streets is excluded even though something could physically be built there | Pre-registered with its reason in `docs/evidence/P4-0_road_filter_preregistration.md`; the full 1–20 km sensitivity curve ships in the artifact |
| **Distance is to a road vertex, not to a segment** | Avoids adding a geometry library to a zero-cost offline build | A long straight segment could pass closer to a cell than either endpoint. TIGER geometries carry ~125 vertices per Washington feature, so the error is small — but it is an approximation | Recorded as assumption **A-4.6**, not described as exact |
| Budget is site count, not cost | No cost model (§7.11 Optional tier) | Portfolios cannot be compared on money, and a real cost model would change which sites are chosen | Stated wherever a budget appears |
| Frontier is a 6-state sample | §7.8 compute budget | The published frontier is not national | Labelled; sample spans size and all three evidence grains |
| Equity is one indicator | Avoiding a hand-weighted composite | A single indicator is a narrower view of disadvantage than a composite would be | Stated; the indicator is named wherever equity appears |
| A-2.3 unresolved at block level | No **prebuilt** Census population-weighted centroid product at block grain. The block inputs do exist — TIGER `TABBLOCK20` geometry and P.L. 94-171 block counts — so this is a missing artifact, not missing data | Cells in large rural block groups inherit the corner-population problem at smaller scale | Measured in the direction available; constructing the block-grain artifact is recorded in `FUTURE_WORK.md` |
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
| **D8** Explicit degradation | The road filter **runs** (§11.1). Where it cannot, `build_candidates` **raises** rather than passing cells through; degraded mode must be requested explicitly and every cell admitted that way is counted in the artifact (0 in every published state) | `test_candidate_construction_without_roads_raises_rather_than_dropping_the_filter`, `test_degraded_mode_admits_cells_but_says_so_loudly`, `test_p4_e_the_road_proximity_filter_actually_ran_in_every_state` |

**No deviation required a plan change.**

---

## 8. Open questions for the reviewer

1. ~~**Is a populated-area filter an acceptable stand-in for road-network proximity?**~~
   **Answered by review: no, and the question rested on a false premise.** The §7.8 filter
   now runs on TIGER/Line 2024 roads — see §11.1. What remains open is narrower: whether
   **primary + secondary** are the right road classes (A-4.7), and whether vertex distance
   is close enough to point-to-segment distance (A-4.6). Neither has a sensitivity curve
   the way the 5.0 km threshold does.
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


---

## 11. Correction — 2026-08-31

This section is appended, not merged into the body: prior report content above is
preserved so the audit trail survives (CLAUDE.md §15.3 item 4). External review returned
the first Phase 4 submission as a **CONDITIONAL PASS** with two candidate-construction
blockers. Both are resolved. **The numbers in §5 above have been updated in place to the
corrected values**, and this section states what changed, by how much, and why the original
was wrong.

### 11.1 Blocker 1 — the §7.8 road-proximity filter was omitted on a false premise

**What the first submission said.** That no road-network dataset had been retrieved in any
phase, so the filter was degraded explicitly under directive D8, with a resident-population
filter standing in and the degradation labelled in the config, the code, the artifact and
the report. Recorded as assumption A-4.1.

**Why that was wrong.** The premise was false, and it was my error, not a limitation of the
project. The Census Bureau publishes **TIGER/Line `PRISECROADS`** — one zipped shapefile of
primary and secondary roads per state, free, keyless, and on the same host as the TIGER
tract and block products this pipeline already retrieves. D8 governs what to do when a
source is genuinely unavailable. It does not license omitting a mandatory filter when the
source exists and was not looked for.

Two further points from the review, both correct and both accepted:

- **Resident population is not a substitute for road proximity and must not be presented as
  one.** The substitution fails in both directions: an uninhabited cell can sit on an
  interstate, and an inhabited cell can be far from any arterial. The population filter is
  **retained** — a cell with nobody in it is not a siting candidate — but on its own
  merits, and it is no longer described as standing in for anything.
- **The ratio 500 m / 3,834 m does not establish portfolio robustness.** Addressed in
  §11.2.

**What was retrieved.** TIGER/Line **2024** PRISECROADS for the six frontier states. For
Washington: 3,006 features carrying 376,007 vertices, of which MTFCC `S1200` (secondary) =
2,800 and `S1100` (primary) = 206.

**Pre-registration.** The threshold, the road classes and the distance method were fixed in
`docs/evidence/P4-0_road_filter_preregistration.md` and committed (`18acbb4`) **before any
candidate set was recomputed**, so none of them could be chosen after seeing which value
gave a convenient answer. The pre-registered content:

| Parameter | Value | Reason fixed in advance |
|---|---|---|
| Source | TIGER/Line 2024 `PRISECROADS` | Free, keyless, same host as the TIGER products already used |
| Road classes | MTFCC `S1100` (primary) + `S1200` (secondary) | At 38.2 km² per cell nearly every inhabited cell contains some `S1400` local street, so including local roads would make the filter a near no-op rather than the §7.8 constraint |
| Threshold | **5.0 km** | An H3 res-6 cell has an inradius of ≈3,320 m, so a threshold below that would exclude cells whose nearest arterial lies just outside their own boundary. 5.0 km is the smallest round figure above it |
| Distance | Haversine, cell centroid → nearest road **vertex** | Reuses the Phase 2 haversine ball tree; avoids a geometry dependency in a zero-cost offline build. Recorded as approximation A-4.6 |
| Failure behaviour | **Raise** | Passing every cell through would silently drop the filter |

**What was built.**

- `pipeline/sources/tiger_roads.py` — retrieval and WKB LineString parsing. Validation is
  **eager**: byte order, geometry type and point count are all checked before any iterator
  is returned, and each raises rather than guessing, because a silently mis-parsed geometry
  would put roads in the wrong place and the resulting filter would look perfectly
  plausible while being wrong.
- `pipeline/spatial/road_proximity.py` — nearest-vertex distance and the sensitivity curve.
- `build_candidates` now **raises** `SitingError` without road distances. Degraded mode
  exists but must be requested explicitly via `allow_missing_roads=True`, and every cell
  admitted that way is counted in the published artifact under
  `cells_admitted_without_road_filter`. In the published run that count is **0** in every
  state.

**What changed in the published numbers.** Candidate counts in all six frontier states:

| State | First submission | Corrected | Removed by roads | Share removed |
|---|---:|---:|---:|---:|
| Washington | 856 | **674** | −182 | 21.3% |
| Tennessee | 1,479 | **1,425** | −54 | 3.7% |
| Montana | 400 | **297** | −103 | 25.8% |
| Vermont | 258 | **250** | −8 | 3.1% |
| Texas | 3,073 | **2,417** | −656 | 21.3% |
| California | 1,611 | **1,253** | −358 | 22.2% |

The filter is consequential, and its effect tracks geography as it should: Montana, large
and sparsely roaded, loses the most; Vermont, small and comprehensively roaded, the least.

Downstream, the ε-constraint frontier remains **96 of 96 `optimal`**, the worst empirical
optimality gap moved **3.06% → 3.14%** (Montana at 20 sites), and the slowest greedy solve
moved **0.029 s → 0.023 s** on the smaller candidate sets, against a 2-second budget. Both
solve-time figures are wall clock and vary by a millisecond or two between runs; what is
gated is the budget, not the figure.

**One accounting subtlety, stated so the tables reconcile.** Exclusions are first-match-wins
in a fixed order — uninhabited, then beyond the road network, then already saturated — so
adding the road filter *reduced* the saturated counts by absorbing cells that qualified for
both. Washington's saturated exclusions fell 187 → 184 for this reason. The before/after
table above therefore holds every other filter fixed and varies **only** the road threshold
between 5.0 km and infinity, which is the honest comparison.

**What is now claimed, and what is not.** Road proximity is **proximity, not
buildability**. A cell within 5.0 km of an arterial may have no legal, physical or
commercially available site on it. This is a proximity proxy in exactly the sense D6
applies to grid proximity, and nothing in the pipeline or documentation describes it as
feasibility.

Assumption **A-4.1 is withdrawn and closed.** Two narrower assumptions are opened in its
place: **A-4.6** (vertex distance versus point-to-segment distance, unmeasured) and
**A-4.7** (whether primary + secondary are the right road classes — the *threshold* ships
with a sensitivity curve, the *class choice* does not).

Impact-log entry **I-18**, severity **S1 Blocking**.

### 11.2 Blocker 2 — A-2.1 was closed by an argument, not a measurement

**What the first submission said.** That the largest DBSCAN cluster diameter (500 m)
against the measured H3 res-6 cell edge (3,834 m) — 13.0% — showed station clustering does
not materially distort candidate siting.

**Why that was wrong.** The review is right and the argument is withdrawn. The ratio
establishes that a cluster is small relative to a cell. It establishes **nothing** about
whether a cluster straddling a boundary changes a cell's saturation classification, its
candidate status, or the portfolio selected from it. A boundary effect does not scale with
the size ratio; it depends on where the boundary falls.

**What was measured instead.** `pipeline/model/clustering_sensitivity.py` runs **three
conditions per state**:

| Condition | What it does |
|---|---|
| `shipped_no_clustering` | The shipped path: each AFDC station at its own reported coordinates, never clustered |
| `dbscan_eps_50m` | The Phase 1 site-resolution configuration: DBSCAN sites, whole-site ports placed at the site centroid |
| `dbscan_eps_200m` | Deliberately coarser, to bound the effect of a more aggressive clustering choice rather than only testing the shipped one |

Placing a whole site's ports at its centroid is precisely the mechanism by which clustering
could move ports across a cell boundary, which is what the argument failed to test. Four
things are scored against the shipped baseline: **candidate-set Jaccard**, **cells whose
saturation classification changes**, **portfolio overlap at 5, 20 and 50 sites**, and the
**demand and equity objective deltas**.

**What the measurement found.**

| State | eps 50 m: Jaccard | eps 50 m: saturation changes | eps 200 m: Jaccard | eps 200 m: saturation changes | Any portfolio change, any budget |
|---|---:|---:|---:|---:|---|
| Washington | 1.000000 | 0 | 0.998519 | **1** | **none** |
| Tennessee | 1.000000 | 0 | 1.000000 | 0 | **none** |
| Montana | 1.000000 | 0 | 1.000000 | 0 | **none** |
| Vermont | 1.000000 | 0 | 1.000000 | 0 | **none** |
| Texas | 1.000000 | 0 | 0.999173 | **2** | **none** |
| California | 1.000000 | 0 | 1.000000 | 0 | **none** |

At the shipped Phase 1 configuration the effect is **exactly zero in all six states**. At
the deliberately coarser 200 m, two states reclassify a total of three cells — and **no
portfolio changes at any budget in any state**: overlap 1.000 at 5, 20 and 50 sites, demand
and equity deltas exactly **0.00** everywhere.

**A-2.1 is resolved, now on evidence rather than on geometry.** Three tests assert it:
`test_p4_f_a21_site_clustering_was_measured` (which additionally asserts the withdrawn
`diameter_as_share_of_cell_edge` field is **absent** from the artifact, so the argument
cannot quietly return), `test_p4_f_a21_the_shipped_clustering_configuration_changes_nothing`
and `test_p4_f_a21_no_portfolio_changes_under_any_clustering_condition`.

Impact-log entry **I-19**, severity **S2 Degrading**.

### 11.3 Documentation corrections

| Item | Was | Now |
|---|---|---|
| Block-grain centroids | "Block-level population-weighted centroids **do not exist**" | "**No prebuilt product.**" The block *inputs* do exist — TIGER `TABBLOCK20` geometry and P.L. 94-171 block population counts, both retrievable and both carrying source-contract entries. This is a missing **artifact**, not missing data, and constructing it was out of Phase 2 and Phase 4 scope. Corrected in `LIMITATIONS.md`, the A-2.3 ledger entry, §5.6 and §6 above, and the probe registry note |
| Equity objective naming | The indicator was named in the report but not in the artifact | The definition now ships **inside every artifact** carrying an equity number, as `equity_objective_indicator`: *"population in households with income below $35,000 a year, from the ACS five-year feature `income_share_under_35k` multiplied by tract population. ONE named current ACS-derived socioeconomic indicator, NOT a composite index and NOT a general measure of disadvantage."* A reader of the JSON alone can no longer mistake it for a composite disadvantage index. `METHODOLOGY.md` gains a dedicated §4.6 |
| Frontier-state rationale | Asked to confirm it is pre-outcome | **Confirmed, and it was already in the code.** `FRONTIER_STATES` in `pipeline/model/run_phase4.py` carries a `why_in_the_sample` string per state, published in the artifact, stratified on **inputs** — evidence grain and size — never on results: Washington (`native_tract`, the only tract-native registry), Tennessee (`county_anchored`, complete county observations), Montana (`county_anchored`, partial coverage, sparse and rural), Vermont (`state_total_only`, small), Texas (`state_total_only`, large), California (`state_total_only`, largest by demand). The sample spans size and **all three evidence grains** |
| ε levels | Asked not to extend the sweep | **Not extended.** Still 8 levels per state per direction, 96 points |

### 11.4 One defect found while making these corrections

`python -m pipeline.discovery.probe --only <id>` **overwrote the whole observations
sidecar with just the probed subset**, silently deleting the recorded measurement for every
other source. I tripped over it adding the TIGER roads observation: one command reduced
`SOURCES.observed.json` from 60 observations to 1, and the result was a clean, well-formed
file that gave no sign anything was missing. The sidecar is the evidence that each source
was actually measured, so this is exactly the kind of silent loss D8 exists to prevent.

Fixed: a partial probe now **merges** onto the existing sidecar (`merge_observations`), with
fresh measurements winning per source id and untouched sources — and their recorded drift —
preserved. Two tests cover it, including an end-to-end one that runs `--only` twice with
different ids and asserts both survive. `pipeline/discovery/probe.py` and
`pipeline/discovery/contract.py` are both back at 100% line and branch coverage.

The file was restored from git and the roads observation merged in, so the committed
sidecar is a **pure addition of 14 lines** with no other source's record altered.

### 11.5 What was re-run

The complete Phase 4 gate and every prior gate suite, from a regenerated
`docs/evidence/P4-1_siting.json`. Nothing in this section is carried forward from the first
submission's run.
