# Methodology

Every formula, every threshold and every estimator choice, with the reason for it.
Sections appear as the phase that produced them completes; this file currently covers
Phases 2 and 3.

---

## 1. Vocabulary discipline

Three validations exist and are never blurred (directive D3):

| Term | What it evaluates | Method |
|---|---|---|
| **Demand model validation** | Whether tract-level EV estimates are accurate | Leave-one-state-out against observed states |
| **Historical deployment alignment** | Whether priority areas match where industry actually built | Vintage-enforced rolling-origin backtest (Phase 5) |
| **Cross-objective robustness** | Whether a portfolio optimised for one objective performs on others | ε-constraint Pareto analysis (Phase 5) |

None of them demonstrates that a site is objectively optimal. Ground truth for optimal
siting does not exist.

---

## 2. The demand model (Phase 3)

### 2.1 What is being estimated

Battery-electric vehicle (**BEV**) registrations per census tract.

**The target is BEV, not "EV", and the choice is forced by the constraint.** The AFDC
state registration series publishes `Electric (EV)` and
`Plug-In Hybrid Electric (PHEV)` as separate columns, and the delivered seed totals match
the BEV column (Alabama 13,047 against a rounded 13,000). It is the only state-level
constraint available for all 51 jurisdictions. Counting PHEVs into the target would make
every tract estimate irreconcilable with it. PHEV counts are carried alongside and are
never added in.

### 2.2 Features: demographics only

Directive **D2** forbids charger counts, port counts, charger density, network presence,
distance to the nearest charger, and any transform of them, in the primary model.
Existing infrastructure is an *outcome* of prior investment decisions; predicting demand
from it and then siting from that demand launders historical deployment patterns into
"need" and suppresses exactly the underserved areas the project exists to find.

Fourteen features are derived from nine ACS 2023 5-year tables:

| Feature | Definition | Why it is admissible |
|---|---|---|
| `log_population_density_km2` | `ln(population / land_km² + 1)` | Separates urban from rural without a separate classification; logged because the national distribution spans five orders of magnitude |
| `median_household_income_k` | `B19013_001E / 1000` | Ability to pay |
| `income_share_over_100k` | `(B19001_014E…017E) / B19001_001E` | The upper tail a median hides |
| `income_share_under_35k` | `(B19001_002E…007E) / B19001_001E` | The lower tail, not the mirror of the upper |
| `owner_occupied_share` | `B25003_002E / B25003_001E` | Owners can install home charging; renters usually cannot |
| `single_family_share` | `(B25024_002E + 003E) / B25024_001E` | A dedicated space and a circuit |
| `multifamily_share` | `(B25024_004E…009E) / B25024_001E` | Shared or absent parking is a different problem, not the complement |
| `zero_vehicle_household_share` | `(B25044_003E + 010E) / B25044_001E` | A household with no vehicle is not a prospect |
| `vehicles_per_household` | Binned mean over B25044, top category read as 5 | A multi-vehicle household can replace one without losing mobility |
| `drove_alone_share` | `B08301_003E / B08301_001E` | Car dependence |
| `public_transit_share` | `B08301_010E / B08301_001E` | Lower vehicle demand, different parking |
| `worked_from_home_share` | `B08301_021E / B08301_001E` | Shifts charging toward the residence |
| `mean_commute_minutes` | Binned mean over B08303; top bin (90+) read as 100 | Proxies daily driving distance |
| `bachelors_plus_share` | `(B15003_022E…025E) / B15003_001E` | Consistent correlate of early adoption |

**D2 is enforced structurally, not by prose.**
`pipeline.model.features.assert_primary_feature_set_is_clean` executes every feature
against a recording row and asserts that the input keys it actually touched are a subset
of the declared ACS variables plus land area. A feature that reached for a charger count
fails there even if its name and description said nothing. An earlier substring check was
worse than useless: it rejected "means of transportation to work" because
"transportation" contains "port".

**Missing data is recorded, never silently defaulted (D8).** The Census jam value
`-666666666` and blanks become `None`; a share with a zero denominator becomes `None`.
Imputation happens once, explicitly, filling with the national median and returning a
per-row count of how many features were filled.

### 2.3 The estimator, and why this one

CLAUDE.md §7.3 forbids hard-coding the estimator. Five candidates were fitted, and the
winner was chosen by a rule pre-registered in
`docs/evidence/P3-0_phase3_preregistration.md` §5 **before any candidate was run**:
lowest EV-weighted WAPE in leave-one-state-out validation, ties inside one percentage
point broken toward the simpler model.

| Candidate | Aggregate WAPE (state-total-reconciled) |
|---|---:|
| `poisson_glm` — Poisson GLM, log link, households as exposure | **0.3312** |
| `boosted_poisson` — gradient-boosted trees, Poisson loss | 0.3320 |
| `ridge_log_rate` — ridge on `log1p` of the rate | 0.3789 |
| `baseline_population_share` — EVs spread like people | 0.7096 |
| `baseline_household_share` — EVs spread like households | 0.7119 |

**`poisson_glm` is the published estimator.** It and the boosted model are 0.0008 apart,
inside the tie-break band, so the pre-registered rule selects the simpler and more
interpretable of the two. Both beat both baselines by more than a factor of two.

The target is a **rate with households as the exposure**, so predicted count is
`rate × households`. Fitting `count / exposure` with `sample_weight = exposure` is
algebraically a Poisson regression with `log(exposure)` as an offset.

### 2.4 Fitting at the observed geography, not at tract grain

Eleven states publish registrations by USPS ZIP Code, three by county, one
(Washington) by census tract. The obvious move — allocate those counts down to tracts and
fit on tract rows — would **manufacture tract labels** from a crosswalk with a *measured*
17.94% EV-weighted total variation distance and then score a model on them.

Instead, ACS publishes features directly at tract, ZCTA and county grain, so each state
is fitted against the counts it actually publishes, at the geography it publishes them
at. **No pseudo-label is created anywhere in the fitting path.** The same feature code
computes every feature at every grain, so a comparison across grains is not measuring
definitional drift.

### 2.5 Reconciliation

Counties nest inside states exactly, and tracts inside counties exactly, because a tract
GEOID *is* its state and county codes followed by the tract code. Every constraint Phase 3
applies therefore **partitions** the tracts it constrains, and on a partition the exact
solution is a single proportional scaling — no iteration, no convergence question:

```
value_i  =  raw_i × (total_g / Σ_{j∈g} raw_j)      for each constraint group g
```

Where a group's raw estimates sum to zero the total is spread evenly across its members;
leaving it at zero would silently discard an observed total.

Constraint selection, per tract: **its county total where the state publishes county
observations, otherwise its state total**, at the AFDC vintage nearest that state's own
observation date. Measured residual across the national surface: **2.3 × 10⁻¹⁰**, with
zero unconstrained tracts.

Iterative proportional fitting is implemented and tested for constraint sets that
overlap rather than partition. It is **not applied**: binding tract estimates to ZIP
totals would need the ZIP→tract allocation, and evaluating that constraint set properly
is its own piece of work (`docs/FUTURE_WORK.md`).

**Vintage alignment matters more than it looks.** Reconciling North Carolina's June 2024
snapshot to the 2025 total attributes eighteen months of fleet growth to model error:
−45.27% against the 2025 vintage, −5.66% against the contemporaneous 2023 one.

### 2.6 Uncertainty

Five components, each normalised to `[0,1]`, combined as a weighted arithmetic mean with
`w = 0.2` each:

| Component | Definition |
|---|---|
| `prediction_interval` | Bootstrap 10th–90th percentile half-width `h`, expressed as `h / (h + max(estimate, 1))`. The bootstrap resamples the **training areas**, because the dominant uncertainty is which areas were observed at all |
| `out_of_distribution` | Mahalanobis distance from the training feature distribution, mapped to `[0,1]` by its empirical CDF |
| `reconciliation_movement` | `|reconciled − raw| / (reconciled + raw + 1)` |
| `allocation_error` | The **measured** statewide tract-level TVD of the transformation that constrains the value — see §2.7 |
| `source_degradation` | Share of contributing sources whose contract status is not `confirmed` |

**The weights are equal by declaration, not by calibration.** That is stated wherever the
score is published, they live in `pipeline/config/thresholds.yml`, and a
weight-sensitivity report ships with the score (D7). Presenting hand-chosen weights as
calibrated is CLAUDE.md §18 anti-pattern 4; the defence is to say plainly that they are
not calibrated.

**The weights are not tuned against validation results.** The uncertainty-calibration
curve is a check on the score, and tuning the score until the check passes would destroy
the only thing the check was for.

### 2.7 The geographic transformation penalty is measured, not chosen

CLAUDE.md §7.4 component 5 forbids hard-coded numeric penalties and requires the penalty
to be derived from a measurement. Washington's vehicle records carry a **ZIP, a county and
a tract on the same row**, so all three transformations are measurable on the same
vehicles against the observed tract distribution.

The metric is the **statewide tract-level TVD**: rebuild the whole state's tract vector
from each transformation and compare it against the observed one. A within-group mean is
*not* comparable across grains — a ZIP's residual error spreads over a few adjacent
tracts while a state's spreads over every tract in the state — and using one produced an
ordering that appeared to contradict the specification.

| Grain | Method | Statewide tract TVD |
|---|---|---:|
| `native_tract` | identity | 0.0000 |
| `zip_anchored` | HUD `res_ratio` | **0.1621** |
| `zip_anchored` | household share | 0.2100 |
| `county_anchored` | household share | **0.2367** |
| `state_total_only` | household share | **0.3049** |

The ordering CLAUDE.md §7.4 predicts holds, and `assert_ladder_ordering` checks it rather
than assuming it. Group membership comes from geography alone — GEOID nesting for county
and state, the HUD crosswalk for ZIP — never from the observed records, which would hand
each method the answer.

### 2.8 Evidence grain, estimate method and tier

Two orthogonal fields, never collapsed (amendment A2).

`evidence_grain` records the finest observed evidence that **constrains the published
value**: `native_tract` (Washington, where the observation is published as-is),
`county_anchored`, or `state_total_only`.

**`zip_anchored` does not appear in the published surface.** Eleven states publish by ZIP
and those observations do real work — they train the model and they are what
leave-one-state-out scores against — but Phase 3 allocates no ZIP count onto a tract, so
no tract value is anchored to a ZIP total. Labelling one `zip_anchored` would claim
evidence the number does not rest on. A consequence worth stating: **no tract carries a
ZIP- or county-derived allocated value at all**, so the requirement that no such value be
labelled `directly_observed` holds by construction.

Tiers are presentation over the continuous score and are **never geography-based**:
Tier A is **"sub-state anchored"** and is never labelled "observed" (amendment A3);
Tier B and C split the `state_total_only` tracts at the 0.75 quantile of the continuous
score among those tracts, a boundary fixed in advance and not moved to change the tier
mix.

### 2.9 The supply-feature ablation

The one place Phase 2 supply outputs may enter a model, run over the eleven ZIP-grain
states and reported under its own heading. Results in
`docs/reports/PHASE_3_REPORT.md` §9.

---

## 3. Supply and access (Phase 2)

See `docs/reports/PHASE_2_REPORT.md` for the full derivation. The two rules that bind
every later phase:

- **Generic service capacity** uses the *maximum* resolved connector power on a
  single-port unit, never the sum of mutually alternative connectors. Naive summing
  overstates national capacity by 2,104,242 kW (10.69%).
- **Charging level comes from the source's own `charging_level` field**, never from a
  connector name. NEMA types are connector standards, not level designations.
