"use client";

import { cellToLatLng } from "h3-js";
import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";

import { CardAnchor } from "../components/CardAnchor";
import { Disclosure } from "../components/Disclosure";
import { FeatureCard, type FeatureFact } from "../components/FeatureCard";
import { cellBoundaries, type Boundaries } from "../lib/data/geometry";
import { loadHexTable, summarise } from "../lib/data/hexes";
import type { ColumnTable } from "../lib/data/table";
import {
  aggregate,
  displayResolution,
  NATIVE_RESOLUTION,
  type NativeCell,
} from "../lib/aggregate";
import { STATE_NAMES } from "../lib/data/states";
import { groupedPlaceName } from "../lib/reasons";
import {
  boundsOf, geographyLabel, NATIONAL, statesPresent, US_BOUNDS,
  type Bounds, type StateOption,
} from "../lib/geography";
import { perVertexColors } from "../lib/render";
import {
  analyticalOpacity, cellColor, formatCompact, formatCount, quantileScale, rampColor,
} from "../lib/scales";
import {
  EVIDENCE_GRAIN_LABELS,
  METRIC_LABELS,
  METRIC_LEGEND_HINT,
  METRIC_QUESTIONS,
  NO_DATA_EXPLANATION,
  NOT_OPTIMALITY_NOTE,
  TIER_DESCRIPTIONS,
  TIER_LABELS,
  TIER_LABELS_PLAIN,
  TIER_SUMMARY,
  type MetricKey,
  type Tier,
} from "../lib/vocabulary";

const HexMap = dynamic(() => import("../components/HexMap"), {
  ssr: false,
  loading: () => <div className="loading">Loading map…</div>,
});

const METRICS: MetricKey[] = [
  "demand_bev",
  "km_to_nearest_dcfc_site",
  "dcfc_ports",
  "priority",
];

export default function NationalOverview() {
  const [table, setTable] = useState<ColumnTable | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [metric, setMetric] = useState<MetricKey>("demand_bev");
  const [demandWeight, setDemandWeight] = useState(0.6);
  const [zoom, setZoom] = useState(3.4);
  const [boundaries, setBoundaries] = useState<Boundaries | null>(null);
  const [analyticalLayer, setAnalyticalLayer] = useState(true);
  /**
   * Test affordance: `?resolution=native` disables display aggregation.
   *
   * The performance harnesses require the full 53,208-cell surface to be genuinely
   * rendered — a frame rate over 2,700 aggregated parents would not demonstrate the
   * §11.3 budget, and the ≥50,000-cell guard exists precisely to stop that. This forces
   * the heaviest real rendering path so the guard keeps its original meaning.
   */
  const [forceNative, setForceNative] = useState(false);
  /**
   * The geography under examination. `NATIONAL` or a state FIPS.
   *
   * Selecting a state **filters the analysis**, it does not only move the camera: the
   * cells, the totals, the colour scale's quantile breaks and the reliability mix all
   * describe the selected state alone. The alternative — zoom only — would leave national
   * figures beside a state map, which is the kind of quiet mismatch this project exists to
   * avoid. The interface says which it is, and `tests/geography.test.ts` asserts the
   * parity that makes the claim checkable.
   */
  const [state, setState] = useState<string>(NATIONAL);
  const [fit, setFit] = useState<Bounds | null>(null);
  /**
   * Where the reader asked to be taken, from the card of an area they clicked.
   *
   * Distinct from `fit`, which frames a whole geography. This centres one area and keeps
   * the current geography, metric and threshold untouched — moving the camera is the only
   * thing it does, so a reader can look closer without losing the question they set up.
   */
  const [focus, setFocus] =
    useState<{ longitude: number; latitude: number; zoom: number } | null>(null);
  /** Which drawn cell the reader is asking about, and whether they pinned the answer. */
  const [hovered, setHovered] = useState<number | null>(null);
  const [pinned, setPinned] = useState<number | null>(null);
  const [cursor, setCursor] = useState({ x: 0, y: 0 });

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setAnalyticalLayer(params.get("layer") !== "off");
    setForceNative(params.get("resolution") === "native");
  }, []);

  useEffect(() => {
    loadHexTable()
      .then((loaded) => {
        setTable(loaded);
        // Cells REPRESENTED by the view, as distinct from polygons DRAWN. At national
        // zoom the two differ: display aggregation draws ~4,000 parents covering all
        // 53,208 native cells. A guard asking "did this page load its data" must read
        // this one; a guard asking "is a full layer being rendered" reads the other.
        (window as unknown as { __voltgapNativeCells?: number }).__voltgapNativeCells =
          new Set(loaded.strs("h3_index")).size;
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  // Native cells, read straight from the columns. No row objects for 53,208 cells.
  const nativeCells = useMemo<NativeCell[]>(() => {
    if (table === null) return [];
    const index = table.strs("h3_index");
    const demand = table.nums("demand_bev");
    const population = table.nums("population");
    const equity = table.nums("equity_population");
    const ports = table.nums("dcfc_ports");
    const distance = table.nums("km_to_nearest_dcfc_site");
    const anchored = table.nums("sub_state_anchored_share");
    const uncertainty = table.nums("uncertainty_score");
    const tier = table.strs("confidence_tier");
    const county = table.strs("county_name");
    const state = table.strs("state_code");
    const fips = table.strs("state_fips");
    const out = new Array<NativeCell>(table.length);
    for (let i = 0; i < table.length; i += 1) {
      out[i] = {
        h3_index: index[i] ?? "",
        county_name: county[i] ?? "",
        state_code: state[i] ?? "",
        state_fips: fips[i] ?? "",
        confidence_tier: (tier[i] ?? "C") as Tier,
        demand_bev: demand[i] ?? 0,
        population: population[i] ?? 0,
        equity_population: equity[i] ?? 0,
        dcfc_ports: ports[i] ?? 0,
        km_to_nearest_dcfc_site: distance[i] ?? 0,
        sub_state_anchored_share: anchored[i] ?? 0,
        uncertainty_score: uncertainty[i] ?? 0,
      };
    }
    return out;
  }, [table]);

  const stateOptions = useMemo<StateOption[]>(
    () => (table === null
      ? []
      : statesPresent(table.strs("state_fips"), table.strs("state_code"))),
    [table],
  );
  const selectedState = useMemo(
    () => stateOptions.find((o) => o.fips === state) ?? null,
    [stateOptions, state],
  );

  /** Extent per state, from the published cell centroids. Computed once per load. */
  const stateBounds = useMemo(() => {
    const out = new Map<string, Bounds>();
    if (table === null) return out;
    const fips = table.strs("state_fips");
    const lon = table.nums("longitude");
    const lat = table.nums("latitude");
    const points = new Map<string, { longitude: number; latitude: number }[]>();
    for (let i = 0; i < table.length; i += 1) {
      const key = fips[i] ?? "";
      if (key === "") continue;
      let list = points.get(key);
      if (list === undefined) { list = []; points.set(key, list); }
      list.push({ longitude: lon[i] ?? 0, latitude: lat[i] ?? 0 });
    }
    for (const [key, list] of points) {
      const b = boundsOf(list);
      if (b !== null) out.set(key, b);
    }
    return out;
  }, [table]);

  // The analytical universe for everything on this page. Filtering here, once, is what
  // keeps the map, the figures and the legend describing the same set of cells.
  const universe = useMemo(
    () => (selectedState === null
      ? nativeCells
      : nativeCells.filter((c) => c.state_fips === selectedState.fips)),
    [nativeCells, selectedState],
  );

  // Display resolution only. The analytical surface stays at resolution 6, and
  // tests/aggregate.test.ts proves the roll-up conserves every additive quantity.
  const resolution = forceNative ? NATIVE_RESOLUTION : displayResolution(zoom);
  const shown = useMemo(
    () => aggregate(universe, resolution),
    [universe, resolution],
  );

  useEffect(() => {
    if (shown.length === 0) {
      setBoundaries(null);
      return;
    }
    let cancelled = false;
    cellBoundaries(shown.map((c) => c.h3_index)).then((result) => {
      if (!cancelled) setBoundaries(result);
    });
    return () => {
      cancelled = true;
    };
  }, [shown]);

  useEffect(() => {
    // Indexes address positions in `shown`; when that array is rebuilt at a new display
    // resolution the old index points at a different place, so the card is dismissed
    // rather than silently relabelled.
    setHovered(null);
    setPinned(null);
  }, [resolution]);

  const values = useMemo(() => {
    if (metric === "priority") {
      const equityWeight = 1 - demandWeight;
      return shown.map(
        (c) => demandWeight * c.demand_bev + equityWeight * c.equity_population,
      );
    }
    return shown.map((c) => c[metric]);
  }, [shown, metric, demandWeight]);

  // Colour carries the metric and NOTHING ELSE. Reliability used to be encoded as
  // opacity, which made a well-evidenced empty area and a poorly-evidenced busy one look
  // alike, and made low-confidence cells hard to tell from the 78.8% of the country that
  // has no cell at all. Reliability is now reported separately, below and on the map.
  const colors = useMemo<Uint8Array | null>(() => {
    if (boundaries === null || values.length === 0) return null;
    const scale = quantileScale(values.filter(Number.isFinite));
    return perVertexColors(boundaries, (cell) =>
      cellColor(scale(values[cell] ?? 0)),
    );
  }, [boundaries, values]);

  /**
   * The evidence summary for the selected geography.
   *
   * Scoped by row index rather than by rebuilding a table, so the reliability mix and the
   * demand total beside the map are computed from exactly the rows the map is drawing.
   * That identity is what `tests/geography.test.ts` checks.
   */
  const summary = useMemo(() => {
    if (table === null) return null;
    if (selectedState === null) return summarise(table);
    const fips = table.strs("state_fips");
    const rows: number[] = [];
    for (let i = 0; i < table.length; i += 1) {
      if (fips[i] === selectedState.fips) rows.push(i);
    }
    return summarise(table, rows);
  }, [table, selectedState]);

  /**
   * Distinct areas, not published rows. A cell straddling a state line is published once
   * per state, so the row count is 296 higher than the number of places on the map.
   */
  const areaCount = useMemo(
    () => new Set(universe.map((c) => c.h3_index)).size, [universe]);

  /** Where the highest values are, stated above the map so it is not a hover-only fact. */
  const leaders = useMemo(() => {
    if (shown.length === 0) return [];
    const totals = new Map<string, number>();
    for (let i = 0; i < shown.length; i += 1) {
      const cell = shown[i];
      if (cell === undefined || !cell.county_name) continue;
      const key = `${cell.county_name}, ${cell.state_code}`;
      totals.set(key, Math.max(totals.get(key) ?? 0, values[i] ?? 0));
    }
    return [...totals.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3).map((e) => e[0]);
  }, [shown, values]);

  // The card for whichever cell is being asked about. Pinned wins over hovered, so moving
  // the mouse toward the pinned card's own buttons does not replace it.
  const active = pinned ?? hovered;
  /** The ring drawn around whichever cell the card is describing. */
  const outlined = useMemo(
    () => (active === null ? [] : [shown[active]?.h3_index ?? ""].filter(Boolean)),
    [active, shown],
  );
  const card = useMemo(() => {
    if (active === null) return null;
    const cell = shown[active];
    if (cell === undefined) return null;
    const grouped = resolution < NATIVE_RESOLUTION;
    const place =
      groupedPlaceName(cell.county_name, cell.state_code, cell.counties) ??
      "Unnamed area";
    const evs: FeatureFact = { label: "Estimated EVs", value: formatCompact(cell.demand_bev) };
    const people: FeatureFact = { label: "People", value: formatCompact(cell.population) };
    const ports: FeatureFact = {
      label: "Fast-charging ports", value: formatCount(cell.dcfc_ports),
    };
    const distance: FeatureFact = {
      label: "Nearest fast charging", value: `${cell.km_to_nearest_dcfc_site.toFixed(0)} km`,
    };
    const underserved: FeatureFact = {
      label: "Underserved population", value: formatCompact(cell.equity_population),
    };

    // The selected metric is the dominant value, and never repeats as a supporting fact.
    const view: Record<MetricKey, { primary: FeatureFact; facts: FeatureFact[] }> = {
      demand_bev: { primary: evs, facts: [people, ports, distance] },
      dcfc_ports: {
        primary: {
          label: "Fast-charging ports",
          value: formatCount(cell.dcfc_ports, "none today"),
        },
        facts: [evs, people, distance],
      },
      km_to_nearest_dcfc_site: {
        primary: { label: "To nearest fast charging", value: distance.value },
        facts: [evs, people, ports],
      },
      priority: {
        primary: {
          label: `Priority at ${Math.round(demandWeight * 100)}% demand`,
          value: formatCompact(values[active] ?? 0),
        },
        facts: [evs, underserved, distance],
      },
    };
    const chosen = view[metric];

    return {
      place,
      // Carried so the card can offer to centre the map on the area it describes.
      h3_index: cell.h3_index,
      state_fips: cell.state_fips,
      primaryLabel: chosen.primary.label,
      primaryValue: chosen.primary.value,
      facts: chosen.facts,
      // The PUBLISHED tier, never one re-derived here. Where cells are grouped for
      // display the pipeline published several tiers and none of them describes the
      // group, so the group reports its sub-state-anchored share instead — a quantity
      // that is published and that means the same thing at any grouping. §11.5 forbids
      // calling any of this "observed": most anchored demand is allocated from ZIP or
      // county evidence, not reported for the tract itself.
      reliability:
        cell.confidence_tier === null
          ? {
              label:
                `${Math.round(cell.sub_state_anchored_share * 100)}% of demand here is ` +
                "sub-state anchored",
            }
          : {
              label: TIER_LABELS_PLAIN[cell.confidence_tier],
              tier: cell.confidence_tier,
            },
      technical: [
        { label: "H3 index", value: cell.h3_index },
        { label: "H3 resolution", value: String(resolution) },
        { label: "Uncertainty score", value: cell.uncertainty_score.toFixed(3) },
        ...(grouped
          ? [{ label: "Areas grouped here", value: String(cell.children) }]
          : []),
      ],
    };
  }, [active, shown, metric, values, resolution, demandWeight]);

  if (error !== null) {
    return (
      <div className="error">
        <p>{error}</p>
        <p>
          The published data files are missing. Run <code>make artifacts</code> to build
          them.
        </p>
      </div>
    );
  }

  const totalDemand = summary?.demandTotal ?? 0;

  return (
    <div className="view">
      <aside className="sidebar">
        <div className="lede">
          <h1>Where is EV demand highest?</h1>
          <p>{METRIC_QUESTIONS[metric]}</p>
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
                setPinned(null);
                setHovered(null);
                const option = stateOptions.find((o) => o.fips === next) ?? null;
                setFit(
                  option === null ? US_BOUNDS : stateBounds.get(option.fips) ?? US_BOUNDS,
                );
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
                onClick={() => {
                  setState(NATIONAL);
                  setPinned(null);
                  setHovered(null);
                  setFit(US_BOUNDS);
                }}
              >
                Reset to U.S.
              </button>
            )}
          </div>
          <p className="hint">
            Selecting a state narrows the estimates on this page to that state, not just
            the map view. Every figure here describes {geographyLabel(selectedState)}.
          </p>
        </div>

        <div className="field">
          <label htmlFor="metric">Show</label>
          <select
            id="metric"
            value={metric}
            onChange={(e) => setMetric(e.target.value as MetricKey)}
          >
            {METRICS.map((key) => (
              <option key={key} value={key}>
                {METRIC_LABELS[key]}
              </option>
            ))}
          </select>
        </div>

        {metric === "priority" && (
          <div className="field">
            <label htmlFor="w">
              Balance: {Math.round(demandWeight * 100)}% demand,{" "}
              {Math.round((1 - demandWeight) * 100)}% underserved population
            </label>
            <input
              id="w" type="range" min={0} max={1} step={0.05}
              value={demandWeight}
              onChange={(e) => setDemandWeight(Number(e.target.value))}
            />
          </div>
        )}

        <p className="reading">{METRIC_LEGEND_HINT[metric]}</p>

        {table !== null && (
          <div className="figures">
            <div className="figure">
              <div className="n">{formatCompact(totalDemand)}</div>
              <div className="l">estimated EVs nationally</div>
            </div>
            <div className="figure">
              <div className="n">{formatCompact(areaCount)}</div>
              <div className="l">populated areas estimated</div>
            </div>
          </div>
        )}

        {selectedState !== null && STATE_NAMES[selectedState.fips] !== undefined && (
          <a
            className="handoff"
            href={`/studio/?state=${selectedState.fips}&from=national`}
          >
            Plan new locations in {selectedState.name} →
          </a>
        )}

        <Disclosure question="What do the unshaded areas mean?">
          <p>{NO_DATA_EXPLANATION}</p>
          <p>
            An area appears here only where census population sits inside it. About 79% of
            the country&rsquo;s land has none, so it has no estimate to show.
          </p>
        </Disclosure>

        <Disclosure question="How reliable are these estimates?">
          {summary !== null && (
            <>
              <p>
                Every area carries a reliability rating based on the evidence underneath
                it. Across the country, weighted by estimated demand:
              </p>
              <table>
                <tbody>
                  {(["A", "B", "C"] as Tier[]).map((tier) => (
                    <tr key={tier}>
                      <td>
                        <span className={`tier ${tier.toLowerCase()}`}>
                          <span className="dot" />
                          {TIER_LABELS_PLAIN[tier]}
                        </span>
                      </td>
                      <td className="num">
                        {((summary.byTier[tier] / summary.demandTotal) * 100).toFixed(0)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p style={{ marginTop: "0.5rem" }}>{TIER_SUMMARY.A}</p>
            </>
          )}
        </Disclosure>

        <Disclosure question="Where does the underlying data come from?" tone="quiet">
          {summary !== null && (
            <>
              <p>
                Vehicle registration data is published at different levels of detail by
                different states. Share of estimated demand by the finest evidence
                available:
              </p>
              <table>
                <tbody>
                  {Object.entries(summary.byGrain)
                    .sort((a, b) => b[1] - a[1])
                    .map(([grain, demand]) => (
                      <tr key={grain}>
                        <td>
                          {EVIDENCE_GRAIN_LABELS[
                            grain as keyof typeof EVIDENCE_GRAIN_LABELS
                          ] ?? grain}
                        </td>
                        <td className="num">
                          {((demand / summary.demandTotal) * 100).toFixed(1)}%
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
              <p style={{ marginTop: "0.5rem" }}>
                &ldquo;{TIER_LABELS.A}&rdquo; is the technical term for the highest tier.
                {" "}{TIER_DESCRIPTIONS.A}
              </p>
            </>
          )}
        </Disclosure>

        <Disclosure question="Is this saying where chargers should go?" tone="quiet">
          <p>{NOT_OPTIMALITY_NOTE}</p>
          <p>
            To plan against a budget, use <a href="/studio/">Plan new locations</a>.
          </p>
        </Disclosure>
      </aside>

      <div className="canvas">
        {table === null ? (
          <div className="loading">Loading national estimates…</div>
        ) : (
          <>
            <div className="mapsummary">
              <div>
                {METRIC_LABELS[metric]} in{" "}
                <strong>{geographyLabel(selectedState)}</strong> ·{" "}
                <strong>{formatCompact(areaCount)}</strong> populated areas
                {resolution < NATIVE_RESOLUTION && ", grouped for display"}
              </div>
              <div className="places">
                {leaders.length === 0
                  ? "Hover any area to see what it is."
                  : `Highest in ${geographyLabel(selectedState)}: ${
                      leaders.join(" · ")}. Hover any area for detail.`}
              </div>
            </div>
            <HexMap
              boundaries={boundaries}
              colors={colors}
              analyticalLayer={analyticalLayer}
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
            {card !== null && (
              <CardAnchor
                pinned={pinned !== null}
                x={cursor.x}
                y={cursor.y}
                onClose={() => setPinned(null)}
              >
                <FeatureCard
                  place={card.place}
                  primaryLabel={card.primaryLabel}
                  primaryValue={card.primaryValue}
                  facts={card.facts}
                  reliability={card.reliability}
                  technical={pinned !== null ? card.technical : undefined}
                  actions={
                    pinned === null ? undefined : (
                      <>
                        <button
                          type="button"
                          className="fcard-action"
                          onClick={() => {
                            const [lat, lng] = cellToLatLng(card.h3_index);
                            // Never zooms out: a reader who is already close is asking to
                            // centre, not to be pulled back to a fixed level.
                            setFocus({
                              longitude: lng, latitude: lat,
                              zoom: Math.max(zoom, 8),
                            });
                          }}
                        >
                          Zoom to this area
                        </button>
                        {/* Offered only where the Studio actually covers the state,
                            rather than sending the reader somewhere that cannot
                            answer them. */}
                        {STATE_NAMES[card.state_fips] !== undefined && (
                          <a
                            className="fcard-action"
                            href={`/studio/?state=${card.state_fips}&from=national`}
                          >
                            Plan locations in {STATE_NAMES[card.state_fips]}
                          </a>
                        )}
                      </>
                    )
                  }
                />
              </CardAnchor>
            )}
            <div className="legend">
              <div>{METRIC_LABELS[metric]}</div>
              <div className="scale">
                {Array.from({ length: 24 }, (_, i) => {
                  const [r, g, b] = rampColor(i / 23);
                  return <i key={i} style={{ background: `rgb(${r},${g},${b})` }} />;
                })}
              </div>
              <div className="ends">
                <span>lower</span>
                <span>higher</span>
              </div>
              <div className="swatches">
                <span className="sw">
                  <i className="hollow" />
                  no estimate — nobody lives here
                </span>
                {resolution < NATIVE_RESOLUTION && (
                  <span className="sw">
                    <i style={{ background: "var(--ink-faint)" }} />
                    areas grouped for display · zoom in for detail
                  </span>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
