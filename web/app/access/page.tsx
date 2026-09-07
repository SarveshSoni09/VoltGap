"use client";

import { cellToLatLng, cellToParent } from "h3-js";
import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";

import { CardAnchor } from "../../components/CardAnchor";
import { Disclosure } from "../../components/Disclosure";
import { FeatureCard } from "../../components/FeatureCard";
import {
  aggregateGaps, gapAtThreshold, gapCells, loadAccessTable,
} from "../../lib/data/access";
import { cellBoundaries, type Boundaries } from "../../lib/data/geometry";
import { loadHexTable } from "../../lib/data/hexes";
import { NATIVE_RESOLUTION, displayResolution } from "../../lib/aggregate";
import { STATE_NAMES } from "../../lib/data/states";
import type { ColumnTable } from "../../lib/data/table";
import { placeName } from "../../lib/reasons";
import {
  boundsOf, geographyLabel, NATIONAL, nameByFips, scopedLabel, statesPresent, US_BOUNDS,
  type Bounds, type StateOption,
} from "../../lib/geography";
import { perVertexColors } from "../../lib/render";
import {
  analyticalOpacity, cellColor, formatCompact, formatCount, quantileScale, rampColor,
} from "../../lib/scales";
import { CEJST_NOTE } from "../../lib/vocabulary";

const HexMap = dynamic(() => import("../../components/HexMap"), {
  ssr: false,
  loading: () => <div className="loading">Loading map…</div>,
});

const THRESHOLDS = [1, 2, 3, 5, 8, 10, 16.1, 20, 25, 30, 40, 50];

/**
 * Ways of looking at the same gap areas — never a new score.
 *
 * Each of these sorts and trims the areas the threshold already selected, using a
 * quantity that is published in the data dictionary. Nothing here computes a hidden
 * composite: "high impact" means "most people beyond the distance you set", stated in
 * those words, and a reader can reproduce every list from the exported columns.
 */
const HIGHLIGHT_LIMIT = 100;

const LENSES = [
  {
    id: "all", label: "All gap areas", base: "All gap areas",
    // Stated as the predicate, because that is all it is.
    describe: () => "Every area with people beyond the distance you set.",
    sort: (a: Ranked, b: Ranked) => b.population - a.population,
  },
  {
    id: "people", label: "Most people affected", base: "Most people affected",
    describe: (cut: number) =>
      `The ${HIGHLIGHT_LIMIT} areas with the largest population beyond that distance — ` +
      `every highlighted area holds at least ${Math.round(cut).toLocaleString()} people.`,
    sort: (a: Ranked, b: Ranked) => b.population - a.population,
    limit: HIGHLIGHT_LIMIT,
    value: (c: Ranked) => c.population,
  },
  {
    id: "equity", label: "Lower-income households", base: "Most lower-income people affected",
    describe: (cut: number) =>
      `The ${HIGHLIGHT_LIMIT} areas with the most affected people in lower-income ` +
      `households — at least ${Math.round(cut).toLocaleString()} such people each.`,
    sort: (a: Ranked, b: Ranked) => b.equity - a.equity,
    limit: HIGHLIGHT_LIMIT,
    value: (c: Ranked) => c.equity,
  },
  {
    id: "distance", label: "Furthest from charging", base: "Furthest from charging",
    describe: (cut: number) =>
      `The ${HIGHLIGHT_LIMIT} populated areas furthest from public fast charging — ` +
      `every highlighted area is at least ${cut.toFixed(0)} km away.`,
    sort: (a: Ranked, b: Ranked) => b.km - a.km,
    limit: HIGHLIGHT_LIMIT,
    value: (c: Ranked) => c.km,
  },
] as const;

interface Ranked {
  readonly h3_index: string;
  readonly population: number;
  readonly equity: number;
  readonly km: number;
  readonly points: number;
  readonly state_fips: string;
  readonly county_name: string;
  readonly state_code: string;
}

/**
 * Gap areas the current lens is not pointing at.
 *
 * Muted and desaturated so it reads as background, but deliberately not invisible: these
 * areas are 94% of the affected population, and a page that erased them would tell the
 * reader the problem is 100 places wide.
 */
const CONTEXT_COLOR: [number, number, number, number] = [150, 142, 168, 90];

export default function AccessAndEquity() {
  const [points, setPoints] = useState<ColumnTable | null>(null);
  const [hexes, setHexes] = useState<ColumnTable | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [threshold, setThreshold] = useState(16.1);
  const [lens, setLens] = useState<string>("all");
  const [showCejst, setShowCejst] = useState(false);
  const [boundaries, setBoundaries] = useState<Boundaries | null>(null);
  const [hovered, setHovered] = useState<number | null>(null);
  const [pinned, setPinned] = useState<number | null>(null);
  const [cursor, setCursor] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(3.4);
  /**
   * The geography under examination. Same semantics as the National Overview: selecting a
   * state filters the analysis, it does not only move the camera.
   *
   * For this page that choice has a consequence the other page does not have. The three
   * specialised lenses are RANKINGS, and a ranking's scope is part of its meaning — the
   * national hundred furthest areas are 71 in Alaska, 17 in Montana, 10 in Hawaii and 2 in
   * North Dakota, so a reader who selected Washington and kept a national ranking would be
   * shown nothing at all. Rankings are therefore recomputed within the selected state, and
   * the interface says which geography it ranked within.
   */
  const [state, setState] = useState<string>(NATIONAL);
  const [fit, setFit] = useState<Bounds | null>(null);
  /**
   * Where the reader asked to be taken, from the card of an area they clicked.
   *
   * Distinct from `fit`, which frames a whole geography. This centres one area and leaves
   * the geography, the distance threshold and the selected view exactly as they were.
   */
  const [focus, setFocus] =
    useState<{ longitude: number; latitude: number; zoom: number } | null>(null);

  useEffect(() => {
    loadAccessTable().then(setPoints).catch((e: Error) => setError(e.message));
    // Only for the county labels: the access artifact carries no place name, and an H3
    // index is not an answer to "where is this".
    loadHexTable().then(setHexes).catch(() => setHexes(null));
  }, []);

  const placeByCell = useMemo(() => {
    if (hexes === null) return new Map<string, { county: string; state: string }>();
    const index = hexes.strs("h3_index");
    const county = hexes.strs("county_name");
    const state = hexes.strs("state_code");
    const out = new Map<string, { county: string; state: string }>();
    for (let i = 0; i < hexes.length; i += 1) {
      out.set(index[i] ?? "", { county: county[i] ?? "", state: state[i] ?? "" });
    }
    return out;
  }, [hexes]);

  const stateOptions = useMemo<StateOption[]>(() => {
    if (hexes === null) return [];
    return statesPresent(hexes.strs("state_fips"), hexes.strs("state_code"));
  }, [hexes]);
  const selectedState = useMemo(
    () => stateOptions.find((o) => o.fips === state) ?? null,
    [stateOptions, state],
  );

  /** FIPS to name for every state in the data, not only the six the frontier covers. */
  const stateName = useMemo(() => nameByFips(stateOptions), [stateOptions]);

  const stateBounds = useMemo(() => {
    const out = new Map<string, Bounds>();
    if (hexes === null) return out;
    const fips = hexes.strs("state_fips");
    const lon = hexes.nums("longitude");
    const lat = hexes.nums("latitude");
    const points_ = new Map<string, { longitude: number; latitude: number }[]>();
    for (let i = 0; i < hexes.length; i += 1) {
      const key = fips[i] ?? "";
      if (key === "") continue;
      let list = points_.get(key);
      if (list === undefined) { list = []; points_.set(key, list); }
      list.push({ longitude: lon[i] ?? 0, latitude: lat[i] ?? 0 });
    }
    for (const [key, list] of points_) {
      const b = boundsOf(list);
      if (b !== null) out.set(key, b);
    }
    return out;
  }, [hexes]);

  // Both halves of every ratio describe the selected geography. See gapAtThreshold.
  const summary = useMemo(
    () => (points === null
      ? null
      : gapAtThreshold(points, threshold, "km_to_nearest_dcfc_site",
                       selectedState?.fips)),
    [points, threshold, selectedState],
  );

  // The map and the figures above come from ONE pass over the same points at the same
  // threshold, so they cannot disagree. tests/access.test.ts asserts the equality.
  const cells = useMemo<Ranked[]>(() => {
    if (points === null) return [];
    return gapCells(points, threshold, "km_to_nearest_dcfc_site",
                    selectedState?.fips).map((c) => {
      const place = placeByCell.get(c.h3_index);
      return {
        ...c,
        county_name: place?.county ?? "",
        state_code: place?.state ?? "",
      };
    });
  }, [points, threshold, placeByCell, selectedState]);

  const resolution = displayResolution(zoom);

  /**
   * What is drawn, and which of it the lens is pointing at.
   *
   * The three specialised lenses each pick 100 areas. The audit in the Phase 6 report
   * measured what that means: 100 of 20,551 populated gap areas, 0.49% of them, and the
   * three lenses together cover 234 areas — so 98.9% of the gap, holding 94% of the
   * affected population, belongs to none of them. Drawing only the 100 made the rest of
   * the problem disappear from a page whose subject is the problem.
   *
   * So the whole gap universe is always drawn, and the lens changes which part of it is
   * emphasised. The reader can see that the highlighted areas are a subset of something
   * much larger, which is the true relationship.
   *
   * Highlighted areas are appended last so they paint above the context, and the cutoff
   * value is returned so the interface can state the rule rather than assert "most".
   */
  const drawn = useMemo(() => {
    const spec = LENSES.find((l) => l.id === lens) ?? LENSES[0];
    // Uninhabited areas are counted in the figures — they really are beyond the distance —
    // but they are not shaded on a map whose colour means "people affected".
    const populated = cells.filter((c) => c.population > 0);
    const sorted = [...populated].sort(spec.sort);
    const limit = "limit" in spec ? spec.limit : undefined;
    // The lens picks WHICH areas, then display grouping decides how they are drawn, in
    // that order: trimming after grouping would show the top hundred groups rather than
    // the top hundred areas, which is a different answer.
    const picked = limit === undefined ? sorted : sorted.slice(0, limit);
    const highlighted = new Set(picked.map((c) => c.h3_index));
    const value = "value" in spec ? spec.value : undefined;
    const last = picked[picked.length - 1];
    const cutoff = value !== undefined && last !== undefined ? value(last) : 0;

    const group = (list: readonly Ranked[]) => {
      const dominant = new Map<string, Ranked>();
      for (const cell of list) {
        const parent = resolution >= NATIVE_RESOLUTION
          ? cell.h3_index
          : cellToParent(cell.h3_index, resolution);
        const held = dominant.get(parent);
        if (held === undefined || cell.population > held.population) {
          dominant.set(parent, cell);
        }
      }
      return aggregateGaps(list, resolution).map((g) => ({
        ...g,
        county_name: dominant.get(g.h3_index)?.county_name ?? "",
        state_code: dominant.get(g.h3_index)?.state_code ?? "",
      }));
    };

    // Grouped separately so a highlighted area is never merged into a context group and
    // hidden by it. At native resolution the two sets are simply disjoint.
    const context = limit === undefined
      ? []
      : group(populated.filter((c) => !highlighted.has(c.h3_index)));
    const focus = group(picked);
    return {
      context,
      focus,
      cells: [...context, ...focus],
      firstFocus: context.length,
      cutoff,
      pickedCount: picked.length,
      populatedCount: populated.length,
      pickedPopulation: picked.reduce((n, c) => n + c.population, 0),
      populatedPopulation: populated.reduce((n, c) => n + c.population, 0),
    };
  }, [cells, lens, resolution]);

  const active = drawn.cells;

  const curve = useMemo(
    () =>
      points === null
        ? []
        : THRESHOLDS.map((t) => ({ t, ...gapAtThreshold(points, t) })),
    [points],
  );

  /** The ring drawn around whichever area the card is describing. */
  const outlined = useMemo(() => {
    const i = pinned ?? hovered;
    const cell = i === null ? undefined : active[i];
    return cell === undefined ? [] : [cell.h3_index];
  }, [pinned, hovered, active]);

  /** Which states carry the most of this gap. Answers "where am I looking" before zooming. */
  const byState = useMemo(() => {
    const totals = new Map<string, number>();
    for (const cell of drawn.focus) {
      totals.set(cell.state_fips, (totals.get(cell.state_fips) ?? 0) + cell.population);
    }
    return [...totals.entries()].sort((a, b) => b[1] - a[1]).slice(0, 4);
  }, [drawn]);

  useEffect(() => {
    setHovered(null);
    setPinned(null);
    if (active.length === 0) {
      setBoundaries(null);
      return;
    }
    let cancelled = false;
    cellBoundaries(active.map((c) => c.h3_index)).then((b) => {
      if (!cancelled) setBoundaries(b);
    });
    return () => { cancelled = true; };
  }, [active]);

  /**
   * Two treatments in one buffer: context areas in a flat, desaturated grey-purple, and
   * the lens's own areas on the full colour ramp.
   *
   * One layer rather than two, because the reader is looking at one thing — the gap — and
   * a second polygon layer would double the geometry upload for a distinction that is
   * four bytes per vertex.
   *
   * The quantile breaks are computed over the HIGHLIGHTED areas only. Scaling them against
   * the whole gap would push the top hundred into one indistinguishable colour, which is
   * the opposite of what the lens was selected to show.
   */
  const colors = useMemo<Uint8Array | null>(() => {
    if (boundaries === null || active.length === 0) return null;
    const first = drawn.firstFocus;
    const scale = quantileScale(drawn.focus.map((c) => c.population));
    return perVertexColors(boundaries, (cell) => {
      if (cell < first) return CONTEXT_COLOR;
      return cellColor(scale(active[cell]?.population ?? 0));
    });
  }, [boundaries, active, drawn]);

  if (error !== null) return <div className="error">{error}</div>;
  const maxGap = curve.length > 0 ? Math.max(...curve.map((c) => c.population)) : 1;
  const lensSpec = LENSES.find((l) => l.id === lens) ?? LENSES[0];
  const shownIndex = pinned ?? hovered;
  const shown = shownIndex === null ? null : (active[shownIndex] ?? null);

  return (
    <div className="view">
      <aside className="sidebar">
        <div className="lede">
          <h1>Where is charging access weakest?</h1>
          <p>
            How many people live far from public fast charging, where they are, and how
            that changes with the distance you consider &ldquo;far&rdquo;.
          </p>
        </div>

        <div className="field">
          <label htmlFor="geography">Geography</label>
          <div className="geo-row">
            <select
              id="geography"
              value={state}
              onChange={(e) => {
                const next = e.target.value;
                setState(next);
                const option = stateOptions.find((o) => o.fips === next) ?? null;
                setFit(option === null
                  ? US_BOUNDS : stateBounds.get(option.fips) ?? US_BOUNDS);
              }}
            >
              <option value={NATIONAL}>United States</option>
              {stateOptions.map((o) => (
                <option key={o.fips} value={o.fips}>{o.name}</option>
              ))}
            </select>
            {selectedState !== null && (
              <button
                type="button"
                className="geo-reset"
                onClick={() => { setState(NATIONAL); setFit(US_BOUNDS); }}
              >
                Reset to U.S.
              </button>
            )}
          </div>
          <p className="hint">
            Every figure and ranking on this page describes{" "}
            {geographyLabel(selectedState)}. The distance you set is kept when you change
            geography.
          </p>
        </div>

        <div className="field">
          <label htmlFor="threshold">
            Count people further than {threshold.toFixed(1)} km from fast charging
          </label>
          <input
            id="threshold"
            type="range"
            min={1}
            max={50}
            step={0.5}
            value={threshold}
            onChange={(e) => setThreshold(Number(e.target.value))}
          />
        </div>

        <div className="field">
          <label>Which areas to show</label>
          <div className="segmented">
            {LENSES.map((l) => (
              <button
                key={l.id}
                className={lens === l.id ? "on" : ""}
                onClick={() => setLens(l.id)}
              >
                {l.label}
              </button>
            ))}
          </div>
          <p className="hint">{lensSpec.describe(drawn.cutoff)}</p>
          {lens !== "all" && (
            <p className="subset">
              These <strong>{formatCount(drawn.pickedCount)}</strong> areas are{" "}
              {(drawn.pickedCount / Math.max(1, drawn.populatedCount) * 100).toFixed(1)}%
              of the <strong>{formatCount(drawn.populatedCount)}</strong> gap areas in{" "}
              {geographyLabel(selectedState)}, and hold{" "}
              {(drawn.pickedPopulation / Math.max(1, drawn.populatedPopulation) * 100)
                .toFixed(1)}% of the affected people. The rest stay on the map in grey.
            </p>
          )}
        </div>

        {summary !== null && (
          <div className="figures">
            <div className="figure">
              <div className="n">{formatCompact(summary.population)}</div>
              <div className="l">
                people in {geographyLabel(selectedState)} that far from fast charging
              </div>
            </div>
            <div className="figure">
              <div className="n">{(summary.share * 100).toFixed(1)}%</div>
              <div className="l">
                of {selectedState === null
                  ? "the US population"
                  : `${selectedState.name}'s population`}
              </div>
            </div>
            <div className="figure">
              <div className="n">{formatCompact(summary.equityPopulation)}</div>
              <div className="l">of them in lower-income households</div>
            </div>
            <div className="figure">
              <div className="n">{formatCompact(summary.points)}</div>
              <div className="l">neighbourhoods affected</div>
            </div>
          </div>
        )}

        {selectedState !== null && STATE_NAMES[selectedState.fips] !== undefined && (
          <a
            className="handoff"
            href={`/studio/?state=${selectedState.fips}&from=gaps&threshold=${threshold.toFixed(1)}`}
          >
            Explore candidate areas in {selectedState.name} →
          </a>
        )}

        <Disclosure question="What counts as &ldquo;far&rdquo;?">
          <p>
            Distance here is straight-line, not driving distance, so real journeys are
            longer. The number of people actually beyond this drive distance is at least
            as large as shown, never smaller.
          </p>
          <p>
            It measures public <strong>fast</strong> charging only. Slower Level 2 charging
            is not counted, so this is not a picture of all charging.
          </p>
        </Disclosure>

        <Disclosure question="How are these areas ranked?">
          <p>
            By quantities that are already published: population beyond the distance you
            set, how many of those people are in lower-income households, and the
            population-weighted distance. Sorting and trimming that list is all these
            buttons do.
          </p>
          <p>
            There is no combined score behind them, and no area is ranked by anything you
            cannot see in the exported data.
          </p>
        </Disclosure>

        <Disclosure question="Who is counted as lower-income?" tone="quiet">
          <p>
            One named measure from the American Community Survey: people in households
            with income below $35,000 a year. It is a single indicator, not a combined
            score of disadvantage, so it is narrower than the phrase might suggest.
          </p>
        </Disclosure>

        <Disclosure question="Historical equity overlay" tone="quiet">
          <p>{CEJST_NOTE}</p>
          <button onClick={() => setShowCejst(!showCejst)}>
            {showCejst ? "Hide" : "Show"} it anyway
          </button>
          {showCejst && (
            <p style={{ marginTop: "0.5rem" }}>
              Displayed for historical context only. It reflects a framework that is no
              longer in force.
            </p>
          )}
        </Disclosure>

        <Disclosure question="How the answer changes with the distance you pick">
          <p>
            There is no single correct definition of &ldquo;too far&rdquo;, so the whole
            range is shown. Every row is recalculated from the underlying neighbourhood
            distances rather than interpolated.
          </p>
          <table>
            <thead>
              <tr>
                <th className="num">Distance</th>
                <th className="num">People</th>
                <th style={{ width: "40%" }} />
              </tr>
            </thead>
            <tbody>
              {curve.map((point) => (
                <tr key={point.t}>
                  <td className="num">{point.t.toFixed(1)} km</td>
                  <td className="num">{formatCompact(point.population)}</td>
                  <td>
                    <div
                      style={{
                        height: 8,
                        borderRadius: 2,
                        background:
                          Math.abs(point.t - threshold) < 0.25
                            ? "var(--accent)"
                            : "var(--accent-dim)",
                        width: `${(point.population / maxGap) * 100}%`,
                      }}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Disclosure>
      </aside>

      <div className="canvas">
        {points === null ? (
          <div className="loading">Loading block-group access points…</div>
        ) : (
          <>
            <div className="mapsummary">
              <div>
                {/* The scope is in the heading because it is part of the claim. */}
                <strong>{scopedLabel(lensSpec.base, selectedState)}</strong> ·{" "}
                <strong>{formatCompact(
                  drawn.focus.reduce((n, c) => n + c.population, 0))}</strong> people
                beyond {threshold.toFixed(1)} km
                {lens !== "all" && (
                  <> · of <strong>{formatCompact(drawn.populatedPopulation)}</strong> in
                  all gap areas</>
                )}
              </div>
              <div className="places">
                {byState.length === 0
                  ? "No areas at this distance."
                  : selectedState !== null
                  ? `All within ${selectedState.name}. Hover any area for detail.`
                  : `Mostly in ${byState
                      .map(([fips, pop]) =>
                        `${stateName.get(fips) ?? "an unnamed state"} (${
                          formatCompact(pop)})`)
                      .join(", ")}`}
              </div>
            </div>
            <HexMap
              boundaries={boundaries}
              colors={colors}
              fillOpacity={analyticalOpacity(zoom)}
              fitBounds={fit}
              focus={focus}
              outlineCells={outlined}
              onZoom={setZoom}
              onHoverCell={(index, x, y) => {
                setHovered(index);
                setCursor({ x, y });
              }}
              onPickCell={setPinned}
            />
            {shown !== null && (
              <CardAnchor
                pinned={pinned !== null}
                x={cursor.x}
                y={cursor.y}
                onClose={() => setPinned(null)}
              >
                <FeatureCard
                  place={placeName(shown.county_name, shown.state_code) ?? "Unnamed area"}
                  primaryLabel={`People beyond ${threshold.toFixed(1)} km`}
                  primaryValue={formatCompact(shown.population)}
                  facts={[
                    { label: "In lower-income households",
                      value: formatCompact(shown.equity) },
                    { label: "Average distance", value: `${shown.km.toFixed(0)} km` },
                    { label: "Neighbourhoods", value: String(shown.points) },
                  ]}
                  technical={
                    pinned === null
                      ? undefined
                      : [
                          { label: "H3 cell", value: shown.h3_index },
                          { label: "Measure",
                            value: "straight-line to public DC fast charging" },
                        ]
                  }
                  actions={
                    pinned === null ? undefined : (
                      <>
                        <button
                          type="button"
                          className="fcard-action"
                          onClick={() => {
                            const [lat, lng] = cellToLatLng(shown.h3_index);
                            setFocus({
                              longitude: lng, latitude: lat,
                              zoom: Math.max(zoom, 8),
                            });
                          }}
                        >
                          Zoom to this area
                        </button>
                        {STATE_NAMES[shown.state_fips] !== undefined && (
                          <a
                            className="fcard-action"
                            href={`/studio/?state=${shown.state_fips}&from=gaps&threshold=${threshold.toFixed(1)}`}
                          >
                            Plan locations in {STATE_NAMES[shown.state_fips]}
                          </a>
                        )}
                      </>
                    )
                  }
                />
              </CardAnchor>
            )}
            <div className="legend">
              <div>People beyond {threshold.toFixed(1)} km</div>
              <div className="scale">
                {Array.from({ length: 24 }, (_, i) => {
                  const [r, g, b] = rampColor(i / 23);
                  return <i key={i} style={{ background: `rgb(${r},${g},${b})` }} />;
                })}
              </div>
              <div className="ends">
                <span>fewer</span>
                <span>more</span>
              </div>
              <div className="swatches">
                {lens !== "all" && (
                  <span className="sw">
                    <i style={{ background: "rgba(150,142,168,0.55)" }} />
                    other gap areas — a much larger problem this view is a subset of
                  </span>
                )}
                <span className="sw">
                  <i className="hollow" />
                  within {threshold.toFixed(1)} km, or nobody lives here
                </span>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
