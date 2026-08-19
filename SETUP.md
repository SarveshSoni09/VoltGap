# Setup: what to put in the empty directory

Everything below goes into your project root before you start Claude Code. This is the
complete set. Claude Code creates everything else itself.

## 1. Final layout of the starting directory

```
voltgap/
├─ CLAUDE.md                              ← the specification (provided)
├─ STARTER_PROMPT.md                      ← what you paste into Claude Code (provided)
├─ SETUP.md                               ← this file (provided)
├─ .gitignore                             ← (provided)
├─ .env.example                           ← (provided) copy to .env and fill in free keys
├─ Makefile                               ← (provided) `make gate PHASE=n` target stub
├─ docs/
│  ├─ templates/
│  │  └─ PHASE_REPORT_TEMPLATE.md         ← (provided)
│  └─ reports/                            ← empty, Claude Code fills it
└─ data/
   ├─ seed/                               ← your 12 source files go here
   │  ├─ MANIFEST.md                      ← (provided)
   │  ├─ alt_fuel_stations__Dec_11_2024_.csv
   │  ├─ alt_fuel_stations__Dec_10_2024_.csv
   │  ├─ EV_Registration_Counts_by_State.csv
   │  ├─ County_EV_Registrations_Summary.csv
   │  ├─ county_ev_counts.csv
   │  ├─ IL_StationsData.csv
   │  ├─ Simplified_EV_Charging_Stations.csv
   │  ├─ IEA_Global_EV_Data_2024.csv
   │  ├─ ev_launch_data.csv
   │  └─ Electric__Power_Transmission_Lines.geojson
   └─ cache/                              ← empty, gitignored, API responses land here
```

Create the empty directories yourself so Claude Code does not have to guess:

```bash
mkdir -p voltgap/docs/templates voltgap/docs/reports voltgap/data/seed voltgap/data/cache
cd voltgap && git init
```

## 2. The seed data files

Copy all ten data files from your uploads into `data/seed/`. Keep the filenames exactly as
they are; `MANIFEST.md` refers to them by name.

**Important:** `Electric__Power_Transmission_Lines.geojson` is 138 MB and is gitignored. Keep
it locally. Claude Code will convert it to vector tiles in Phase 1 and the tiles, not the
source, become the tracked artifact. If you want it in version control, use Git LFS, but it
is not necessary.

The two PDFs and `EV_Dashboard.py` from your uploads are **not** included. This is a
greenfield build (directive D5) and including prior work would anchor the implementation.
Keep them elsewhere if you want them for your own reference.

## 3. Free API keys to obtain before Phase 0

None are strictly blocking, but Phase 0 will move faster with them in place. All are free
and take a few minutes.

| Key | Where | Used for | Env var |
|---|---|---|---|
| NREL Developer key | `developer.nrel.gov/signup` | AFDC stations and charging units | `NREL_API_KEY` |
| Census API key | `api.census.gov/data/key_signup.html` | ACS, optional (bulk download works without) | `CENSUS_API_KEY` |
| EIA Open Data key | `eia.gov/opendata/register.php` | State electricity and fuel prices | `EIA_API_KEY` |

Copy `.env.example` to `.env` and fill these in. `.env` is gitignored.

## 4. Accounts to set up (not needed until later phases)

| Service | Needed by | Free tier note |
|---|---|---|
| GitHub | Phase 0 | Actions gives 2,000 minutes per month on private repos, unlimited on public |
| Cloudflare R2 | Phase 6 | 10 GB storage, no egress charge, but Class A/B operation quotas apply |
| Vercel | Phase 6 | Hobby tier is personal and non-commercial use only |

Do not set up R2 or Vercel yet. They are not needed and configuring them early invites
premature frontend work.

## 5. Local tooling

```bash
# Python
curl -LsSf https://astral.sh/uv/install.sh | sh    # or use your existing pyenv/poetry

# Node, for the frontend from Phase 6
# Node 20+ recommended

# tippecanoe, for vector tiles in Phase 1
# macOS:  brew install tippecanoe
# Linux:  build from github.com/felt/tippecanoe
```

Claude Code will set up the Python project properly in Phase 0. You do not need to
pre-install Python packages.

## 6. Starting

```bash
cd voltgap
claude
```

Then paste the block from `STARTER_PROMPT.md`.

## 7. What to expect

Claude Code should respond to the starter prompt by describing its Phase 0 plan and flagging
ambiguities in the specification **before writing code**. If it starts writing code
immediately without doing that, stop it and ask for the plan. The plan-first step exists to
surface spec problems while they are cheap.

Phase 0 should take roughly a week part-time and end with it stopping and waiting for you.
That stop is the protocol working, not a failure.
