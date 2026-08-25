# Phase 1 status — SUPERSEDED, phase complete

> **This file is superseded.** It recorded a mid-implementation pause. Phase 1 is now
> complete and its gate has run; see `docs/reports/PHASE_1_REPORT.md`. The content
> below is preserved as the record of where work stopped and what was outstanding, so
> the resume path stays auditable. Every item listed as remaining was completed.

Historical state at the pause: `241 passed, 7 failed`.

## Done and committed

| Deliverable | State |
|---|---|
| `pipeline/quality/identifiability.py` | **Complete.** Eight measurements, 100% coverage. Decision rules fired: no unit identity, `ports` not populated, connectors at `(record_key, connector_type)` grain |
| `pipeline/quality/copy_lint.py` | **Complete.** 15 rules, 100% coverage, repository clean |
| `pipeline/quality/registration_checks.py` | **Complete.** All seven corrected-G9 properties, including the negative test that a low-confidence label cannot come from unusualness alone |
| `pipeline/sources/base.py`, `catalog.py` | **Complete.** A15 enforced structurally by `assert_lossless` |
| `pipeline/spatial/clustering.py` | **Complete.** DBSCAN, eps 50 m |
| `pipeline/transform/` (16 SQL models) | **Complete.** Fixture build runs end to end |
| `pipeline/schemas/canonical.py` | **Complete.** Six pandera schemas, all validating |
| `pipeline/build.py` | **Complete.** Two-state fixture build works |
| `tests/regression/test_domain_rules.py` | **Written, 7 failing** — see below |

## The 7 failing tests, and why

None indicates a defect in shipped pipeline code. Five are test-side errors of mine;
two need a module that does not exist yet.

| Test | Cause | Fix |
|---|---|---|
| `test_g6_iea_usa_projection_years...` | My filter assumes a `region == "USA"` value that the IEA file may spell differently | Inspect the actual `region` vocabulary, correct the filter |
| `test_g7_iea_mode_has_four_values` | Same: asserted an exact 4-value set without checking the delivered file first | Read the real distinct values, assert those |
| `test_g9_property_5_anomaly_screening_executes` | My synthetic population makes no state exceed z=3, so the screen returns empty | Use a population vector that actually produces an outlier |
| `test_g9_property_6_anomalies_surface...` | Same root cause | Same fix |
| `test_g12_no_code_path_calls_json_load...` | Over-broad guard: it flags `seed_inventory.py` and `catalog.py`, which legitimately name the file without parsing it | Narrow to detecting `json.load` on that path specifically |
| `test_g13_county_names_collide...` | **`pipeline/spatial/geography.py` does not exist yet** | Build it (see below) |
| `test_g14_the_pipeline_splits...` | `str_split` in DuckDB returns a JSON-encoded string through `fetch_df`, not a Python list | Assert on the DuckDB value, or decode before asserting |

## Remaining Phase 1 work, in order

1. Fix the seven failures above.
2. **`pipeline/spatial/geography.py`** — county FIPS lookup (G13) and explicit source
   geography declaration; then **`crosswalk.py`** for weighted ZIP/ZCTA→tract and
   county→tract allocation with `evidence_grain` / `estimate_method` stamped per row.
   No allocation *error* measurement — that is the Phase 3 boundary.
3. **A-0.5 provenance investigation** (one working session, budget fixed). Decisive
   test: compare an Internet Archive capture of `?year=2020` against today's
   `?year=2020`. Resolve, or record `historical_vintage_semantics: unresolved` with
   preserved evidence.
4. **Determinism test** — semantic hash equality across two pinned runs, volatile
   metadata normalised out; live-refresh behaviour reported separately (A14).
5. **Unit tests** for `sources/`, `transform/`, `spatial/`, `build.py` to reach the
   coverage tiers: 100% line and branch on `pipeline/spatial/`, ≥85% on
   `pipeline/sources/` and `pipeline/transform/`, ≥70% repository-wide.
6. **Smoke-forward test** for Phase 2: trivial rung-1 power resolution over the real
   canonical `charging_units` table.
7. **`make gate PHASE=1`**, then `docs/reports/PHASE_1_REPORT.md`, then stop.

## Findings to carry into the report

- **AFDC `port_count` is 1 for all 292,756 units.** An AFDC charging unit *is* one
  port; no cabinet grain exists in the source. Worth the owner's attention: the §6.1
  five-level hierarchy has two levels the data cannot support.
- **The JSON API exposes 8 connector standards; the CSV export exposes 5**, dropping
  NEMA515/520/1450 (Level 1). Phase 1 ingests the JSON for that reason.
- 16,610 units expose more than one connector standard on a single port, led by
  CHADEMO+J1772COMBO (7,071) and J1772COMBO+TESLA (5,168).
- Fixture build: 1,029 MN stations → 780 sites (249 co-located, G4 working);
  520 raw registration rows → 510 after G8 removes ten total rows.
