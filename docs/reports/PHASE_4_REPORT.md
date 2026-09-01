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
| 9 | Shortfall on real state problems | `test_p4_c_gaps_are_reported_on_representative_real_state_problems` | **PASS** | 18 measurements, 6 states |
| 10 | Shortfall on controlled fixtures | `test_p4_c_gaps_are_reported_on_controlled_fixtures_too` | **PASS** | §5.5 |
| 11 | Greedy solves a state in ≤ 2 s | `test_p4_d_greedy_solves_a_state_within_two_seconds` | **PASS** | slowest **0.032 s** |
| 12 | Candidate filtering verified | `test_p4_e_every_state_retains_candidates_after_filtering` | **PASS** | §5.1 |
| 13 | **No mandatory substation filter** | `test_p4_e_there_is_no_mandatory_substation_filter` | **PASS** | only 3 exclusion reasons exist, none of them grid |
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

### 5.5 Greedy objective shortfall against the optimal CBC solution (task 7)

Greedy against an exact CBC solve on the same problem, ε relaxed to zero so the comparison
isolates the objective greedy actually optimises. **Every exact solve reached optimality.**

**This is deliberately not called an "optimality gap".** A solver's optimality gap is the
distance between its own bound and its own incumbent, and it is reported separately, per
frontier point, as `cbc_optimality_gap`. What this table shows is a different quantity: how
much objective a heuristic left on the table against a known optimum. See §12.7.

| State | Budget 5 | Budget 20 | Budget 50 |
|---|---:|---:|---:|
| Washington | **0.0000%** | 0.8756% | 0.3753% |
| Tennessee | **0.0000%** | 0.4771% | 1.1501% |
| Montana | **0.0000%** | **3.1411%** | 1.0855% |
| Vermont | **0.0000%** | 0.8894% | 1.0564% |
| Texas | **0.0000%** | **0.0000%** | 0.6372% |
| California | 1.6549% | 1.0947% | **0.0000%** |

**Worst observed greedy objective shortfall against the optimal CBC solution: 3.14%**
(Montana at 20 sites). Greedy is exact at budget 5 in five of six states, and exact in three
further cells of this table. This is an observation on these eighteen problems, **not a
bound**: no approximation guarantee is claimed for the browser algorithm anywhere (§7.8,
amendment A11). Controlled fixtures are covered separately by
`test_the_greedy_shortfall_is_measured_against_an_exact_solve`.

**Timing:** slowest greedy solve **0.032 s** (Texas, 2,417 candidates) against a 2-second
budget — roughly 62x headroom. This is wall-clock time on the build machine and it moves a
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

---

## 12. Correction — 2026-08-31 (second round)

Appended, not merged: §11 and everything above it are preserved (CLAUDE.md §15.3 item 4).
External review **accepted** the §11 corrections — TIGER/Line PRISECROADS and the
S1100/S1200 selection are accepted for Core, and A-2.1 is accepted as resolved — and
identified **one newly exposed correctness issue** in the road filter that §11 introduced.
It is resolved here, together with four bounded naming and documentation items.

### 12.1 The blocker — road distance was measured to the nearest vertex

**What §11 shipped.** Distance from a cell centroid to the nearest TIGER **vertex**,
computed with a haversine ball tree. The limitation was noticed and recorded as assumption
**A-4.6**, deferred to Phase 6.

**Why that was wrong, and why deferring it was wrong.** A LineString's nearest vertex is
not generally its nearest point. A cell beside the middle of a long straight segment is
close to the road and far from both of its endpoints, so the measurement **overestimates**
distance. The overestimate is bounded by half the segment length — up to **2.96 km**
against the longest segment measured on this data (5.928 km, California) — on a filter
whose threshold is **5.0 km**.

Recording that as a deferred assumption was the mistake. This is not a number that comes
out slightly wrong; it is an error in a **hard candidate filter**, where an overestimate
does not degrade a value, it removes a cell from consideration entirely. The review is
right, and A-4.6 is closed by replacing the method rather than by confirming the guess.

**Segment lengths, measured across the six frontier states.** This is what bounds the
error, so it is reported rather than assumed:

| State | Features | Vertices | Segments | Mean segment | p99 | Longest |
|---|---:|---:|---:|---:|---:|---:|
| Washington | 3,006 | 376,007 | 373,001 | 56.9 m | 401.9 m | 3.377 km |
| Tennessee | 9,184 | 1,392,729 | 1,383,545 | 41.9 m | 245.9 m | 2.120 km |
| Montana | 1,251 | 252,599 | 251,348 | 76.8 m | 559.4 m | 3.438 km |
| Vermont | 1,432 | 178,596 | 177,164 | 42.9 m | 231.0 m | 1.236 km |
| Texas | 15,290 | 1,115,704 | 1,100,414 | 93.5 m | 608.8 m | 4.754 km |
| California | 7,351 | 1,246,491 | 1,239,140 | 54.0 m | 404.7 m | 5.928 km |

TIGER is densely vertexed — about 125 vertices per feature — which is why the practical
error turns out small. It is *not* why the method was acceptable.

### 12.2 What replaced it

`pipeline/spatial/distance.py` gains `PolylineIndex`, which measures distance to the
nearest **point on** the nearest segment. Three properties matter:

1. **The reported number is a real geodesic distance to a real place.** The nearest point
   along each segment is located in a tangent plane centred on the query point; the
   distance to *that point* is then measured with the same haversine used everywhere else
   in the pipeline. So the published value is a great-circle distance to an actual
   location on an actual road, not a planar approximation of one.
2. **It can never exceed the vertex distance.** A vertex is itself a point on the segment
   — the `t=0` and `t=1` cases — so the minimum over the segment is at most the minimum
   over its endpoints. `test_the_segment_distance_never_exceeds_the_vertex_distance`
   asserts this over a grid of 25 offsets, and `compare_distance_methods` raises rather
   than publishing if it is ever violated on real data.
3. **Segments are formed only within one road feature.** `RoadVertices` now carries
   CSR-style `offsets`, so vertex *i* and *i+1* are joined only when they belong to the
   same feature. Flattening the vertex list without them would join the end of one road to
   the start of the next and invent a segment that does not exist — asserted by
   `test_segments_are_never_formed_between_two_different_roads`, where the invented
   segment would put a query point 3.8 km from a road that is really 50+ km away.

**Cost of the correction.** Pruning keeps it cheap: the vertex distance is an upper bound,
so only segments with an endpoint within `vertex_distance + longest_segment` can beat it,
and only those are evaluated exactly. Washington's 569-cell benchmark takes **0.30 s**
against 0.09 s for the vertex method. The full `make phase4` run is unchanged in practice.

### 12.3 The synthetic regression fixture (review item 2)

`test_a_long_segment_is_not_reduced_to_its_endpoints`. A **two-vertex road about 76 km
long**, and a candidate cell whose centroid sits **2.22 km from its middle**:

| Quantity | Value |
|---|---|
| Distance by nearest **vertex** | **37.98 km** |
| Distance by nearest **point on segment** | **2.22 km** |
| Overestimate | **17x** |
| Vertex method at the 5.0 km filter | cell **excluded** |
| Corrected method at the 5.0 km filter | cell **admitted** |

The test asserts both the ratio and the filter outcome, and it calls
`vertex_road_distances` — the superseded method, retained only for comparison — to assert
the old behaviour explicitly, so the fixture cannot silently start passing because both
methods changed together.

The road is positioned relative to the **cell centroid** rather than to an arbitrary point,
because the filter measures from centroids and an H3 res-6 centroid can sit over 3 km from
any given point inside its own cell. A first version of this fixture placed the road
relative to a chosen coordinate and failed for that reason — the fixture was wrong, not the
implementation.

**A second defect the fixture caught.** The first implementation of the correction skipped
the exact refinement whenever the *vertex* distance exceeded a 30 km cap. That is precisely
backwards: a point beside a long segment is near the road while being far from every
vertex, so the shortcut skipped refinement exactly where it was needed, and the fixture
returned 37.98 km. The cap now gates on what is *provable* — the true distance is at least
`vertex_distance - longest_segment`, so refinement is skipped only when that lower bound
already exceeds the cap. `test_the_refinement_is_not_skipped_just_because_vertices_are_far`
locks it, and `assert_refinement_covers` raises if any threshold is ever swept past the
cap rather than answering it with an unrefined number.

### 12.4 What the correction changed across the six states (review item 3)

`pipeline/model/road_method_comparison.py` scores the corrected method against the
superseded one, per state, on everything the review asked for.

| State | Cells | Mean error | p99 error | Max error | Cells >100 m | Cells changing side of 5.0 km | Candidates vertex | Candidates corrected | Jaccard |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Washington | 1,054 | 2.4 m | 45.5 m | 193.2 m | 3 | **0** | 674 | **674** | **1.000000** |
| Tennessee | 1,603 | 1.7 m | 29.2 m | 169.1 m | 2 | **0** | 1,425 | **1,425** | **1.000000** |
| Montana | 432 | 2.8 m | 59.2 m | 138.0 m | 1 | **0** | 297 | **297** | **1.000000** |
| Vermont | 311 | 0.7 m | 10.6 m | 53.4 m | 0 | **0** | 250 | **250** | **1.000000** |
| Texas | 3,532 | 4.5 m | 67.9 m | 666.9 m | 18 | **0** | 2,417 | **2,417** | **1.000000** |
| California | 2,268 | 2.8 m | 53.3 m | 394.2 m | 10 | **0** | 1,253 | **1,253** | **1.000000** |

*(Cell counts and per-state error percentiles are read from
`per_state[].distance_method_comparison_vertex_vs_segment` in
`docs/evidence/P4-1_siting.json`.)*

**Portfolio overlap is 1.000 at 5, 20 and 50 sites in every state.** Demand and equity
objective deltas are exactly **0.00** everywhere. The frontier is unchanged: 96 of 96
`optimal`, every `cbc_optimality_gap` 0.0. The greedy shortfalls are unchanged.

This was verified rather than asserted: the regenerated artifact was compared against the
committed one key by key, normalising only the field renames of §12.5 and wall-clock
timings. Every frontier point matched, every shortfall record matched, and every per-state
key matched in all six states.

### 12.5 Regeneration (review item 4)

`docs/evidence/P4-1_siting.json` was regenerated. **No published value changed on its
merits** — the artifact differs only in the renamed fields, the new comparison block, the
corrected `distance_method` and `road_network` descriptions, and wall-clock times. Slowest
greedy solve is now **0.0323 s** (0.0288 s in the first submission, 0.023 s in
the §11 round — all three are wall clock on the build machine and move run to run, which
is why the gate asserts the 2-second budget and never a figure); worst greedy shortfall
remains **3.14%** (Montana at 20
sites).

The honest summary: **the defect was real and the fix was necessary, and it moved nothing.**
The practical error sits far below the 2.96 km worst case because the longest segments
happen not to lie near candidate cells. That is a property of this snapshot, not a
guarantee — which is exactly why the method was corrected rather than the outcome accepted.
On sparser geometry, or at a tighter threshold, the same defect would change results.

### 12.6 Naming (review item 5)

"Road proximity" implied proximity to roads in general. What is measured is proximity to
**TIGER/Line 2024 primary (`S1100`) and secondary (`S1200`) roads**, with local streets
(`S1400`) excluded by design. Renamed accordingly:

| Where | Was | Now |
|---|---|---|
| Exclusion reason | `beyond_road_network` | **`beyond_primary_secondary_road_network`** |
| Enum member | `ExclusionReason.BEYOND_ROAD_NETWORK` | **`ExclusionReason.BEYOND_PRIMARY_SECONDARY_ROADS`** |
| Artifact | no statement of scope | **`road_network`**: *"TIGER/Line 2024 PRIMARY (MTFCC S1100) and SECONDARY (S1200) roads only. NOT all roads: local streets (S1400) are excluded by design."* |
| Artifact | `distance_method` describing vertex distance | **`distance_method`** describing nearest-point-on-segment, and naming the superseded method as wrong |
| `METHODOLOGY.md` §4.5, `LIMITATIONS.md` | "road proximity" | proximity to primary and secondary roads, with the consequence stated: a cell can be excluded while being served by local streets |

`test_the_shipped_summary_names_the_method_and_the_road_classes` asserts the artifact
carries the road classes and the phrase "NOT all roads".

### 12.7 Greedy shortfall is not an optimality gap (review item 6)

Two different quantities were both being called an optimality gap. They are now separated
in code, in the artifact and in the documentation:

| Quantity | What it is | Published as |
|---|---|---|
| **CBC solver optimality gap** | The distance between the solver's own bound and its own incumbent. A property of the *solve*. | `cbc_optimality_gap`, with `cbc_status`, per frontier point |
| **Greedy objective shortfall** | How much objective the browser heuristic left on the table against a known optimum. A property of the *heuristic*. | `greedy_objective_shortfall_vs_optimal_cbc`, with `optimal_cbc_objective` and `cbc_status` |

**§11 above is left as written.** It is a dated correction section from the previous round
and CLAUDE.md §15.3 item 4 forbids rewriting prior report content in place, so its sentence
"the worst empirical optimality gap moved 3.06% → 3.14%" stands as the record of what was
said at the time. It is superseded by this section: that quantity is the worst observed
greedy objective shortfall against the optimal CBC solution.

The class `OptimalityGap` is now `GreedyShortfall`; `measure_optimality_gap` is
`measure_greedy_shortfall`; the property `.gap` is `.shortfall`; the artifact section
`empirical_optimality_gaps` is `greedy_objective_shortfall_vs_optimal_cbc`. Every shortfall
record carries a `measures` field stating in full: *"observed shortfall of the greedy
objective against the optimal CBC objective on the same problem. NOT a solver optimality
gap and NOT an approximation bound: no bound is claimed for the browser algorithm."*

`test_the_greedy_shortfall_is_never_called_an_optimality_gap` asserts that no shortfall key
contains `optimality_gap` and no frontier key starts with `greedy`, so the two cannot drift
back together.

**The 3.14% figure is therefore restated as: the worst observed greedy objective shortfall
against the optimal CBC solution**, across six states and three budgets — Montana at 20
sites. It is an observation on those eighteen problems. It is not a bound, and §7.8 with
amendment A11 remains satisfied: no approximation bound is claimed anywhere.

### 12.8 What was not reopened

Per the review's instruction, no other Phase 4 design decision was revisited. The ε sweep
is still 8 levels per state per direction, 96 points. The frontier sample is still the same
six states with the same pre-outcome stratification. The equity indicator, the k-ring, the
uniform site cost and the saturation threshold are unchanged.

### 12.9 Assumption ledger and impact log

- **A-4.6 CLOSED** — withdrawn and resolved by replacing the method, not by confirming the
  assumption.
- **A-4.8 OPENED** — the tangent-plane step assumes it selects the same point along a
  segment that an exact spherical calculation would. It can only affect *which* point is
  chosen, never the distance reported for it, so the published value remains a rigorous
  upper bound on the true minimum; what is unproven is that no other point is closer by an
  amount the projection hid. Millimetres at these distances. Deferred to Phase 6 or to
  whenever a geodesic geometry dependency is added.
- **Impact-log entry I-20**, severity **S2 Degrading** — the method could falsely exclude
  cells from a hard filter; measurement afterwards showed it changed no published value on
  this data, which is why it is S2 rather than S1.

### 12.10 What was re-run

Gates 0, 1, 2, 3 and 4 in full, from a regenerated `docs/evidence/P4-1_siting.json`.
Nothing in this section is carried forward from an earlier run.

---

## 13. Gate-runtime optimisation and the A-4.8 validation — 2026-08-31 (third round)

Appended, not merged. Two pieces of work: the gate was made to stop doing the same thing
twice, and assumption **A-4.8** — opened in §12 — was validated and closed.

### 13.1 Gate runtime: 13 min 11 s → 8 min 22 s

**What was wrong.** Every gate ran the complete test suite **twice**: once plain
(`pytest`), then the identical selection again under coverage (`pytest --cov`). And
validating Phase 4 was being done by invoking `make gate PHASE=0` … `PHASE=4` in sequence,
which repeated that doubled work five times — the repository has *one* test suite and
*one* set of coverage thresholds, so four of those five passes added no evidence at all.

**What changed.** Recorded as CLAUDE.md amendments **A25** and **A26**:

| | Was | Now |
|---|---|---|
| Full suite + coverage | two invocations of the same selection | **one** coverage-instrumented invocation, which runs the same complete selection with no deselection, fails on any test failure, produces the report, and enforces every threshold |
| G-C | read as "run each earlier phase's whole gate ceremony" | **replay each earlier phase's phase-specific gate suite**, each as its own invocation, printing its name, PASS/FAIL and test count |

**Nothing was removed.** Not a test, not a test selection, not a coverage threshold, not
the determinism check, not a smoke-forward check, not the lint, not a regression suite.
`tests/regression/test_gate_protocol.py` (34 tests) asserts exactly that, and would fail if
any of it were quietly dropped later:

- every required prior-phase suite appears in the Makefile's `PRIOR_GATE_SUITES`, **and**
  the Makefile carries nothing the test does not know about — the check runs in both
  directions, so a suite cannot be dropped *and* an added one cannot go unrecorded;
- every replayed suite path actually exists;
- no gate runs a bare whole-repository `pytest` any more;
- every gate still runs the suite under coverage;
- the coverage invocation carries no path argument and no `-k`/`-m` deselection, so
  merging the two runs could not have lost coverage of any test;
- all nine coverage thresholds are still enforced, by tier;
- no gate recursively invokes another gate;
- the Phase 4 gate still runs all eight of its steps and both of its own suites;
- a failing prior suite fails the gate rather than being printed and ignored — the loop
  continues after a failure so every suite is reported, which makes forgetting the exit
  status an easy mistake, so `failed=1` and `exit 1` are asserted.

**What the Phase 4 gate now prints for G-C:**

```
--- 4. prior-phase gate suites replayed (Phase 0, 1, 2 and 3) ---
    tests/regression/test_source_findings.py             PASS  23 passed
    tests/regression/test_domain_rules.py                PASS  39 passed
    tests/regression/test_phase2_gates.py                PASS  37 passed
    tests/regression/test_phase3_gates.py                PASS  20 passed
    tests/regression/test_phase3_corrections.py          PASS  32 passed
    tests/integration/test_smoke_forward.py              PASS  11 passed
    tests/integration/test_smoke_forward_phase2.py       PASS  5 passed
    tests/integration/test_smoke_forward_phase3.py       PASS  5 passed
    all prior-phase gate suites PASS
```

**The expensive fixture.** Profiling contradicted the obvious guess. `build_surface` costs
**0.47 s**; the real cost was `load_hex_supply` at **19.3 s of a 28 s prelude** — three
DBSCAN passes over the national station export, once per A-2.1 clustering condition, repeated
by every driver test. It is now memoised with `functools.lru_cache`, exactly as
`allocation_penalty` already was, on the same reasoning: a pure function of an immutable
on-disk snapshot. It returns a **read-only mapping** (`MappingProxyType`) of frozen
`HexSupply` values, so no caller can mutate a shared entry and change what a later caller
sees — which is what keeps tests order-independent. Temporary snapshots keep their own cache
key, so test-local paths stay test-local. The genuine end-to-end reconstruction test —
`test_the_artifact_is_written_where_asked`, which drives `main()` through the real Phase 3
pipeline from its normal inputs — is untouched and still builds everything for real. Nothing
was replaced with a mock.

**Measured, on the same machine, `make gate PHASE=4` end to end:**

| | Wall clock |
|---|---:|
| Before | **13 min 11 s** |
| After | **8 min 22 s** |
| Saving | **4 min 49 s, 37%** |
| Before, as Phase 4 was actually being validated (gates 0–4 in sequence) | **~66 min** |
| After (one authoritative gate) | **8 min 22 s**, ~87% less |

The wall-clock acceptance criterion is unaffected by instrumentation: the ≤2 s greedy
budget is measured by `python -m pipeline.model.run_phase4`, which the gate runs
**uninstrumented** at its rebuild step, and the criterion is asserted against the figure
that run recorded. No second repository-wide `pytest` exists for timing and none may be
reintroduced for it.

### 13.2 A-4.8 validated and closed

**The assumption.** §12 corrected road distance to measure to the nearest *point on* a
segment, locating that point in a tangent plane centred on the query point. The reported
distance is then measured with haversine, so it is always a real geodesic distance to a
real place on a road — a rigorous upper bound on the truth whatever the projection does.
What the projection *could* do is pick a slightly different point, making the reported
distance a little larger than the true minimum. That was A-4.8, and §12 deferred it.

**How it was tested.** `pipeline/validation/road_geometry.py`. Both methods parameterise
the **same curve** — `lerp(A, B, t)` in (latitude, longitude) — so the only thing under test
is which `t` is chosen. The reference minimises the true haversine distance along that curve
by **golden-section search on t**, with no projection anywhere; the distance from a fixed
point to points along the curve is unimodal in `t`, which is what makes the search exact to
convergence, and the endpoints are checked explicitly because the interior optimum can lie
outside [0, 1]. The error is `reported − exact`, which cannot be negative: the reported value
is the distance at one `t`, the reference is the minimum over every `t`.

**Result — 200 cells per state, all six frontier states:**

| State | Comparisons | Mean error | p99 | **Max** | Negative errors | Cells reclassified at 5 km |
|---|---:|---:|---:|---:|---:|---:|
| Washington | 200 | 0.096 mm | 2.459 mm | **4.917 mm** | 0 | **0** |
| Tennessee | 200 | 0.004 mm | 0.079 mm | **0.185 mm** | 0 | **0** |
| Montana | 200 | 0.181 mm | 1.414 mm | **17.539 mm** | 0 | **0** |
| Vermont | 200 | 0.002 mm | 0.030 mm | **0.042 mm** | 0 | **0** |
| Texas | 200 | 0.016 mm | 0.109 mm | **2.107 mm** | 0 | **0** |
| California | 200 | 0.013 mm | 0.302 mm | **0.810 mm** | 0 | **0** |

Worst disagreement anywhere: **17.5 mm**, against a **5,000,000 mm** filter threshold.

**And an adversarial case, because six real states is not a proof.** Searching over
latitude, segment span, offset and tilt for the worst case inside the regime the method is
actually used in — distances within the refinement cap — gives a 6-degree-span segment at
**78° north** with the query point ~15 km away, where a tangent plane distorts most. Error
there: **95 mm**. Still four orders of magnitude below the threshold.
`test_even_an_adversarial_projection_case_errs_by_under_ten_centimetres` locks it.

**One honest detail.** The first run reported four "impossible" negative errors. They were
**1e-13 km — 0.1 nanometres** — last-unit-in-the-last-place disagreement between the
vectorised numpy haversine used for the reported value and the scalar `math` one used for
the reference, with both values identical to every printed digit. The tolerance was set to
1e-9 km (a micrometre), which is far above float noise and far below anything geometrically
meaningful, and the reasoning is recorded in the code and in the artifact rather than the
number being quietly adjusted until it passed.

**A-4.8 is CLOSED.** Both assumptions opened by the road-filter work — A-4.6 and A-4.8 —
are now resolved by measurement rather than by argument.

### 13.3 What was re-run

`make gate PHASE=4`, the authoritative Phase 4 gate, which replays all four prior phases'
gate suites (see the output quoted in §13.1). Not Phase 5.
