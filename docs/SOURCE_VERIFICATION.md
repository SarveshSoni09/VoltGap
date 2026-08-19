# Source verification — Phase 0

Every source in `SOURCES.yml` was probed live on **2026-08-19 UTC** by
`pipeline/discovery/probe.py`. Nothing below is taken from documentation alone.
Measured values live in the generated sidecar `SOURCES.observed.json`; this document
summarises them and names the Core models each degraded source affects.

**Tally: 57 sources — 53 confirmed, 3 gated, 1 unavailable (by design).**
By tier: 53 Core, 3 Optional, 1 Extension.

Status meanings, assigned mechanically by the probe:

| Status | Meaning |
|---|---|
| `confirmed` | Reachable and measurable. Records were decoded, or an availability probe returned 2xx. |
| `gated` | Reachable but a credential is required, or the shared credential's quota is exhausted. |
| `degraded` | Reachable but the payload could not be measured, or the sample was empty. None in this run. |
| `unavailable` | Not reachable, or the resource does not exist. |

---

## 1. Not confirmed — the four exceptions

### 1.1 `afdc_stations` — gated (rate limit exhausted)

The AFDC station endpoint returned **HTTP 429** during the final probe run:

```
x-ratelimit-limit:     10
x-ratelimit-remaining: 0
retry-after:           78590     (~21.8 hours)
```

The shared `DEMO_KEY` credential is limited to 10 requests per window, and all three
AFDC specs (`afdc_stations`, `afdc_last_updated`, `afdc_charging_units`) share it, so a
single full probe run exhausts it. No credential is fabricated, entered or persisted by
this pipeline.

**Core models affected: supply, access, deployment alignment.** They are *not* blocked.
The 75-column station schema was verified live by another route: the first 75 columns of
the charging-units export are byte-identical to the station schema, both hashing to
`f6860736f1304654`, which is also the hash of the delivered December 2024 seed file.
The live envelope observed during discovery reported 89,685 electric station records and
292,399 ports.

**Action required from the operator:** obtain a free key at `developer.nlr.gov` and set
`NREL_API_KEY`. See §3 below — the signup URL in `SETUP.md` no longer resolves.

### 1.2 `census_acs_api` — gated (key now mandatory)

`https://api.census.gov/data/2023/acs/acs5` returns an HTML page titled *Missing Key*
without `CENSUS_API_KEY`. `SETUP.md` describes this key as optional because "bulk
download works without"; the *API* path is no longer keyless.

**Core models affected: demand model, home charging, equity. Not blocked.** The keyless
bulk path is confirmed and is the primary retrieval route:
`https://www2.census.gov/programs-surveys/acs/summary_file/2023/table-based-SF/data/5YRData/acsdt5y{year}-{table}.dat`,
pipe-delimited, HTTP 200, 26,878,591 bytes for B25003.

### 1.3 `eia_prices_api` — gated (no anonymous access)

Returns HTTP 403 `API_KEY_MISSING`. There is no demo credential.
**Optional tier; no Core model is affected.** The keyless bulk fallback
`https://www.eia.gov/electricity/data/state/avgprice_annual.xlsx` is confirmed.

### 1.4 `census_cenpop_block` — unavailable (probed to establish absence)

HTTP 404, as expected. The `CenPop2020` directory publishes `county/`, `tract/` and
`blkgrp/` only. There is **no ready-made block-level population-weighted centroid
product.** This is recorded as a source entry precisely so the absence is a measured
fact rather than an assumption. See §2.2.

---

## 2. Confirmed but qualified

These four passed the mechanical status check yet carry findings a later phase must act
on. Recording them here is the point of §4.2 task 6.

### 2.1 `hifld_substations` — no national layer exists that Phase 0 could locate

The probe confirms *a* service is reachable, but the substantive result is negative.
Five searches were run:

| Search | Result |
|---|---|
| HIFLD ArcGIS org `services1.arcgis.com/Hp6G80Pky0om7QvQ` | 526 services enumerated; matches for `/sub\|electric\|power\|transmis/i` are `Electric_Power_Transmission_Lines` and `Planned_transmission_line_`. No substation layer. |
| EIA Energy Atlas org `services7.arcgis.com/FGr1D95XCGALKXqM` | 79 services. None. |
| `hifld-geoplatform.hub.arcgis.com/datasets/electric-substations` | HTTP 404 |
| ArcGIS Online title search, Feature Service, "Electric Substations" | No authoritative national result in the top 10 by views |
| `services.arcgis.com/G4S1dGvn7PIgYd6Y/.../HIFLD_electric_power_substations/0` | HTTP 200, point geometry, 32 fields, **`returnCountOnly` → 128 features** |

128 features is not a national layer. HIFLD has historically published on the order of
55,000 to 80,000 substations.

**Core specification points degraded:**
- §7.8 candidate filtering — *"within a configured distance of a substation"*
- §7.9 grid proximity — *"distance to nearest HIFLD substation, plus voltage class"*

Per directive D8, **no substitute has been adopted.** Live HIFLD transmission lines
remain available (52,244 features), but line proximity is a *weaker* proxy than
substation proximity, and adopting it would make the directive D6 language constraints
more important, not less. Tracked as assumption **A-0.9**, to be resolved before Phase 4.

### 2.2 Block-level population weights are constructible, not ready-made

| Product | Status | Measured |
|---|---|---|
| `CenPop2020` tract centroids | confirmed | 1,505 Minnesota tracts |
| `CenPop2020` block group centroids | confirmed | 4,706 Minnesota block groups |
| `CenPop2020` **block** centroids | **unavailable** | HTTP 404; the directory has no `block/` |
| TIGER `TABBLOCK20` (geometry + `INTPTLAT`/`INTPTLON`) | confirmed | 147,565,957 bytes, Minnesota |
| 2020 P.L. 94-171 block population, keyless bulk | confirmed | 29,625,918 bytes, Minnesota |

§7.5 permits *"population-weighted centroids **or** block-level allocation"*, while §7.6
requires *"block-level population weights, not area weights"*. The finest ready-made
population-weighted product stops at block group. Genuine block-level weighting must be
built from TIGER blocks joined to P.L. 94-171 block population. Both paths are free.
Which one is taken is a Phase 2 decision; assumption **A-0.6**.

### 2.3 `cejst_archive` — live host gone, archive works

Neither `screeningtool.geoplatform.gov` nor `static-data-screeningtool.geoplatform.gov`
has a DNS record. The CEJST v2.0 communities CSV (45,316,831 bytes, 136 columns) was
retrieved through the Internet Archive. Consistent with §8: Executive Order 14008 was
revoked on 20 January 2025, so this may appear only as an archived historical equity
classification, vintage-labelled. Dependence on a third-party archive is a single point
of failure; a local mirror should be taken before Phase 6. Assumption **A-0.10**.

### 2.4 `hifld_transmission_service` — live service and seed file disagree

| Extract | Features |
|---|---|
| Delivered seed GeoJSON | 94,216 |
| Live HIFLD feature service | 52,244 |

A difference of 41,972 features. The publisher documents no reason. Assumption
**A-0.8**; whichever is used must be labelled with which extract it is.

---

## 3. Corrections to delivered project material

Two statements in the supplied setup material are no longer true. Neither is a
specification change; both are facts about the outside world that moved.

| Where | Says | Actually |
|---|---|---|
| `SETUP.md` §3 | Get the NREL key at `developer.nrel.gov/signup` | `developer.nrel.gov` has no DNS record. NREL's developer network moved to **`developer.nlr.gov`**; the old domain was retired on 29 May 2026. |
| `SETUP.md` §3 | Census key is "optional (bulk download works without)" | True of the bulk path only. The **API** path now returns a *Missing Key* page without a key. |

A third discrepancy concerns a domain rule and is escalated separately, not corrected
here: `CLAUDE.md` rule **G9** and `data/seed/MANIFEST.md` both state Oregon reports
6,436 EV registrations; the delivered file records **64,361**. See
`docs/reports/PLAN_CHANGE_0.md`.

Two smaller documentation discrepancies, recorded but not escalated:

- `data/seed/MANIFEST.md` states `ev_launch_data.csv` has 90 data rows; it parses to 91.
- `SETUP.md` §1 and `MANIFEST.md` refer to seed filenames in underscore form
  (`alt_fuel_stations__Dec_11_2024_.csv`); the delivered files use spaces and
  parentheses (`alt_fuel_stations (Dec 11 2024).csv`). Raw filenames were preserved
  exactly as delivered; canonical identifiers are mapped in
  `pipeline/discovery/seed_inventory.py`.

---

## 4. Core model data paths

Every model named in `CLAUDE.md` section 7, and whether Phase 0 established a path.

| Model | Primary source | Status | Fallback | Verdict |
|---|---|---|---|---|
| §7.1 Supply | `afdc_charging_units`, `afdc_stations` | confirmed / gated on quota | Dec 2024 seed snapshot | **Path established.** Rung-1 power coverage measured at 88.11% port-weighted on public + operational supply. |
| §7.2 Home charging | `nrel_home_charging` | confirmed | none | **Fallback path triggered.** The shares are a parametric scenario surface, not current values, so home charging is excluded from the primary siting objective and ships as a labelled exploratory index. |
| §7.3 Demand | `census_acs_bulk`, 14 Atlas states, `wa_ev_population`, seed IL and MN | confirmed | ACS API | **Path established.** 16 distinct states with sub-state registration data. |
| §7.3 Reconciliation | `afdc_state_ev_registrations_{2016..2025}` | confirmed | seed 2023 file | **Path established**, including at the 2020/2021/2022 backtest cutoffs. |
| §7.4 Uncertainty | derived from the above | n/a | n/a | Inputs available. |
| §7.5 Access | `census_cenpop_blockgroup`, `census_tiger_blocks`, `census_pl94171_blocks` | confirmed | tract centroids | **Path established**, but block-level weighting must be constructed (§2.2). |
| §7.6 Allocation | as §7.5 | confirmed | block group centroids | As above. |
| §7.8 Siting | `hifld_substations` for candidate filtering | **degraded** | transmission proximity, weaker | **Not established.** See §2.1 and A-0.9. |
| §7.9 Grid proximity | `hifld_substations` | **degraded** | transmission proximity, weaker | **Not established.** See §2.1 and A-0.9. |
| §7.10 Forecast (Ext) | `seed_il_county_ev_monthly_panel` | confirmed | none | Path established: 84 monthly observations, 2017-11 to 2024-11. |
| §7.11 Economics (Opt) | `eia_prices_api` | gated | `eia_prices_bulk`, confirmed | Path established via the keyless bulk file. |
| §8 Equity | `census_acs_bulk` primary; `cejst_archive` overlay | confirmed | none | Path established; the overlay is archive-dependent (§2.3). |
| §10.2 Deployment alignment | AFDC vintages, `fhwa_traffic` | confirmed / landing page only | none | **Partially established.** No machine-retrievable FHWA dataset URL was found; must be resolved before Phase 5. Assumption A-0.11. |

`egrid` is confirmed and reachable but **no model in section 7 consumes it.** It appears
in the section 3 repository layout with no declared downstream consumer. Recorded, not
resolved; raised as an open question in the Phase 0 report.

---

## 5. Rate limits, measured

| Source | Advertised | Observed |
|---|---|---|
| AFDC on `DEMO_KEY` | not stated | **10 requests per window**, `retry-after` 78,590 s |
| Census bulk (`www2.census.gov`) | none | No throttling across 8 requests |
| Atlas EV Hub | none | No throttling across 14 requests |
| AFDC registration pages | none | No throttling across 10 sequential requests |
| ArcGIS feature services | `maxRecordCount` 2000 per query | No throttling |
| EIA API | n/a | 403 without a key |

A separate behavioural finding: several hosts advertise `accept-ranges: bytes` and then
ignore a `Range` request header, answering HTTP 200 with the whole file. A first probe
implementation that trusted `Range` downloaded 3.3 GB. The probe now bounds transfers by
streaming and cutting off locally, which is robust whatever the server does.
