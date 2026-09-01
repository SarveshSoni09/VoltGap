/** Client for the geometry worker. One worker, reused across views. */

import type { BoundaryRequest, BoundaryResult } from "./geometryWorker";

let worker: Worker | null = null;

export interface Boundaries {
  readonly length: number;
  readonly positions: Float64Array;
  readonly startIndices: Uint32Array;
}

export function cellBoundaries(cells: readonly string[]): Promise<Boundaries> {
  worker ??= new Worker(new URL("./geometryWorker.ts", import.meta.url), {
    type: "module",
  });
  const instance = worker;
  return new Promise((resolve) => {
    const listener = (event: MessageEvent<BoundaryResult>) => {
      instance.removeEventListener("message", listener);
      resolve(event.data);
    };
    instance.addEventListener("message", listener);
    const request: BoundaryRequest = { kind: "boundaries", cells: [...cells] };
    instance.postMessage(request);
  });
}
