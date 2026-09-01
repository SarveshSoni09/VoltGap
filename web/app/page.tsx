"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";

import { EvidencePanel } from "../components/EvidencePanel";
import type { HexDatum } from "../components/HexMap";
import { loadHexes, summarise, type HexRow } from "../lib/data/hexes";
import { cellColor, formatCompact, quantileScale, rampColor } from "../lib/scales";
import { METRIC_LABELS, NOT_OPTIMALITY_NOTE, type MetricKey } from "../lib/vocabulary";

// deck.gl and MapLibre are ~500 KB gzipped between them. Loading them dynamically keeps
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

/** Priority is a transparent weighted blend of published components, never a new model. */
function priorityOf(row: HexRow, demandWeight: number): number {
  const equityWeight = 1 - demandWeight;
  return demandWeight * row.demand_bev + equityWeight * row.equity_population;
}

export default function NationalOverview() {
  const [rows, setRows] = useState<HexRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [metric, setMetric] = useState<MetricKey>("demand_bev");
  const [demandWeight, setDemandWeight] = useState(0.6);
  const [hovered, setHovered] = useState<HexDatum | null>(null);

  useEffect(() => {
    loadHexes().then(setRows).catch((e: Error) => setError(e.message));
  }, []);

  const values = useMemo(() => {
    if (rows === null) return [];
    if (metric === "priority") return rows.map((r) => priorityOf(r, demandWeight));
    return rows.map((r) => r[metric]);
  }, [rows, metric, demandWeight]);

  const hexes = useMemo<HexDatum[]>(() => {
    if (rows === null) return [];
    const scale = quantileScale(values.filter(Number.isFinite));
    return rows.map((row, i) => {
      const raw = values[i] ?? 0;
      // Access distance reads the other way round: far from a charger is the notable
      // condition, so the ramp is inverted rather than the number being negated.
      const t = metric === "km_to_nearest_dcfc_site" ? scale(raw) : scale(raw);
      return {
        h3_index: row.h3_index,
        color: cellColor(t, row.confidence_tier),
        value: raw,
        tier: row.confidence_tier,
      };
    });
  }, [rows, values, metric]);

  const summary = useMemo(() => (rows === null ? null : summarise(rows)), [rows]);

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
          Estimated demand, existing supply, and DCFC access across {" "}
          {rows === null ? "…" : formatCompact(rows.length)} H3 resolution-6 cells.
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

        {summary !== null && (
          <>
            <h3>National totals</h3>
            <div className="stat">
              <span className="k">Estimated BEV demand</span>
              <span className="v">{formatCompact(summary.demandTotal)}</span>
            </div>
            <div className="stat">
              <span className="k">Cells</span>
              <span className="v">{formatCompact(rows?.length ?? 0)}</span>
            </div>
          </>
        )}
      </aside>

      <div className="canvas">
        {rows === null ? (
          <div className="loading">Loading {METRIC_LABELS[metric]}…</div>
        ) : (
          <>
            <HexMap hexes={hexes} onHover={setHovered} />
            <div className="legend">
              <div>{METRIC_LABELS[metric]}</div>
              <div className="scale">
                {Array.from({ length: 24 }, (_, i) => {
                  const [r, g, b] = rampColor(i / 23);
                  return (
                    <i key={i} style={{ background: `rgb(${r},${g},${b})` }} />
                  );
                })}
              </div>
              <div className="ends">
                <span>low</span>
                <span>high</span>
              </div>
              {hovered !== null && (
                <div style={{ marginTop: "0.4rem" }}>
                  <span className={`tier ${hovered.tier.toLowerCase()}`}>
                    <span className="dot" />
                    {formatCompact(hovered.value)}
                  </span>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
