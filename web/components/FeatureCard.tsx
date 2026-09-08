"use client";

/**
 * One information pattern for a selected place, used by every map in the product.
 *
 * The shape is fixed so a reader learns it once: **where this is**, then **the number that
 * matters on this page**, then a little supporting context, then how reliable it is, then
 * what they can do next. Only the primary metric changes between views.
 *
 * Deliberately small. The point of this pass was to make the maps explorable, not to move
 * the sidebar into a tooltip, so anything that is not needed to decide: H3 indexes, exact
 * uncertainty scores, provenance: sits behind "Technical details".
 */

export interface FeatureFact {
  readonly label: string;
  readonly value: string;
}

export interface FeatureCardProps {
  /** "Pierce County, WA": the same identity the tables use for the same cell. */
  readonly place: string;
  /** Optional finer context, e.g. "Near Tacoma". Omitted when not defensible. */
  readonly near?: string;
  readonly primaryLabel: string;
  readonly primaryValue: string;
  readonly facts: readonly FeatureFact[];
  /**
   * How much to trust the number above. `tier` is §7.4.2's published tier and is omitted
   * where the pipeline published no single tier for what is being shown, rather than
   * having one guessed in the interface.
   */
  readonly reliability?: { readonly label: string; readonly tier?: "A" | "B" | "C" };
  readonly reasons?: readonly string[];
  readonly technical?: readonly FeatureFact[];
  readonly actions?: React.ReactNode;
  readonly rank?: number;
}

export function FeatureCard({
  place, near, primaryLabel, primaryValue, facts, reliability, reasons, technical,
  actions, rank,
}: FeatureCardProps) {
  return (
    <div className="fcard">
      <div className="fcard-place">
        {rank !== undefined && <span className="fcard-rank">{rank}</span>}
        <div>
          {near !== undefined && <div className="fcard-near">{near}</div>}
          <div className="fcard-name">{place}</div>
        </div>
      </div>

      <div className="fcard-primary">
        <div className="fcard-plabel">{primaryLabel}</div>
        <div className="fcard-pvalue">{primaryValue}</div>
      </div>

      {facts.length > 0 && (
        <dl className="fcard-facts">
          {facts.map((fact) => (
            <div key={fact.label}>
              <dt>{fact.label}</dt>
              <dd>{fact.value}</dd>
            </div>
          ))}
        </dl>
      )}

      {reasons !== undefined && reasons.length > 0 && (
        <div className="fcard-reasons">
          <div className="fcard-rlabel">Why this area</div>
          <ul>
            {reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </div>
      )}

      {reliability !== undefined && (
        <div
          className={
            reliability.tier === undefined
              ? "fcard-rel quiet"
              : `fcard-rel tier ${reliability.tier.toLowerCase()}`
          }
        >
          {reliability.tier !== undefined && <span className="dot" />}
          {reliability.label}
        </div>
      )}

      {technical !== undefined && technical.length > 0 && (
        <details className="fcard-tech">
          <summary>Technical details</summary>
          <dl>
            {technical.map((fact) => (
              <div key={fact.label}>
                <dt>{fact.label}</dt>
                <dd>{fact.value}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}

      {actions !== undefined && <div className="fcard-actions">{actions}</div>}
    </div>
  );
}
