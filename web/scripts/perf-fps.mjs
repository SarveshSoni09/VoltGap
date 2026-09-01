#!/usr/bin/env node
/**
 * Sustained frame-rate budget, CI-enforced. CLAUDE.md §11.3:
 *
 *   | National hex layer render | ≥ 55 fps sustained pan and zoom |
 *
 * **What is measured, exactly.** Presented animation frames while the national layer —
 * all 53,208 H3 cells — is continuously panned and zoomed. Frame timestamps are collected
 * with `requestAnimationFrame`, which fires once per frame the compositor actually
 * presents, so this counts frames rendered rather than JavaScript executed.
 *
 * Explicitly NOT measured, because none of these is frame performance: bundle size,
 * whether the first render succeeded, or how long the layer took to build.
 *
 * **"Sustained" is the worst second, not the average.** The reported figure is the minimum
 * frame rate over any 1-second sliding window in the run. An average would let a half-second
 * stall hide behind fast frames either side of it, which is the exact failure a user
 * notices when dragging a map.
 *
 * **The motion is deterministic.** The camera follows a fixed path — a continuous pan
 * across the contiguous United States with a zoom oscillation superimposed — advanced once
 * per animation frame. Synthetic mouse events would make the measurement depend on the
 * driver's event timing rather than on the renderer.
 *
 * **Hardware.** Headless Chrome renders through ANGLE on the host GPU; the harness prints
 * the reported renderer so the run is interpretable, and fails if it finds itself on a
 * software rasteriser, where a frame rate would describe the harness rather than the
 * application.
 */

import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

import puppeteer from "puppeteer";

import { recordBenchmark } from "./perf-provenance.mjs";

const BUDGET_FPS = 55;
const MEASURE_MS = 6000;
const WARMUP_MS = 1500;
const WINDOW_MS = 1000;
const PORT = Number(process.env.PERF_PORT ?? 4398);
/** The national surface is 53,208 cells. Anything far below it means the
 *  benchmark is measuring something other than the national layer. */
const MIN_CELLS = 50000;

const server = spawn(
  "node", [fileURLToPath(new URL("../serve-static.mjs", import.meta.url))],
  { env: { ...process.env, PORT: String(PORT) }, stdio: "ignore" },
);
const stop = () => server.kill();
process.on("exit", stop);
await new Promise((resolve) => setTimeout(resolve, 700));

const browser = await puppeteer.launch({
  headless: true,
  args: [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--enable-gpu",
    "--window-size=1600,1000",
  ],
});

try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1600, height: 1000, deviceScaleFactor: 1 });
  await page.goto(`http://localhost:${PORT}/`, {
    waitUntil: "networkidle0", timeout: 120000,
  });

  const renderer = await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    const gl = canvas.getContext("webgl2") ?? canvas.getContext("webgl");
    if (!gl) return "none";
    const info = gl.getExtension("WEBGL_debug_renderer_info");
    return info ? String(gl.getParameter(info.UNMASKED_RENDERER_WEBGL)) : "unknown";
  });
  console.log(`  renderer: ${renderer}`);
  // "none" is the case a GPU-less CI runner actually produces: this Chrome build serves
  // no WebGL context at all rather than falling back to SwiftShader, so a name-only check
  // would miss it and the run would fail later as an opaque timeout.
  if (renderer === "none") {
    console.error(
      "FAIL: no WebGL context is available on this machine, so the national layer cannot " +
        "render and no frame rate exists to measure. This is what a GPU-less runner " +
        "produces. See docs/reports/PLAN_CHANGE_6.md — do not substitute a software " +
        "measurement or a proxy.",
    );
    process.exit(1);
  }
  if (/swiftshader|software|llvmpipe|softwarerasterizer/i.test(renderer)) {
    console.error(
      `FAIL: this run is on a software rasteriser (${renderer}). A frame rate measured ` +
        "here would describe the harness, not the application, so it is refused rather " +
        "than reported. See docs/reports/PLAN_CHANGE_6.md.",
    );
    process.exit(1);
  }

  // The map must exist AND the national layer must actually hold the cells. Without the
  // second condition this benchmark would happily report 60 fps for an empty basemap,
  // which is the most likely way for it to silently stop measuring anything.
  await page.waitForFunction(
    () => Boolean(window.__voltgapMap) && (window.__voltgapLayerCells ?? 0) > 0,
    { timeout: 120000 },
  );
  const cells = await page.evaluate(() => window.__voltgapLayerCells ?? 0);
  console.log(`  cells in the rendered layer: ${cells.toLocaleString()}`);
  if (cells < MIN_CELLS) {
    console.error(
      `FAIL: the layer holds ${cells} cells, fewer than the ${MIN_CELLS} this benchmark ` +
        "requires. A frame rate measured over a near-empty layer means nothing.",
    );
    process.exit(1);
  }
  // deck.gl uploads the 53,208-cell buffer on the first frames after the layer is set;
  // measuring through that would measure a one-off upload rather than sustained render.
  await new Promise((resolve) => setTimeout(resolve, WARMUP_MS));

  const result = await page.evaluate(
    async (measureMs, windowMs) => {
      const map = window.__voltgapMap;
      if (!map) throw new Error("map handle absent");
      const frames = [];
      const started = performance.now();
      await new Promise((resolve) => {
        const step = (now) => {
          frames.push(now);
          const t = (now - started) / measureMs;
          if (t >= 1) {
            resolve(undefined);
            return;
          }
          // A fixed path: pan west to east across the contiguous US, with a zoom
          // oscillation on top so both operations are exercised continuously.
          map.jumpTo({
            center: [-124 + 50 * t, 38 + 4 * Math.sin(t * Math.PI * 2)],
            zoom: 4.0 + 1.4 * Math.sin(t * Math.PI * 4),
          });
          requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
      });

      const elapsed = (frames[frames.length - 1] - frames[0]) / 1000;
      const mean = (frames.length - 1) / elapsed;

      // Minimum frame rate over any sliding window of `windowMs`.
      let worst = Infinity;
      let start = 0;
      for (let end = 0; end < frames.length; end += 1) {
        while (frames[end] - frames[start] > windowMs) start += 1;
        const span = frames[end] - frames[start];
        if (span >= windowMs * 0.9 && end > start) {
          worst = Math.min(worst, ((end - start) / span) * 1000);
        }
      }

      const deltas = [];
      for (let i = 1; i < frames.length; i += 1) deltas.push(frames[i] - frames[i - 1]);
      deltas.sort((a, b) => a - b);
      const pct = (p) => deltas[Math.min(deltas.length - 1, Math.floor(deltas.length * p))];

      return {
        frames: frames.length,
        elapsed,
        mean,
        worstWindow: Number.isFinite(worst) ? worst : mean,
        p50: pct(0.5),
        p95: pct(0.95),
        p99: pct(0.99),
        longest: deltas[deltas.length - 1],
      };
    },
    MEASURE_MS, WINDOW_MS,
  );

  console.log("");
  console.log(
    `Sustained pan and zoom over the national layer, ${(result.elapsed).toFixed(1)} s, ` +
      `1600x1000, headless Chrome on the host GPU.`,
  );
  console.log("");
  console.log(`  frames presented              ${result.frames}`);
  console.log(`  mean frame rate               ${result.mean.toFixed(1)} fps`);
  console.log(`  SUSTAINED (worst 1 s window)  ${result.worstWindow.toFixed(1)} fps   (budget ${BUDGET_FPS} fps)`);
  console.log(`  frame time p50 / p95 / p99    ${result.p50.toFixed(1)} / ${result.p95.toFixed(1)} / ${result.p99.toFixed(1)} ms`);
  console.log(`  longest single frame          ${result.longest.toFixed(1)} ms`);
  console.log("");

  recordBenchmark("sustained_frame_rate", {
    budget_fps: BUDGET_FPS,
    measured_fps: Number(result.worstWindow.toFixed(2)),
    within_budget: result.worstWindow >= BUDGET_FPS,
    metric:
      "presented animation frames during a deterministic pan-and-zoom over the national " +
      "layer; the reported value is the MINIMUM frame rate over any 1-second sliding " +
      "window, not the mean",
    enforcement_class:
      "environment-dependent, hardware-rendered (CLAUDE.md 11.3, amendment A27)",
    harness: "web/scripts/perf-fps.mjs",
    renderer,
    cells_rendered: cells,
    measure_seconds: Number(result.elapsed.toFixed(2)),
    warmup_ms: WARMUP_MS,
    viewport: "1600x1000",
    mean_fps: Number(result.mean.toFixed(2)),
    frame_time_p50_ms: Number(result.p50.toFixed(2)),
    frame_time_p95_ms: Number(result.p95.toFixed(2)),
    frame_time_p99_ms: Number(result.p99.toFixed(2)),
    longest_frame_ms: Number(result.longest.toFixed(2)),
    validity_guards: [
      `refuses fewer than ${MIN_CELLS} rendered cells`,
      "refuses a software rasteriser (SwiftShader, llvmpipe, software)",
      "refuses an absent WebGL context, which is what a GPU-less runner produces",
    ],
    not_measured_by_proxy:
      "bundle size, first-render success and script execution time are never used as " +
      "stand-ins for frame performance",
  });

  if (result.worstWindow < BUDGET_FPS) {
    console.error(
      `FAIL: sustained frame rate ${result.worstWindow.toFixed(1)} fps is below the ` +
        `${BUDGET_FPS} fps budget.`,
    );
    process.exit(1);
  }
  console.log(
    `PASS: sustained ${result.worstWindow.toFixed(1)} fps against a ${BUDGET_FPS} fps budget.`,
  );
} finally {
  await browser.close();
  stop();
}
