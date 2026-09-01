"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";

import { EvidencePanel } from "../components/EvidencePanel";
import { cellBoundaries, type Boundaries } from "../lib/data/geometry";
import { loadHexTable, summarise } from "../lib/data/hexes";
import type { ColumnTable } from "../lib/data/table";
import { cellColor, formatCompact, quantileScale, rampColor } from "../lib/scales";
import {
  METRIC_LABELS,
  NOT_OPTIMALITY_NOTE,
  TIER_LABELS,
  type MetricKey,
  type Tier,
} from "../lib/vocabulary";

// deck.gl and MapLibre are ~460 KB gzipped between them. Loading them dynamically keeps
// them out of the app shell, which is what makes the §11.3 600 KB shell budget achievable.
const HexMap = dynamic(() => import("../components/HexMap"), {
  ssr: false,
  loading: () => <div className="loading">Loading map…</div>,
});

const METRICS: MetricKey[] = [
  "demand_bev",
  "dcfc_ports",
  "km_to_nearest_dcfc_site",
  "priority",
];

export default function NationalOverview() {
  const [table, setTable] = useState<ColumnTable | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [metric, setMetric] = useState<MetricKey>("demand_bev");
  const [demandWeight, setDemandWeight] = useState(0.6);
  const [boundaries, setBoundaries] = useState<Boundaries | null>(null);

  useEffect(() => {
    loadHexTable()
      .then((loaded) => {
        setTable(loaded);
        // Geometry is computed in its own worker, so neither the decode nor the ~320,000
        // vertices it produces sit on the main thread between paint and interactive.
        return cellBoundaries(loaded.strs("h3_index")).then(setBoundaries);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  // A flat RGBA buffer, built straight from the columns and handed to the GPU. No row
  // objects, and no per-cell array allocated for the renderer to walk.
  const colors = useMemo<Uint8Array | null>(() => {
    if (table === null) return null;
    const tiers = table.strs("confidence_tier");
    const values =
      metric === "priority" ? priorityColumn(table, demandWeight) : table.nums(metric);
    const scale = quantileScale(Array.from(values));
    const out = new Uint8Array(table.length * 4);
    for (let i = 0; i < table.length; i += 1) {
      const [r, g, b, a] = cellColor(scale(values[i] ?? 0), (tiers[i] ?? "C") as Tier);
      out[i * 4] = r;
      out[i * 4 + 1] = g;
      out[i * 4 + 2] = b;
      out[i * 4 + 3] = a;
    }
    return out;
  }, [table, metric, demandWeight]);

  const summary = useMemo(() => (table === null ? null : summarise(table)), [table]);

  if (error !== null) {
    return (
      <div className="error">
        <p>{error}</p>
        <p>
          The published artifacts are missing. Run <code>make artifacts</code> to build
          them from the accepted pipeline outputs.
        </p>
      </div>
    );
  }

  return (
    <div className="view">
      <aside className="sidebar">
        <h1>National Overview</h1>
        <p className="sub">
          Estimated demand, existing supply, and DCFC access across{" "}
          {table === null ? "…" : formatCompact(table.length)} H3 resolution-6 cells.
        </p>

        <div className="field">
          <label htmlFor="metric">Metric</label>
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
          <>
            <div className="field">
              <label htmlFor="w">
                Demand weight {demandWeight.toFixed(2)} · equity{" "}
                {(1 - demandWeight).toFixed(2)}
              </label>
              <input
                id="w"
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={demandWeight}
                onChange={(e) => setDemandWeight(Number(e.target.value))}
              />
            </div>
            <div className="note">
              <strong>Weights are yours, not calibrated.</strong> This index is a
              transparent blend of two published quantities. Nothing fits these weights to
              data, so moving the slider is the sensitivity analysis.
            </div>
          </>
        )}

        <div className="note">{NOT_OPTIMALITY_NOTE}</div>

        {summary !== null && <EvidencePanel summary={summary} />}

        {summary !== null && table !== null && (
          <>
            <h3>National totals</h3>
            <div className="stat">
              <span className="k">Estimated BEV demand</span>
              <span className="v">{formatCompact(summary.demandTotal)}</span>
            </div>
            <div className="stat">
              <span className="k">Cells</span>
              <span className="v">{formatCompact(table.length)}</span>
            </div>
          </>
        )}
      </aside>

      <div className="canvas">
        {table === null ? (
          <div className="loading">Loading {METRIC_LABELS[metric]}…</div>
        ) : (
          <>
            <HexMap boundaries={boundaries} colors={colors} />
            <div className="legend">
              <div>{METRIC_LABELS[metric]}</div>
              <div className="scale">
                {Array.from({ length: 24 }, (_, i) => {
                  const [r, g, b] = rampColor(i / 23);
                  return <i key={i} style={{ background: `rgb(${r},${g},${b})` }} />;
                })}
              </div>
              <div className="ends">
                <span>low</span>
                <span>high</span>
              </div>
              <div className="tierkey">
                {(["A", "B", "C"] as Tier[]).map((tier) => (
                  <span key={tier} className={`tier ${tier.toLowerCase()}`}>
                    <span className="dot" />
                    {TIER_LABELS[tier]}
                  </span>
                ))}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/** Priority is a transparent weighted blend of published components, never a new model. */
function priorityColumn(table: ColumnTable, demandWeight: number): Float64Array {
  const demand = table.nums("demand_bev");
  const equity = table.nums("equity_population");
  const equityWeight = 1 - demandWeight;
  const out = new Float64Array(table.length);
  for (let i = 0; i < table.length; i += 1) {
    out[i] = demandWeight * (demand[i] ?? 0) + equityWeight * (equity[i] ?? 0);
  }
  return out;
}
