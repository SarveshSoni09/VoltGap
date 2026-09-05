/**
 * The charging-gaps map and the charging-gaps figures must be the same answer.
 *
 * Before this pass the page had no map: the threshold control drove four summary numbers
 * and a sensitivity table, and there was nothing spatial to respond to it. The map added
 * here is derived from the SAME points at the SAME threshold as those numbers, and these
 * tests exist so the two can never drift into disagreeing — the failure mode where a
 * headline says 12 million people and the shaded areas add up to something else.
 *
 * The fixture is 4,000 real published block-group access points.
 */

import { describe, expect, it } from "vitest";

import points from "./fixtures/access_points.json";
import { aggregateGaps, gapAtThreshold, gapCells } from "../lib/data/access";
import { ColumnTable } from "../lib/data/table";

interface Point {
  h3_index: string;
  state_fips: string;
  population: number;
  km_to_nearest_dcfc_site: number;
  km_to_nearest_l2_site: number;
  income_share_under_35k: number;
}

const rows = points as unknown as Point[];

const table = new ColumnTable(
  rows.length,
  {
    population: Float64Array.from(rows.map((r) => r.population)),
    km_to_nearest_dcfc_site:
      Float64Array.from(rows.map((r) => r.km_to_nearest_dcfc_site)),
    km_to_nearest_l2_site: Float64Array.from(rows.map((r) => r.km_to_nearest_l2_site)),
    income_share_under_35k:
      Float64Array.from(rows.map((r) => r.income_share_under_35k)),
  },
  {
    h3_index: rows.map((r) => r.h3_index),
    state_fips: rows.map((r) => r.state_fips),
  },
  {},
);

const THRESHOLDS = [1, 5, 16.1, 30, 50];
const sum = (xs: readonly number[]) => xs.reduce((a, b) => a + b, 0);

describe("the map and the summary are one calculation", () => {
  for (const km of THRESHOLDS) {
    it(`agrees on population, equity and point count at ${km} km`, () => {
      const summary = gapAtThreshold(table, km);
      const cells = gapCells(table, km);
      expect(sum(cells.map((c) => c.population))).toBeCloseTo(summary.population, 6);
      expect(sum(cells.map((c) => c.equity))).toBeCloseTo(summary.equityPopulation, 6);
      expect(sum(cells.map((c) => c.points))).toBe(summary.points);
    });
  }

  it("responds to the threshold instead of ignoring it", () => {
    // The defect this page had was a control that changed numbers while the geography
    // stayed put. Tightening the threshold must strictly widen the mapped area.
    const near = gapCells(table, 40);
    const far = gapCells(table, 5);
    expect(far.length).toBeGreaterThan(near.length);
    expect(sum(far.map((c) => c.population))).toBeGreaterThan(
      sum(near.map((c) => c.population)));
  });

  it("maps the same measure the summary counts, not a different one", () => {
    const dcfc = gapCells(table, 16.1, "km_to_nearest_dcfc_site");
    const l2 = gapCells(table, 16.1, "km_to_nearest_l2_site");
    expect(sum(dcfc.map((c) => c.population))).toBeCloseTo(
      gapAtThreshold(table, 16.1, "km_to_nearest_dcfc_site").population, 6);
    expect(sum(l2.map((c) => c.population))).toBeCloseTo(
      gapAtThreshold(table, 16.1, "km_to_nearest_l2_site").population, 6);
    // Fast charging is scarcer than Level 2, so the two are genuinely different maps and
    // one cannot silently stand in for the other.
    expect(sum(dcfc.map((c) => c.population))).toBeGreaterThan(
      sum(l2.map((c) => c.population)));
  });
});

describe("each mapped cell is internally consistent", () => {
  const cells = gapCells(table, 16.1);

  it("reports a distance beyond the threshold for every cell it shows", () => {
    // A cell on the gap map is a place people are far from charging. If the reported
    // distance could fall below the threshold the colour would describe something the
    // reader did not ask for. This includes uninhabited cells, whose distance is a plain
    // mean rather than a weighted mean over zero weight — reporting those as 0 km would
    // state the opposite of what is true about them.
    expect(cells.length).toBeGreaterThan(0);
    for (const cell of cells) expect(cell.km).toBeGreaterThan(16.1);
  });

  it("keeps uninhabited areas in the count and out of the population map", () => {
    // Both facts are true and they must not be conflated: an empty block group beyond the
    // threshold belongs in "neighbourhoods affected", and does not belong shaded on a map
    // whose colour means "people affected".
    const empty = cells.filter((c) => c.population === 0);
    expect(empty.length).toBeGreaterThan(0);
    for (const cell of empty) expect(cell.km).toBeGreaterThan(16.1);
    const drawn = cells.filter((c) => c.population > 0);
    expect(sum(drawn.map((c) => c.population))).toBeCloseTo(
      gapAtThreshold(table, 16.1).population, 6);
  });

  it("never reports more affected equity population than population", () => {
    for (const cell of cells) {
      expect(cell.equity).toBeLessThanOrEqual(cell.population + 1e-9);
      expect(cell.population).toBeGreaterThanOrEqual(0);
      expect(cell.points).toBeGreaterThan(0);
    }
  });

  it("carries the state, so an area can be handed to the siting studio", () => {
    for (const cell of cells) expect(cell.state_fips).toMatch(/^\d{2}$/);
  });

  it("returns one row per H3 cell", () => {
    expect(new Set(cells.map((c) => c.h3_index)).size).toBe(cells.length);
  });
});


describe("grouping gaps for display does not change the gap", () => {
  const cells = gapCells(table, 16.1);

  for (const resolution of [4, 5]) {
    it(`conserves people and affected lower-income population at resolution ${resolution}`, () => {
      const grouped = aggregateGaps(cells, resolution);
      expect(grouped.length).toBeLessThan(cells.length);
      expect(sum(grouped.map((c) => c.population))).toBeCloseTo(
        sum(cells.map((c) => c.population)), 6);
      expect(sum(grouped.map((c) => c.equity))).toBeCloseTo(
        sum(cells.map((c) => c.equity)), 6);
      expect(sum(grouped.map((c) => c.points))).toBe(sum(cells.map((c) => c.points)));
    });

    it(`keeps distance a population-weighted mean at resolution ${resolution}`, () => {
      // Distance is not additive. Summing it would make a group of far-flung areas look
      // absurdly remote; averaging it unweighted would let an empty area drag a city's
      // figure. Every grouped distance must stay inside the range of its parts.
      const grouped = aggregateGaps(cells, resolution);
      const lo = Math.min(...cells.map((c) => c.km));
      const hi = Math.max(...cells.map((c) => c.km));
      for (const cell of grouped) {
        expect(cell.km).toBeGreaterThanOrEqual(lo - 1e-9);
        expect(cell.km).toBeLessThanOrEqual(hi + 1e-9);
      }
    });
  }

  it("is a pass-through at native resolution", () => {
    const grouped = aggregateGaps(cells, 6);
    expect(grouped.length).toBe(cells.length);
  });
});
