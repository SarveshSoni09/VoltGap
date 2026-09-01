/**
 * The columnar store the views read.
 *
 * This exists because moving decoding into a worker and rows into typed arrays was done to
 * meet a performance budget, and a change made for speed is exactly the kind that quietly
 * loses correctness. These check the store returns what was put in, and that a column
 * nobody asked to decode fails loudly rather than reading as zeros.
 */

import { describe, expect, it } from "vitest";

import { ColumnTable } from "../lib/table-testing";

const table = new ColumnTable(
  3,
  { demand_bev: Float64Array.from([10, 20, 30]) },
  { h3_index: ["a", "b", "c"], confidence_tier: ["A", "B", "C"] },
  { passes_road_filter: Uint8Array.from([1, 0, 1]) },
);

describe("ColumnTable", () => {
  it("returns numeric, string and boolean columns as stored", () => {
    expect(Array.from(table.nums("demand_bev"))).toEqual([10, 20, 30]);
    expect(table.strs("h3_index")).toEqual(["a", "b", "c"]);
    expect(Array.from(table.bools("passes_road_filter"))).toEqual([1, 0, 1]);
  });

  it("fails loudly on a column that was never decoded", () => {
    // Reading as zeros would render a blank metric that looks like real data.
    expect(() => table.nums("population")).toThrow(/was not decoded/);
    expect(() => table.strs("state_fips")).toThrow(/was not decoded/);
    expect(() => table.bools("nope")).toThrow(/was not decoded/);
  });

  it("reports which columns it holds", () => {
    expect(table.has("demand_bev")).toBe(true);
    expect(table.has("h3_index")).toBe(true);
    expect(table.has("passes_road_filter")).toBe(true);
    expect(table.has("population")).toBe(false);
  });

  it("materialises a single row for the few places that need one", () => {
    expect(table.row(1)).toEqual({
      demand_bev: 20,
      h3_index: "b",
      confidence_tier: "B",
      passes_road_filter: false,
    });
  });
});
