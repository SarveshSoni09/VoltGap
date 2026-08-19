# Phase 0 Report — Source contract

## 0. Report metadata

| Field | Value |
|---|---|
| Phase | 0 — Source contract |
| Date | 2026-08-19 |
| Gate status | **PASS** |
| Commit | `55f388a5adf024211d388454615ea9ff9b5e072e` (implementation); this report is committed on top as `gate(phase-0): PASS` |
| Duration | 1 working session against a planned 1.0 week part-time |
| Prepared by | Claude Code |

---

## 1. Context for a reader with zero prior knowledge

### 1.1 What this project is

**VoltGap** is an open, statically hosted decision-support application for electric
vehicle charging infrastructure planning in the United States. It answers one question:
given a budget and a set of policy priorities, where should the next EV charging
infrastructure be built, and how confident should we be in that answer? Its users are
infrastructure planners, charge point operators, state energy offices and researchers.

Its primary output is a ranked, budget-feasible portfolio of candidate hexagonal sites
(H3 resolution 6 nationally, resolution 8 in the top 50 metros), each carrying a score,
an uncertainty band, tradeoff context, and CSV/GeoJSON export. It is explicitly *not* a
consumer charger finder, a general EV statistics browser, or a real-time availability
map.

The project is bound by eight prime directives, four of which matter throughout this
report. **D1**: no temporal leakage in retrospective evaluation — any feature used in a
backtest must carry a vintage that a runtime assertion checks against the prediction
cutoff. **D2**: no supply-to-demand feedback loop — existing charger density and
anything derived from installed infrastructure are excluded from the demand model,
because using prior investment to predict need launders historical deployment patterns
into "demand" and suppresses exactly the underserved areas the system exists to find.
**D4**: zero recurring cost — free tiers only, no paid API, no managed database.
**D8**: when a source is unavailable, degrade explicitly and flag it; never substitute a
plausible default silently.

A further directive, **D3**, fixes three distinct validation terms that must never be
blurred: *demand model validation* (are tract-level EV estimates accurate — leave-one-
state-out), *historical deployment alignment* (do priority areas match where industry
actually built — a vintage-enforced backtest), and *cross-objective robustness* (does a
portfolio optimised for one objective perform on others — ε-constraint Pareto analysis).
None of the three demonstrates that a site is objectively optimal; ground truth for
optimal siting does not exist, and no output may claim otherwise.

### 1.2 The architecture in one paragraph

An offline Python pipeline (3.11+, `uv`, DuckDB as a file-based warehouse, pandera for
schema validation) ingests public data, models supply, demand, access and siting, and
exports static artifacts — Parquet tables, PMTiles vector tiles, JSON frontiers, and a
manifest. Those artifacts are hosted on Cloudflare R2 and consumed by a statically
exported Next.js frontend using MapLibre GL JS and deck.gl, with an interactive greedy
optimiser running in a Web Worker. Nothing runs server-side at request time. The
constraint driving that architecture is D4: static hosting plus a free object store plus
GitHub Actions for scheduled refresh is a zero-recurring-cost stack, and every design
choice downstream — H3 pre-aggregation, range-requested Parquet, tiled geometry, a
browser-side approximate solver instead of a hosted exact one — follows from it.

### 1.3 What the previous phase produced

**This is the first phase.** The starting state was a directory containing:

- `CLAUDE.md`, the 969-line authoritative specification.
- `SETUP.md`, `STARTER_PROMPT.md`, a stub `Makefile`, `gitignore` and `env.example`
  (both without leading dots, therefore inert), and `PHASE_REPORT_TEMPLATE.md`.
- `data/seed/` with ten delivered data files and a `MANIFEST.md` describing them.
- **Not a git repository.** No Python project, no `.env`, no API keys, no dependencies.

The ten delivered seed files, as measured by this phase:

| Canonical id | Raw filename (preserved exactly) | Bytes | Data rows | Columns |
|---|---|---:|---:|---:|
| `seed_afdc_stations_national_20241211` | `alt_fuel_stations (Dec 11 2024).csv` | 27,542,687 | 79,618 | 75 |
| `seed_afdc_stations_mn_20241210` | `alt_fuel_stations (Dec 10 2024).csv` | 339,993 | 985 | 75 |
| `seed_state_ev_registrations` | `EV_Registration_Counts_by_State.csv` | 826 | 52 | 2 |
| `seed_mn_county_ev_registrations` | `County_EV_Registrations_Summary.csv` | 1,711 | 87 | 2 |
| `seed_il_county_ev_monthly_panel` | `county_ev_counts.csv` | 27,105 | 84 | 106 |
| `seed_il_stations` | `IL_StationsData.csv` | 267,418 | 1,626 | 13 |
| `seed_mn_stations_simplified` | `Simplified_EV_Charging_Stations.csv` | 67,011 | 985 | 6 |
| `seed_iea_global_ev_2024` | `IEA Global EV Data 2024.csv` | 874,985 | 12,654 | 8 |
| `seed_ev_model_launch` | `ev_launch_data.csv` | 6,098 | 91 | 9 |
| `seed_hifld_transmission_lines` | `Electric__Power_Transmission_Lines.geojson` | 144,115,564 | 94,216 features | 19 properties |

### 1.4 What this phase was supposed to do

`CLAUDE.md` §4 opens: *"Do not design any model before this phase completes. Two errors
were already made in the design process by assuming external data shapes. Verify
everything."*

The declared acceptance criteria, quoted verbatim from §15.5:

> Every source has all contract fields populated. Every Core model has a data path or
> documented fallback. AFDC connector power missingness measured numerically. NREL home
> charging vintage determined as current or 2030 scenario. Historical registration
> vintage availability resolved yes/no. Tier A states enumerated with granularity and
> temporal coverage each. `probe.py` is idempotent.

And from §4.2: *"Phase 0 acceptance: `SOURCES.yml` is complete for every source,
`probe.py` is re-runnable and idempotent, and every Core model in §7 has a documented
data path or a documented fallback."*

The project owner additionally required four specific unknowns to be resolved rather
than assumed: (a) whether the AFDC charging units endpoint exposes per-connector
`power_kw` and `port_count` and their measured missingness; (b) whether the NREL county
home charging shares are current values or 2030 projections; (c) whether historical
state-level EV registration vintages are obtainable anywhere; (d) exactly which states
have usable open sub-state EV registration data, at what granularity, over what period.

---

## 2. What was built

### 2.1 Modules created or changed

| Path | Purpose | Lines | Key public functions |
|---|---|---:|---|
| `pipeline/config/settings.py` | Typed settings; every path and tuning constant | 77 | `PATHS`, `PROBE`, `api_keys()` |
| `pipeline/discovery/cache.py` | HTTP fetching, content-addressed cache, replay mode | 278 | `cache_key`, `redact`, `LiveFetcher`, `ReplayFetcher`, `CacheMissError` |
| `pipeline/discovery/measure.py` | Schema discovery, missingness, power coverage | 374 | `measure_delimited`, `measure_json_records`, `measure_html_table`, `measure_geojson_properties`, `measure_connector_power_coverage`, `schema_hash` |
| `pipeline/discovery/contract.py` | Contract validation, observations, drift | 274 | `load_contract`, `validate_contract`, `evaluate_drift`, `write_observations` |
| `pipeline/discovery/registry.py` | 57 declarative probe specifications | 368 | `ProbeSpec`, `all_specs()` |
| `pipeline/discovery/probe.py` | Orchestration, status classification, CLI | 301 | `probe_one`, `probe_remote`, `probe_local`, `run`, `main` |
| `pipeline/discovery/seed_inventory.py` | Provenance and SHA-256 of delivered files | 183 | `build_inventory`, `write_inventory`, `sha256_of` |
| `Makefile` | `make gate PHASE=0` and its constituent targets | 88 | — |
| `pyproject.toml` | uv, Python 3.12, ruff, mypy strict, pytest, coverage | 66 | — |

Test code: 1,688 lines across 8 files (§5).

### 2.2 Key implementations, quoted

**Bounded transfers.** The first probe implementation trusted the `Range` request header
and downloaded 3.3 GB, because several hosts advertise `accept-ranges: bytes` and then
ignore it. The fix streams and cuts off locally:

```python
# pipeline/discovery/cache.py
def _fetch_once(
    self,
    url: str,
    params: Mapping[str, str],
    headers: Mapping[str, str],
    max_bytes: int | None,
) -> tuple[int, dict[str, str], bytes, bool]:
    """Return (status, response headers, body, truncated)."""
    with (
        self._client_factory() as client,
        client.stream("GET", url, params=dict(params), headers=dict(headers)) as raw,
    ):
        chunks: list[bytes] = []
        size = 0
        truncated = False
        for chunk in raw.iter_bytes():
            chunks.append(chunk)
            size += len(chunk)
            if max_bytes is not None and size >= max_bytes:
                truncated = True
                break
        body = b"".join(chunks)
        if max_bytes is not None and len(body) > max_bytes:
            body = body[:max_bytes]
        return (
            raw.status_code,
            {k.lower(): v for k, v in raw.headers.items()},
            body,
            truncated,
        )
```

**Credential handling.** Secrets are redacted *before* the cache key is hashed, so a
cache recorded under `DEMO_KEY` still replays once the operator supplies a personal key.
No credential ever reaches disk.

```python
# pipeline/discovery/cache.py
REDACTED_PARAMS: frozenset[str] = frozenset({"api_key", "key", "token"})
REDACTION = "<redacted>"


def redact(params: Mapping[str, str]) -> dict[str, str]:
    """Replace secret parameter values so nothing sensitive reaches the cache or a report."""
    return {k: (REDACTION if k in REDACTED_PARAMS else v) for k, v in params.items()}


def cache_key(
    url: str, params: Mapping[str, str], headers: Mapping[str, str] | None = None
) -> str:
    payload = json.dumps(
        {
            "url": url,
            "params": dict(sorted(redact(params).items())),
            "headers": dict(sorted((headers or {}).items())),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
```

**Rung-1 power coverage.** This is the measurement the whole §7.1 power ladder depends
on. Raw column missingness would badly understate coverage, because a power column is
only meaningful where that connector is actually present. Coverage is therefore measured
*conditional on the connector existing* and weighted by ports, which is the quantity the
supply model sums:

```python
# pipeline/discovery/measure.py
def measure_connector_power_coverage(
    rows: Iterable[dict[str, object]],
    connectors: Sequence[str] = CONNECTOR_TYPES,
    public_operational_only: bool = False,
) -> dict[str, Any]:
    counters = {
        name: {"units": 0, "ports": 0, "units_kw": 0, "ports_kw": 0} for name in connectors
    }
    considered = 0
    zero_power_cells = 0
    for row in rows:
        if public_operational_only and not (
            str(row.get("Status Code", "")).strip() == "E"
            and str(row.get("Access Code", "")).strip() == "public"
        ):
            continue
        considered += 1
        for name in connectors:
            count = _to_float(row.get(f"EV {name} Connector Count")) or 0.0
            if count <= 0:
                continue
            power = _to_float(row.get(f"EV {name} Power Output (kW)"))
            bucket = counters[name]
            bucket["units"] += 1
            bucket["ports"] += int(count)
            if power is not None:
                bucket["units_kw"] += 1
                bucket["ports_kw"] += int(count)
                if power == 0.0:
                    zero_power_cells += 1
```

`Status Code == 'E'` and `Access Code == 'public'` are domain rules G2 and G3.

**G12-safe GeoJSON reading.** Domain rule G12 forbids loading the 137 MiB HIFLD
transmission GeoJSON as a single object *anywhere*. The probe reads it as a text stream
and decodes one `"properties": {...}` object at a time, carrying partial objects across
1 MiB read boundaries:

```python
# pipeline/discovery/measure.py
def iter_geojson_property_names(path: Path, max_features: int) -> Iterator[tuple[str, ...]]:
    seen = 0
    depth = 0
    buffer: list[str] = []
    capturing = False
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        pending = ""
        while seen < max_features:
            chunk = handle.read(1 << 20)
            if not chunk:
                break
            pending += chunk
            while seen < max_features:
                if not capturing:
                    index = pending.find('"properties"')
                    if index < 0:
                        pending = pending[-16:]
                        break
                    brace = pending.find("{", index)
                    if brace < 0:
                        break
                    pending = pending[brace:]
                    capturing, depth, buffer = True, 0, []
                consumed = 0
                for character in pending:
                    consumed += 1
                    buffer.append(character)
                    if character == "{":
                        depth += 1
                    elif character == "}":
                        depth -= 1
                        if depth == 0:
                            yield tuple(json.loads("".join(buffer)).keys())
                            seen += 1
                            capturing = False
                            break
                pending = pending[consumed:]
                if capturing:
                    break
```

**Status classification.** Mechanically assigned from the response, never by judgement:

```python
# pipeline/discovery/probe.py
def _classify(spec: ProbeSpec, response: Response,
              measurement: measure.Measurement | None) -> tuple[str, str]:
    """Assign one of confirmed / degraded / gated / unavailable, with a reason."""
    if looks_gated(response):
        return "gated", (
            f"credential required; set {spec.needs_api_key.upper()}_API_KEY. "
            "No credential is fabricated or persisted by this pipeline."
        )
    if response.status_code == 429:
        limit = response.headers.get("x-ratelimit-limit", "?")
        retry = response.headers.get("retry-after", "?")
        return "gated", (
            f"HTTP 429: rate limit exhausted (x-ratelimit-limit={limit}, "
            f"retry-after={retry}s). The shared DEMO_KEY credential is heavily "
            "throttled; supply a free key in the environment for full probing. "
            "No credential is fabricated or persisted by this pipeline."
        )
    if not response.ok:
        return "unavailable", f"HTTP {response.status_code}"
    if spec.kind == "availability":
        return "confirmed", f"reachable, HTTP {response.status_code}, " \
                            f"{len(response.content)} bytes sampled"
    if measurement is None:
        return "degraded", "reachable but the payload could not be measured"
    if measurement.row_count == 0:
        return "degraded", "reachable but the sample contained no records"
    return "confirmed", f"{measurement.row_count} records measured in the bounded sample"
```

**Contract validation** is the executable check behind the "every source has all
contract fields populated" criterion. It accumulates every problem rather than failing
on the first, and it enforces one cross-field invariant tied to directive D1 — a source
cannot claim backtest eligibility without historical vintages:

```python
# pipeline/discovery/contract.py
REQUIRED_CONTRACT_FIELDS: tuple[str, ...] = (
    "id", "name", "tier", "retrieval", "coverage", "schema", "quality", "license",
    "update_cadence", "fallback_source", "used_by", "backtest_eligible",
    "known_limitations",
)
REQUIRED_RETRIEVAL_FIELDS = ("method", "endpoint", "auth", "rate_limit")
REQUIRED_COVERAGE_FIELDS = ("geographic", "temporal", "historical_vintages_available",
                            "vintage_field", "vintage_semantics")
REQUIRED_SCHEMA_FIELDS = ("join_keys", "stable_keys", "schema_version")
REQUIRED_QUALITY_FIELDS = ("expected_row_count", "drift_tolerance",
                           "expected_range_derivation")
REQUIRED_FINDING_FIELDS = ("question", "resolved_value", "evidence_url", "retrieved_at",
                           "evidence_quote", "evidence_artifact", "evidence_sha256")

        if (
            isinstance(coverage, dict)
            and entry.get("backtest_eligible") is True
            and coverage.get("historical_vintages_available") is not True
        ):
            problems.append(
                f"{label}: backtest_eligible is true but "
                "coverage.historical_vintages_available is not true"
            )
```

### 2.3 Data artifacts produced

| Artifact | Grain | Rows / entries | Size | Schema summary |
|---|---|---:|---:|---|
| `SOURCES.yml` | one entry per source | 57 sources + 10 findings | 1,997 lines | Stable contract, hand-authored, YAML anchors for repeated blocks |
| `SOURCES.observed.json` | one observation per source | 57 observations + 57 drift records | 4,339 lines | Generated, deterministic (sorted keys, sorted entries) |
| `data/seed/seed_inventory.json` | one entry per delivered file | 10 | 4,428 bytes | `raw_filename`, `canonical_id`, `size_bytes`, `sha256`, `provenance`, `version_controlled` |
| `data/seed/SEED_INVENTORY.md` | same, human-readable | 10 | 3,449 bytes | Markdown table |
| `docs/evidence/F-1 … F-10` | one artifact per research finding | 10 files | 20,571 bytes | Preserved evidence, each SHA-256 recorded in `SOURCES.yml` |
| `tests/fixtures/replay/` | one directory per remote source | 47 sources | 3.4 MB | Recorded HTTP bodies + metadata; the deterministic gate substrate |
| `data/cache/` | live probe cache | 47 sources | ~3 MB (+ 136 MB in `raw/`, gitignored) | Not version controlled |

### 2.4 Schemas, quoted in full

`SOURCES.yml` entry schema (every field mandatory; validated by
`validate_contract`), shown with a real entry:

```yaml
  - id: afdc_charging_units
    name: AFDC EV Charging Units export
    tier: core                          # core | extension | optional
    retrieval:
      method: rest_api                  # rest_api | bulk_download | scrape
      endpoint: "https://developer.nlr.gov/api/alt-fuel-stations/v1/ev-charging-units.csv"
      auth: api_key_free
      rate_limit: "shared with afdc_stations; DEMO_KEY limit measured at 10 per window"
    coverage:
      geographic: "US 50 states + DC + PR; probed Minnesota-scoped"
      temporal: "current snapshot only"
      historical_vintages_available: false
      vintage_field: "Snapshot Date"
      vintage_semantics: >-
        Present-day snapshot. The column exists but the endpoint accepts no
        snapshot/date parameter, so prior snapshots cannot be requested.
    schema:
      join_keys: [ID]
      stable_keys: true
      schema_version: c7ef314df7ff8fce   # order-sensitive hash of the field list
      expected_field_count: 86
    quality:
      expected_row_count: [2400, 3600]
      drift_tolerance: 0.20
      expected_range_derivation: >-
        Provisional, for the Minnesota-scoped probe only. First verified live
        observation was 2,951 unit rows for Minnesota on 2026-08-19, widened by the
        default tolerance. The national export holds 292,435 unit rows.
    license: "US Government work, public domain"
    update_cadence: "daily"
    fallback_source: afdc_stations
    used_by: [supply, power_ladder]
    backtest_eligible: false
    known_limitations:
      - >-
        One row is a charging unit that may hold one or more ports and one or more
        connectors; rows are not ports.
      - >-
        55 rows nationally report a power output of exactly 0.00 kW, which is not a
        valid power and must not be treated as a rung-1 reported value.
      - >-
        Rung-1 power coverage is uneven by connector: 99.9% for CCS and CHAdeMO but
        73.4% for J3400 and 81.4% for J1772 (port-weighted, national).
```

`SOURCES.yml` finding schema, shown with a real entry (abridged in the prose fields
only):

```yaml
  - id: F-2
    question: >-
      Are the NREL county home charging access shares current values or 2030 scenario
      projections?
    resolved_value: >-
      NEITHER, and the distinction matters. They are a parametric scenario surface, not
      a dated observation: 942,600 rows = 3,142 counties x 3 access scenarios
      (baseline / low / high) x 100 levels of an 'EV Share of Stock' parameter running
      0.01 to 1.00. [...]
    evidence_url: "https://data.nlr.gov/submissions/278"
    retrieved_at: "2026-08-19T00:00:00Z"
    evidence_quote: >-
      Modeled county-level home electric vehicle (EV) charging access shares from the
      study, 'The 2030 National Charging Network: Estimating U.S. Light-Duty Demand for
      Electric Vehicle Charging Infrastructure' by Wood et al. (2023).
    evidence_artifact: "docs/evidence/F-2_nrel_home_charging_semantics.txt"
    evidence_sha256: "a11035f49567ca4b1d40c3c3387e2a5d3d08073df00434a5a05ff65b8be0e5f1"
```

`SOURCES.observed.json` observation schema, one real entry:

```json
{
  "source_id": "afdc_charging_units",
  "status": "confirmed",
  "url": "https://developer.nlr.gov/api/alt-fuel-stations/v1/ev-charging-units.csv",
  "http_status": 200,
  "retrieved_at": "2026-08-19T02:08:50+00:00",
  "elapsed_ms": 1709.4,
  "content_bytes": 1121967,
  "content_sha256": "ba3d6cdafec3145032d18d05059606c5a2621446f763f0bb531e29b60c2a81a1",
  "measurement": {
    "row_count": 2951,
    "field_count": 86,
    "fields": ["Fuel Type Code", "Station Name", "...", "Snapshot Date"],
    "missingness": { "EV CCS Power Output (kW)": 0.80244, "...": 0.0 },
    "schema_hash": "c7ef314df7ff8fce",
    "truncated": false,
    "notes": []
  },
  "rate_limit_headers": { "x-ratelimit-limit": "10", "x-ratelimit-remaining": "1" },
  "vintage": "Wed, 19 Aug 2026 02:08:49 GMT",
  "note": "2951 records measured in the bounded sample. One row per charging unit. ..."
}
```

Drift record schema:

```json
{
  "source_id": "afdc_charging_units",
  "within_expected_row_count": true,
  "observed_row_count": 2951,
  "expected_row_count": [2400, 3600],
  "tolerance_band": [1920, 4320],
  "schema_hash_changed": false,
  "note": "within tolerance"
}
```

---

## 3. Decisions made and why

| Decision | Options considered | Chosen | Rationale | Reversible? |
|---|---|---|---|---|
| Contract vs observations storage | (a) single `SOURCES.yml` as §4.1 specifies; (b) split into a stable contract plus a generated sidecar | **(b) split** | Every live refresh would otherwise dirty the human-reviewed file, and expectation would be indistinguishable from observation. Approved by the project owner in advance as a deviation from §4.1. | Yes |
| Bounding large transfers | (a) `Range` request header; (b) stream and cut off locally | **(b)** | Evidence: with (a) the probe downloaded 3.3 GB. Several hosts advertise `accept-ranges: bytes` and then answer HTTP 200 with the whole file. (b) is robust regardless of server behaviour. | Yes |
| Probe idempotency definition | (a) live runs must be identical; (b) replay runs must be identical, live runs preserve structure | **(b)** | (a) is impossible against changing live sources. (b) is verifiable and is what the gate needs. Verified byte-identical across two replay runs. | Yes |
| Gate network dependence | (a) gate probes live; (b) gate replays committed fixtures | **(b)** | Required by the project owner. Also protects the AFDC free-tier quota, which one live run exhausts. 3.4 MB of fixtures across 47 sources. | Yes |
| Raw seed filenames | (a) rename to shell-safe underscore forms; (b) preserve exactly, map to canonical ids in code | **(b)** | Required by the project owner: raw-source immutability outranks shell convenience. `SEED_PROVENANCE` in `seed_inventory.py` is the mapping layer. | Yes |
| Expected row-count derivation | (a) provisional ±20% band from first live observation; (b) exact frozen values for seed fixtures | **both, per source** | Live sources drift; frozen fixtures do not. Every entry records `expected_range_derivation` in prose. Frozen fixtures carry `drift_tolerance: 0.0`. | Yes |
| Home charging classification | (a) treat the EV-share slice nearest today's penetration as "current"; (b) classify as not-current and take the §7.2 fallback | **(b)** | (a) dresses a modelling choice as a data fact. §7.2 is unambiguous once the shares are established as non-current. Raised as open question 1 for the reviewer. | Yes |
| Substation substitute | (a) adopt transmission-line proximity; (b) record degraded, adopt nothing | **(b)** | Directive D8. A weaker proxy adopted silently would make §7.9's language constraints harder to honour, not easier. | Yes |
| Handling the G9 discrepancy | (a) write a test that passes; (b) reshape the rule; (c) escalate | **(c)** | Required by the working agreement. `docs/reports/PLAN_CHANGE_0.md` with three options. No workaround implemented. | n/a |
| Python version pin for mypy | (a) pin 3.11 per `requires-python`; (b) check against the running interpreter | **(b)** | Pinning 3.11 made the bundled numpy stubs unparseable. The project runs on 3.12 under `uv`. | Yes |

---

## 4. Acceptance criteria verification (Gate part G-A)

Every criterion, its verifying test, and its result. No criterion is marked passed by
inspection.

| # | Criterion (quoted from spec) | Verifying test (full name) | What the test asserts | Result | Evidence |
|---|---|---|---|---|---|
| 1 | "Every source has all contract fields populated" | `tests/regression/test_source_findings.py::test_the_contract_validates_completely` | `validate_contract` raises `ContractError` unless every one of 13 top-level fields, 4 retrieval sub-fields, 5 coverage sub-fields, 3 schema sub-fields and 3 quality sub-fields is present and non-null on all 57 entries, tiers are in `{core, extension, optional}`, ids are unique, `expected_row_count` is an ascending pair, and `backtest_eligible` implies `historical_vintages_available` | **PASS** | 57 sources validate; no exception raised |
| 2 | as above, coverage of the registry | `::test_every_probe_spec_has_a_contract_entry_and_the_reverse` | The set of `ProbeSpec.source_id` equals the set of contract ids | **PASS** | Both sets are the same 57 ids |
| 3 | as above, scale check | `::test_there_are_57_sources_and_10_findings` | Exact counts | **PASS** | 57 sources, 10 findings |
| 4 | "Every Core model has a data path or documented fallback" | `::test_every_source_declares_a_fallback_or_states_it_has_none` | Every entry's `fallback_source` is a non-empty string, and where it is not `"none"` it names an existing contract entry | **PASS** | 57/57; no dangling fallback references |
| 5 | as above, D8 enforcement | `::test_every_source_that_is_not_confirmed_documents_why` | Every source whose observed status is not `confirmed` has non-empty `known_limitations` and a `fallback_source` | **PASS** | 4 non-confirmed sources, all documented |
| 6 | "AFDC connector power missingness measured numerically" | `::test_afdc_exposes_per_connector_power_and_count_columns` | For each of J1772, CCS, CHAdeMO, J3400, J3271, both `EV {c} Connector Count` and `EV {c} Power Output (kW)` appear in the discovered column list | **PASS** | All 10 columns present in the 86-column export |
| 7 | as above | `::test_afdc_power_missingness_is_measured_numerically` | For both the all-rows and public+operational scopes, `rung1_port_coverage` is a float, `total_ports > 0`, and every per-connector `port_coverage` is a float in [0, 1] | **PASS** | 299,289 and 270,620 ports respectively |
| 8 | as above, §7.1 threshold | `::test_rung1_coverage_clears_the_forty_percent_threshold` | `rung1_port_coverage` equals 0.827561 (all rows) and 0.881099 (public + operational) to 1e-6, and the latter exceeds 0.40 | **PASS** | 88.11% > 40%, so no prominent LIMITATIONS entry is triggered on coverage grounds |
| 9 | as above, data fault | `::test_zero_kilowatt_reported_values_are_recorded_as_a_data_fault` | Exactly 55 cells report power of exactly 0.00 kW | **PASS** | 55 |
| 10 | "NREL home charging vintage determined as current or 2030 scenario" | `::test_nrel_home_charging_is_recorded_as_not_current_values` | The contract's `coverage.vintage_semantics` contains "NOT current values" and "942,600", and `historical_vintages_available` is `false` | **PASS** | Resolved: parametric scenario surface |
| 11 | as above, consequence | `::test_home_charging_is_excluded_from_the_primary_siting_objective` | `used_by == ["home_charging_exploratory_index"]` and some `known_limitations` entry contains "EXCLUDED from the primary siting objective" | **PASS** | §7.2 fallback path recorded in the contract itself |
| 12 | "Historical registration vintage availability resolved yes/no" | `::test_historical_state_registration_vintage_availability_is_resolved_yes` | The F-3 evidence lists years 2016–2025, and each of the ten `afdc_state_ev_registrations_{year}` entries has `historical_vintages_available: true` and `backtest_eligible: true` | **PASS** | Resolved **yes**, 10 vintages |
| 13 | as above, secondary result | `::test_the_undated_seed_registration_file_was_dated_to_2023` | Half-up rounding matches the AFDC 2023 vintage for 51/51 jurisdictions, and the `Total` row equals the sum of jurisdictions (3,555,445) | **PASS** | 51/51 |
| 14 | as above, §10.2.3 consequence | `::test_the_reconciliation_constraint_is_available_at_the_backtest_cutoffs` | Contract entries exist for the 2020, 2021 and 2022 vintages | **PASS** | The §10.2.3 unconstrained-propensity fallback is **not** triggered |
| 15 | "Tier A states enumerated with granularity and temporal coverage each" | `::test_tier_a_states_are_enumerated_with_granularity_and_coverage` | F-4 evidence records 14 Atlas states (11 ZIP, 3 county), `login_required: false`, Washington at `census tract (_2020_census_tract)`, and 16 distinct states overall | **PASS** | 16 states |
| 16 | as above, in the contract | `::test_every_atlas_state_entry_declares_its_granularity` | 14 Atlas entries exist; `schema.granularity` is `zip` for 11 and `county` for 3 | **PASS** | 11 / 3 |
| 17 | as above | `::test_washington_is_the_only_tract_granularity_registration_source` | Exactly one contract entry declares `granularity: tract`, and it has `backtest_eligible: false` | **PASS** | `wa_ev_population` |
| 18 | "`probe.py` is idempotent" | `::test_the_probe_is_idempotent_in_replay_mode` | Two subprocess invocations of `python -m pipeline.discovery.probe --offline` against the committed fixtures produce byte-identical output files | **PASS** | Identical bytes |
| 19 | Evidence preservation (owner decision B) | `::test_every_finding_evidence_artifact_still_matches_its_recorded_hash` | For all 10 findings, the artifact exists and its recomputed SHA-256 equals `evidence_sha256` in the contract | **PASS** | 10/10 |
| 20 | as above | `::test_every_finding_carries_a_url_a_timestamp_and_a_quote` | Every finding has a non-empty `evidence_url`, a `retrieved_at` beginning `2026-`, and an `evidence_quote` longer than 10 characters | **PASS** | 10/10 |
| 21 | Substation degradation is real, not assumed | `::test_hifld_substations_service_is_not_national` | Replaying the recorded `returnCountOnly` response yields exactly 128, which is `< 55000`, and the contract's `known_limitations` contains "DEGRADED" | **PASS** | 128 features |
| 22 | Seed provenance integrity | `::test_the_seed_inventory_still_matches_the_delivered_bytes` | Recomputed SHA-256 and byte size of every present seed file equal the recorded inventory values | **PASS** | 10/10 |
| 23 | Large artifact excluded from git | `::test_the_large_transmission_geojson_is_excluded_from_version_control` | `git check-ignore` returns 0 for the 144,115,564-byte GeoJSON | **PASS** | Ignored |
| 24 | No spec targets the retired host | `tests/unit/test_settings_and_registry.py::test_no_spec_targets_the_retired_nrel_host` | No `ProbeSpec.url` contains `developer.nrel.gov` | **PASS** | 0 of 57 |

**Criteria passed: 24/24.**

---

## 5. Test and coverage evidence (Gate part G-B)

### 5.1 Suite summary

```
$ .venv/bin/python -m pytest
........................................................................ [ 48%]
........................................................................ [ 97%]
....                                                                     [100%]
148 passed in 3.69s
```

| File | Tests | Lines |
|---|---:|---:|
| `tests/unit/test_cache.py` | 11 | 150 |
| `tests/unit/test_measure.py` | 26 | 249 |
| `tests/unit/test_contract.py` | 27 | 259 |
| `tests/unit/test_probe.py` | 33 | 373 |
| `tests/unit/test_seed_inventory.py` | 9 | 90 |
| `tests/unit/test_settings_and_registry.py` | 10 | 83 |
| `tests/regression/test_source_findings.py` | 23 | 257 |
| `tests/integration/test_smoke_forward.py` | 9 | 197 |
| **Total** | **148** | **1,658** |

Lint and type checks:

```
$ .venv/bin/python -m ruff check .
All checks passed!

$ .venv/bin/python -m mypy
Success: no issues found in 24 source files
```

`mypy` runs with `strict = true`.

### 5.2 Coverage by module

```
Name                                   Stmts   Miss Branch BrPart  Cover
------------------------------------------------------------------------
pipeline/__init__.py                       0      0      0      0   100%
pipeline/config/__init__.py                0      0      0      0   100%
pipeline/config/settings.py               37      0      0      0   100%
pipeline/discovery/__init__.py             0      0      0      0   100%
pipeline/discovery/cache.py              103      0     14      0   100%
pipeline/discovery/contract.py           116      0     42      0   100%
pipeline/discovery/measure.py            191      0     70      0   100%
pipeline/discovery/probe.py              137      0     54      0   100%
pipeline/discovery/registry.py            53      0      2      0   100%
pipeline/discovery/seed_inventory.py      50      0     10      0   100%
pipeline/sources/__init__.py               0      0      0      0   100%
------------------------------------------------------------------------
TOTAL                                    687      0    192      0   100%
```

| Module | Line % | Branch % | Required | Met? |
|---|---|---|---|---|
| `pipeline/discovery/` | 100% | 100% | 100% (agreed Phase 0 interpretation) | **Yes** |
| `pipeline/config/` | 100% | 100% | not specified | Yes |
| `pipeline/sources/` | n/a — contains only an empty `__init__.py`; 0 statements | n/a | ≥85% | **Vacuously met.** Stated plainly rather than claimed as an achievement: there is no source-adapter code in Phase 0. |
| `pipeline/model/` | — | — | 100% | **Not applicable.** Directory does not exist. First binds in Phase 2. |
| `pipeline/validation/` | — | — | 100% | **Not applicable.** Directory does not exist. First binds in Phase 5. |
| `pipeline/spatial/` | — | — | 100% | **Not applicable.** Directory does not exist. First binds in Phase 2. |
| `pipeline/transform/` | — | — | ≥85% | **Not applicable.** Directory does not exist. First binds in Phase 1. |
| Repository total | 100% | 100% | ≥70% | **Yes** |

Per the project owner's decision A, no placeholder directories or code were created
merely to satisfy a future coverage rule.

### 5.3 Coverage exclusions

| Location | Reason for `pragma: no cover` | Justified? |
|---|---|---|
| `pipeline/discovery/cache.py`, `Fetcher.get` body | `Protocol` method declaration. Its body is the literal `...` and is never executed at runtime; only concrete implementations run, and both `LiveFetcher` and `ReplayFetcher` are fully covered. | Yes |
| `pipeline/discovery/probe.py`, `if __name__ == "__main__":` | Module entry point. `main()` itself is covered by five tests. | Yes |
| `pipeline/discovery/probe.py`, `probe_local` guard for a local spec with no `local_path` | Unreachable given the registry, which is asserted by `test_local_specs_carry_a_path_and_remote_specs_carry_a_url`. Kept as a defensive raise. | Yes |
| `pipeline/discovery/seed_inventory.py`, `main()` | Thin CLI wrapper; the logic it calls (`write_inventory`) is covered. | Yes |
| `tests/regression/test_source_findings.py`, missing-seed-file branch | Handles a clean clone where the gitignored 137 MiB GeoJSON is absent. Cannot be exercised on a machine that has the file. | Yes |

Five exclusions, all justified. None is used to reach a coverage number: coverage is 100%
line and branch on everything that remains.

### 5.4 Notable tests, with assertions quoted

The rung-1 coverage assertion, which pins the number the §7.1 power ladder depends on:

```python
def test_rung1_coverage_clears_the_forty_percent_threshold() -> None:
    """CLAUDE.md 7.1 requires a prominent LIMITATIONS entry below 40% rung-1 coverage."""
    payload = evidence("F-1")
    assert payload["all_rows"]["rung1_port_coverage"] == pytest.approx(0.827561, abs=1e-6)
    assert payload["public_operational_only"]["rung1_port_coverage"] == pytest.approx(
        0.881099, abs=1e-6
    )
    assert payload["public_operational_only"]["rung1_port_coverage"] > 0.40
```

The evidence-integrity test, which is what makes decision B's "resolution with evidence,
not external truth" enforceable:

```python
def test_every_finding_evidence_artifact_still_matches_its_recorded_hash() -> None:
    for finding_id, finding in FINDINGS.items():
        path = PATHS.root / str(finding["evidence_artifact"])
        assert path.exists(), f"{finding_id}: evidence artifact missing"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == finding["evidence_sha256"], (
            f"{finding_id}: evidence artifact changed since the finding was recorded"
        )
```

The idempotency test, run as two real subprocesses rather than in-process:

```python
def test_the_probe_is_idempotent_in_replay_mode(tmp_path: object) -> None:
    """CLAUDE.md 4.2 acceptance: 'probe.py is re-runnable and idempotent'."""
    outputs = []
    for name in ("first.json", "second.json"):
        target = PATHS.root / "data" / "cache" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [sys.executable, "-m", "pipeline.discovery.probe", "--offline",
             "--cache-root", str(PATHS.replay_fixtures), "--out", str(target)],
            cwd=PATHS.root, check=True, capture_output=True,
        )
        outputs.append(target.read_bytes())
        target.unlink()
    assert outputs[0] == outputs[1]
```

The conditional-coverage test, which encodes *why* raw missingness would have been the
wrong measurement:

```python
def test_power_coverage_is_conditional_on_the_connector_existing() -> None:
    """A power column is only meaningful where that connector is actually present."""
    rows = [
        _unit(**{"EV CCS Connector Count": "2", "EV CCS Power Output (kW)": "350"}),
        _unit(**{"EV CCS Connector Count": "1", "EV CCS Power Output (kW)": ""}),
    ]
    result = measure_connector_power_coverage(rows)
    ccs = next(c for c in result["per_connector"] if c["connector"] == "CCS")
    assert ccs["units_with_connector"] == 2
    assert ccs["ports"] == 3
    assert ccs["ports_with_power"] == 2
    assert ccs["port_coverage"] == pytest.approx(2 / 3, abs=1e-6)
    assert result["rung1_port_coverage"] == pytest.approx(2 / 3, abs=1e-6)
```

The credential-safety test:

```python
def test_live_fetcher_records_body_and_metadata(tmp_path: Path) -> None:
    ...
    meta = json.loads(meta_files[0].read_text())
    assert meta["params"] == {"api_key": REDACTION}, "the credential must never reach disk"
```

---

## 6. Regression against prior phases (Gate part G-C)

| Prior phase | Gate suite | Tests | Result |
|---|---|---|---|
| — | — | — | **Not applicable to this phase.** Phase 0 is the first phase; there are no prior gate suites to re-run. |

From Phase 1 onward, `make gate PHASE=n` will run every prior phase's suite. The Phase 0
suite that later phases must keep passing is
`tests/regression/test_source_findings.py` (23 tests) plus
`tests/integration/test_smoke_forward.py` (9 tests).

---

## 7. Forward viability (Gate part G-D)

### 7.1 Output contract table

| Artifact | Schema | Grain | Guaranteed invariants | Consumed by phase |
|---|---|---|---|---|
| `SOURCES.yml` | §2.4 above | one entry per source | All 13 top-level and 15 sub-fields present and non-null; ids unique; tier in `{core, extension, optional}`; `expected_row_count` ascending; `backtest_eligible` ⇒ `historical_vintages_available`; every `fallback_source` either `"none"` or an existing id; every `join_keys` entry present in the observed schema; every `expected_field_count` and `schema_version` matches the observation | 1, 2, 3, 4, 5 |
| `SOURCES.observed.json` | §2.4 above | one observation + one drift record per source | Deterministic under replay (byte-identical); entries sorted by `source_id`; keys sorted; no credential present | 1, 7 |
| `docs/evidence/F-*` | free-form text/JSON | one per finding | SHA-256 matches `SOURCES.yml`; enforced by test | 2, 3, 4, 5 |
| `data/seed/seed_inventory.json` | §2.3 above | one per delivered file | SHA-256 and byte size match the files on disk | 1 |
| `tests/fixtures/replay/` | recorded HTTP body + metadata | one directory per remote source | Every non-local spec replays without network; 47 of 47 | 1 |
| `pipeline/discovery/probe.py` | CLI | — | `--offline` opens no sockets; two runs identical | 1, 7 |

### 7.2 Smoke-forward test

Phase 1's core operation is: *read a source's contract, retrieve it, and land its rows in
a typed staging frame keyed on the contract's declared join keys, using only the field
names Phase 0 discovered.* The smoke-forward test runs exactly that against Phase 0's
real outputs, on the two-state fixture (Minnesota and Illinois) that `CLAUDE.md` §14
requires, entirely offline.

```python
# tests/integration/test_smoke_forward.py
TWO_STATE_FIXTURE = (
    "seed_afdc_stations_mn_20241210",   # Minnesota, 75-column AFDC station schema
    "seed_il_stations",                 # Illinois, reduced station schema
    "seed_mn_county_ev_registrations",  # Minnesota, county EV registrations
    "seed_il_county_ev_monthly_panel",  # Illinois, monthly county panel
)


def stage(source_id: str) -> pd.DataFrame:
    """The minimal Phase 1 staging operation, driven entirely by the contract.

    Staging models must not filter rows (CLAUDE.md section 9): this only types and
    loads. Every column is read as a string, which is what a staging layer does before
    the intermediate layer applies business logic.
    """
    spec = SPECS[source_id]
    if spec.kind == "local_csv":
        assert spec.local_path is not None
        with spec.local_path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
            rows = list(csv.DictReader(fh, delimiter=spec.delimiter))
    else:
        response = ReplayFetcher(PATHS.replay_fixtures).get(
            source_id, spec.url, request_params(spec), spec.headers
        )
        text = response.content.decode("utf-8", errors="replace")
        rows = list(csv.DictReader(io.StringIO(text), delimiter=spec.delimiter))
    frame = pd.DataFrame(rows, dtype="string")
    frame["source_id"] = source_id
    frame["source_vintage"] = str(SOURCES[source_id]["coverage"]["temporal"])
    return frame


def test_every_two_state_fixture_source_stages_with_its_declared_schema() -> None:
    for source_id in TWO_STATE_FIXTURE:
        entry = SOURCES[source_id]
        frame = stage(source_id)
        expected_rows = entry["quality"]["expected_row_count"]
        expected_fields = entry["schema"]["expected_field_count"]

        assert len(frame) == expected_rows[0] == expected_rows[1], source_id
        # Two provenance columns are added by the staging step itself.
        assert len(frame.columns) == expected_fields + 2, source_id
        assert (frame["source_id"] == source_id).all()
        assert frame["source_vintage"].notna().all()
```

**Result:**

```
$ .venv/bin/python -m pytest tests/integration/test_smoke_forward.py -v
tests/integration/test_smoke_forward.py::test_every_two_state_fixture_source_stages_with_its_declared_schema PASSED
tests/integration/test_smoke_forward.py::test_declared_join_keys_exist_in_the_staged_data PASSED
tests/integration/test_smoke_forward.py::test_a_remote_source_stages_from_the_replay_cache_without_network PASSED
tests/integration/test_smoke_forward.py::test_the_two_afdc_extracts_share_one_schema_so_they_can_be_unioned PASSED
tests/integration/test_smoke_forward.py::test_the_power_ladder_input_columns_survive_staging PASSED
tests/integration/test_smoke_forward.py::test_a_source_spec_can_be_reconstructed_from_the_contract_alone PASSED
tests/integration/test_smoke_forward.py::test_every_declared_join_key_exists_in_the_observed_schema PASSED
tests/integration/test_smoke_forward.py::test_expected_field_counts_match_the_observed_schema PASSED
tests/integration/test_smoke_forward.py::test_declared_schema_versions_match_the_observed_schema_hashes PASSED
9 passed in 0.23s
```

Staged shapes: Minnesota AFDC 985 rows × 77 columns (75 + 2 provenance); Illinois
stations 1,626 × 15; Minnesota county registrations 87 × 4; Illinois monthly panel
84 × 108; AFDC charging units (remote, from cache) 2,951 rows including all ten
per-connector columns and `Snapshot Date`.

**This test found a real defect.** On first run it failed with
`AssertionError: seed_il_stations: join key 'ID' absent`. A contract-wide audit then
found **21 join-key errors** across the contract: `id` where the column is `ID`, `state`
where it is `State`, `County` where it is `county`, a `Date` key on a file whose first
column is `Month-Year`, an `ID` key on a file that has no identifier column at all, and
two CenPop files whose first column name carries a UTF-8 byte order mark. All 21 are now
corrected, the BOM is recorded as a known limitation on both CenPop entries, and
`test_every_declared_join_key_exists_in_the_observed_schema` guards the whole contract
against recurrence. The audit also caught two fabricated schema hashes that I had
written into the contract without reading them from the observations; those are now the
measured values (`fc8309b768fd7aa2`, `7999983afe209055`).

**What this proves.** `SOURCES.yml` is machine-consumable. The discovered schemas are
real and match the contract exactly (field counts and order-sensitive hashes both). Every
declared join key exists in the data. A typed staging load succeeds on the shapes Phase 1
will meet, including a remote source served from cache with no network. The two AFDC
extracts share one schema hash, so state extracts can be stacked into one canonical
table. The §7.1 power ladder's input columns survive staging with non-null values.

**What this does not prove.** Nothing about the site / station / charging unit / port
entity hierarchy in §6.1, nothing about DBSCAN site clustering, nothing about
deduplication of the 1,756 coordinate-duplicate pairs, nothing about spatial joins or H3
allocation, and nothing about the correctness of any modelled quantity. It also does not
prove any full-file property: every remote fixture holds only a bounded head of its
source.

### 7.3 Assumption ledger additions

Fifteen assumptions were opened; the full text of each is in
`docs/reports/ASSUMPTION_LEDGER.md`. Summarised:

| ID | Assumption (falsifiable statement) | Depends on | Tested in | Status |
|---|---|---|---|---|
| A-0.1 | The live AFDC station schema is identical to the December 2024 seed schema | Both hash `f6860736f1304654` | 1 | **CONFIRMED** |
| A-0.2 | AFDC serves no historical snapshots, so reconstruction is survivorship-biased | No snapshot parameter documented | 5 | OPEN |
| A-0.3 | Rung-1 power coverage ≥ 40% | Measured 88.11% | 2 | **CONFIRMED** |
| A-0.4 | NREL home charging cannot be a present-day calibration target | Parametric over EV share | 3 | **CONFIRMED** |
| A-0.5 | Each AFDC annual registration page is a contemporaneous snapshot, not a retrospective reconstruction | Not stated by the publisher. **Weakest link in the D1 vintage story** | 5 | OPEN |
| A-0.6 | Block-group centroids suffice, or TIGER + P.L. 94-171 gives block-level weights at acceptable cost | No ready-made block product exists | 2 | OPEN |
| A-0.7 | ZIP registrations can be reallocated to tracts with acceptable error | ZCTAs do not nest in tracts; 11 of 16 states are ZIP-grain | 3 | OPEN |
| A-0.8 | The seed GeoJSON (94,216 features) and live service (52,244) are the same dataset at different vintages | Difference of 41,972 features, undocumented | 1 | OPEN |
| A-0.9 | A free national substation dataset exists somewhere unsearched, or §7.8/§7.9 can be respecified without one | Five searches found none. **Blocks §7.8 and §7.9 as specified** | 4 | OPEN |
| A-0.10 | The Internet Archive CEJST copy stays retrievable, or is mirrored before it is not | Live host has no DNS record | 6 | OPEN |
| A-0.11 | A machine-retrievable FHWA traffic URL exists and is stable | Only the landing page was found | 5 | OPEN |
| A-0.12 | Usable Tier A states are numerous enough for LOSO to have power | 16 states, but tract usability depends on A-0.7. If ≤3, a formal plan change is required before Phase 3 | 3 | OPEN |
| A-0.13 | Bounded-sample row-count ranges detect real drift without false alarms | Ranges from 64 KiB samples ± 20% | 1 | OPEN |
| A-0.14 | 3.4 MB of bounded replay fixtures stay sufficient as a gate substrate | Fixtures hold only file heads | 1 | OPEN |
| A-0.15 | The seed files remain byte-identical for the life of the project | SHA-256 recorded and test-enforced | every | **CONFIRMED** |

### 7.4 Prior assumptions re-checked

**Not applicable to this phase.** Phase 0 is the first phase; there are no prior
assumptions.

---

## 8. Impact log delta (Cross-phase protocol)

### 8.1 Opened this phase

**None.** Phase 0 is the first phase, so there is no earlier phase for it to invalidate.

Two Phase 0 findings concern the specification and the delivered documentation rather
than a prior phase's output, and so are correctly *not* impact-log entries:

- Domain rule **G9** is factually wrong against the delivered data. Escalated through
  `docs/reports/PLAN_CHANGE_0.md`. No workaround implemented.
- `SETUP.md` names a retired NREL host and describes the Census API key as optional.
  Recorded in `docs/SOURCE_VERIFICATION.md` §3.

### 8.2 Resolved this phase

None.

### 8.3 Still open

None.

---

## 9. Results and numbers

### 9.1 Overall probe result

All 57 sources probed live on 2026-08-19 UTC.

| Status | Count | Sources |
|---|---:|---|
| `confirmed` | 53 | — |
| `gated` | 3 | `afdc_stations` (quota exhausted), `census_acs_api`, `eia_prices_api` |
| `degraded` | 0 | — |
| `unavailable` | 1 | `census_cenpop_block` (probed to establish absence) |

By tier: 53 Core, 3 Optional, 1 Extension.

### 9.2 Unknown (a) — AFDC per-connector power and port counts

**Both are exposed, at per-connector granularity.** The endpoint is
`GET https://developer.nlr.gov/api/alt-fuel-stations/v1/ev-charging-units.csv`, returning
CSV, one row per charging unit. Its documentation states: *"Each row in the spreadsheet
represents an EV charging unit that might have one or more ports and one or more
connectors."*

The export has 86 columns: the 75 station columns byte-identical to the station schema,
plus eleven:

```
EV J1772 Connector Count,   EV J1772 Power Output (kW),
EV CCS Connector Count,     EV CCS Power Output (kW),
EV CHAdeMO Connector Count, EV CHAdeMO Power Output (kW),
EV J3400 Connector Count,   EV J3400 Power Output (kW),
EV J3271 Connector Count,   EV J3271 Power Output (kW),
Snapshot Date
```

The national export (292,435 unit rows across 89,687 distinct station IDs,
111,271,558 bytes) gives:

**Connector counts** are effectively complete: 292,423 of 292,435 rows non-null on every
count column, i.e. 0.004% missing.

**Power, port-weighted, all rows:**

| Connector | Units with connector | Ports | Units with kW | Unit coverage | **Port coverage** |
|---|---:|---:|---:|---:|---:|
| J1772 | 191,631 | 191,803 | 156,029 | 81.42% | **81.36%** |
| CCS | 38,508 | 39,362 | 38,480 | 99.93% | **99.93%** |
| CHAdeMO | 8,766 | 8,766 | 8,754 | 99.86% | **99.86%** |
| J3400 (NACS) | 59,348 | 59,348 | 43,533 | 73.35% | **73.35%** |
| J3271 | 10 | 10 | 10 | 100.00% | **100.00%** |
| **Total** | | **299,289** | | | **82.76%** |

**Power on public + operational supply** (`Status Code == 'E'` and
`Access Code == 'public'`, domain rules G2 and G3 — the subset the supply model uses):
256,095 unit rows, 270,620 ports, **238,443 ports with reported power = 88.11%**.

Raw column missingness would have given a badly misleading picture: `EV CCS Power Output
(kW)` is 86.84% null across all rows, but that is almost entirely rows with no CCS
connector. Conditional on the connector existing, CCS coverage is 99.93%.

**Consequence for §7.1.** The specification says: *"Phase 0 measures rung 1 missingness;
if rung 1 coverage is below 40 percent, record that prominently in
`docs/LIMITATIONS.md`."* At 88.11% port-weighted on public operational supply, that
threshold is comfortably cleared and no prominent limitation is triggered on coverage
grounds. Two qualifications remain, both recorded in the contract: coverage is uneven by
connector (73.35% for J3400 versus 99.93% for CCS), so rung 2's empirical
`(network, connector_type)` median will matter most for NACS and Level 2; and **55 cells
report a power output of exactly 0.00 kW**, which is not a valid power and must not be
treated as a rung-1 reported value.

Distribution of reported power where present:

| Connector | n | min | p25 | median | p75 | max |
|---|---:|---:|---:|---:|---:|---:|
| J1772 | 156,029 | 0.00 | 6.50 | 6.50 | 7.70 | 180.00 |
| CCS | 38,480 | 0.00 | 120.00 | 200.00 | 350.00 | 640.00 |
| J3400 | 43,533 | 3.60 | 250.00 | 250.00 | 325.00 | 500.00 |

**Historical vintages: none.** The endpoint documents no snapshot or date parameter. The
`Snapshot Date` column exists but always carries the current date (2026-08-19 in this
run). `backtest_eligible: false`; assumption A-0.2.

### 9.3 Unknown (b) — NREL home charging vintage

**Neither current values nor a single 2030 projection. It is a parametric scenario
surface.**

The dataset is *County Electric Vehicle Home Charging Access Shares from the 2030
National Charging Network Study* (Ge, Wood & Borlaug 2024; DOI 10.7799/2483609),
distributed as a 30,335,649-byte workbook. Its own description sheet reads:

> This file contains modeled county-level home EV charging access shares from the study,
> "The 2030 National Charging Network: Estimating U.S. Light-Duty Demand for Electric
> Vehicle Charging Infrastructure" by Wood et al. (2023).

The `C-Data` sheet has six columns and **942,600 data rows**:

```
County FIPS | State FIPS | County Name | Home Access Scenario | EV Share of Stock | Home Charging Access
1001        | 1          | Autauga, AL | baseline             | 0.01              | 0.996
1001        | 1          | Autauga, AL | baseline             | 0.02              | 0.995
1001        | 1          | Autauga, AL | baseline             | 0.03              | 0.983
```

942,600 = **3,142 counties × 3 scenarios × 100 EV-share levels**. The scenarios, quoted
from the workbook's own data dictionary:

> **Baseline:** Average of Low and High scenarios.
> **Low:** "Existing Access" scenario from Ge et al. (2021) assumes EV owners use
> existing electrical outlets at their residential parking locations.
> **High:** "Potential Access" scenario from Ge et al. (2021) assumes EV owners may
> install additional electrical infrastructure to enable home charging at their primary
> parking location.

`EV Share of Stock` runs 0.01 to 1.00 in steps of 0.01. Home charging access is published
*as a function of assumed fleet penetration*, and it falls steeply with it — baseline
median access is 0.991 at 1% EV share, 0.973 at 5%, 0.857 at 30%, and 0.489 at 100%.

**Consequence for §7.2.** The primary path requires the NREL county shares as a
calibration target for a tract-level downscaling model. They cannot serve as one, because
selecting a slice of the EV-share parameter is a modelling assumption, not an observation.
The specification's fallback path therefore applies, and the contract records it:

- home charging access ships as a **clearly labelled exploratory index**;
- it is **excluded from the primary siting objective function**;
- it is exposed only as a user-selectable weight with a sensitivity display;
- no hand-picked coefficients are published as if calibrated.

Enforced by `test_home_charging_is_excluded_from_the_primary_siting_objective`, which
asserts `used_by == ["home_charging_exploratory_index"]`.

One practical note for Phase 1: the workbook declares the namespace
`http://purl.oclc.org/ooxml/spreadsheetml/main` rather than the standard
`schemas.openxmlformats.org` one, so `openpyxl` reports **zero worksheets** and silently
returns nothing. It must be parsed from the underlying XML.

### 9.4 Unknown (c) — historical registration vintages

**Yes, at both state and sub-state level, and neither requires a login.**

**State level.** AFDC publishes ten annual vintages at
`https://afdc.energy.gov/vehicle-registration?year={year}`, one HTML table each (no JSON
or CSV endpoint exists, so scraping is the retrieval method). Each has 51 jurisdictions
plus a `United States` total row. The publisher states:

> Counts are rounded to the closest 100 vehicles and reflect the total number of
> light-duty registered vehicles through the selected year. Fuel types are based on
> vehicle identification numbers (VINs).

National EV totals by vintage, as measured:

| Year | US total EV | Oregon | Kansas | Iowa |
|---|---:|---:|---:|---:|
| 2016 | 280,300 | 7,700 | 600 | 400 |
| 2017 | 377,100 | 10,000 | 1,000 | 600 |
| 2018 | 572,600 | 13,800 | 1,700 | 1,100 |
| 2019 | 783,600 | 18,800 | 2,300 | 1,600 |
| 2020 | 1,018,900 | 22,800 | 3,100 | 2,300 |
| 2021 | 1,454,400 | 30,300 | 4,500 | 3,700 |
| 2022 | 2,442,300 | 47,000 | 7,600 | 6,200 |
| 2023 | 3,555,900 | 64,400 | 11,300 | 9,000 |
| 2024 | 4,503,700 | 78,400 | 14,500 | 11,700 |
| 2025 | 5,689,100 | 98,000 | 18,700 | 15,100 |

**Sub-state level.** Every Atlas EV Hub state export carries a repeated DMV snapshot
series: columns `Registration Date` (monthly), `DMV Snapshot ID`, `DMV Snapshot (Date)`
and `Latest DMV Snapshot Flag`. The earliest snapshot observed is 2017-12-31 (New
Jersey). Historical sub-state vintages are therefore reconstructable by construction, not
by inference.

**Consequence for §10.2.3.** The specification anticipates the negative case: *"If Phase 0
finds no historical state total vintages, the reconciliation constraint cannot be applied
at the cutoff."* It can. Vintages exist for all three rolling origins (2020, 2021, 2022),
so the demand model's reconciliation constraint can be applied at each cutoff and **the
unconstrained-propensity fallback is not triggered.** The backtested model and the
deployed model will differ less than §10.2.3 feared, though §10.2.3's other exclusions
still apply.

**Secondary result: the undated seed file is dated.**
`data/seed/EV_Registration_Counts_by_State.csv` arrived with no vintage. Rounding every
value half-up to the nearest 100 and comparing against each AFDC vintage:

| Vintage | Jurisdictions matching |
|---|---|
| 2022 | 0 / 51 |
| **2023** | **51 / 51** |
| 2024 | 0 / 51 |

It is the AFDC 2023 vintage, unrounded. Its `Total` row (3,555,445) equals the sum of its
51 jurisdiction rows exactly.

**Caveat, recorded as assumption A-0.5.** Whether each year page is a contemporaneous
snapshot or a retrospective reconstruction from current VIN data is not stated by the
publisher. If retrospective, the series is survivorship-affected and its use at a
backtest cutoff needs an explicit caveat. This is the weakest link in the D1 vintage
story and is flagged for Phase 5.

### 9.5 Unknown (d) — Tier A states

**Sixteen distinct states have open sub-state EV registration data, from three
independent sources, none login-gated.**

**Atlas EV Hub — 14 states, uniform 13-column vehicle-grain schema.** No account is
required; direct CSV links are public. The schema is identical across states except that
the second column is `ZIP Code` or `County`:

```
State, {ZIP Code|County}, Registration Date, Vehicle Make, Vehicle Model,
Vehicle Model Year, Drivetrain Type, Vehicle GVWR Class, Vehicle GVWR Category,
Vehicle Count, DMV Snapshot ID, DMV Snapshot (Date), Latest DMV Snapshot Flag
```

Two schema hashes: `f9bf2ed08cb72100` (ZIP grain) and `fbbb059d7e4761db` (county grain).

| State | Granularity | File bytes | Last modified |
|---|---|---:|---|
| NY | ZIP | 1,320,829,913 | 2026-03-18 |
| TX | ZIP | 927,191,057 | 2026-03-24 |
| CO | ZIP | 664,460,416 | 2026-03-24 |
| MN | ZIP | 112,777,329 | 2026-02-27 |
| NJ | ZIP | 86,988,084 | 2026-03-18 |
| NM | ZIP | 68,250,337 | 2026-07-29 |
| VA | **County** | 48,736,748 | 2026-07-29 |
| CT | ZIP | 36,236,372 | 2026-01-12 |
| TN | **County** | 28,600,788 | 2026-02-27 |
| ME | ZIP | 27,799,658 | 2026-02-27 |
| OR | ZIP | 26,977,381 | 2025-09-20 |
| NC | ZIP | 22,705,092 | 2025-09-20 |
| VT | ZIP | 16,995,725 | 2026-02-27 |
| MT | **County** | 3,933,265 | 2026-02-27 |

11 ZIP-grain, 3 county-grain, ~3.4 GB in total. Temporal coverage: per-vehicle
`Registration Date` plus a DMV snapshot series reaching back to 2017-12-31 at the
earliest.

**Washington — the only tract-granularity source.** `data.wa.gov` resource `f6w7-q2d2`,
Socrata, Open Data Commons Open Database License, **294,193 vehicle rows**, 19 columns
including **`_2020_census_tract`**. This is a current snapshot with no registration-date
field, so it yields no historical vintages and cannot be used at a backtest cutoff
(`backtest_eligible: false`).

**Delivered seed files — Illinois and Minnesota.** Illinois: county grain, **84 monthly
observations from 2017-11 to 2024-11**. Its 106 columns are `Month-Year`, 102 Illinois
county columns, and `Chicago`, `Unknown County` and `Total Count`, which are not
counties and must be excluded from county aggregations. This is the longest sub-state
time series available and the basis for the Extension-tier forecast bakeoff (§7.10).
Minnesota: county grain, single snapshot, 87 rows. Minnesota also appears in Atlas at ZIP
grain.

**Distinct states with sub-state data (16):** CO, CT, IL, ME, MN, MT, NC, NJ, NM, NY, OR,
TN, TX, VA, VT, WA.

**Bearing on §7.4 and §10.1, recorded as assumptions A-0.7 and A-0.12.** Only Washington
is natively tract-grain. Eleven of the sixteen are ZIP-grain and need a ZIP-to-tract
crosswalk, and ZIP Code Tabulation Areas do not nest inside tracts. The count of
*genuinely usable* Tier A states at tract granularity therefore depends on how well that
crosswalk performs, which Phase 3 will determine. Per the project owner's instruction, if
that count falls to three or fewer, the leave-one-state-out design must be reconsidered
through a formal plan change rather than continued quietly.

### 9.6 Other substantive findings

**The NREL developer host was retired.** `developer.nrel.gov` has no DNS A record from
any resolver tested. NREL's developer network moved to `developer.nlr.gov`; the old
domain was retired on 29 May 2026. The replacement was verified live: HTTP 200,
`total_results` 89,685 electric station records, 292,399 ports. `SETUP.md` §3 directs the
operator to `developer.nrel.gov/signup`, which no longer resolves.

**The AFDC DEMO_KEY rate limit, measured by exhausting it.** §4.2 requires the rate limit
to be measured empirically. After ten requests the endpoint answered:

```
HTTP 429
x-ratelimit-limit:     10
x-ratelimit-remaining: 0
retry-after:           78590     (~21.8 hours)
```

All three AFDC specs share this quota, so one full probe run consumes it. A free personal
key is required for repeated probing or any scheduled refresh.

**No national HIFLD substation layer could be located.** Five searches, all negative: the
HIFLD ArcGIS organisation (526 services) has transmission lines but no substations; the
EIA Energy Atlas organisation (79 services) has none; `hifld-geoplatform.hub.arcgis.com`
returns 404; an ArcGIS Online title search found no authoritative national match; and the
best candidate service returns `{"count": 128}` against a historical national figure on
the order of 55,000–80,000. **This degrades §7.8 candidate filtering and §7.9 grid
proximity as specified.** Per D8 no substitute has been adopted. Assumption A-0.9.

**No block-level population-weighted centroid product exists.** The `CenPop2020`
directory publishes `county/`, `tract/` and `blkgrp/` only; the block path returns 404.
Tract centroids (1,505 for Minnesota) and block-group centroids (4,706) are confirmed.
Genuine block-level weighting must be constructed from TIGER `TABBLOCK20`
(147,565,957 bytes for Minnesota, carrying `INTPTLAT`/`INTPTLON`) joined to 2020 P.L.
94-171 block population (29,625,918 bytes, keyless). §7.5 permits *"population-weighted
centroids **or** block-level allocation"* while §7.6 requires *"block-level population
weights"*; both paths are free and the choice is a Phase 2 decision. Assumption A-0.6.

**CEJST's live host is gone; the archive works.** Neither
`screeningtool.geoplatform.gov` nor `static-data-screeningtool.geoplatform.gov` has a DNS
record. The v2.0 communities CSV (45,316,831 bytes, 136 columns) was retrieved through
the Internet Archive. Consistent with §8, which permits it only as an archived historical
classification because Executive Order 14008 was revoked on 20 January 2025.

**The live HIFLD transmission service and the delivered seed GeoJSON disagree**: 52,244
features against 94,216, a difference of 41,972, with no documented reason. Assumption
A-0.8.

**The Census ACS API now requires a key**; the keyless bulk summary file path is
confirmed and becomes the primary route.

**`egrid` is reachable but has no consumer.** It appears in the §3 repository layout but
no model in §7 uses it. Recorded, not resolved; raised as open question 3.

**Domain rule G9 is factually wrong against the delivered data.** G9 and
`data/seed/MANIFEST.md` both state Oregon reports 6,436 EV registrations; the delivered
file records **64,361** (Kansas 11,271, Iowa 9,031 and Maine 7,377 all match as stated).
The general claim of "inconsistent reporting vintages across states" also fails: the file
is one consistent 2023 vintage across 51 of 51 jurisdictions. Because §14 requires a
regression test per rule G1–G14, a test asserting G9 as written would fail. Escalated in
`docs/reports/PLAN_CHANGE_0.md` with three options and a recommendation. No workaround
implemented.

### 9.7 Domain rules G1–G14 reproduced from the delivered data

Regression tests for these belong to Phase 1, but Phase 0 verified the underlying
measurements against `alt_fuel_stations (Dec 11 2024).csv`:

| Measure | Value |
|---|---:|
| Total station records | 79,618 |
| `Status Code = E` (available) | 73,972 |
| `Status Code = T` (temporarily unavailable) | 5,217 |
| `Status Code = P` (planned) | 429 |
| `Access Code = public` | 74,956 |
| `Access Code = private` | 4,662 |
| `EV Level1 EVSE Num` total | 3,018 |
| `EV Level2 EVSE Num` total | 173,892 |
| `EV DC Fast Count` total | 51,752 |
| **Total ports** | **228,662** |
| Exact coordinate-duplicate rows | 1,756 |
| Null `Open Date` | 455 |

79,618 station records represent 228,662 ports: counting records as capacity understates
supply roughly threefold, and unevenly across states (G1).

---

## 10. Limitations introduced or discovered

| Limitation | Cause | Effect on downstream results | Mitigated? | Recorded in LIMITATIONS.md? |
|---|---|---|---|---|
| No national substation dataset | Not published anywhere Phase 0 could find | §7.8 candidate filtering and §7.9 grid proximity cannot be built as specified | No. D8 followed: nothing substituted. A-0.9, must resolve before Phase 4 | Not yet — `docs/LIMITATIONS.md` is a Phase 7 deliverable; recorded in `SOURCE_VERIFICATION.md` §2.1 |
| Home charging excluded from the primary objective | The NREL shares are parametric, not current | §7.2's primary downscaling path is unavailable; home charging becomes an exploratory index only | Yes, by taking the specified fallback | As above |
| Block-level population weights must be constructed | No ready-made product | §7.6 needs a build step, or a documented drop to block-group grain | Partially: both free paths confirmed | As above |
| AFDC reconstruction is survivorship-biased | No historical snapshots served | §10.2 alignment must be labelled an approximate reconstruction (G10, G11) | No, and not mitigable with current sources | As above |
| CEJST depends on a third-party archive | The live host has no DNS record | The archived equity overlay could disappear | No. A local mirror is recommended before Phase 6 | As above |
| No machine-retrievable FHWA URL | Only a landing page was found | Traffic is named in §10.2.3's backtest feature set | No. A-0.11, must resolve before Phase 5 | As above |
| Expected row-count ranges rest on bounded samples | Full files reach 1.3 GB | Drift detection may be over- or under-sensitive for large sources | Partially: derivation recorded per source; A-0.13 | As above |
| Replay fixtures hold only file heads | Version-control size limits | Later phases needing full-file behaviour need a different substrate | No. A-0.14 | As above |
| AFDC probing is quota-limited on DEMO_KEY | 10 requests per window | One full probe run exhausts the AFDC budget | Partially: replay mode means the gate never spends quota. Requires an operator-supplied key | As above |
| `pipeline/sources/` has no code | Phase 0 builds discovery, not adapters | Its ≥85% coverage requirement is vacuously met | n/a; stated plainly rather than claimed | n/a |

`docs/LIMITATIONS.md` is a §16 deliverable due in Phase 7. Every row above is recorded
now in `docs/SOURCE_VERIFICATION.md` and `docs/reports/ASSUMPTION_LEDGER.md` so nothing
waits on that file.

---

## 11. Specification compliance

### 11.1 Prime directives

| Directive | How compliance is enforced | Verified by |
|---|---|---|
| **D1** No temporal leakage | `validate_contract` raises unless `backtest_eligible: true` implies `coverage.historical_vintages_available: true`; every source records `vintage_field` and `vintage_semantics`. The `assert_no_leakage` runtime guard itself is a Phase 5 deliverable. | `test_backtest_eligible_must_agree_with_historical_vintages_available`; `test_historical_state_registration_vintage_availability_is_resolved_yes` |
| **D2** No supply-to-demand loop | No feature engineering exists yet. Structurally prepared: `used_by` separates supply consumers (`supply`, `power_ladder`) from demand consumers (`demand_model`), so a supply source appearing in a demand feature set is visible in the contract. Enforcement by test is a Phase 3 deliverable. | Not yet exercised. Phase 3. |
| **D3** Three validation terms | This report and `SOURCE_VERIFICATION.md` use "demand model validation", "historical deployment alignment" and "cross-objective robustness" only in their §D3 senses, and make no optimality claim anywhere. The copy lint that enforces this mechanically is a Phase 5 deliverable. | Manual for now; §12 open question 4 asks whether to bring the lint forward. |
| **D4** Zero recurring cost | Every one of the 57 sources is free. Three need a free-tier key (`NREL_API_KEY`, `CENSUS_API_KEY`, `EIA_API_KEY`); all three have a documented keyless or fallback path. No paid API, database, tile host or LLM is a dependency. | `SOURCES.yml` `retrieval.auth` on all 57 entries; `SOURCE_VERIFICATION.md` §4 |
| **D5** Greenfield | No prior version was consulted, matched or extended. The information architecture is derived from `CLAUDE.md` alone. | n/a |
| **D6** Grid proximity language | No grid claim is made anywhere in Phase 0 output. `hifld_substations` is described as a proximity proxy and its degradation is stated. The words "grid feasible", "interconnection ready" and "grid capacity" appear nowhere. | Manual review; the copy lint is Phase 5/6 |
| **D7** Uncertainty first-class | No modelled quantity exists yet. Structurally prepared: every source carries `quality.drift_tolerance` and `expected_range_derivation`, and `known_limitations` is mandatory. | Phase 3 |
| **D8** Explicit degradation | Four sources are non-confirmed and every one is recorded with a status, a machine-generated reason and human-written limitations. No plausible default was substituted anywhere — most pointedly, no substation dataset was adopted to paper over the §7.8/§7.9 gap. | `test_every_source_that_is_not_confirmed_documents_why`; `test_probe_local_reports_an_absent_file_without_substituting_anything` |

### 11.2 Deviations from specification

| Spec section | What the spec says | What was done | Why | Approved? |
|---|---|---|---|---|
| §4.1 | `SOURCES.yml` holds contract and live measurements together, including `status`, `observed_row_count`, `missingness`, `last_successful_retrieval` | Split: `SOURCES.yml` holds the stable contract; `SOURCES.observed.json` holds all measurements and the probe-assigned status | Every live refresh would otherwise dirty the human-reviewed file and make expectation indistinguishable from observation | **Yes**, approved by the project owner in advance |
| §15.1 G-B | 100% line and branch on `pipeline/model/`, `pipeline/validation/`, `pipeline/spatial/`; ≥85% on `pipeline/transform/`, `pipeline/sources/` | 100% on `pipeline/discovery/`; ≥70% repo-wide; the named directories reported not applicable because they do not exist | Those directories are created in Phases 1–5. No placeholder code was created to satisfy a future rule | **Yes**, approved by the project owner in advance |
| §15.5 Phase 0, G-A | "No criterion is marked passed by inspection" | Criteria 10–17 verify that a research question is *resolved and evidenced* — resolved value, evidence URL, retrieval timestamp, supporting quote, and a SHA-256-pinned cached artifact — not that the external conclusion is objectively true | No test can prove an external fact about the world. The gate verifies resolution with preserved evidence | **Yes**, approved by the project owner in advance, with strengthened evidence requirements |
| §3 repository layout | `pipeline/discovery/` contains `probe.py` | It contains `probe.py` plus `cache.py`, `measure.py`, `contract.py`, `registry.py`, `seed_inventory.py` | Splitting fetching, measurement, contract handling and declarative specs keeps each unit small enough for 100% branch coverage. `probe.py` remains the entry point | Not separately approved; a structural elaboration within the named directory rather than a change of contents. Flagged here for the reviewer |
| §5 rule G9 | Oregon reports 6,436 EV registrations; state vintages are inconsistent | Neither is true of the delivered file. **No workaround implemented.** Escalated | The working agreement requires escalation rather than silent revision | **Pending** — `docs/reports/PLAN_CHANGE_0.md` |

---

## 12. Open questions for the reviewer

1. **Should the NREL home charging surface be used at a chosen EV-share slice, or stay
   out of the primary objective?** The dataset gives home charging access at 100 levels
   of assumed fleet penetration. Current US light-duty EV stock is roughly 2% of the
   fleet, so the 0.02 slice is arguably "approximately current". I took the conservative
   reading — a parametric surface is not a present-day observation, so §7.2's fallback
   applies and home charging is excluded from the primary siting objective. The opposite
   reading is defensible and would materially change Phase 3, because home charging
   access is one of the strongest available predictors of public charging need. Which
   reading do you want?

2. **How should §7.8 and §7.9 proceed with no national substation dataset?** Three
   routes: (a) keep searching in Phase 4 and accept schedule risk; (b) respecify grid
   proximity in terms of transmission-line distance, which is a weaker proxy and would
   require the D6 language constraints to be tightened further; (c) drop the grid
   proximity constraint from candidate filtering entirely and state its absence. I have
   adopted none of them and recorded the gap as assumption A-0.9. This needs a decision
   before Phase 4, not at it.

3. **What consumes eGRID?** It is listed in the §3 repository layout as
   `pipeline/sources/egrid.py`, but no model in §7 uses grid emissions data, and I have
   recorded its `used_by` as empty. Should it be dropped from the source inventory, or is
   there an intended consumer that §7 omits?

4. **Should the D3 vocabulary copy lint be brought forward from Phase 5?** §15.5 schedules
   it for Phase 5, but every phase from here produces prose that must respect the three
   validation terms and the §11.5 UI copy rules. A lint that runs from Phase 1 would
   catch drift when it is cheap. It is a small piece of work and would be a scope addition
   to Phase 1, so I am not doing it unless you say so.

5. **Is assumption A-0.5 worth resolving before Phase 5?** Whether AFDC's annual
   registration pages are contemporaneous snapshots or retrospective reconstructions from
   current VIN data determines whether the reconciliation constraint at the 2020/2021/2022
   backtest cutoffs is genuinely vintage-clean or subtly leaky. It is the weakest link in
   the D1 story and the publisher does not state it. Resolving it may need a direct
   enquiry to NREL rather than more probing.

---

## 13. Next phase readiness

| Check | Status |
|---|---|
| All acceptance criteria passed | **Yes — 24/24** |
| Coverage thresholds met | **Yes** — 100% line and branch on `pipeline/discovery/`; 100% repo-wide against a ≥70% requirement |
| All prior gates passing | **Not applicable** — Phase 0 is the first phase |
| Smoke-forward test passing | **Yes** — 9 tests, offline, against real Phase 0 output; it found and forced the fix of 21 contract join-key errors |
| Report complete and self-contained | **Yes** |
| No S1 impacts open | **Yes** — the impact log is empty |

**Recommendation: PROCEED to Phase 1, conditional on one decision.**

`docs/reports/PLAN_CHANGE_0.md` must be resolved before Phase 1 writes the G1–G14
regression suite, because domain rule G9 as written cannot pass against the delivered
data. Every other Phase 1 input is ready. The plan change does not block the Phase 0
gate, and Phase 0 stops here regardless.

Two operator actions would also help Phase 1: obtain a free API key at
`developer.nlr.gov` (not the retired URL in `SETUP.md`) and set `NREL_API_KEY`, and
obtain a free Census key for `CENSUS_API_KEY` — though the keyless bulk path means the
latter is optional in practice.

---

## Corrections

*(none)*
