# Phase {N} Report — {Phase Name}

> **Instructions to the author (delete this block before submitting).**
> This report is reviewed by a person and by an external AI model that has **no access to
> this repository, the code, the data, or any prior conversation**. Everything needed to
> evaluate this phase must be inside this document.
>
> Rules:
> - Quote actual values, schemas, formulas, and code. Never write "see file X".
> - Include real numbers. Never write "tests pass" without naming them and their assertions.
> - Write every section. If one does not apply, write "Not applicable to this phase" and why.
> - Length is not a constraint. Completeness is.

---

## 0. Report metadata

| Field | Value |
|---|---|
| Phase | {N} — {name} |
| Date | {YYYY-MM-DD} |
| Gate status | PASS / FAIL |
| Commit | {sha} |
| Duration | {actual vs planned} |
| Prepared by | Claude Code |

---

## 1. Context for a reader with zero prior knowledge

### 1.1 What this project is
{2 to 3 paragraphs. What VoltGap does, who it is for, what it outputs. Written for someone
who has never heard of it.}

### 1.2 The architecture in one paragraph
{Offline Python pipeline produces static artifacts; browser-side static frontend consumes
them; zero recurring cost; hosted static. Enough that a reviewer understands why constraints
exist.}

### 1.3 What the previous phase produced
{Concrete summary. What tables, what artifacts, what numbers. If this is Phase 0, write
"This is the first phase" and describe the starting state.}

### 1.4 What this phase was supposed to do
{The phase objective and its declared acceptance criteria, quoted from the specification.}

---

## 2. What was built

### 2.1 Modules created or changed

| Path | Purpose | Lines | Key public functions |
|---|---|---|---|
| | | | |

### 2.2 Key implementations, quoted

{For each significant function or model, include the signature and enough of the body to
evaluate the logic. Do not summarize logic that a reviewer needs to check.}

```python
# path/to/module.py
{actual code}
```

### 2.3 Data artifacts produced

| Artifact | Grain | Rows | Size | Schema summary |
|---|---|---|---|---|
| | | | | |

### 2.4 Schemas, quoted in full

{Full pandera schema definitions or equivalent for every table this phase produces.}

---

## 3. Decisions made and why

| Decision | Options considered | Chosen | Rationale | Reversible? |
|---|---|---|---|---|
| | | | | |

{Include any decision the specification left open, for example the reconciliation estimator
choice, threshold values, clustering parameters. State the evidence used.}

---

## 4. Acceptance criteria verification (Gate part G-A)

Every criterion, its check, and its result. No criterion may be marked passed by inspection.

| # | Criterion (quoted from spec) | Verifying test (full name) | What the test asserts | Result | Evidence |
|---|---|---|---|---|---|
| 1 | | | | PASS/FAIL | {actual value or output} |

**Criteria passed: {n}/{n}.** If not 100%, the gate has failed and this report should say
FAIL in section 0.

---

## 5. Test and coverage evidence (Gate part G-B)

### 5.1 Suite summary

```
{actual pytest output summary: counts, duration, failures}
```

### 5.2 Coverage by module

| Module | Line % | Branch % | Required | Met? |
|---|---|---|---|---|
| pipeline/model/ | | | 100% | |
| pipeline/validation/ | | | 100% | |
| pipeline/spatial/ | | | 100% | |
| pipeline/transform/ | | | 85% | |
| pipeline/sources/ | | | 85% | |
| Repository total | | | 70% | |

### 5.3 Coverage exclusions

| Location | Reason for `pragma: no cover` | Justified? |
|---|---|---|
| | | |

{Unjustified exclusions fail the gate.}

### 5.4 Notable tests, with assertions quoted

{For the tests that matter most, quote them. A reviewer should be able to judge whether the
test actually verifies the claim.}

```python
{actual test code}
```

---

## 6. Regression against prior phases (Gate part G-C)

| Prior phase | Gate suite | Tests | Result |
|---|---|---|---|
| | | | |

{If any prior gate now fails, this phase has not passed. Record it in section 8 and stop.}

---

## 7. Forward viability (Gate part G-D)

### 7.1 Output contract table

| Artifact | Schema | Grain | Guaranteed invariants | Consumed by phase |
|---|---|---|---|---|
| | | | | |

### 7.2 Smoke-forward test

{Describe the minimal exercise of the next phase's core operation against this phase's real
output. Include the code and the actual result. State explicitly what it proves and what it
does not.}

```python
{actual smoke-forward test code}
```

**Result:** {actual output}

**What this proves:** {specific}
**What this does not prove:** {specific}

### 7.3 Assumption ledger additions

| ID | Assumption (falsifiable statement) | Depends on | Will be tested in phase | Status |
|---|---|---|---|---|
| A-{n}.{m} | | | | OPEN / CONFIRMED / FALSIFIED |

### 7.4 Prior assumptions re-checked

| ID | Assumption | Status this phase | Evidence |
|---|---|---|---|

---

## 8. Impact log delta (Cross-phase protocol)

### 8.1 Opened this phase

| ID | Severity | Affected phase | Assumed | Actually true | Evidence | Outputs invalidated | Response |
|---|---|---|---|---|---|---|---|

### 8.2 Resolved this phase

| ID | How resolved | Gates re-run | Reports amended |
|---|---|---|---|

### 8.3 Still open

| ID | Severity | Why still open | Planned resolution phase |
|---|---|---|---|

{If none in any subsection, write "None."}

---

## 9. Results and numbers

{The substantive output of the phase. Real values, not descriptions of values. Tables,
distributions, key statistics. This is the section a reviewer will scrutinize hardest.}

{Where a model was fit, include: feature list, coefficients or importances, fit statistics,
validation metrics with their definitions written out, and the baseline comparison.}

---

## 10. Limitations introduced or discovered

| Limitation | Cause | Effect on downstream results | Mitigated? | Recorded in LIMITATIONS.md? |
|---|---|---|---|---|

{Include every fallback taken, every degraded source used, every threshold chosen without
empirical grounding.}

---

## 11. Specification compliance

### 11.1 Prime directives

| Directive | How compliance is enforced | Verified by |
|---|---|---|
| D1 No temporal leakage | | |
| D2 No supply-to-demand loop | | |
| D3 Three validation terms | | |
| D4 Zero recurring cost | | |
| D5 Greenfield | | |
| D6 Grid proximity language | | |
| D7 Uncertainty first-class | | |
| D8 Explicit degradation | | |

{Write "Not applicable to this phase" where a directive is not yet exercised, and say when
it will be.}

### 11.2 Deviations from specification

| Spec section | What the spec says | What was done | Why | Approved? |
|---|---|---|---|---|

{Any deviation not approved in advance should have triggered a PLAN_CHANGE document. Say so
if it did.}

---

## 12. Open questions for the reviewer

{Specific questions where an outside judgment would change the implementation. Not
rhetorical. Each should be answerable from this report alone.}

1.
2.

---

## 13. Next phase readiness

| Check | Status |
|---|---|
| All acceptance criteria passed | |
| Coverage thresholds met | |
| All prior gates passing | |
| Smoke-forward test passing | |
| Report complete and self-contained | |
| No S1 impacts open | |

**Recommendation:** PROCEED to Phase {N+1} / HOLD pending {specific}

---

## Corrections

{Never edit this report above this line after submission. Append dated corrections here.}

<!-- ## Correction — YYYY-MM-DD
     Discovered in Phase {n}. What was wrong, what is now true, what changed. -->
