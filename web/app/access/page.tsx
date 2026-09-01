"use client";

import { useEffect, useMemo, useState } from "react";

import { gapAtThreshold, loadAccessPoints, type AccessPoint } from "../../lib/data/access";
import { formatCompact } from "../../lib/scales";
import { CEJST_NOTE } from "../../lib/vocabulary";

const THRESHOLDS = [1, 2, 3, 5, 8, 10, 16.1, 20, 25, 30, 40, 50];

export default function AccessAndEquity() {
  const [points, setPoints] = useState<AccessPoint[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [threshold, setThreshold] = useState(16.1);
  const [showCejst, setShowCejst] = useState(false);

  useEffect(() => {
    loadAccessPoints().then(setPoints).catch((e: Error) => setError(e.message));
  }, []);

  const summary = useMemo(
    () => (points === null ? null : gapAtThreshold(points, threshold)),
    [points, threshold],
  );
  const curve = useMemo(
    () =>
      points === null
        ? []
        : THRESHOLDS.map((t) => ({ t, ...gapAtThreshold(points, t) })),
    [points],
  );

  if (error !== null) return <div className="error">{error}</div>;
  const maxGap = curve.length > 0 ? Math.max(...curve.map((c) => c.population)) : 1;

  return (
    <div className="view">
      <aside className="sidebar">
        <h1>Access &amp; Equity</h1>
        <p className="sub">
          Population beyond a drive distance from operational public DC fast charging,
          measured from block-group population-weighted points.
        </p>

        <div className="field">
          <label htmlFor="threshold">
            DCFC access gap threshold: {threshold.toFixed(1)} km
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

        <div className="note">
          <strong>This is a DCFC access gap.</strong> It measures distance to DC fast
          charging only and says nothing about Level 2 availability.
        </div>

        {summary !== null && (
          <>
            <h3>At {threshold.toFixed(1)} km</h3>
            <div className="stat">
              <span className="k">Population in gap</span>
              <span className="v">{formatCompact(summary.population)}</span>
            </div>
            <div className="stat">
              <span className="k">Share of population</span>
              <span className="v">{(summary.share * 100).toFixed(2)}%</span>
            </div>
            <div className="stat">
              <span className="k">Block groups in gap</span>
              <span className="v">{formatCompact(summary.points)}</span>
            </div>
            <div className="stat">
              <span className="k">Lower-income population in gap</span>
              <span className="v">{formatCompact(summary.equityPopulation)}</span>
            </div>
            <p className="sub" style={{ fontSize: "0.75rem", marginTop: "0.4rem" }}>
              &ldquo;Lower-income&rdquo; is one named ACS indicator — population in
              households below $35,000 a year — not a composite disadvantage index.
            </p>
          </>
        )}

        <div className="note warn">
          <strong>Straight-line distance.</strong> Core ships network-free distance, which
          always understates real travel distance. The population actually beyond this
          drive distance is at least as large as reported here, never smaller.
        </div>

        <h3>Archived overlay</h3>
        <div className="field">
          <button onClick={() => setShowCejst(!showCejst)}>
            {showCejst ? "Hide" : "Show"} archived CEJST context
          </button>
        </div>
        {showCejst && <div className="note warn">{CEJST_NOTE}</div>}
      </aside>

      <div className="canvas" style={{ padding: "1.5rem", overflowY: "auto" }}>
        <h2 style={{ marginTop: 0 }}>Threshold sensitivity</h2>
        <p className="sub">
          How the affected population changes across the threshold range. The curve is
          recomputed in the browser from the per-point distances, so every row is the same
          arithmetic rather than an interpolation between fixed points.
        </p>
        {points === null ? (
          <div className="loading" style={{ position: "static", padding: "3rem" }}>
            Loading block-group access points…
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th className="num">Threshold (km)</th>
                <th className="num">Population in gap</th>
                <th className="num">Share</th>
                <th style={{ width: "45%" }} />
              </tr>
            </thead>
            <tbody>
              {curve.map((point) => (
                <tr key={point.t}>
                  <td className="num">{point.t.toFixed(1)}</td>
                  <td className="num">{formatCompact(point.population)}</td>
                  <td className="num">{(point.share * 100).toFixed(2)}%</td>
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
        )}
      </div>
    </div>
  );
}
