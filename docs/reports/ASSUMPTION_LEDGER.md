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
