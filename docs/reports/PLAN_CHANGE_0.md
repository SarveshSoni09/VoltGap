# Plan change request 0 — domain rule G9 is factually wrong against the delivered data

| Field | Value |
|---|---|
| Raised in | Phase 0 (source contract) |
| Date | 2026-08-19 |
| Status | **OPEN — awaiting project owner decision** |
| Blocks | Phase 1 acceptance criterion "All G1–G14 regression tests pass" |
| Does not block | Phase 0 delivery. Everything else in Phase 0 is complete. |

---

## 1. What the specification says

`CLAUDE.md` section 5 defines fourteen domain rules for the source data, and section 14
requires **one regression test per domain rule G1–G14** in `tests/regression/`. Rule G9
reads, verbatim:

> | G9 | State registration counts have inconsistent reporting vintages across states.
> Oregon reports 6,436, below Kansas at 11,271 and Iowa at 9,031, which is implausible.
> Flag outliers by comparing per-capita rates against neighboring states and mark
> low-confidence states in the data. |

`data/seed/MANIFEST.md` repeats the same claim in its closing section:

> Oregon reports 6,436, which falls below Kansas (11,271), Iowa (9,031), and Maine
> (7,377). That ordering is implausible and indicates inconsistent reporting vintages
> across states. Phase 0 should attempt to establish the vintage of each state's
> figure. Flag low-confidence states in the data rather than silently using the numbers.

## 2. What the delivered data actually contains

The file is `data/seed/EV_Registration_Counts_by_State.csv`, SHA-256
`4c72eeace1defeddf7dddeaedf4f65ffff970b4c2ce8090184fd6408076bb7ad`, 826 bytes, 52 data
rows (51 jurisdictions plus a `Total` row), two columns `State,Registration Count`.

The values named in G9 are:

| State | G9 / MANIFEST.md claims | Delivered file contains |
|---|---:|---:|
| Oregon | 6,436 | **64,361** |
| Kansas | 11,271 | 11,271 |
| Iowa | 9,031 | 9,031 |
| Maine | 7,377 | 7,377 |

Oregon is **64,361**, not 6,436. Kansas, Iowa and Maine match. The stated Oregon figure
appears to be a truncation of the real one (64,361 → 6,436, dropping the final digit).

At 64,361, Oregon sits above Kansas, Iowa and Maine, and the ordering G9 calls
implausible does not exist in the delivered file.

## 3. The general claim also fails

G9's specific example being wrong would not by itself invalidate the rule. Its general
claim — "inconsistent reporting vintages across states" — was therefore tested directly.

`AFDC` publishes ten annual vintages of state EV registration counts at
`https://afdc.energy.gov/vehicle-registration?year={year}`, rounded to the nearest 100.
Rounding every value in the delivered file half-up to the nearest 100 and comparing
against each vintage gives:

| AFDC vintage | Jurisdictions matching the delivered file |
|---|---|
| 2022 | 0 / 51 |
| **2023** | **51 / 51** |
| 2024 | 0 / 51 |

Worked examples:

```
Oregon      64,361 -> 64,400   AFDC 2023 Oregon      = 64,400
Kansas      11,271 -> 11,300   AFDC 2023 Kansas      = 11,300
Iowa         9,031 ->  9,000   AFDC 2023 Iowa        =  9,000
Maine        7,377 ->  7,400   AFDC 2023 Maine       =  7,400
California 1,256,646 -> 1,256,600  AFDC 2023 California = 1,256,600
Washington   152,101 ->   152,100  AFDC 2023 Washington =   152,100
```

The delivered `Total` row is 3,555,445, which equals the sum of the 51 jurisdiction rows
exactly.

**Conclusion.** The file is a single, internally consistent AFDC 2023 vintage across all
51 jurisdictions, published from one Experian-derived extract. It is not a mixture of
per-state vintages. The premise of G9 does not hold for this file.

Evidence artifact: `docs/evidence/F-9_g9_oregon_discrepancy.txt`, SHA-256 recorded in
`SOURCES.yml` under finding `F-9`.

## 4. Why this is escalated rather than worked around

Per the working agreement, a specification that is wrong is not silently revised or
patched around. Concretely, three things break if it is ignored:

1. A Phase 1 regression test asserting G9 as written (`Oregon == 6436`) **will fail**
   against the delivered data. A test asserting the general claim (mixed vintages) will
   also fail.
2. Writing a test that passes by asserting something G9 does not say would make the
   G1–G14 suite dishonest — the suite is meant to lock the domain rules, not to be
   reshaped until it goes green.
3. The downstream instruction ("mark low-confidence states in the data") would attach a
   low-confidence flag to states on the basis of an anomaly that is not present,
   propagating a fabricated quality signal into the uncertainty model in section 7.4.

Note also that the rule's *remedy* is still a reasonable practice in general. Per-capita
outlier screening against neighbouring states is a sound quality check to run on any
registration file, including a single-vintage one — it is the stated *evidence* and the
stated *cause* that are wrong here.

## 5. Options

### Option A — Restate G9 around what is actually true, keep the outlier screen

Rewrite G9 as: *"State registration counts are published as a single AFDC annual vintage
covering all 51 jurisdictions, rounded to the nearest 100, and derived from Experian VIN
data. The delivered seed file is the 2023 vintage. Vintage consistency must be verified,
not assumed, whenever a registration file is ingested, and per-capita rates must still be
screened against neighbouring states for outliers, with any state failing the screen
marked low-confidence."*

The Phase 1 regression test then asserts what is verifiable: that all 51 jurisdictions in
a registration file resolve to one vintage, and that the per-capita outlier screen runs
and produces a confidence flag per state.

- **Pros.** Keeps a real, useful invariant. The test is honest and will pass. Preserves
  the intent of the rule (do not trust registration counts blindly). Costs nothing
  downstream: the low-confidence mechanism in section 7.4 still exists, it simply is not
  pre-populated with a false positive.
- **Cons.** Changes the text of a numbered domain rule, so `docs/DATA_GOTCHAS.md` and any
  future reference to "G9" must carry the corrected wording. Anyone reading the original
  `CLAUDE.md` will see a mismatch unless the correction is recorded prominently.
- **Reversible?** Yes.

### Option B — Retire G9 as a data rule and demote it to a quality procedure

Mark G9 **withdrawn, evidence not reproducible**, leaving G1–G8 and G10–G14 as the
regression suite (thirteen rules), and move the per-capita outlier screen into
`docs/METHODOLOGY.md` as a standard ingestion quality check with no regression test bound
to a specific state's value.

- **Pros.** Most honest about what happened: the rule was written from a mistaken reading
  and no replacement invariant is being invented to fill the slot. Avoids the awkwardness
  of a "G9" whose content bears no relation to the original. Leaves the numbering of the
  other thirteen rules untouched.
- **Cons.** Loses a regression test slot, so the vintage-consistency property in Option A
  would go unenforced unless added separately. The G1–G14 count in `CLAUDE.md` sections 5
  and 14 and in the Phase 1 acceptance criteria becomes G1–G14-minus-G9, which needs
  stating everywhere those are quoted.
- **Reversible?** Yes.

### Option C — Keep G9 exactly as written and source a file that exhibits it

Treat G9 as describing some *other* registration file, not the delivered one, and go find
a registration extract that genuinely mixes vintages across states to serve as the G9
fixture.

- **Pros.** Requires no specification edit at all.
- **Cons.** No such file is known to exist, and Phase 0 found the opposite: AFDC publishes
  one consistent vintage per year, and the 14 Atlas EV Hub state files each carry their
  own explicit `DMV Snapshot (Date)`, so mixed vintages there are labelled rather than
  hidden. This option risks an open-ended search for a file that may not exist, and
  blocks the Phase 1 gate while it runs. Recorded for completeness; not recommended.
- **Reversible?** Yes, but at the cost of Phase 1 schedule.

## 6. Recommendation

**Option A.** It keeps a genuine, testable invariant (single-vintage verification plus a
per-capita outlier screen), preserves the rule's original intent, and is the smallest
change that makes the G1–G14 suite honest. Option B is a reasonable second choice if you
would rather not restate a numbered rule at all.

## 7. What is needed from the project owner

A decision between A, B and C before Phase 1 writes the G1–G14 regression suite. Phase 0
is complete and stops here regardless; this document does not block the Phase 0 gate.

No workaround has been implemented. `SOURCES.yml` records the true delivered values under
`seed_state_ev_registrations.known_limitations` and points at this document.
