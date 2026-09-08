# VoltGap

**Where should the next EV charging infrastructure be built in the United States, and how
confident should we be in that answer?**

VoltGap is an open, statically hosted decision-support application that combines estimated
EV demand, existing charging access, community characteristics and infrastructure
constraints to help planners explore where additional charging investment may have the most
value. It runs entirely on public data at zero recurring cost.

The second half of that question carries as much weight as the first. Every estimate ships
with the evidence underneath it, and the interface is built so a weak estimate cannot be
mistaken for a strong one.

---

## What it does

| View | Question it answers |
|---|---|
| **EV demand** | Where are electric vehicles concentrated, and how good is the evidence there? |
| **Charging gaps** | Which communities are furthest from public fast charging, and how many people does that affect? |
| **Plan locations** | Given a state, a budget and a priority, which candidate areas would a portfolio choose, and what does that choice give up? |
| **Methodology** | The full technical record: sources, models, validation, engineering and every open limitation |

## How it is built

```
Public data sources  →  Source verification & caching  →  Canonical models (DuckDB)
                     →  Supply / access / demand modeling  →  H3 spatial processing
                     →  Candidate generation  →  Offline optimization (PuLP + CBC)
                     →  Static artifacts  →  Next.js static export  →  Browser workers
```

Everything analytical happens offline in Python. The browser receives finished, checksummed
artifacts and re-derives nothing: except the interactive portfolio solver, which is
checked against the offline exact solver rather than trusted.

**Stack.** Python 3.12, DuckDB, pandas, Pandera, scikit-learn, H3, PuLP/CBC · TypeScript,
Next.js, React, MapLibre GL JS, deck.gl, Web Workers · pytest, Ruff, mypy strict, Vitest,
GitHub Actions.

## Things worth knowing

- **Existing charging supply is excluded from the demand model, enforced by a test.**
  Infrastructure is an outcome of past investment; predicting demand from it and then
  siting from that demand would launder historical deployment patterns into "need".
- **Three validations that are never conflated**: demand model validation, historical
  deployment alignment, and cross-objective robustness. A copy lint fails the build if the
  vocabulary blurs.
- **A runtime leakage guard.** Every backtest feature must satisfy
  `feature_release_date <= prediction_cutoff`, checked at runtime with a committed negative
  test. Release date, not data period: the 2016–2020 ACS was published in March 2022.
- **The headline backtest result is negative and reported as such.** The model beats random
  by 5.9–6.7×, and loses to a simple population baseline at every origin.
- **Nothing here claims to find best sites.** There is no ground truth for siting, so
  nothing on the page could be checked against one.

## Running it

```bash
uv sync                     # Python environment
make artifacts              # rebuild published artifacts from accepted pipeline outputs
cd web && npm ci && npm run dev
```

Full rebuild needs a local source cache (~4.4 GB, git-ignored). The published artifacts in
`web/public/data/` are committed, so the frontend runs from a clean clone without it.

```bash
make gate PHASE=6           # the full release gate
```

## Deployment

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for the audited deployment topology and
step-by-step Vercel instructions.

## Documentation

| Document | Contents |
|---|---|
| [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) | Formulas, thresholds, estimator choices |
| [`docs/SOURCE_VERIFICATION.md`](docs/SOURCE_VERIFICATION.md) | Every source: confirmed, degraded or unavailable |
| [`docs/FUTURE_WORK.md`](docs/FUTURE_WORK.md) | Deliberately deferred work |
| [`docs/DATA_GOTCHAS.md`](docs/DATA_GOTCHAS.md) | Source domain rules, each with a regression test |
| [`docs/VALIDATION.md`](docs/VALIDATION.md) | All three validations, in full |
| [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md) | What this does not establish |
| [`docs/reports/`](docs/reports/) | Per-phase reports, assumption ledger, impact log |

## Status

Core Phases 0–6 complete; this release is a frozen snapshot with no scheduled refresh
behind it, and the interface says so.

Two things are outstanding and recorded rather than waived. An **unmoderated usability
check** with a participant unfamiliar with the project is the one unmet Phase 6 acceptance
criterion. **`DATA_DICTIONARY.md`** is a Phase 7 deliverable and is not yet written; field
definitions currently live in `docs/METHODOLOGY.md` and in the published `manifest.json`,
which carries the column list, row count and checksum of every artifact.
