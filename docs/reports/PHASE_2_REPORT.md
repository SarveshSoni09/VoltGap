# Phase 2 Report — Supply and Access

## 0. Report metadata

| Field | Value |
|---|---|
| Phase | 2 — Supply + access |
| Date | 2026-08-24 |
| Gate status | **PASS** |
| Commit | `gate(phase-2): PASS` |
| Duration | 1.75 part-time weeks planned; delivered within plan |
| Prepared by | Claude Code |

---

## 1. Context for a reader with zero prior knowledge

### 1.1 What this project is

**VoltGap** is an open, statically hosted decision-support application answering one
question: *given a budget and a set of policy priorities, where should the next EV
charging infrastructure be built in the United States, and how confident should we be
in that answer?* Users are infrastructure planners, charge point operators, state energy
offices and researchers. The output is a ranked, budget-feasible portfolio of candidate
hexagonal sites with scores, uncertainty bands, tradeoff context and CSV/GeoJSON export.

Eight prime directives govern it. Four matter in this report. **D2** forbids
supply-derived features from the primary demand model, because existing infrastructure
is an *outcome* of prior investment and using it to predict demand would launder
historical deployment patterns into "need". **D6** forbids describing anything as grid
feasible or interconnection ready; proximity says nothing about hosting capacity. **D7**
makes uncertainty a first-class output. **D8** requires explicit degradation when a
source is unavailable, never a silent plausible default.

### 1.2 The architecture in one paragraph

An offline Python pipeline retrieves public data, transforms it through a file-based
DuckDB warehouse (staging → intermediate → marts), and writes static artifacts to object
storage. A statically exported browser application reads those artifacts directly; there
is no server and no database at request time. Once an artifact ships, nothing downstream
can correct it, which is why schema validation blocks publication and why the gate is
offline and deterministic.

### 1.3 What the previous phases produced

**Phase 0** produced the source contract: a re-runnable probe, `SOURCES.yml` covering 57
sources with a generated observation sidecar, and hashed evidence for ten findings. It
established that AFDC exposes per-connector power (rung-1 coverage 88.11% port-weighted
on public operational supply), that the NREL home-charging dataset is a parametric
scenario surface rather than a dated observation, that ten annual state registration
vintages exist covering all three backtest origins, that sixteen states publish sub-state
registration data, and that **no national substation dataset could be located**.

**Phase 1** produced the canonical model. Its identifiability analysis established that
AFDC exposes **no charging-unit identifier of any kind** — 99.4% of unit objects are
byte-identical to another — so `charging_unit_record_key` is synthetic and per-snapshot,
and the `ports` and `connectors` tables are deliberately **not populated**. It also found
that `port_count` is 1 for every unit in the snapshot, and that **16,610 units expose
more than one connector standard on that single service port**. Its gate passed with 100%
line and branch coverage.

Phase 1's review authorised eight further amendments (A17–A24), all applied before this
phase began. Three shaped Phase 2 directly: the non-double-counting capacity rule, the
prohibition on consuming registration allocations, and two preflight investigations.

### 1.4 What this phase was supposed to do

Quoting the specification:

> Power ladder rung distribution reported with actual percentages. National population
> in DCFC access gap computed and reproducible. Sensitivity curve produced across the
> full threshold range. Population-weighted allocation verified against a hand-computed
> rural tract fixture. G1–G4 enforced in the supply path by test. **Plus P2-A to P2-H.**

Phase 2 does **no** demand modelling, siting, forecasting, queueing or economics.

---

## 2. What was built

### 2.1 Modules created

| Path | Purpose | Key functions |
|---|---|---|
| `pipeline/model/supply.py` | Connector normalisation, three-rung power ladder, capacity aggregation | `resolve_power`, `build_empirical_table`, `aggregate_unit_capacity`, `aggregate_site_capacity` |
| `pipeline/model/access.py` | DCFC and L2 access gaps with sensitivity curves | `compute_access`, `qualifying_sites`, `load_thresholds` |
| `pipeline/model/preflight.py` | The two required preflight investigations | `reconcile_stations`, `diagnose_sites`, `cluster_diameter_m` |
| `pipeline/model/build_supply_access.py` | Phase 2 build against the Phase 1 canonical tables | `build_supply_access`, `register_marts` |
| `pipeline/spatial/distance.py` | Great-circle nearest-site distance | `nearest_site_distances` |
| `pipeline/spatial/allocation.py` | Population-weighted allocation | `allocate_by_population`, `population_weights` |
| `pipeline/config/connectors.yml` | Connector taxonomy normalisation table | — |
| `pipeline/config/power_defaults.yml` | Rung-2 grouping rules, rung-3 defaults with citations | — |
| `pipeline/config/thresholds.yml` | Access thresholds and the sensitivity sweep | — |

### 2.2 The rule that mattered most, quoted

Phase 1 found 16,610 units exposing several connector standards on one service port.
Those are **alternative compatibility interfaces**, not independent ports. Summing their
power double counts capacity:

```python
# pipeline/model/supply.py
if unit_reported_maximum_kw is not None and unit_reported_maximum_kw > ZERO_POWER:
    capacity: float | None = float(unit_reported_maximum_kw)
    basis = CapacityBasis.UNIT_REPORTED_MAXIMUM
    source = PowerSource.REPORTED
elif port_count > 1:
    capacity, basis = None, CapacityBasis.MULTI_PORT_UNRESOLVED
elif powers:
    # THE non-double-counting rule. max, never sum.
    capacity, basis = max(powers), CapacityBasis.SINGLE_PORT_CONNECTOR_MAXIMUM
else:
    capacity, basis = None, CapacityBasis.UNRESOLVED
```

Note the `port_count > 1` branch. A multi-port unit does **not** inherit the one-port
maximum rule: AFDC exposes no per-port connector mapping, so which connectors serve which
port is unknown, and inventing an allocation would fabricate structure the source does not
report. Such a unit reports `None` with basis `multi_port_unresolved`.

**Charging level never comes from a connector name:**

```python
# pipeline/model/supply.py, resolve_power
spec = normalize_connector(str(record.get("connector_type_raw", "")), connectors)
level = str(record.get("charging_level", ""))   # from the RECORD, not the connector
```

The configuration says so explicitly, and NEMA 14-50 is the concrete counter-example to
"NEMA means Level 1":

```yaml
# pipeline/config/connectors.yml
# CHARGING LEVEL IS NOT DERIVED HERE. Connector standard and charging level are
# separate concepts (7.1.2). Level comes from the charging-unit record's own
# `charging_level` field. `typical_levels` below is DESCRIPTIVE ONLY.
  NEMA1450:
    normalized: NEMA 14-50
    typical_levels: ["1", "2"]
    note: >-
      A 240 V outlet, commonly used for Level 2 despite the NEMA family often being
      associated with Level 1. Concrete evidence that connector name does not
      determine level.
```

**The access metric is named for what it measures:**

```python
@property
def metric_name(self) -> str:
    """Named for what it measures, never as a desert."""
    return f"{self.supply_class} access gap"
```

### 2.3 Data artifacts produced

| Mart | Grain | Rows (MN fixture) |
|---|---|---:|
| `mart_unit_capacity` | one charging-unit record | 2,957 |
| `mart_site_supply` | one resolved site | 780 |

`mart_site_supply` carries `generic_service_capacity_kw` and
`connector_compatible_kw_json` as **separate columns**. The connector-compatible values
are serialised rather than exploded into one column per standard specifically so a reader
cannot sum them across columns by accident (gate check P2-H).

---

## 3. Decisions made and why

| Decision | Options | Chosen | Rationale | Reversible? |
|---|---|---|---|---|
| Generic capacity for a one-port multi-connector unit | sum vs max vs unresolved | **max** | The connectors are alternatives on one service position. Sum overstates by 10.69% nationally | No — it is a correctness rule |
| Multi-port units | apply the max rule vs report unresolved | **unresolved** | No per-port connector mapping exists; allocating would fabricate structure | Yes, if AFDC exposes the mapping |
| Rung-2 minimum sample | none vs 10 vs 30 | **30** | A median on a handful of points is not reliable. At 30, 164 national groups qualify and rung 3 is never reached | Yes, configured |
| Rung-2 grouping | fixed vs hierarchy | **3-level hierarchy**, most specific first | `(network, connector, level)` where populated, falling back to `(connector, level)` then `(level)` | Yes, configured |
| Population geography | tract geometric centroid vs block group population-weighted vs block | **block group, population-weighted** | §7.5 forbids geometric centroids. Block-level does not exist as a ready-made product (Phase 0 F-7); constructing it is deferred | Yes |
| Distance metric | straight-line vs drive-time | **straight-line**, labelled | §7.5: Core ships network-free distance; isochrones are Extension E3. Reported as a lower bound | No, by specification |
| Site public/operational status | any station vs all stations | **any** | A site with one public operational station offers public operational service | Yes |

---

## 4. Acceptance criteria verification (Gate part G-A)

| # | Criterion | Verifying test | Result | Evidence |
|---|---|---|---|---|
| 1 | "Power ladder rung distribution reported with actual percentages" | `test_rung_1_reported_power_wins` and siblings; evidence artifact | PASS | §9.1: 80.15% / 19.85% / 0.00% |
| 2 | "National population in DCFC access gap computed and reproducible" | `tests/unit/test_access_and_spatial.py` (17 tests); evidence artifact | PASS | §9.3: 32,113,986 (9.69%) |
| 3 | "Sensitivity curve produced across the full threshold range" | `test_the_sensitivity_curve_is_produced_and_monotonic` | PASS | 80 points, 1–80 km, monotonic |
| 4 | "Population-weighted allocation verified against a hand-computed rural tract fixture" | `test_population_weighting_beats_area_weighting_on_a_hand_computed_rural_fixture` | PASS | 957.4468 vs 333.33 area-weighted |
| 5 | "G1–G4 enforced in the supply path by test" | `test_only_public_operational_sites_qualify`, `test_g1_mart_capacity_comes_from_units_not_station_rows`, `test_g4_*` | PASS | — |
| 6 | **P2-A** no connector double counting | 6 tests incl. the three specified fixtures | PASS | 200 kW not 300 |
| 7 | **P2-B** level from source semantics | 4 tests | PASS | TESLA at L2 vs DC differ |
| 8 | **P2-C** normalisation preserves raw | 3 tests | PASS | 8/8 retain raw |
| 9 | **P2-D** `port_count` monitored, not ontology | 4 tests | PASS | schema accepts 4 ports |
| 10 | **P2-E** 22 exceptions classified | 4 tests | PASS | 0 unresolved |
| 11 | **P2-F** site diagnostic complete | 3 tests | PASS | 4 suspicious of 12,971 |
| 12 | **P2-G** no registration allocations | 4 tests | PASS | dependency graph clean |
| 13 | **P2-H** two capacity concepts separate | 4 tests | PASS | diverge by 10.69% |

**Criteria passed: 13/13.**

---

## 5. Test and coverage evidence (Gate part G-B)

```
$ make gate PHASE=2
--- 1. lint (ruff + mypy strict) ---      All checks passed! / 59 source files
--- 2. full test suite ---                528 passed, 1 skipped in 31.33s
--- 3. coverage thresholds ---            see below
--- 4. prior gate suites (Phase 0 and Phase 1) ---   passed; determinism: identical
--- 5. Phase 2 gate checks P2-A to P2-H ---          32 passed in 7.91s
--- 6. D3 copy lint ---                   copy lint: clean (94 files, 15 rules)
--- 7. determinism (semantic) ---         7 passed, 1 skipped
--- 8. one-command rebuild ---            16 models, 6 marts
=== Phase 2 gate: PASS ===
```

| Module | Statements | Missed | Branches | Partial | Cover | Required |
|---|---:|---:|---:|---:|---:|---|
| `pipeline/discovery/` | 663 | 0 | 194 | 0 | **100%** | 100% |
| `pipeline/model/` | 496 | 0 | 108 | 0 | **100%** | 100% |
| `pipeline/spatial/` | 285 | 0 | 70 | 0 | **100%** | 100% |
| `pipeline/quality/` | 287 | 0 | 64 | 0 | **100%** | 100% |
| `pipeline/schemas/` | 52 | 0 | 2 | 0 | **100%** | 100% |
| `pipeline/sources/` | 213 | 0 | 46 | 0 | **100%** | ≥85% |
| `pipeline/transform/` | 100 | 0 | 14 | 0 | **100%** | ≥85% |
| **Repository total** | **2,261** | **0** | **530** | **0** | **100%** | ≥70% |

**A gate defect was found and fixed during this phase.** The coverage checks were written
as `coverage report --fail-under=N | tail -2`. A shell pipeline returns the *last*
command's status, so `tail` masked every coverage failure and the threshold could never
fail the gate. It was caught because `pipeline/discovery/` reported 99% while the gate
still passed. The checks now capture output to a file and test the exit status
explicitly, and the previously hidden two uncovered statements — the new nested-JSON
probe branch — are now covered.

---

## 6. Regression against prior phases (Gate part G-C)

| Prior phase | Suite | Result |
|---|---|---|
| 0 | `test_source_findings.py` (23) + `test_smoke_forward.py` (13) + probe determinism | PASS |
| 1 | `test_domain_rules.py` G1–G14 (39) + `test_smoke_forward_phase2.py` (5) | PASS |

Six Phase 0/1 tests required updating because the amendments deliberately changed what
they asserted, not because they broke:

- three asserted the CSV shape of `afdc_charging_units`, now the JSON primary (A23);
- two pinned source and schema counts that grew (58 sources, 8 schemas);
- one pinned the probe spec kinds, which gained `nested_json_units`.

Each was updated to assert the *new* contracted truth, and two new tests were added: the
CSV fallback must still stage, and both representations must return the same row count
for one state. They do: **2,957 each for Minnesota**, an independent cross-check that the
representations carry the same data.

---

## 7. Forward viability (Gate part G-D)

### 7.1 Output contract

| Artifact | Grain | Guaranteed invariants | Consumed by |
|---|---|---|---|
| `mart_unit_capacity` | one charging-unit record | key unique; `port_count >= 1`; `generic_capacity_basis` from a closed vocabulary; capacity null where unresolved rather than guessed | 4 (candidates) |
| `mart_site_supply` | one site | `site_id` unique; generic and connector-compatible capacity in **separate** columns; `power_confidence_share` in [0,1] | 3 (D2 ablation only), 4, 6 |

### 7.2 Smoke-forward for Phase 3

Phase 3's core operation is tract-level EV propensity, reconciled to observed totals.
Its inputs are the Phase 1 registration marts and ACS demographics — **not** Phase 2's
supply outputs, because directive D2 forbids supply-derived features in the primary
demand model. The most useful smoke-forward for Phase 3 is therefore a *negative* one,
and it already exists as gate check **P2-G**: the Phase 2 dependency graph contains no
registration table, and by symmetry Phase 3's primary feature set must contain no supply
table. That test will be inverted and strengthened in Phase 3.

**What this proves:** the two halves of the pipeline are separable and currently
separated. **What it does not prove:** anything about the demand model, which does not
exist.

### 7.3 Assumption ledger additions

| ID | Assumption | Tested in | Status |
|---|---|---|---|
| A-2.1 | The 4 DBSCAN clusters exceeding 200 m diameter do not materially distort access metrics | Phase 4 | OPEN |
| A-2.2 | A 30-observation minimum makes rung-2 medians reliable | Phase 3 | OPEN |
| A-2.3 | Block-group population weighting is close enough to block-level for national access | Phase 4 | OPEN |
| A-2.4 | Straight-line distance is a usable lower bound for drive distance | E3 | OPEN |

---

## 8. Impact log delta

### 8.1 Opened this phase

| ID | Severity | Affected | Response |
|---|---|---|---|
| I-2 | **S3 Cosmetic** | Phase 1 report | "100.0% of stations" was a rounded 99.975%. Corrected by appended section; the 22 exceptions are now fully classified |
| I-3 | **S2 Degrading** | Phase 1 schema | `port_count == 1` was stated as a guaranteed invariant. Corrected to `>= 1` structural with `== 1` monitored as drift |
| I-4 | **S2 Degrading** | Phase 1 gate (`Makefile`) | Coverage thresholds piped through `tail`, so a failure could not fail the gate. Fixed; the previously hidden gap is now covered |

### 8.2 Resolved this phase

All three. I-2 and I-3 by amendment plus appended corrections to the Phase 1 report; I-4
by fixing the gate and re-running both Phase 1 and Phase 2 gates.

### 8.3 Still open

None.

---

## 9. Results and numbers

### 9.1 Power-resolution ladder, national

308,300 connector observations across 292,666 charging units.

| Rung | Source | Count | Share |
|---|---|---:|---:|
| 1 | `reported` | 247,088 | **80.15%** |
| 2 | `empirical_fallback` | 61,212 | **19.85%** |
| 3 | `type_default` | **0** | **0.00%** |
| — | `unresolved` | **0** | 0.00% |

**Rung 3 is never reached nationally.** Every connector lacking reported power falls into
a peer group meeting the 30-observation minimum; 164 groups qualify. The documented type
defaults are therefore precautionary rather than load-bearing in this snapshot — which is
worth stating plainly, because a reader could otherwise assume the cited default values
are shaping published numbers. They are not.

### 9.2 Capacity, national — the correction quantified

| Quantity | Value |
|---|---:|
| Charging units with at least one connector | 292,666 |
| Units exposing >1 connector standard on one port | **15,598** |
| **Generic service capacity** (non-overlapping) | **19,679,636 kW** |
| Naive connector sum | 21,783,878 kW |
| **Overstatement avoided** | **2,104,242 kW (10.69%)** |

Summing connector-level power as though every connector were an independently usable port
would have overstated national public charging capacity by **2.1 GW**. On the Minnesota
fixture the same effect is 9.5%.

The worked fixture, from the specification and now a test:

```
port_count = 1, CCS = 200 kW, CHAdeMO = 100 kW
  simultaneous_service_ports    = 1
  generic_service_capacity_kw   = 200      (NOT 300)
  CCS-compatible capacity       = 200
  CHAdeMO-compatible capacity   = 100
```

### 9.3 Access, national

239,780 population-weighted block-group centroids, total population 331,449,281.

| Metric | Threshold | Qualifying sites | Population in gap | Share | Median distance |
|---|---:|---:|---:|---:|---:|
| **DCFC access gap** | 16.1 km | 13,143 | **32,113,986** | **9.69%** | 3.30 km |
| **L2 access gap** | 8.05 km | 42,928 | **53,462,245** | **16.13%** | 2.11 km |

Sensitivity across the full 1–80 km sweep (80 points; selected):

| Threshold | DCFC gap population | L2 gap population |
|---:|---:|---:|
| 2 km | 232.3 M | 171.6 M |
| 5 km | 109.2 M | 80.4 M |
| 10 km | 55.6 M | 43.6 M |
| 16 km | 32.4 M | 25.3 M |
| 25 km | 15.6 M | 12.3 M |
| 50 km | 3.0 M | 2.2 M |
| 80 km | 0.7 M | 0.5 M |

The curve is why the single threshold cannot ship alone: the reported population moves by
two orders of magnitude across a defensible range, so choosing 16.1 km is a reporting
decision, not a finding. Both figures are **lower bounds**: straight-line distance never
exceeds road distance.

### 9.4 Preflight — the 22 station reconciliation exceptions

Unscoped reconciliation is **89,736 / 89,758 = 99.9755%**, never 100%.

| Classification | Count | Explanation |
|---|---:|---|
| `no_unit_records` | 12 | All `Status Code = P` (planned); nothing built, so no units and no totals |
| `legacy_charging_level` | 8 | Contain `legacy`-level units, which the L1/L2/DCFC aggregate does not count |
| `missing_station_aggregate` | 2 | Hold *only* legacy units, so report no aggregate at all |

**Zero unresolved.** Under the documented scope *"stations with at least one
charging-unit record and no legacy-level unit"*, reconciliation is **89,736 / 89,736 =
exactly 100.0000%**.

**Which source is authoritative for which metric:** charging-unit records are
authoritative for `simultaneous_service_ports`, because they carry the unit-level
`port_count` and include the legacy units the station aggregate omits. The station-level
L1/L2/DCFC fields are used only for cross-checking.

### 9.5 Preflight — site-resolution diagnostic

89,758 stations resolve to **59,232 clusters**; 46,261 (78.1%) are singletons.

| Measure | Value |
|---|---:|
| Multi-station clusters | 12,971 |
| Median diameter (multi-station) | **11.84 m** |
| Maximum diameter | 288.35 m |
| Clusters > 50 m | 886 (6.8%) |
| Clusters > 100 m | 86 (0.66%) |
| Clusters > 200 m | **4 (0.031%)** |
| Clusters > 500 m | **0** |

**Transitive chaining is real and measured.** DBSCAN connectivity means `eps = 50 m` does
not bound diameter: 886 clusters exceed it. But the effect is immaterial — the median
multi-station cluster spans 11.84 m, and only 4 clusters nationally exceed 200 m. All
four are single-network with near-unique station names (the largest: 117 stations, 117
distinct names, one network), which is the signature of a large parking structure or
campus where treating the stations as one site is arguably correct.

Four clusters out of 59,232 could shift a nearest-site distance by at most a few hundred
metres — well inside the 16.1 km threshold and its 1 km sensitivity step. **Verdict: rare
and immaterial, documented, no plan change.**

### 9.6 Population-weighted allocation, hand-computed fixture

A rural tract with 4,700 people, 4,500 of them in one corner:

| Cell | Population | Population weight | Allocated (of 1,000) | Area-weighted would give |
|---|---:|---:|---:|---:|
| town | 4,500 | 0.957447 | **957.4468** | 333.33 |
| farm 1 | 120 | 0.025532 | 25.5319 | 333.33 |
| farm 2 | 80 | 0.017021 | 17.0213 | 333.33 |

Conservation error 0.0. This is the case §7.6 exists for: area weighting would have put
two-thirds of the tract's quantity where almost nobody lives.

---

## 10. Limitations introduced or discovered

| Limitation | Effect | Mitigated? |
|---|---|---|
| Block-group, not block-level, population weighting | A block group averages ~1,380 people; in large rural block groups the same corner-population problem recurs at smaller scale | Declared; block-level is constructible from TIGER + P.L. 94-171 (Phase 0 F-7) and deferred |
| Straight-line distance | Understates real travel distance, so gap populations are lower bounds | Stated in the artifact's own `interpretation` field; isochrones are E3 |
| Multi-port units report no generic capacity | None exist in this snapshot, so the effect is currently zero | `multi_port_unresolved` basis is explicit and counted |
| 4 clusters exceed 200 m diameter | Could shift a nearest-site distance by a few hundred metres | Quantified as immaterial; assumption A-2.1 |
| Rung-3 defaults are untested in production | Never exercised nationally, so their values rest on cited reasoning rather than observed behaviour | Each carries a citation; a source change could make them load-bearing without warning |
| Site public/operational status is "any station" | A site with one public station and nine private ones counts as public | Declared; `public_operational_stations` is carried on the mart |

---

## 11. Specification compliance

| Directive | Enforcement | Verified by |
|---|---|---|
| **D1** No temporal leakage | Not yet exercised; no backtest until Phase 5 | — |
| **D2** No supply-to-demand loop | Phase 2 reads no registration table; `FORBIDDEN_INPUT_TABLES` is asserted | P2-G, 4 tests |
| **D3** Three validation terms | Copy lint, 15 rules, 94 files | `test_the_repository_itself_is_clean` |
| **D4** Zero recurring cost | Every new source is a free Census bulk file needing no key | — |
| **D5** Greenfield | No prior implementation consulted | — |
| **D6** Grid proximity language | No substation module exists (A6); lint rules D6-GRID-01..05 | copy lint clean |
| **D7** Uncertainty first-class | Every resolved power carries `power_source` and `power_confidence`; every site carries `power_confidence_share` | schema `Check.isin` |
| **D8** Explicit degradation | Unresolvable power reported as `unresolved`, not guessed; sites without coordinates skipped, not placed at a default; no-sites-anywhere is an infinite gap, not a dropped record | 6 tests |

**Deviations:** none beyond the authorised amendments A17–A24.

---

## 12. Open questions for the reviewer

**Q1. Rung 3 is never reached.** The documented type defaults did not fire once across
308,300 national observations, because rung 2 always found a qualifying peer group. That
is a good outcome, but it means the rung-3 values have never been exercised against real
data and rest purely on cited engineering reasoning. **Is that acceptable, or would you
prefer the rung-2 minimum sample raised** (which would push some resolution down to rung 3
and exercise it) **or a deliberate test that forces rung-3 resolution on a real subset?**
I lean toward leaving it: rung 2 is genuinely better evidence than a default, and
suppressing it to exercise a fallback would be backwards.

**Q2. Site public/operational status uses "any station".** A site is treated as public
operational supply if *at least one* of its stations is. The alternative is requiring all
of them. With G4 aggregating co-located multi-network infrastructure, a site can mix a
public ChargePoint station with a private fleet depot. **Is "any" the right rule for
access**, given that a driver genuinely can charge there, even though site-level capacity
then includes ports they cannot use? A stricter alternative would count only the
public-operational units' capacity.

**Q3. Block-group population weighting.** §7.6 asks for block-level weights; the finest
ready-made product is block group. Constructing block-level means downloading TIGER
`TABBLOCK20` (roughly 150 MB per state) plus P.L. 94-171 for all 51 jurisdictions.
**Should Phase 4 construct genuine block-level weights before national access figures are
published**, or is block-group sufficient given that the sensitivity curve already spans
the range where the choice would matter?

---

## 13. Next phase readiness

| Check | Status |
|---|---|
| All acceptance criteria passed | 13/13 |
| Coverage thresholds met | 100% line and branch, 2,261 statements |
| All prior gates passing | Phase 0 and Phase 1 re-run, PASS |
| Smoke-forward passing | P2-G is the Phase 3 negative check |
| Report complete and self-contained | Yes |
| No S1 impacts open | None open at any severity |

**Recommendation: PROCEED to Phase 3 (Demand + uncertainty).** Phase 3's inputs are the
Phase 1 registration marts, ACS demographics, and the crosswalk machinery Phase 1 built
and Phase 3 must now validate via the Washington round-trip. Phase 2's supply outputs are
available to Phase 3 **only** for the explicitly labelled D2 ablation, never for the
primary demand model.

---

## Corrections

## Correction — 2026-08-26 (mixed public/private sites)

Required by the project owner's review of this report. Phase 2 remains **PASS**; this
corrects how public capacity and level qualification are computed at sites that mix
public and private infrastructure. The text above is preserved unedited.

**What was wrong.** Domain rule G4 aggregates co-located multi-network stations into one
site, so a site can hold a public ChargePoint station *and* a private fleet depot. The
original implementation treated a site as public operational supply if **any** of its
stations was, and then counted **all** of its capacity as public. It also qualified a
site for DCFC access if the site had some public station and some DCFC station — which
can be *different stations*. A driver cannot use a private DC charger.

**The corrected rule.** Three separate statements, each now enforced:

1. **Public site existence** — a site offers public operational service when at least
   one unit is simultaneously public *and* operational.
2. **Public capacity** — only units that are simultaneously public and operational
   contribute to `public_generic_service_capacity_kw` and
   `public_connector_compatible_kw`. Private and out-of-service capacity is still
   tallied, in separate all-units columns, and never added to the public totals.
3. **Level qualification** — a site qualifies for DCFC (or L2) only if a **public
   operational unit** offers that level, evaluated on `public_ports_by_level`.

```python
# pipeline/model/supply.py
def qualifies_for_level(self, levels: frozenset[str] | set[str]) -> bool:
    """True when a PUBLIC OPERATIONAL unit offers one of these charging levels.

    Deliberately not "site has a public station and site has a DCFC station":
    those can be different stations, and a driver cannot use a private DC charger.
    """
    return any(self.public_ports_by_level.get(level, 0) > 0 for level in levels)
```

**Before and after, national:**

| Figure | Before | After | Delta |
|---|---:|---:|---:|
| Generic service capacity | 19,679,636 kW (all units) | **19,001,862 kW** (public only) | **−677,774 kW (−3.44%)** |
| DCFC qualifying sites | 13,143 | **13,079** | −64 |
| DCFC access gap population | 32,113,986 (9.69%) | **32,169,758 (9.71%)** | +55,772 |
| L2 qualifying sites | 42,928 | **42,861** | −67 |
| L2 access gap population | 53,462,245 (16.13%) | **53,584,530 (16.17%)** | +122,285 |

The 64 sites that lost DCFC qualification are exactly the case the correction exists
for: each had a public station and a DC fast station, but no unit that was both.
677,774 kW of private or out-of-service capacity is no longer reported as public.

Every other Phase 2 figure is unchanged, including the power-ladder distribution and the
10.69% connector double-counting overstatement, because neither depends on public status.

**Also corrected in this pass:**

- **The "lower bound" claim was too strong.** Section 9.3 described the access-gap
  population as a lower bound. Straight-line distance is a lower bound on network
  distance *for each representative point*, but because each block group is represented
  by one population-weighted point, the aggregate is an **approximation** and is not
  guaranteed to bound the true population lacking road access. The artifact's own
  `interpretation` field now says so, and a stratified block-level benchmark is required
  before publication.
- **Assumption A-2.2 was pointed at the wrong phase.** Rung-2 validation is a *supply*
  method question and does not belong in the Phase 3 demand model. It is now a **Phase 4
  prerequisite**, to be validated by masked-power evaluation holding out entire stations
  or sites rather than random connector rows.
- **Rung 3 at 0% is accepted as-is.** It is not forced merely to exercise it; synthetic
  tests cover it instead. This answers open question Q1 in section 12.

New gate check **P2-I** covers the mixed-site rule. The Phase 2 gate was re-run after
these changes.
