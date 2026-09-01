# Phase 6 plan — Frontend Core

Written before implementation, so the acceptance criteria cannot be reinterpreted after
seeing what was easy to build. Phases 0–5 are frozen reviewed inputs; nothing below
re-derives a model quantity.

## What Phase 6 must deliver (§15.5, §11)

| Criterion | How it will be verified |
|---|---|
| Static export deploys | `next build` with `output: "export"` produces `web/out/`, asserted by a test that the expected HTML files exist and contain rendered content |
| Performance budgets met, **CI-enforced** | Bundle budget checked in CI against §11.3's 600 KB gzipped app shell; greedy re-solve timed |
| Exports produce valid CSV and GeoJSON **verified by parse** | The exporter is pure TypeScript, unit-tested by parsing its output back |
| UI copy lint passes (§11.5) | The Phase 1 copy lint extended over `web/`, run in the gate |
| Confidence tier renders on every modeled value | A test over the rendering layer, not an eyeball |
| Unmoderated usability check | **Cannot be executed by me — see below** |

## The one criterion I cannot execute

> *"Unmoderated usability check: one person unfamiliar with the project produces a siting
> recommendation without instructions."*

This requires a human participant. §15.1 G-A requires every criterion be "verified by an
executable check" and forbids marking one passed by inspection. I can neither recruit a
participant nor honestly simulate one.

**This is a real gate blocker, not a technicality**, and it is recorded here before
implementation so it cannot look like a convenient discovery afterwards. It is handled
under §15.6: if the gate cannot pass because the plan itself is unworkable in this
environment, the response is `PLAN_CHANGE_6.md` with options — not a quiet redefinition of
the criterion into something I can pass.

What I will do: build the *task* the check requires — a self-contained scenario a
participant can attempt — and ship the executable half (the artifact exists, is reachable
from a cold start, and the recorded path through it works), then declare the human half
outstanding and owner-owned. The decision on how to close it is the owner's.

## Data path, validated before building on it

Measured, not assumed:

- national surface: **84,401 tracts → 53,208 populated H3 res-6 cells**, built in 33 s
  from the accepted Phase 3 surface, with demand conservation and provenance survival
  asserted per state exactly as Phase 4 asserts them;
- `hex6_national.parquet`: **2.79 MB** with ZSTD at 8,192-row groups, against a §12 budget
  of 8–15 MB;
- **48,800 BEV (0.88%) unallocated** — demand in tracts with no block-group population
  weight. This is carried into the manifest and surfaced, not dropped.

## Hosting, and where R2 fits

§12 targets Cloudflare R2 for artifacts. I cannot provision R2 here, and §13.2 already
places "upload to R2" inside the **Phase 7** ETL workflow. So Phase 6 writes artifacts to a
local directory with a manifest, and the frontend reads them from a configurable base URL
defaulting to same-origin. Phase 7 points that base at R2. This keeps Core deployable and
testable now without inventing infrastructure, and without pretending R2 is wired up.

## Language constraints carried forward, unchanged

Every §11.5 rule stays in force and is machine-checked: no "optimal site", no "grid
feasible", no "charging desert" for a DCFC-only measure, no "Justice40 compliance", no
modeled tract without its confidence tier, **Tier A never labelled "observed"**, no
approximation bound for the interactive solver, and the three D3 validation terms never
conflated. Phase 5's results are presented as Phase 5 stated them: the historical
deployment-alignment result is **negative against the population baseline**, reconstructed
capacity carries its unknown-direction caveat, and no claim is strengthened for
presentation.
