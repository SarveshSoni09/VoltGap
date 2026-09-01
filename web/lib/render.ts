/**
 * Turning per-cell colours into the per-vertex buffer deck.gl's binary path requires.
 *
 * **Why per-vertex.** A binary attribute on `SolidPolygonLayer` is read per *vertex*, not
 * per *polygon*. Supplying one RGBA per cell produced a buffer a seventh of the length the
 * layer expected, and deck.gl read colours from the wrong offsets — the visible symptom
 * was polygons rendering black. Nothing warned; the layer reported the right feature count
 * throughout.
 *
 * **Why `_normalize` is left at its default.** The first version of this path set
 * `_normalize: false`, on the reasoning that H3 rings arrive already closed so the
 * normalisation step is redundant. It is documented as valid for closed rings, and the
 * rings *are* closed — `cellToBoundary(cell, true)` returns 7 points for a hexagon with the
 * first repeated last. But with it set, deck.gl produced **no geometry at all**: the layer
 * attached, reported 53,208 features, held valid coordinates, had non-zero alpha on every
 * cell, and drew nothing. Removing it fixes it. Both facts were established by isolating
 * one variable at a time against the identical coordinate buffers; see the Phase 6 report.
 */

import type { Boundaries } from "./data/geometry";

export type Rgba = readonly [number, number, number, number];

/**
 * Expand a per-cell colour function into the per-vertex `Uint8Array` the layer reads.
 *
 * `boundaries.startIndices` is CSR-style with `length + 1` entries, so cell `i` owns the
 * vertices `[startIndices[i], startIndices[i + 1])`.
 */
export function perVertexColors(
  boundaries: Boundaries,
  colorAt: (cell: number) => Rgba,
): Uint8Array {
  const vertices = boundaries.positions.length / 2;
  const out = new Uint8Array(vertices * 4);
  for (let cell = 0; cell < boundaries.length; cell += 1) {
    const [r, g, b, a] = colorAt(cell);
    const from = boundaries.startIndices[cell] ?? 0;
    const to = boundaries.startIndices[cell + 1] ?? from;
    for (let vertex = from; vertex < to; vertex += 1) {
      const at = vertex * 4;
      out[at] = r;
      out[at + 1] = g;
      out[at + 2] = b;
      out[at + 3] = a;
    }
  }
  return out;
}
