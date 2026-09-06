# Phase 6 UX pass — before and after

Captured at 1440×900 from the production static export, same data, same build pipeline.

| View | Before | After |
|---|---|---|
| EV demand (was "National Overview") | `before-national.png` | `after-national.png` |
| Charging gaps (was "Access & Equity") | `before-access.png` | `after-access.png` |
| Plan locations (was "Siting Studio") | `before-studio.png` | `after-studio.png` |
| How it works (was "Methodology & Validation") | `before-methodology.png` | `after-methodology.png` |

The "before" set is commit `4f95a4f`, immediately after the rendering defect was fixed and
before any UX work. Nothing about the model, the artifacts or the thresholds differs between
the two sets.

## Map explorability pass — 2026-09-05

A second set, captured the same way by `web/scripts/shots.mjs`, showing the interactions
the earlier set could not have: before this pass none of the three views answered a hover,
and the charging-gaps view had no map at all.

| File | Shows |
|---|---|
| `explore-national-hover.png` | Hovering a grouped area on the EV demand map. The card names it "Turner County, SD and 2 nearby counties", leads with the selected metric, and reports the anchored share rather than a tier the pipeline did not publish for a group. |
| `explore-gaps-map.png` | The charging-gaps map, which did not previously exist. The threshold now moves geography, not only four figures. |
| `explore-gaps-pinned.png` | A pinned gap card: people beyond the threshold, affected lower-income population, average distance, `▸ Technical details`, and the hand-off to the siting studio for that state. |
| `explore-studio-row-hover.png` | Hovering table row 3 highlights the row and enlarges map marker ③; the card names the same area with the same rank. Map and table are one list. |

Nothing about the model, the artifacts or the thresholds differs between any of these sets.

## Layer hierarchy and geography pass (2026-09-06)

Captured by `web/scripts/shots-geo.mjs` from the production static export, 1440×900,
headless Chrome on the host GPU. The `geo-before-*` images were produced by building commit
`011528c` in a separate git worktree against the identical published data, so the
comparison is between two builds rather than between a build and a description.

| File | Zoom | What to look for |
|---|---|---|
| `geo-before-demand-national.png` | 3.4 | City labels washed out; no state borders |
| `geo-before-demand-local.png` | 9.5 | Seattle metro with **neither I-5 nor I-405 visible** |
| `geo-before-gaps-people.png` | 3.4 | 100 dots; the other 20,451 gap areas absent |
| `geo-demand-national.png` | 3.4 | Labels and state borders read through the surface |
| `geo-demand-state.png` | 6.2 | Washington; cells resolve, county context remains |
| `geo-demand-local.png` | 9.5 | Highways crisp through an 0.88-opacity surface |
| `geo-demand-washington.png` | fit | U.S. → Washington; 401 drawn cells |
| `geo-demand-texas.png` | fit | Washington → Texas; 1,303 drawn cells |
| `geo-demand-reset.png` | fit | Reset to U.S.; 4,012 drawn cells |
| `geo-gaps-all.png` | 3.4 | The whole gap universe |
| `geo-gaps-people-national.png` | 3.4 | Highlighted 100 over grey context, ranked nationally |
| `geo-gaps-people-washington.png` | fit | The same view ranked within Washington |
