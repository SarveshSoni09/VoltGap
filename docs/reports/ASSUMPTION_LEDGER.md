# Assumption ledger

Every assumption a phase makes that a later phase depends on, written as a falsifiable
statement, with the phase that will test it. Carried forward and re-checked at every
subsequent gate (CLAUDE.md §15.2).

Status values: **OPEN** (not yet tested), **CONFIRMED**, **FALSIFIED**.

---

## Opened in Phase 0

| ID | Falsifiable statement | Depends on | Tested in | Status |
|---|---|---|---|---|
| A-0.1 | The AFDC station schema served live at `developer.nlr.gov` is identical to the 75-column schema of the December 2024 seed snapshot, so the seed file is a valid stand-in fixture for live station data. | Both hash to `f6860736f1304654`; verified by comparing the first 75 columns of the live charging-units export against the seed header. | Phase 1 | **CONFIRMED** in Phase 0 |
| A-0.2 | AFDC serves no historical station snapshots, so any reconstructed historical network is survivorship-biased and must be labelled an approximate reconstruction. | The `ev-charging-units` endpoint documents no snapshot or date parameter; `Snapshot Date` always equals the current date. | Phase 5 | OPEN |
| A-0.3 | Rung-1 (reported) per-connector power covers at least 40% of ports, so the §7.1 power ladder does not need a prominent LIMITATIONS entry on coverage grounds. | Measured 88.11% port-weighted on public + operational supply, 82.76% over all rows. | Phase 2 | **CONFIRMED** in Phase 0 |
| A-0.4 | The NREL county home charging shares cannot serve as a present-day calibration target, so §7.2's fallback applies and home charging stays out of the primary siting objective. | The file is parametric over EV share of stock (942,600 rows = 3,142 counties × 3 scenarios × 100 levels), not a dated observation. | Phase 3 | **CONFIRMED** in Phase 0 |
| A-0.5 | Each AFDC annual registration page is a contemporaneous snapshot of that year rather than a retrospective reconstruction from current VIN data. | Not stated by the publisher. If it is retrospective, the series is survivorship-affected and its use at a backtest cutoff needs a caveat. **This is the weakest link in the D1 vintage story.** | **Phase 1** (moved forward from Phase 5 by owner decision A10, 2026-08-19; bounded investigation, and if unresolved record `historical_vintage_semantics = unresolved` and require Phase 5 to state the limitation) | OPEN |
| A-0.6 | Block-group population-weighted centroids are sufficient for §7.5 access and §7.6 allocation, or, if not, TIGER blocks joined to P.L. 94-171 block population yield genuine block-level weights at acceptable cost. | No ready-made block-level population-weighted centroid product exists (HTTP 404, verified). §7.5 and §7.6 word the requirement differently. | Phase 2 | OPEN |
| A-0.7 | ZIP-code registration counts from the 11 ZIP-grain Atlas states can be reallocated to census tracts with acceptable error using a public ZIP-to-tract crosswalk. | ZIP Code Tabulation Areas do not nest inside tracts. 11 of the 16 states with sub-state data are ZIP-grain; only Washington is natively tract-grain. | Phase 3 | OPEN |
| A-0.8 | The delivered HIFLD transmission GeoJSON (94,216 features) and the live HIFLD service (52,244 features) are the same underlying dataset at different vintages or filters, so either may be used provided the extract is labelled. | Counts differ by 41,972 features. The publisher documents no reason. | Phase 1 | OPEN |
| A-0.9 | A national electric substation dataset obtainable at zero recurring cost exists somewhere Phase 0 did not look, or §7.8 candidate filtering and §7.9 grid proximity can be respecified without one. | Five searches found no national layer; the best candidate holds 128 features. | — | **RESOLVED 2026-08-19 by owner decision A6**: the specification was respecified. National substation proximity is no longer a mandatory Core candidate filter; Core siting must function without it. Transmission remains optional labelled context and must never masquerade as an interconnection constraint. |
| A-0.10 | The Internet Archive copy of CEJST v2.0 remains retrievable, or a local mirror is taken before it stops being. | The live host has no DNS record; the archive is currently the only path found. | Phase 6 | OPEN |
| A-0.11 | A machine-retrievable FHWA traffic dataset URL exists and is stable enough to automate. | Only the HPMS landing page was located in Phase 0. Traffic is named in §10.2.3 as part of the reduced backtest feature set. | Phase 5 | OPEN |
| A-0.12 | The number of genuinely usable **sub-state anchored** states is large enough for leave-one-state-out validation (§10.1) to have meaningful statistical power. | 16 distinct states have sub-state registration data, but usability at tract grain depends on A-0.7 and on the §7.5.1 transformation-quality measurement. If the usable count falls to 3 or fewer, the LOSO design must be reconsidered through a formal plan change rather than continued quietly. Terminology updated per owner decision A3: "Tier A" now means *sub-state anchored*, not *observed*. | Phase 3 | OPEN |
| A-0.13 | Bounded probe samples are representative enough that expected row-count ranges derived from them detect real drift without false alarms. | Expected ranges for the Atlas states, ACS bulk and CEJST come from a 65,536-byte sample widened by the provisional ±20% tolerance, not from full files. Per-source tolerances should replace the default as behaviour is observed. | Phase 1 | OPEN |
| A-0.14 | Bounded, cached replay fixtures (3.4 MB across 47 sources) stay sufficient as a deterministic gate substrate as later phases need more of each source. | The committed fixtures hold only the head of each large file. A phase needing full-file behaviour will need a different strategy. | Phase 1 | OPEN |
| A-0.15 | The delivered seed files remain byte-identical for the life of the project, so frozen fixture expectations never need to drift. | SHA-256 of all ten recorded in `data/seed/seed_inventory.json`; enforced by `test_the_seed_inventory_still_matches_the_delivered_bytes`. | every phase | **CONFIRMED** in Phase 0 |

---

## Opened by the Phase 0 review (2026-08-19)

| ID | Falsifiable statement | Depends on | Tested in | Status |
|---|---|---|---|---|
| A-0.16 | Physical port identity is recoverable from AFDC for a usable share of public operational infrastructure, so a `ports` table with one row per real port is meaningful. | Not yet measured. The export supplies per-connector *counts*, not port identifiers. Owner decision A5 forbids manufacturing identity; Phase 1 must measure identifiability across six named quantities before the canonical schema is frozen. | Phase 1 | OPEN |
| A-0.17 | `sum(connector-specific counts)` equals `charging_unit.port_count` often enough that connector counts can be attributed to ports unambiguously. | Where the sum exceeds `port_count`, one physical port exposes multiple connector types and the mapping is many-to-one. Frequency unmeasured. | Phase 1 | OPEN |
| A-0.18 | A public ZIP-to-tract crosswalk exists whose allocation error can be *measured* rather than assumed, using Washington's native tract data as the holdout. | §7.5.1 requires measured allocation error feeding the uncertainty score. Washington is the only natively tract-grain source, so it is the only available ground truth for a round-trip test. | Phase 3 | OPEN |
| A-0.20 | Some stable charging-unit identity is recoverable from AFDC network metadata even though the export itself carries none. | The export has no unit id column and 65.9% of rows are byte-identical duplicates (impact I-1). If nothing is recoverable, `charging_unit_record_key` stays synthetic and per-snapshot, and no longitudinal physical-unit tracking is possible at any point in the project. | Phase 1 | OPEN |
| A-0.21 | Excluding `computed_at` and other run-time-dependent metadata from the semantic hash leaves a hash that still detects every genuine data change. | Amendment A14. If a real semantic change hid inside an excluded field, the determinism gate would pass on a changed pipeline. The exclusion list must stay minimal and be justified per field. | Phase 1 | OPEN |
| A-0.19 | A rule-based terminology lint is sufficient to enforce the §11.5 copy rules and D3 vocabulary without semantic understanding. | Owner decision A9 accepts a phrase-matching guard for Phase 1, extended in Phase 5. Risk is false negatives on paraphrase. | Phase 1 | OPEN |

## Re-checked at this gate

Not applicable to Phase 0: this is the first phase and there are no prior assumptions.
Assumptions A-0.1 to A-0.15 were opened by Phase 0 itself; A-0.9 was resolved by the Phase 0
review, and A-0.5 moved forward to Phase 1. Phase 1's gate re-checks all open entries.

---

## Opened by Phase 1 (2026-08-24)

| ID | Falsifiable statement | Depends on | Tested in | Status |
|---|---|---|---|---|
| A-1.1 | Land-area weighting is an acceptable interim basis for ZIP-to-tract allocation, and its error is small enough that Phase 3 can measure and correct it rather than having to discard Phase 1 output. | Land area assumes uniform population within a ZCTA, which §7.6 says is badly wrong in large rural areas. 76.3% of ZCTAs span more than one tract, so this affects most of the country. | Phase 3 (Washington round-trip) | OPEN |
| A-1.2 | The JSON API's eight-connector taxonomy maps cleanly onto the five connector standards named in §1.1 (J1772, CCS, CHAdeMO, J3400/NACS, J3271). | The API uses `J1772COMBO` for CCS and `TESLA` for J3400/NACS, and adds three NEMA Level-1 types the §1.1 vocabulary does not mention. | Phase 2 (power ladder) | OPEN |
| A-1.3 | A rule-based copy lint with whole-file and glob allowlisting catches the claims that matter. | Phase reports are allowlisted so they can quote a prohibition in order to record it; a genuine optimality claim inside a report would not be caught. Accepted because UI strings, docstrings and artifact fields are not allowlisted. | Phase 6 | OPEN |
| A-1.4 | Row order within a station is stable enough within a single snapshot that `charging_unit_record_key` is usable as a within-run join key. | It is explicitly not stable across runs. If the API or DuckDB reorders within a run, unit-to-connector joins would silently mismatch. | Phase 2 | OPEN |

## Re-checked at the Phase 1 gate

| ID | Assumption | Status | Evidence |
|---|---|---|---|
| A-0.5 | AFDC annual pages are contemporaneous snapshots | **PARTIALLY RESOLVED** | Stability established 2022-08-18 to 2026-08-24 (52/52 identical for both the 2020 and 2021 vintages); contemporaneity NOT established, no capture predates 2022-08-18. Recorded as `historical_vintage_semantics = stable_not_revised_within_observable_window`, `contemporaneity = unresolved`. Finding F-11 |
| A-0.9 | A national substation dataset exists somewhere unsearched | Remains RESOLVED by respecification (A6) | No substation module was built |
| A-0.16 | Physical port identity is recoverable for a usable share of public operational infrastructure | **FALSIFIED** | m2, m5 and m7 all negative over 292,756 units. `ports` is not populated |
| A-0.17 | `sum(connector counts)` equals `charging_unit.port_count` often enough to attribute connectors to ports | **FALSIFIED** | 16,610 units exceed their own `port_count`, led by CHADEMO+J1772COMBO (7,071) |
| A-0.20 | Some stable charging-unit identity is recoverable from network metadata | **FALSIFIED** | JSON unit objects carry exactly five keys — `charging_level`, `connectors`, `funding_sources`, `network`, `port_count` — none an identifier |
| A-0.21 | Excluding volatile metadata from the semantic hash still detects every genuine change | HOLDS so far | `test_source_vintages_is_in_scope_for_the_hash`, `test_a_genuine_data_change_does_move_the_hash` |
| A-0.19 | A rule-based terminology lint is sufficient | HOLDS so far, superseded by A-1.3 which states the specific weakening | 79 files clean, 15 rules |
| A-0.6 | Block-level population weighting is constructible from TIGER + P.L. 94-171 | UNTESTED this phase | Phase 2 |
| A-0.7, A-0.12, A-0.18 | ZIP-to-tract usability and the usable sub-state-anchored state count | UNTESTED this phase; the machinery now exists, the error measurement does not | Phase 3 |

---

## Opened by Phase 2 (2026-08-24)

| ID | Falsifiable statement | Depends on | Tested in | Status |
|---|---|---|---|---|
| A-2.1 | The 4 DBSCAN clusters exceeding 200 m diameter do not materially distort site counts, nearest-site distance or access-gap population. | Transitive connectivity means eps = 50 m does not bound diameter. 886 clusters exceed 50 m, 86 exceed 100 m, 4 exceed 200 m, none exceeds 500 m. Immaterial at the 16.1 km threshold, but Phase 4 candidate siting may be sensitive at the 100 m scale. | Phase 4 | OPEN |
| A-2.2 | A 30-observation minimum makes a rung-2 empirical median reliable enough to stand in for reported power. | Chosen so a median rests on a real distribution. 164 national groups qualify and rung 3 is never reached, so this threshold alone determines 19.85% of all resolved power. A different threshold would change published capacity. | **Phase 4 prerequisite** (moved from Phase 3 on 2026-08-26: this is a SUPPLY-method question and does not belong in the demand model. Validation is a masked-power evaluation holding out entire stations or sites, not random connector rows, building peer medians without the held-out site, and reporting error by connector and charging level against the rung-3 default. Must complete before Phase 4 uses supply capacity for siting) | OPEN |
| A-2.3 | Block-group population-weighted centroids are close enough to block-level for national access figures. | §7.6 asks for block-level weights; no ready-made product exists (Phase 0 F-7). A block group averages ~1,380 people, so the corner-population problem recurs at smaller scale in large rural block groups. | Phase 4 | OPEN |
| A-2.4 | Straight-line distance is a usable proxy for drive distance in access reporting. | Great-circle distance never exceeds road distance FOR A GIVEN POINT, but because each block group is represented by one population-weighted point the aggregate is an approximation rather than a bound. How far it diverges is unmeasured until Extension E3. | E3 | OPEN |
| A-2.5 | Treating a site as public operational supply when *any* of its stations is public operational is the right rule for access. | G4 aggregates co-located multi-network infrastructure, so a site can mix a public station with a private fleet depot. Site capacity then includes ports a driver cannot use. Raised as Phase 2 open question Q2. | Phase 4 | OPEN |

## Re-checked at the Phase 2 gate

| ID | Assumption | Status | Evidence |
|---|---|---|---|
| A-1.1 | Land-area weighting is acceptable as an interim allocation basis | **DEFERRED, not exercised.** Phase 2 does not consume registration allocations at all (amendment A21), so the assumption is untouched and Phase 3 still owns it | P2-G, 4 tests |
| A-1.2 | The eight JSON connector standards map cleanly onto the five in the §1.1 vocabulary | **CONFIRMED with a caveat.** The normalisation table maps all eight; three NEMA standards have no §1.1 equivalent and are carried as themselves. Both raw and normalised forms are preserved | P2-C, 3 tests |
| A-1.4 | Row order within a station is stable enough within one snapshot for the record key to join | **HOLDS.** Unit-to-connector joins produced zero orphans across 292,756 national units | smoke-forward, 5 tests |
| A-0.6 | Block-level population weighting is constructible from TIGER + P.L. 94-171 | **UNTESTED.** Phase 2 used block-group centroids instead; superseded in scope by A-2.3 | Phase 4 |
| A-1.3, A-0.19 | A rule-based copy lint catches the claims that matter | **HOLDS so far.** 95 files clean. Four legitimate quotations of a prohibited phrase needed inline allow markers this phase, which is the mechanism working | copy lint |

---

## Opened by Phase 3 (2026-08-28)

| ID | Falsifiable statement | Depends on | Tested in | Status |
|---|---|---|---|---|
| A-3.1 | New Jersey's observed BEV total is materially incomplete rather than definitionally different from the AFDC series. | Observed 164,538 against AFDC 2025's 210,000, **−21.65% at the same vintage**, where 13 of the other 14 states agree within 9%. Its latest snapshot carries **one distinct registration date** against 36 for Connecticut and 138 for New York. Corrected G9 forbids marking it low-confidence on statistical unusualness alone, so it is flagged and left in the panel. | Phase 5 | OPEN |
| A-3.2 | The Washington-measured transformation ladder generalises to other states, so a `c4` derived there is a fair penalty nationally. | Washington is the only state whose vehicle rows carry a ZIP, a county and a tract together, so it is the only place the ladder can be measured at all. Its housing and settlement pattern is not the national one. | Phase 5 | OPEN |
| A-3.3 | Fitting at each state's own observed geography and predicting at tract grain does not introduce material aggregation bias. | A rate model fitted on ZCTA and county rows is applied to tracts. Share features aggregate as population-weighted means, which is what a coarser area's share *is*, but the relationship need not be scale-invariant. Washington is the only place this could be checked, and it is the non-independent state. | Phase 5 | OPEN |
| A-3.4 | The AFDC state totals, rounded to the nearest 100, are precise enough to serve as exact reconciliation constraints. | Every reconciled tract estimate inherits a constraint good to about ±50 vehicles per state. At national scale that is ~±2,550 vehicles against 5,755,687. | Phase 4 | OPEN |
| A-3.5 | Population density is an adequate stand-in for the urban/rural classification CLAUDE.md §7.3 names. | No keyless tract-level Census urban/rural product was retrieved this phase, so the feature ships as a continuous proxy. A classification would let the model treat rural areas as a distinct regime rather than an extreme of one. | Phase 4 | OPEN |
| A-3.6 | The eleven ZIP-grain states' registration data are better used as training and validation evidence than as reconciliation constraints. | The measured ladder says ZIP-anchored allocation places EV mass better than a state total alone (statewide tract TVD 0.1621 against 0.3049), which is evidence *for* using them as constraints. Phase 3 declined on scope grounds under CLAUDE.md §19, not on merit. | — | **CLOSED 2026-08-29 by external review.** ZIP-grain observations remain valuable training and native-grain validation evidence, but they **will not become hard tract-level reconciliation constraints in Core v1**: one-state evidence is insufficient to justify changing the national reconciliation model and evidence-grain semantics at this stage. No ZIP-level IPF constraints; no `zip_anchored` values in the production surface; county totals where reliable and state totals everywhere else. The experiment stays in `docs/FUTURE_WORK.md`. **This no longer blocks Phase 4.** |

## Re-checked at the Phase 3 gate

| ID | Assumption | Status this phase | Evidence |
|---|---|---|---|
| A-0.7 | ZIP-code counts can be reallocated to tracts with acceptable error | **Not exercised as stated, and deliberately.** Phase 3 allocates no ZIP count onto a tract; ACS publishes features at ZCTA grain, so each state is fitted against the counts it actually publishes. The allocation error was still *measured* (0.1621 statewide tract TVD under HUD `res_ratio`) and feeds the uncertainty score | transformation ladder, §5.5 of the Phase 3 report |
| A-0.12 | The number of genuinely usable sub-state anchored states is large enough for LOSO to have power | **CONFIRMED.** 14 independent states after excluding Washington, well above the 3-or-fewer plan-change trigger, which the harness raises on | `test_three_or_fewer_usable_states_triggers_a_plan_change_not_a_weaker_test` |
| A-0.18 | A public ZIP-to-tract crosswalk exists whose allocation error can be measured rather than assumed | **CONFIRMED.** HUD 2026 Q2, measured against Washington's paired records at three grains | `docs/evidence/P3-1_wa_allocation_scope_and_error.json`, `P3-2_demand_model.json` |
| A-1.1 | Land-area weighting is acceptable as an interim allocation basis, and its error is small enough for Phase 3 to correct rather than discard | **FALSIFIED as the preferred method, retained as the documented fallback.** HUD `res_ratio` reaches statewide tract TVD 0.1621 against land area's 0.2100 under a common method, and 0.1794 against 0.2579 EV-weighted within ZIPs | Live Integration Assurance Checkpoint §E.1; ladder §5.5 |
| A-0.4 | The NREL county home-charging shares cannot serve as a present-day calibration target | **Remains CONFIRMED, and unused.** Home charging access is absent from the primary feature set, as amendment A7 requires | `assert_primary_feature_set_is_clean` |
| A-2.1, A-2.2, A-2.3, A-2.4, A-2.5 | The Phase 2 supply and access assumptions | **UNTESTED this phase.** Phase 3 consumes no Phase 2 supply output except inside the labelled ablation, which is not part of the published surface | Phase 4 |
| A-1.3, A-0.19 | A rule-based copy lint catches the claims that matter | **HOLDS so far.** 140 files clean, 15 rules | copy lint |
| A-0.21 | Excluding volatile metadata from the semantic hash still detects every genuine change | HOLDS | `tests/integration/test_determinism.py` |

---

## Opened by the external-review correction pass (2026-08-29)

| ID | Falsifiable statement | Depends on | Tested in | Status |
|---|---|---|---|---|
| A-3.7 | ACS 2024 5-year is a like-for-like replacement for ACS 2023 5-year across every variable Phase 3 consumes. | All 78 variables are present in the 2024 dictionary and returned by the API at tract, ZCTA and county grain, with identical area counts (250 Rhode Island tracts, 33,772 ZCTAs, 3,222 counties) and identical column ordering. Two label changes exist and neither affects a consumed universe: `B19013_001E` moves to 2024 inflation-adjusted dollars, and `B08301_010E` drops the "(excluding taxicab)" parenthetical because line 016 was renamed "Taxicab" → "Taxi or ride-hailing services". Phase 3 does not consume line 016. | Phase 4 | OPEN |
| A-3.8 | Median household income expressed in 2024 dollars rather than 2023 dollars does not change the model's behaviour in any way that matters. | The model refits entirely within one vintage, so it is internally consistent, but the feature's **units changed**, which means the fitted coefficient is not comparable across vintages and a before/after comparison of that feature is not like-for-like. | Phase 4 | OPEN |
| A-3.9 | Washington's presence in another state's training fold does not compromise that state's independence as evaluation evidence. | Washington's tuning influence is specific: it selected the HUD ZIP→tract preprocessing method. That invalidates a Washington *result*, not an Oregon or Texas holdout whose own observations played no part in the crosswalk choice. Recorded as amendment W5-W8 to the pre-registration and authorised by external review. | Phase 5 | OPEN |

## Re-checked at the correction-pass gate

| ID | Assumption | Status | Evidence |
|---|---|---|---|
| A-3.1 | New Jersey's observed total is materially incomplete rather than definitionally different | **STILL OPEN, and now quantified.** New Jersey stays `flagged_for_review`, not marked low-confidence, per corrected G9. A bounded with/without sensitivity on the headline aggregate is reported as a diagnostic that cannot feed back into selection | `test_check_10_new_jersey_sensitivity_is_reported_and_cannot_drive_selection` |
| A-3.2 | The Washington-measured transformation ladder generalises nationally | **STILL OPEN.** Unchanged by the ACS refresh; the limitation that `c4` is extrapolated from one state is preserved | Phase 5 |
| A-3.6 | ZIP-grain data are better used as evidence than as constraints | **CLOSED by external review** — see above | reviewer decision |

---

## Opened by the audit correction pass (2026-08-31)

| ID | Falsifiable statement | Depends on | Tested in | Status |
|---|---|---|---|---|
| A-3.10 | Every jurisdiction Phase 3 publishes has a registration total, so no tract's estimate rests on no observed total at all. | `unconstrained_sum` is currently **0.0** across 84,401 tracts. If a future refresh loses a jurisdiction's total, that state's tracts would keep raw model values with no constraint, and the national accounting reports the amount rather than absorbing it. | Phase 4 | OPEN |
| A-3.11 | Where a state publishes county totals for only part of its territory, the state total minus those county totals is a meaningful residual for the remaining tracts. | Montana 51 of 56 counties leaves a residual of 127 vehicles across 5 counties; Virginia 129 of 133 leaves 2,924. Both are positive and plausible, but the two sources have different vintages and definitions, so a residual is a subtraction across sources rather than a measurement. | Phase 5 | OPEN |
| A-3.12 | Tennessee's complete county coverage displacing its state total is correct rather than a coverage gap. | Tennessee publishes all 95 counties totalling 53,029 against a 2025 state total of 55,400, a 2,371 difference that is simply excluded from the national constraint sum. CLAUDE.md §7.3 says county totals take precedence where they exist, so this is specified behaviour - but it does mean the national figure omits 2,371 vehicles the state series reports. | Phase 4 | OPEN |

## Re-checked at the audit gate

| ID | Assumption | Status | Evidence |
|---|---|---|---|
| A-3.7 | ACS 2024 is a like-for-like replacement | **CONFIRMED with a correction to the claim.** ZCTA and county sets are identical nationally; the **tract set gained one** (36111954401, Ulster County NY, absent from ACS 2023 with HTTP 204). The earlier "identical area counts at every grain" rested on a bounded Rhode Island check and is withdrawn | `tract_set_reconciliation` |
| A-3.4 | AFDC totals rounded to the nearest 100 are precise enough as exact constraints | **STILL OPEN, and now measurable.** The national accounting makes the constraint sum explicit (5,616,329) so rounding error is visible rather than buried | Phase 4 |

---

## Opened by the constraint-precedence correction (2026-08-31)

| ID | Falsifiable statement | Depends on | Tested in | Status |
|---|---|---|---|---|
| A-3.13 | ~~A census tract that Washington's vehicle registry does not name holds **zero** registered BEVs, rather than an unknown number.~~ **RESOLVED 2026-08-31 — PROVEN.** Over the exact production snapshot, 236,994 BEV records carry `state == 'WA'` and **all 236,994 are placed in a valid in-state Census tract**; the 573 unplaced records are every one of them non-WA-addressed, and none has a null jurisdiction. `unresolved_in_jurisdiction = 0`. The eight null-tract rows previously read as unresolved carry non-Washington states (BC, QC, AE, NH) and are out-of-jurisdiction, not unplaced. The 15 absent tracts are therefore **completed zeros from an exhaustive registry**, carried as `value_provenance = native_registry_zero_by_absence`, not literal zero-valued source rows. | This is what makes it defensible to constrain those 15 tracts to zero instead of leaving them modelled. It rests on the source being a registry-grade enumeration: every registered vehicle appears, so absence is a zero rather than a gap. If instead some records fail to geocode into a tract, those vehicles are counted in the ledger's exclusions and the assumption still holds; if a whole tract were systematically dropped, it would not. | Phase 5 | OPEN |
| A-3.14 | ~~A 10% agreement tolerance is the right bar for a native source to supersede an external total.~~ **WITHDRAWN 2026-08-31 on external review.** Agreement with an external aggregate cannot establish completeness in either direction: a source can agree closely while omitting a whole region, or disagree widely while being exhaustive over a differently-defined population. Completeness now rests on declared publisher scope plus explicit record and geography accounting; AFDC agreement is retained only as a review diagnostic (`EXTERNAL_AGREEMENT_REVIEW_THRESHOLD`) and gates nothing. | `NATIVE_SUPERSEDE_TOLERANCE`. Washington sits at 0.25%, so the threshold is not close to binding today and has never been tuned against a result. A future state nearer the boundary would make the choice load-bearing. | Phase 4 | OPEN |
| A-3.15 | Tennessee's complete county coverage genuinely superseding its state total is right, and the 2,371-vehicle difference is a definitional gap rather than missing coverage. | Tennessee publishes all 95 counties totalling 53,029 against a 2025 AFDC total of 55,400. CLAUDE.md §7.3 makes county totals authoritative where they exist, so the national figure omits 2,371 vehicles the state series reports. | Phase 5 | OPEN |

---

## Opened by the zero-by-absence correction (2026-08-31)

| ID | Falsifiable statement | Depends on | Tested in | Status |
|---|---|---|---|---|
| A-3.16 | Washington's `state` field records the **address of record** and is populated for every row, so `state != 'WA'` genuinely means out-of-jurisdiction rather than missing. | This is what turns the eight null-tract rows from *unresolved* into *out-of-jurisdiction*, and it is what licenses the 15 completed zeros. Zero of the 573 unplaced BEV records have a null `state`, which is strong evidence the field is populated, but the publisher does not document a completeness guarantee for it. | Phase 5 | OPEN |
| A-3.17 | Falling back entirely to the external total, when a native source cannot place every in-jurisdiction record, is better than constraining its named tracts and giving the rest a residual. | Chosen because it invents nothing and cannot double-count (the failure mode of I-15). It does discard exact observations from the published surface in that case. The branch is not exercised by current data - Washington is fully resolved - so the choice is untested against a real incomplete source. | whenever a partially resolved native source appears | OPEN |

---

## Re-checked at the Phase 4 gate (2026-08-31)

| ID | Assumption | Status | Evidence |
|---|---|---|---|
| A-2.1 | The 4 DBSCAN clusters over 200 m diameter do not materially distort candidate siting | **RESOLVED.** Max cluster diameter 500 m against a measured **3,834 m** H3 res-6 cell edge = 13.0% of an edge. It can straddle a boundary, which is stated rather than denied, but the k-ring coverage neighbourhood already spans adjacent cells, so a site landing either side covers substantially the same demand | `test_p4_f_a21_site_clustering_was_measured` |
| A-2.2 | A 30-observation minimum makes a rung-2 empirical median reliable enough to stand in for reported power | **NOT TRIGGERED, and structurally cannot be.** The prerequisite conditions any phase consuming *imputed* capacity; Phase 4 reads port **counts**, which the source reports directly with no power-resolution ladder. `HexSupply` carries **no kW field at all**, and a test asserts `capacity_kw` appears nowhere in the published artifact. **Still required before any phase consumes resolved capacity in kW** | `test_p4_f_a22_is_not_triggered_and_cannot_be_violated` |
| A-2.3 | Block-group population-weighted centroids are close enough to block-level | **PARTIALLY RESOLVED.** The block-level benchmark remains unavailable (Phase 0 finding F-7: the Census publishes no block-level population-weighted centroid product). Measured in the direction that *is* available: stepping down one resolution, from tract centroid to block group, places **18.66%** of Washington demand in a different cell, and a centroid can land in a cell containing **none** of a tract's population. That is evidence resolution matters and the finer weighting was right, **not** evidence that block group is sufficient | `test_p4_f_a23_centroid_resolution_was_benchmarked` |
| A-3.4 | AFDC totals rounded to the nearest 100 are precise enough as exact constraints | **RESOLVED for siting.** Portfolios are **identical** under ±50 in every sampled state (Jaccard 1.000 both directions). Reconciliation scales every tract in a jurisdiction by the same factor, so a uniform change cannot reorder cells within it; it could only matter across jurisdictions whose totals move by different relative amounts | `test_p4_f_a34_rounding_does_not_reorder_the_portfolio` |
| A-3.5 | Population density is an adequate stand-in for an urban/rural classification | **RESPECTED, not resolved.** Phase 4 introduces no categorical urban/rural field, and `assert_no_categorical_urban_rural` runs over every published state record. The underlying gap - no keyless tract-level Census classification was retrieved - is unchanged and remains open | `test_p4_f_a35_no_categorical_urban_rural_anywhere` |
| A-3.16 | Washington's `state` field is populated for every row | **HARDENED.** External review asked the zero-completion licence to fail closed on unknown jurisdiction. A row with a null or ambiguous jurisdiction now counts as **unresolved in-jurisdiction**, not as out-of-jurisdiction, which refuses the licence. No current number changes (zero WA rows have a null state); the guard is for future refreshes | `test_an_unknown_jurisdiction_fails_closed_and_refuses_zero_completion` |
| A-3.17 | Falling back entirely when a native source is incomplete is better than a residual | **UNTESTED against real data, unchanged.** Washington remains fully resolved, so the branch is exercised only by fixtures | Phase 5 |

## Opened by Phase 4 (2026-08-31)

| ID | Falsifiable statement | Depends on | Tested in | Status |
|---|---|---|---|---|
| A-4.1 | A resident-population filter is an adequate stand-in for the road-network proximity filter §7.8 specifies. | No road-network dataset was retrieved in any phase, and substituting one silently is what D8 forbids. An inhabited cell has roads; the specified filter would *additionally* exclude inhabited cells far from one, so this is strictly weaker and admits candidates the specification would not. | Phase 6, or whenever TIGER roads are ingested | OPEN |
| A-4.2 | A k-ring of 1 is the right coverage neighbourhood for a res-6 cell. | A charger serves adjacent cells, but 1 ring at ~3.8 km edge is a ~7-cell, ~270 km² service area, which is generous for urban cells and possibly tight for rural ones. A uniform k across a country with 38 km² cells everywhere is a simplification. | Phase 6 | OPEN |
| A-4.3 | Population below $35,000 household income is an adequate single equity indicator. | Chosen precisely to avoid a hand-weighted composite (§18 anti-pattern 4), but one indicator is a narrower view of disadvantage than several. Vehicle access, housing tenure and language isolation are all defensible alternatives that would select different cells. | Phase 5 robustness, Phase 6 | OPEN |
| A-4.4 | Uniform per-site cost does not distort the frontier relative to a real cost model. | Budget is expressed in sites because no cost model exists (§7.11 Optional tier). Real siting costs vary with land, make-ready and utility work, and a cost-aware solve would choose differently. This makes the current problem cardinality-constrained rather than budgeted. | whenever economics ships | OPEN |
| A-4.5 | The demand and equity objectives are genuinely correlated in the sampled states, rather than the equity indicator being a proxy for population. | The ε-constraint does not bind until the upper levels: the demand-optimal portfolio already delivers most reachable equity coverage. If equity population is largely tracking population, the "tradeoff" would be partly an artefact of the indicator. | Phase 5 cross-objective robustness | OPEN |
