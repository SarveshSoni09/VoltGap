/**
 * Colour scales, and the rule that keeps confidence visible.
 *
 * §11.1: "Confidence tier is always visible via opacity or hatching." That is implemented
 * here as opacity, so it cannot be forgotten by a caller - `cellColor` takes the tier and
 * there is no overload that omits it.
 */

import type { Tier } from "./vocabulary";

/** Perceptually ordered, colour-blind-safe sequential ramp (viridis-like, 6 stops). */
const RAMP: readonly [number, number, number][] = [
  [68, 1, 84],
  [72, 40, 120],
  [62, 74, 137],
  [49, 104, 142],
  [38, 130, 142],
  [253, 231, 37],
];

/**
 * Opacity by tier. **No longer used to draw the map**, and kept because the exporters and
 * the vocabulary tests still describe the tiers.
 *
 * Encoding reliability as transparency was a mistake: it made a low-reliability estimate
 * fade toward the background, which is also what 78.8% of the country looks like — the
 * land with no cell at all. A reader could not tell "we are unsure" from "nobody lives
 * here". Reliability is now reported separately, in the sidebar and on hover, and the
 * underlying confidence values are unchanged.
 */
export const TIER_OPACITY: Record<Tier, number> = { A: 235, B: 175, C: 105 };

/** One opacity for every drawn cell, so colour means the metric and only the metric. */
export const CELL_ALPHA = 215;

/**
 * How solid the analytical surface is at a given zoom.
 *
 * One fill treatment cannot serve the whole range. At national zoom the reader is looking
 * for a regional pattern and needs state borders and big-city labels to place it, so the
 * surface steps back. Zoomed in they are reading one area's value and the individual cell
 * should dominate, with local roads and place names still legible through it.
 *
 * Applied as a deck.gl layer uniform, never baked into the colour buffer: re-expanding
 * 370,384 vertices on every zoom change is exactly the per-frame work that cost 26 fps
 * once already.
 *
 * The floor is 0.55 rather than something fainter because the metric has to stay readable
 * — the fix for an overpowering overlay is putting the labels above it, not making the
 * data too faint to read.
 */
export function analyticalOpacity(zoom: number): number {
  if (!Number.isFinite(zoom)) return 0.72;
  if (zoom <= 4) return 0.55;
  if (zoom >= 9) return 0.88;
  // Linear between the anchors rather than a step, so the change reads as the map
  // settling rather than as a redraw. It is applied when the zoom settles, not per frame.
  return 0.55 + ((zoom - 4) / 5) * (0.88 - 0.55);
}

export function rampColor(t: number): [number, number, number] {
  const clamped = Number.isFinite(t) ? Math.min(1, Math.max(0, t)) : 0;
  const scaled = clamped * (RAMP.length - 1);
  const lower = Math.floor(scaled);
  const upper = Math.min(RAMP.length - 1, lower + 1);
  const frac = scaled - lower;
  const a = RAMP[lower] ?? RAMP[0]!;
  const b = RAMP[upper] ?? RAMP[RAMP.length - 1]!;
  return [
    Math.round(a[0] + (b[0] - a[0]) * frac),
    Math.round(a[1] + (b[1] - a[1]) * frac),
    Math.round(a[2] + (b[2] - a[2]) * frac),
  ];
}

/**
 * Colour for one cell: the metric, at a constant opacity.
 *
 * Reliability is deliberately NOT encoded here. See `TIER_OPACITY` for why, and the
 * sidebar's "How reliable are these estimates?" for where it went.
 */
export function cellColor(t: number): [number, number, number, number] {
  const [r, g, b] = rampColor(t);
  return [r, g, b, CELL_ALPHA];
}

/**
 * Quantile breaks. Demand and access distance are both heavily skewed, so a linear scale
 * renders almost everything as the bottom colour and hides the variation that matters.
 */
export function quantileScale(values: readonly number[]): (value: number) => number {
  const sorted = values.filter(Number.isFinite).slice().sort((a, b) => a - b);
  if (sorted.length === 0) return () => 0;
  return (value: number) => {
    if (!Number.isFinite(value)) return 0;
    let low = 0;
    let high = sorted.length;
    while (low < high) {
      const mid = (low + high) >> 1;
      if ((sorted[mid] ?? 0) < value) low = mid + 1;
      else high = mid;
    }
    return low / sorted.length;
  };
}

export function formatCompact(value: number): string {
  if (!Number.isFinite(value)) return "—";
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  if (abs >= 10) return value.toFixed(0);
  return value.toFixed(2);
}

/**
 * A physical count, written the way a count is written.
 *
 * `formatCompact` shows two decimals below 10, which is right for a modelled quantity like
 * estimated vehicles and wrong for ports: a tooltip reading "Fast-charging ports 0.00"
 * describes a thing that is counted, not measured, and says "none" the long way round.
 */
export function formatCount(value: number, none = "none"): string {
  if (!Number.isFinite(value)) return "\u2014";
  if (value === 0) return none;
  if (Math.abs(value) >= 1_000) return formatCompact(value);
  return value.toFixed(0);
}
