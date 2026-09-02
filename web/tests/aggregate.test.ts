/**
 * The national view aggregates for display. It must not change what is displayed.
 *
 * Aggregation exists because 53,208 resolution-6 cells read as scattered dots at national
 * zoom, not because the analytical surface is wrong. So the property that matters is
 * conservation: rolling up must not create, destroy or move any additive quantity.
 */

import { describe, expect, it } from "vitest";
import { cellToParent, getResolution } from "h3-js";

import cells from "./fixtures/national_cells.json";
import {
  NATIVE_RESOLUTION,
  aggregate,
  displayResolution,
  type NativeCell,
} from "../lib/aggregate";

const native = cells as unknown as NativeCell[];
const sum = (xs: readonly number[]) => xs.reduce((a, b) => a + b, 0);

describe("the fixture is the real published surface", () => {
  it("is native resolution 6", () => {
    expect(native.length).toBe(6000);
    for (const cell of native.slice(0, 200)) {
      expect(getResolution(cell.h3_index)).toBe(NATIVE_RESOLUTION);
    }
  });
});

describe("conservation of additive quantities", () => {
  for (const resolution of [3, 4, 5]) {
    it(`preserves demand exactly at resolution ${resolution}`, () => {
      const rolled = aggregate(native, resolution);
      expect(sum(rolled.map((c) => c.demand_bev))).toBeCloseTo(
        sum(native.map((c) => c.demand_bev)),
        6,
      );
    });

    it(`preserves population, underserved population and ports at resolution ${resolution}`, () => {
      const rolled = aggregate(native, resolution);
      expect(sum(rolled.map((c) => c.population))).toBeCloseTo(
        sum(native.map((c) => c.population)), 4);
      expect(sum(rolled.map((c) => c.equity_population))).toBeCloseTo(
        sum(native.map((c) => c.equity_population)), 4);
      expect(sum(rolled.map((c) => c.dcfc_ports))).toBeCloseTo(
        sum(native.map((c) => c.dcfc_ports)), 4);
    });

    it(`accounts for every native cell exactly once at resolution ${resolution}`, () => {
      const rolled = aggregate(native, resolution);
      expect(sum(rolled.map((c) => c.children))).toBe(native.length);
      // And it genuinely coarsens, or it is not doing its job.
      expect(rolled.length).toBeLessThan(native.length);
      for (const cell of rolled) {
        expect(getResolution(cell.h3_index)).toBe(resolution);
      }
    });

    it(`puts every cell under its own H3 parent at resolution ${resolution}`, () => {
      const rolled = new Map(aggregate(native, resolution).map((c) => [c.h3_index, c]));
      for (const cell of native.slice(0, 500)) {
        expect(rolled.has(cellToParent(cell.h3_index, resolution))).toBe(true);
      }
    });
  }

  it("is a no-op at native resolution, so nothing is paid for nothing", () => {
    const rolled = aggregate(native, NATIVE_RESOLUTION);
    expect(rolled.length).toBe(native.length);
    expect(sum(rolled.map((c) => c.demand_bev))).toBeCloseTo(
      sum(native.map((c) => c.demand_bev)), 6);
  });
});

describe("quantities that are not additive are not summed", () => {
  it("reports distance as a population-weighted mean, within the native range", () => {
    const rolled = aggregate(native, 4);
    const finite = native
      .filter((c) => Number.isFinite(c.km_to_nearest_dcfc_site))
      .map((c) => c.km_to_nearest_dcfc_site);
    const max = Math.max(...finite);
    for (const cell of rolled) {
      // A mean can never exceed the largest value it averages. Summing would.
      expect(cell.km_to_nearest_dcfc_site).toBeLessThanOrEqual(max + 1e-6);
      expect(cell.km_to_nearest_dcfc_site).toBeGreaterThanOrEqual(0);
    }
  });

  it("keeps anchored share and uncertainty as shares, never sums", () => {
    for (const cell of aggregate(native, 4)) {
      expect(cell.sub_state_anchored_share).toBeGreaterThanOrEqual(0);
      expect(cell.sub_state_anchored_share).toBeLessThanOrEqual(1);
      expect(cell.uncertainty_score).toBeGreaterThanOrEqual(0);
      expect(cell.uncertainty_score).toBeLessThanOrEqual(1);
    }
  });
});

describe("display resolution by zoom", () => {
  it("coarsens at national zoom and is native when zoomed in", () => {
    expect(displayResolution(3)).toBeLessThan(NATIVE_RESOLUTION);
    expect(displayResolution(4)).toBeLessThan(NATIVE_RESOLUTION);
    expect(displayResolution(8)).toBe(NATIVE_RESOLUTION);
    expect(displayResolution(12)).toBe(NATIVE_RESOLUTION);
  });

  it("never coarsens as you zoom in", () => {
    let previous = 0;
    for (let zoom = 2; zoom <= 12; zoom += 0.5) {
      const resolution = displayResolution(zoom);
      expect(resolution).toBeGreaterThanOrEqual(previous);
      previous = resolution;
    }
  });

  it("never exceeds the analytical resolution", () => {
    for (let zoom = 0; zoom <= 20; zoom += 1) {
      expect(displayResolution(zoom)).toBeLessThanOrEqual(NATIVE_RESOLUTION);
    }
  });
});
