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

## CI runner limits — 2026-09-01, awaiting an owner decision

§11.3 requires *"All performance budgets met and **CI-enforced**"* and *"Lighthouse CI runs
on every PR"*. `.github/workflows/ci.yml` now exists and runs on pull requests. Two
prerequisites are absent from a GitHub-hosted runner, and both were **measured on this
machine rather than assumed**.

### Limitation 1 — no GPU, and no software fallback either

A Chrome launched without GPU access does not fall back to SwiftShader here; it serves **no
WebGL context at all**:

```
--use-gl=swiftshader     => NO WEBGL AT ALL
--disable-gpu            => NO WEBGL AT ALL
```

So the national layer cannot render and **no frame rate exists to measure**. This is not a
degraded measurement that could be reported with a caveat; it is the absence of the thing
being measured. The harness refuses both cases explicitly — the `renderer === "none"` check
was added after this probe, because a name-only software check would have missed it and the
run would have failed later as an opaque timeout.

**No software frame rate and no proxy is substituted.** Bundle size, first-render success
and script execution time all remain excluded.

### Limitation 2 — no source data, and a silent-green failure it caused

`data/cache/` is git-ignored and **4.4 GB**. A CI runner cloning the repository has none of
it, so `make artifacts` cannot run and `web/public/data/` cannot be built. Consequences:

* most of the Python suite reads that cache, so **the full suite and its coverage
  thresholds cannot run** on a clean runner. Lint, types and the copy lint can, and do.
* the National Overview fetches the artifacts at runtime. Measured: with them absent, the
  page renders its error state and the TTI harness reported **0.96 s — a comfortable PASS
  against a 3.0 s budget — while measuring a page with no map and no data.**

That last one was a **defect in the harness**, found by this investigation and fixed
independently of CI: `perf-tti.mjs` now refuses to report unless the page under test holds
at least 50,000 cells, the same guard the frame-rate harness already carried.

### Limitation 3 — Time to Interactive is host-dependent, which I previously overclaimed

§12 of `PHASE_6_REPORT.md` said the pinned throttling profile meant "the number means the
same thing on a laptop and in CI". **That is wrong.** Lighthouse's `simulate` method
normalises the *network* but derives CPU task durations from a trace taken on the host.
Measured on this machine, same code, same page:

| `cpuSlowdownMultiplier` | TTI | against the 3.0 s budget |
|---|---:|---|
| 1 | 2.38 s | within |
| **4 (the shipped profile)** | **2.86 s** | **within** |
| 8 | 3.40 s | over |
| 12 | 3.96 s | over |

A shared CI runner is materially slower than this development machine, so even with the
identical profile its absolute figure would not be interchangeable with the accepted one.

### What the workflow does about it

Nothing is measured with weakened semantics. The jobs split by prerequisite:

| Check | On a GitHub-hosted PR runner | Where it is enforced |
|---|---|---|
| ruff, mypy --strict, D3 copy lint | **enforced** | both |
| Frontend typecheck, build, tests | **enforced** | both |
| Greedy port vs the Python reference, 2 s solve budget | **enforced** (fixtures committed, real 3,532-cell Texas surface) | both |
| **App shell ≤ 600 KB gzipped** | **enforced** — deterministic gzip of emitted files, identical semantics | both |
| **TTI ≤ 3.0 s** | skipped unless `PERF_DATA_RUNNER` is set | `make gate PHASE=6` |
| **Sustained ≥ 55 fps** | skipped unless `PERF_GPU_RUNNER` is set | `make gate PHASE=6` |
| Full Python suite + coverage thresholds | not run | `make gate PHASE=6` |

The two host-dependent jobs are **skipped rather than faked**, and an always-running
`performance-enforcement-status` job prints, on every PR, exactly which budgets that PR did
and did not enforce — so a green CI cannot be read as more than it is. That job also fails
if this section stops documenting the limitation.

Setting either repository variable to a runner that has the prerequisite turns the
corresponding job on with no other change.

### The narrowest truthful distinction, for owner decision

I am **not** adopting this unilaterally, because it distinguishes two things §11.3 states as
one:

**(a) CI-enforced reproducible performance regression check.** What a GitHub-hosted runner
can honestly provide today: the app-shell budget, which is deterministic and already
enforced, plus — if wanted — a *relative* TTI check against a runner-calibrated baseline
committed to the repository, catching "this PR made it twice as slow" without pretending the
runner's absolute number is the acceptance figure.

**(b) Hardware-rendered acceptance benchmark.** The absolute §11.3 budgets — TTI ≤ 3.0 s and
≥ 55 fps sustained — measured on a machine with a GPU and the source cache, which today is
`make gate PHASE=6`. This is where the accepted figures (2.87 s, 59.0 fps) come from.

**Three options.**

**Option A — provide the runners, and the literal requirement is met as written.** Set
`PERF_DATA_RUNNER` and `PERF_GPU_RUNNER` to a self-hosted runner with a GPU and the source
cache. No code change; both jobs activate. This is the only option under which "all
performance budgets CI-enforced" is literally true, and it is what I recommend if a machine
is available.

**Option B — adopt the (a)/(b) split, and amend §11.3's wording to match.** The absolute
budgets remain gate-enforced on hardware; PRs get the deterministic shell budget plus a
relative regression check. This is honest but it **is** a weakening of the literal
requirement, which is why it needs your approval rather than my judgement.

**Option C — leave it as it stands.** The workflow enforces what it can, skips what it
cannot, and says so on every PR. The literal requirement remains unmet and visibly so.

**I have stopped here rather than choosing.** The workflow as committed is Option C, which
is the only one of the three that does not require a decision from you — and it hides
nothing.

## What I did in the meantime

Built the task the protocol needs, so whichever option is chosen the check is ready to run:
the Studio takes a state and a budget and produces an exportable ranked portfolio in a
single view, with no prerequisite reading. `test_p6_g_the_unmoderated_usability_check_is_recorded_as_outstanding`
asserts this document exists with its options and protocol, so the gap stays visible in the
gate output rather than resting on someone remembering it.

**I have not marked the criterion passed, and the Phase 6 report does not claim it.**
