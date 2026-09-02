"use client";

import { useEffect, useMemo, useState } from "react";

import { gapAtThreshold, loadAccessTable } from "../../lib/data/access";
import type { ColumnTable } from "../../lib/data/table";
import { formatCompact } from "../../lib/scales";
import { Disclosure } from "../../components/Disclosure";
import { CEJST_NOTE } from "../../lib/vocabulary";

const THRESHOLDS = [1, 2, 3, 5, 8, 10, 16.1, 20, 25, 30, 40, 50];

export default function AccessAndEquity() {
  const [points, setPoints] = useState<ColumnTable | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [threshold, setThreshold] = useState(16.1);
  const [showCejst, setShowCejst] = useState(false);

  useEffect(() => {
    loadAccessTable().then(setPoints).catch((e: Error) => setError(e.message));
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
        <div className="lede">
          <h1>Where is charging access weakest?</h1>
          <p>
            How many people live far from public fast charging, and how that changes with
            the distance you consider &ldquo;far&rdquo;.
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

        {summary !== null && (
          <>
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
          </>
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
      </aside>

      <div className="canvas" style={{ padding: "1.5rem", overflowY: "auto" }}>
        <h2 style={{ marginTop: 0 }}>How the answer changes with the distance you pick</h2>
        <p className="sub">
          There is no single correct definition of &ldquo;too far&rdquo;, so the whole
          range is shown. Every row is recalculated from the underlying neighbourhood
          distances rather than interpolated.
        </p>
        {points === null ? (
          <div className="loading" style={{ position: "static", padding: "3rem" }}>
            Loading block-group access points…
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th className="num">Distance</th>
                <th className="num">People further than this</th>
                <th className="num">Share of US</th>
                <th style={{ width: "45%" }} />
              </tr>
            </thead>
            <tbody>
              {curve.map((point) => (
                <tr key={point.t}>
                  <td className="num">{point.t.toFixed(1)} km</td>
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
