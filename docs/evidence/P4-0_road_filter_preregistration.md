# Pre-registration — the Core road-proximity candidate filter

**Written and committed BEFORE any candidate set, frontier or portfolio was recomputed
with road data.** The threshold and the road classes are fixed here so they cannot be
chosen after seeing which value produces a convenient candidate count.

---

## 1. Why this exists

Phase 4 shipped with a resident-population filter standing in for the road-proximity filter
CLAUDE.md §7.8 specifies, on the stated grounds that "no road-network dataset was
retrieved". External review established that **this premise was wrong**: the U.S. Census
Bureau publishes TIGER/Line road products, free and keyless, including current national and
per-state artifacts.

The error was mine, and it matters more than a missing feature would: a population filter is
not a road filter, and presenting one as a stand-in for the other overstated what the
candidate set represented. Resident population is **not** a substitute for road proximity
and is not presented as one from here on.

## 2. The source

| Field | Value |
|---|---|
| Publisher | U.S. Census Bureau, TIGER/Line |
| Product | **Primary and Secondary Roads**, per state |
| Vintage | **2024** |
| Endpoint | `https://www2.census.gov/geo/tiger/TIGER2024/PRISECROADS/tl_2024_{state_fips}_prisecroads.zip` |
| Auth | none |
| Cost | free, no quota, no key (D4) |
| Format | ESRI Shapefile, `LineString`, EPSG:4269 (NAD83) |
| Cached | yes, per state, for deterministic offline rebuilds |

## 3. Road classes included

Two MTFCC classes, and only these:

| MTFCC | Class | Included |
|---|---|---|
| **S1100** | Primary Road — limited-access highways | **yes** |
| **S1200** | Secondary Road — main arteries, US/state highways | **yes** |
| S1400 | Local neighborhood road, rural road, city street | no |
| S1500, S1630, S1640, S1710, S1720, S1730, S1740, S1750, S1780, S1820, S1830 | service drives, ramps, alleys, walkways, tracks, private roads | no |

**Why arterials only.** A public charging site needs arterial access: a driver has to be
able to reach it and turn into it from a road that carries through traffic. At H3
resolution 6 — 38.2 km² per cell — almost every inhabited cell in the country contains
*some* local street, so including S1400 would make the filter a near no-op and would not
represent the siting constraint the specification is asking for. Restricting to primary and
secondary roads makes the filter mean what it says.

**This is a modelling choice with a consequence**: a cell served only by local streets is
excluded even though something could physically be built there. That is recorded as a
limitation, not hidden.

## 4. The threshold, fixed before any result was seen

> **A candidate cell qualifies when a primary or secondary road passes within
> `road_proximity_km = 5.0` kilometres of the cell's centroid.**

**Derivation, from grid geometry rather than from an outcome.** An H3 resolution-6 cell has
a measured area of 38.2 km² and an edge of ~3,834 m. For a regular hexagon of edge *a* the
inradius is `a·√3/2`, so a cell's centroid sits up to **~3,320 m** from its own boundary. A
road lying just outside the cell is therefore already ~3.3 km from the centroid.

A threshold below ~3.3 km would exclude cells whose nearest arterial is immediately outside
their own boundary, which is not the intent. **5.0 km** admits a cell whose arterial lies
within the cell or roughly one cell-width beyond it, and excludes a cell more than about a
cell-width from any arterial.

**A sensitivity curve across 1–20 km ships with the result**, in the same spirit as the
access-threshold curve §7.5 requires, so the choice is visible as a choice rather than
presented as a finding.

## 5. Distance method

Road geometries are LineStrings. Their **vertices** are indexed into H3 resolution-6 cells
once. For a candidate cell, the search gathers road vertices in `grid_disk(cell, 2)` — two
rings, ~7.7 km, comfortably beyond the 5.0 km threshold — and takes the minimum **haversine**
distance from the cell centroid to any of them.

**Known approximation, stated in advance.** Distance is measured to road *vertices*, not to
the nearest point on a road *segment*. A long straight segment between two distant vertices
could pass close to a cell whose centroid is far from either endpoint. TIGER road geometries
are densely vertexed — the first Washington feature carries 42 vertices — so the error is
small, but it is an approximation and it is recorded as assumption **A-4.6** rather than
described as exact.

## 6. Failure behaviour (D8)

If a state's road artifact is missing or unreadable, candidate construction **raises**,
naming the artifact. It does not silently pass every cell through, and it does not fall back
to the population filter.

A caller may explicitly opt into degraded operation, in which case every affected cell is
recorded under a named exclusion reason and the degradation appears in the published
artifact. **Degradation is never the default and is never silent.**

## 7. What does not change

- **No national substation-proximity filter is reintroduced.** §7.9 stands: Phase 0 located
  no authoritative national substation dataset, Core siting functions without one, and no
  cell is excluded for lacking grid data.
- Transmission proximity remains unused; if it ever ships it is a labelled contextual
  proximity proxy and never an interconnection constraint (D6).
- The ε sweep keeps its eight levels and is **not** extended above the empirically
  achievable secondary-objective ceiling. The shallow tradeoff is a result, not a defect.
- The uninhabited filter is retained **on its own merits** — a cell with no residents is not
  a siting candidate — but it is no longer described as standing in for road proximity,
  because it never was one.
