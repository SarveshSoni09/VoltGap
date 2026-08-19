# Starter prompt

Paste the block below into Claude Code as your first message, in the project directory.
Nothing else is needed. Do not paste the specification itself; Claude Code will read it.

---

```
Read CLAUDE.md in full before doing anything. It is the authoritative specification for
this repository and it overrides your default assumptions about what this kind of project
looks like. Then read docs/templates/PHASE_REPORT_TEMPLATE.md and data/seed/MANIFEST.md.

Context: this is a greenfield build. There is no prior version to match or extend.

Rules for how we work together:

1. Work strictly one phase at a time, in the order given in CLAUDE.md section 15.5.
2. Do not begin a phase until I have approved the previous phase's report. After you finish
   a phase, run the gate, write the report, commit, and stop. Wait for me.
3. The gate has five parts (CLAUDE.md section 15.1). All five must pass. Do not report a
   partial gate as a pass.
4. If you find that the specification itself is wrong or unworkable, do not work around it
   and do not revise it yourself. Write docs/reports/PLAN_CHANGE_{n}.md with the evidence
   and at least two options with tradeoffs, then stop and ask me.
5. If a later phase invalidates an earlier one, follow the cross-phase impact protocol in
   CLAUDE.md section 15.3. Stop first, record it, classify severity, then act.
6. Phase reports are read by me and by an external AI reviewer who will have no access to
   this repository or any of our conversation. Every report must be fully self-contained:
   quote actual code, actual numbers, actual schemas, actual test names and assertions.
   Never write "see file X".
7. Never claim a siting recommendation is validated as optimal. Use the three validation
   terms in CLAUDE.md directive D3 exactly and consistently.
8. Zero recurring cost. Free tiers only. If a free path does not exist for something, tell
   me rather than assuming a paid one.

Start with Phase 0, the source contract, and nothing beyond it.

Phase 0 deliverables:
  - pipeline/discovery/probe.py, idempotent, writes SOURCES.yml
  - SOURCES.yml complete for every source, all contract fields per CLAUDE.md section 4.1
  - docs/SOURCE_VERIFICATION.md
  - docs/reports/PHASE_0_REPORT.md
  - docs/reports/ASSUMPTION_LEDGER.md (initialized)
  - docs/reports/IMPACT_LOG.md (initialized, empty)

Phase 0 must specifically resolve these four unknowns, because the modeling design depends
on them and I do not want them assumed:
  a) Does the AFDC charging units endpoint expose per-connector power_kw and port_count,
     and what is the measured missingness of each?
  b) Are the NREL county home charging access shares current values or 2030 scenario
     projections?
  c) Do historical state-level EV registration vintages exist anywhere obtainable
     (Atlas EV Hub archives, state DMV historical releases, IEA national stock series)?
  d) Exactly which states have usable open sub-state EV registration data, at what
     granularity, and over what time period?

Before you write code, tell me your plan for Phase 0 and flag anything in CLAUDE.md that is
ambiguous or that you think is wrong. I would rather resolve it now than at a gate.
```

---

## After each phase

When Claude Code stops with `gate(phase-n): PASS`:

1. Read `docs/reports/PHASE_{n}_REPORT.md`.
2. Paste the full report to your external reviewer. It is written to be self-contained, so
   no other files are needed. A useful framing for that review:

   > This is a phase gate report from a data engineering and geospatial modeling project.
   > Review it for methodological soundness, unsupported claims, missing validation, and
   > anything that will cause problems in later phases. The report is intended to be
   > self-contained; tell me if it is not, and what is missing.

3. Return here with either approval or the corrections, and tell Claude Code to proceed or
   to address the findings first.

## If a phase report says FAIL

Do not approve it and do not let the next phase start. Ask Claude Code for the specific
failing criteria and its remediation plan. A failed gate that is honestly reported is
working as designed.
