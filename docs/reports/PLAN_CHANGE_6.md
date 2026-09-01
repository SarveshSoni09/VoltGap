# Plan change 6 — the unmoderated usability check cannot be executed by an automated gate

Raised under §15.6. Every other Phase 6 acceptance criterion is met and verified by an
executable check. This one is not, and it is escalated rather than redefined into something
I can pass.

## What the specification requires

§15.5, Phase 6 acceptance criteria:

> Unmoderated usability check: one person unfamiliar with the project produces a siting
> recommendation without instructions.

## Why it cannot pass here

It requires **a human participant who has not seen this project**. I cannot recruit one,
and I cannot simulate one: the whole value of the check is that a person unfamiliar with
the design meets the interface cold, and anything I produce is by construction familiar
with it. Reporting a simulated result would be fabricating evidence about a real person.

§15.1 G-A is explicit that "100% of the phase's declared criteria [must be] verified by an
executable check" and that "no criterion is marked passed by inspection". Both halves bind
here: I cannot execute it, and I may not wave it through.

This is a limit of the environment, not a defect in the specification. The criterion is a
good one — an interface that needs a briefing to use has failed at its job, and no
automated check substitutes for watching someone try.

## Evidence

What **is** verified automatically, and what it does and does not tell you:

| Verified | What it shows | What it does not show |
|---|---|---|
| All four views statically export and render real data | The task is reachable from a cold start | Whether anyone can work out what to do |
| A portfolio can be produced end to end: pick a state, set a budget, read a ranked table, export CSV/GeoJSON | The path exists and terminates in a usable artifact | Whether an unprompted person finds that path |
| Every candidate row carries its confidence tier and evidence grain | The caveats are present at the point of decision | Whether a reader understands them |
| The browser's candidate universe reproduces Phase 4's counts exactly, per state | The interface is not quietly siting on different cells | Nothing about comprehension |
| App shell 307.4 KB of a 600 KB budget; Texas re-solve well inside 2 s | The interface responds fast enough to explore | Whether exploring it makes sense |

So the machinery a participant would need is demonstrably present and correct. What is
untested is the only thing this criterion was written to test: **whether a person who has
never seen it can get to a recommendation unaided.**

## The protocol, ready to run

Written out so the check is a scheduling problem rather than a design problem. It needs one
participant and about fifteen minutes.

**Recruit.** One person who has not seen VoltGap, this repository, or these reports. Any
professional background; no EV or GIS knowledge required.

**Set up.** Open the deployed site at the National Overview. Give them the task below and
nothing else. Answer no questions during the attempt; note where they ask.

**The task, given verbatim and with no other instruction:**

> You have a budget for 20 new EV charging sites in Washington state. Produce a list of
> where you would put them, and save it as a file.

**Record.** Whether they produced an export (the criterion), time taken, every point where
they hesitated or backtracked, anything they said aloud, and — separately, because it is
the thing this project most needs to know — whether they came away believing the tool had
told them the *best* places to build. A participant who finishes the task but leaves
thinking the output is optimal has exposed a real failure of the §11.5 language rules, and
that finding matters more than the completion.

**Pass condition.** The participant produces a siting recommendation without instructions.

## Options

**Option A — the owner runs the protocol above, and Phase 6's gate closes when they do.**
Phase 6 is otherwise complete, so this is the only outstanding item. Cost: one participant,
about fifteen minutes. This is the option that actually satisfies the criterion as written,
and it is what I recommend.

**Option B — accept Phase 6 with the criterion explicitly outstanding, and close it in
Phase 7.** Phase 7 already requires a full rebuild verification on a fresh machine, so a
person is in the loop there anyway. Cost: the frontend ships without ever having been given
to an unfamiliar user, which is exactly the risk the criterion exists to catch. If this is
chosen, it should be recorded in `LIMITATIONS.md`, not just in a report.

**Option C — amend the criterion to something automatable.** I do not recommend this and am
not proposing wording for it. Every automatable proxy I can construct — task-flow
reachability, click depth, reading level — measures the interface against my own model of a
user, which is the assumption the criterion was written to test rather than trust. Replacing
it would remove the only check in the whole plan that involves a person who is not already
persuaded.

## Amendment — 2026-09-01

External review, on the first Phase 6 submission, made two things explicit that this
document had blurred.

**The performance budgets are Phase 6 criteria and were not deferrable.** I had recorded
cold time-to-interactive and sustained frame rate as assumptions A-6.1 and A-6.2 to be
closed in Phase 7. That was wrong: §15.5 requires "All performance budgets met and
CI-enforced" *in Phase 6*, and moving an unmet criterion into an assumption is relabelling,
not measuring. Both are now measured by reproducible harnesses that fail the gate when
exceeded, and **both pass**. A-6.1 and A-6.2 are closed by measurement. Details in
`PHASE_6_REPORT.md` §12.

**The usability criterion stays genuinely outstanding.** The protocol below is unchanged
and is not to be simulated, automated or self-administered. The record sheet a facilitator
fills in now lives at `docs/usability/UNMODERATED_CHECK_PROTOCOL.md`, covering participant
eligibility, the verbatim task, whether a recommendation was produced without instruction,
completion time, blocking confusion, and pass/fail against the predeclared criterion. It
also fixes the order of operations if the check fails: record the failure first, then
correct, then re-run with a **new** unfamiliar participant.

Options A, B and C below stand as written. **A remains my recommendation.**

## What I did in the meantime

Built the task the protocol needs, so whichever option is chosen the check is ready to run:
the Studio takes a state and a budget and produces an exportable ranked portfolio in a
single view, with no prerequisite reading. `test_p6_g_the_unmoderated_usability_check_is_recorded_as_outstanding`
asserts this document exists with its options and protocol, so the gap stays visible in the
gate output rather than resting on someone remembering it.

**I have not marked the criterion passed, and the Phase 6 report does not claim it.**
