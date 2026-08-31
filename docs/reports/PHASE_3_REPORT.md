# Phase 3 Report — Demand and Uncertainty

## 0. Report metadata

| Field | Value |
|---|---|
| Phase | 3 — Demand + uncertainty |
| Date | 2026-08-28 |
| Gate status | **PASS** — all five parts (G-A acceptance, G-B coverage, G-C regression, G-D forward viability, G-E report) |
| Commit | the `gate(phase-3): PASS` commit that carries this report |
| Planned duration | 2.25 part-time weeks |
| Reproduce every number | `python -m pipeline.model.run_phase3` (cached inputs only; no network, no credentials) |
| Prepared by | Claude Code |

---

## 1. Context for a reader with zero prior knowledge

### 1.1 What this project is

**VoltGap** is an open, statically hosted decision-support application that answers one
question: *given a budget and a set of policy priorities, where should the next EV
charging infrastructure be built in the United States, and how confident should we be in
that answer?* Its users are infrastructure planners, charge point operators, state energy
offices and researchers. Its output is a ranked, budget-feasible portfolio of candidate
hexagonal sites with scores, uncertainty bands, tradeoff context, and CSV/GeoJSON export.

It is deliberately **not** a general EV statistics browser, a consumer charger finder, a
vehicle comparison tool, or a real-time availability map.

Four constraints shape everything. **Zero recurring cost**: free tiers only, no paid API,
no managed database. **Static hosting**: an offline Python pipeline produces artifacts
that a browser-side static frontend consumes. **Uncertainty is a first-class output**: no
point estimate ships without it. And **no supply-to-demand feedback loop**: charger
counts, port counts, charger density and distance-to-charger are *forbidden* in the
demand model, because existing infrastructure is an outcome of prior investment
decisions, and predicting demand from it and then siting from that demand launders
historical deployment patterns into "need".

### 1.2 The architecture in one paragraph

Python 3.12 pipeline, `uv` for dependencies, DuckDB as a file-based warehouse with no
server, pandera schemas that fail the build on violation, and a phase-gate protocol in
which no phase begins until the previous one's gate passes. Sources are retrieved through
adapters that must preserve every source row; business filtering happens in an
intermediate SQL layer where it is visible and testable. Everything published carries the
vintages of the sources it came from.

### 1.3 What the previous phases produced

**Phase 0** (source contract) verified 60 sources into `SOURCES.yml` plus a generated
`SOURCES.observed.json`. It established that the NREL host had migrated to
`developer.nlr.gov`, that AFDC reported-power coverage is 88.11% port-weighted on public
operational supply, that the NREL county home-charging dataset is a *parametric scenario
surface* rather than a dated observation (so home charging is excluded from the primary
objective), that AFDC publishes ten annual state registration vintages 2016–2025, and
that **no national substation dataset exists**, which removed substation proximity as a
mandatory siting filter.

**Phase 1** (ingestion and canonical model) found that **no AFDC charging-unit identifier
exists at any level** — 99.4% of unit objects are byte-identical to another — so the
`ports` and `connectors` tables are deliberately not populated and
`charging_unit_record_key` is explicitly synthetic and per-snapshot. It built the G1–G14
regression suite and a 15-rule terminology copy lint that has run in CI ever since.

**Phase 2** (supply and access) established the non-double-counting capacity rule:
16,610 charging units expose more than one connector standard on a single service port,
and naive summing overstates national capacity by 2,104,242 kW (10.69%). National figures:
19,001,862 kW public capacity, DCFC access gap 32,169,758 people (9.71%), L2 access gap
53,584,530 (16.17%).

A **Live Integration Assurance Checkpoint** then exercised every Core source's production
path with real credentials, found and fixed two defects, and validated the HUD ZIP→tract
crosswalk. Its Washington paired comparison selected HUD `res_ratio` over land-area
weighting as the ZIP→tract allocation method.

Immediately before this phase, four corrections were made: two checkpoint documents'
test counts were wrong; "acceptability floor" was corrected to **maximum acceptable TVD**;
the Washington denominator was reconciled record by record (294,193 = 292,581 included +
1,612 excluded by named reason); and **Washington was reclassified as
preprocessing-method-selection data rather than independent validation**, since it chose
the crosswalk.

### 1.4 What this phase was supposed to do

CLAUDE.md §15.5 declares Phase 3's deliverable as "Propensity model, reconciliation,
continuous uncertainty, tiers", with these acceptance criteria, quoted:

> Leave-one-state-out run across every Tier A state with WAPE, MAE, R² per held-out
> state. D2 enforced: a test asserts no supply-derived feature is present in the primary
> feature set. Reconciliation identity holds exactly (tract sums equal constraints to
> within floating point tolerance). Uncertainty calibration curve produced. Ablation with
> supply features run and reported separately.

A pre-registration document (`docs/evidence/P3-0_phase3_preregistration.md`), written and
committed **before any model was fitted**, additionally fixed: how a held-out state is
scored, which states may enter the headline aggregate, the estimator-selection rule, how
allocation error enters the uncertainty score, and where the confidence-tier boundary
sits.

---

## 2. What was built

### 2.1 Modules created

| Path | Purpose | Lines | Key public functions |
|---|---|---:|---|
| `pipeline/sources/census_acs.py` | ACS 5-year features at tract, ZCTA and county grain | 308 | `AcsSource`, `batches`, `assert_no_supply_features` |
| `pipeline/model/features.py` | 14 derived features, D2 enforcement, imputation | 440 | `FEATURES`, `build_feature_rows`, `impute`, `assert_primary_feature_set_is_clean` |
| `pipeline/model/observed.py` | Observed sub-state registrations at each source's own geography | 433 | `load_atlas_state`, `load_washington`, `load_state_totals` |
| `pipeline/model/panel.py` | Joins observations to ACS features; the out-of-state ZIP guard | 275 | `build_area_table`, `build_state_panel`, `prediction_rows` |
| `pipeline/model/demand.py` | Five candidate estimators, metrics | 364 | `candidate_estimators`, `fit`, `wape`, `mae`, `r_squared` |
| `pipeline/model/reconcile.py` | `Reconciler` protocol, proportional and IPF | 258 | `ProportionalReconciler`, `IterativeProportionalFitting` |
| `pipeline/model/uncertainty.py` | Five components, tiers, weight sensitivity | 288 | `combine`, `bc_threshold`, `assign_tier`, `AllocationPenalty` |
| `pipeline/model/build_demand.py` | The national tract surface | 326 | `build_surface` |
| `pipeline/model/ablation.py` | The one place supply features may appear | 161 | `load_supply_by_zip`, `with_supply_features` |
| `pipeline/model/run_phase3.py` | One command reproduces every Phase 3 number | 272 | `run`, `main` |
| `pipeline/validation/demand_model.py` | Leave-one-state-out at native granularity | 371 | `run_loso`, `score_state`, `select_estimator` |
| `pipeline/validation/washington.py` | The measured transformation ladder (extended) | 451 | `measure_transformation_ladder`, `statewide_tvd` |
| `pipeline/validation/scope.py` | Balanced record ledgers (from the pre-phase corrections) | 186 | `classify`, `ledger_from`, `ExclusionLedger` |

**4,133 lines across the thirteen modules**, all at 100% line and branch coverage.

### 2.2 Key implementations, quoted

**D2 enforced by execution, not by prose.** The primary feature set may read ACS
demographics and land area, and nothing else. This is proved by running every feature
against a row that records what it asked for:

```python
# pipeline/model/features.py
class _RecordingRow(dict):
    """A row that answers every lookup and remembers what was asked for."""
    def __init__(self) -> None:
        super().__init__()
        self.accessed: set[str] = set()

    def get(self, key, default=None):
        self.accessed.add(str(key))
        return 1.0


def assert_primary_feature_set_is_clean(features=FEATURES) -> None:
    assert_no_supply_features(ACS_VARIABLES)
    allowed = set(ACS_VARIABLES) | {"land_area_km2"}
    for feature in features:
        used = feature_inputs(feature)
        stray = sorted(used - allowed)
        if stray:
            raise FeatureError(
                f"D2 violation: feature {feature.name!r} reads {stray}, which is not a "
                "declared ACS demographic variable. ...")
```

**The out-of-state mailing ZIP guard**, which is the single most consequential piece of
code written this phase:

```python
# pipeline/model/panel.py
        if observations.source_geography is SourceGeography.USPS_ZIP:
            states_touched = membership.get(geoid)
            if states_touched is None:
                drop("zip_has_no_like_numbered_zcta", ..., count.bev_count)
                continue
            if state_fips not in states_touched:
                drop("zip_outside_the_registering_state",
                     "the ZIP Code lies wholly outside the state whose DMV reported "
                     "it - an out-of-state mailing address. The vehicles are real and "
                     "belong in the state total, but they cannot be attributed to any "
                     "in-state area, and joining them to a like-numbered ZCTA "
                     "elsewhere would import that area's households as exposure",
                     count.bev_count)
                continue
```

**Exact reconciliation**, valid only on a partition, which is checked rather than assumed:

```python
# pipeline/model/reconcile.py
    def reconcile(self, estimates, constraints) -> ReconciledEstimates:
        unconstrained = _check_partition(estimates, constraints)
        values = np.array(estimates, dtype=np.float64, copy=True)
        for constraint in constraints:
            index = list(constraint.members)
            group = values[index]
            subtotal = float(group.sum())
            if subtotal > 0:
                values[index] = group * (constraint.total / subtotal)
            else:
                values[index] = constraint.total / len(index)
```

**The statewide comparability metric** that made the transformation ladder meaningful:

```python
# pipeline/validation/washington.py
def statewide_tvd(records, links, source_field, state_fips=WASHINGTON_FIPS):
    """Statewide tract-level TVD for one transformation.

    **This is the metric the uncertainty model needs, and the within-group mean is not.**
    A within-group TVD averages many small separate problems and is not comparable
    across grains ...
    """
```

### 2.3 Data artifacts produced

| Artifact | Grain | Rows | Size | Contents |
|---|---|---:|---:|---|
| `docs/evidence/P3-2_demand_model.json` | mixed | — | 109 KB | LOSO table, transformation ladder, national surface summary, calibration curve, ablation |
| `docs/evidence/P3-1_wa_allocation_scope_and_error.json` | ZIP | 431 | 6 KB | Washington paired allocation comparison with a balanced ledger |
| National tract surface (in-memory / rebuildable) | census tract | **84,400** | — | `bev_estimate`, `evidence_grain`, `estimate_method`, `uncertainty_score` + 5 components, `confidence_tier`, constraint and vintage |

The tract surface is rebuilt by one command, `python -m pipeline.model.run_phase3`, from
cached inputs only — no network, no credentials.

### 2.4 The published tract row, field by field

| Field | Type | Meaning |
|---|---|---|
| `geoid` | 11-char string | 2020 census tract |
| `state_fips` | 2-char string | Derived from the GEOID, never from a name (G13) |
| `households` | float | ACS B25003_001E; the model's exposure |
| `population` | float | ACS B01003_001E |
| `bev_estimate` | float | Reconciled battery-electric registrations |
| `bev_estimate_unreconciled` | float | The raw model output, before the constraint |
| `evidence_grain` | enum | `native_tract` / `county_anchored` / `state_total_only` |
| `estimate_method` | enum | `directly_observed` / `modeled` / `modeled_high_uncertainty` |
| `uncertainty_score` | float in [0,1] | Weighted mean of five components |
| `uncertainty_components` | map | The five components, individually |
| `confidence_tier` | A / B / C | Presentation over the score; A is **"sub-state anchored"**, never "observed" |
| `constraint` | string | The county or state group whose total it reconciles to |
| `constraint_vintage` | string | Which AFDC registration vintage that total came from |

---

## 3. Decisions made and why

| Decision | Options considered | Chosen | Rationale | Reversible? |
|---|---|---|---|---|
| Target quantity | All plug-in vehicles; BEV only | **BEV only** | AFDC publishes `Electric (EV)` and `Plug-In Hybrid Electric (PHEV)` as separate columns and the delivered seed totals match the BEV column. It is the only state constraint available for all 51 jurisdictions; counting PHEVs would make every tract estimate irreconcilable with it | Yes, if a PHEV-inclusive state series appears |
| Fitting grain | Allocate counts to tracts and fit there; fit at each source's own geography | **Fit at the observed geography** | Allocating would manufacture tract labels from a crosswalk with a measured 17.94% EV-weighted TVD and then score a model on them. ACS publishes features at tract, ZCTA and county grain, so no pseudo-label is needed | Yes |
| Estimator | Ridge, Poisson GLM, boosted Poisson, two baselines | **Poisson GLM** | Pre-registered rule: lowest EV-weighted LOSO WAPE, ties inside 1pp to the simpler model. Poisson 0.3312 against boosted 0.3320 — inside the band, so the simpler model wins | Yes; the rule would re-decide on new data |
| Reconciler | Proportional; IPF/raking | **Proportional** | Every constraint Phase 3 applies partitions the tracts (counties nest in states, tracts in counties), and on a partition the exact solution is one scaling. IPF is implemented and tested for the overlapping case | Yes |
| ZIP totals as constraints | Apply via IPF; do not apply | **Do not apply in Phase 3** | Scope, not merit. The ladder shows ZIP-anchored allocation places EV mass *better* than a state total alone (0.1621 vs 0.3049), so the case against is weak; evaluating a new constraint set properly is its own work. Recorded in `docs/FUTURE_WORK.md` | Yes |
| Constraint vintage | Always latest; nearest to each state's snapshot | **Nearest** | North Carolina's June 2024 snapshot against the 2025 total is −45.27%; against the contemporaneous 2023 vintage it is −5.66% | Yes |
| Uncertainty weights | Fit them; declare them | **Declare, equal at 0.2** | Fitting them against validation results would make the calibration check meaningless. Declared, exposed in `thresholds.yml`, shipped with a sensitivity report, and labelled not calibrated everywhere | Yes, with a documented method |
| `zip_anchored` in the published surface | Use it for the 11 ZIP states; omit it | **Omit** | Phase 3 allocates no ZIP count onto a tract, so no tract value is anchored to a ZIP total. Claiming otherwise would overstate the evidence | Yes, if ZIP constraints are later applied |
| Out-of-state ZIPs | Drop silently; renormalise; exclude by name | **Exclude by name, count in the ledger** | The vehicles are real and belong in the state total; they simply cannot be attributed to any in-state area | No — this is a correctness fix |

---

## 4. Acceptance criteria verification (Gate part G-A)

Every criterion is checked by a named test in `tests/regression/test_phase3_gates.py`,
which reads the published evidence artifact so the criteria are verified against the
numbers that ship.

| # | Criterion (quoted) | Verifying test | What it asserts | Result | Evidence |
|---|---|---|---|---|---|
| 1 | "Leave-one-state-out run across every Tier A state with WAPE, MAE, R² per held-out state" | `test_p3_a_loso_runs_across_every_usable_state_with_all_three_metrics` | 14 independent states; every row carries all three metrics and a positive area count | **PASS** | 14 states, 15 rows including Washington |
| 2 | (pre-registration §3) each state scored at its native granularity | `test_p3_a_every_state_is_scored_at_its_own_observed_granularity` | `usps_zip→zcta`, `county→county`, `tract→tracts` for every row | **PASS** | 15/15 rows |
| 3 | (pre-registration §5) selection rule applied as written | `test_p3_a_the_selection_rule_was_pre_registered_and_applied` | The chosen estimator is within the 1pp tie-break band of the best | **PASS** | poisson 0.3312, best 0.3312 |
| 4 | (§18 anti-pattern 2) models must beat the baselines | `test_p3_a_both_models_beat_both_baselines` | All three models beat both baselines | **PASS** | 0.331/0.332/0.379 vs 0.710/0.712 |
| 5 | (pre-registration §2) Washington excluded from the independent aggregate | `test_p3_b_washington_is_excluded_from_the_independent_aggregate` | `WA` absent from `independent_states`, present in the exclusion map with its status | **PASS** | `non_independent_preprocessing_selection_state` |
| 6 | (pre-registration §2) Washington still run and reported separately | `test_p3_b_washington_is_still_run_and_reported_in_its_own_row` | WA rows exist, all with `independent: false` and a status string | **PASS** | WAPE 0.381, R² 0.501 at tract grain |
| 7 | "D2 enforced: a test asserts no supply-derived feature is present in the primary feature set" | `test_p3_c_the_primary_feature_set_contains_no_supply_derived_feature` | Structural check passes; supply names disjoint from primary names | **PASS** | 14 primary features, 3 supply features, disjoint |
| 8 | "Ablation with supply features run and reported separately" | `test_p3_c_the_ablation_is_run_and_reported_under_its_own_heading` | Warning text present, both aggregates present, feature list matches | **PASS** | §9.8 below |
| 9 | "Reconciliation identity holds exactly" | `test_p3_d_the_reconciliation_identity_holds_to_floating_point` | Max residual < 1e-6, zero unconstrained tracts | **PASS** | **2.33e-10**, 0 unconstrained |
| 10 | "Uncertainty calibration curve produced" | `test_p3_e_a_calibration_curve_is_produced` | ≥2 bins, correct keys, bins ordered by uncertainty | **PASS** | 5 bins of 353–354 tracts |
| 11 | (§18 anti-pattern 4) weights never presented as calibrated | `test_p3_e_the_weights_are_never_presented_as_calibrated` | `weights_are_calibrated` is `false`; 5 sensitivity entries | **PASS** | — |
| 12 | (§7.4) transformation penalty measured, not chosen | `test_p3_e_the_transformation_penalty_is_measured_not_chosen` | HUD rung present; measured values respect the predicted ordering; native = 0 | **PASS** | 0.0 < 0.1621 < 0.2367 < 0.3049 |
| 13 | (A2) two orthogonal status fields, never collapsed | `test_p3_f_evidence_grain_and_tier_are_reported_separately` | Both breakdowns sum to the tract count | **PASS** | 84,400 both ways |
| 14 | (§17) no ZIP-derived tract value labelled directly observed | `test_p3_f_no_tract_is_labelled_zip_anchored` | `zip_anchored` absent from the surface | **PASS** | Satisfied by construction |
| 15 | (§7.4.2) Tier A is exactly the sub-state anchored tracts | `test_p3_f_tier_a_exists_only_where_sub_state_evidence_constrains_the_value` | Tier A count equals non-`state_total_only` count | **PASS** | 5,973 = 1,769 + 4,204 |
| 16 | (D8) every observed source publishes a balanced ledger | `test_p3_g_every_observed_source_publishes_a_balanced_ledger` | `retrieved == included + excluded_total` for all 15 states | **PASS** | 15/15 |
| 17 | (D8) every panel join publishes a balanced ledger | `test_p3_g_every_panel_join_publishes_a_balanced_ledger` | Same, for the join stage | **PASS** | 15/15 |
| 18 | the out-of-state ZIP defect is visible | `test_p3_g_the_out_of_state_zip_defect_is_visible_in_the_ledgers` | Oregon's ledger records the exclusion | **PASS** | 1,253 vehicles |
| 19 | target definition is stated in the artifact | `test_p3_h_the_target_is_battery_electric_and_says_so` | "battery-electric" and "PHEV" both present | **PASS** | — |
| 20 | pre-registration is named and exists | `test_p3_h_the_pre_registration_is_named_in_the_artifact` | Path recorded and present on disk | **PASS** | — |

**Criteria passed: 20/20.**

---

## 5. Test and coverage evidence (Gate part G-B)

### 5.1 Suite summary

```
$ .venv/bin/python -m pytest
861 passed, 47 deselected in 95.73s (0:01:35)
```

The 47 deselected are the `live` tests, excluded by `addopts = -m "not live"` in
`pyproject.toml` so that no deterministic gate ever opens a socket. The suite grew from
609 tests at the start of this phase to **861**, of which **252 were written this phase**
across 13 new files:

| Test file | Tests | Covers |
|---|---:|---|
| `tests/unit/test_features.py` | 25 | Feature definitions, D2 by execution, imputation, land area |
| `tests/unit/test_observed.py` | 25 | Atlas and Washington extraction, ledgers, state totals |
| `tests/unit/test_panel.py` | 18 | The out-of-state ZIP guard, join accounting, area tables |
| `tests/unit/test_demand_and_reconcile.py` | 31 | Five estimators, metrics, both reconcilers |
| `tests/unit/test_uncertainty.py` | 25 | Five components, weights, tiers, sensitivity |
| `tests/unit/test_demand_validation.py` | 23 | LOSO, vintage alignment, the selection rule |
| `tests/unit/test_transformation_ladder.py` | 24 | The measured ladder, the ZCTA-state index |
| `tests/unit/test_census_acs.py` | 21 | ACS batching, the HTML key trap, geographies |
| `tests/unit/test_build_demand.py` | 14 | The national surface, grains, tiers |
| `tests/unit/test_ablation.py` | 13 | Supply aggregation, the D2 boundary |
| `tests/unit/test_run_phase3.py` | 8 | The one-command driver |
| `tests/regression/test_phase3_gates.py` | 20 | The 20 acceptance criteria of §4 |
| `tests/integration/test_smoke_forward_phase3.py` | 5 | Phase 4's core operation against real output |
| **Total** | **252** | |

### 5.2 Coverage by module

Measured by `make coverage`, which runs one instrumented pass and then enforces each
threshold against the same coverage data, capturing output to a file and testing the exit
status explicitly — the fix for impact I-4, where a `tail` in the pipeline had been
swallowing every coverage failure.

| Module | Statements | Missed | Branches | Partial | Line % | Branch % | Required | Met? |
|---|---:|---:|---:|---:|---:|---:|---|---|
| `pipeline/model/` | 1,606 | 0 | 364 | 0 | 100% | 100% | 100% | **yes** |
| `pipeline/validation/` | 534 | 0 | 150 | 0 | 100% | 100% | 100% | **yes** |
| `pipeline/spatial/` | 299 | 0 | 78 | 0 | 100% | 100% | 100% | **yes** |
| `pipeline/discovery/` | 677 | 0 | 198 | 0 | 100% | 100% | 100% | **yes** |
| `pipeline/quality/` | 287 | 0 | 64 | 0 | 100% | 100% | 100% | **yes** |
| `pipeline/schemas/` | 52 | 0 | 2 | 0 | 100% | 100% | 100% | **yes** |
| `pipeline/sources/` | 316 | 0 | 78 | 0 | 100% | 100% | ≥85% | **yes** |
| `pipeline/transform/` | 100 | 0 | 14 | 0 | 100% | 100% | ≥85% | **yes** |
| **Repository total** | **4,055** | **0** | **986** | **0** | **100%** | **100%** | ≥70% | **yes** |

`pipeline/validation/` first binds at 100% from this phase: it was created by the
pre-phase corrections and extended here, and the Makefile tier was added accordingly.
`pipeline/model/` grew from 527 statements to 1,606 and `pipeline/sources/` from 213 to
316, both still at 100% line and branch.

### 5.3 Coverage exclusions

Every `pragma: no cover` in code written this phase, with its justification:

| Location | Reason | Justified? |
|---|---|---|
| `demand.py:114,116` | `Estimator` Protocol method bodies (`...`), never executed | Yes — a Protocol declaration has no runtime body |
| `reconcile.py:122` | `Reconciler` Protocol method body | Yes — same |
| `run_phase3.py:127` | `if not scores` in the calibration curve | Yes — Washington is present in every full run; the branch exists so a partial run degrades rather than crashes |
| `run_phase3.py:151` | `if len(primary) <= 3` in the ablation | Yes — eleven ZIP-grain states always qualify; the guard exists so the ablation reports "not run" rather than producing a meaningless comparison |
| `run_phase3.py:278` | `if __name__ == "__main__"` | Yes — module entry point |
| `ablation.py:97` | `except ValueError` on `unit_port_count` | Yes — AFDC port counts are always numeric; the guard prevents one malformed record from failing a national aggregation |
| `washington.py:449` | `except ValueError` on ACS household counts | Yes — same shape |
| `demand_model.py:88` | `except ValueError` on a malformed snapshot date | Yes — defensive; a bad date returns `None` and the newest vintage is used |
| `demand_model.py:363` | `if index.size == 0` in `array_split` | Yes — `array_split` fills bins left to right and cannot produce an empty leading bin |

Pre-existing exclusions in `allocation_error.py` (4) and `build_supply_access.py` (1) were
justified when written and are unchanged.

One pragma written during this phase was **removed rather than justified**: an unused
`observed_totals` helper in `run_phase3.py`. A pragma on dead code is a pragma on code
that should not exist.

### 5.4 Notable tests, with assertions quoted

**D2 is not testable by reading the feature list; it is testable by running it.**

```python
# tests/unit/test_features.py
def test_a_feature_reaching_outside_the_declared_variables_is_rejected() -> None:
    """The guarantee is structural: a supply input fails here even if the name is bland."""
    smuggled = Feature("neighbourhood_quality", "innocuous", "innocuous",
                       lambda r: r.get("afdc_port_count_within_5km"))
    with pytest.raises(FeatureError, match=r"D2 violation.*neighbourhood_quality"):
        assert_primary_feature_set_is_clean([smuggled])
```

**The out-of-state ZIP guard, which is the correctness fix of this phase.**

```python
# tests/unit/test_panel.py
def test_a_zip_outside_the_registering_state_is_excluded_by_name() -> None:
    """Oregon's export carries 00907 (Puerto Rico) and 10010 (Manhattan). Joining
    those to a like-numbered ZCTA imported 3.5 million out-of-state households."""
    areas = table(["05401", "10010"])
    panel = build_state_panel(
        observations([("05401", 40), ("10010", 3)], SourceGeography.USPS_ZIP),
        {"zcta": areas},
        {"05401": frozenset({"50"}), "10010": frozenset({"36"})},
    )
    assert [row.geoid for row in panel.rows] == ["05401"]
    assert panel.ledger.excluded["zip_outside_the_registering_state"] == 3
    panel.ledger.assert_balanced()
```

**The plan-change trigger fires rather than degrading the definition of validation.**

```python
# tests/unit/test_demand_validation.py
def test_three_or_fewer_usable_states_triggers_a_plan_change_not_a_weaker_test() -> None:
    panels = {state: panel(state) for state in STATES[:3]}
    with pytest.raises(ValidationError, match="formal plan change"):
        run_loso(panels, totals_for(panels), estimators=[ConstantRateBaseline()])
```

**The reconciled mode never reaches for the held-out state's own observed sum.**

```python
# tests/unit/test_demand_validation.py
def test_reconciling_needs_a_published_total_and_never_the_held_out_sum() -> None:
    held = panel("VT")
    with pytest.raises(ValidationError, match="refusing to reconcile"):
        score_state(PoissonRate(), list(panel("CO").rows), held,
                    STATE_TOTAL_RECONCILED)
```

**The two baselines are genuinely two baselines.**

```python
# tests/unit/test_demand_and_reconcile.py
def test_the_two_baselines_are_genuinely_different_models() -> None:
    """A per-person rate converted to a per-household rate collapses to the household
    baseline, and the two reported identical error for every state until this was fixed."""
    sample = rows()
    household = fit(ConstantRateBaseline(), sample).predict_counts(sample)
    population = fit(PopulationShareBaseline(), sample).predict_counts(sample)
    assert not np.allclose(household, population)
```

**The measured ladder is checked against the specification's prediction, not sorted to
match it.**

```python
# tests/unit/test_transformation_ladder.py
def test_a_ladder_that_violates_the_ordering_raises_with_the_numbers() -> None:
    """CLAUDE.md calls the ordering 'subject to empirical validation', so a violation
    is a finding to report, not something to fix by re-sorting."""
    rungs = [
        LadderRung("zip_anchored", HOUSEHOLD_SHARE, 1, 1.0, 0.35, 0.0),
        LadderRung("county_anchored", HOUSEHOLD_SHARE, 1, 1.0, 0.24, 0.0),
    ]
    with pytest.raises(AssertionError, match=r"zip_anchored=0\.3500"):
        assert_ladder_ordering(rungs)
```

---

## 6. Regression against prior phases (Gate part G-C)

Every prior gate suite is re-run as step 4 of `make gate PHASE=3`, before this phase's own
checks.

| Prior phase | Gate suite | Tests | Result |
|---|---|---:|---|
| 0 | `tests/regression/test_source_findings.py` | 23 | **PASS** |
| 1 | `tests/regression/test_domain_rules.py` (G1–G14, corrected G9) | 39 | **PASS** |
| 1 | `tests/integration/test_smoke_forward.py` | 11 | **PASS** |
| 2 | `tests/regression/test_phase2_gates.py` (P2-A to P2-I) | 37 | **PASS** |
| 2 | `tests/integration/test_smoke_forward_phase2.py` | 5 | **PASS** |
| 0–2 | Offline probe determinism (`make determinism`) | byte-identical | **PASS** |
| 1–2 | Semantic determinism (`make determinism-1`) | 7 | **PASS** |
| 1–2 | One-command rebuild (`make build-fixture`) | 16 models | **PASS** |

**No prior gate broke.** Phase 3 adds source modules and model modules; it changes no
staging or intermediate SQL, no canonical schema, and no Phase 2 supply or access output.
The only shared file it touched is `pipeline/spatial/crosswalk.py`, to which it *added*
`zcta_state_index` without altering any existing function.

---

## 7. Forward viability (Gate part G-D)

### 7.1 Output contract table

| Artifact | Schema | Grain | Guaranteed invariants | Consumed by |
|---|---|---|---|---|
| National tract demand surface | `TractEstimate` (§2.4) | census tract, 84,400 rows | Every row carries a non-negative estimate, an uncertainty score in [0,1], all five components, a tier in {A,B,C}, an evidence grain and an estimate method. Estimates sum exactly to their constraint group's published total (max residual 2.33e-10). No row is `zip_anchored`. No modelled row is `directly_observed` | Phase 4 (siting), Phase 5 (validation), Phase 6 (frontend) |
| `docs/evidence/P3-2_demand_model.json` | JSON | mixed | Every observed source and every panel join publishes a balanced ledger. The selection rule and its result are recorded together | Phase 5, the report, external review |
| `AllocationPenalty` | dataclass | by evidence grain | Values are measured, never chosen; the ordering `native ≤ zip ≤ county ≤ state` is asserted | Phase 4 candidate scoring, Phase 5 |
| `run_loso` / `LosoResult` | dataclass | per state per estimator per mode | Washington is never inside the independent aggregate; a state with no published total is recorded, not silently reconciled | Phase 5 |

### 7.2 Smoke-forward test

`tests/integration/test_smoke_forward_phase3.py` exercises Phase 4's core operation —
score, sort, select under a budget, report coverage — against a **real Phase 3 demand
surface** built from cached inputs for the Vermont + Washington two-state fixture (1,977
tracts).

```python
def to_candidate(row: TractEstimate) -> Candidate:
    """Phase 4 reads exactly these fields. A missing one would fail here, not there."""
    return Candidate(
        geoid=row.geoid, demand=row.estimate, uncertainty=row.uncertainty_score,
        tier=row.confidence_tier, evidence_grain=row.evidence_grain, cost=1.0)


def greedy_under_budget(candidates: list[Candidate], budget: float) -> list[Candidate]:
    chosen: list[Candidate] = []
    spent = 0.0
    for candidate in sorted(candidates, key=lambda c: (-c.demand, c.geoid)):
        if spent + candidate.cost > budget:
            continue
        chosen.append(candidate)
        spent += candidate.cost
    return chosen
```

**Result:** 5 tests pass. 1,977 candidates constructed with no missing field; a
budget-250 selection returns exactly 250 candidates costing ≤ 250; the selection is
order-independent (ties break on GEOID, not dictionary order); the top-500 selection
covers a materially larger share of demand than 500/1977; and the surface's
reconciliation residual is below 1e-6 before Phase 4 touches it.

**What this proves:** every field Phase 4's ranking and budget logic needs is present,
typed and populated on real output; confidence context survives into a selection, so a
ranked portfolio cannot silently lose its uncertainty (D7); and the join, reconciliation
and tier assignment hold on real data at two grains including the tract-native state.

**What this does not prove:** that any selected tract is a good place to build. No
validation in this project demonstrates that, and none is claimed. It also does not
exercise cost modelling, spatial candidate filtering, H3 aggregation or the ε-constraint
frontier, all of which are Phase 4's own work.

### 7.3 Assumption ledger additions

| ID | Assumption | Depends on | Tested in | Status |
|---|---|---|---|---|
| A-3.1 | New Jersey's observed BEV total is materially incomplete rather than definitionally different from the AFDC series | −21.65% at the same vintage; one distinct registration date against 36 and 138 for comparable states | Phase 5 | OPEN |
| A-3.2 | The Washington-measured transformation ladder generalises, so a `c4` derived there is a fair national penalty | Washington is the only state with ZIP, county and tract on one row | Phase 5 | OPEN |
| A-3.3 | Fitting at each state's observed geography and predicting at tract grain introduces no material aggregation bias | Share features aggregate as population-weighted means, but the relationship need not be scale-invariant | Phase 5 | OPEN |
| A-3.4 | AFDC totals rounded to the nearest 100 are precise enough as exact constraints | ±50 vehicles per state, ~±2,550 nationally against 5,755,687 | Phase 4 | OPEN |
| A-3.5 | Population density is an adequate stand-in for an urban/rural classification | No keyless tract-level Census classification retrieved | Phase 4 | OPEN |
| A-3.6 | ZIP-grain data are better used as training and validation evidence than as reconciliation constraints | The ladder is evidence *against* this: 0.1621 vs 0.3049 | Phase 4, or a reviewer decision | OPEN |

### 7.4 Prior assumptions re-checked

| ID | Assumption | Status this phase | Evidence |
|---|---|---|---|
| A-0.7 | ZIP counts can be reallocated to tracts with acceptable error | **Not exercised as stated, deliberately.** No ZIP count is allocated onto a tract; the error was still measured and feeds `c4` | §9.5 |
| A-0.12 | Enough usable sub-state states for LOSO to have power | **CONFIRMED.** 14 independent states against a 3-state trigger | `test_three_or_fewer_usable_states_triggers_a_plan_change_not_a_weaker_test` |
| A-0.18 | A public ZIP-to-tract crosswalk exists whose error can be measured | **CONFIRMED.** HUD 2026 Q2, measured at three grains | `P3-1`, `P3-2` |
| A-1.1 | Land-area weighting is an acceptable interim basis | **FALSIFIED as preferred, retained as documented fallback.** 0.2100 against HUD's 0.1621 | §9.5 |
| A-0.4 | NREL home-charging shares cannot be a present-day calibration target | **Remains CONFIRMED and unused.** Absent from the feature set | `assert_primary_feature_set_is_clean` |
| A-2.1 to A-2.5 | Phase 2 supply and access assumptions | **UNTESTED.** Phase 3 consumes no Phase 2 supply output outside the ablation | Phase 4 |
| A-1.3, A-0.19 | A rule-based copy lint catches the claims that matter | **HOLDS.** 140 files, 15 rules, clean | copy lint |
| A-0.21 | Excluding volatile metadata still detects genuine change | **HOLDS** | `tests/integration/test_determinism.py` |

---

## 8. Impact log delta (Cross-phase protocol)

### 8.1 Opened this phase

| ID | Severity | Affected phase | Assumed | Actually true | Response |
|---|---|---|---|---|---|
| **I-11** | **S1 had it shipped** — caught before publication | 3 only | A ZIP in a state's DMV export belongs to that state | State exports carry **out-of-state mailing ZIPs**. Oregon has 310, holding 1,253 vehicles, whose like-numbered ZCTAs contributed **3,541,636 households — 62% of Oregon's matched exposure**. Rank correlation went negative: Oregon −0.177, Vermont −0.365 | ZCTA-to-state index; such ZIPs excluded **by name** with vehicles counted in the ledger. Aggregate LOSO WAPE **0.72 → 0.33** |
| **I-12** | S2 | 3 only | A within-group mean TVD measures distance from observed evidence and is comparable across grains | It is not. Group membership was also being derived from the observed records, handing each method the answer. Measured that way the ladder read county 0.2367 *better than* ZIP 0.3461, which would have been published as falsifying CLAUDE.md §7.4 | Membership from geography alone; metric changed to **statewide tract-level TVD**. Ordering now holds and is asserted |
| **I-13** | S3 | 3 only | The population-share baseline differed from the household-share baseline | `(Σcount/Σpop) × (Σpop/Σhh) = Σcount/Σhh`. The two reported identical WAPE to four decimals for every state | `exposure_kind` per estimator; the two now differ (0.7096 vs 0.7119) and a test asserts it |

**None of these invalidates an earlier phase.** I-11 is the only one that would have been
S1, and it was caught before any Phase 3 output was published; amendment A21 had already
forbidden Phase 2 from consuming registration allocations, so no earlier published number
passed through that path.

### 8.2 Resolved this phase

| ID | How resolved | Gates re-run | Reports amended |
|---|---|---|---|
| I-11 | ZCTA-to-state membership check | Phase 3 gate | None needed — no prior report was affected |
| I-12 | Statewide TVD metric, geography-derived membership | Phase 3 gate | None |
| I-13 | Per-estimator exposure kind | Phase 3 gate | None |
| **R-5** (open risk from the Live Integration Assurance Checkpoint: "HUD's 60/min rate limit makes a national ZIP sweep slow, ~9.5 hours serially") | **Closed.** The crosswalk API accepts a state abbreviation, so the twelve states needed cost twelve requests. Validated against the per-ZIP route: strict superset, 0.0 maximum difference in `res_ratio` on shared ZIPs, identical Washington scope | Phase 3 gate | Recorded here |
| **R-3** (open risk: "allocation error must feed the uncertainty score") | **Closed.** It does, as component `c4`, from a measurement rather than a chosen penalty | Phase 3 gate | Recorded here |

### 8.3 Still open

| ID | Severity | Why still open | Planned resolution |
|---|---|---|---|
| R-1 | S3 | `cejst_archive` not live-tested; its host has no DNS record | Phase 6 |
| R-2 | S3 | HIFLD transmission service reports 52,244 features against 94,216 in the seed GeoJSON | Phase 6 |
| R-4 | S2 | A-0.5 contemporaneity unresolved for the 2020 and 2021 rolling origins | Phase 5 |
| R-6 | S3 | Missing and invalid HUD tokens are indistinguishable (both 401) | Phase 6 |
| A-3.1 | — | New Jersey's registration gap | Phase 5 |

---

## 9. Results and numbers

### 9.1 Inputs retrieved

| Source | Grain | Scale |
|---|---|---|
| ACS 2023 5-year, 78 variables | census tract | **84,400 tracts** across 51 jurisdictions |
| ACS 2023 5-year, 78 variables | ZCTA | **33,772** |
| ACS 2023 5-year, 78 variables | county | **3,222** |
| Census 2023 gazetteer | tract / ZCTA / county land area | 3 files |
| Atlas EV Hub state DMV exports | vehicle-level | **27,154,302 source rows**, 3.4 GB, 14 states |
| Washington EV population | vehicle-level | **294,193 records** |
| AFDC state registrations | state | 51 jurisdictions × 10 vintages (2016–2025) |
| HUD USPS ZIP crosswalk, 2026 Q2 | ZIP → tract | 12 states, one request each |

**HUD state-query validation (closes open risk R-5).** The crosswalk API accepts a state
abbreviation, so the twelve states Phase 3 needs cost twelve requests rather than a
~34,000-ZIP sweep at 60 requests per minute (≈9.5 hours). Validated against the
known-good per-ZIP Washington cache: the state route is a strict superset (700 ZIPs
against 438), **every shared ZIP matches to 0.0 absolute difference in `res_ratio`**, no
tract is missing, and the Washington comparison scope is unchanged — the same six
zero-residential ZIPs and the same 404 ZIP 98504.

### 9.2 Observed registrations, with balanced ledgers

Every state's extraction accounts for every vehicle in the source. `retrieved` counts all
snapshots and drivetrains; `included` is the latest snapshot, BEV only, with a resolvable
geography.

| State | Grain | Snapshot | Retrieved | Included BEV | Areas |
|---|---|---|---:|---:|---:|
| CO | ZIP | 2026-03-07 | 7,194,896 | 154,541 | 803 |
| CT | ZIP | 2025-12-31 | 339,392 | 47,187 | 406 |
| ME | ZIP | 2026-01-01 | 235,842 | 11,597 | 478 |
| MN | ZIP | 2026-01-01 | 1,044,629 | 61,734 | 824 |
| NC | ZIP | 2024-06-01 | 250,247 | 66,226 | 845 |
| NJ | ZIP | 2025-12-31 | 1,610,605 | 164,538 | 621 |
| NM | ZIP | 2026-07-01 | 599,463 | 19,374 | 258 |
| NY | ZIP | 2026-03-10 | 12,974,618 | 205,774 | 2,076 |
| OR | ZIP | 2025-01-31 | 261,768 | 83,372 | 687 |
| TX | ZIP | 2026-03-01 | 10,794,509 | 392,437 | 1,768 |
| VT | ZIP | 2026-01-03 | 201,285 | 12,917 | 458 |
| MT | county | 2026-01-08 | 34,535 | 6,773 | 51 |
| TN | county | 2025-12-31 | 771,787 | 53,029 | 95 |
| VA | county | 2025-12-31 | 595,245 | 131,976 | 129 |
| WA | tract | current | 294,193 | 236,994 | 1,769 |

**Cross-check against an independent series.** Observed BEV against the AFDC registration
total at the vintage nearest each state's own snapshot:

| State | Observed | AFDC (nearest vintage) | Difference |
|---|---:|---:|---:|
| WA | 236,994 | 236,400 (2025) | +0.25% |
| TX | 392,437 | 387,400 (2025) | +1.30% |
| NY | 205,774 | 209,300 (2025) | −1.68% |
| MT | 6,773 | 6,900 (2025) | −1.84% |
| VA | 131,976 | 134,900 (2025) | −2.17% |
| ME | 11,597 | 11,900 (2025) | −2.55% |
| MN | 61,734 | 59,800 (2025) | +3.23% |
| CT | 47,187 | 48,800 (2025) | −3.31% |
| TN | 53,029 | 55,400 (2025) | −4.28% |
| CO | 154,541 | 162,800 (2025) | −5.07% |
| NC | 66,226 | 70,200 (2023) | −5.66% |
| OR | 83,372 | 78,400 (2024) | +6.34% |
| VT | 12,917 | 11,900 (2025) | +8.55% |
| NM | 19,374 | 16,600 (2025) | +16.71% |
| **NJ** | **164,538** | **210,000 (2025)** | **−21.65%** |

Thirteen of fifteen agree within 9%. New Mexico's +16.71% is explained by its snapshot
being eighteen months newer than the newest available AFDC vintage. **New Jersey is a
genuine anomaly** and is flagged for review, not marked low-confidence — see §10.1.

### 9.3 The panel join

| State | Areas joined | BEV joined | Excluded: out-of-state ZIP | Excluded: no like-numbered ZCTA | Excluded: no households | Excluded: no ACS area |
|---|---:|---:|---:|---:|---:|---:|
| CO | 456 | 153,840 | 468 | 68 | 165 | — |
| CT | 278 | 45,745 | 1,316 | 110 | 16 | — |
| ME | 355 | 11,277 | 127 | 171 | 22 | — |
| MN | 689 | 61,211 | 405 | 22 | 96 | — |
| NC | 693 | 59,032 | 5,040 | 2,101 | 53 | — |
| NJ | 569 | 164,397 | — | 120 | 21 | — |
| NM | 246 | 19,246 | — | 108 | 20 | — |
| NY | 1,614 | 197,934 | 6,922 | 266 | 214 | 438 |
| OR | 359 | 82,070 | 1,253 | 40 | 9 | — |
| TX | 1,593 | 374,464 | 1 | 15,405 | 2,567 | — |
| VT | 251 | 12,528 | 225 | 124 | 40 | — |
| MT | 51 | 6,773 | — | — | — | — |
| TN | 95 | 53,029 | — | — | — | — |
| VA | 129 | 131,976 | — | — | — | — |
| WA | 1,767 | 236,985 | — | — | 9 | — |

### 9.4 Demand model validation — leave-one-state-out

**This is demand model validation in the D3 sense**: whether tract-level EV estimates are
accurate. It is not historical deployment alignment and it is not cross-objective
robustness.

Definitions, written out: **WAPE** = `Σ|predicted − observed| / Σ|observed|`, reported
instead of MAPE because MAPE explodes on the small counts that dominate a ZIP panel.
**MAE** = `mean(|predicted − observed|)`. **R²** = `1 − Σ(observed − predicted)² /
Σ(observed − mean(observed))²`.

Aggregate EV-weighted WAPE across the fourteen independent states:

| Candidate | Unreconciled | State-total-reconciled |
|---|---:|---:|
| **`poisson_glm`** | **0.3835** | **0.3312** |
| `boosted_poisson` | 0.4004 | 0.3320 |
| `ridge_log_rate` | 0.4244 | 0.3789 |
| `baseline_population_share` | 0.7624 | 0.7096 |
| `baseline_household_share` | 0.7657 | 0.7119 |

**The two reconciliation modes and why both are reported.** `unreconciled` is the raw
propensity surface, which has to guess a held-out state's overall EV penetration from
demographics alone — not what the deployed system asks of it.
`state_total_reconciled` scales the held-out state's predictions to the AFDC total at the
vintage nearest its own snapshot. **This is not leakage**: AFDC publishes a state total
for all 51 jurisdictions independently of any sub-state source, so the constraint is
available for a state with no sub-state data at all. No sub-state observation of the
held-out state is used in either mode.

Per state, `poisson_glm`, state-total-reconciled:

| State | Native grain | Areas | Observed BEV | WAPE | MAE | R² | Constraint vintage | Independent |
|---|---|---:|---:|---:|---:|---:|---|---|
| VA | county | 129 | 131,976 | **0.167** | 170.8 | 0.971 | 2025 | yes |
| CT | ZIP | 278 | 45,745 | 0.212 | 34.9 | 0.900 | 2025 | yes |
| OR | ZIP | 359 | 82,070 | 0.222 | 50.7 | 0.926 | 2024 | yes |
| CO | ZIP | 456 | 153,840 | 0.258 | 87.1 | 0.872 | 2025 | yes |
| TN | county | 95 | 53,029 | 0.264 | 147.5 | 0.934 | 2025 | yes |
| MN | ZIP | 689 | 61,211 | 0.274 | 24.3 | 0.907 | 2025 | yes |
| VT | ZIP | 251 | 12,528 | 0.312 | 15.6 | 0.876 | 2025 | yes |
| NM | ZIP | 246 | 19,246 | 0.313 | 24.5 | 0.901 | 2025 | yes |
| NC | ZIP | 693 | 59,032 | 0.342 | 29.1 | 0.853 | 2023 | yes |
| ME | ZIP | 355 | 11,277 | 0.353 | 11.2 | 0.875 | 2025 | yes |
| TX | ZIP | 1,593 | 374,464 | 0.365 | 85.7 | 0.795 | 2025 | yes |
| NJ | ZIP | 569 | 164,397 | 0.431 | 124.5 | 0.622 | 2025 | yes |
| NY | ZIP | 1,614 | 197,934 | 0.451 | 55.3 | 0.353 | 2025 | yes |
| MT | county | 51 | 6,773 | 0.545 | 72.4 | 0.582 | 2025 | yes |
| **WA** | **tract** | 1,767 | 236,985 | 0.381 | 51.1 | 0.501 | 2025 | **NO — preprocessing-method-selection state** |

R² is above 0.85 for ten of the fourteen independent states (0.853 to 0.971). New York (0.353) and
Montana (0.582) are the weakest; Montana has only 51 counties, so a single county's error
moves the statistic a long way.

### 9.5 The measured transformation ladder

| Grain | Method | Groups | EVs placed | Unplaced | Statewide tract TVD |
|---|---|---:|---:|---:|---:|
| `native_tract` | identity | 1,784 | 294,193 | 0 | **0.0000** |
| `zip_anchored` | HUD `res_ratio` | 438 | 292,593 | 606 | **0.1621** |
| `zip_anchored` | household share | 438 | 292,826 | 606 | 0.2100 |
| `county_anchored` | household share | 39 | 293,432 | 0 | **0.2367** |
| `state_total_only` | household share | 1 | 293,432 | 0 | **0.3049** |

The ordering CLAUDE.md §7.4 component 5 predicts **holds**, and `assert_ladder_ordering`
checks it rather than assuming it.

### 9.6 The national surface

| Quantity | Value |
|---|---:|
| Tracts | **84,400** |
| Estimator | `poisson_glm` |
| Training rows | 7,378 (14 independent states, at their own grains) |
| National BEV estimate | **5,755,687** |
| Reconciliation max residual | **2.33 × 10⁻¹⁰** |
| Unconstrained tracts | **0** |
| Mean uncertainty score | 0.2041 |
| B/C threshold | 0.2622 |

Evidence grain: `native_tract` 1,769 · `county_anchored` 4,204 · `state_total_only`
78,427. Confidence tier: **A (sub-state anchored) 5,973 · B (modeled) 58,820 · C (low
confidence) 19,607.**

Weight sensitivity — change in the mean score when each component's weight is raised by
0.1 and the set renormalised:

| Component | Δ mean score |
|---|---:|
| `out_of_distribution` | +0.0269 |
| `allocation_error` | +0.0083 |
| `reconciliation_movement` | −0.0043 |
| `prediction_interval` | −0.0123 |
| `source_degradation` | −0.0186 |

### 9.7 Uncertainty calibration — a mixed result, published as such

Washington-only, and therefore **diagnostic rather than validation**: it is the
non-independent state, and it is the only place a tract-level error can be computed at
all. Mean absolute error by uncertainty quintile:

| Bin | n | Mean uncertainty | Mean absolute error |
|---:|---:|---:|---:|
| 0 | 354 | 0.0757 | 54.04 |
| 1 | 354 | 0.1106 | 57.69 |
| 2 | 354 | 0.1443 | 50.96 |
| 3 | 354 | 0.1800 | 50.72 |
| 4 | 353 | 0.2274 | **74.92** |

**The curve is not monotonic.** The top quintile is clearly worse than every other, which
is the behaviour the score is supposed to have; the middle three are flat and slightly
below the first. The pre-registration forbids retuning the weights in response, and they
have not been retuned.

> ~~A well-calibrated uncertainty score is a publishable result; so is a
> partly-calibrated one, and this is the latter.~~  <!-- copy-lint: allow -->
>
> **Corrected 2026-08-29 on external review (see §14.7).** That sentence read as a
> calibration claim and it is withdrawn. Higher uncertainty identifies the highest-error
> quintile, but error is not monotonic across the remaining bins. The current uncertainty
> score is therefore **not empirically calibrated**; this diagnostic only provides limited
> evidence that the score identifies some high-error observations.

### 9.8 The supply-feature ablation

**This is the only place Phase 2 supply outputs enter a model, and it is not part of the
published surface.** Scope: the eleven ZIP-grain states, where AFDC station ZIPs join
directly. Features added: `dcfc_ports_per_1k_households`, `l2_ports_per_1k_households`,
`public_stations_per_1k_households`, built from public **and** operational supply only
(status code `E`, access code `public`), with charging level read from the source's own
field.

| Measure | Without supply features | With supply features |
|---|---:|---:|
| In-sample WAPE (`poisson_glm`) | 0.366382 | 0.366342 |
| **LOSO WAPE (`poisson_glm`)** | **0.3517** | **0.4232** |
| LOSO WAPE (`ridge_log_rate`) | 0.4056 | 0.4008 |

**Supply features degrade out-of-state transfer by 20% and do not improve in-sample fit.**
This vindicates D2's prohibition on transfer grounds, and it is worth being precise about
what it does *not* show: CLAUDE.md §18 anti-pattern 5 warns that supply features "will
improve fit", and **that premise was not reproduced here** — in-sample WAPE moved by
0.004 percentage points, which is nothing. With these three features, at this grain, they
buy no fit and cost real transfer. The prohibition stands, and the reason it stands is
now measured rather than asserted.

---

## 10. Limitations introduced or discovered

| Limitation | Cause | Effect on downstream results | Mitigated? |
|---|---|---|---|
| The independent aggregate contains **no tract-native state** | Washington selected the crosswalk, so it is excluded from the independent aggregate | Every independent validation figure is scored at ZIP or county grain. Tract-level accuracy is not directly validated by an independent state | No. Accepted explicitly in the pre-registration; the cost is stated, not avoided |
| Uncertainty calibration is Washington-only | It is the only state with observed tract counts | The calibration check rests on one state, which is also the non-independent one | No. Reported as diagnostic |
| `c4` is extrapolated nationally from one state | Washington is the only state with ZIP, county and tract on the same row | Every published `c4` is a Washington-derived number applied elsewhere | Partly: the value is measured rather than chosen, and its provenance travels with it |
| AFDC state totals are rounded to the nearest 100 | Publisher behaviour | Every reconciled estimate inherits a constraint precise to about ±50 vehicles per state | Documented |
| Sub-state snapshots span 2024-06 to 2026-07 | Publisher behaviour, state by state | States are not contemporaneous with one another | Partly: each state is reconciled to the AFDC vintage nearest its own snapshot |
| Texas loses 15,405 BEV (3.9%) to ZIPs with no like-numbered ZCTA | Point and PO-Box ZIPs have no areal equivalent | Texas's panel is 96.1% of its observed BEV | Recorded in the ledger, by name |
| ZIP totals are not used as constraints | Scope decision | Tracts in the eleven ZIP-grain states rest on a state total, not on the finer evidence that exists | Recorded in `FUTURE_WORK.md`; the ladder measurement suggests it would help |
| Urban/rural is represented by population density only | No keyless tract-level Census urban/rural classification was retrieved | The urban/rural feature CLAUDE.md §7.3 names is present as a continuous proxy rather than a classification | Documented here and in `LIMITATIONS.md` |

---

### 10.1 New Jersey: an anomaly flagged for review

Corrected domain rule **G9** requires that an anomalous state be *flagged for review*
rather than automatically marked low-confidence, and that a low-confidence designation
require corroborating evidence of a vintage, coverage, definition or source-quality
problem.

**What is anomalous.** New Jersey's observed BEV total is 164,538 against the AFDC 2025
figure of 210,000 — **−21.65% at the same vintage**, where thirteen of the other fourteen
states agree within 9%.

**Corroborating evidence, such as it is.** New Jersey's latest snapshot carries **one
distinct registration date**, against 36 for Connecticut and 138 for New York. That is
consistent with a partial or differently-constructed export, but it is not proof.

**What has been done.** Nothing has been marked low-confidence. New Jersey remains a full
independent validation state, and its LOSO result (WAPE 0.431, R² 0.622) is among the
weaker ones, which is itself consistent with the anomaly. It is recorded as an open
assumption for a later phase to resolve.

---

## 11. Specification compliance

### 11.1 Prime directives

| Directive | How compliance is enforced | Verified by |
|---|---|---|
| **D1** No temporal leakage | Not exercised this phase; Phase 3 fits a current-vintage cross-section, not a backtest. The vintage guard is Phase 5's deliverable. Phase 3 *does* align each state's constraint to the vintage nearest its own observation | `test_the_nearest_vintage_is_chosen_rather_than_the_newest` |
| **D2** No supply-to-demand loop | Structural: every feature is executed against a recording row and its inputs must be a subset of declared ACS variables plus land area. Supply features exist only in a separately reported ablation | `test_p3_c_the_primary_feature_set_contains_no_supply_derived_feature`, `test_a_feature_reaching_outside_the_declared_variables_is_rejected` |
| **D3** Three validation terms | The LOSO harness names itself "demand model validation" in its own output; the copy lint enforces the vocabulary across 138 files | copy lint, `test_loso_scores_every_state_in_both_modes_and_selects_one_estimator` |
| **D4** Zero recurring cost | Every source used is free-tier; the Phase 3 rebuild reads only cached responses and needs no credentials | `make phase3` runs offline |
| **D5** Greenfield | No prior version exists to match | — |
| **D6** Grid proximity language | Not exercised; Phase 3 touches no grid data | copy lint |
| **D7** Uncertainty first-class | Every tract carries a continuous score with five components, a tier, and a weight-sensitivity report; the weights are labelled not calibrated everywhere | `test_p3_e_the_weights_are_never_presented_as_calibrated`, `test_every_estimate_carries_its_uncertainty_and_tier` |
| **D8** Explicit degradation | Every observed source and every panel join publishes a balanced ledger; a missing gazetteer raises rather than defaulting; zero-residential ZIPs are never renormalised | `test_p3_g_*`, `test_a_missing_gazetteer_raises_rather_than_defaulting_the_area` |

### 11.2 Deviations from specification

| Spec section | What the spec says | What was done | Why |
|---|---|---|---|
| §7.4.1 | Lists `zip_anchored` as an `evidence_grain` value | The published surface contains no `zip_anchored` tract | Phase 3 allocates no ZIP count onto a tract, so no tract value is anchored to a ZIP total. Using the label would claim evidence the number does not rest on. The enum value remains in the codebase and is used by the observation layer |
| §7.3 | "Tract estimates must reconcile exactly to reliable county totals where they exist and to state totals everywhere else" | Implemented exactly as written | No deviation |
| §10.1 | "Leave-one-state-out across every sub-state anchored state that remains genuinely usable" | 14 of 15 states; Washington excluded from the independent aggregate | The pre-registration, approved before fitting, reclassified Washington as method-selection data |

No deviation required a plan change. The three-or-fewer-usable-states trigger did not
fire: fourteen independent states remain, and the harness raises if that count ever falls
to three or fewer (`test_three_or_fewer_usable_states_triggers_a_plan_change_not_a_weaker_test`).

---

## 12. Open questions for the reviewer

1. **Should ZIP totals become reconciliation constraints?** The measured ladder says
   ZIP-anchored allocation places EV mass substantially better than a state total alone
   (statewide tract TVD 0.1621 against 0.3049). Phase 3 declined on scope grounds and
   recorded it as future work. If the reviewer judges the evidence sufficient, this would
   change the published surface for eleven states and would make `zip_anchored` a real
   evidence grain.

2. **Is the Washington exclusion the right trade?** It removes the only tract-native state
   from the independent aggregate, so no independent figure validates tract-grain accuracy
   directly. The alternative — readmitting a state whose result is tuning-influenced — was
   judged worse, but the cost is real.

3. **Is New Jersey's −21.65% gap sufficient to mark it low-confidence?** Corrected G9 says
   a statistical anomaly alone is not enough. The one-distinct-registration-date finding is
   suggestive but not conclusive.

4. **Is a Washington-only calibration curve worth publishing?** It is the only tract-level
   error measurable anywhere, and it is non-monotonic. The alternative is to publish no
   calibration evidence at all.

---

## 13. Next phase readiness

| Check | Status |
|---|---|
| All acceptance criteria passed | **20/20** (§4) |
| Coverage thresholds met | **100% line and branch on every tier**; 4,055 statements, 986 branches, zero missed (§5.2) |
| All prior gates passing | **yes** — Phase 0, 1 and 2 suites re-run, 115 tests, plus byte-identical probe determinism and an unchanged semantic hash `9c7f9506cf6ae832abb53e250fc26a446861f80875c53abba01ef2a87eb3a593` (§6) |
| Smoke-forward test for Phase 4 passing | **yes** — 5 tests over 1,977 real tracts (§7.2) |
| Report complete and self-contained | **yes** — every number quoted inline; no reference requires opening a file |
| No S1 impacts open | **yes** — I-11 would have been S1 and was caught before publication; I-12 and I-13 are S2 and S3, all three resolved (§8) |
| Lint | ruff and `mypy --strict` clean over 98 source files; D3 copy lint clean over 140 |

**Recommendation: PROCEED to Phase 4 (siting and frontier), subject to external review,
and subject to a decision on open question 1.**


## Corrections

None. This report has not been amended since submission.

---

# 14. External Review Corrections — ACS 2024 Production Refresh (2026-08-29)

**Nothing above this line has been rewritten.** Phase 3's history stands as submitted; one
sentence in §9.7 is struck in place with a pointer here, matching the precedent set for the
Live Integration Assurance Checkpoint's test counts. This section records a bounded
correction pass authorised by external review after Phase 3 passed methodologically.

Every number below reproduces with `python -m pipeline.model.run_phase3`, offline.

## 14.1 What external review asked for

1. Move the current production surface to **ACS 2024 5-year**, after verifying it, and
   **re-run the pre-registered estimator selection** rather than preserving the previous
   winner.
2. Correct Washington's role: **validation exclusion does not imply training exclusion**.
3. Record the reviewer's decision that **ZIP totals do not become Core reconciliation
   constraints** (closing A-3.6).
4. Keep **New Jersey review-flagged**, and add a bounded with/without sensitivity.
5. Remove any wording that reads as a **calibration claim**.
6. Preserve older ACS vintages so **Phase 5's D1 temporal integrity** survives.

## 14.2 ACS 2024 verification, before anything was changed

| Check | Result |
|---|---|
| Latest tract-level release | **ACS 2024 5-year**. ACS 2025 returns HTTP 404 |
| All consumed variables present | **78/78** in the 2024 dictionary (28,475 variables against 2023's 28,299) |
| Retrieval at tract / ZCTA / county | All HTTP 200, **identical column ordering** to 2023 |
| Area counts | **250** Rhode Island tracts, **33,772** ZCTAs, **3,222** counties — *identical* to 2023 at every grain |
| Group (table) changes | **none** |

**Two label changes, both examined, neither affecting a consumed universe:**

- **`B19013_001E`** moves from *2023* to *2024 inflation-adjusted dollars*, and 18
  income-table concepts change for the same reason. The model refits entirely within one
  vintage so it is internally consistent, but **the feature's units changed**: the fitted
  coefficient is not comparable across vintages, and a before/after comparison of that
  feature is not like-for-like. Recorded as assumption **A-3.8**.
- **`B08301_010E`** drops the "(excluding taxicab)" parenthetical, because line **016 was
  renamed "Taxicab" → "Taxi or ride-hailing services"** — a genuine universe expansion on
  line 016. **Phase 3 does not consume line 016.** The table still has 21 lines with the
  same hierarchy, and taxi remains a category *outside* the public-transportation subtree,
  so `public_transit_share = B08301_010E / B08301_001E` has the same universe in both
  vintages. Recorded as assumption **A-3.7**.

## 14.3 Before and after

| Quantity | ACS 2023 (as submitted) | ACS 2024 (corrected) | Delta |
|---|---:|---:|---:|
| **Feature vintage** | ACS 2023 5-year | **ACS 2024 5-year** | — |
| **Estimator selected** | `poisson_glm` | **`poisson_glm`** | unchanged |
| **Independent LOSO aggregate WAPE** (reconciled) | 0.331156 | **0.320309** | **−0.010847** |
| `boosted_poisson` | 0.331954 | 0.329409 | −0.002545 |
| `ridge_log_rate` | 0.378926 | 0.376324 | −0.002602 |
| `baseline_population_share` | 0.709645 | 0.705842 | −0.003803 |
| `baseline_household_share` | 0.711871 | 0.708315 | −0.003556 |
| **Unreconciled aggregate WAPE** (`poisson_glm`) | 0.383513 | 0.380904 | −0.002609 |
| `boosted_poisson` unreconciled | 0.400355 | 0.416467 | +0.016112 |
| `ridge_log_rate` unreconciled | 0.424436 | 0.433045 | +0.008609 |
| baselines unreconciled | 0.762355 / 0.765664 | 0.800568 / 0.802679 | +0.038 / +0.037 |
| **Tracts** | 84,400 | **84,401** | +1 |
| **National BEV estimate** | 5,755,687 | **5,755,689** | +2 |
| **Reconciliation max residual** | 2.33e-10 | **2.33e-10** | unchanged |
| **Unconstrained tracts** | 0 | **0** | unchanged |
| **Mean uncertainty** | 0.204082 | **0.202687** | −0.001395 |
| **B/C threshold** | 0.262238 | **0.260170** | −0.002068 |
| **Evidence grain** | 1,769 / 4,204 / 78,427 | **1,769 / 4,204 / 78,428** | +1 state-total-only |
| **Confidence tiers A/B/C** | 5,973 / 58,820 / 19,607 | **5,973 / 58,821 / 19,607** | +1 Tier B |
| **Training states** | 14 | **15** | +1 (Washington) |
| **Training rows** | 7,378 | **9,140** | +1,762 |
| **Independent validation states** | 14 | **14** | unchanged |

**Ablation, recomputed:**

| Measure | ACS 2023 | ACS 2024 |
|---|---|---|
| In-sample WAPE, without / with supply features | 0.366382 / 0.366342 | **0.360885 / 0.360072** |
| **LOSO WAPE `poisson_glm`, without / with** | 0.3517 / 0.4232 | **0.344865 / 0.416967** |
| LOSO WAPE `ridge_log_rate`, without / with | 0.4056 / 0.4008 | 0.398673 / 0.396359 |

The conclusion is unchanged and slightly sharper: supply features **degrade out-of-state
transfer by 7.2 percentage points** while moving in-sample fit by 0.08 — they buy no fit
and cost real transfer.

## 14.4 Decomposing the improvement — it is mostly ACS 2024, but not entirely

Two things changed at once, so attributing the whole gain to the vintage would be wrong.
All four combinations, same pre-registered rule throughout:

| ACS vintage | Washington in training | Training rows | `poisson_glm` | `boosted_poisson` | Selected |
|---|---|---:|---:|---:|---|
| 2023 | no | 7,378 | 0.331156 | 0.331954 | `poisson_glm` |
| 2023 | **yes** | 9,145 | 0.328251 | **0.324946** | `poisson_glm` |
| **2024** | no | 7,373 | 0.321982 | 0.328466 | `poisson_glm` |
| **2024** | **yes** | 9,140 | **0.320310** | 0.328979 | `poisson_glm` |

- **ACS 2024 alone** accounts for **−0.009174** of the −0.010847 total (about 85%).
- **Washington in training alone** accounts for **−0.002905**.
- They are not additive (−0.012079 against an observed −0.010847): mild interaction,
  expected when both add information about the same relationship.

**One row deserves attention.** In the `2023 + Washington trains` configuration,
`boosted_poisson` (0.324946) is *numerically better* than `poisson_glm` (0.328251). The
gap is 0.0033, inside the pre-registered 1-percentage-point band, so the tie-break selects
the simpler model. **The selection is stable across all four configurations, but in one of
them only the tie-break preserves it.** That is the rule doing exactly what it was written
to do, and it is reported rather than glossed.

## 14.5 Washington: training evidence yes, independent validation evidence no

| | |
|---|---|
| **Training / development evidence** | **YES** — Washington is in every other state's LOSO training fold and in the final production fit |
| **Independent validation evidence** | **NO** — excluded from the headline aggregate, status `non_independent_preprocessing_selection_state`, its own LOSO row is diagnostic only |

`independent_validation_states` (14): CO, CT, ME, MN, MT, NC, NJ, NM, NY, OR, TN, TX, VA, VT
`training_states` (15): the same fourteen **plus WA**

**What was actually wrong.** The pre-registration's rules W1–W4 speak, in every clause, to
*validation records*, *the headline aggregate*, and *figures quoting a Washington LOSO
metric*. They never barred Washington from training. The **implementation** conflated the
two by reusing a single `is_independent` flag for both training-set construction and
aggregate membership. That was an over-restriction introduced by code, not a requirement of
the pre-registration.

**Why the distinction holds.** Washington's tuning influence is specific — it selected the
HUD ZIP→tract crosswalk — so a Washington *result* cannot be quoted as independent evidence
about a model whose preprocessing Washington chose. That reasoning does not reach an Oregon
or Texas holdout, whose own observations played no part in the crosswalk decision. Washington
is also the only tract-native registration source in the country, so discarding it as
training evidence threw away the most granular observations available for no methodological
gain.

Recorded as **amendment W5–W8** appended to `docs/evidence/P3-0_phase3_preregistration.md`,
authorised by external review, with the original pre-registration preserved unedited above
it. Two separate fields now exist (`is_independent`, `is_trainable`), both are published,
and a regression test asserts Washington is in **exactly one** of the two lists.

## 14.6 New Jersey sensitivity — material, and it did not drive anything

New Jersey remains **`flagged_for_review`**, not marked low-confidence, per corrected
domain rule G9: a statistical anomaly alone is not corroborating evidence of a vintage,
coverage, definition or source-quality failure.

| Aggregate (`poisson_glm`, state-total-reconciled) | States | Observed BEV | Weighted WAPE |
|---|---:|---:|---:|
| **With New Jersey** (the headline) | 14 | 1,373,621 | **0.320309** |
| **Without New Jersey** | 13 | 1,209,207 | **0.303913** |
| **Delta** | | | **−0.016396** |

**This is material and is stated as such:** excluding New Jersey improves the headline
aggregate by **1.64 percentage points**, which is larger than the entire ACS 2023 → 2024
gain. New Jersey is the second-worst independent state (WAPE 0.441, R² 0.618) and carries
12% of the aggregate's EV weight.

**It did not drive model selection, and structurally could not have.** The sensitivity is
derived from scores that had *already been computed and already been used to select the
estimator* — there is no refit and no re-ranking, and the estimator is an input to the
calculation rather than an output of it. New Jersey remains in the headline aggregate, in
the training set, and in the panel. Confidence tiers are untouched. Assumption **A-3.1**
stays open for Phase 5.

## 14.7 Uncertainty: a diagnostic, not a calibration result

The sentence in §9.7 reading *"A well-calibrated uncertainty score is a publishable
result; so is a partly-calibrated one, and this is the latter"* is **withdrawn**.  <!-- copy-lint: allow -->
It read as a calibration claim and the evidence does not support one.

**Approved interpretation, now used everywhere:**

> Higher uncertainty identifies the highest-error quintile, but error is not monotonic
> across the remaining bins. The current uncertainty score is therefore **not empirically
> calibrated**; this diagnostic only provides limited evidence that the score identifies
> some high-error observations.

The artifact key is renamed `washington_uncertainty_error_diagnostic` and carries
`is_empirical_calibration: false`. Recomputed on ACS 2024, Washington only, diagnostic:

| Bin | n | Mean uncertainty | Mean absolute error |
|---:|---:|---:|---:|
| 0 | 354 | 0.0604 | 50.95 |
| 1 | 354 | 0.0921 | 46.81 |
| 2 | 354 | 0.1240 | 50.46 |
| 3 | 354 | 0.1625 | 42.43 |
| 4 | 353 | 0.2122 | **73.17** |

**Weights were not retuned.** The equal declared weights stand, the five components stand,
the weight-sensitivity report stands, and the limitation that component `c4` is
extrapolated from Washington stands. A regression test scans every document and fails on a
calibration overclaim.

## 14.8 ZIP totals stay out of Core v1 — reviewer decision, A-3.6 closed

> ZIP-grain observations remain valuable training and native-grain validation evidence, but
> they will not become hard tract-level reconciliation constraints in Core v1. The
> Washington transformation ladder demonstrates potential value, but one-state evidence is
> insufficient to justify changing the national reconciliation model and evidence-grain
> semantics at this stage.

No ZIP-level IPF constraints; no `zip_anchored` values in the production surface; county
totals where reliable and state totals everywhere else. The experiment stays in
`docs/FUTURE_WORK.md`. **This is settled and no longer blocks Phase 4.** Open question 1 in
§12 is answered and withdrawn.

## 14.9 ACS vintage handling preserves Phase 5's temporal integrity

| | |
|---|---|
| **Current production feature vintage** | ACS 2024 5-year |
| **Historical validation feature vintages** | cutoff-appropriate ACS releases; ACS 2023 5-year is retained |

Directive **D1** requires `feature_vintage <= prediction_cutoff`. The ACS 2024 refresh
applies to the production cross-section **only**; Phase 5's rolling origins must continue
to use the release contemporaneous with each cutoff.

Older vintages are not overwritten, and that is structural rather than a convention: the
cache key hashes the request URL, which carries the year, so each vintage occupies its own
entry under the same source id. Both replay offline today, and two regression tests prove
it — one that the older vintage still loads, and one that the two vintages return
*genuinely different values*, so a cache silently serving one vintage for both could not
pass vacuously.

**A defect in this area was found and fixed during the correction pass.**
`AcsSource` binds `ACS_YEAR` as a **default argument, evaluated once at definition time**,
so monkeypatching `census_acs.ACS_YEAR` does not change which vintage loads — it silently
returns the production vintage. My first attempt at the §14.4 decomposition did exactly
that and produced four rows in which the 2023 and 2024 results were *byte-identical*, which
is what exposed it. `load_area_tables` now takes an explicit `year` parameter. Left
unfixed, this would have handed Phase 5 a D1 violation that looked like a passing test.
Recorded as impact **I-14**.

## 14.10 Per-state results, recomputed on ACS 2024

`poisson_glm`, state-total-reconciled:

| State | Native grain | Areas | Observed BEV | WAPE | MAE | R² | Constraint vintage | Independent |
|---|---|---:|---:|---:|---:|---:|---|---|
| VA | county | 129 | 131,976 | **0.153** | 156.1 | 0.979 | 2025 | yes |
| OR | ZIP | 358 | 82,069 | 0.221 | 50.7 | 0.935 | 2024 | yes |
| CT | ZIP | 278 | 45,750 | 0.223 | 36.7 | 0.887 | 2025 | yes |
| CO | ZIP | 455 | 153,852 | 0.261 | 88.3 | 0.873 | 2025 | yes |
| MN | ZIP | 690 | 61,279 | 0.273 | 24.2 | 0.915 | 2025 | yes |
| TN | county | 95 | 53,029 | 0.274 | 152.9 | 0.936 | 2025 | yes |
| NM | ZIP | 245 | 19,245 | 0.316 | 24.9 | 0.899 | 2025 | yes |
| VT | ZIP | 250 | 12,526 | 0.324 | 16.2 | 0.863 | 2025 | yes |
| TX | ZIP | 1,589 | 374,452 | 0.342 | 80.6 | 0.814 | 2025 | yes |
| NC | ZIP | 693 | 59,032 | 0.342 | 29.2 | 0.861 | 2023 | yes |
| ME | ZIP | 356 | 11,284 | 0.357 | 11.3 | 0.863 | 2025 | yes |
| NY | ZIP | 1,614 | 197,940 | 0.411 | 50.5 | 0.538 | 2025 | yes |
| NJ | ZIP | 570 | 164,414 | 0.441 | 127.2 | 0.618 | 2025 | yes |
| MT | county | 51 | 6,773 | 0.535 | 71.0 | 0.609 | 2025 | yes |
| **WA** | **tract** | 1,767 | 236,985 | 0.384 | 51.5 | 0.505 | 2025 | **NO — training evidence only** |

R² is above 0.85 for eleven of the fourteen independent states, up from ten. New York
improves markedly (0.353 → 0.538); Montana remains the weakest at 51 counties.

The measured transformation ladder is essentially unchanged: `native_tract` 0.0000,
`zip_anchored` 0.162088, `county_anchored` 0.236679, `state_total_only` 0.304071. The
ordering CLAUDE.md §7.4 predicts still holds.

## 14.11 Gate evidence for the correction pass

`make gate PHASE=3`, run on the final tree:

| Step | Result |
|---|---|
| 1. lint | ruff clean; `mypy --strict` clean over **99** source files |
| 2. full test suite | **883 passed, 47 deselected** in 102.59s |
| 3. coverage | **100% line and branch on every tier**: 4,077 statements, 988 branches, **zero missed** |
| 4. prior gate suites (Phase 0, 1, 2) | pass; offline probe determinism byte-identical |
| 5. Phase 3 acceptance criteria P3-A to P3-H | **20 passed** |
| 6. D3 copy lint | clean over 141 files, 15 rules |
| 7. semantic determinism | pass |
| 8. one-command rebuild | canonical tables and every Phase 3 number rebuilt |
| **Verdict** | **PASS** |

Coverage by tier: `pipeline/model/` 1,619 statements / 364 branches; `pipeline/validation/`
542 / 152; `pipeline/spatial/` 299 / 78; `pipeline/discovery/` 677 / 198;
`pipeline/quality/` 287 / 64; `pipeline/schemas/` 52 / 2; `pipeline/sources/` 317 / 78;
`pipeline/transform/` 100 / 14. All 100%.

The suite grew from 861 to **883**: the nineteen checks in
`tests/regression/test_phase3_corrections.py` covering the fourteen the external review
named, plus three added while fixing what the pass uncovered.

**378 warnings appear and are benign.** They are a single sklearn-internal notice
(`sklearn.utils.parallel.delayed` used without `Parallel`, about thread-config
propagation) emitted by `HistGradientBoostingRegressor` inside the ablation's folds. It is
**not** a convergence warning and carries no information about model quality.

## 14.12 What this correction pass did not change

- **No threshold, metric or selection rule moved.** The 1-percentage-point tie-break, the
  0.75 B/C quantile, the equal uncertainty weights, the 0.35 maximum acceptable TVD and
  the three-or-fewer-usable-states plan-change trigger are all exactly as pre-registered.
- **No acceptance criterion was weakened** to make the refreshed surface pass. The gate
  failed twice during the pass — once on stale artifact keys, once on an uncovered branch
  in the new sensitivity guard — and both were fixed rather than accommodated.
- **D2 is unchanged and still enforced structurally.** 14 primary features, all reading
  only declared ACS demographics and land area.
- **Reconciliation is unchanged**: proportional, on partitions, residual 2.33e-10.
- **The uncertainty weights were not retuned**, and the components are the same five.
- **New Jersey was not downgraded.**

---

# 15. External Review Corrections — audit items A, B and C (2026-08-31)

Three audit items raised after the ACS 2024 refresh was accepted. **Item B uncovered an
S1 defect that the two-vehicle question was not looking for**, and correcting it changes
the published national estimate.

## 15.1 Item A — the 84,400 → 84,401 tract set, reconciled

**The earlier wording was an overclaim and is withdrawn.** §14.2 said "identical area
counts at every grain". That rested on a **bounded Rhode Island retrieval check** (250
tracts) plus national ZCTA and county counts. It was **never a national tract-count
comparison**, and the national tract count had in fact changed. The claim should have read:
*ZCTA and county sets are identical nationally; the tract set gained one.*

Complete national GEOID-set comparison, ACS 2023 against ACS 2024:

| Grain | 2023 | 2024 | Intersection | Old-only | New-only |
|---|---:|---:|---:|---:|---:|
| **tract** | 84,400 | **84,401** | 84,400 | **0** | **1** |
| ZCTA | 33,772 | 33,772 | 33,772 | 0 | 0 |
| county | 3,222 | 3,222 | 3,222 | 0 | 0 |

**The one tract that entered:**

| Field | Value |
|---|---|
| GEOID | **36111954401** |
| Name | Census Tract 9544.01, **Ulster County, New York** |
| Population / households | 6,088 / 690 |
| Median household income | $146,824 |
| Constraint | New York state total, 2025 vintage (New York is ZIP-observed, so no county totals bind) |
| Evidence grain / tier | `state_total_only` / **B** |
| **Reason it entered** | It **does not exist in ACS 2023**: the live API returns **HTTP 204 No Content** for `state:36 county:111 tract:954401` in the 2023 release and HTTP 200 in 2024. Ulster County went from 49 to 50 published tracts. Its pair 9544.**02** was already published in 2023, so 9544.01 is the half that had no published estimates until this release |

Nothing left the surface. The ratio of 6,088 people to 690 households (8.8) points to a
substantial group-quarters population, which is consistent with a tract that only became
publishable once its estimates cleared disclosure thresholds — but the Census does not
state a reason, and none is asserted here.

`tract_set_reconciliation` is now computed on **every** run and lands in the evidence
artifact, so a future vintage change is named tract by tract rather than noticed later.

## 15.2 Item B — the national total, and the S1 defect it exposed

The reviewer was right to refuse "floating-point noise". Building the exact accounting
showed the national total **exceeding the sum of its constraints by 141,816** — a gap four
orders of magnitude larger than the two vehicles under investigation.

### The defect (impact I-15, S1)

"Reconcile to county totals where they exist, else to the state total" partitions a
state's tracts cleanly **only when county coverage is complete**. Where a state's DMV
reports *some* of its counties, the remaining tracts fell through to a group keyed by the
state whose total was the **full state total** — which the observed counties had already
claimed. Both were counted.

| State | Counties observed | Published before | Correct | Error |
|---|---|---:|---:|---:|
| **Montana** | 51 of 56 | **13,673** | 6,900 | +6,773 |
| **Virginia** | 129 of 133 | **266,876** | 134,900 | +131,976 |
| Tennessee | 95 of 95 (complete) | 53,029 | 53,029 | none |

Every Montana and Virginia tract outside an observed county carried roughly **twice** the
demand it should have.

**Why every existing check passed.** `ProportionalReconciler` was working correctly: every
constraint was satisfied exactly, the residual really was 2.33e-10, and `_check_partition`
confirmed no tract was bound twice — the tracts *were* partitioned. The defect was in the
**totals handed to the reconciler**, not in the reconciliation. Nothing verified that the
constraint totals themselves summed to the intended national figure.

### The fix and the identity that now guards it

The state-level fallback is the **residual** — state total minus county totals already
claimed. A state whose county totals *exceed* its state total raises rather than clamping
to a negative residual. `ConstraintAccounting` proves this identity on every build:

```
national_published == constraint_sum + observed_substitution_delta + unconstrained_sum
```

| Term | Value | Meaning |
|---|---:|---|
| `constraint_sum` | **5,616,329.0000** | 325 groups: 51 state groups + 274 observed county groups |
| `observed_substitution_delta` | **611.0328** | Washington's 1,769 directly observed tract counts published in place of estimates, overriding its state constraint by design |
| `unconstrained_sum` | **0.0000** | Tracts no constraint binds. Zero: every jurisdiction has a published total |
| **`national_published`** | **5,616,940.0328** | |
| **Imbalance** | **1e-09** | |

`constraint_sum` (5,616,329) is **not** the sum of the 51 state totals (5,618,700). The
difference of **2,371** is exactly Tennessee's: its complete county coverage displaces its
state total, and 53,029 county-observed vehicles replace a 55,400 state figure. That is
§7.3 working as specified — county totals take precedence where they exist.

### The original two-vehicle question, answered

| Quantity | ACS 2023 | ACS 2024 | Change |
|---|---:|---:|---:|
| `constraint_sum` | 5,616,329.0000 | 5,616,329.0000 | **0** |
| `observed_substitution_delta` | 610.3405 | 611.0328 | **+0.6923** |
| `unconstrained_sum` | 0.0 | 0.0 | 0 |
| **National published** | 5,616,939.3405 | 5,616,940.0328 | **+0.6923** |

**The constraint totals did not change at all.** The entire difference is the Washington
observed-substitution term, which is *not* a constraint: it is the gap between Washington's
observed tract counts and the reconciled values they displace, and those reconciled values
depend on the ACS features. A feature refresh therefore moves it. The displayed integers
differed by 2 rather than 1 because the pre-fix totals were dominated by the double count
and rounded across a boundary.

### National estimate, corrected

| | |
|---|---:|
| Published in §9.6 and §14.3 (defective) | 5,755,687 / 5,755,689 |
| **Corrected** | **5,616,940** |
| Overstatement removed | **138,749** (≈2.5%) |

Confidence tiers move by one tract (B 58,820 → 58,821, from the new Ulster tract);
evidence grains are 1,769 `native_tract` / 4,204 `county_anchored` / 78,428
`state_total_only`; mean uncertainty 0.202676; B/C threshold 0.260165. **The measured
transformation ladder, the estimator selection, the LOSO metrics and the ablation are all
unaffected** — none of them depends on the constraint plan.

## 15.3 Item C — the New Jersey claim, corrected

**The earlier claim was too strong and is withdrawn.** §14.6 said New Jersey "did not
drive selection, and structurally could not have". The second half is false: **New Jersey
was in the aggregate that selected the estimator**, so it could in principle have
influenced candidate ranking. The defensible claim is narrower:

> The **post-selection** New Jersey sensitivity was not used to alter estimator selection.
> It reuses already-generated leave-one-state-out scores — no refitting, no reselection —
> and the estimator chosen under the original pre-registered rule is retained regardless
> of what the table shows.

**Candidate sensitivity, all five, from already-generated scores:**

| Candidate | With NJ | Without NJ | Delta |
|---|---:|---:|---:|
| **`poisson_glm`** *(selected)* | **0.320310** | **0.303913** | −0.016397 |
| `boosted_poisson` | 0.328979 | 0.313015 | −0.015964 |
| `ridge_log_rate` | 0.376339 | 0.363478 | −0.012861 |
| `baseline_population_share` | 0.705842 | 0.701335 | −0.004507 |
| `baseline_household_share` | 0.708315 | 0.701188 | −0.007127 |

**Ranking with NJ:** poisson_glm, boosted_poisson, ridge_log_rate,
baseline_population_share, baseline_household_share
**Ranking without NJ:** poisson_glm, boosted_poisson, ridge_log_rate,
**baseline_household_share, baseline_population_share**

**The ranking does change — and the change is confined to the two baselines**, which swap
by 0.000147. The winner is unchanged, and the ordering *among models* is unchanged. Since
a baseline is a floor to clear rather than a candidate that can win, this is not selection
fragility in any sense that bears on the choice. Reporting a bare "the ranking is not
stable" would have been true and useless; the artifact records which part moved.

Removing New Jersey improves the headline aggregate by **1.64 percentage points**, which
remains material and is stated as such. New Jersey stays `flagged_for_review`, stays in
the panel, stays in the training set, and confidence tiers are untouched. **A-3.1 remains
open for Phase 5.**

## 15.4 Regression coverage added

| Item | Guards |
|---|---|
| **A** | tract-set reconciliation computed every run; entered/left fully enumerated with profiles; `intersection + entered == current`; ZCTA and county compared **nationally** |
| **B** | national accounting identity asserted on every build and raises if unmet; partial county coverage constrains the remainder to the residual; complete coverage creates no state group; county totals exceeding a state total are refused rather than clamped |
| **C** | sensitivity covers all five candidates; the narrow claim is asserted verbatim; the pre-registered winner is retained; an ordering change must be described precisely rather than as a bare boolean |

## 15.5 Newly discovered defect

**I-15, S1** — described in §15.2. It is the only new defect. It was caught before the
surface reached any downstream phase, and no earlier phase consumed it.

## 15.6 Gate evidence for the audit correction pass

`make gate PHASE=3`:

| Step | Result |
|---|---|
| 1. lint | ruff clean; `mypy --strict` clean over 99 source files |
| 2. full test suite | **903 passed, 47 deselected** in 99.38s |
| 3. coverage | **100% line and branch on every tier**: 4,135 statements, 1,002 branches, zero missed |
| 4. prior gate suites (Phase 0, 1, 2) | pass; probe determinism byte-identical |
| 5. Phase 3 acceptance criteria | **20 passed** |
| 6. D3 copy lint | clean, 141 files |
| 7. semantic determinism | pass |
| 8. one-command rebuild | canonical tables and every Phase 3 number rebuilt |
| **Verdict** | **PASS** |

The suite grew 883 → **903**: nine checks for audit items A, B and C, four for the
partial-county-coverage defect, and seven for the fragility description and tract-set
reconciliation. **The gate failed twice during this pass** — once because the completed
accounting identity caught its own missing `unconstrained_sum` term, once on the untested
branches of the new fragility helper — and both were fixed rather than accommodated.
