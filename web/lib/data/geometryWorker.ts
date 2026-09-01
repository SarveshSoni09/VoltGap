/**
 * H3 cell boundaries, computed off the main thread and transferred as binary.
 *
 * Three things this buys, all of them measured against §11.3 budgets:
 *
 * 1. **`@deck.gl/geo-layers` is not needed.** Its `H3HexagonLayer` is the only thing this
 *    application used from it, and it exists to do exactly this conversion. Doing it here
 *    lets the map use `SolidPolygonLayer` from `@deck.gl/layers`, which is a materially
 *    smaller dependency to download and parse on a cold load.
 * 2. **No main-thread geometry.** 53,208 cells is ~320,000 vertices; computing them on the
 *    main thread is a long task sitting directly between first paint and interactive.
 * 3. **deck.gl's binary attribute path.** Positions arrive as a `Float64Array` deck can
 *    upload to the GPU without walking 53,208 objects, which is what the sustained
 *    frame-rate budget needs.
 */

import { cellToBoundary } from "h3-js";

export interface BoundaryRequest {
  readonly kind: "boundaries";
  readonly cells: string[];
}

export interface BoundaryResult {
  readonly kind: "boundaries";
  readonly length: number;
  /** Flat [lon, lat, lon, lat, …] over every ring, in cell order. */
  readonly positions: Float64Array;
  /** Vertex index at which each polygon starts; length is `length + 1`. */
  readonly startIndices: Uint32Array;
}

self.onmessage = (event: MessageEvent<BoundaryRequest>) => {
  const { cells } = event.data;
  // An H3 cell is a hexagon, except the twelve pentagons per resolution. Sizing for 6 and
  // growing on demand avoids both a second pass and a wildly oversized buffer.
  const rings = cells.map((cell) => cellToBoundary(cell, true));
  let total = 0;
  for (const ring of rings) total += ring.length;

  const positions = new Float64Array(total * 2);
  const startIndices = new Uint32Array(cells.length + 1);
  let vertex = 0;
  for (let i = 0; i < rings.length; i += 1) {
    startIndices[i] = vertex;
    const ring = rings[i] ?? [];
    for (const point of ring) {
      // cellToBoundary(cell, true) yields [lng, lat], which is the order deck.gl wants.
      positions[vertex * 2] = point[0] ?? 0;
      positions[vertex * 2 + 1] = point[1] ?? 0;
      vertex += 1;
    }
  }
  startIndices[cells.length] = vertex;

  const result: BoundaryResult = {
    kind: "boundaries",
    length: cells.length,
    positions,
    startIndices,
  };
  (self as unknown as Worker).postMessage(result, [
    positions.buffer,
    startIndices.buffer,
  ]);
};
