"use client";

import { cellToParent } from "h3-js";
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
import { perVertexColors } from "../../lib/render";
import { cellColor, formatCompact, quantileScale, rampColor } from "../../lib/scales";
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
const LENSES = [
  { id: "all", label: "All gap areas",
    hint: "Every area where people are beyond the distance you set.",
    sort: (a: Ranked, b: Ranked) => b.population - a.population },
  { id: "people", label: "Most people affected",
    hint: "The 100 areas with the largest population beyond that distance.",
    sort: (a: Ranked, b: Ranked) => b.population - a.population, limit: 100 },
  { id: "equity", label: "Lower-income households",
    hint: "The 100 areas with the most affected people in lower-income households.",
    sort: (a: Ranked, b: Ranked) => b.equity - a.equity, limit: 100 },
  { id: "distance", label: "Furthest from charging",
    hint: "The 100 populated areas furthest from public fast charging.",
    sort: (a: Ranked, b: Ranked) => b.km - a.km, limit: 100 },
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

  const summary = useMemo(
    () => (points === null ? null : gapAtThreshold(points, threshold)),
    [points, threshold],
  );

  // The map and the figures above come from ONE pass over the same points at the same
  // threshold, so they cannot disagree. tests/access.test.ts asserts the equality.
  const cells = useMemo<Ranked[]>(() => {
    if (points === null) return [];
    return gapCells(points, threshold).map((c) => {
      const place = placeByCell.get(c.h3_index);
      return {
        ...c,
        county_name: place?.county ?? "",
        state_code: place?.state ?? "",
      };
    });
  }, [points, threshold, placeByCell]);

  const resolution = displayResolution(zoom);

  const active = useMemo(() => {
    const spec = LENSES.find((l) => l.id === lens) ?? LENSES[0];
    // Uninhabited areas are counted in the figures — they really are beyond the distance —
    // but they are not shaded on a map whose colour means "people affected". 230 of the
    // 20,781 cells beyond 16.1 km nationally have no population.
    const sorted = cells.filter((c) => c.population > 0).sort(spec.sort);
    const limit = "limit" in spec ? spec.limit : undefined;
    // The lens picks WHICH areas, then display grouping decides how they are drawn, in
    // that order: trimming after grouping would show the top hundred groups rather than
    // the top hundred areas, which is a different answer.
    const picked = limit === undefined ? sorted : sorted.slice(0, limit);

    // A grouped area is named after the cell contributing the most affected people, so
    // the label points at where the number actually is.
    const dominant = new Map<string, Ranked>();
    for (const cell of picked) {
      const parent =
        resolution >= NATIVE_RESOLUTION
          ? cell.h3_index
          : cellToParent(cell.h3_index, resolution);
      const held = dominant.get(parent);
      if (held === undefined || cell.population > held.population) {
        dominant.set(parent, cell);
      }
    }
    return aggregateGaps(picked, resolution).map((group) => ({
      ...group,
      county_name: dominant.get(group.h3_index)?.county_name ?? "",
      state_code: dominant.get(group.h3_index)?.state_code ?? "",
    }));
  }, [cells, lens, resolution]);

  const curve = useMemo(
    () =>
      points === null
        ? []
        : THRESHOLDS.map((t) => ({ t, ...gapAtThreshold(points, t) })),
    [points],
  );

  /** Which states carry the most of this gap. Answers "where am I looking" before zooming. */
  const byState = useMemo(() => {
    const totals = new Map<string, number>();
    for (const cell of active) {
      totals.set(cell.state_fips, (totals.get(cell.state_fips) ?? 0) + cell.population);
    }
    return [...totals.entries()].sort((a, b) => b[1] - a[1]).slice(0, 4);
  }, [active]);

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

  const colors = useMemo<Uint8Array | null>(() => {
    if (boundaries === null || active.length === 0) return null;
    const scale = quantileScale(active.map((c) => c.population));
    return perVertexColors(boundaries, (cell) =>
      cellColor(scale(active[cell]?.population ?? 0)));
  }, [boundaries, active]);

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
          <p className="hint">{lensSpec.hint}</p>
        </div>

        {summary !== null && (
          <div className="figures">
            <div className="figure">
              <div className="n">{formatCompact(summary.population)}</div>
              <div className="l">people that far from fast charging</div>
            </div>
            <div className="figure">
              <div className="n">{(summary.share * 100).toFixed(1)}%</div>
              <div className="l">of the US population</div>
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
                <strong>{formatCompact(active.length)}</strong>{" "}
                {resolution < NATIVE_RESOLUTION ? "grouped areas" : "areas"} shown ·{" "}
                <strong>{formatCompact(
                  active.reduce((s, c) => s + c.population, 0))}</strong> people beyond{" "}
                {threshold.toFixed(1)} km
              </div>
              <div className="places">
                {byState.length === 0
                  ? "No areas at this distance."
                  : `Mostly in ${byState
                      .map(([fips, pop]) =>
                        `${STATE_NAMES[fips] ?? fips} (${formatCompact(pop)})`)
                      .join(", ")}`}
              </div>
            </div>
            <HexMap
              boundaries={boundaries}
              colors={colors}
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
                    pinned === null
                      ? undefined
                      : STATE_NAMES[shown.state_fips] !== undefined && (
                          <a
                            className="fcard-action"
                            href={`/studio/?state=${shown.state_fips}&from=gaps&threshold=${threshold.toFixed(1)}`}
                          >
                            Plan locations in {STATE_NAMES[shown.state_fips]}
                          </a>
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
