"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";

import { Disclosure } from "../components/Disclosure";
import { cellBoundaries, type Boundaries } from "../lib/data/geometry";
import { loadHexTable, summarise } from "../lib/data/hexes";
import type { ColumnTable } from "../lib/data/table";
import {
  aggregate,
  displayResolution,
  NATIVE_RESOLUTION,
  type NativeCell,
} from "../lib/aggregate";
import { perVertexColors } from "../lib/render";
import { cellColor, formatCompact, quantileScale, rampColor } from "../lib/scales";
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
          loaded.length;
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
    const out = new Array<NativeCell>(table.length);
    for (let i = 0; i < table.length; i += 1) {
      out[i] = {
        h3_index: index[i] ?? "",
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

  // Display resolution only. The analytical surface stays at resolution 6, and
  // tests/aggregate.test.ts proves the roll-up conserves every additive quantity.
  const resolution = forceNative ? NATIVE_RESOLUTION : displayResolution(zoom);
  const shown = useMemo(
    () => aggregate(nativeCells, resolution),
    [nativeCells, resolution],
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

  const summary = useMemo(() => (table === null ? null : summarise(table)), [table]);

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
              <div className="n">{formatCompact(table.length)}</div>
              <div className="l">populated areas estimated</div>
            </div>
          </div>
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
            <HexMap
              boundaries={boundaries}
              colors={colors}
              analyticalLayer={analyticalLayer}
              onZoom={setZoom}
            />
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
