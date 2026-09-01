"use client";

import type { EvidenceSummary } from "../lib/data/hexes";
import { formatCompact } from "../lib/scales";
import { EVIDENCE_GRAIN_LABELS, TIER_DESCRIPTIONS, TIER_LABELS, type Tier } from "../lib/vocabulary";

/**
 * §11.1: "Every aggregate reports sub-state anchored versus modeled share, with the
 * `evidence_grain` breakdown available beneath it."
 *
 * This component exists so that requirement is met in one place and cannot be met
 * differently, or forgotten, on each view.
 */
export function EvidencePanel({ summary }: { summary: EvidenceSummary }) {
  const grains = Object.entries(summary.byGrain).sort((a, b) => b[1] - a[1]);
  return (
    <>
      <h3>Evidence behind these numbers</h3>
      <div className="stat">
        <span className="k">Sub-state anchored</span>
        <span className="v">{(summary.subStateAnchoredShare * 100).toFixed(1)}%</span>
      </div>
      <div className="stat">
        <span className="k">Modeled from state totals</span>
        <span className="v">
          {((1 - summary.subStateAnchoredShare) * 100).toFixed(1)}%
        </span>
      </div>
      <div className="note">
        <strong>Tier A is &ldquo;sub-state anchored&rdquo;, not &ldquo;observed&rdquo;.</strong>{" "}
        Most anchored evidence is ZIP- or county-grain and was allocated down to tracts.
        Only Washington publishes registrations at tract grain.
      </div>

      <h3>Demand by evidence grain</h3>
      <table>
        <tbody>
          {grains.map(([grain, demand]) => (
            <tr key={grain}>
              <td>
                {EVIDENCE_GRAIN_LABELS[grain as keyof typeof EVIDENCE_GRAIN_LABELS] ??
                  grain}
              </td>
              <td className="num">{formatCompact(demand)}</td>
              <td className="num">
                {((demand / summary.demandTotal) * 100).toFixed(1)}%
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>Confidence tier</h3>
      <table>
        <tbody>
          {(["A", "B", "C"] as Tier[]).map((tier) => (
            <tr key={tier}>
              <td>
                <span className={`tier ${tier.toLowerCase()}`} title={TIER_DESCRIPTIONS[tier]}>
                  <span className="dot" />
                  {TIER_LABELS[tier]}
                </span>
              </td>
              <td className="num">{formatCompact(summary.byTier[tier])}</td>
              <td className="num">
                {((summary.byTier[tier] / summary.demandTotal) * 100).toFixed(1)}%
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="sub" style={{ marginTop: "0.5rem", fontSize: "0.75rem" }}>
        Cells are drawn more faintly as confidence falls, so a modeled estimate never
        carries the same visual weight as an anchored one.
      </p>
    </>
  );
}
