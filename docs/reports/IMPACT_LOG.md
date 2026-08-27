# Impact log

Records every instance where a later phase invalidates an earlier one, per the
cross-phase impact protocol in CLAUDE.md §15.3.

Severity: **S1 Blocking** (an earlier phase's published output is wrong and downstream
results are invalid), **S2 Degrading** (usable but weaker than claimed), **S3 Cosmetic**
(documentation, naming or presentation only).

---

## Open entries

None.

### I-5 — the probe attached a measurement to failed responses

| Field | Value |
|---|---|
| Opened | 2026-08-26, Live Integration Assurance Checkpoint |
| Affected phase | 0, 1, 2 (`pipeline/discovery/probe.py`) |
| Severity | **S2 Degrading** — a failure was reportable as an empty dataset |
| Status | **RESOLVED 2026-08-26** |

**Assumed.** That measuring a response was harmless regardless of its status.

**Actually true.** A 4xx or 5xx body was measured like any other payload, producing a
measurement with `row_count: 0`. A downstream reader could take that as "this source has
no rows" rather than "this request failed" — precisely the silent-empty-dataset outcome
directive D8 forbids. Found by a mocked failure-mode test, not by live traffic.

**Response.** Non-OK and credential-gated responses are no longer measured; the
observation carries `measurement: None` and a status of `unavailable` or `gated`. All
prior gates re-run and passing. No published number changes: every real probe run to date
returned 200 for the sources whose measurements were used.

### I-6 — request headers were persisted to the cache unredacted

| Field | Value |
|---|---|
| Opened | 2026-08-26, before any live credential was used |
| Affected phase | 1, 2 (`pipeline/discovery/cache.py`) |
| Severity | **S2 Degrading** — a credential could have been written to disk |
| Status | **RESOLVED 2026-08-26** |

**Assumed.** That redacting query parameters was sufficient, because every credential up
to this point was a query parameter.

**Actually true.** `_record` wrote `request_headers` verbatim into cache metadata. HUD
authenticates with `Authorization: Bearer <jwt>`, so the first HUD fetch would have
written a live token to disk in plain text — and `tests/fixtures/replay/` is tracked by
git.

**Caught before any exposure.** The hole was found and closed during the mandatory
secret-hygiene step, before the first authenticated request. No credential was ever
written: the HUD cache records `"Authorization": "<redacted>"`.

**Response.** `REDACTED_HEADERS` added covering `authorization`, `x-api-key`, `api-key`,
`token`, `x-auth-token`, `cookie` and `proxy-authorization`; `REDACTED_PARAMS` widened
and matched case-insensitively; redaction applied before the metadata write. Cache keys
hash the *redacted* form, so a fixture recorded under one credential replays under
another. A leakage scan over tracked files, caches, evidence, reports and `.body`
payloads passes.

### I-2 — the Phase 1 report described a rounded 99.975% as "100.0%"

| Field | Value |
|---|---|
| Opened | 2026-08-24, project owner review of the Phase 1 report |
| Affected phase | 1 (`docs/reports/PHASE_1_REPORT.md` §9.1) |
| Severity | **S3 Cosmetic** — presentation only; no measurement was wrong |
| Status | **RESOLVED 2026-08-24** |

**Assumed.** That `89,665 / 89,687` stations reconciling could be written as 100.0%.

**Actually true.** The ratio is 99.9755%. The 22 exceptions are real and were unexamined.

**Response.** Phase 2 preflight (CLAUDE.md 15.5.1) classified all 22 with zero
unresolved: 12 planned stations with no unit records, 8 containing `legacy`-level units
the L1/L2/DCFC aggregate does not count, and 2 holding only legacy units. Under the
documented scope "at least one unit record and no legacy-level unit", reconciliation is
89,736 / 89,736 = exactly 100.0000%. A dated correction was appended to the Phase 1
report and a test now asserts the unscoped rate is never called 100%.

### I-3 — `port_count == 1` was published as a guaranteed invariant

| Field | Value |
|---|---|
| Opened | 2026-08-24, project owner review of the Phase 1 report |
| Affected phase | 1 (`pipeline/schemas/canonical.py`, report §7.1) |
| Severity | **S2 Degrading** — usable but claimed more than the source supports |
| Status | **RESOLVED 2026-08-24** |

**Assumed.** That every AFDC charging unit has exactly one port, permanently.

**Actually true.** It holds for all 292,756 units in the 2026-08 snapshot, but it is a
current-source property. Charging unit and port remain conceptually distinct entities,
and a future record with several ports would be legitimate data. A schema pinned at
`== 1` would have rejected it as corruption.

**Response.** Amendment A19. The schema now requires `port_count >= 1`;
`check_port_count_drift` monitors the `== 1` observation and reports a higher value as
source drift requiring review, never raising. Gate check P2-D covers both directions,
including that the schema accepts a 4-port record.

### I-4 — the gate's coverage thresholds could not fail

| Field | Value |
|---|---|
| Opened | 2026-08-24, during the Phase 2 gate run |
| Affected phase | 1 (`Makefile`, `gate-1` and `coverage`) |
| Severity | **S2 Degrading** — the gate reported a threshold it was not enforcing |
| Status | **RESOLVED 2026-08-24** |

**Assumed.** That `coverage report --fail-under=N | tail -2` fails when coverage is
below N.

**Actually true.** A shell pipeline returns the last command's exit status, so `tail`
masked every coverage failure. The threshold could never fail the gate. It was caught
because `pipeline/discovery/` reported 99% while the Phase 2 gate still passed.

**What this did NOT invalidate.** The Phase 1 coverage figures were correct as measured
and reported — 100% line and branch at that time. The defect meant a *future* regression
would have gone unnoticed, not that the reported numbers were wrong.

**Response.** Each check now captures output to a file and tests the exit status
explicitly. The two statements the defect had hidden (the new nested-JSON probe branch)
are now covered, and both the Phase 1 and Phase 2 gates were re-run and pass.

## Resolved entries

### I-1 — `afdc_charging_units` was published with `stable_keys: true` and a station-level join key

| Field | Value |
|---|---|
| Opened | 2026-08-19, during Phase 1 planning review |
| Discovered by | Project owner review of the Phase 1 plan |
| Affected phase | 0 (`SOURCES.yml`, `docs/reports/PHASE_0_REPORT.md`) |
| Severity | **S2 Degrading** — the contract entry is usable but claims more than the source supports |
| Status | **RESOLVED 2026-08-19**, same day, within the correction window §15.3 allows for S2 |

**What was assumed.** The Phase 0 contract recorded, for `afdc_charging_units`:

```yaml
    schema:
      join_keys: [id]
      stable_keys: true
```

`stable_keys: true` is defined in the contract as meaning the join keys are stable across
refreshes. Read together with a one-row-per-charging-unit source, it implies row-level
identity that can be followed over time.

**What is actually true.** Measured over the full national export, 292,435 rows:

| Measurement | Value |
|---|---|
| Rows | 292,435 |
| Distinct station `ID` values | 89,687 |
| Columns resembling a unit identifier | **none** — `ID` is the station, `Federal Agency ID` and `NPS Unit Name` are unrelated |
| Distinct full-row values | 99,639 |
| Rows participating in an identical-row group | 265,836 (**90.9%**) |
| Redundant rows (n−1 per identical group) | 192,796 (**65.9%**) |
| Largest identical-row group | 410 rows (station 225833, Viejas Casino and Resort) |
| Stations where row count == reported L1+L2+DCFC | **89,665 / 89,687 (100.0%)** |

`ID` is the **station parent key**, not row identity. There is no charging-unit identifier
column of any kind. Two-thirds of rows are byte-identical to another row, so rows are not
distinguishable from one another by their content, and row *order* is the only thing
separating them — which no refresh guarantees.

**These duplicates are not data errors.** The last row of the table above is the key finding:
row count reconciles exactly to the station's reported EVSE totals for 100.0% of stations. The
export emits one row per EVSE, and identical units produce identical rows. This is the same
logic as domain rule G4 for coordinate duplicates — real distinct physical objects that are
indistinguishable in every reported attribute.

**What is invalidated, and what is not.**

- **Invalidated:** `stable_keys: true` for this source, and the implication that
  `charging_unit_id` could be a stable physical identifier. Corrected in `SOURCES.yml` to
  `stable_keys: false` with `parent_key` and `row_identity` stated separately.
- **NOT invalidated:** every quantitative Phase 0 finding. The rung-1 power coverage figures
  (82.76% all rows, 88.11% public+operational, port-weighted) aggregate counts across rows and
  never rely on row identity. The 100.0% reconciliation above independently corroborates that
  the port totals are trustworthy. Finding F-1 and its evidence artifact stand unchanged.

**Response taken.** Contract corrected; specification §6.1.1 extended from ports to
charging-unit and connector identity; the Phase 1 identifiability investigation widened to
three levels; a dated correction appended to `docs/reports/PHASE_0_REPORT.md`; Phase 0 gate
re-run and passing. No Phase 0 measurement required recomputation.

---

## Phase 0 note

Phase 0 is the first phase, so there is no earlier phase for it to invalidate and this
log is correctly empty.

Two findings from Phase 0 concern the *specification and the delivered documentation*
rather than a prior phase's output, so they do not belong here:

- Domain rule **G9** is factually wrong against the delivered data. Escalated through
  `docs/reports/PLAN_CHANGE_0.md`, awaiting a decision. Would become an impact-log
  entry only if a later phase had already published something depending on it.
- `SETUP.md` names a retired NREL host and describes the Census API key as optional.
  Recorded as corrections in `docs/SOURCE_VERIFICATION.md` §3.
