# Live Integration Assurance Checkpoint — SUPERSEDED, checkpoint complete

> **This file is superseded.** It recorded a mid-checkpoint pause. The checkpoint is now
> complete: see `docs/reports/LIVE_INTEGRATION_AUDIT.md` for the finished report. The
> content below is preserved as the record of where work stopped, so the resume path
> stays auditable. Every item listed as remaining was completed.

Verified state at pause: ~~585 deterministic tests pass, 46 live tests pass~~ **563 deterministic tests pass; 47 tests carry the `live` marker, 46 of them in `tests/live/`** (corrected 2026-08-28 — see `LIVE_INTEGRATION_AUDIT.md` §K.1),
100% line and branch coverage (2,325 statements, 548 branches, zero missed),
ruff and mypy strict clean, copy lint clean (104 files), **Phase 2 gate PASS**.

## Done

| Item | State |
|---|---|
| Secret hygiene verified first | `.env` git-ignored and untracked; `.env.example` has 7 assignments, **0** with values |
| Redaction hardened | `REDACTED_PARAMS` widened; new `REDACTED_HEADERS` covers `Authorization`, `x-api-key`, `cookie`. Request headers are redacted **before** the cache write. Cache keys are stable across different credential values |
| `.env` loading + `HUD_USER_TOKEN` | `load_dotenv()` never mutates `os.environ`; `presence()` reports booleans; `secret_values()` is in-memory only, for the leak scan |
| Live tests separated from the gate | `addopts = -m "not live"` in `pyproject.toml`, so a plain `pytest` (what `make gate` runs) never touches the network. 46 tests live in `tests/live/`; **47** carry the `live` marker, the extra one being `tests/integration/test_determinism.py::test_live_refresh_is_not_expected_to_be_byte_identical` (corrected 2026-08-28) |
| Makefile targets | `live-smoke`, `live-integration`, `integration-assurance` |
| **AFDC** live (12 tests) | Valid key OK; **rate limit 1,000/hr vs DEMO_KEY's 10**; missing→403 `API_KEY_MISSING`; invalid→403 `API_KEY_INVALID`; pagination has no overlap/drop; JSON schema unchanged; **no unit identifier has appeared upstream** |
| **Census** live (6 tests) | Keyless returns **HTTP 200 with an HTML "Missing Key" page**, not a 4xx; authenticated returns JSON; **API and bulk agree exactly** for tract 53033007202 / B25003 / ACS 2023; all 8 planned Phase 3 tables exist in vintages 2019–2023 |
| **HUD** live (13 tests) | Bearer auth OK; missing and invalid both 401 (indistinguishable); vintage 2026 Q2; `geoid` is 11-digit tract FIPS; `res_ratio` sums to exactly 1.0; **99546 sums to 0.0** (no residential addresses); **98504 returns 404** (PO-Box-only); rate limit **60/min** |
| **EIA** live (6 tests) | Auth OK; missing/invalid distinguished; commercial-sector price in cents/kWh; pagination clean; **test asserts EIA acquires no Core consumer** |
| Reconciliations | AFDC JSON units = CSV rows = envelope = **1,045** (RI); Census API = bulk exactly |
| Live→replay equivalence | Passes for AFDC, Census, HUD, EIA and a CSV source |
| Secret-leakage audit | **PASS.** Scans tracked files, caches, evidence, reports and `.body` payloads. HUD cache records `Authorization: <redacted>` |
| Failure modes (20 mocked tests) | 401/403/404/429/500/503, timeout, DNS failure, malformed JSON, wrong content type, empty success, missing field, partial download. Bounded retries with widening backoff; no secret in cache, exception text or observation notes |
| **Washington paired validation** | Decision rule **pre-registered and committed at `66f1bfb` before any result was computed.** 431 ZIPs, 292,581 EVs |
| Phase 2 mixed-site correction | Implemented, tested (P2-I, 5 checks), national figures recomputed, dated correction appended to the Phase 2 report, Phase 2 gate re-run and passing |
| Contract corrections | Census claim replaced with exact observed behaviour; `hud_usps_zip_tract` and `census_zcta_tract_landarea` added with live-verified schemas; both given probe specs (bearer support added) |
| "Lower bound" overclaim corrected | Now stated as an approximation, since each block group is one population-weighted point |
| A-2.2 retargeted | Moved from Phase 3 to a **Phase 4 prerequisite**; it is a supply-method question |

## The Washington result

Against the pre-registered rule, **HUD materially outperforms** on both conditions:

| Metric | HUD `res_ratio` | land area |
|---|---:|---:|
| EV-weighted mean TVD | **0.1794** | 0.2579 |
| Unweighted mean TVD | **0.1439** | 0.2767 |
| Top-tract accuracy | **59.6%** | 47.1% |

`D = +0.0785` (threshold 0.05) and HUD wins **64.5%** of ZIPs (threshold 60%). Neither
exceeds the 0.35 **maximum acceptable TVD** (an acceptability *ceiling*; the earlier
wording "floor" inverted the sense — corrected 2026-08-28), so **no plan change is
triggered**. HUD becomes the
preferred Phase 3 ZIP→tract method; land-area is retained as documented degraded fallback.

## Phase 2 correction, before/after

| Figure | Before | After | Delta |
|---|---:|---:|---:|
| Generic capacity | 19,679,636 kW | **19,001,862 kW** | −677,774 (−3.44%) |
| DCFC sites | 13,143 | **13,079** | −64 |
| DCFC gap population | 32,113,986 | **32,169,758** | +55,772 |
| L2 sites | 42,928 | **42,861** | −67 |
| L2 gap population | 53,462,245 | **53,584,530** | +122,285 |

## Defects this checkpoint found in existing code

1. **The probe measured failed responses.** A 4xx produced a measurement with
   `row_count: 0`, which a reader could take as "this source is empty" rather than "this
   request failed". Fixed: non-OK and gated responses are no longer measured.
2. **Request headers were persisted unredacted.** A Bearer token would have been written
   to cache metadata in plain text. Fixed before any credential touched the network.

## Remaining work

1. **Write `docs/reports/LIVE_INTEGRATION_AUDIT.md`** — the required report: executive
   result, credential matrix (presence/auth only), Core source integration matrix, live
   endpoint evidence, reconciliation results, failure-mode results, secret-leakage
   result, contract corrections, open risks.
2. Write `docs/evidence/live_integration_status.json` (machine-readable, no secrets).
3. Save the Washington comparison as a hashed evidence artifact (numbers are in
   `/tmp/wa_alloc.json`; the inputs are cached under `data/cache/raw/`).
4. Update `SETUP.md` / `.env.example` notes for the retired NREL host and `HUD_USER_TOKEN`.
5. Update `IMPACT_LOG.md` with the two defects above.
6. Re-run the Phase 0 and Phase 1 gates (Phase 2 already re-run and passing).

**All six remaining items were completed.** `LIVE_INTEGRATION_AUDIT.md` and
`live_integration_status.json` are written, the Washington evidence artifact is hashed,
`SETUP.md` and `.env.example` carry dated corrections, `IMPACT_LOG.md` records I-5 and
I-6, and the Phase 0, 1 and 2 gates were all re-run and pass.

**Phase 3 has not started and must not start until the audit report is reviewed.**

---

## Correction — 2026-08-28

This file is superseded and is preserved as the record of a mid-checkpoint pause, so its
body is left as written apart from the three inline corrections marked above. The full
corrections — test counts, the acceptability-ceiling wording, the Washington record
accounting, and Washington's status as method-selection rather than independent
validation data — are in `docs/reports/LIVE_INTEGRATION_AUDIT.md` §K.

The Washington comparison itself is now reproducible code rather than a one-off script:
`pipeline/validation/allocation_error.py` and `pipeline/validation/washington.py`, with
the balanced record ledger in `docs/evidence/P3-1_wa_allocation_scope_and_error.json`.
