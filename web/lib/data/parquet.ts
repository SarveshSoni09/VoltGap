/**
 * Reading the published parquet artifacts in the browser.
 *
 * `hyparquet` is a dependency-free reader that supports **column projection**, which is
 * the whole reason the artifacts are parquet rather than JSON: the National Overview shows
 * one metric at a time, so it fetches that column's byte ranges instead of a 2.79 MB file
 * for every metric switch (§12 notes HTTP range requests).
 */

import { parquetReadObjects } from "hyparquet";
import { compressors } from "hyparquet-compressors";

import { DATA_BASE } from "./manifest";

/** A row of an artifact, as read. Values are numbers, strings or booleans. */
export type Row = Record<string, unknown>;

/**
 * Fetch one artifact, optionally projecting columns.
 *
 * The whole file is fetched here rather than served through range requests, because a
 * static host is not guaranteed to honour `Range` and a silent full fetch that the code
 * believed was a range read would be a performance claim that is not true. The projection
 * still matters: it bounds decode cost and the memory the page holds.
 */
export async function readArtifact(
  name: string,
  columns?: readonly string[],
  base: string = DATA_BASE,
): Promise<Row[]> {
  const response = await fetch(`${base}/${name}`);
  if (!response.ok) {
    throw new Error(`${name} unavailable (HTTP ${response.status})`);
  }
  const file = await response.arrayBuffer();
  return (await parquetReadObjects({
    file,
    compressors,
    ...(columns ? { columns: [...columns] } : {}),
  })) as Row[];
}

export function asNumber(value: unknown): number {
  if (typeof value === "number") return value;
  if (typeof value === "bigint") return Number(value);
  return Number.NaN;
}

export function asString(value: unknown): string {
  return typeof value === "string" ? value : String(value ?? "");
}
