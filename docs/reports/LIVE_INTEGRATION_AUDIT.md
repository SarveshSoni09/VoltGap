# Live Integration Assurance Checkpoint

| Field | Value |
|---|---|
| Date | 2026-08-26 |
| Scope | Integration correctness only. Not Phase 3. No model fitting, siting, forecasting or frontend work |
| Deterministic suite | 585 tests pass; 100% line and branch coverage (2,325 statements, 548 branches, zero missed) |
| Live suite | 46 tests pass, all marked `live` and excluded from every deterministic gate |
| Prepared by | Claude Code |

---

## A. Executive result

## **PASS — Phase 3 may begin**

Every Core source on the Phase 3 critical path has had its **current production
retrieval path** exercised with real credentials, and the data received match the
assumptions encoded in VoltGap. Two genuine defects in existing code were found and
fixed. One Phase 0 claim was imprecise and has been corrected against live evidence. Two
Core sources were **not** live-tested; neither is on the Phase 3 critical path and both
are recorded as open risks in §I.

The checkpoint's own premise held: **100% coverage was not equivalent to live external
correctness.** The two defects below were invisible to a fully-covered deterministic
suite because they concerned behaviour the fixtures never exhibited.

---

## B. Credential matrix

Presence and authentication only. **No value is printed, logged, cached or reported
anywhere in this repository.**

| Variable | Present | Successfully authenticated |
|---|---|---|
| `NREL_API_KEY` | yes | yes |
| `CENSUS_API_KEY` | yes | yes |
| `HUD_USER_TOKEN` | yes | yes |
| `EIA_API_KEY` | yes | yes |

Verified before anything else: `.env` is matched by `.gitignore:2`, is untracked
(`git ls-files .env` is empty), and `.env.example` contains 7 assignment lines of which
**0** carry a value.

---

## C. Core source integration matrix

| source_id | Tier | Consumer | Auth | Cred | Live | HTTP | Schema | Rows checked | Pagination | Fallback | FB live | Reconciled | Vintage | D8 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `afdc_stations` | Core | P2 supply, P5 alignment | key | req | ✅ | 200 | ✅ | 380 (RI) | ✅ | seed snapshot | — | ✅ | current | ✅ |
| `afdc_charging_units` | Core | P2 power ladder | key | req | ✅ | 200 | ✅ | 1,045 (RI) | ✅ | CSV | ✅ | ✅ | current | ✅ |
| `afdc_charging_units_csv_fallback` | Core | fallback only | key | req | ✅ | 200 | ✅ | 1,045 (RI) | — | none | — | ✅ | Snapshot Date | ✅ |
| `afdc_state_ev_registrations_2016..2025` | Core | P3 reconciliation, P5 | none | none | ✅ | 200 | ✅ | 52/vintage | — | seed file | — | ✅ | year param | ✅ |
| `census_acs_api` | Core | P3 features | key | req | ✅ | 200 | ✅ | 1 tract | — | bulk | ✅ | ✅ | 2023 5-yr | ✅ |
| `census_acs_bulk` | Core | P3 features (primary) | none | none | ✅ | 200 | ✅ | streamed | — | API | ✅ | ✅ | 2023 5-yr | ✅ |
| `hud_usps_zip_tract` | Core | **P3 ZIP→tract (new, preferred)** | Bearer | req | ✅ | 200 | ✅ | 1–24/ZIP | — | land area | ✅ | ✅ | 2026 Q2 | ✅ |
| `census_zcta_tract_landarea` | Core | P3 fallback allocation | none | none | ✅ | 200 | ✅ | 697 (bounded) | — | none | — | ✅ | 2020 | ✅ |
| `wa_ev_population` | Core | P3 validation | none | none | ✅ | 200 | ✅ | 294,193 | ✅ | none | — | ✅ | current | ✅ |
| `census_cenpop_blockgroup` | Core | P2 access geography | none | none | ✅ | 200 | ✅ | 239,780 | — | tract centroids | — | n/a | 2020 | ✅ |
| `eia_prices_api` | **Optional** | **none in Core** | key | req | ✅ | 200 | ✅ | 3 records | ✅ | bulk | — | n/a | monthly | ✅ |
| `cejst_archive` | Core | P6 archived overlay | none | none | ❌ | — | — | — | — | none | — | — | v2.0 | ✅ |
| `hifld_transmission_service` | Core | P6 contextual layer | none | none | ❌ | — | — | — | — | seed GeoJSON | — | **unresolved** | current | ✅ |

Machine-readable: `docs/evidence/live_integration_status.json`.

---

## D. Live endpoint evidence

All checks 2026-08-26. Endpoints shown without credentials.

### AFDC / NLR — `developer.nlr.gov` (12 tests)

The retired `developer.nrel.gov` appears nowhere; a test asserts no spec targets it.

| Check | Result |
|---|---|
| Valid key | HTTP 200, `application/json`, `total_results` present |
| **Rate limit** | `x-ratelimit-limit: 1000` — **100× the DEMO_KEY allowance of 10** measured in Phase 0 |
| Missing key | HTTP 403, `API_KEY_MISSING` |
| Invalid key | HTTP 403, `API_KEY_INVALID` — **distinct from missing** |
| Invalid key echoed in body | No |
| Unit object keys | Exactly `charging_level`, `connectors`, `funding_sources`, `network`, `port_count` — unchanged since Phase 1 |
| **Unit identifier** | **Still absent.** The synthetic per-snapshot key decision stands |
| `status_code` vocabulary | ⊆ {E, T, P} (G2 holds) |
| `access_code` vocabulary | ⊆ {public, private} (G3 holds) |
| `charging_level` values | ⊆ {1, 2, dc_fast, legacy} |
| Pagination | `limit=all` returns all 380; `offset` pages do not overlap; no duplicates; `total_results` consistent |

429 handling was **not** provoked against the personal key — Phase 0 already established
that path by exhausting DEMO_KEY. It is covered by a mocked response instead.

### Census ACS (6 tests)

| Check | Result |
|---|---|
| **Keyless** | **HTTP 200 with `text/html` and a "Missing Key" page** |
| Authenticated | HTTP 200, `application/json`, correct geography echoed |
| Invalid key | Non-JSON response |
| **API vs bulk** | **Exact match** — tract 53033007202, B25003, ACS 2023 5-year: 2152 / 286 / 1866 both routes |
| Phase 3 tables in 2023 | All 8 present (B19013, B25003, B25024, B25044, B08303, B08301, B15003, B01003) |
| Phase 5 historical vintages | All 8 present in 2019, 2020, 2021 and 2022 |

The last row matters for **D1**: a 2020 rolling origin can use the contemporaneous 2020
5-year release, verified now rather than discovered missing during Phase 5.

### HUD USER USPS ZIP Code Crosswalk (13 tests)

| Check | Result |
|---|---|
| Bearer authentication | HTTP 200 |
| Missing token | HTTP 401, `{"error": "Unauthenticated"}` |
| Invalid token | HTTP 401, **identical body** — not distinguishable from missing |
| Invalid token echoed | No |
| Vintage | year 2026, quarter 2, `crosswalk_type: zip-tract` |
| Fields | `zip`, `geoid`, `city`, `state`, `res_ratio`, `bus_ratio`, `oth_ratio`, `tot_ratio` |
| `geoid` format | 11-digit tract FIPS — joins to Census geography directly |
| Ratios in [0,1] | Yes, all four |
| `res_ratio` sums to 1.0 | Yes for 98101, 10001, 00601, 20001 — **exactly**, residual 0.00e+00 |
| **ZIP 99546** | `res_ratio` sums to **0.0** — no residential addresses. `tot_ratio` > 0 |
| **ZIP 98504** | **HTTP 404** — PO-Box-only ZIP with no areal equivalent |
| Rate limit | `x-ratelimit-limit: 60` per minute |

Neither edge case is renormalised. Rescaling 99546 to 1.0 would invent residents;
silently skipping 98504 would hide an unallocatable ZIP.

### EIA Open Data v2 (6 tests)

| Check | Result |
|---|---|
| Valid key | HTTP 200 |
| Missing key | HTTP 403, `API_KEY_MISSING` |
| Invalid key | HTTP 403, `API_KEY_INVALID` |
| Series semantics | `cents per kilowatt-hour`, monthly, `stateid: WA`, **`sectorid: COM`** |
| Pagination | `offset`/`length`; no overlap; `total` consistent |
| Core consumer | **None.** A test asserts `tier == optional` and `used_by ⊆ {economics}` |

Commercial sector deliberately, not residential: public charging is a commercial load,
and residential prices would be a category error for charger economics.

---

## E. Reconciliation results

| Comparison | Result |
|---|---|
| **AFDC JSON vs CSV vs envelope** (Rhode Island) | JSON units **1,045** = CSV rows **1,045** = `station_counts.ELEC.total` **1,045**. Three independent routes agree |
| **AFDC connector taxonomy** | JSON exposes 6 standards in use in RI including NEMA1450 and NEMA520; the CSV has **no NEMA columns at all**. The documented limitation holds |
| **Census API vs bulk** | Exact match. Naming differs (`B25003_001E` vs `B25003_E001`) — a cross-route join on variable name fails silently unless translated |
| **HUD vs land area** | See §E.1 |
| **Live vs replay** | Semantic parse equality for AFDC JSON, AFDC CSV, Census, HUD and EIA |

### E.1 Washington paired allocation validation

The decision rule was **written and committed at `66f1bfb` before any result was
computed**, so the threshold for "materially outperforms" could not be chosen after
seeing which method won.

431 ZIPs, 292,581 EVs.

| Metric | HUD `res_ratio` | land area |
|---|---:|---:|
| **EV-weighted mean TVD** | **0.1794** | 0.2579 |
| Unweighted mean TVD | 0.1439 | 0.2767 |
| EV-weighted mean MAE | 0.0337 | 0.0531 |
| **Top-tract accuracy** | **59.6%** | 47.1% |
| Max conservation error | 0.00e+00 | 1.11e-16 |

Stratified by observed tracts per ZIP:

| Tracts/ZIP | ZIPs | EVs | TVD HUD | TVD land area |
|---:|---:|---:|---:|---:|
| 1 | 57 | 2,601 | 0.0046 | 0.0212 |
| 2–3 | 100 | 12,654 | 0.1076 | 0.2351 |
| 4–7 | 111 | 51,773 | 0.1715 | 0.2576 |
| 8+ | 163 | 225,553 | 0.1872 | 0.2619 |

**Both pre-registered conditions are met:** `D = +0.0785` (threshold 0.05) and HUD has
lower TVD on **64.5%** of ZIPs (threshold 60%). Neither method exceeds the 0.35
acceptability floor, so **no plan change is triggered**.

**Decision: HUD `res_ratio` becomes the preferred Phase 3 ZIP→tract allocation method.
Land-area allocation is retained as a documented degraded fallback**, with method
provenance on every allocated row.

**Caveat that must travel with this result.** Even the winning method misallocates
**17.94%** of EV mass in a single state. This selects between two candidates; it does not
establish that ZIP-anchored tract estimates may be called observed. They remain
`zip_anchored` / `crosswalked`, exactly as amendment A2 requires.

Washington is **not national ground truth** — it is direct paired evidence from one state.

---

## F. Failure-mode results

20 mocked tests. Production services were not deliberately driven into error states:
provoking 429 on a shared credential is destructive, and Phase 0 already established the
real 429 path.

| Mode | Adapter behaviour |
|---|---|
| 403, 404, 500, 503 | `unavailable`; **no measurement attached** |
| 401 | `gated`, naming the required variable |
| 429 | `gated`, recording `x-ratelimit-limit` and `retry-after` |
| **HTTP 200 + HTML credential page** | **`gated`** — the Census trap is caught |
| Timeout | Exactly 3 bounded attempts, then `unavailable` |
| DNS failure | `unavailable`, reported not swallowed |
| Retry backoff | 0.5 s then 1.0 s — widens, and terminates |
| Malformed JSON | `degraded`, never parsed into an empty dataset |
| Unexpected content type | `degraded` |
| Empty successful response | `degraded`, not `confirmed` |
| Missing required field | Absent, never silently defaulted |
| Partial download | Flagged as a bounded sample |

Secret hygiene under failure: no secret reaches the cache at any status, an exception
message, or an observation note; cache keys stay stable when only the credential changes.

---

## G. Secret-leakage result

## **secret leakage scan: PASS**

Scans `SOURCES.yml`, `SOURCES.observed.json`, `docs/`, `tests/fixtures/`, `data/cache/`,
`pipeline/`, `Makefile` and `.env.example`, plus every cached `.body` payload, for the
four configured values held in memory. The test reports offending **paths** only and
never the value or the matching content.

Redaction was **hardened before any credential touched the network**:

- `REDACTED_PARAMS` widened to `api_key`, `key`, `token`, `apikey`, `access_token`,
  `auth`, `secret`, matched case-insensitively;
- new `REDACTED_HEADERS` covering `authorization`, `x-api-key`, `api-key`, `token`,
  `x-auth-token`, `cookie`, `proxy-authorization`;
- request headers are redacted **before** the cache metadata write. The HUD cache
  records `"Authorization": "<redacted>"`.

---

## H. Contract corrections

| File | Change |
|---|---|
| `SOURCES.yml` | **Census claim corrected.** "The API requires a key" replaced with the tested behaviour: a keyless request returns **HTTP 200 with an HTML error page**, so an adapter checking only the status code would treat it as success. Records that API and bulk agree exactly, and that variable naming differs between routes |
| `SOURCES.yml` | **`hud_usps_zip_tract` added** (Core) with live-verified endpoint, Bearer auth, 2026 Q2 vintage, field list, the 60/min rate limit, and all three edge cases: identical 401s, zero-residential ZIPs, 404 ZIPs |
| `SOURCES.yml` | **`census_zcta_tract_landarea` added** and **demoted to fallback**, citing the Washington evidence |
| `SOURCES.yml` | `afdc_charging_units` and `census_zcta_tract_landarea` quality blocks now state `probe_scope`, so a bounded probe cannot report false drift against a national expectation |
| `pipeline/discovery/registry.py` | Probe specs for both new sources; `needs_bearer` support added |
| `pipeline/discovery/cache.py` | Header redaction (see §G) |
| `pipeline/discovery/probe.py` | Failed and gated responses are no longer measured; 401 classified as `gated` |
| `pipeline/config/settings.py` | `.env` loading that never mutates `os.environ`; `HUD_USER_TOKEN`; `presence()` and `secret_values()` |
| `pipeline/model/access.py` | **"Lower bound" overclaim corrected** — the aggregate is an approximation, because each block group is one population-weighted point |
| `pyproject.toml` | `addopts = -m "not live"` so the deterministic gate never opens a socket |
| `Makefile` | `live-smoke`, `live-integration`, `integration-assurance` |
| `docs/reports/PHASE_2_REPORT.md` | Dated correction: mixed public/private sites; the lower-bound wording; A-2.2 retargeted |
| `docs/reports/ASSUMPTION_LEDGER.md` | A-2.2 moved to a **Phase 4 prerequisite**; A-2.3 and A-2.4 reworded |
| `docs/reports/IMPACT_LOG.md` | I-5 and I-6 (§I) |
| `SETUP.md`, `.env.example` | Notes appended for the retired NREL host and `HUD_USER_TOKEN` |

`CLAUDE.md` required no amendment: nothing here contradicts the specification.

---

## I. Remaining open risks

| ID | Risk | Severity | Affected phase | Blocks Phase 3? |
|---|---|---|---|---|
| **I-5** | The probe attached a measurement to failed responses, so a 4xx produced `row_count: 0` — readable as "this source is empty" rather than "this request failed" | **S2** | 0, 1, 2 | **No** — fixed, gates re-run |
| **I-6** | Request headers were persisted to cache metadata unredacted; a Bearer token would have been written in plain text | **S2** | 1, 2 | **No** — fixed before any live credential use |
| R-1 | `cejst_archive` not live-tested. Its host has no DNS record and the Internet Archive is the only route; a third-party archive is a single point of failure | S3 | 6 | No |
| R-2 | `hifld_transmission_service` not live-tested, and the live service reports 52,244 features against 94,216 in the delivered seed GeoJSON — **still unresolved** | S3 | 6 | No |
| R-3 | HUD and land-area allocation disagree materially, and even HUD misallocates 17.94% of EV mass in Washington. Allocation error must feed the uncertainty score | S2 | 3 | No — Phase 3 owns it |
| R-4 | A-0.5 contemporaneity remains unresolved for the 2020 and 2021 rolling origins | S2 | 5 | No |
| R-5 | HUD's 60/min rate limit makes a national ZIP sweep slow (~34,000 ZIPs ≈ 9.5 hours serially). Phase 3 needs a cached bulk strategy | S3 | 3 | No — plan for it |
| R-6 | Missing and invalid HUD tokens are indistinguishable (both 401), so a misconfigured deployment cannot be told from an expired token | S3 | 3 | No |

**No S1 unresolved integration defect exists.**

---

## J. Checkpoint PASS criteria

| # | Criterion | Result |
|---|---|---|
| 1 | Four credentials detected without displaying values | ✅ |
| 2 | NLR valid authentication passes | ✅ |
| 3 | Census authenticated path passes | ✅ |
| 4 | Census keyless behaviour empirically classified | ✅ HTTP 200 + HTML |
| 5 | HUD authentication passes | ✅ |
| 6 | HUD ZIP→tract semantics verified | ✅ incl. 3 edge cases |
| 7 | EIA authentication passes | ✅ |
| 8 | AFDC JSON primary live-tested | ✅ |
| 9 | AFDC CSV fallback live-tested | ✅ |
| 10 | AFDC JSON/CSV reconciliation | ✅ 1,045 = 1,045 |
| 11 | Census API/bulk reconciliation | ✅ exact |
| 12 | No Core source relied upon has an untested production path | ✅ the two untested are Phase 6 only |
| 13 | Fallbacks tested where reachable | ✅ |
| 14 | Live→replay equivalence for NLR, Census, HUD, EIA | ✅ |
| 15 | Secret-leakage scan | ✅ PASS |
| 16 | Error handling tests | ✅ 20 tests |
| 17 | Schema-drift checks | ✅ |
| 18 | No S1 unresolved integration defect | ✅ |

**18/18. Live-network tests are not part of any deterministic `make gate` invocation.**
