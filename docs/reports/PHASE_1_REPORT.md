# Phase 1 Report — Ingestion and Canonical Model

## 0. Report metadata

| Field | Value |
|---|---|
| Phase | 1 — Ingestion + canonical |
| Date | 2026-08-24 |
| Gate status | **PASS** |
| Commit | `gate(phase-1): PASS` |
| Duration | ~2.25 part-time weeks planned; delivered within plan |
| Prepared by | Claude Code |

---

## 1. Context for a reader with zero prior knowledge

### 1.1 What this project is

**VoltGap** is an open, statically hosted decision-support application that answers one
question: *given a budget and a set of policy priorities, where should the next EV
charging infrastructure be built in the United States, and how confident should we be
in that answer?* Its users are infrastructure planners, charge point operators, state
energy offices, and researchers. Its primary output is a ranked, budget-feasible
portfolio of candidate hexagonal sites with scores, uncertainty bands, tradeoff
context, and CSV/GeoJSON export.

It is explicitly **not** a general EV statistics browser, a consumer charger finder, a
vehicle comparison tool, or a real-time charger availability map.

The project operates under eight prime directives. Three matter repeatedly in this
report. **D2** forbids any supply-derived feature (charger counts, port counts, charger
density, network presence, distance to nearest charger) from entering the primary
demand model, because existing infrastructure is an *outcome* of prior investment
decisions and using it to predict demand would launder historical deployment patterns
into "need". **D8** requires that when a source is unavailable the pipeline degrades
explicitly and never substitutes a plausible default silently. **D4** requires zero
recurring cost: free tiers only.

### 1.2 The architecture in one paragraph

An offline Python pipeline retrieves public data, transforms it through a file-based
DuckDB warehouse (staging → intermediate → marts), and writes static artifacts
(Parquet, PMTiles, JSON) to object storage. A statically exported browser application
reads those artifacts directly; there is no server and no database at request time.
That is why constraints such as artifact size budgets, offline determinism, and
schema validation before publication exist: once an artifact ships, nothing downstream
can correct it.

### 1.3 What the previous phase produced

Phase 0 was the source contract. It produced a re-runnable source probe
(`pipeline/discovery/probe.py`), a stable human-reviewed contract (`SOURCES.yml`, 57
sources) with a generated observation sidecar (`SOURCES.observed.json`), hashed
evidence artifacts for ten research findings, and a provenance inventory of the ten
delivered seed files. Its gate passed with 100% line and branch coverage on
`pipeline/discovery/`.

Phase 0's substantive findings, all of which Phase 1 depends on:

- The NREL developer host `developer.nrel.gov` was retired on 29 May 2026; the API is
  now at `developer.nlr.gov`.
- AFDC exposes per-connector power. Rung-1 (reported) power coverage is **82.76%** of
  ports nationally and **88.11%** on public + operational supply, far above the 40%
  threshold that would have triggered a prominent limitation.
- The NREL county home-charging dataset is a **parametric scenario surface** — 942,600
  rows = 3,142 counties × 3 access scenarios × 100 EV-share-of-stock levels — not a
  dated observation. It is therefore excluded from the primary siting objective.
- Historical state EV registration vintages **do** exist: ten annual AFDC vintages,
  2016–2025, covering all three planned backtest origins.
- **Sixteen** states publish sub-state registration data: 11 at ZIP grain and 3 at
  county grain via Atlas EV Hub, plus Washington at census-tract grain and Illinois
  and Minnesota from the delivered seed files.
- **No national substation dataset could be located.** Five searches failed; the best
  candidate held 128 features against a national figure on the order of 55,000–80,000.
- Domain rule **G9 was factually wrong** against the delivered data.

The Phase 0 review authorised sixteen specification amendments (A0–A16), recorded in
`CLAUDE.md` §19. Phase 1 was gated on those being applied first.

### 1.4 What this phase was supposed to do

Quoting the specification's Phase 1 acceptance criteria:

> One command rebuilds every canonical table from a clean clone. All G1–G14 regression
> tests pass, including corrected G9 (§5) verifying vintage resolution, jurisdiction
> coverage, non-negativity, total reconciliation, anomaly screening execution,
> review-flag surfacing, and that a low-confidence label cannot be assigned on
> statistical unusualness alone. Every canonical table validates against its schema.
> Entity hierarchy resolves with no orphans, and **no `ports` row exists whose identity
> the source does not support** (§6.1.1). Port-identifiability analysis completed with
> all six measurements reported numerically. Every registration observation carries
> `evidence_grain` and `estimate_method` (§7.4.1), and **no ZIP-derived or
> county-derived tract value is labelled `directly_observed`**. Source geography
> declared explicitly per source; no USPS ZIP Code silently treated as a ZCTA (§7.5.1).
> D3 terminology copy lint exists and passes. A-0.5 investigation yields either an
> evidence-backed classification or an explicitly recorded
> `historical_vintage_semantics = unresolved` with preserved evidence. Row counts
> within the `SOURCES.yml` expected ranges. Determinism check: two runs produce
> identical checksums.

Phase 1 explicitly does **no model fitting**. No propensity model, no reconciliation,
no siting, no uncertainty scoring.

---

## 2. What was built

### 2.1 Modules created or changed

| Path | Purpose | Lines | Key public functions |
|---|---|---:|---|
| `pipeline/quality/identifiability.py` | Eight-measurement unit/port/connector identifiability analysis | 205 | `analyse`, `analyse_station_json`, `scan_header_for_identifiers` |
| `pipeline/quality/copy_lint.py` | D3 and §11.5 terminology guard, 15 rules | 205 | `lint_text`, `lint_paths`, `is_allowlisted`, `main` |
| `pipeline/quality/registration_checks.py` | Corrected G9: seven properties | 245 | `check_registrations`, `screen_per_capita`, `screen_year_over_year`, `assign_confidence` |
| `pipeline/sources/base.py` | Adapter framework; A15 enforced structurally | 355 | `StagedTable.assert_lossless`, `DelimitedSource`, `JsonRecordsSource`, `HtmlTableSource`, `NestedUnitsSource` |
| `pipeline/sources/catalog.py` | 38-entry Phase 1 retrieval catalogue | 150 | `all_sources`, `seed_sources`, `afdc_sources`, `atlas_sources` |
| `pipeline/spatial/geography.py` | Source-geography declaration; county FIPS (G13) | 150 | `county_fips_lookup`, `resolve_county_fips`, `evidence_grain_for`, `estimate_method_for` |
| `pipeline/spatial/crosswalk.py` | Weighted ZIP/ZCTA→tract allocation with provenance | 215 | `load_zcta_tract_links`, `zip_to_zcta`, `allocate`, `allocate_many`, `conservation_error` |
| `pipeline/spatial/clustering.py` | DBSCAN site resolution, eps 50 m | 135 | `cluster_sites`, `haversine_m` |
| `pipeline/transform/runner.py` | DuckDB layered execution and semantic hashing | 200 | `Warehouse`, `discover_models`, `semantic_hash`, `build_context` |
| `pipeline/schemas/canonical.py` | Six pandera schemas | 195 | `validate`, `validate_all` |
| `pipeline/build.py` | One-command canonical rebuild | 265 | `build`, `validate_marts`, `union_staged`, `resolve_sites` |
| `pipeline/transform/models/**` | 16 SQL models across three layers | — | — |

Deliberately **not** built, each with its reason:

| Not built | Reason |
|---|---|
| `pipeline/sources/egrid.py` | Amendment A8: Optional/Future Work, no Core consumer |
| `pipeline/sources/hifld_substations.py` | Amendment A6: no national dataset exists |
| `pipeline/sources/fhwa_traffic.py` | Amendment A16: Optional/Future Work, no surviving Core consumer |
| `pipeline/sources/eia_prices.py` | Optional tier (§7.11) |
| `ports` / `connectors` canonical tables | The identifiability analysis found no stable identity; see §9.1 |

### 2.2 Key implementations, quoted

**The A15 guard.** Retrieval and staging preserve source rows. This is enforced
structurally rather than by convention, so an adapter physically cannot filter:

```python
# pipeline/sources/base.py
@dataclass
class StagedTable:
    source_id: str
    columns: tuple[str, ...]
    rows: list[dict[str, str]]
    vintage: SourceVintage
    source_row_count: int

    def assert_lossless(self) -> StagedTable:
        """Enforce A15. Called by every adapter before returning."""
        self.assert_unique_columns()
        if len(self.rows) != self.source_row_count:
            raise LossyStagingError(
                f"{self.source_id}: staging produced {len(self.rows)} rows from "
                f"{self.source_row_count} source rows. Retrieval and staging must "
                "preserve source rows; business filtering belongs in the intermediate "
                "layer (CLAUDE.md section 9)."
            )
        return self
```

**The synthetic key.** No physical unit identity is claimed anywhere:

```python
# pipeline/sources/base.py, NestedUnitsSource
row: dict[str, str] = {
    "charging_unit_record_key": f"{station.get('id')}:{ordinal}",
    "station_id": _flatten(station.get("id")),
    "record_ordinal": str(ordinal),
}
```

with the docstring stating the limitation in full:

> A synthetic `charging_unit_record_key` is assigned as `{station_id}:{ordinal}`. It is
> **per-snapshot and carries no longitudinal meaning**. The ordinal is row order within
> the station, which is the only thing that separates identical units, and row order is
> not guaranteed stable across refreshes. This key must never be used to track a unit
> over time.

**G9 property 7**, the load-bearing correction from the Phase 0 review:

```python
# pipeline/quality/registration_checks.py
def assign_confidence(
    jurisdiction: str,
    review_flags: Sequence[ReviewFlag] = (),
    corroborating_defects: Sequence[DefectKind] = (),
) -> Confidence:
    """Property 7: a low-confidence label requires corroborating evidence of a defect.

    Statistical or geographic unusualness alone is **never** sufficient. A state whose
    EV adoption genuinely differs from its neighbours is not a data-quality problem,
    and labelling it one would push a fabricated signal into the uncertainty model.
    """
    if corroborating_defects:
        return Confidence.LOW
    # review_flags are deliberately ignored here. They exist to route a jurisdiction
    # to a human, not to downgrade it.
    _ = (jurisdiction, review_flags)
    return Confidence.OK
```

**The ZIP≠ZCTA boundary**, isolated so it cannot be applied silently:

```python
# pipeline/spatial/crosswalk.py
def zip_to_zcta(zip_code: str, known_zctas: Mapping[str, object]) -> str:
    """Approximate a USPS ZIP Code by the like-numbered ZCTA.

    This is an **approximation, not an identity**. A USPS ZIP Code is a collection of
    mail-delivery routes; a ZCTA is an area built from census blocks. Many ZIPs have a
    same-numbered ZCTA, but point ZIPs (single large recipients) and PO-Box-only ZIPs
    have none, and the boundaries never match exactly.
    """
    code = normalise_zip(zip_code)
    if code not in known_zctas:
        raise GeographyError(
            f"USPS ZIP {code} has no like-numbered ZCTA. It is probably a point or "
            "PO-Box ZIP with no areal equivalent; it cannot be allocated to tracts "
            "and must be reported as unallocatable rather than dropped."
        )
    return code
```

**G8 removal in the intermediate layer**, which is A15's worked example. The adapter
ingests the published total row unchanged; this is where it is removed:

```sql
-- pipeline/transform/models/intermediate/int_state_totals.sql
SELECT vintage, jurisdiction, ev_count, 'stock' AS measure_type
FROM stg_state_ev_registrations
WHERE jurisdiction NOT IN ('United States', 'Total')
  AND jurisdiction IS NOT NULL AND jurisdiction <> '' AND ev_count IS NOT NULL
```

**Semantic determinism** (CLAUDE.md §14.1, amendment A14):

```python
# pipeline/transform/runner.py
VOLATILE_COLUMNS: frozenset[str] = frozenset({
    "computed_at", "retrieved_at", "last_successful_retrieval", "elapsed_ms",
})

def semantic_hash(self, tables: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for table in sorted(tables):
        described = self.connection.execute(f'DESCRIBE "{table}"').fetchall()
        keep = [str(d[0]) for d in described if str(d[0]) not in VOLATILE_COLUMNS]
        digest.update(f"TABLE:{table}:{','.join(keep)}\n".encode())
        if not keep:
            continue
        projection = ", ".join(f'CAST("{c}" AS VARCHAR)' for c in keep)
        rows = self.connection.execute(f'SELECT {projection} FROM "{table}"').fetchall()
        for row in sorted(str(tuple(r)) for r in rows):
            digest.update(row.encode()); digest.update(b"\n")
    return digest.hexdigest()
```

### 2.3 Data artifacts produced

Two-state fixture build (Minnesota AFDC + Minnesota Atlas + all ten national
registration vintages + the frozen seed files):

| Layer | Model | Rows |
|---|---|---:|
| staging | `stg_afdc_stations` | 1,029 |
| staging | `stg_afdc_charging_units` | 2,957 |
| staging | `stg_atlas_registrations` | 903,083 |
| staging | `stg_state_ev_registrations` | 520 |
| staging | `stg_seed_state_ev_registrations` | 52 |
| intermediate | `int_stations` | 1,029 |
| intermediate | `int_charging_units` | 2,957 |
| intermediate | `int_charging_unit_connectors` | 23,656 |
| intermediate | `int_state_totals` | 510 |
| intermediate | `int_observed_subregion_ev` | 17,146 |
| **mart** | `mart_sites` | **780** |
| **mart** | `mart_stations` | **1,029** |
| **mart** | `mart_charging_units` | **2,957** |
| **mart** | `mart_charging_unit_connectors` | **23,656** |
| **mart** | `mart_state_totals` | **510** |
| **mart** | `mart_observed_subregion_ev` | **17,146** |

Three of those numbers carry meaning rather than being mere counts:

- **1,029 stations → 780 sites.** 249 stations are co-located with another station and
  share a site. That is domain rule G4 working: exact coordinate duplicates are
  co-located multi-network infrastructure, aggregated for coverage and summed for
  capacity, never deleted.
- **520 → 510 registration rows.** Ten published "United States" total rows, one per
  vintage, are removed in the intermediate layer. 51 jurisdictions × 10 vintages = 510.
- **2,957 units → 23,656 connector rows.** 2,957 × 8 connector standards. Rows with a
  zero port count are retained so that "this unit does not offer this standard" stays
  distinguishable from "this unit was never asked about it".

### 2.4 Schemas, quoted in full

Every canonical table has a strict, coercing pandera schema. A violation fails the
build and blocks publication (CLAUDE.md §9). Several schemas encode a domain rule
directly rather than merely typing a column.

```python
# pipeline/schemas/canonical.py
PROVENANCE = {
    "computed_at": Column(str, nullable=False),
    "source_vintages": Column(str, nullable=False),
}

MART_CHARGING_UNITS = _schema({
    "charging_unit_record_key": Column(str, nullable=False, unique=True),
    "station_id": Column(str, nullable=False),
    "site_id": Column(str, nullable=True),
    "record_ordinal": Column(int, Check.ge(0)),
    "state": Column(str, nullable=True),
    "status_code": Column(str, nullable=True),
    "access_code": Column(str, nullable=True),
    "ev_network": Column(str, nullable=True),
    "charging_level": Column(str, nullable=True),
    "port_count": Column(int, Check.ge(0)),
    "connector_port_sum": Column(int, Check.ge(0)),
    "is_multi_connector_port": Column(bool),
    "is_public_operational": Column(bool),
    # The two flags that stop a consumer treating the record key as physical
    # identity. Both are constants, asserted rather than merely documented.
    "key_is_synthetic": Column(bool, Check.eq(True)),
    "has_longitudinal_identity": Column(bool, Check.eq(False)),
})

MART_STATE_TOTALS = _schema({
    "state": Column(
        str,
        # G8: the published total row must never survive into a mart.
        Check(lambda s: ~s.isin(["United States", "Total"]),
              error="G8: a published total row reached mart_state_totals"),
    ),
    "vintage": Column(str, nullable=False),
    "ev_count": Column(int, Check.ge(0)),
    "measure_type": Column(str, Check.eq("stock")),
}, unique=["state", "vintage"])

MART_OBSERVED_SUBREGION_EV = _schema({
    "state": Column(str, nullable=False),
    "source_geography_type": Column(str, Check.isin(SOURCE_GEOGRAPHIES)),
    "source_geography_id": Column(str, nullable=False),
    "vintage": Column(str, nullable=True),
    "dmv_snapshot_id": Column(str, nullable=True),
    "is_latest_snapshot": Column(bool),
    "ev_count": Column(int, Check.ge(0)),
    "evidence_grain": Column(str, Check.isin(EVIDENCE_GRAINS)),
    "estimate_method": Column(str, Check.isin(ESTIMATE_METHODS)),
})

MART_STATIONS = _schema({
    "station_id": Column(str, nullable=False, unique=True),
    "site_id": Column(str, nullable=True),
    # G2: Status Code has exactly three values.
    "status_code": Column(str, Check.isin(["E", "T", "P"]), nullable=True),
    "latitude": Column(float, Check.in_range(-90, 90), nullable=True),
    "longitude": Column(float, Check.in_range(-180, 180), nullable=True),
    "evse_count_l1": Column(int, Check.ge(0)),
    "evse_count_l2": Column(int, Check.ge(0)),
    "evse_count_dcfc": Column(int, Check.ge(0)),
    "ev_connector_types": Column(object, nullable=True),
    "is_operational": Column(bool),
    "is_public": Column(bool),
    "is_public_operational": Column(bool),
    # ... station_name, state, city, zip, access_code, ev_network, open_date,
    #     facility_type omitted here for length; all present and typed
})

MART_SITES = _schema({
    "site_id": Column(str, nullable=False, unique=True),
    "latitude": Column(float, Check.in_range(-90, 90), nullable=True),
    "longitude": Column(float, Check.in_range(-180, 180), nullable=True),
    "station_count": Column(int, Check.ge(1)),
    "network_count": Column(int, Check.ge(0)),
    "state": Column(str, nullable=True),
    "public_operational_stations": Column(int, Check.ge(0)),
    # G1: capacity comes from unit counts, never from counting station rows.
    "charging_unit_count": Column(int, Check.ge(0)),
    "public_operational_unit_count": Column(int, Check.ge(0)),
})

MART_CHARGING_UNIT_CONNECTORS = _schema({
    "charging_unit_record_key": Column(str, nullable=False),
    "connector_type": Column(str, Check.isin(CONNECTOR_TYPES)),
    "connector_count": Column(int, Check.ge(0)),
    "power_kw": Column(float, Check.ge(0), nullable=True),
    "power_source": Column(str, Check.isin(["reported"]), nullable=True),
    "has_reported_power": Column(bool),
    "is_zero_power_anomaly": Column(bool),
    "charging_level": Column(str, nullable=True),
    "is_public_operational": Column(bool),
}, unique=["charging_unit_record_key", "connector_type"])
```

where `CONNECTOR_TYPES = ["J1772", "J1772COMBO", "CHADEMO", "TESLA", "J3271",
"NEMA515", "NEMA520", "NEMA1450"]`, `EVIDENCE_GRAINS = ["native_tract",
"zip_anchored", "county_anchored", "state_total_only"]`, `ESTIMATE_METHODS =
["directly_observed", "crosswalked", "modeled", "modeled_high_uncertainty"]`, and
`SOURCE_GEOGRAPHIES = ["usps_zip", "zcta", "county", "tract", "state"]`.

---

## 3. Decisions made and why

| Decision | Options considered | Chosen | Rationale | Reversible? |
|---|---|---|---|---|
| Charging-unit retrieval path | AFDC CSV export (contracted in Phase 0) vs the JSON REST endpoint | **JSON** | Only the JSON carries a genuine unit-level `port_count` and the full eight-connector taxonomy. The CSV exposes five connector columns and station-level EVSE totals, silently dropping NEMA515/520/1450, all Level 1. Same source, different retrieval path. See §12 Q1 | Yes |
| `ports` and `connectors` tables | Populate with synthetic rows vs leave unpopulated | **Unpopulated** | Pre-registered decision rule fired: no stable identity is recoverable at any level. Manufacturing `port_001` rows would fabricate observed physical objects (§6.1.1) | Yes, if AFDC ever adds identifiers |
| Site resolution | Coordinate rounding vs DBSCAN | **DBSCAN, eps 50 m, haversine** | Mandated by §6.1. Rounding creates arbitrary grid-boundary splits: two stations 8 m apart can straddle a rounding boundary. A test asserts this exact case | No |
| Crosswalk weight basis | Land area vs population vs housing units | **Land area, declared per row** | The only free, unauthenticated national weight available in Phase 1. It is the *weakest defensible* basis and is recorded as `allocation_weight_basis` on every row so Phase 3 can measure its error and replace it. See §10 | Yes, by design |
| G2/G3 filtering placement | Filter in `int_stations` vs carry as flags | **Flags, not a WHERE clause** | The canonical table keeps every station and downstream models choose their own filter explicitly. Filtering at the canonical layer would make "how many private stations are there" unanswerable | Yes |
| Zero-count connector rows | Drop vs retain | **Retain** | Keeps "this unit does not offer this standard" distinguishable from "this unit was never asked". Costs 8× row count on a small table | Yes |
| Copy-lint allowlisting | Per-line markers only vs whole-file and glob | **Both** | Phase reports must be able to quote a prohibited phrase in order to record that it is prohibited. Tracked as an accepted weakening in §10 | Yes |
| Determinism gate | Byte equality vs semantic hash | **Semantic hash with volatile columns excluded** | Amendment A14. Byte equality is impossible once every derived table carries `computed_at` | No |

---

## 4. Acceptance criteria verification (Gate part G-A)

| # | Criterion (quoted from spec) | Verifying test | What it asserts | Result | Evidence |
|---|---|---|---|---|---|
| 1 | "One command rebuilds every canonical table from a clean clone" | `make build-fixture` (gate step 8) | `python -m pipeline.build --fixture --offline` runs all 16 models and validates all 6 marts | PASS | 6 marts built, semantic hash `6e7d543fbcd4ce33…` |
| 2 | "All G1–G14 regression tests pass" | `tests/regression/test_domain_rules.py`, 39 tests | One test minimum per rule, plus `test_every_domain_rule_g1_to_g14_has_at_least_one_test` which fails if any rule lacks a test | PASS | 39/39 |
| 3 | "including corrected G9 … vintage resolution" | `test_g9_property_1_vintage_is_resolved` | `check_registrations(..., vintage=None).vintage_resolved is False` | PASS | — |
| 4 | "… jurisdiction coverage" | `test_g9_property_2_jurisdiction_coverage_is_complete` | 51 jurisdictions present; a 40-state subset fails | PASS | 51/51 |
| 5 | "… non-negativity" | `test_g9_property_3_counts_must_be_non_negative` | A −5 count sets `all_counts_non_negative False` and `passed False` | PASS | — |
| 6 | "… total reconciliation" | `test_g9_property_4_published_total_reconciles` | Sum equals the published total exactly; a +1 total fails; a missing total is `None`, not a failure | PASS | 3,555,445 = 3,555,445 |
| 7 | "… anomaly screening execution" | `test_g9_property_5_anomaly_screening_executes`, `..._year_over_year_screening_executes` | Both screens fire and produce flags | PASS | California flagged |
| 8 | "… review-flag surfacing" | `test_g9_property_6_anomalies_surface_as_diagnostic_review_flags` | Every flag carries `is_diagnostic_only: True`, and flags do not fail the structural check | PASS | — |
| 9 | "… a low-confidence label cannot be assigned on statistical unusualness alone" | `test_g9_property_7_low_confidence_cannot_come_from_unusualness_alone`, `test_no_number_of_review_flags_can_lower_confidence` | 50 extreme flags still yield `Confidence.OK`; only a `DefectKind` yields `LOW` | PASS | — |
| 10 | "Every canonical table validates against its schema" | `pipeline.build.validate_marts`, called inside `build()`; `test_validate_marts_returns_row_counts` | All 6 marts validate; the build raises `SchemaViolationError` otherwise | PASS | 6/6 |
| 11 | "Entity hierarchy resolves with no orphans" | `test_the_entity_hierarchy_joins_without_orphans` | Three LEFT JOIN counts are 0: units→stations, connectors→units, stations→sites | PASS | 0, 0, 0 |
| 12 | "**no `ports` row exists whose identity the source does not support**" | `test_no_ports_table_was_fabricated` | Neither `ports` nor `mart_ports` exists; every unit row has `key_is_synthetic True` and `has_longitudinal_identity False` | PASS | — |
| 13 | "Port-identifiability analysis completed with all six measurements reported numerically" | `tests/unit/test_identifiability.py`, 24 tests; artifact `docs/evidence/P1-1_identifiability.json` | Eight measurements (six required plus A13's two), reported for national and public+operational scopes | PASS | See §9.1 |
| 14 | "Every registration observation carries `evidence_grain` and `estimate_method`" | `MART_OBSERVED_SUBREGION_EV` schema `Check.isin`; `test_allocation_stamps_full_transformation_provenance` | Both columns non-null and drawn from closed vocabularies on all 17,146 rows | PASS | 17,146 rows |
| 15 | "**no ZIP-derived or county-derived tract value is labelled `directly_observed`**" | `test_only_a_tract_source_earns_directly_observed` | For every `SourceGeography` except `TRACT`, `estimate_method_for(source, TRACT)` is not `DIRECTLY_OBSERVED` | PASS | 5/5 geographies |
| 16 | "Source geography declared explicitly per source; no USPS ZIP Code silently treated as a ZCTA" | `test_every_atlas_state_has_a_declared_geography_and_column`, `test_usps_zip_is_never_labelled_zcta`, `test_zip_to_zcta_is_an_approximation_that_fails_loudly` | 14 declared geographies, none labelled `zcta`; the ZIP→ZCTA step raises on a missing ZCTA rather than returning nothing | PASS | 11 zip / 3 county |
| 17 | "D3 terminology copy lint exists and passes" | `pipeline/quality/copy_lint.py`; `test_the_repository_itself_is_clean`; gate step 6 | 15 rules over 71 files, exit 0 | PASS | 71 files clean |
| 18 | "A-0.5 investigation yields either an evidence-backed classification or an explicitly recorded `historical_vintage_semantics = unresolved` with preserved evidence" | `SOURCES.yml` finding F-11 + `coverage.historical_vintage_semantics` on all ten vintages; `test_every_finding_evidence_artifact_still_matches_its_recorded_hash` | Recorded as `stable_not_revised_within_observable_window` with `contemporaneity: unresolved`, evidence hashed | PASS | See §9.3 |
| 19 | "Row counts within the `SOURCES.yml` expected ranges" | `pipeline.discovery.probe --offline`, gate step 4 | Probe exits 0; no drift outside tolerance | PASS | 57 sources |
| 20 | "Determinism check: two runs produce identical checksums" | `tests/integration/test_determinism.py`, 8 tests | Semantic hash identical across two pinned runs; unaffected by `computed_at` or row order; moved by a genuine data change | PASS | See §9.5 |

**Criteria passed: 20/20.**

Criterion 18 deserves an explicit caveat rather than a bare PASS. The specification
allowed either a resolved classification *or* a recorded `unresolved`. The outcome is
**partial**: stability is established, contemporaneity is not. That is recorded
verbatim in the contract and is carried into Phase 5 as a stated limitation. It is
reported as PASS because the criterion asks for an evidence-backed outcome, and this
is one; it would be wrong to report it as a clean resolution.

---

## 5. Test and coverage evidence (Gate part G-B)

### 5.1 Suite summary

```
$ make gate PHASE=1

=== Phase 1 gate ===
--- 1. lint (ruff + mypy strict) ---
All checks passed!
Success: no issues found in 49 source files
--- 2. full test suite ---
400 passed, 1 skipped in 29.71s
--- 3. coverage thresholds ---
--- 4. prior gate suite (Phase 0) ---
32 passed ; determinism: identical
--- 5. smoke-forward test for Phase 2 ---
5 passed in 7.57s
--- 6. D3 copy lint ---
copy lint: clean (81 files, 15 rules)
--- 7. determinism (semantic, CLAUDE.md 14.1) ---
7 passed, 1 skipped
--- 8. one-command rebuild ---
16 models, 6 marts, semantic hash 6e7d543fbcd4ce336c35b28cb358a2f4bacdf972990256cf344e9adae22f0c60
=== Phase 1 gate: PASS ===
```

The single skip is `test_live_refresh_is_not_expected_to_be_byte_identical`, marked
`live` and deliberately excluded from the deterministic gate. It documents that a live
refresh producing different artifacts is not a determinism failure; asserting that
would require the network, which the gate must not depend on.

Test counts by area:

| Area | Tests |
|---|---:|
| `tests/unit/` — cache, measure, contract, probe, seed inventory, settings, registry | 189 |
| `tests/unit/` — copy lint, identifiability, registration checks | 84 |
| `tests/unit/` — spatial, sources, transform, schemas, build | 105 |
| `tests/regression/test_domain_rules.py` — G1–G14 | 39 |
| `tests/regression/test_source_findings.py` — Phase 0 criteria | 23 |
| `tests/integration/` — smoke-forward ×2, determinism | 22 |

### 5.2 Coverage by module

Measured with `--cov-branch` from a single instrumented run.

| Module | Statements | Missed | Branches | Partial | Cover | Required | Met? |
|---|---:|---:|---:|---:|---:|---|---|
| `pipeline/build.py` | 120 | 0 | 32 | 0 | **100%** | — | yes |
| `pipeline/config/settings.py` | 37 | 0 | 0 | 0 | **100%** | — | yes |
| `pipeline/discovery/` (6 modules) | 650 | 0 | 192 | 0 | **100%** | 100% | **yes** |
| `pipeline/quality/` (3 modules) | 287 | 0 | 64 | 0 | **100%** | 100% | **yes** |
| `pipeline/schemas/canonical.py` | 29 | 0 | 2 | 0 | **100%** | 100% | **yes** |
| `pipeline/sources/` (2 modules) | 211 | 0 | 46 | 0 | **100%** | ≥85% | **yes** |
| `pipeline/spatial/` (3 modules) | 207 | 0 | 52 | 0 | **100%** | 100% | **yes** |
| `pipeline/transform/runner.py` | 100 | 0 | 14 | 0 | **100%** | ≥85% | **yes** |
| **Repository total** | **1,641** | **0** | **402** | **0** | **100%** | ≥70% | **yes** |

`pipeline/model/` and `pipeline/validation/` do not exist yet; their 100% requirement
first binds in the phase that creates them (Phases 2 and 5 respectively).
`pipeline/spatial/` was created this phase, so its 100% requirement binds from now on.

### 5.3 Coverage exclusions

| Location | Reason for `pragma: no cover` | Justified? |
|---|---|---|
| `pipeline/discovery/cache.py` — `Fetcher.get` | Protocol declaration; the body is `...` and is never executed | Yes |
| `pipeline/discovery/probe.py` — `main` guard, `probe_local` path assertion | Module entry point; registry guarantees a path for local kinds | Yes |
| `pipeline/discovery/seed_inventory.py` — `main` | Thin CLI wrapper, exercised via `write_inventory` | Yes |
| `pipeline/quality/identifiability.py` — `main` | Thin CLI wrapper, exercised via `analyse_file` | Yes |
| `pipeline/build.py` — `main` | Thin CLI wrapper; the underlying `build()` is fully covered and the CLI is exercised by gate step 8 | Yes |
| `tests/regression/test_domain_rules.py` — gitignored GeoJSON skip | The 137 MiB file is excluded from version control by design, so a clean clone must skip rather than fail | Yes |

No unjustified exclusions.

**Two coverage gaps found real bugs rather than needing contrived tests.** In
`registration_checks.py`, the zero-deviation guard was `if deviation == 0`, comparing a
float to exact zero. Identical per-capita rates produce a deviation of ~1.4e-17, so the
guard never fired and every jurisdiction would then have been scored against a
near-zero denominator, flagging the whole file as anomalous. It now compares against a
tolerance. In `build.py`, a `load_registrations` parameter was uncovered because it was
also broken: `stg_state_ev_registrations.sql` reads the table it would have skipped, so
setting it False failed the staging layer rather than producing a smaller build. It was
removed rather than tested.

### 5.4 Notable tests, with assertions quoted

**The G9 correction, as a negative test.** This is the test that encodes the owner's
modification to Option A:

```python
def test_g9_property_7_low_confidence_cannot_come_from_unusualness_alone() -> None:
    """The load-bearing correction: an outlier is a diagnostic, not proof of a defect.

    A state's genuine EV adoption rate may differ sharply from its neighbours because
    of income, incentives, urbanisation, housing structure, climate, electricity
    prices or market maturity. Downgrading it would push a fabricated quality signal
    into the uncertainty model.
    """
    flags = [
        ReviewFlag("Oregon", "per_capita_z", "5.9 sd from the mean", 5.9),
        ReviewFlag("Oregon", "year_over_year", "9.00x between vintages", 9.0),
    ]
    assert assign_confidence("Oregon", flags) is Confidence.OK
    assert assign_confidence("Oregon", flags, []) is Confidence.OK
```

**The A15 guard, tested in both directions:**

```python
def test_dropping_a_row_raises() -> None:
    table = StagedTable("s", ("a",), [{"a": "1"}], vintage(), source_row_count=2)
    with pytest.raises(LossyStagingError, match="preserve source rows"):
        table.assert_lossless()

def test_g8_total_rows_never_reach_the_mart(fixture_warehouse: Warehouse) -> None:
    """The adapter ingests the total row (A15); intermediate removes it."""
    raw = scalar(fixture_warehouse,
        "SELECT count(*) FROM raw_afdc_state_ev_registrations "
        "WHERE \"State\" = 'United States'")
    assert raw == 10, "the adapter must preserve one total row per vintage"
    mart = fixture_warehouse.fetch_df("mart_state_totals")
    assert not mart["state"].isin(["United States", "Total"]).any()
    assert len(mart) == 510, "51 jurisdictions x 10 vintages"
```

**No fabricated identity, asserted against the real build:**

```python
def test_no_ports_table_was_fabricated(fixture_warehouse: Warehouse) -> None:
    tables = fixture_warehouse.table_names()
    assert "mart_ports" not in tables
    assert "ports" not in tables
    units = fixture_warehouse.fetch_df("mart_charging_units")
    assert units["key_is_synthetic"].all()
    assert not units["has_longitudinal_identity"].any()
    # Every unit is exactly one port, which is why capacity is still computable.
    assert set(units["port_count"].unique()) == {1}
```

**Clustering, not rounding, proved on the case that distinguishes them:**

```python
def test_g4_site_ids_come_from_clustering_not_coordinate_rounding() -> None:
    """Rounding creates arbitrary grid-boundary splits; clustering does not."""
    # Two points 8 m apart that straddle a 3-decimal rounding boundary.
    assignments = cluster_sites(["a", "b"], [44.90049, 44.90056], [-93.0, -93.0])
    assert assignments[0].site_id == assignments[1].site_id
    assert round(44.90049, 3) != round(44.90056, 3), "they do straddle the boundary"
```

**Suite completeness, so a rule cannot quietly lose its test:**

```python
def test_every_domain_rule_g1_to_g14_has_at_least_one_test() -> None:
    """A rule with no test is a rule that is not locked."""
    text = pathlib.Path(__file__).read_text(encoding="utf-8")
    covered = {m.group(1).upper() for m in re.finditer(r"def test_(g\d+)_", text)}
    expected = {f"G{i}" for i in range(1, 15)}
    assert covered == expected, f"missing tests for {sorted(expected - covered)}"
```

---

## 6. Regression against prior phases (Gate part G-C)

| Prior phase | Gate suite | Tests | Result |
|---|---|---:|---|
| 0 | `tests/regression/test_source_findings.py` | 23 | PASS |
| 0 | `tests/integration/test_smoke_forward.py` | 9 | PASS |
| 0 | `make determinism` (probe replay, byte-identical) | 1 | PASS |
| 0 | `pipeline/discovery/` coverage, 100% line and branch | — | PASS |

No prior gate broke. One Phase 0 artifact was **extended** rather than broken:
`SOURCES.yml` gained finding F-11 and four `coverage.*` fields recording the A-0.5
outcome on the ten registration vintages. `validate_contract` still passes, and
`test_every_finding_evidence_artifact_still_matches_its_recorded_hash` now checks
eleven artifacts instead of ten.

---

## 7. Forward viability (Gate part G-D)

### 7.1 Output contract table

| Artifact | Grain | Guaranteed invariants | Consumed by |
|---|---|---|---|
| `mart_sites` | one physical location | `site_id` unique; `station_count ≥ 1`; `charging_unit_count ≥ station_count`; coordinates in range or null | 2 (access), 4 (candidates) |
| `mart_stations` | one AFDC record | `station_id` unique; `status_code ∈ {E,T,P}`; every station has a `site_id`; `ev_connector_types` is a LIST | 2 (supply) |
| `mart_charging_units` | one AFDC unit record = **one port** | `charging_unit_record_key` unique per snapshot; `port_count = 1` throughout; `key_is_synthetic` always True; `has_longitudinal_identity` always False | 2 (supply, power ladder) |
| `mart_charging_unit_connectors` | (unit record, connector type) | unique on the pair; `connector_type` in the 8-value vocabulary; `power_source` is `reported` or null | 2 (power ladder rung 1) |
| `mart_state_totals` | (state, vintage) | unique on the pair; no published total row; `measure_type = stock`; `ev_count ≥ 0` | 3 (reconciliation), 5 (backtest) |
| `mart_observed_subregion_ev` | (state, source geography, snapshot) | `evidence_grain` and `estimate_method` from closed vocabularies; `source_geography_type` declared, never inferred | 3 (demand), 3 (validation) |

Every mart additionally carries `computed_at` and `source_vintages`.

### 7.2 Smoke-forward test

Phase 2's core operation is the supply power-resolution ladder (§7.1): every port
carries `power_kw`, `power_source` and `power_confidence`, resolved through three
rungs. The smoke-forward test exercises **rung 1 only**, against the real canonical
tables produced by this phase on the two-state fixture.

```python
# tests/integration/test_smoke_forward_phase2.py
def resolve_rung_one(connectors: pd.DataFrame) -> pd.DataFrame:
    """The minimal Phase 2 operation: assign rung-1 power where it is reported."""
    frame = connectors.reset_index(drop=True).copy()
    reported = frame["power_kw"].notna() & (frame["power_kw"] > 0)
    frame["resolved_power_kw"] = frame["power_kw"].where(reported)
    frame["power_source"] = pd.Series("reported", index=frame.index).where(reported)
    frame["power_confidence"] = pd.Series("high", index=frame.index).where(reported)
    return frame


def test_rung_one_resolves_against_the_real_canonical_tables(fixture_warehouse):
    connectors = fixture_warehouse.fetch_df("mart_charging_unit_connectors")
    present = connectors[connectors["connector_count"] > 0]
    resolved = resolve_rung_one(present)
    reported = resolved[resolved["power_source"] == "reported"]
    assert len(reported) > 0
    assert (reported["resolved_power_kw"] > 0).all()
    assert set(reported["power_confidence"]) == {"high"}
    share = len(reported) / len(resolved)
    assert 0.0 < share < 1.0
```

Five tests run: rung-1 resolution, hierarchy joins without orphans, no fabricated
`ports` table, capacity computable from units, and `power_confidence_share` computable
per site.

**Result:** 5 passed.

**What this proves.** The canonical tables join correctly through the whole hierarchy
with zero orphans; `power_kw`, `power_source` and `power_confidence` can be populated
from canonical data; rung-1 coverage is strictly between 0 and 1, which is why rungs 2
and 3 exist; and aggregate capacity is computable per site despite absent physical
identity.

**What this does not prove.** Nothing about the accuracy of any power value, nothing
about rungs 2 or 3, nothing about H3 gridding or spatial allocation, and nothing about
whether the site clustering produces the *right* sites — only that it produces
consistent ones.

### 7.3 Assumption ledger additions

| ID | Assumption | Depends on | Tested in | Status |
|---|---|---|---|---|
| A-1.1 | Land-area weighting is an acceptable interim basis for ZIP→tract allocation, and its error is small enough that Phase 3 can measure and correct it rather than having to discard Phase 1 output | Land area assumes uniform population within a ZCTA, which §7.6 says is badly wrong in large rural areas. 76.3% of ZCTAs span more than one tract, so this affects most of the country | Phase 3 (Washington round-trip) | OPEN |
| A-1.2 | The JSON API's eight-connector taxonomy maps cleanly onto the five connector standards named in §1.1 vocabulary (J1772, CCS, CHAdeMO, J3400/NACS, J3271) | The API uses `J1772COMBO` for CCS and `TESLA` for J3400/NACS, and adds three NEMA Level-1 types the vocabulary does not mention | Phase 2 (power ladder) | OPEN |
| A-1.3 | A rule-based copy lint with whole-file and glob allowlisting catches the claims that matter | Phase reports are allowlisted, so a genuine optimality claim inside a report would not be caught. Accepted because the places a false claim would ship — UI strings, docstrings, artifact fields — are not allowlisted | Phase 6 | OPEN |
| A-1.4 | Row order within a station is stable enough within a single snapshot that `charging_unit_record_key` is usable as a within-run join key | It is explicitly not stable *across* runs. If DuckDB or the API reorders within a run, unit-to-connector joins would silently mismatch | Phase 2 | OPEN |

### 7.4 Prior assumptions re-checked

| ID | Assumption | Status this phase | Evidence |
|---|---|---|---|
| A-0.5 | AFDC annual pages are contemporaneous snapshots | **PARTIALLY RESOLVED** | Stability established over 2022-08-18 → 2026-08-24; contemporaneity not. §9.3 |
| A-0.9 | A national substation dataset exists somewhere | Remains RESOLVED by respecification (A6). No substation module was built | §2.1 |
| A-0.16 | Physical port identity is recoverable | **FALSIFIED** | m2, m5, m7 all negative. §9.1 |
| A-0.17 | Connector counts map unambiguously to ports | **FALSIFIED** | 16,610 units exceed their own `port_count`. §9.1 |
| A-0.20 | Stable unit identity is recoverable via network metadata | **FALSIFIED** | JSON unit objects carry five keys, none an identifier. §9.1 |
| A-0.21 | Excluding volatile metadata still detects every genuine change | Holds so far | `test_source_vintages_is_in_scope_for_the_hash`, `test_a_genuine_data_change_does_move_the_hash` |
| A-0.7, A-0.12, A-0.18 | ZIP→tract usability and Tier A state count | Untouched; Phase 3 | — |

---

## 8. Impact log delta

### 8.1 Opened this phase

**None.** No Phase 1 finding invalidated a Phase 0 output.

### 8.2 Resolved this phase

| ID | How resolved | Gates re-run | Reports amended |
|---|---|---|---|
| I-1 | Opened during the Phase 1 plan review and resolved before implementation began: `SOURCES.yml` corrected from `stable_keys: true` to `false` with `parent_key` and `row_identity: none` recorded separately | Phase 0 gate re-run and passing | `PHASE_0_REPORT.md` second dated correction |

### 8.3 Still open

**None.**

Two things that might look like impacts and are not:

- **G6 and G7 test corrections.** My first drafts asserted IEA vocabularies I had not
  read. Both *rules* hold substantively; my *tests* were imprecise. G6's forward
  projection years are exactly {2025, 2030, 2035} once "projection years" is read as
  years beyond the last historical year (2023) rather than every year appearing under
  a `Projection-` category, and the 2026–2029 and 2031–2034 gaps the rule warns about
  are real. G7's four vehicle modes hold for `EV sales` and `EV stock`; the file
  carries a fifth `mode` value, `EV`, used only on `EV charging points` rows where
  `powertrain` is "Publicly available fast"/"slow". Both are documentation
  observations for `docs/DATA_GOTCHAS.md`, not rule changes, so neither was escalated.
- **The connector-decoding bug.** `int_stations` originally split
  `ev_connector_types` on spaces, which is correct for the bulk CSV (G14) but wrong
  for the JSON API, which returns an array. A two-connector station decoded to a
  single-element list containing the literal string `["CHADEMO","J1772"]`. This was
  caught by the G14 regression test before any artifact shipped, which is what that
  test exists for. Both encodings are now decoded explicitly.

---

## 9. Results and numbers

### 9.1 Identifiability analysis (CLAUDE.md §6.1.1, amendments A5 and A13)

Measured over the full national export: **89,758 stations, 292,756 charging units**.
Evidence artifact: `docs/evidence/P1-1_identifiability.json`.

| # | Measurement | Result |
|---|---|---|
| m1 | Unit-level `port_count` available | **100.0%** (292,756 / 292,756) — JSON only; the CSV carries station-level EVSE totals |
| m2 | Stable network-provided port identifier | **No** |
| m3 | Connector counts map unambiguously to ports | **No** |
| m4 | Units where connector ports exceed the unit's own `port_count` | **16,610** |
| m5 | Share supporting individual port identity | **0%** |
| m6 | Share supporting only aggregate capacity | **100%** |
| m7 | Stable charging-unit identity, including via network metadata | **No** |
| m8 | Identical rows distinguishable other than by row order | **No** |

Supporting measurements:

```
CSV representation (292,435 rows)
  distinct full-row values            99,639
  rows in an identical-row group     265,836   (90.9%)
  redundant rows (n-1 per group)     192,796   (65.9%)
  largest identical group                410   (station 225833, Viejas Casino)
  stations where row count == reported L1+L2+DCFC   89,665 / 89,687  (100.0%)

JSON representation (292,756 units)
  unit object keys       charging_level, connectors, funding_sources, network, port_count
  identifier keys found  none
  distinct unit objects           1,752
  redundant unit objects        291,004   (99.4%)
  largest identical group        69,100
  connector types exposed  CHADEMO, J1772, J1772COMBO, J3271, NEMA1450, NEMA515,
                           NEMA520, TESLA   (8, against 5 in the CSV)
```

**Two findings the analysis produced that the plan did not anticipate.**

**(a) An AFDC charging unit *is* one port.** `port_count` is **1 for all 292,756
units**. There is no cabinet grain in the source at all. The specification's §6.1
hierarchy is `site → station → charging_unit (EVSE cabinet) → port → connector`; the
data supports `site → station → charging_point`, where the middle two levels collapse
into one. This is raised for the owner's attention in §12 Q2. Charging level
distribution: `dc_fast` 77,490, level 2 212,509, level 1 2,736, `legacy` 21.

**(b) 16,610 units expose more than one connector standard on that single port**,
led by:

```
  CHADEMO + J1772COMBO           7,071    (dual-standard DC dispenser)
  J1772COMBO + TESLA             5,168    (CCS + NACS)
  J1772 + TESLA                  3,283    (Level 2 dual cable)
  CHADEMO + TESLA                   40
  CHADEMO + J1772COMBO + TESLA      36
```

**The finding that keeps Phase 2 viable.** Row count reconciles to each station's
reported L1+L2+DCFC total for **89,665 of 89,687 stations (100.0%)**. The export is
genuinely one row per EVSE and the duplicates are *real distinct physical units that
are indistinguishable in every reported attribute* — structurally the same situation
as domain rule G4 for coordinate duplicates. **Aggregate counts and capacity are
therefore trustworthy even though identity is not**, so the power ladder is unaffected.

**Decision rules fired**, exactly as pre-registered in `PHASE_1_PLAN.md` §3 before the
measurement ran:

```
decision_ports_table_populated                false
decision_charging_unit_key_is_synthetic       true
decision_connector_grain                      (charging_unit_record_key, connector_type)
decision_longitudinal_unit_identity_claimable false
```

### 9.2 Geographic reconciliation (§7.5.1, amendment A4)

Crosswalk: Census 2020 ZCTA-to-tract relationship file
(`tab20_zcta520_tract20_natl.txt`), vintage 2020, free and unauthenticated.

```
ZCTAs with tract links                33,791
ZCTAs spanning more than one tract    25,770   (76.3%)
```

**76.3% is the measured case for why this is not a lookup.** Three-quarters of ZCTAs
must be split across tracts, so a one-to-one crosswalk would misassign most of the
country's registrations.

USPS ZIP → tract is executed as **two declared steps**: an approximate identity from
USPS ZIP to the like-numbered ZCTA, then a weighted split from ZCTA to tract. Every
allocated row carries `source_geography_type`, `source_geography_id`,
`evidence_grain`, `estimate_method`, `crosswalk_source`, `crosswalk_vintage`,
`allocation_weight_basis` and `allocation_weight`. Allocation conserves mass exactly
(`conservation_error == 0.0`). ZIPs with no areal equivalent are **returned as
unallocatable, never dropped** (D8).

Domain rule G13 is enforced by construction: the county lookup is keyed by
`(state, name)` and `resolve_county_fips` raises rather than guessing. 3,235 counties
load. Cook County resolves to **27031** in Minnesota, **17031** in Illinois and
**13075** in Georgia — and note that Minnesota and Illinois share county code `031`,
so even a bare county code collides; only the state prefix separates them.

### 9.3 A-0.5 vintage provenance (amendment A10)

**Question.** Are AFDC's `year=` registration pages contemporaneous annual snapshots,
or retrospective reconstructions from later VIN data? This bears directly on D1: a page
labelled 2020 is not by itself proof that its numbers were information available at a
2020 cutoff.

**Method.** Enumerate every Internet Archive capture of the page; compare archived
values against the live page today. Budget: one working session, as fixed by A10.

**Results.**

```
vintage 2021, captured 2022-08-18  vs live 2026-08-24 :  52/52 identical, 0 changed
vintage 2020, captured 2023-09-12  vs live 2026-08-24 :  52/52 identical, 0 changed

earliest capture of the page          2022-08-18
captures before 2022                  0
year selector in the earliest capture  2016, 2017, 2018, 2019, 2020, 2021
displayed vintage in that capture      2021  (Oregon 30,300; California 563,100)
```

**Resolution: PARTIAL.**

- **Established.** The series is **not retrospectively revised** within the observable
  window 2022-08-18 → 2026-08-24.
- **Not established.** Whether the 2020 and 2021 figures were *published* during or
  shortly after those years. No capture exists before 2022-08-18, and that earliest
  capture already offered a full back-series to 2016, so the archive cannot show
  whether any given year page existed during that year.

Recorded on all ten vintages in `SOURCES.yml` as
`historical_vintage_semantics: stable_not_revised_within_observable_window` with
`contemporaneity: unresolved`, plus finding **F-11** with a hashed evidence artifact.

**Consequence for Phase 5.** `docs/VALIDATION.md` must state that the 2020 and 2021
rolling origins rest on a technical vintage *label* whose information-availability
semantics are unverified, while the 2022 origin is supported by an archived capture
predating it. The D1 runtime guard `feature_vintage <= prediction_cutoff` is
unaffected: what is unverified is the *meaning* of the label, not the mechanics of the
check.

### 9.4 Corrected G9 against the delivered data

```
jurisdictions                51
vintage resolved             2023
coverage complete            yes
all counts non-negative      yes
published total              3,555,445
sum of jurisdictions         3,555,445
total reconciles             yes
half-up rounded matches to the AFDC 2023 vintage    51/51
Oregon                       64,361   (the original G9 asserted 6,436)
Kansas                       11,271
Iowa                          9,031
```

`test_g9_property_1_the_delivered_file_resolves_to_the_2023_afdc_vintage` re-derives
Phase 0's dating independently inside the regression suite rather than trusting the
earlier result, and asserts `Oregon > Kansas > Iowa`.

### 9.5 Determinism (CLAUDE.md §14.1, amendment A14)

Eight tests. The required property — replay reproducibility — holds: two builds against
pinned inputs with an injected fixed timestamp produce an identical 64-character
semantic hash and identical model row counts. The hash is unaffected by `computed_at`
and by row order, and *is* moved by a genuine data change and by a `source_vintages`
change. A ninth test is marked `live` and skipped in the gate, documenting that a
live refresh producing different artifacts is **not** a determinism failure.

`test_naive_byte_equality_would_fail_which_is_why_it_is_not_the_gate` demonstrates the
problem A14 exists to solve by showing `computed_at` genuinely differing between runs,
rather than asserting it abstractly.

---

## 10. Limitations introduced or discovered

| Limitation | Cause | Effect downstream | Mitigated? | In LIMITATIONS.md? |
|---|---|---|---|---|
| **No longitudinal charging-unit identity anywhere in the project** | AFDC exposes no unit identifier in either representation; 65.9% of CSV rows and 99.4% of JSON unit objects are byte-identical duplicates | No unit can be tracked across refreshes. Any future "this charger was upgraded" analysis is impossible from this source | Not mitigable. Declared in data via `key_is_synthetic` / `has_longitudinal_identity` and asserted by schema | Yes |
| **Land-area allocation weights** | Only free, unauthenticated national weight available; population weighting needs a heavier build | Assumes uniform population within a ZCTA, badly wrong in large rural areas (§7.6). Affects 76.3% of ZCTAs | Declared per row as `allocation_weight_basis`; Phase 3 measures the error via the Washington round-trip and may replace it | Yes |
| **A-0.5 contemporaneity unresolved for 2020 and 2021** | No Internet Archive capture predates 2022-08-18 | The two earlier rolling origins rest on an unverified vintage label | Recorded in the contract; Phase 5 must state it | Yes |
| **Phase reports allowlisted from the copy lint** | Reports must quote prohibited phrases in order to record that they are prohibited | A genuine optimality claim inside a report would not be caught | UI strings, docstrings and artifact fields are not allowlisted, which is where a false claim would ship. Assumption A-1.3 | Yes |
| **`ports` and `connectors` tables unpopulated** | No stable identity at any level | Any Phase 2+ code expecting per-port rows must work at charging-unit grain instead | This is the honest outcome, not a defect. Asserted by `test_no_ports_table_was_fabricated` | Yes |
| **Charging-unit retrieval switched from CSV to JSON** | Only the JSON carries unit-level `port_count` and all eight connector standards | `SOURCES.yml` contracts the CSV endpoint for `afdc_charging_units`; the built pipeline uses the JSON. Same source, different path | Raised as open question Q1 for the owner | Yes |
| **Two-state fixture, not a national build** | National Atlas retrieval is ~3.4 GB across 14 states | The gate proves the pipeline works, not that it scales to national volume | `make build` runs nationally; only the gate uses the fixture | Yes |
| **55 connector rows nationally report exactly 0.00 kW** | Upstream data fault | 0 kW is not a valid reported power and must not be treated as rung 1 | Flagged as `is_zero_power_anomaly` in the canonical table; excluded from `power_source = reported` | Yes |

---

## 11. Specification compliance

### 11.1 Prime directives

| Directive | How compliance is enforced | Verified by |
|---|---|---|
| **D1** No temporal leakage | Not yet exercised: no backtest exists until Phase 5. Phase 1 records vintage on every state total and carries the A-0.5 caveat forward | `mart_state_totals` has 510 rows across 10 explicit vintages |
| **D2** No supply-to-demand loop | Not yet exercised: no demand model exists until Phase 3. Phase 1 keeps supply and registration marts entirely separate, with no join between them | `mart_observed_subregion_ev` and `mart_charging_units` share no key |
| **D3** Three validation terms | Copy lint rules `D3-CONFLATE-01/02` plus five optimality rules, run in CI from this phase | `test_the_repository_itself_is_clean`, 71 files |
| **D4** Zero recurring cost | Every source retrieved without payment. The two new sources this phase (county FIPS reference, ZCTA-tract relationship file) are free Census bulk files needing no key | 52 of 57 sources need no credential |
| **D5** Greenfield | No prior implementation consulted | — |
| **D6** Grid proximity language | Copy lint rules `D6-GRID-01` through `-05`. No substation module was built (A6) | 71 files clean |
| **D7** Uncertainty first-class | Not yet exercised: no modelled quantity exists until Phase 3. Phase 1 lays the groundwork by stamping `evidence_grain`, `estimate_method` and `allocation_weight_basis` on every allocated value | `MART_OBSERVED_SUBREGION_EV` schema |
| **D8** Explicit degradation | Unallocatable ZIPs returned, not dropped; unusable coordinates get singleton no-geo sites, not a default location; missing crosswalk raises with the fetch URL rather than proceeding | `test_allocate_many_returns_unallocatable_records_rather_than_dropping_them`, `test_unusable_coordinates_get_a_singleton_site_rather_than_being_dropped` |

### 11.2 Deviations from specification

| Spec section | What the spec says | What was done | Why | Approved? |
|---|---|---|---|---|
| §6.2 | `ports` table, one row per port; `connectors` table | Neither populated | §6.1.1 as amended requires exactly this when identity is unrecoverable, and the pre-registered decision rule fired | Yes — A5/A13 |
| §6.1 | Five-level hierarchy, "do not collapse them" | Four levels: `site → station → charging_unit → (unit, connector_type)` | Two of the five do not exist in the source: `port_count = 1` for all units, so unit *is* port, and no cabinet grain exists | Raised as Q2 |
| §4.1 `afdc_charging_units.retrieval.endpoint` | The `ev-charging-units.csv` endpoint | The JSON endpoint | Only the JSON carries unit-level `port_count` and all eight connector standards | Raised as Q1 |
| §3 | `pipeline/sources/` includes `egrid.py`, `fhwa_traffic.py`, `hifld_substations.py`, `eia_prices.py` | None built | A6, A8, A16 and Optional tier respectively | Yes |

---

## 12. Open questions for the reviewer

**Q1. The charging-unit retrieval path changed from the contracted CSV to the JSON
endpoint.** `SOURCES.yml` contracts
`https://developer.nlr.gov/api/alt-fuel-stations/v1/ev-charging-units.csv` for
`afdc_charging_units`, and Phase 0 verified that endpoint. Phase 1 measurement then
established that the CSV **exposes five connector columns and station-level EVSE
totals**, while the JSON endpoint exposes **eight connector standards and a genuine
unit-level `port_count`**. The three the CSV drops — NEMA515, NEMA520, NEMA1450 — are
all Level 1. §7.1 requires `port_count_l1` as a supply output, so using the CSV would
mean Level-1 connector detail is silently unavailable.

I switched to the JSON and recorded it as a deviation rather than amending the
contract unilaterally. **Should `SOURCES.yml` be amended to contract the JSON endpoint
for this source, keeping the CSV as the documented fallback?** I recommend yes.

**Q2. An AFDC charging unit is one port, and no cabinet grain exists.** `port_count` is
1 for all 292,756 units. §6.1 specifies five levels and says "do not collapse them",
but two of them are not in the data: there is no EVSE-cabinet record, and the unit
record *is* the port. The canonical model therefore has four levels, and the table
named `charging_units` holds one row per port.

That naming is now slightly misleading. **Would you prefer the table renamed (for
example to `charging_points`) to match what it holds, or left as `charging_units` to
match the specification's vocabulary?** I lean toward leaving the name and documenting
the equivalence, because renaming diverges from §6.2's table list, but the current name
invites a reader to assume a cabinet grain that does not exist.

**Q3. Land-area allocation weights.** These are the weakest defensible basis and affect
76.3% of ZCTAs. Phase 3 is scheduled to measure the error via the Washington
round-trip. **Is it acceptable for Phase 2 to consume land-area-weighted allocations in
the interim**, given that every row declares its weight basis, or should Phase 2 avoid
tract-allocated registration data entirely until Phase 3 has measured the error?

**Q4. G6 and G7 wording.** Both rules hold substantively but are imprecise about the
delivered file: G6 does not distinguish forward projection years from the historical
baseline years restated inside each `Projection-` category, and G7 does not mention the
fifth `mode` value `EV` used on charging-point rows. I treated both as documentation
observations for `docs/DATA_GOTCHAS.md` rather than escalating them. **Do you want the
G6 and G7 wording amended in `CLAUDE.md` for precision, or is a DATA_GOTCHAS note
sufficient?**

---

## 13. Next phase readiness

| Check | Status |
|---|---|
| All acceptance criteria passed | 20/20 |
| Coverage thresholds met | **100% line and branch across the whole pipeline package** (1,641 statements, 402 branches, zero missed) |
| All prior gates passing | Phase 0 re-run, PASS |
| Smoke-forward test passing | 5/5 against real Phase 1 output |
| Report complete and self-contained | Yes |
| No S1 impacts open | None open at any severity |

**Recommendation: PROCEED to Phase 2 (Supply + access)**, subject to the owner's
answers on Q1–Q4 in §12. None of the four blocks Phase 2 from starting; Q1 and Q3
would change what Phase 2 consumes, so answering them before Phase 2 begins is
preferable to answering them mid-phase.

Phase 2's inputs are all present and validated: `mart_charging_units` with
`port_count` and public/operational flags, `mart_charging_unit_connectors` with
per-connector `power_kw` and rung-1 `power_source`, `mart_sites` with resolved
clusters, and `mart_stations` with G2/G3 flags and split connector lists.

---

## Corrections

*(none)*

## Correction — 2026-08-24

Recorded after the project owner's review of this report, which accepted Phase 1 as
**PASS** and required two statements in it to be corrected. Phase 1 is not rewound and
no measurement is retracted. The text above is preserved unedited.

**1. "100.0% of stations" overstated a rounded figure.** Section 9.1 and the commit
message report reconciliation as `89,665 / 89,687 (100.0%)`. That ratio is **99.975%**;
the one-decimal display rounded it up. The 22 exceptions are real.

Phase 2's preflight investigation (CLAUDE.md 15.5.1, amendment A24) classified all 22,
with **zero unresolved**:

| Classification | Count | Explanation |
|---|---:|---|
| `no_unit_records` | 12 | All have `Status Code = P` (planned). Nothing is built yet, so there are no unit records and no station-level EVSE totals. Domain rule G2 already excludes them from operational supply |
| `legacy_charging_level` | 8 | Contain units whose `charging_level` is `legacy`, which the L1/L2/DCFC aggregate does not count, so unit rows exceed the reported total by exactly the legacy count |
| `missing_station_aggregate` | 2 | Hold *only* legacy units, so report no aggregate at all |

12 + 10 = 22. Under the documented scope **"stations with at least one charging-unit
record and no legacy-level unit"**, reconciliation is **89,736 / 89,736 = exactly
100.0000%**. The unscoped figure must be written as 99.975%, never as 100%.

Evidence: `docs/evidence/P2-1_station_reconciliation.json`. Enforced by
`tests/regression/test_phase2_gates.py::test_p2e_the_unscoped_rate_is_never_described_as_one_hundred_percent`.

**2. `port_count = 1` was described as a guaranteed invariant.** Section 7.1's contract
table states "`port_count = 1` throughout" as a guaranteed invariant of
`mart_charging_units`. It is a **current-source observation, not permanent ontology**
(amendment A19). Charging unit and port remain conceptually distinct source entities;
the one-to-one relationship happens to hold in the 2026-08 snapshot.

The canonical schema now requires `port_count >= 1`. Pinning `== 1` would reject a
legitimate future AFDC record reporting multiple ports as though it were corrupt data.
The `== 1` observation is monitored by `check_port_count_drift`, which reports a value
above 1 as **source drift requiring review** and never raises. Gate check P2-D covers
both directions.

**Consequential change to a Phase 1 output.** The AFDC charging-unit source contract was
amended (A23): the **JSON representation is now primary** and the CSV is a documented
fallback, because only the JSON carries a unit-level `port_count` and all eight connector
standards. This answers open question Q1 in section 12. `SOURCES.yml` records both
representations with their own endpoints, schema hashes and limitations, and both are
probed. As an independent cross-check, both return **2,957 rows for Minnesota**. The
schema hash for the primary representation is `68cadbe608518980` (35 staged columns); the
fallback remains `c7ef314df7ff8fce` (86 columns).

The other three open questions were answered as follows: **Q2** keep the table name
`charging_units` and correct the semantics instead; **Q3** Phase 2 must *not* consume
land-area-weighted registration allocations; **Q4** amend G6 and G7 in `CLAUDE.md`, not
only in `DATA_GOTCHAS.md`. All are applied and logged as amendments A17–A24 in
`CLAUDE.md` §19.

Phase 0 and Phase 1 gates were re-run after these amendments and both pass.
