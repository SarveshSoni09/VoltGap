/**
 * The geography control.
 *
 * Selecting a state filters the analysis on both map pages, which makes two things
 * testable: that the control can only ever offer geographies the data actually contains,
 * and that a state's frame is derived from the cells the page will draw for it. The
 * analytical parity (a state's figures equalling the aggregate of its displayed cells)
 * is asserted in `access.test.ts` against real published points.
 */

import { describe, expect, it } from "vitest";

import {
  boundsOf, geographyLabel, NATIONAL, scopedLabel, statesPresent, STATE_NAMES_BY_CODE,
  US_BOUNDS,
} from "../lib/geography";
import { analyticalOpacity } from "../lib/scales";

describe("the control offers only geographies the data contains", () => {
  it("lists each state once, alphabetically by name", () => {
    const options = statesPresent(
      ["53", "06", "53", "48", "06"],
      ["WA", "CA", "WA", "TX", "CA"],
    );
    expect(options.map((o) => o.name)).toEqual(["California", "Texas", "Washington"]);
    expect(options.map((o) => o.fips)).toEqual(["06", "48", "53"]);
  });

  it("skips a FIPS whose code it cannot name rather than showing a bare number", () => {
    // A territory or a malformed row must not become an option labelled "78".
    const options = statesPresent(["53", "78"], ["WA", "VI"]);
    expect(options.map((o) => o.code)).toEqual(["WA"]);
  });

  it("skips blank codes and blank FIPS", () => {
    expect(statesPresent(["", "53"], ["WA", ""])).toEqual([]);
  });

  it("returns nothing for empty columns", () => {
    expect(statesPresent([], [])).toEqual([]);
  });

  it("names every state the published surface can carry", () => {
    // 50 states, DC and Puerto Rico. A missing entry silently drops that state from the
    // control, which is the failure this asserts against.
    expect(Object.keys(STATE_NAMES_BY_CODE)).toHaveLength(52);
    expect(STATE_NAMES_BY_CODE.WA).toBe("Washington");
    expect(STATE_NAMES_BY_CODE.DC).toBe("District of Columbia");
  });
});

describe("the frame around a geography", () => {
  it("covers every point, with padding", () => {
    const b = boundsOf([
      { longitude: -122.3, latitude: 47.6 },
      { longitude: -117.4, latitude: 46.7 },
    ], 0.5);
    expect(b).not.toBeNull();
    expect(b!.west).toBeCloseTo(-122.8, 6);
    expect(b!.east).toBeCloseTo(-116.9, 6);
    expect(b!.south).toBeCloseTo(46.2, 6);
    expect(b!.north).toBeCloseTo(48.1, 6);
  });

  it("is null for an empty set rather than a frame around nothing", () => {
    expect(boundsOf([])).toBeNull();
  });

  it("ignores non-finite coordinates instead of producing an infinite frame", () => {
    const b = boundsOf([
      { longitude: Number.NaN, latitude: 1 },
      { longitude: -100, latitude: 40 },
    ], 0);
    expect(b).toEqual({ west: -100, south: 40, east: -100, north: 40 });
  });

  it("is null when no coordinate is usable", () => {
    expect(boundsOf([{ longitude: Number.NaN, latitude: Number.NaN }])).toBeNull();
  });

  it("reaches Alaska and Hawaii when returning to the national view", () => {
    // Both are in the published surface, so "Reset to U.S." must not frame the lower 48.
    expect(US_BOUNDS.west).toBeLessThan(-160);
    expect(US_BOUNDS.north).toBeGreaterThan(60);
    expect(US_BOUNDS.south).toBeLessThan(20);
  });
});

describe("scope is stated, because scope changes the mathematics", () => {
  const wa = { fips: "53", code: "WA", name: "Washington" };

  it("names the nation when nothing is selected", () => {
    expect(geographyLabel(null)).toBe("the United States");
    expect(scopedLabel("Most people affected", null))
      .toBe("Most people affected nationally");
  });

  it("names the state when one is selected", () => {
    expect(geographyLabel(wa)).toBe("Washington");
    expect(scopedLabel("Most people affected", wa))
      .toBe("Most people affected in Washington");
  });

  it("never renders the national sentinel as a state code", () => {
    expect(NATIONAL).toBe("US");
    expect(STATE_NAMES_BY_CODE[NATIONAL]).toBeUndefined();
  });
});

describe("zoom-dependent fill keeps both layers readable", () => {
  it("steps back at national zoom so borders and city labels can be read", () => {
    expect(analyticalOpacity(3.4)).toBeCloseTo(0.55, 6);
  });

  it("becomes dominant when the reader is examining one area", () => {
    expect(analyticalOpacity(11)).toBeCloseTo(0.88, 6);
  });

  it("rises monotonically between the anchors", () => {
    const zooms = [4, 5, 6, 7, 8, 9];
    const values = zooms.map(analyticalOpacity);
    for (let i = 1; i < values.length; i += 1) {
      expect(values[i]!).toBeGreaterThan(values[i - 1]!);
    }
  });

  it("never becomes so faint that the metric stops being readable", () => {
    // The fix for an overpowering overlay was the layer order, not fading the data out.
    for (const z of [0, 1, 3, 5, 8, 12, 20]) {
      expect(analyticalOpacity(z)).toBeGreaterThanOrEqual(0.55);
      expect(analyticalOpacity(z)).toBeLessThanOrEqual(0.88);
    }
  });

  it("degrades to a usable value on a non-finite zoom", () => {
    expect(analyticalOpacity(Number.NaN)).toBeCloseTo(0.72, 6);
  });
});
