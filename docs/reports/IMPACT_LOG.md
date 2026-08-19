# Impact log

Records every instance where a later phase invalidates an earlier one, per the
cross-phase impact protocol in CLAUDE.md §15.3.

Severity: **S1 Blocking** (an earlier phase's published output is wrong and downstream
results are invalid), **S2 Degrading** (usable but weaker than claimed), **S3 Cosmetic**
(documentation, naming or presentation only).

---

## Open entries

None.

## Resolved entries

None.

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
