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
| A-0.5 | Each AFDC annual registration page is a contemporaneous snapshot of that year rather than a retrospective reconstruction from current VIN data. | Not stated by the publisher. If it is retrospective, the series is survivorship-affected and its use at a backtest cutoff needs a caveat. **This is the weakest link in the D1 vintage story.** | Phase 5 | OPEN |
| A-0.6 | Block-group population-weighted centroids are sufficient for §7.5 access and §7.6 allocation, or, if not, TIGER blocks joined to P.L. 94-171 block population yield genuine block-level weights at acceptable cost. | No ready-made block-level population-weighted centroid product exists (HTTP 404, verified). §7.5 and §7.6 word the requirement differently. | Phase 2 | OPEN |
| A-0.7 | ZIP-code registration counts from the 11 ZIP-grain Atlas states can be reallocated to census tracts with acceptable error using a public ZIP-to-tract crosswalk. | ZIP Code Tabulation Areas do not nest inside tracts. 11 of the 16 states with sub-state data are ZIP-grain; only Washington is natively tract-grain. | Phase 3 | OPEN |
| A-0.8 | The delivered HIFLD transmission GeoJSON (94,216 features) and the live HIFLD service (52,244 features) are the same underlying dataset at different vintages or filters, so either may be used provided the extract is labelled. | Counts differ by 41,972 features. The publisher documents no reason. | Phase 1 | OPEN |
| A-0.9 | A national electric substation dataset obtainable at zero recurring cost exists somewhere Phase 0 did not look, or §7.8 candidate filtering and §7.9 grid proximity can be respecified without one. | Five searches found no national layer; the best candidate holds 128 features. **Blocks §7.8 and §7.9 as specified.** | Phase 4 | OPEN |
| A-0.10 | The Internet Archive copy of CEJST v2.0 remains retrievable, or a local mirror is taken before it stops being. | The live host has no DNS record; the archive is currently the only path found. | Phase 6 | OPEN |
| A-0.11 | A machine-retrievable FHWA traffic dataset URL exists and is stable enough to automate. | Only the HPMS landing page was located in Phase 0. Traffic is named in §10.2.3 as part of the reduced backtest feature set. | Phase 5 | OPEN |
| A-0.12 | The number of genuinely usable Tier A states is large enough for leave-one-state-out validation (§10.1) to have meaningful statistical power. | 16 distinct states have sub-state registration data, but usability at tract grain depends on A-0.7. If the usable count falls to 3 or fewer, the LOSO design must be reconsidered through a formal plan change rather than continued quietly. | Phase 3 | OPEN |
| A-0.13 | Bounded probe samples are representative enough that expected row-count ranges derived from them detect real drift without false alarms. | Expected ranges for the Atlas states, ACS bulk and CEJST come from a 65,536-byte sample widened by the provisional ±20% tolerance, not from full files. Per-source tolerances should replace the default as behaviour is observed. | Phase 1 | OPEN |
| A-0.14 | Bounded, cached replay fixtures (3.4 MB across 47 sources) stay sufficient as a deterministic gate substrate as later phases need more of each source. | The committed fixtures hold only the head of each large file. A phase needing full-file behaviour will need a different strategy. | Phase 1 | OPEN |
| A-0.15 | The delivered seed files remain byte-identical for the life of the project, so frozen fixture expectations never need to drift. | SHA-256 of all ten recorded in `data/seed/seed_inventory.json`; enforced by `test_the_seed_inventory_still_matches_the_delivered_bytes`. | every phase | **CONFIRMED** in Phase 0 |

---

## Re-checked at this gate

Not applicable to Phase 0: this is the first phase and there are no prior assumptions.
