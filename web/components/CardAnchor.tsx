"use client";

/**
 * Positions a {@link FeatureCard} over a map.
 *
 * Two modes, one component, because the alternative: a hover tooltip in one file and a
 * details panel in another: is how a product ends up with three information patterns that
 * disagree. Hovering floats the card by the cursor; clicking pins it to the corner, where
 * it can hold actions the reader has time to click.
 */

import type React from "react";

export interface CardAnchorProps {
  readonly pinned: boolean;
  /** Cursor position in map-container pixels; ignored when pinned. */
  readonly x: number;
  readonly y: number;
  readonly onClose?: () => void;
  readonly children: React.ReactNode;
}

/** Keeps the floating card inside the viewport instead of off the right-hand edge. */
const CARD_WIDTH = 268;
const EDGE_PAD = 16;

export function CardAnchor({ pinned, x, y, onClose, children }: CardAnchorProps) {
  if (pinned) {
    return (
      <div className="card-anchor pinned">
        {onClose !== undefined && (
          <button type="button" className="card-close" onClick={onClose}>
            Close
          </button>
        )}
        {children}
      </div>
    );
  }
  const flip = typeof window !== "undefined" && x + CARD_WIDTH + EDGE_PAD > window.innerWidth;
  return (
    <div
      className="card-anchor floating"
      style={{
        left: flip ? undefined : x + 14,
        right: flip ? EDGE_PAD : undefined,
        top: Math.max(EDGE_PAD, y - 12),
      }}
    >
      {children}
    </div>
  );
}
