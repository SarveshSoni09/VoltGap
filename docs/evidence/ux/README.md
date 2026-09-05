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
