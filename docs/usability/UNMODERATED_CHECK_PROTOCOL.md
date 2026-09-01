# Unmoderated usability check — protocol and record sheet

The Phase 6 acceptance criterion (§15.5):

> Unmoderated usability check: one person unfamiliar with the project produces a siting
> recommendation without instructions.

**This has not been run.** It requires a human participant. It must not be simulated,
automated, or self-administered, and nothing in this repository claims it has passed.

Everything below is prepared so the check is a scheduling problem, not a design problem.
The facilitator fills in §4 and commits it.

---

## 1. Participant eligibility

All of these must hold. If any fails, the participant is not eligible and the run does not
count.

- [ ] Has **not** seen VoltGap, this repository, or any of these reports
- [ ] Was **not** involved in specifying, building or reviewing the project
- [ ] Has not been told what the tool does beyond the task wording in §3
- [ ] Is comfortable using a web browser unaided

No EV, GIS, energy or data-science background is required, and none should be sought — a
participant who already knows what a "DCFC access gap" is cannot tell us whether the
interface explains itself.

## 2. Setup

1. Build and serve the production static export:
   ```
   make artifacts && make web-build && node web/serve-static.mjs
   ```
2. Open **the National Overview** (`http://localhost:4321/`) on a normal-sized screen.
3. Have a clock or timer ready.
4. Do **not** describe the interface, name any view, or point at anything.

## 3. The task, read or handed over verbatim

> You have a budget for 20 new EV charging sites in Washington state. Produce a list of
> where you would put them, and save it as a file.

Say nothing else. If the participant asks a question, record it in §4.4 and reply only:
*"Whatever you think is best — I can't help with this one."*

Stop the run at **15 minutes** if they have not finished.

## 4. Record

Filled in by the facilitator during and immediately after the run.

**4.1 Participant eligibility confirmed:** ☐ yes ☐ no — *(if no, the run does not count)*

**4.2 Did they produce a siting recommendation without instruction?** ☐ yes ☐ no

*This is the criterion. "Yes" requires a downloaded CSV or GeoJSON file, or a written list
of specific locations they identified using the tool.*

**4.3 Completion time:** ______ minutes  *(or "not completed" if stopped at 15)*

**4.4 Blocking confusion** — every point where they stalled, backtracked, asked a question,
or did something that did not work. Quote what they said where possible.

| Time | What happened | Their words |
|---|---|---|
| | | |

**4.5 Did they reach the Siting Studio unaided?** ☐ yes ☐ no — *(if no, how did they try?)*

**4.6 The comprehension question, asked only after the task ends:**

> In your own words, what did this tool just tell you?

Record the answer verbatim: ______________________________________________

**Then specifically:** did they come away believing the tool identified the **best** places
to build? ☐ yes ☐ no ☐ unclear

*This matters as much as the completion. A participant who finishes the task but leaves
believing the output is optimal has exposed a real failure of the §11.5 language rules —
the interface says in several places that it is a ranking and not a claim of optimality. If
they missed all of it, the copy is not working, and that finding outranks the completion.*

**4.7 Result against the predeclared criterion:** ☐ **PASS** ☐ **FAIL**

*PASS requires 4.1 = yes and 4.2 = yes. Nothing else can convert a fail into a pass.*

**Facilitator:** ______________  **Date:** ______________

## 5. If it fails

In this order, and not in any other:

1. **Record the failure first**, in this document, committed, before anything is changed.
   The record is the evidence; a fix applied before it is written down leaves no trace of
   what was actually wrong.
2. Diagnose from §4.4 and §4.6.
3. Make the correction.
4. **Re-run with a new participant who is also unfamiliar with the project.** The original
   participant is no longer eligible — they have now seen it.

## 6. What must not happen

- The interface must **not** be changed after watching the participant unless the check
  **failed**. Adjusting it in response to behaviour that still produced a pass is tuning
  the product to one person, and it invalidates the result that was just obtained.
- The task wording in §3 must not be softened, expanded, or supplemented mid-run.
- A partial result is a **fail**, not a qualified pass.
