/**
 * A columnar view over a decoded artifact.
 *
 * The worker hands back typed arrays; nothing here materialises a row unless a caller asks
 * for one. 53,208 cells become a handful of `Float64Array`s rather than 53,208 objects,
 * which is most of why the page becomes interactive before the data finishes arriving.
 *
 * `row(i)` exists for the few places that genuinely need an object - the ranked portfolio
 * table is about fifty rows - and is deliberately not used in any loop over the whole set.
 */

import { DATA_BASE } from "./manifest";
import type { DecodeRequest, WorkerOutgoing } from "./dataWorker";

export interface ColumnSpec {
  readonly columns: readonly string[];
  readonly stringColumns: readonly string[];
  readonly boolColumns: readonly string[];
}

export class ColumnTable {
  constructor(
    readonly length: number,
    private readonly numeric: Record<string, Float64Array>,
    private readonly text: Record<string, string[]>,
    private readonly flags: Record<string, Uint8Array>,
  ) {}

  /** A numeric column. Throws rather than returning zeros for a column never requested. */
  nums(name: string): Float64Array {
    const column = this.numeric[name];
    if (column === undefined) {
      throw new Error(`numeric column "${name}" was not decoded`);
    }
    return column;
  }

  strs(name: string): string[] {
    const column = this.text[name];
    if (column === undefined) {
      throw new Error(`string column "${name}" was not decoded`);
    }
    return column;
  }

  bools(name: string): Uint8Array {
    const column = this.flags[name];
    if (column === undefined) {
      throw new Error(`boolean column "${name}" was not decoded`);
    }
    return column;
  }

  has(name: string): boolean {
    return name in this.numeric || name in this.text || name in this.flags;
  }

  /** One row as an object. For small selections only. */
  row(index: number): Record<string, number | string | boolean> {
    const out: Record<string, number | string | boolean> = {};
    for (const [name, column] of Object.entries(this.numeric)) out[name] = column[index] ?? 0;
    for (const [name, column] of Object.entries(this.text)) out[name] = column[index] ?? "";
    for (const [name, column] of Object.entries(this.flags)) out[name] = column[index] === 1;
    return out;
  }
}

/** One worker, reused: spinning one up per artifact would pay the startup cost twice. */
let worker: Worker | null = null;

function decodeWorker(): Worker {
  worker ??= new Worker(new URL("./dataWorker.ts", import.meta.url), { type: "module" });
  return worker;
}

export function loadTable(
  name: string,
  spec: ColumnSpec,
  base: string = DATA_BASE,
): Promise<ColumnTable> {
  const url = `${base}/${name}`;
  return new Promise((resolve, reject) => {
    const instance = decodeWorker();
    const listener = (event: MessageEvent<WorkerOutgoing>) => {
      const message = event.data;
      if (message.url !== url) return; // another artifact's reply on the shared worker
      instance.removeEventListener("message", listener);
      if (message.kind === "failed") {
        reject(new Error(message.message));
        return;
      }
      resolve(
        new ColumnTable(message.length, message.numeric, message.text, message.flags),
      );
    };
    instance.addEventListener("message", listener);
    const request: DecodeRequest = {
      kind: "decode",
      url,
      columns: [...spec.columns],
      stringColumns: [...spec.stringColumns],
      boolColumns: [...spec.boolColumns],
    };
    instance.postMessage(request);
  });
}
