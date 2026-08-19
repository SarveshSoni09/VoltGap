# CLAUDE.md — VoltGap Implementation Specification

> This file is the authoritative specification for this repository. Read it fully before
> writing any code. Where this document conflicts with your own judgment about what
> "a normal EV dashboard" looks like, this document wins. Several requirements here exist
> specifically to prevent failure modes that look correct in output but are wrong.

---

## 0. Prime directives

These are non-negotiable. Violating any one of them invalidates the project.

**D1. No temporal leakage in retrospective evaluation.** Any feature used in a backtest
must carry a `feature_vintage` and the harness must assert
`feature_vintage <= prediction_cutoff` at runtime, raising on violation. This is a hard
check in code, not a convention. See §10.2.

**D2. No supply-to-demand feedback loop.** Existing charger density, charger counts,
charging network presence, and any feature derived from installed infrastructure are
**excluded from the primary demand model**. They may appear only in a clearly labeled
ablation. Rationale: existing infrastructure is an outcome of prior investment decisions.
Using it to predict demand, then using that demand to site new infrastructure, launders
historical deployment patterns into "need" and systematically suppresses underserved
areas, which are precisely what this system exists to find.

**D3. Three distinct validation terms, used consistently everywhere.** Never blur them in
code, docs, UI copy, or commit messages.

| Term | What it evaluates | Method |
|---|---|---|
| **Demand model validation** | Whether tract-level EV estimates are accurate | Leave-one-state-out against observed states |
| **Historical deployment alignment** | Whether priority areas match where industry actually built | Vintage-enforced rolling-origin backtest |
| **Cross-objective robustness** | Whether a portfolio optimized for one objective also performs on others | ε-constraint Pareto analysis |

None of these demonstrates that a site is objectively optimal. No code comment, docstring,
or UI string may claim optimality validation. Ground truth for optimal siting does not exist.

**D4. Zero recurring cost.** No paid API, no managed database, no paid tile host, no LLM as
a required dependency. Free tiers only, with quotas documented in `SOURCES.yml`.

**D5. Greenfield.** There is no prior version of this project to match, extend, or compare
against. Design the information architecture from the requirements in this document.

**D6. Language discipline on grid claims.** Use "grid proximity" or "interconnection proxy".
Never "grid feasible", "interconnection ready", or "grid capacity available". Substation
distance says nothing about hosting capacity, feeder availability, transformer headroom, or
make-ready cost.

**D7. Uncertainty is a first-class output.** Every modeled quantity carries an uncertainty
score. No point estimate ships without it. No composite index ships without a weight
sensitivity control.

**D8. When a source is unavailable, degrade explicitly.** Never substitute a plausible
default silently. Every fallback is flagged in the data and surfaced in the UI.

---

## 1. What is being built

**VoltGap** is an open, statically hosted decision-support application that answers:
*given a budget and a set of policy priorities, where should the next EV charging
infrastructure be built in the United States, and how confident should we be in that
answer?*

**Users:** infrastructure planners, charge point operators, state energy offices,
researchers.

**Primary output:** a ranked, budget-feasible portfolio of candidate hexagonal sites with
scores, uncertainty bands, tradeoff context, and CSV/GeoJSON export.

**Explicitly not goals:** a general EV statistics browser, a consumer charger finder, a
vehicle comparison tool, a real-time charger availability map.

### 1.1 Vocabulary

Use these terms exactly. They are distinct entities in the data model (§6.1).

| Term | Definition |
|---|---|
| **Site** | A physical location where charging occurs. May contain multiple stations from multiple networks. |
| **Station** | An AFDC station record. One network's presence at a site. |
| **Charging unit / EVSE** | A physical cabinet or pedestal. |
| **Port** | An outlet that can serve one vehicle at a time. |
| **Connector** | The plug standard on a port (J1772, CCS, CHAdeMO, J3400/NACS, J3271). |
| **DCFC access gap** | A location beyond a configured drive distance or time from operational public DC fast charging. Not "charging desert" unless the measure includes Level 2. |

---

## 2. Hard constraints

| Constraint | Value |
|---|---|
| Recurring cost | 0 USD |
| Hosting | Static export only. No serverless functions in Core. |
| National spatial unit | H3 resolution 6 |
| Metro spatial unit | H3 resolution 8, top 50 CBSAs, lazy loaded |
| Basemap | OpenFreeMap primary, self-hosted Protomaps on R2 as fallback. No keyed provider. |
| Large artifacts | Cloudflare R2, HTTP range requests |
| Optimizer (offline) | PuLP + CBC |
| Optimizer (interactive) | Greedy marginal gain in a Web Worker |
| Python | 3.11+, `uv` for dependency management |
| Frontend | Next.js static export, TypeScript strict, MapLibre GL JS, deck.gl, PMTiles |
| Warehouse | DuckDB, file-based, no server |
| Validation | pandera schemas, build fails on violation |

---

## 3. Repository layout

```
voltgap/
├─ CLAUDE.md                      this file
├─ README.md
├─ pyproject.toml
├─ SOURCES.yml                    the data contract, see §4
├─ pipeline/
│  ├─ config/
│  │  ├─ settings.py              typed settings, no magic numbers elsewhere
│  │  ├─ thresholds.yml           all configurable analytic thresholds
│  │  └─ power_defaults.yml       connector power fallback ladder values
│  ├─ sources/                    one module per source, uniform interface
│  │  ├─ base.py                  Source ABC, caching, retry, vintage stamping
│  │  ├─ afdc_stations.py
│  │  ├─ afdc_charging_units.py
│  │  ├─ census_acs.py
│  │  ├─ census_tiger.py
│  │  ├─ census_blocks.py         population-weighted centroids
│  │  ├─ nrel_home_charging.py
│  │  ├─ eia_prices.py
│  │  ├─ egrid.py                 Optional/Future Work tier, see §7.12
│  │  ├─ hifld_substations.py
│  │  ├─ hifld_transmission.py
│  │  ├─ cejst_archive.py
│  │  ├─ state_ev_registrations/  one module per Tier A state
│  │  └─ fhwa_traffic.py           Optional/Future Work tier, see §7.13
│  ├─ discovery/
│  │  └─ probe.py                 Phase 0 schema discovery, writes SOURCES.yml
│  ├─ schemas/                    pandera schemas, one per canonical table
│  ├─ transform/
│  │  ├─ models/                  DuckDB SQL, staging → intermediate → marts
│  │  └─ runner.py
│  ├─ spatial/
│  │  ├─ h3_grid.py
│  │  ├─ allocation.py            block-level population allocation
│  │  └─ distance.py
│  ├─ model/
│  │  ├─ supply.py
│  │  ├─ home_charging.py
│  │  ├─ demand.py
│  │  ├─ reconcile.py
│  │  ├─ uncertainty.py
│  │  ├─ access.py
│  │  ├─ queueing.py              Extension tier
│  │  ├─ forecast.py              Extension tier
│  │  ├─ siting.py
│  │  └─ economics.py             Optional tier
│  ├─ validation/
│  │  ├─ demand_model.py          leave-one-state-out
│  │  ├─ deployment_alignment.py  vintage-enforced backtest
│  │  ├─ vintage.py               the leakage guard, see §10.2
│  │  └─ robustness.py            ε-constraint cross-objective
│  └─ export/
│     ├─ parquet.py
│     ├─ tiles.py                 tippecanoe wrappers
│     └─ manifest.py
├─ web/
│  ├─ app/                        Next.js app router, static export
│  ├─ components/
│  ├─ lib/
│  │  ├─ data/                    Arrow/Parquet loaders, R2 clients
│  │  ├─ optimizer/               greedy solver, Web Worker
│  │  └─ h3/
│  └─ public/
├─ docs/
│  ├─ METHODOLOGY.md
│  ├─ DATA_DICTIONARY.md
│  ├─ DATA_GOTCHAS.md             see §5
│  ├─ LIMITATIONS.md
│  ├─ VALIDATION.md
│  └─ FUTURE_WORK.md              anything that tempts a redesign goes here
├─ tests/
│  ├─ unit/
│  ├─ integration/
│  ├─ regression/                 locks the domain rules in §5
│  └─ fixtures/
└─ .github/workflows/
   ├─ ci.yml
   ├─ etl.yml                     scheduled + workflow_dispatch
   └─ keepalive.yml               see §13.3
```

---

## 4. Phase 0: the source contract

**Do not design any model before this phase completes.** Two errors were already made in
the design process by assuming external data shapes. Verify everything.

### 4.1 `SOURCES.yml` schema

Every source gets an entry with all of these fields. A source with unverified fields cannot
be used by a Core model.

> **Amended 2026-08-19 (§19 A0).** The contract and its live measurements are stored in two
> files, not one: `SOURCES.yml` holds the stable, human-reviewed contract, and the generated
> sidecar `SOURCES.observed.json` holds volatile observations — observed row count, observed
> schema, schema hash, missingness, last successful retrieval, observed rate-limit behaviour,
> current vintage, retrieval metadata, and the probe-assigned `status`. Keeping them together
> made every live refresh dirty the reviewed file and made expectation indistinguishable from
> observation. Downstream tooling merges the two programmatically. The field list below still
> defines what must exist; it is split across the two files.

```yaml
- id: afdc_charging_units
  name: NREL AFDC EV Charging Units
  status: confirmed | degraded | unavailable      # set by probe.py
  retrieval:
    method: rest_api | bulk_download | scrape
    endpoint: "..."
    auth: api_key_free | none
    rate_limit: "1000 req/hour"
    last_successful_retrieval: "2026-08-18T00:00:00Z"
  coverage:
    geographic: "US 50 states + DC + PR"
    temporal: "current snapshot"
    historical_vintages_available: false          # critical for backtest eligibility
    vintage_field: null
  schema:
    discovered_fields: [...]                       # written by probe.py, verbatim
    join_keys: [station_id, unit_id]
    stable_keys: true
  quality:
    expected_row_count: [70000, 95000]
    observed_row_count: 79618
    missingness: { power_kw: 0.34, port_count: 0.02 }
  license: "public domain"
  update_cadence: "daily"
  fallback_source: afdc_stations_bulk_csv
  used_by: [supply, access, deployment_alignment]
  backtest_eligible: false                         # derived from historical_vintages_available
```

### 4.2 Phase 0 tasks

1. Implement `pipeline/discovery/probe.py`. For each source: fetch a bounded sample, dump
   the live schema verbatim, count rows, compute per-field missingness, record the vintage,
   measure the rate limit empirically, write the entry to `SOURCES.yml`.
2. **Verify AFDC charging units endpoint.** Confirm whether per-connector `power_kw` and
   `port_count` are present, and measure their missingness. The supply model's power ladder
   (§7.1) depends on this. Do not design the ladder before measuring.
3. **Verify the NREL county home charging access dataset.** Determine whether the county
   shares are present-day values or 2030 scenario projections. If they are 2030 projections,
   record that as a vintage mismatch and set `home_charging.calibration_target_valid: false`,
   which triggers the fallback path in §7.2.
4. **Search for historical state EV registration vintages.** Check Atlas EV Hub archives,
   state DMV historical releases, and the IEA national stock series. This determines whether
   the demand reconciliation constraint can be applied at backtest cutoffs (§10.2.3).
   Record findings in `SOURCES.yml` under `historical_vintages_available`.
5. **Enumerate Tier A states.** Identify every state with usable open sub-state EV
   registration data. Do not assume a count. Record each as a separate source entry with its
   geographic granularity (county or tract) and temporal coverage.
6. Write `docs/SOURCE_VERIFICATION.md` summarizing confirmed, degraded, and unavailable
   sources, and list every Core model affected by a degraded or unavailable source.

**Phase 0 acceptance:** `SOURCES.yml` is complete for every source, `probe.py` is
re-runnable and idempotent, and every Core model in §7 has a documented data path or a
documented fallback.

---

## 5. Domain rules for the source data

These are properties of the upstream data, not preferences. Each one gets a regression test
in `tests/regression/`. Write them into `docs/DATA_GOTCHAS.md` as domain rules.

| ID | Rule |
|---|---|
| G1 | AFDC station records are **sites of one network's presence**, not ports. A record with one Level 2 plug and a record with forty DC fast stalls are both one row. Never count rows as capacity. |
| G2 | `Status Code` has three values: `E` available, `T` temporarily unavailable, `P` planned. Operational supply is `E` only. In the Dec 2024 snapshot that is 73,972 of 79,618. |
| G3 | `Access Code` includes `private` (4,662 of 79,618 in the Dec 2024 snapshot). Private stations are not public supply. |
| G4 | Exact coordinate duplicates exist (1,756 pairs in the Dec 2024 snapshot). These are usually **co-located multi-network infrastructure, not duplicate records**. Aggregate them into one site for coverage. Sum their ports for capacity. Do not delete them. |
| G5 | The IEA global dataset contains three `category` values for the USA: `Historical`, `Projection-STEPS`, `Projection-APS`. STEPS and APS are **alternative scenarios**. Summing them double counts. Any query touching IEA projections must filter `category` explicitly. |
| G6 | IEA projection years for the USA are only 2025, 2030, 2035. Do not interpolate silently. |
| G7 | IEA `mode` has four values (Cars, Buses, Trucks, Vans). Stacking all four is valid only when the intent is total fleet. |
| G8 | AFDC state registration counts are **stock, not sales**. Never label them "EV sales". The file contains a `Total` row that must be excluded before any aggregation. |
| G9 | **State registration vintage and plausibility validation.** Each ingested state-registration dataset must resolve to a documented vintage, jurisdiction coverage must be complete for the claimed geography, counts must be non-negative, and jurisdiction totals must reconcile to the published total where one exists. The delivered seed file resolves consistently to the 2023 AFDC vintage across all 51 jurisdictions. Per-capita and year-over-year anomaly screening must be run as a diagnostic quality check, but an anomalous state is **flagged for review rather than automatically marked low-confidence**. A low-confidence designation requires corroborating evidence of a vintage, coverage, definition, or source-quality problem. *(Amended 2026-08-19 — see §19 A1. The original G9 asserted Oregon reports 6,436 and that vintages differ across states; the delivered file records Oregon at 64,361 and is one consistent 2023 vintage.)* |
| G10 | `Open Date` ranges 1995 to present but AFDC documents that some dates are approximate and, for automated network feeds, may reflect first appearance in the Station Locator rather than actual opening. |
| G11 | A current snapshot plus `Open Date` does **not** perfectly reconstruct a historical network. Stations that closed, were removed from the feed, changed port counts, or were power-upgraded are invisible. Reconstruction is survivorship-biased, and the bias grows with age. |
| G12 | The HIFLD transmission GeoJSON is ~138 MB and ~94,216 features. It must be filtered by voltage and tiled. Never load it in a browser as GeoJSON. |
| G13 | County names collide across states (both Minnesota and Illinois have a Cook County). Join on FIPS, never on name. |
| G14 | `EV Connector Types` in the bulk CSV is a space-delimited concatenated string, not a normalized field. |

---

## 6. Canonical data model

### 6.1 Infrastructure entity hierarchy

Model all five levels. Do not collapse them.

```
site (spatial cluster of co-located infrastructure)
 └─ station (AFDC record: one network's presence at the site)
     └─ charging_unit (EVSE cabinet)
         └─ port (one vehicle at a time)          <- identity must be EARNED, see below
             └─ connector (J1772 | CCS | CHAdeMO | J3400 | J3271)
```

`site_id` is derived by spatial clustering of station coordinates (DBSCAN, eps ≈ 50 m),
**not** by rounding coordinates. Rounding creates arbitrary grid-boundary splits.

#### 6.1.1 Physical identity must not be manufactured — at any level

The AFDC charging-units export supplies **per-connector counts and power**, not individually
identified physical objects. Creating rows named `port_001`, `port_002` … and assigning
connectors to them would fabricate observed physical objects that the source never reported.

**This applies to charging units and connectors, not only to ports.** Measurement over the
full national export (292,435 rows, 2026-08-19) established:

- the export carries **no charging-unit identifier column**; `ID` is the *station* parent key,
  and 89,687 station IDs span 292,435 unit rows;
- **65.9% of rows are byte-identical duplicates** of another row (265,836 rows, 90.9%,
  participate in an identical group; the largest group is 410 rows), so rows cannot be told
  apart by their content;
- but row count reconciles to the station's reported L1+L2+DCFC totals for **100.0% of
  stations** (89,665 of 89,687), so the export is genuinely one row per EVSE and the duplicate
  rows are *real distinct physical units that are indistinguishable in every reported
  attribute* — the same situation as domain rule G4 for coordinate duplicates.

**Therefore `charging_unit_id` must not be defined as a stable physical identifier.** Until
Phase 1's investigation proves otherwise, distinguish three separate things and never conflate
them:

| Concept | Status |
|---|---|
| `station_id` | The **parent key**. Genuine, stable, source-provided |
| `charging_unit_record_key` | A **synthetic, per-snapshot source-row key**. Not a physical identifier. Carries no longitudinal meaning and must never be used to track a unit across refreshes |
| physical unit identity | **Not available** unless Phase 1 recovers it, including via network metadata |

**Phase 1 must run an identifiability analysis at all three levels — charging unit, port, and
connector — before the canonical schema is frozen**, measuring:

1. how often unit-level `port_count` is available;
2. how often stable, network-provided port identifiers are available;
3. whether connector-specific counts map unambiguously to physical ports;
4. how often `sum(connector-specific counts) > charging_unit.port_count`, which indicates one
   physical port exposing multiple connector types;
5. what share of national and of public-operational infrastructure supports true individual
   port identity;
6. what share supports only aggregate charging-unit capacity;
7. whether **any stable charging-unit identity** is recoverable from the export or from
   network metadata, and if so for what share of infrastructure;
8. whether identical duplicate rows can be distinguished from one another by any means other
   than row order.

**Canonical model rule.** If physical port identity is not recoverable from the source, the
honest hierarchy stops at `charging_unit`:

```
site → station → charging_unit
    with: port_count, connector-specific port counts, reported power, aggregate capacity
```

**Connector grain.** Do not create individual physical `connector_id` rows from connector
*counts*. AFDC exposes connector-type counts and power associated with a charging unit, not
identified connectors. Unless actual connector identity exists, model connectors at the grain:

```
(charging_unit_record_key, connector_type) -> connector_count, power_kw, power_source, provenance
```

Create rows in `ports` and `connectors` **only where identity is genuinely supported by the
source.** Where a row-per-port expansion is needed for a specific mathematical operation, label
it explicitly as a *computational representation*, never as observed physical identity, and
keep it out of any published table that a reader would take as a physical inventory.

If no physical unit identity exists, the synthetic source-row key ships with its limitations
documented in `docs/DATA_DICTIONARY.md`, and **no longitudinal physical-unit identity is
claimed anywhere** — not in code, not in a schema comment, not in the UI.

### 6.2 Core tables

| Table | Grain | Key |
|---|---|---|
| `sites` | one row per physical location | `site_id` |
| `stations` | one row per AFDC record | `station_id` |
| `ports` | one row per port, **only where source identity supports it** (§6.1.1) | `port_id` |
| `charging_units` | one row per EVSE cabinet, carrying `port_count`, reported power, aggregate capacity | `charging_unit_record_key` (**synthetic, per-snapshot; not a physical identifier** — §6.1.1), parent `station_id` |
| `charging_unit_connectors` | one row per (unit record, connector type) | `(charging_unit_record_key, connector_type)` with `connector_count`, `power_kw`, `power_source`, provenance |
| `tracts` | one row per census tract | `geoid` |
| `blocks_pop` | population-weighted centroids | `block_geoid` |
| `hex6` | national H3 res 6 | `h3_index` |
| `hex8_metro` | H3 res 8, top 50 CBSAs | `h3_index` |
| `substations` | HIFLD | `substation_id` |
| `state_totals` | EV stock by state and vintage | `(state, vintage)` |
| `observed_subregion_ev` | Tier A registrations | `(geoid, vintage)` |

Every derived table carries: `computed_at`, `source_vintages` (map of source id to vintage),
and where applicable `confidence_score` and `confidence_tier`.

---

## 7. Model specifications

### 7.1 Supply model — `pipeline/model/supply.py`

```python
def build_supply(
    stations: pd.DataFrame,
    charging_units: pd.DataFrame | None,
    power_defaults: PowerDefaults,
) -> SupplyResult:
    """Compute port-level supply with an explicit power-resolution ladder."""
```

**Power resolution ladder.** Every port carries `power_kw`, `power_source`, and
`power_confidence`.

| Rung | Source | `power_source` | Confidence |
|---|---|---|---|
| 1 | Reported connector or unit `power_kw` from the AFDC charging units endpoint | `reported` | high |
| 2 | Empirically derived median for the same `(network, connector_type)` combination, computed from rung 1 records | `empirical_fallback` | medium |
| 3 | Documented type default from `power_defaults.yml` | `type_default` | low |

Do not hard-code power values in Python. All defaults live in `power_defaults.yml` with a
cited justification comment per value. Phase 0 measures rung 1 missingness; if rung 1
coverage is below 40 percent, record that prominently in `docs/LIMITATIONS.md`.

**Filters applied to public operational supply:** `Status Code == 'E'` (G2) and
`Access Code == 'public'` (G3).

**Aggregation:** for spatial coverage, collapse to `site_id` (G4). For capacity, sum ports
across all stations at the site.

Outputs per hex: `port_count_l1`, `port_count_l2`, `port_count_dcfc`, `capacity_kw`,
`site_count`, `power_confidence_share` (share of capacity from rung 1).

### 7.2 Home charging access — `pipeline/model/home_charging.py`

```python
def fit_home_charging_downscale(
    acs_tracts: pd.DataFrame,
    nrel_county_shares: pd.DataFrame | None,
) -> HomeChargingModel:
    """Fit tract-level ACS features to county-level modeled home charging access shares."""
```

**Primary path.** Fit a tract-level model on ACS features (tenure B25003, units in structure
B25024, vehicles available B25044, density, income) with the NREL county home charging access
shares as the calibration target. Constrain population-weighted tract predictions to
reproduce county values.

**This is a downscaling model of NREL's estimates, not an independent measurement.** State
that verbatim in `docs/METHODOLOGY.md`. Validation is leave-one-county-out on downscaling
fidelity, reported as such. It demonstrates that tract predictions aggregate correctly to
the target, not that either the target or the predictions are correct against ground truth.

**Fallback path — TRIGGERED. This is settled, not a Phase 3 decision.** The fallback applies
if Phase 0 finds the NREL dataset unavailable, determines it to be a 2030 scenario projection
rather than current values, **or determines it to be a parametric scenario surface rather than
a dated current observation**. Phase 0 established the third condition: the dataset is
942,600 rows = 3,142 counties × 3 access scenarios × 100 levels of an `EV Share of Stock`
parameter running 0.01 to 1.00. Home charging access is published as a *function of assumed
fleet penetration*, not as an observation of any date.

Selecting the EV-share slice nearest today's penetration would still be a modelling choice,
and must not be presented as a present-day observed measurement. Therefore:
- Ship home charging access as an **exploratory index**, clearly labeled.
- **Exclude it from the primary siting objective function.**
- Expose it only as a user-selectable weight with a sensitivity display.
- Never publish weights that were chosen by hand as if they were calibrated.

Do not invent coefficients. If it is not fit to something, it does not enter the objective.

**Do not reopen this in Phase 3.** Any future attempt to promote home charging access into
the primary objective belongs in `docs/FUTURE_WORK.md`, unless new empirical data materially
changes the source situation.

### 7.3 Demand model — `pipeline/model/demand.py` and `reconcile.py`

```python
def estimate_ev_propensity(
    tracts: pd.DataFrame,
    observed: pd.DataFrame,
    feature_set: FeatureSet,
) -> PropensityModel:
    """Model tract-level EV propensity from demographics. Supply features are forbidden."""
```

**Feature set (primary model).** Median household income, income distribution, housing
tenure, units in structure, vehicles available per household, population density, commute
distance and mode, urban/rural classification, educational attainment, home charging access
(if §7.2 primary path succeeded).

**Forbidden features (D2).** Charger count, port count, charger density, network presence,
distance to nearest charger, or any transform thereof. These are available only via
`FeatureSet.ablation_supply_features = True`, which must be logged and reported separately.

**Reconciliation.** Tract estimates must reconcile exactly to reliable county totals where
they exist and to state totals everywhere else.

**Do not hard-code the estimator.** IPF, raking, hierarchical proportional reconciliation,
and other constrained estimators are all candidates. Choose based on the data structure
discovered in Phase 0, implement behind a common interface in `reconcile.py`, and document
the choice with the reason in `docs/METHODOLOGY.md`.

```python
class Reconciler(Protocol):
    def reconcile(
        self, tract_estimates: pd.Series, constraints: list[Constraint]
    ) -> ReconciledEstimates: ...
```

### 7.4 Uncertainty — `pipeline/model/uncertainty.py`

Every modeled tract carries a **continuous** score with these components:

1. **Prediction interval width** from the propensity model (bootstrap or quantile).
2. **Out-of-distribution score**: Mahalanobis distance in feature space from the sub-state
   anchored training distribution, or an isolation-forest score. Tracts unlike any anchored
   state get high uncertainty regardless of geography.
3. **Constraint slack**: how much the reconciliation step moved the raw estimate.
4. **Source degradation**: penalty for inputs marked degraded in `SOURCES.yml`.

5. **Geographic transformation penalty.** How far the tract value is from directly observed
   evidence. Ordering, subject to empirical validation:
   `native tract observation < high-quality ZIP→tract allocation < county→tract allocation <
   state-total-only model`. **Do not hard-code numeric penalties.** Measure transformation
   quality where possible (§7.4.2) and derive the penalty from the measurement.

#### 7.4.1 Two orthogonal status fields — never collapse them

Phase 0 found that only Washington publishes registrations at census-tract grain; 11 states
publish at ZIP and 4 at county. A tract estimate built from ZIP or county observations is
*anchored* to observed sub-state data, but the tract value itself is **not directly
observed**. The data model must not imply otherwise.

Every tract estimate therefore carries **two independent fields**:

**A. `evidence_grain`** — the finest actual observed registration evidence supporting it.

| Value | Meaning |
|---|---|
| `native_tract` | Registration data observed at census-tract grain for this tract |
| `zip_anchored` | Observed at ZIP/ZCTA grain, allocated to this tract |
| `county_anchored` | Observed at county grain, allocated to this tract |
| `state_total_only` | No sub-state observation; the tract value rests on a state total plus the propensity model |

**B. `estimate_method`** — what was done to produce the tract value.

| Value | Meaning |
|---|---|
| `directly_observed` | The source reports this tract |
| `crosswalked` | Spatially or proportionally allocated from a coarser observed geography |
| `modeled` | Produced by the propensity model |
| `modeled_high_uncertainty` | Modeled, above the documented uncertainty threshold |

These are **not** to be collapsed into a single A/B/C label internally. The continuous
uncertainty score remains computationally primary; the tier is a presentation layer only.

#### 7.4.2 Presentation tiers

Tiers are a presentation layer over the continuous score, defined by documented thresholds
in `thresholds.yml`. **Tier is never geography-based.**

| Tier | Label | Definition |
|---|---|---|
| A | **sub-state anchored** | `evidence_grain` is not `state_total_only`: some observed sub-state registration evidence supports this tract |
| B | modeled | `evidence_grain == state_total_only`, continuous uncertainty score below the B/C threshold |
| C | low confidence | Continuous uncertainty score above the B/C threshold |

**Tier A must never be labelled "observed" in the UI or in code**, because most Tier A tracts
are ZIP- or county-anchored rather than directly observed. Use "sub-state anchored".

Every aggregate displayed in the UI reports the share of underlying demand that is sub-state
anchored versus modeled, and the breakdown of `evidence_grain` beneath it.

### 7.5 Access — `pipeline/model/access.py`

```python
def compute_access(
    population_points: gpd.GeoDataFrame,  # block-level, population-weighted
    sites: gpd.GeoDataFrame,
    thresholds: AccessThresholds,
) -> AccessResult:
```

- Use **population-weighted centroids** or block-level allocation. Do not use tract
  geometric centroids. In large rural tracts the population often occupies one corner.
- Distance to nearest operational public DCFC site, and separately to nearest public L2 site.
- Thresholds live in `thresholds.yml`, are exposed in the UI, and ship with a sensitivity
  analysis showing how the affected population changes across the threshold range.
- Name the metric for what it measures. If it covers DCFC only, it is a **DCFC access gap**.
- Drive-time isochrones (OSMnx, computed offline) are **Extension tier**, top metros only.
  Core ships network-free distance with the limitation stated.

### 7.5.1 Geographic reconciliation of observed registrations — **required, not a lookup**

Most sub-state registration sources Phase 0 found are keyed by **postal ZIP Code**. A USPS
ZIP Code is a mail-delivery route collection, not an area; a Census ZCTA is an approximating
area. **They are not interchangeable and must never be silently equated.** Converting either
to census tracts is a modelling and data-integration step with measurable error, not a
one-to-one crosswalk.

Every pipeline path that moves registration counts between geographies must:

1. **Identify the source geography explicitly** — USPS ZIP Code, Census ZCTA, county, tract,
   or other — recorded per source in `SOURCES.yml`. Never inferred from column naming.
2. **Name the crosswalk source and its vintage** in the data and in
   `docs/DATA_DICTIONARY.md`.
3. **Use weighted allocation**, not one-to-one lookup, wherever the source geography does not
   nest inside the target. Weights must themselves be documented (population, housing units,
   address count).
4. **Preserve the transformation method on every resulting estimate** via `evidence_grain`
   and `estimate_method` (§7.4.1).
5. **Measure allocation ambiguity or error where feasible.** Washington's native tract data
   is the natural holdout: aggregate it up to ZIP, allocate back down, and measure the
   round-trip error. That number is evidence, not a guess.
6. **Propagate that uncertainty into the continuous uncertainty score** (§7.4 component 5).

**A ZIP-based state does not qualify as tract-observed merely because tract estimates can be
generated from it.** Phase 3 determines how many of the sub-state-data states are genuinely
usable for tract-level demand model validation once these transformations are evaluated. If
the count of genuinely usable states falls to **three or fewer**, that triggers a formal plan
change (§15.6), not a quiet continuation of leave-one-state-out.

### 7.6 Tract to hex allocation — `pipeline/spatial/allocation.py`

Allocate tract quantities to H3 cells using **block-level population weights**, not
area weights. Area-weighted apportionment assumes uniform population within a tract, which
is badly wrong in large rural tracts.

### 7.7 Queueing — `pipeline/model/queueing.py` (Extension tier)

Erlang C converts demand into required port counts as an **analytical baseline only**. EV
charging has variable service durations, heterogeneous charger power, time-of-day demand,
state-of-charge differences, and nonstationary arrivals. Ship Erlang C alongside a small
discrete-event simulation for representative site archetypes, and report the divergence.
Calibrate utilization assumptions against published US charging station utilization research;
cite the source in the docstring and in `docs/METHODOLOGY.md`.

### 7.8 Siting optimization — `pipeline/model/siting.py`

**Offline (published frontier).** ε-constraint multi-objective integer programming with
PuLP and CBC.

```
maximize   Σ_i demand_i · y_i
subject to Σ_j cost_j · x_j ≤ B
           Σ_i equity_pop_i · y_i ≥ ε          # the ε-constraint
           y_i ≤ Σ_{j ∈ N(i)} x_j
           x_j, y_i ∈ {0,1}
```

Sweep ε across a documented range, then **reverse the objectives** (maximize equity coverage
subject to a minimum demand coverage) as a check. Weighted-sum scalarization cannot recover
unsupported Pareto-efficient points on an integer program, so the published analytical
frontier must come from ε-constraint solutions.

**Compute budget.** Each ε level is a separate integer program. A national solve over
~224,000 res 6 cells at eight ε levels in two objective directions is sixteen national IP
solves inside a GitHub Actions runner with a six-hour job ceiling. Therefore:
- Compute the published frontier **per state** or on a stratified metro sample.
- Label it accordingly.
- Set CBC time limits per solve and record whether each solve reached optimality or hit the
  limit. Report gap.

**Interactive (browser).** A greedy marginal-gain solver in a Web Worker for the budget and
weight sliders. **Label the interactive surface an approximate weighted-sum tradeoff, not the
analytical Pareto frontier.**

**No blanket (1 − 1/e) claim.** The classic (1 − 1/e) bound for greedy submodular
maximisation holds under a *cardinality* constraint. The VoltGap interactive problem has
non-uniform candidate costs, a budget (knapsack) constraint, and possibly further eligibility
constraints — that is budgeted maximum coverage, a different problem class, and plain greedy
carries no such guarantee on it. **Do not state a formal approximation bound in the UI, in a
docstring, or in documentation unless it provably applies to the exact algorithm and
constraint set implemented.** Phase 4 must:

1. define the exact browser algorithm;
2. state the mathematical problem class it solves;
3. determine whether a formal approximation guarantee applies to *that* algorithm under
   *those* constraints;
4. cite the specific theorem and source if one does;
5. verify the theorem's assumptions actually hold;
6. compare browser solutions against offline CBC on controlled fixtures and on representative
   real state problems;
7. report **empirical optimality gaps**.

If no valid formal bound applies, the UI shows none. Acceptable copy: *"Interactive
approximation. Exact offline solutions are used for the published analytical frontier."*
Empirical gap figures may be shown alongside.

**Candidate filtering.** Restrict candidates to hexes within a configured distance of the
road network and not already saturated. **Substation proximity is not a filter** — see §7.9.

### 7.9 Grid proximity — optional context, never a Core constraint

**Phase 0 could not locate an authoritative national substation dataset.** Five independent
searches failed; the best candidate service held 128 features against a historical national
figure on the order of 55,000–80,000. Per directive D8 no substitute was adopted.

Consequently:

- **National substation proximity is NOT a mandatory Core candidate filter.** Core siting
  must function without it. Do not exclude an otherwise viable candidate cell because the
  project lacks a reliable national substation dataset.
- Transmission infrastructure may remain an **optional, clearly labelled contextual map
  layer**, a source of descriptive grid context, a research input, and a future-work pathway.
- Where a trustworthy utility or substation dataset is *independently* available for a
  region, grid proximity may later become an **optional** feature. Every such value must
  carry its source provenance.

**Do not substitute transmission-line distance for substation distance and treat them as
equivalent. They are not.** Line proximity may be displayed as a weaker contextual
infrastructure proxy if clearly labelled as such, but it must never function as, or be
described as, an interconnection-feasibility constraint.

Any grid proximity value that does ship is a **proximity proxy** (D6). It says nothing about
hosting capacity, feeder availability, transformer headroom, or make-ready cost. Any UI
string or docstring implying feasibility is a bug.

### 7.10 Forecast — `pipeline/model/forecast.py` (Extension tier)

Use the Illinois monthly county panel (84 months, 2017-11 to 2024-11, 105 counties) as a
longitudinal experiment. Compare Bass diffusion against logistic, Gompertz, and simple
statistical baselines (naive, drift, damped trend). Do not assume Bass wins.

**Metrics: report WAPE or MAE alongside MAPE.** Small county counts explode percentage
errors and make MAPE misleading.

### 7.11 Economics — `pipeline/model/economics.py` (Optional tier)

- Broad geographic electricity prices: **EIA**.
- Tariff structures and demand charges: **OpenEI Utility Rate Database**.
- **Do not use the NREL Utility Rates API.** Its rate data are from 2012 with no update
  plans, and it does not provide complex rate structures. It is unsuitable for a current
  charger economics model. This is recorded here so the mistake is not repeated.

### 7.12 eGRID — Optional / Future Work, no Core consumer

Phase 0 confirmed eGRID is reachable, but **no Core calculation in this specification
consumes it.** It is therefore Optional/Future Work tier, not Core. A source is not retained
merely because it appeared in an earlier architecture sketch.

Plausible future consumers, none of which is required by the Core decision engine: avoided-
emissions estimates, electricity carbon-intensity analysis, carbon-aware siting, emissions-
per-mile comparison, environmental-benefit scenarios.

**Do not invent an emissions feature in order to justify keeping eGRID in Core.** If a
concrete Core consumer appears, promote it deliberately and record why.

### 7.13 FHWA traffic — Optional / Future Work, no surviving Core consumer

Traffic entered this specification in exactly one place: §10.2.3's reduced backtest feature
set, which applies **only if** no historical state EV registration totals exist and the
reconciliation constraint cannot be applied at a backtest cutoff.

**That fallback is not triggered.** Phase 0 established that AFDC publishes ten annual state
registration vintages, 2016 through 2025, covering all three rolling origins (2020, 2021,
2022). The reconciliation constraint *can* be applied at every cutoff, so the reduced feature
set that would have needed traffic is never constructed.

No other Core model in §7 consumes traffic. The "within a configured distance of the road
network" candidate filter in §7.8 is road-network *geometry*, not traffic volume, and does not
depend on this source.

FHWA traffic is therefore **Optional / Future Work**, on the same footing as eGRID (§7.12).
The same discipline applies: **do not invent a traffic feature in order to justify keeping the
source.** If a concrete Core consumer appears, promote it deliberately and record why.

---

## 8. Equity layer

Executive Order 14008, which established Justice40, was revoked on 20 January 2025.

- **Do not describe the project as evaluating current Justice40 compliance.**
- CEJST may be included as an **archived historical equity classification**, labeled with
  its data vintage everywhere it appears.
- The primary equity measure is built from **current ACS-derived socioeconomic and
  vulnerability indicators**, not from CEJST.
- The UI must state that the archived overlay reflects a policy framework no longer in force.

---

## 9. Transform layer

DuckDB SQL in `pipeline/transform/models/`, three layers, executed by `runner.py` in
dependency order.

```
staging/       stg_*.sql        one per source, typing and renaming only, no logic
intermediate/  int_*.sql        joins, spatial allocation, entity resolution
marts/         mart_*.sql       the tables that become published artifacts
```

Rules:
- **Retrieval and staging preserve source rows.** This binds source adapters in
  `pipeline/sources/` as well as `stg_*.sql`. An adapter may perform transformations that are
  purely mechanical and lossless — decoding, decompression, character-set handling, streaming
  a large file, reshaping a fixed layout into rows — but it must not drop, filter, or
  editorialise rows. Business filtering belongs in the intermediate layer, where it is visible
  and testable.
  Worked consequences: the AFDC state-registration adapter **ingests the published
  `United States` total row**, and G8's removal of it happens in intermediate; the HIFLD
  transmission adapter **streams** the file to satisfy G12 but performs **no voltage
  filtering**, which is an intermediate transformation, and tiling belongs to the export phase
  entirely.
- Staging models must not filter rows. Filtering is business logic and belongs in
  intermediate.
- Every mart carries `computed_at` and `source_vintages`.
- Every model has a matching pandera schema in `pipeline/schemas/`, checked after execution.
  **A schema violation fails the build and blocks publication.**

Required marts: `mart_hex6_national`, `mart_hex8_metro`, `mart_tract_access`,
`mart_sites`, `mart_state_summary`, `mart_candidates`, `mart_frontier`.

---

## 10. Validation harnesses

### 10.1 Demand model validation — `pipeline/validation/demand_model.py`

**Leave-one-state-out** across every sub-state anchored state that remains **genuinely
usable after the §7.5.1 geographic transformations have been evaluated**. Phase 0 found 16
states with sub-state registration data, but only Washington is natively tract-grain; the rest
require ZIP→tract or county→tract allocation whose quality Phase 3 must measure. Do not fix
the number of states in advance, and do not count a state as usable merely because tract
estimates can be generated for it.

Report at the **native observed granularity** of each held-out state wherever possible. A
ZIP→tract allocation does not constitute tract-level ground truth and must not be reported as
if it did. Alongside the accuracy metrics, report crosswalk/allocation quality, reconciliation
movement, and out-of-distribution behaviour.

**If the count of genuinely usable states falls to three or fewer, trigger a formal plan
change (§15.6) rather than quietly proceeding with leave-one-state-out.**

Report per held-out state: WAPE, MAE, R² at the native granularity of that state's data,
plus calibration of the uncertainty score (are high-uncertainty tracts actually less
accurate?). A well-calibrated uncertainty score is itself a result worth publishing.

### 10.2 Historical deployment alignment — `pipeline/validation/deployment_alignment.py`

**This measures whether model priorities match where industry actually built. It does not
measure whether those deployments were optimal.** Charge point operators build based on real
estate availability, grant programs, utility relationships, commercial strategy, highway
contracts, and network expansion plans. High alignment may mean the model reproduces industry
behavior including its biases. Say this in `docs/VALIDATION.md`, in the UI, and in the
README.

#### 10.2.1 The vintage guard (D1)

```python
@dataclass(frozen=True)
class VintagedFeature:
    name: str
    values: pd.Series
    feature_vintage: date
    source_id: str

def assert_no_leakage(
    features: list[VintagedFeature], prediction_cutoff: date
) -> None:
    """Raise LeakageError if any feature postdates the cutoff. Called by the harness
    before every backtest fit. This is a runtime assertion, not documentation."""
```

Any feature whose historically appropriate vintage cannot be reconstructed is **excluded
from the retrospective backtest**, even when it is used in the live model. Enumerate every
excluded feature in `docs/VALIDATION.md`.

Known exclusions to expect:
- Home charging access (single NREL vintage, not reconstructable) — excluded.
- Any 2024-vintage ACS release for a 2020 or 2021 origin — use the contemporaneous ACS
  5-year release instead.

#### 10.2.2 Rolling origins

Run at least three origins: **2020, 2021, 2022**, each predicting the following 24 months.
Reconstruction confidence degrades with age because of survivorship bias (G11), so report
a reconstruction confidence note per origin and weight conclusions toward the most recent.

#### 10.2.3 The reconciliation problem

The demand model reconciles to state EV totals. If Phase 0 finds no historical state total
vintages, the reconciliation constraint cannot be applied at the cutoff.

> **NOT TRIGGERED (Phase 0, 2026-08-19).** AFDC publishes ten annual state registration
> vintages, 2016 through 2025, covering all three rolling origins. The reconciliation
> constraint can be applied at every cutoff, so the reduced feature set below is not
> constructed and traffic is not needed for it (§7.13). The clause is retained because it
> remains the correct response should those vintages become unobtainable, and because the
> A-0.5 investigation (§15.5 Phase 1) could still change what those vintages *mean*.

In that case:
- Run the backtest on an unconstrained propensity surface.
- Enumerate the reduced feature set explicitly (demographics, network state, geography,
  traffic).
- State in `docs/VALIDATION.md` that **the backtested model and the deployed model are not
  the same model**, and list every difference.

#### 10.2.4 Metrics

Top-decile capture rate of subsequent installations, gain curve across all deciles, and lift
against two baselines: random, and population-weighted. Report ports and capacity captured,
not just station counts (G1).

#### 10.2.5 Reconstruction labeling

Label the historical network an **approximate reconstruction** everywhere. Per G10 and G11
it is survivorship-biased and open dates are imprecise. If archived AFDC snapshots become
obtainable, that upgrade goes in `docs/FUTURE_WORK.md`, not into a redesign.

### 10.3 Cross-objective robustness — `pipeline/validation/robustness.py`

Optimize a portfolio on **one** objective, then evaluate it on objectives that were **never
in the loss function**: population served, demand covered, equity coverage, accessibility
improvement, estimated utilization, cost efficiency.

Compare against baselines: population-weighted, demand-only, existing-network-proximity, and
random.

**Do not report "the optimizer wins" on its own objective. That is circular.** The result is
either cross-objective robustness (a demand-optimized portfolio also performs on equity) or
an exposed tradeoff (it does not). Both are publishable findings. Present the ε-constraint
frontier as the tradeoff surface rather than declaring a winner.

---

## 11. Frontend specification

### 11.1 Core views (three)

**1. National Overview.** H3 res 6 choropleth with a metric selector (supply capacity, DCFC
access gap, estimated EV demand, priority score). Confidence tier is always visible via
opacity or hatching. Every aggregate reports **sub-state anchored versus modeled** share, with
the `evidence_grain` breakdown available beneath it (§7.4.1). Metro drill-down lazy loads res
8 on zoom.

**2. Access and Equity.** DCFC access gap distribution with a live threshold control and its
sensitivity curve. Population affected, broken down by current ACS-derived vulnerability
indicators. Archived CEJST overlay is opt-in and vintage-labeled.

**3. Siting Studio.** Budget slider, objective weight sliders, constraint toggles (minimum
equity coverage, exclude saturated cells). **No national grid-proximity constraint control**,
because no national substation dataset exists (§7.9); if a trustworthy regional substation
dataset is later added, an optional control may appear for that region only, labelled with its
provenance. Greedy Web Worker re-solve under 2 seconds. Ranked candidate table with scores,
uncertainty bands, and power confidence. Map of selected portfolio. CSV and GeoJSON export. A
link to the published ε-constraint frontier for the relevant state, with the interactive
surface labeled as an approximate weighted-sum tradeoff and **no approximation bound stated
unless one provably applies** (§7.8).

Plus a **Methodology and Validation** page that is a first-class view, not a footer link.

### 11.2 Extension views

Forecast Explorer. Site archetype queueing detail.

### 11.3 Performance budget (CI-enforced)

| Metric | Budget |
|---|---|
| App shell, gzipped | ≤ 600 KB |
| Time to interactive, cold, national view | ≤ 3.0 s |
| National hex layer render | ≥ 55 fps sustained pan and zoom |
| Greedy re-solve, state-level | ≤ 2.0 s |
| DuckDB-WASM | Lazy, Web Worker, Studio and SQL panel only, never on first paint |

CI fails on bundle budget violation. Lighthouse CI runs on every PR.

### 11.4 Loading strategy

| Asset | Loaded |
|---|---|
| App shell | always |
| Basemap (OpenFreeMap) | always |
| `hex6_national.parquet` | always |
| `tract_access.parquet` | Access view |
| `sites.pmtiles` | map layer toggle |
| `transmission.pmtiles` (>100 kV, simplified) | opt-in contextual layer only, labelled as infrastructure context and never as an interconnection constraint (§7.9) |
| `hex8_metro/{cbsa}.parquet` | on zoom |
| DuckDB-WASM | Studio view only |

### 11.5 UI copy rules

- Never "optimal site", "validated optimal", "optimal siting accuracy", or "proven best".
- Never "grid feasible", "interconnection ready", "available grid capacity", "feeder
  capacity", or "transformer headroom". Use "grid proximity", and only where a provenanced
  dataset supports it.
- Never "charging desert" for a DCFC-only measure. Use "DCFC access gap".
- Never "Justice40 compliance". Archived overlays carry their vintage.
- Never present a modeled tract without its confidence tier.
- **Never label Tier A "observed".** Use "sub-state anchored" (§7.4.2). "Observed" is
  reserved for `evidence_grain == native_tract` with `estimate_method == directly_observed`.
- **Never state an approximation bound for the interactive solver** unless it provably
  applies to the implemented algorithm and constraint set (§7.8).
- Never conflate the three D3 validation terms: demand model validation, historical
  deployment alignment, cross-objective robustness.

These rules are enforced by a **rule-based terminology copy lint created in Phase 1** and run
in CI from that phase onward, covering documentation and code as well as UI strings. It need
not understand arbitrary prose; catching the prohibited phrases above and the D3 conflations
is sufficient. Phase 5 extends it.

---

## 12. Artifacts and hosting

| Artifact | Target size | Host |
|---|---|---|
| `hex6_national.parquet` | 8–15 MB | R2 |
| `tract_access.parquet` | 5–10 MB | R2 |
| `sites.pmtiles` | 3–6 MB | R2 |
| `transmission.pmtiles` | 15–30 MB | R2 |
| `hex8_metro/*.parquet` | ~150 KB each | R2 |
| `frontier/*.json` | small | R2 |
| `manifest.json` | small | R2 |

`manifest.json` carries per-artifact checksums, row counts, `computed_at`, and the full
`source_vintages` map. The frontend reads it first and renders the freshness indicator from
it.

**Hosting notes to record in `docs/LIMITATIONS.md`:**
- Cloudflare R2 free tier has no egress charge but does have Class A and Class B operation
  quotas. Zero cost is not guaranteed indefinitely at arbitrary traffic.
- Vercel Hobby is restricted to personal, non-commercial use. Appropriate for a portfolio
  project; note it.
- OpenFreeMap's public instance requires no key and states no request limits, but it is a
  single point of failure. Ship a self-hosted Protomaps basemap on R2 as the fallback. Do not
  depend on an anonymous third-party CDN.

---

## 13. CI/CD and refresh

### 13.1 `ci.yml`
Runs on PR: ruff, mypy strict, pytest with coverage gate, pandera schema tests against
fixtures, frontend typecheck, bundle budget, Lighthouse CI.

### 13.2 `etl.yml`
Scheduled weekly **and** `workflow_dispatch`. Steps: probe sources, refresh, validate,
model, export, upload to R2, write manifest, trigger deploy.

**Failure behavior:** on any schema or quality gate failure, do not publish. Keep the prior
artifacts live and mark the manifest stale. A stale-but-correct site beats a fresh-but-broken
one.

### 13.3 Refresh health
- GitHub scheduled workflows can be delayed, and scheduled workflows on public repositories
  are **automatically disabled after 60 days without repository activity**. Add
  `keepalive.yml` and, more importantly, a **refresh health indicator in the UI** driven by
  `manifest.json.computed_at`. If the data is older than a configured threshold, the UI says
  so plainly.
- `workflow_dispatch` must always be available for manual refresh.

---

## 14. Testing requirements

| Layer | Requirement |
|---|---|
| Unit | Every model function, pipeline coverage ≥ 70% |
| Regression | One test per domain rule G1–G14 in §5, using the corrected G9 |
| Copy lint | D3 terminology and §11.5 rules, created in Phase 1, run in CI from then on |
| Leakage | `assert_no_leakage` raises on a deliberately poisoned feature set |
| Schema | Every canonical table validated against its pandera schema |
| Integration | Full pipeline on a fixture subset (2 states) completes end to end |
| Determinism | See §14.1. Semantic determinism under pinned inputs, not naive byte equality |
| Frontend | Component tests for the Studio solver, snapshot tests for tier rendering |

A test that asserts a model is "correct" in the sense of optimal siting is a mis-specified
test. Test mechanics, invariants, and reconciliation identities instead.

### 14.1 What determinism means here

Every derived table carries `computed_at` (§6.2), so **byte-identical checksums across
independent runs are impossible** unless volatile metadata are controlled. A gate that
demanded naive byte equality would either fail permanently or force `computed_at` to be
dropped, and neither is acceptable.

Determinism is therefore defined as:

> **Same pinned source snapshots + same code + same configuration ⇒ same semantic data
> output.**

Two distinct properties are tested, and the gate must not confuse them:

| Property | How it is tested | Expectation |
|---|---|---|
| **Replay reproducibility** | Run twice against pinned/replayed inputs, with either one injected fixed run timestamp or volatile metadata normalised out before hashing | **Byte-identical semantic hash. Required.** A failure is a real defect |
| **Live-source refresh behaviour** | Run against live sources | **Not expected to be byte-identical.** Upstream data legitimately change. Verified by schema conformance, drift bounds and quality gates instead |

Volatile metadata excluded from the semantic hash: `computed_at`, `last_successful_retrieval`,
retrieval durations, and any other field whose value is a function of when the run happened
rather than of what the data are. Everything else is in scope, including `source_vintages`,
because a change there is a genuine semantic change.

A live refresh producing different artifacts is **not** a determinism failure. Treating it as
one would push the pipeline toward suppressing real upstream change, which is the opposite of
what §13.2 requires.

---

## 15. Phase plan and gate protocol

Estimates are part-time and **include gate work**. The official schedule, rebaselined
2026-08-19 by summing the phase table below rather than carrying an earlier rough estimate:

| Scope | Planned part-time weeks |
|---|---:|
| **Core (Phases 0–7)** | **14.5** |
| Core remaining (Phase 0 complete) | 13.5 |
| Extensions (E1 + E2 + E3) | 4.25 |
| **Core + Extensions** | **18.75** |
| Optional (O1–O3) | unestimated, strictly behind Core and Extension gates |

This is the single official timeline. Any earlier figure elsewhere in the repository —
"roughly 10 weeks", "12.5 weeks", "16 to 17 weeks", or an eight-week estimate — is obsolete.
The scope now carries substantially stronger validation and engineering requirements than
those estimates assumed. **Do not compress by skipping validation or gates**, and do not
compress merely to preserve an earlier estimate.

### 15.1 The phase gate rule

**No phase begins until the previous phase's gate passes and its report is approved by the
project owner.** Work does not proceed in parallel across a gate. If you believe a phase is
complete, run the gate, write the report, and stop.

A gate has five parts. All five must pass.

| Part | Requirement |
|---|---|
| **G-A. Acceptance criteria** | 100% of the phase's declared criteria verified by an executable check. Each criterion maps to a named test. No criterion is marked passed by inspection. |
| **G-B. Coverage** | 100% line and branch coverage on `pipeline/model/`, `pipeline/validation/`, and `pipeline/spatial/`. ≥ 85% on `pipeline/transform/` and `pipeline/sources/`. ≥ 70% repository wide. |
| **G-C. Regression** | Every prior phase's gate suite re-run and passing. A phase that breaks an earlier gate has not passed its own. |
| **G-D. Forward viability** | A written demonstration that this phase's outputs are sufficient for the next phase's inputs. See §15.2. |
| **G-E. Report** | `docs/reports/PHASE_{n}_REPORT.md` complete per the template, self-contained. See §15.4. |

**Coverage note.** The 100% requirement applies to result-computing code because that is
where a silent error becomes a wrong published number. Do not pad with trivial assertions
to reach the number. If a branch cannot be meaningfully tested, mark it
`# pragma: no cover` with a written justification in the report. Unjustified pragmas fail
the gate.

### 15.2 Forward viability check (G-D)

The risk this protocol exists to manage is reaching Phase 5 and discovering Phase 1 made an
assumption that does not hold. Each gate must therefore prove its outputs are usable
downstream, not merely internally correct.

At each gate, produce:

1. **Contract table.** Every artifact this phase produces, its schema, its grain, its
   guaranteed invariants, and which later phase consumes it.
2. **Smoke-forward test.** A minimal executable exercise of the *next* phase's core
   operation against this phase's real output, on a two-state fixture. It does not have to
   be complete or accurate. It has to prove the data shape works. Example: Phase 1's gate
   runs a trivial supply aggregation over the real canonical tables to prove the entity
   hierarchy joins correctly.
3. **Assumption ledger.** Every assumption this phase makes that a later phase depends on,
   written as a falsifiable statement with the phase that will test it. Carried forward and
   re-checked at every subsequent gate.

### 15.3 Cross-phase impact protocol

When a later phase invalidates an earlier one, do not silently patch and continue.

1. **Stop.** Do not implement a workaround before recording the finding.
2. **Record** in `docs/reports/IMPACT_LOG.md` with: discovering phase, affected phase, what
   was assumed, what is actually true, evidence, and which published outputs are now wrong.
3. **Classify severity.**

| Severity | Definition | Response |
|---|---|---|
| **S1 Blocking** | An earlier phase's published output is wrong and downstream results are invalid | Halt forward work. Fix the earlier phase. Re-run its full gate. Re-run every gate since. Amend the affected phase reports with a dated correction section. |
| **S2 Degrading** | An earlier output is usable but weaker than claimed | Fix within the current phase if under one day. Otherwise schedule as a remediation task with a named phase and record the interim limitation in `docs/LIMITATIONS.md`. |
| **S3 Cosmetic** | Documentation, naming, or presentation only | Fix immediately, note in the current phase report. |

4. **Amend, do not rewrite.** Prior phase reports are never edited in place. Append a
   dated `## Correction — {date}` section. The report history must remain auditable.
5. Every gate report includes an **Impact Log delta** section listing entries opened,
   resolved, and still open since the previous gate.

### 15.4 Report requirements

Reports are reviewed by the project owner and by an external model that **will not have
access to the repository, the code, the data, or any prior context**. A report that requires
opening a file to be understood has failed.

Every report must therefore:

- **Restate context.** What the project is, what this phase was for, what the previous phase
  produced. Assume the reader has read nothing.
- **Quote, never reference.** Include the actual numbers, the actual test names, the actual
  schema definitions, the actual formulas, and relevant code excerpts inline. Never write
  "see `supply.py`" or "as defined in the schema."
- **Show the evidence.** Real output values, real row counts, real coverage percentages,
  real test output summaries. Not "tests pass" but which tests, how many, and what they
  assert.
- **State what is not known.** Every assumption, every fallback taken, every limitation
  introduced, every open question.
- **Be falsifiable.** A reviewer must be able to identify a specific wrong claim from the
  report alone.

Use `docs/templates/PHASE_REPORT_TEMPLATE.md` verbatim. Do not omit sections; write "not
applicable to this phase" where a section does not apply.

**Length is not a constraint.** A Phase 3 report will reasonably run several thousand words
because it must include the model specification, feature list, validation results, and
uncertainty calibration inline. Completeness beats brevity here.

### 15.5 Phases

| Phase | Weeks | Deliverable | Acceptance criteria (all must be executable checks) |
|---|---|---|---|
| **0. Source contract** | 1.0 | `SOURCES.yml`, `probe.py`, `docs/SOURCE_VERIFICATION.md` | Every source has all contract fields populated. Every Core model has a data path or documented fallback. AFDC connector power missingness measured numerically. NREL home charging vintage determined as current or 2030 scenario. Historical registration vintage availability resolved yes/no. Tier A states enumerated with granularity and temporal coverage each. `probe.py` is idempotent. |
| **1. Ingestion + canonical** | 2.25 | All sources ingested, staging and intermediate models, pandera schemas, G1–G14 regression tests, port-identifiability analysis, D3 copy lint, A-0.5 provenance investigation | One command rebuilds every canonical table from a clean clone. All G1–G14 regression tests pass, including corrected G9 (§5) verifying vintage resolution, jurisdiction coverage, non-negativity, total reconciliation, anomaly screening execution, review-flag surfacing, and that a low-confidence label cannot be assigned on statistical unusualness alone. Every canonical table validates against its schema. Entity hierarchy resolves with no orphans, and **no `ports` row exists whose identity the source does not support** (§6.1.1). Port-identifiability analysis completed with all six measurements reported numerically. Every registration observation carries `evidence_grain` and `estimate_method` (§7.4.1), and **no ZIP-derived or county-derived tract value is labelled `directly_observed`**. Source geography declared explicitly per source; no USPS ZIP Code silently treated as a ZCTA (§7.5.1). D3 terminology copy lint exists and passes. A-0.5 investigation yields either an evidence-backed classification or an explicitly recorded `historical_vintage_semantics = unresolved` with preserved evidence. Row counts within the `SOURCES.yml` expected ranges. Determinism check: two runs produce identical checksums. |
| **2. Supply + access** | 1.75 | Supply with power ladder, block-weighted access, threshold sensitivity | Power ladder rung distribution reported with actual percentages. National population in DCFC access gap computed and reproducible. Sensitivity curve produced across the full threshold range. Population-weighted allocation verified against a hand-computed rural tract fixture. G1–G4 enforced in the supply path by test. |
| **3. Demand + uncertainty** | 2.25 | Propensity model, reconciliation, continuous uncertainty, tiers | Leave-one-state-out run across every Tier A state with WAPE, MAE, R² per held-out state. D2 enforced: a test asserts no supply-derived feature is present in the primary feature set. Reconciliation identity holds exactly (tract sums equal constraints to within floating point tolerance). Uncertainty calibration curve produced. Ablation with supply features run and reported separately. |
| **4. Siting + frontier** | 1.75 | ε-constraint frontier, greedy Web Worker solver | Frontier computed per state with solve status and optimality gap recorded per point. Reverse-objective check run. The browser algorithm is defined exactly, its problem class stated, and either a formal approximation guarantee is cited with its theorem and its assumptions verified to hold, **or no bound is claimed anywhere** (§7.8). **Empirical optimality gaps against offline CBC reported** on controlled fixtures and on representative real state problems. Greedy solves a state in ≤ 2 s. Candidate filtering verified against constraint definitions, **with no mandatory national substation-proximity filter** (§7.9). |
| **5. Validation** | 1.75 | Vintage guard, three rolling origins, cross-objective robustness, `docs/VALIDATION.md` | `assert_no_leakage` raises on a deliberately poisoned feature set (negative test). All three origins run with gain curves and lift against random and population baselines. Excluded backtest features enumerated. Robustness reported against four baselines on six objectives. Every claim uses the D3 vocabulary (checked by the copy lint **created in Phase 1** and extended here). Backtest methodology states the A-0.5 vintage-semantics finding explicitly, including the limitation if it remained unresolved. |
| **6. Frontend Core** | 2.75 | Three views plus Methodology, exports | Static export deploys. All performance budgets met and CI-enforced. Exports produce valid CSV and GeoJSON verified by parse. UI copy lint passes (§11.5 rules). Confidence tier renders on every modeled value. Unmoderated usability check: one person unfamiliar with the project produces a siting recommendation without instructions. |
| **7. Automation + docs** | 1.0 | ETL cron, health indicator, all docs | ETL completes unattended end to end. Failure path verified: an injected schema violation blocks publication and preserves prior artifacts. Staleness indicator verified by clock manipulation. All six docs complete. Full rebuild from clean clone verified on a fresh machine or container. |
| **E1. Queueing** | 1.25 | Erlang C plus DES check | Divergence between analytical and simulated reported across archetypes. |
| **E2. Forecast** | 1.75 | Model bakeoff on the Illinois panel | WAPE, MAE, MAPE for every candidate against naive, drift, and damped-trend baselines. |
| **E3. Isochrones** | 1.25 | Drive-time access, top metros | Network versus straight-line divergence quantified and reported. |
| **O1–O3. Optional** | — | Economics, DuckDB SQL panel, PDF briefs | Only after Core and Extension gates all pass. |

### 15.6 Gate ceremony

At the end of each phase, in this order:

1. Run `make gate PHASE=n`. This executes: full test suite, coverage report, all prior gate
   suites, the smoke-forward test, the UI copy lint where applicable, and the determinism
   check.
2. If anything fails, the phase is not done. Fix and re-run. Do not report a partial gate.
3. Write `docs/reports/PHASE_{n}_REPORT.md` from the template.
4. Update `docs/reports/ASSUMPTION_LEDGER.md` and `docs/reports/IMPACT_LOG.md`.
5. Commit with message `gate(phase-{n}): PASS` and **stop**. Await owner approval before
   starting phase n+1.

If a gate cannot pass because the plan itself is wrong rather than the implementation,
write `docs/reports/PLAN_CHANGE_{n}.md` stating what in this specification is unworkable,
the evidence, and two or more options with tradeoffs. Then stop and await a decision. Do not
unilaterally revise the specification.

---

## 16. Documentation deliverables

| File | Must contain |
|---|---|
| `METHODOLOGY.md` | Every formula, every threshold, every estimator choice with its reason, the downscaling caveat for home charging, the ε-constraint rationale |
| `DATA_DICTIONARY.md` | Every field in every published artifact: definition, units, source, vintage, confidence semantics |
| `DATA_GOTCHAS.md` | G1–G14 as domain rules with reproductions, using the **corrected G9** (§5) and recording that the original G9 was amended by `docs/reports/PLAN_CHANGE_0.md` |
| `LIMITATIONS.md` | Approximate reconstruction, survivorship bias, downscaling not ground truth, grid proximity not feasibility, free-tier quota caveats, Vercel Hobby terms, archived CEJST status |
| `VALIDATION.md` | All three validations with the D3 vocabulary, excluded backtest features enumerated, backtested-versus-deployed model differences, gain curves, calibration results, honest discussion of confounding |
| `FUTURE_WORK.md` | Everything that tempts a redesign mid-build |

---

## 17. Definition of done

- [ ] Every displayed number traces to a source and a transformation in the data dictionary
- [ ] No composite index ships without a weight sensitivity control
- [ ] Every modeled tract carries a continuous uncertainty score and a derived tier
- [ ] Every tract estimate carries `evidence_grain` and `estimate_method`, and no
      ZIP-derived or county-derived value is labelled directly observed
- [ ] No `ports` row exists whose physical identity the source does not support
- [ ] No approximation bound is stated for the interactive solver unless it provably applies
- [ ] `assert_no_leakage` is called in the backtest harness and has a passing negative test
- [ ] No supply-derived feature appears in the primary demand model (enforced by test)
- [ ] The three validation terms are used consistently and never conflated
- [ ] No UI string claims optimality, grid feasibility, or current Justice40 compliance,
      and no Tier A value is labelled "observed" (enforced by the D3 copy lint from Phase 1)
- [ ] Core siting functions without any national substation dataset
- [ ] Cold load ≤ 3 s, national layer ≥ 55 fps, greedy re-solve ≤ 2 s
- [ ] Full rebuild from a clean clone with one command
- [ ] Pipeline coverage ≥ 70%, all G1–G14 regression tests passing
- [ ] Recurring cost is 0 USD
- [ ] Refresh health is visible in the UI

---

## 18. Anti-patterns

Things that will look like progress and are not:

1. Adding chart types. The output is decisions, not visualizations.
2. Treating a high backtest lift as proof the model is good. It may mean the model
   reproduces industry bias. Report it with that caveat every time.
3. Filling a missing source with a plausible default instead of degrading explicitly.
4. Hand-picking index weights and presenting them as calibrated.
5. Letting supply features into the demand model because they improve fit. They will improve
   fit. That is the problem.
6. Sweeping weights and calling the result a Pareto frontier.
7. Loading the transmission GeoJSON directly, at any point, for any reason.
8. Counting station rows as capacity.
9. Redesigning mid-build. New ideas go to `docs/FUTURE_WORK.md`.

---

## 19. Specification amendment log

This specification is amended, never silently rewritten. Every entry below records a change
made after a phase gate produced evidence that the specification as written was wrong or
underspecified. The original wording is quoted so the audit trail survives.

### Amendments of 2026-08-19 — arising from the Phase 0 gate and `docs/reports/PLAN_CHANGE_0.md`

Authorised by the project owner on review of `docs/reports/PHASE_0_REPORT.md`. These are
corrections from evidence, not a design round. With them applied, the design is closed again.

| ID | Section | Was | Now |
|---|---|---|---|
| A0 | §4.1 | `SOURCES.yml` holds contract and live measurements together | Split: `SOURCES.yml` stable contract, `SOURCES.observed.json` generated observations |
| A1 | §5 G9 | "Oregon reports 6,436, below Kansas at 11,271 and Iowa at 9,031, which is implausible… mark low-confidence states" | Vintage/coverage/non-negativity/total-reconciliation validation; anomaly screening is a **diagnostic that flags for review**; low confidence requires corroborating evidence of an actual defect |
| A2 | §7.4.1 | Single A/B/C confidence label | Two orthogonal fields, `evidence_grain` and `estimate_method`, never collapsed internally |
| A3 | §7.4.2, §11.1, §11.5 | "Tier A (observed) = sub-state registration data exists…" | "Tier A — **sub-state anchored**". Tier A must never be labelled "observed" |
| A4 | §7.5.1 (new) | ZIP→tract treated as an implicit crosswalk | Explicit geographic reconciliation requirement: declare source geography, name crosswalk and vintage, weighted allocation, preserve method, measure error, propagate uncertainty. USPS ZIP ≠ Census ZCTA |
| A5 | §6.1.1 (new), §6.2 | `ports` table with one physical port per row | Port identity must be earned. Phase 1 port-identifiability analysis before schema freeze; hierarchy stops at `charging_unit` where identity is unrecoverable; synthetic expansions labelled computational |
| A6 | §7.8, §7.9, §11.1, §11.4, §15.5 Phase 4 | Candidates must be "within a configured distance of a substation" | **National substation proximity removed as a mandatory Core filter.** Core siting functions without it. Transmission stays optional labelled context and must never masquerade as an interconnection constraint |
| A7 | §7.2 | Fallback triggers if the dataset is unavailable or a 2030 projection | Third condition added and **found to hold**: parametric scenario surface, not a dated current observation. Home charging is exploratory/optional-weight only, excluded from the primary objective. Not reopenable in Phase 3 |
| A8 | §3, §7.12 (new) | eGRID listed as a Core source module | Demoted to Optional/Future Work; no Core consumer exists. Do not invent an emissions feature to justify it |
| A9 | §11.5, §14, §15.5 Phases 1 and 5 | D3 copy lint first appears in Phase 5 | Copy lint **created in Phase 1**, run in CI from then on; Phase 5 extends it |
| A10 | §15.5 Phase 1 | A-0.5 vintage-semantics question deferred to Phase 5 | Bounded provenance investigation moved to **Phase 1**, with a fixed budget; if unresolved, record `historical_vintage_semantics = unresolved` and require Phase 5 to state the limitation. Never equate a year label with verified information availability |
| A11 | §7.8, §15.5 Phase 4 | Browser greedy "carries a (1 − 1/e) approximation bound; state this in the UI" | **Claim removed.** Non-uniform costs plus a budget constraint make this budgeted maximum coverage, a different problem class. Phase 4 must define the algorithm, verify any cited theorem's assumptions, and report **empirical** optimality gaps. No bound is displayed unless it provably applies |
| A12 | §15 | "Core is 12.5 weeks. Core plus Extension is 16 to 17 weeks." | **Core 14.5 part-time weeks** (13.5 remaining after Phase 0); Extensions 4.25; Core + Extensions 18.75. Single official schedule |

### Amendments of 2026-08-19 (second set) — arising from the Phase 1 plan review

| ID | Section | Was | Now |
|---|---|---|---|
| A13 | §6.1.1, §6.2 | Port identity must be earned; `charging_unit_id` assumed to be a stable key | Extended to **charging-unit and connector identity**. Measurement found no unit identifier column, 65.9% byte-identical duplicate rows, and `ID` as the station parent key only. `charging_unit_record_key` is explicitly synthetic and per-snapshot; no longitudinal physical-unit identity may be claimed. Connectors are modelled at `(charging_unit_record_key, connector_type)` grain, never as manufactured `connector_id` rows. Phase 1's investigation covers all three levels and gains measurements 7 and 8. Recorded as impact-log entry **I-1** |
| A14 | §14, §14.1 (new) | "Same inputs plus same seed produce identical artifact checksums" | Naive byte equality is impossible because every derived table carries `computed_at`. Determinism redefined as **same pinned snapshots + same code + same configuration ⇒ same semantic output**, tested with pinned/replayed inputs and a fixed injected timestamp or normalised-out volatile metadata. **Replay reproducibility and live-refresh behaviour are separated in the gate**; a live refresh producing different artifacts is not a determinism failure |
| A15 | §9 | "Staging models must not filter rows" (bound only `stg_*.sql`) | The rule binds **source adapters too**. Retrieval and staging preserve source rows; only mechanical, lossless transformation is allowed. Worked consequences: the registration adapter ingests the `United States` total row and G8 removes it in intermediate; the HIFLD adapter streams for G12 but does no voltage filtering, and tiling moves to the export phase |
| A16 | §3, §7.13 (new), §10.2.3 | `fhwa_traffic.py` a Core source module | **Optional / Future Work.** Traffic appeared only in §10.2.3's reduced feature set, which applies solely when historical state totals are unavailable — and Phase 0 found ten vintages covering all three origins, so the fallback is not triggered. §10.2.3 now carries a NOT TRIGGERED note so a later phase cannot resurrect traffic by accident. Do not invent a traffic feature to justify the source |

**Scope control from this point.** Findings are classified before they are acted on. A
**genuine correctness blocker** — a wrong source assumption, temporal leakage, invalid
statistical inference, an impossible schema, a mathematical guarantee that does not apply, a
source that does not exist, a canonical entity that cannot be identified — may trigger a
formal plan change under §15.6. A **useful enhancement** — another visualisation, model,
dataset, frontend feature, optimisation method, scenario, or dashboard — goes to
`docs/FUTURE_WORK.md` and does not interrupt the current phase. The objective from here is to
build the system that has been designed, not to keep making the design more ambitious.
