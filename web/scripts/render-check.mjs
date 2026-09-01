#!/usr/bin/env node
/**
 * Does the analytical layer actually DRAW?
 *
 * This exists because of a defect that every other check passed: the layer attached,
 * reported all 53,208 cells, held coordinates with valid US bounds, carried non-zero alpha
 * on every cell — and rendered nothing. `__voltgapLayerCells` said 53,208 the whole time.
 * A populated layer is not a visible layer, and only rendered output distinguishes them.
 *
 * **Method: pixel difference, not a golden screenshot.** The same view is rendered twice,
 * once with the analytical layer and once with `?layer=off`, and the two are compared. A
 * golden image would break on a basemap tile change, a font, or a browser update, and
 * would be quietly re-blessed. A difference between two images taken seconds apart on the
 * same machine isolates exactly one variable: the layer.
 *
 * It also holds the structural guards, because a difference alone would not catch
 * geometry drawn in the wrong place:
 *
 *   - polygon count is non-zero and matches the national surface;
 *   - every sampled coordinate lies within the US bounds, including Alaska and Hawaii;
 *   - a continental-US cell has plausible bounds;
 *   - the colour buffer carries visible alpha.
 */

import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

import puppeteer from "puppeteer";

const PORT = Number(process.env.PERF_PORT ?? 4394);
const MIN_CELLS = 50000;
/** Share of map pixels the layer must change. At res 6 the national surface covers the
 *  landmass densely; 2% is far above rendering noise and far below what it actually paints. */
const MIN_CHANGED_SHARE = 0.02;

/**
 * Share of the CHANGED pixels that must actually carry the layer's palette.
 *
 * Pixel count alone is not enough, and this project has the measurement to prove it: with
 * `_normalize: false` the layer drew the whole national surface in WHITE, on a white
 * basemap. That still changed 5.2% of pixels and would have passed a count-only check,
 * while being invisible to a person.
 *
 * The palette is viridis - dark purple through teal to yellow - so every colour it paints
 * is either saturated or dark. White is neither. Measured on this build: the defective
 * white rendering scores 0.009, the correct rendering scores 0.516. The threshold sits
 * between them with an order of magnitude of margin on each side.
 */
const MIN_CHROMATIC_SHARE_OF_CHANGED = 0.20;
/** Bounds for the 50 states, generous enough for Alaska's Aleutian tail and Hawaii. */
const US_BOUNDS = { minLon: -180, maxLon: -64, minLat: 17, maxLat: 72 };
/** A tighter box for the continental-US spot check. */
const CONUS = { minLon: -125, maxLon: -66, minLat: 24, maxLat: 50 };

const server = spawn(
  "node", [fileURLToPath(new URL("../serve-static.mjs", import.meta.url))],
  { env: { ...process.env, PORT: String(PORT) }, stdio: "ignore" },
);
const stop = () => server.kill();
process.on("exit", stop);
await new Promise((resolve) => setTimeout(resolve, 700));

const browser = await puppeteer.launch({
  headless: true,
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--enable-gpu"],
});

let failed = false;
const fail = (message) => {
  console.error(`FAIL: ${message}`);
  failed = true;
};

try {
  const shoot = async (query) => {
    const page = await browser.newPage();
    await page.setViewport({ width: 1400, height: 900, deviceScaleFactor: 1 });
    await page.goto(`http://localhost:${PORT}/${query}`, {
      waitUntil: "networkidle0", timeout: 120000,
    });
    // The map is created only once its container has real layout, and the geometry
    // arrives from a worker after that, so wait for the layer rather than a fixed delay.
    await page
      .waitForFunction(
        () => document.querySelectorAll("canvas").length >= 2,
        { timeout: 120000 },
      )
      .catch(() => undefined);
    await new Promise((resolve) => setTimeout(resolve, 6000));
    const box = await page.evaluate(() => {
      const canvas = document.querySelectorAll("canvas")[1];
      const r = canvas.getBoundingClientRect();
      return { x: r.x, y: r.y, width: r.width, height: r.height };
    });
    const shot = await page.screenshot({ clip: box, type: "png" });
    const state = await page.evaluate(() => {
      const map = window.__voltgapMap;
      const overlay = map ? (map._controls || []).find((c) => c && c._deck) : null;
      const deck = overlay ? overlay._deck : null;
      const layer = deck && deck.props.layers[0];
      if (!layer) return { cells: window.__voltgapLayerCells ?? 0, layer: false };
      const d = layer.props.data;
      const pos = d.attributes.getPolygon.value;
      const col = d.attributes.getFillColor.value;
      let minLon = Infinity, maxLon = -Infinity, minLat = Infinity, maxLat = -Infinity;
      for (let i = 0; i < pos.length; i += 2) {
        const lo = pos[i], la = pos[i + 1];
        if (lo < minLon) minLon = lo;
        if (lo > maxLon) maxLon = lo;
        if (la < minLat) minLat = la;
        if (la > maxLat) maxLat = la;
      }
      let visibleAlpha = 0;
      for (let i = 3; i < col.length; i += 4) if (col[i] > 0) visibleAlpha += 1;
      // One continental-US cell, for the spot check.
      let conus = null;
      for (let c = 0; c < d.length && conus === null; c += 1) {
        const from = d.startIndices[c], to = d.startIndices[c + 1];
        const lon = pos[from * 2], lat = pos[from * 2 + 1];
        if (lon > -125 && lon < -66 && lat > 24 && lat < 50) {
          const ring = [];
          for (let v = from; v < to; v += 1) ring.push([pos[v * 2], pos[v * 2 + 1]]);
          conus = { cell: c, ring };
        }
      }
      return {
        cells: window.__voltgapLayerCells ?? 0, layer: true,
        polygons: d.length, vertices: pos.length / 2,
        colorLength: col.length, visibleAlpha,
        bounds: { minLon, maxLon, minLat, maxLat }, conus,
      };
    });
    await page.close();
    return { shot, box, state };
  };

  console.log("  rendering with the analytical layer…");
  const on = await shoot("");
  console.log("  rendering with ?layer=off…");
  const off = await shoot("?layer=off");

  // --- structural guards -------------------------------------------------------------
  const s = on.state;
  if (!s.layer) fail("no analytical layer was attached at all");
  if (s.polygons < MIN_CELLS) {
    fail(`layer holds ${s.polygons} polygons, fewer than ${MIN_CELLS}`);
  }
  if (s.colorLength !== s.vertices * 4) {
    fail(
      `colour buffer is ${s.colorLength} for ${s.vertices} vertices; deck.gl reads ` +
        "colours PER VERTEX, so it must be vertices * 4",
    );
  }
  if (s.visibleAlpha < MIN_CELLS) {
    fail(`only ${s.visibleAlpha} vertices carry visible alpha`);
  }
  const b = s.bounds;
  if (b.minLon < US_BOUNDS.minLon || b.maxLon > US_BOUNDS.maxLon ||
      b.minLat < US_BOUNDS.minLat || b.maxLat > US_BOUNDS.maxLat) {
    fail(`geometry bounds ${JSON.stringify(b)} fall outside the United States`);
  }
  if (s.conus === null) {
    fail("no cell was found inside the continental US");
  } else {
    const lons = s.conus.ring.map((p) => p[0]);
    const lats = s.conus.ring.map((p) => p[1]);
    const ok = Math.min(...lons) > CONUS.minLon && Math.max(...lons) < CONUS.maxLon &&
      Math.min(...lats) > CONUS.minLat && Math.max(...lats) < CONUS.maxLat;
    console.log(
      `  continental-US spot check: cell ${s.conus.cell}, ${s.conus.ring.length} vertices, ` +
        `lon ${Math.min(...lons).toFixed(3)}..${Math.max(...lons).toFixed(3)}, ` +
        `lat ${Math.min(...lats).toFixed(3)}..${Math.max(...lats).toFixed(3)} — ` +
        `${ok ? "within" : "OUTSIDE"} ${CONUS.minLon}..${CONUS.maxLon} / ${CONUS.minLat}..${CONUS.maxLat}`,
    );
    if (!ok) fail("the continental-US spot-check cell has implausible bounds");
    const first = s.conus.ring[0];
    const last = s.conus.ring[s.conus.ring.length - 1];
    if (first[0] !== last[0] || first[1] !== last[1]) {
      fail("the spot-check ring is not closed");
    }
  }

  // --- the rendering check -----------------------------------------------------------
  const { PNG } = await import("pngjs");
  const a = PNG.sync.read(on.shot);
  const z = PNG.sync.read(off.shot);
  if (a.width !== z.width || a.height !== z.height) {
    fail(`screenshots differ in size: ${a.width}x${a.height} vs ${z.width}x${z.height}`);
  } else {
    let changed = 0;
    let chromatic = 0;
    const total = a.width * a.height;
    for (let i = 0; i < a.data.length; i += 4) {
      const dr = Math.abs(a.data[i] - z.data[i]);
      const dg = Math.abs(a.data[i + 1] - z.data[i + 1]);
      const db = Math.abs(a.data[i + 2] - z.data[i + 2]);
      if (dr + dg + db <= 24) continue;
      changed += 1;
      // Does this pixel carry the palette, or is it white? Viridis is saturated or dark
      // throughout; white is neither.
      const r = a.data[i], g = a.data[i + 1], b2 = a.data[i + 2];
      const mx = Math.max(r, g, b2);
      const mn = Math.min(r, g, b2);
      const saturation = mx === 0 ? 0 : (mx - mn) / mx;
      const luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b2) / 255;
      if (saturation > 0.15 || luminance < 0.6) chromatic += 1;
    }
    const share = changed / total;
    const chromaticShare = changed === 0 ? 0 : chromatic / changed;
    console.log(
      `  rendered difference: ${changed.toLocaleString()} of ${total.toLocaleString()} ` +
        `pixels changed (${(share * 100).toFixed(2)}%), threshold ${(MIN_CHANGED_SHARE * 100).toFixed(0)}%`,
    );
    console.log(
      `  of those, ${(chromaticShare * 100).toFixed(1)}% carry the layer's palette ` +
        `(threshold ${(MIN_CHROMATIC_SHARE_OF_CHANGED * 100).toFixed(0)}%)`,
    );
    if (share < MIN_CHANGED_SHARE) {
      fail(
        `the analytical layer changed only ${(share * 100).toFixed(2)}% of the map. ` +
          "The layer is populated but not visibly rendering.",
      );
    }
    if (chromaticShare < MIN_CHROMATIC_SHARE_OF_CHANGED) {
      fail(
        `only ${(chromaticShare * 100).toFixed(1)}% of the changed pixels carry the ` +
          "layer's palette. The layer is drawing geometry but not its colours - the " +
          "symptom of a colour-attribute defect, which is invisible on a light basemap.",
      );
    }
  }
} finally {
  await browser.close();
  stop();
}

if (failed) process.exit(1);
console.log("PASS: the analytical layer is visibly rendered.");
