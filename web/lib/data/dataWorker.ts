/**
 * Artifact decoding, off the main thread.
 *
 * Decoding a 3 MB parquet and materialising 53,208 rows costs enough main-thread time to
 * dominate time-to-interactive: measured against the §11.3 3-second budget, doing it on the
 * main thread gave 4.94 s under a 4x CPU slowdown and 29.2 s on simulated slow 4G, with
 * largest-contentful-paint pinned to time-to-interactive because nothing meaningful painted
 * until the parse finished.
 *
 * Two things fix that, and both are here:
 *
 * 1. the decode happens in a worker, so the main thread stays free to respond;
 * 2. the result crosses as **columnar typed arrays**, transferred rather than copied, so
 *    53,208 objects are never allocated at all. The views build what they need from the
 *    columns directly.
 */

import { parquetReadObjects } from "hyparquet";
import { compressors } from "hyparquet-compressors";

export interface DecodeRequest {
  readonly kind: "decode";
  readonly url: string;
  readonly columns: string[];
  /** Columns to keep as strings. Everything else becomes a Float64Array. */
  readonly stringColumns: string[];
  /** Columns to keep as booleans, packed into a Uint8Array. */
  readonly boolColumns: string[];
}

export interface DecodedMessage {
  readonly kind: "decoded";
  readonly url: string;
  readonly length: number;
  readonly numeric: Record<string, Float64Array>;
  readonly text: Record<string, string[]>;
  readonly flags: Record<string, Uint8Array>;
}

export interface DecodeFailed {
  readonly kind: "failed";
  readonly url: string;
  readonly message: string;
}

export type WorkerOutgoing = DecodedMessage | DecodeFailed;

self.onmessage = async (event: MessageEvent<DecodeRequest>) => {
  const { url, columns, stringColumns, boolColumns } = event.data;
  const post = (message: WorkerOutgoing, transfer: Transferable[] = []) =>
    (self as unknown as Worker).postMessage(message, transfer);
  try {
    const response = await fetch(url);
    if (!response.ok) {
      post({ kind: "failed", url, message: `${url} unavailable (HTTP ${response.status})` });
      return;
    }
    const file = await response.arrayBuffer();
    const rows = (await parquetReadObjects({
      file,
      compressors,
      columns: [...columns],
    })) as Record<string, unknown>[];

    const strings = new Set(stringColumns);
    const flagsSet = new Set(boolColumns);
    const numeric: Record<string, Float64Array> = {};
    const text: Record<string, string[]> = {};
    const flags: Record<string, Uint8Array> = {};
    for (const name of columns) {
      if (strings.has(name)) {
        text[name] = rows.map((row) => String(row[name] ?? ""));
      } else if (flagsSet.has(name)) {
        const packed = new Uint8Array(rows.length);
        for (let i = 0; i < rows.length; i += 1) packed[i] = row_true(rows[i]?.[name]) ? 1 : 0;
        flags[name] = packed;
      } else {
        const values = new Float64Array(rows.length);
        for (let i = 0; i < rows.length; i += 1) values[i] = to_number(rows[i]?.[name]);
        numeric[name] = values;
      }
    }
    post(
      { kind: "decoded", url, length: rows.length, numeric, text, flags },
      [...Object.values(numeric).map((a) => a.buffer),
       ...Object.values(flags).map((a) => a.buffer)],
    );
  } catch (error) {
    post({
      kind: "failed", url,
      message: error instanceof Error ? error.message : String(error),
    });
  }
};

function to_number(value: unknown): number {
  if (typeof value === "number") return value;
  if (typeof value === "bigint") return Number(value);
  return Number.NaN;
}

function row_true(value: unknown): boolean {
  return value === true || value === 1 || value === "true";
}
