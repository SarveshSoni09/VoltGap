# Pre-registered decision rule — ZIP→tract allocation method

**Written and committed BEFORE any comparison result was computed.** Recorded so the
threshold for "materially outperforms" cannot be chosen after seeing which method wins.

## What is being compared

Washington's EV registration records carry **both** a postal ZIP Code and a 2020 Census
tract on the same observed vehicle row. Aggregating them gives, for each ZIP, the
*observed* distribution of EVs across the tracts that ZIP touches. Two candidate
allocation methods are scored against that observed distribution:

| Method | Weight basis | Source |
|---|---|---|
| **land_area** (incumbent) | ZCTA∩tract land area | Census 2020 ZCTA-to-tract relationship file, via a USPS ZIP → like-numbered ZCTA approximation |
| **hud_res_ratio** (candidate) | residential address ratio | HUD USER USPS ZIP Code Crosswalk, ZIP → tract, `res_ratio` |

**Washington is not national ground truth.** It is direct paired evidence for how well
each method reconstructs an observed EV-location distribution in one state.

## Primary metric

For each ZIP *z* with observed tract shares `o_z` and estimated shares `e_z`:

    TVD(z) = 0.5 * sum_t | o_z(t) - e_z(t) |

Total variation distance is used because it reads directly as **the fraction of EV mass
assigned to the wrong tract**. The headline figure is the **EV-count-weighted mean TVD**
across ZIPs, so a ZIP holding 4,000 EVs counts more than one holding 4.

## Secondary metrics (reported, not decisive)

Mean absolute error in tract shares; top-tract accuracy (does the method put the plurality
of EVs in the tract that actually holds it); conservation error; results stratified by
number of tracts per ZIP.

## Decision rule

Let `D = weighted_mean_TVD(land_area) - weighted_mean_TVD(hud_res_ratio)`.
"Materially outperforms" requires **both** conditions:

1. `|D| >= 0.05` — at least 5 percentage points of EV mass, and
2. the winning method has lower TVD on **at least 60%** of the ZIPs compared individually.

| Outcome | Action |
|---|---|
| HUD materially outperforms | **HUD becomes the preferred Phase 3 ZIP→tract method.** Land-area is retained as a documented degraded fallback; method provenance stays on every row |
| Land-area materially outperforms | Keep land-area; record HUD as tested and rejected, with evidence |
| Neither materially outperforms (`\|D\| < 0.05`) | Keep the incumbent (land-area) as default and record HUD as an available, validated alternative. No plan change |
| **Both** methods exceed a weighted mean TVD of **0.35** | Neither is acceptable for tract-level demand evidence. **Trigger `PLAN_CHANGE_3.md`** rather than continuing quietly |

## Scope limits fixed in advance

- ZIPs whose observed EV count is below **10** are excluded from the weighted mean: a
  share vector built on a handful of vehicles is noise, not evidence. They are still
  reported separately.
- Ratios are **not** silently renormalised. A ZIP whose `res_ratio` sums to zero
  (no residential addresses) is reported as unallocatable by that method, not rescued.
- This comparison does **not** by itself decide whether either method is good enough for
  national use. It decides which of the two is preferred, and whether either clears the
  acceptability floor.
