# VoltGap: deployment

Manual deployment of the current Core release to Vercel. This is a **frozen portfolio
release**, not Phase 7 automation: there is no scheduled ETL, no automated refresh and no
keepalive workflow, and none of those is required for the site to work.

Every fact below was measured against this repository rather than assumed from a general
Next.js setup. Where a number appears, it came from a command whose output is quoted.

---

## 1. Audit findings

### 1.1 Build topology

| Question | Answer | How it was established |
|---|---|---|
| Frontend root directory | **`web`** | The Next.js app lives there; the repository root is the Python pipeline |
| Package manager | **npm** | `web/package-lock.json` present; no yarn or pnpm lockfile |
| Node version | **22.x** (24.9.0 used locally) | No `engines` field and no `.nvmrc`; Next.js 15 requires ≥ 18.18. Pinned explicitly at §3.4 rather than left to drift |
| Build command | **`npm run build`** → `next build` | `web/package.json` scripts |
| `output: "export"` | **Yes** | `web/next.config.ts` |
| Output directory | **`out`** | `output: "export"` writes `out/`, not `.next` |
| Routes produced | 6 (below) | `next build` route table |
| Server runtime required | **None** | A gate test asserts no `api/`, `_next/server`, `server.js`, `middleware.js` or `proxy.js` exists in the export |

Routes in the static export:

```
/                 EV demand (national overview)
/access/          Charging gaps
/studio/          Plan locations (Siting Studio)
/how-it-works/    Plain-language explanation
/methodology/     Methodology & Architecture
/404/             Not found
```

`trailingSlash: true` is set, so the export is servable by any static host without rewrite
rules.

### 1.2 The deployment risk, found and fixed

**This is the finding that mattered.** The brief warned about a successful build that
renders an empty application. That was the exact state of the repository.

`web/public/data/` (every file the browser fetches at runtime) was listed in
`.gitignore`. Measured before the fix:

```
$ git archive HEAD | tar -t | grep -c '^web/public/'
0
```

A clean clone contained **zero** files under `web/public/`. Vercel would have cloned,
installed, built successfully, exported six routes, and served an application in which
every data fetch returned 404. The three data-driven views would have shown their error
state. Nothing in the build would have failed.

It survived this long because local development and the gate both run `make artifacts`
first, so the directory was always populated on any machine that had ever run the
pipeline. A build host has not.

**Resolution: the runtime artifacts are now committed.**

| File | Size |
|---|---:|
| `web/public/data/access_points.parquet` | 7.07 MB |
| `web/public/data/hex6_national.parquet` | 2.96 MB |
| `web/public/data/sites.parquet` | 1.06 MB |
| `web/public/data/manifest.json` | 0.01 MB |
| `web/public/data/frontier/*.json` (6 states) | < 0.01 MB |
| **Total** | **11 MB across 10 files** |

**Why committing them is the right answer here**, rather than the object-storage path the
architecture also supports:

- **It is small.** 11 MB total, largest file 7.07 MB: an order of magnitude inside
  GitHub's 50 MB per-file warning and well inside Vercel's deployment limits.
- **It is frozen.** This release does not refresh, so the artifacts are written once. The
  usual objection to binaries in Git (history bloat from repeated churn) does not apply.
- **It removes moving parts.** No bucket, no CORS configuration, no base-URL environment
  variable, no second place for the deployment to be wrong. The most reliable deployment
  is the one with fewest external dependencies.
- **It guarantees provenance.** The deployed site serves byte-for-byte the artifacts the
  release gate verified, checksummed in `manifest.json`. Nothing can drift between what
  was tested and what is served.
- **It keeps the 4.4 GB cache out of the picture.** Vercel never runs the Python pipeline
  and never needs `data/cache/`.

**The alternative, and why it was not chosen.** `NEXT_PUBLIC_DATA_BASE` already supports
pointing the frontend at an external origin (Cloudflare R2 was the design target). That
path remains available and is documented at §5 for a future release where artifacts grow.
For 11 MB it would add a bucket, a CORS policy and an environment variable to be
misconfigured, in exchange for nothing.

**Verification after the fix:**

```
$ git archive $(git write-tree) | tar -t | grep -c '^web/public/data'
12          # 10 files + 2 directory entries
```

### 1.3 Environment variables

| Variable | Required on Vercel? | Default | Contains anything sensitive? |
|---|---|---|---|
| `NEXT_PUBLIC_DATA_BASE` | **No** | `/data` | No: a path on the site's own origin |

**Set nothing.** The default serves artifacts from the deployment itself, which is what
committing them enables.

The four pipeline API keys (`NREL_API_KEY`, `CENSUS_API_KEY`, `HUD_USER_TOKEN`,
`EIA_API_KEY`) are used **only by the offline Python pipeline**. They must **not** be added
to Vercel: the frontend never reads them, and a `NEXT_PUBLIC_*` value is compiled into
client JavaScript and readable by anyone.

Checked: the only `NEXT_PUBLIC_*` reference in the entire frontend is
`NEXT_PUBLIC_DATA_BASE`, in `web/lib/data/manifest.ts` and `web/next.config.ts`. No
credential reaches the browser bundle.

### 1.4 External hosts and CORS

One external origin: **`https://tiles.openfreemap.org`**, the basemap. It requires no API
key, serves permissive CORS headers, and is designed for direct browser use. No
configuration is needed.

With artifacts served same-origin, **no CORS configuration is required anywhere**. (This
changes if you later move artifacts to object storage: see §5.)

### 1.5 Freshness reporting: corrected for a frozen release

The interface carries a data-age indicator driven by `manifest.json.computed_at`. Its
wording was **wrong for a manual release** and was fixed as part of this work.

| | Was | Now |
|---|---|---|
| Fresh | "Data refreshed today." | "Data artifacts built today. Sources carry their own, older vintages." |
| Past threshold | "…past the 14-day refresh threshold. **The scheduled refresh may have stopped.**" | "…past this release's 14-day freshness threshold. Sources carry their own, older vintages." |

Two separate untruths were removed. There is no scheduled refresh behind this release, so
claiming one "may have stopped" would have asserted a broken automation that does not
exist, and it would have started saying so on the fourteenth day after publication.
Separately, `computed_at` is when the **artifacts were built**, not when the underlying
data was refreshed; the registration and census inputs are considerably older, and their
vintages are listed separately in the manifest. Telling a reader that year-old
registration data was refreshed this morning would be false.

The indicator still reports age plainly, as the specification requires. It simply now
describes the thing it actually measures.

### 1.6 Route and asset verification

All six routes are prerendered as static HTML. A gate test asserts each exists and is
larger than 2 KB, so an empty or error-page export fails the release rather than shipping.

Runtime fetches, all same-origin under `/data/`:

| Route | Fetches |
|---|---|
| `/` | `manifest.json`, `hex6_national.parquet` |
| `/access/` | `manifest.json`, `access_points.parquet` |
| `/studio/` | `manifest.json`, `hex6_national.parquet`, `frontier/{State}.json` |
| `/how-it-works/`, `/methodology/` | none: fully static |

---

## 2. Repository preparation: completed

Everything in this section is done; no owner action is required for any of it.

- [x] Runtime artifacts committed (`web/public/data/`, 11 MB, 10 files), with the
      `.gitignore` entry replaced by a comment explaining why.
- [x] Clean-checkout build verified: extract the committed tree to an empty directory,
      `npm ci && npm run build`, confirm `out/data/` is populated: with no pipeline run
      and no source cache present.
- [x] Freshness copy corrected for a frozen release (§1.5).
- [x] `vercel.json` added, pinning the framework, build command, output directory and
      long-lived cache headers for the immutable artifacts.
- [x] Node version pinned via `engines` in `web/package.json` and `.nvmrc`.
- [x] Gate assertions extended to cover the two new routes and the figures the
      Methodology page publishes.
- [x] Full release gate re-run: see the release-readiness summary.

---

## 3. Owner actions

These are the steps only you can perform. They assume you are starting from this
repository on your machine with everything committed.

### 3.1 Push to GitHub

The repository already points at `https://github.com/SarveshSoni09/VoltGap`. The `gh` CLI
in the development environment is authenticated as a read-only account and **cannot
push**, so this step is yours.

```bash
git push origin main
```

If the remote rejects the push because the repository is empty or the branch has diverged,
confirm what is there first with `git remote -v` and `git log --oneline origin/main -1`
rather than forcing.

**Expect this push to include 11 MB of Parquet.** That is intended (§1.2).

### 3.2 Import the project into Vercel

1. Sign in at <https://vercel.com> with the GitHub account that owns the repository.
2. **Add New… → Project**.
3. Find **VoltGap** in the repository list and click **Import**. Grant repository access
   if prompted.

### 3.3 Configure the project

This is the step where a wrong value produces a green build and a broken site. Three
settings matter:

| Setting | Value |
|---|---|
| **Framework Preset** | Next.js (detected automatically) |
| **Root Directory** | **`web`** ← must be changed from the default |
| Build Command | `npm run build` (default) |
| Output Directory | `out` |
| Install Command | `npm ci` (default) |
| Environment Variables | **none** |

**Root Directory is the one to get right.** The default is the repository root, which
holds the Python pipeline and no `package.json`. Click **Edit** beside Root Directory and
enter `web`.

`vercel.json` in the repository root already declares the build command, output directory
and cache headers, so the dashboard values should match what it specifies. If the
dashboard and `vercel.json` disagree, `vercel.json` wins.

Do **not** add any environment variable. In particular do not add the four pipeline API
keys: the frontend never reads them, and anything prefixed `NEXT_PUBLIC_` is compiled
into client JavaScript and publicly readable.

### 3.4 Node version

Set **Node.js Version: 22.x** under **Settings → General** if it is not already. The
repository pins the same version through `.nvmrc` and `engines`, so a mismatch would be
visible rather than silent.

### 3.5 First deployment

Click **Deploy**. Expect roughly two to four minutes: install, `next build`, static
export, upload.

A successful build log ends with the route table showing six routes marked `○ (Static)`.

### 3.6 Production verification

Run the smoke test at §4 against the deployment URL. Do not skip it: the failure mode
this release was most exposed to produces a **completely successful build log**.

### 3.7 Optional: custom domain

**Settings → Domains → Add**, then follow the DNS instructions Vercel shows for your
registrar. A custom domain changes nothing about the build; artifacts remain same-origin.

### 3.8 Redeploying

Any push to `main` triggers a new deployment automatically. To redeploy the same commit (after changing a project setting, for example) use **Deployments → ⋯ → Redeploy** and
leave "Use existing Build Cache" unchecked if you changed anything about the build
configuration.

To publish updated data, rebuild the artifacts locally and commit them:

```bash
make artifacts
git add -f web/public/data
git commit -m "data: refresh published artifacts"
git push
```

---

## 4. Production smoke test

Run every check against the live URL. Six routes, four of which must load data.

### 4.1 Routes respond

```bash
BASE=https://your-deployment.vercel.app
for p in / /access/ /studio/ /how-it-works/ /methodology/; do
  printf '%-18s %s\n' "$p" "$(curl -s -o /dev/null -w '%{http_code}' "$BASE$p")"
done
```

All five must return `200`.

### 4.2 Data artifacts are served

```bash
for f in manifest.json hex6_national.parquet access_points.parquet sites.parquet \
         frontier/Washington.json; do
  printf '%-28s %s\n' "$f" "$(curl -s -o /dev/null -w '%{http_code} %{size_download}' "$BASE/data/$f")"
done
```

All five must return `200` with a non-trivial byte count. **A `404` here is the failure
this release exists to prevent**: it means the artifacts did not reach the deployment.

### 4.3 Interface checks, by eye

| Route | Must be true |
|---|---|
| `/` | Coloured hexagons over the map; city names and state borders readable *through* the surface; metric selector changes the colouring; hovering a cell shows a card naming a county; the Geography dropdown zooms to a state |
| `/access/` | Threshold slider moves the headline figures **and** the map together; the four gap views each highlight a subset over the full grey gap surface; the subset line states the proportion |
| `/studio/` | Choosing a state and budget returns a ranked table within about a second; hovering a row highlights its map marker and vice versa; rank numbers on markers match the table; CSV and GeoJSON export download and parse |
| `/how-it-works/` | Reads as plain language; no H3, Poisson, ε-constraint or CBC anywhere; the Methodology link works |
| `/methodology/` | Sticky contents highlights the section in view; all 23 sections present; tables scroll horizontally on a narrow window rather than overflowing the page |
| all | Header shows "Data artifacts built … Sources carry their own, older vintages": **never** "The scheduled refresh may have stopped" |

### 4.4 Console and network

Open developer tools on `/` and confirm: no console errors, no failed requests, and
`tiles.openfreemap.org` returning tiles.

---

## 5. If artifacts outgrow Git

Not needed for this release. Recorded so the decision is not re-derived later.

Should the artifacts grow past roughly 50 MB, move them to object storage rather than Git
LFS:

1. Upload the contents of `web/public/data/` to a Cloudflare R2 bucket, preserving the
   directory layout.
2. Enable public read access and set a CORS policy allowing `GET` from the deployment
   origin. **This is required**: the browser fetches these cross-origin, and a missing
   CORS header fails silently in exactly the way §1.2 describes.
3. Set `NEXT_PUBLIC_DATA_BASE` in Vercel to the public bucket URL, with no trailing slash.
4. Re-run the §4.2 checks against the bucket URL.

The trade is explicit: an external dependency and a CORS surface, in exchange for keeping
large binaries out of Git history.

---

## 6. What is deliberately not deployed

Per the release scope freeze:

- No scheduled ETL or automated refresh.
- No keepalive workflow.
- No R2 automation.
- No serverless functions: `output: "export"` makes this a build-time guarantee.
- No Extension-tier features.

The site is a fixed snapshot. It says so, in those words, in its own freshness indicator.
