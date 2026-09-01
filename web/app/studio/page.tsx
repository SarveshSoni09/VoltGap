"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { cellBoundaries, type Boundaries } from "../../lib/data/geometry";
import { perVertexColors } from "../../lib/render";
import { STATE_NAMES } from "../../lib/data/states";
import { hexRow, loadHexTable, type HexRow } from "../../lib/data/hexes";
import type { ColumnTable } from "../../lib/data/table";
import { downloadBlob, toCsv, toGeoJson, type PortfolioRow } from "../../lib/exporters";
import { buildCandidates } from "../../lib/optimizer/candidates";
import type { Outgoing, SolvedMessage } from "../../lib/optimizer/worker";
import { cellColor, formatCompact, quantileScale } from "../../lib/scales";
import {
  INTERACTIVE_SOLVER_NOTE,
  NOT_OPTIMALITY_NOTE,
  TIER_LABELS,
} from "../../lib/vocabulary";

const HexMap = dynamic(() => import("../../components/HexMap"), {
  ssr: false,
  loading: () => <div className="loading">Loading map…</div>,
});

const FRONTIER_STATES = ["53", "47", "30", "50", "48", "06"] as const;

export default function SitingStudio() {
  const [table, setTable] = useState<ColumnTable | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [state, setState] = useState<string>("53");
  const [budget, setBudget] = useState(20);
  const [demandWeight, setDemandWeight] = useState(0.6);
  const [excludeSaturated, setExcludeSaturated] = useState(true);
  const [result, setResult] = useState<SolvedMessage | null>(null);
  const worker = useRef<Worker | null>(null);

  useEffect(() => {
    loadHexTable().then(setTable).catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    const instance = new Worker(new URL("../../lib/optimizer/worker.ts", import.meta.url), {
      type: "module",
    });
    instance.onmessage = (event: MessageEvent<Outgoing>) => {
      if (event.data.kind === "solved") setResult(event.data);
      else setError(event.data.message);
    };
    worker.current = instance;
    return () => {
      instance.terminate();
      worker.current = null;
    };
  }, []);

  // Materialise only this state's cells - a few thousand, not the national 53,208.
  const stateRows = useMemo<HexRow[]>(() => {
    if (table === null) return [];
    const states = table.strs("state_fips");
    const out: HexRow[] = [];
    for (let i = 0; i < table.length; i += 1) {
      if (states[i] === state) out.push(hexRow(table, i));
    }
    return out;
  }, [table, state]);

  const candidateSet = useMemo(
    () => (stateRows.length === 0 ? null : buildCandidates(stateRows, excludeSaturated ? 2.0 : Infinity)),
    [stateRows, excludeSaturated],
  );

  useEffect(() => {
    if (worker.current === null || candidateSet === null) return;
    worker.current.postMessage({
      kind: "load",
      candidates: candidateSet.candidates,
      coverage: [...candidateSet.coverage.entries()],
    });
    worker.current.postMessage({
      kind: "solve",
      budget,
      weights: { demand: demandWeight, equity: 1 - demandWeight },
    });
  }, [candidateSet, budget, demandWeight]);

  const selected = useMemo(
    () => new Set(result?.selected ?? []),
    [result],
  );

  const byIndex = useMemo(
    () => new Map(stateRows.map((r) => [r.h3_index, r])),
    [stateRows],
  );

  const portfolio = useMemo<PortfolioRow[]>(() => {
    if (result === null) return [];
    return result.selected.flatMap((index, i) => {
      const row = byIndex.get(index);
      if (row === undefined) return [];
      return [{
        h3_index: row.h3_index,
        latitude: row.latitude,
        longitude: row.longitude,
        rank: i + 1,
        demand_bev: row.demand_bev,
        equity_population: row.equity_population,
        population: row.population,
        uncertainty_score: row.uncertainty_score,
        confidence_tier: row.confidence_tier,
        dominant_evidence_grain: row.dominant_evidence_grain,
        sub_state_anchored_share: row.sub_state_anchored_share,
        existing_dcfc_ports: row.dcfc_ports,
        km_to_nearest_dcfc_site: row.km_to_nearest_dcfc_site,
      }];
    });
  }, [result, byIndex]);

  const [boundaries, setBoundaries] = useState<Boundaries | null>(null);

  useEffect(() => {
    if (stateRows.length === 0) {
      setBoundaries(null);
      return;
    }
    let cancelled = false;
    cellBoundaries(stateRows.map((r) => r.h3_index)).then((result) => {
      if (!cancelled) setBoundaries(result);
    });
    return () => {
      cancelled = true;
    };
  }, [stateRows]);

  // Selected cells are highlighted by recolouring the buffer, not by a second layer.
  // Per-VERTEX, which is what deck.gl's binary attribute path reads (see lib/render.ts).
  const colors = useMemo<Uint8Array | null>(() => {
    if (stateRows.length === 0 || boundaries === null) return null;
    const scale = quantileScale(stateRows.map((r) => r.demand_bev));
    return perVertexColors(boundaries, (cell) => {
      const row = stateRows[cell];
      if (row === undefined) return [0, 0, 0, 0] as const;
      const chosen = selected.has(row.h3_index);
      const [r, g, b, a] = chosen
        ? ([255, 214, 102, 245] as const)
        : cellColor(scale(row.demand_bev), row.confidence_tier);
      const dim = selected.size > 0 && !chosen;
      return [r, g, b, dim ? 60 : a] as const;
    });
  }, [stateRows, boundaries, selected]);

  const centre = useMemo(() => {
    if (stateRows.length === 0) return undefined;
    const lat = stateRows.reduce((s, r) => s + r.latitude, 0) / stateRows.length;
    const lon = stateRows.reduce((s, r) => s + r.longitude, 0) / stateRows.length;
    return { latitude: lat, longitude: lon, zoom: 5.6 };
  }, [stateRows]);

  const exportCsv = useCallback(() => {
    downloadBlob(`voltgap_portfolio_${state}.csv`, "text/csv", toCsv(portfolio));
  }, [portfolio, state]);

  const exportGeoJson = useCallback(() => {
    downloadBlob(
      `voltgap_portfolio_${state}.geojson`,
      "application/geo+json",
      JSON.stringify(toGeoJson(portfolio), null, 2),
    );
  }, [portfolio, state]);

  if (error !== null) return <div className="error">{error}</div>;

  return (
    <div className="view">
      <aside className="sidebar">
        <h1>Siting Studio</h1>
        <p className="sub">
          A ranked, budget-feasible portfolio of candidate cells, solved in your browser.
        </p>

        <div className="field">
          <label htmlFor="state">State</label>
          <select id="state" value={state} onChange={(e) => setState(e.target.value)}>
            {FRONTIER_STATES.map((fips) => (
              <option key={fips} value={fips}>
                {STATE_NAMES[fips] ?? fips}
              </option>
            ))}
          </select>
        </div>

        <div className="field">
          <label htmlFor="budget">Budget: {budget} sites</label>
          <input
            id="budget" type="range" min={1} max={100} step={1}
            value={budget} onChange={(e) => setBudget(Number(e.target.value))}
          />
        </div>

        <div className="field">
          <label htmlFor="weight">
            Demand {demandWeight.toFixed(2)} · equity {(1 - demandWeight).toFixed(2)}
          </label>
          <input
            id="weight" type="range" min={0} max={1} step={0.05}
            value={demandWeight} onChange={(e) => setDemandWeight(Number(e.target.value))}
          />
        </div>

        <div className="field">
          <label>
            <input
              type="checkbox" checked={excludeSaturated} style={{ width: "auto" }}
              onChange={(e) => setExcludeSaturated(e.target.checked)}
            />{" "}
            Exclude already-saturated cells
          </label>
        </div>

        <div className="note">
          <strong>{INTERACTIVE_SOLVER_NOTE}</strong> No approximation bound is claimed for
          this solver. The published analytical frontier is computed offline with exact
          integer programming.
        </div>
        <div className="note">{NOT_OPTIMALITY_NOTE}</div>

        {candidateSet !== null && (
          <>
            <h3>Candidate universe</h3>
            <div className="stat">
              <span className="k">Candidates</span>
              <span className="v">{formatCompact(candidateSet.candidates.length)}</span>
            </div>
            {Object.entries(candidateSet.excluded).map(([reason, count]) => (
              <div className="stat" key={reason}>
                <span className="k">excluded: {reason.replace(/_/g, " ")}</span>
                <span className="v">{formatCompact(count)}</span>
              </div>
            ))}
            <p className="sub" style={{ fontSize: "0.75rem", marginTop: "0.4rem" }}>
              There is no substation-proximity filter: no authoritative national dataset
              exists, and siting works without one.
            </p>
          </>
        )}

        {result !== null && (
          <>
            <h3>This portfolio</h3>
            <div className="stat">
              <span className="k">Sites selected</span>
              <span className="v">{result.selected.length}</span>
            </div>
            <div className="stat">
              <span className="k">Demand covered</span>
              <span className="v">{formatCompact(result.demandCovered)}</span>
            </div>
            <div className="stat">
              <span className="k">Lower-income population covered</span>
              <span className="v">{formatCompact(result.equityCovered)}</span>
            </div>
            <div className="stat">
              <span className="k">Solve time</span>
              <span className="v">{result.elapsedMs.toFixed(0)} ms</span>
            </div>
            <div className="row" style={{ marginTop: "0.8rem" }}>
              <button onClick={exportCsv}>Export CSV</button>
              <button onClick={exportGeoJson}>Export GeoJSON</button>
            </div>
          </>
        )}
      </aside>

      <div className="canvas" style={{ display: "grid", gridTemplateRows: "1fr auto" }}>
        <div style={{ position: "relative" }}>
          {table === null ? (
            <div className="loading">Loading cells…</div>
          ) : (
            <HexMap
              boundaries={boundaries}
              colors={colors}
              initialViewState={centre}
            />
          )}
        </div>
        <div style={{ maxHeight: "40vh", overflowY: "auto", borderTop: "1px solid var(--line)", padding: "0.75rem 1rem" }}>
          <table>
            <thead>
              <tr>
                <th className="num">#</th>
                <th>Cell</th>
                <th className="num">Demand</th>
                <th className="num">Lower-income pop.</th>
                <th className="num">Existing DCFC</th>
                <th className="num">Uncertainty</th>
                <th>Confidence</th>
              </tr>
            </thead>
            <tbody>
              {portfolio.map((row) => (
                <tr key={row.h3_index}>
                  <td className="num">{row.rank}</td>
                  <td style={{ fontFamily: "var(--mono)", fontSize: "0.75rem" }}>
                    {row.h3_index}
                  </td>
                  <td className="num">{formatCompact(row.demand_bev)}</td>
                  <td className="num">{formatCompact(row.equity_population)}</td>
                  <td className="num">{row.existing_dcfc_ports.toFixed(0)}</td>
                  <td className="num">{row.uncertainty_score.toFixed(3)}</td>
                  <td>
                    <span className={`tier ${row.confidence_tier.toLowerCase()}`}>
                      <span className="dot" />
                      {TIER_LABELS[row.confidence_tier]}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {portfolio.length === 0 && (
            <p className="sub">Adjust the budget to select sites.</p>
          )}
        </div>
      </div>
    </div>
  );
}
