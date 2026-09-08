#!/usr/bin/env node
/**
 * Time-to-interactive budget, CI-enforced. CLAUDE.md §11.3:
 *
 *   | Time to interactive, cold, national view | ≤ 3.0 s |
 *
 * **What is measured, exactly.** Lighthouse's `interactive` audit: Time to Interactive:
 * the first 5-second window after First Contentful Paint in which the main thread has no
 * long task and no more than two network requests are in flight. That is the metric §11.3
 * names, and it is the one asserted.
 *
 * **TTI is a LEGACY metric, and this harness does not pretend otherwise.** Lighthouse 10
 * removed Time to Interactive from the performance score and from the report display. It
 * is *still computed and still emitted* by current Lighthouse: in 12.8.2 the audit is
 * registered as `{id: 'interactive', weight: 0, group: 'hidden', acronym: 'TTI'}`, i.e.
 * unscored and hidden, but fully calculated by the original algorithm. So:
 *
 *   - **TTI is NOT a current Lighthouse scored metric and is NOT a Core Web Vital.**
 *     It is a pre-registered project criterion from CLAUDE.md §11.3, retained because that
 *     is what the specification fixed, and asserted from the value current Lighthouse still
 *     computes. No Lighthouse version is pinned below 10 to obtain it.
 *   - The contemporary metrics are printed alongside as **diagnostics**: LCP, TBT, CLS,
 *     Speed Index and the overall performance score: so modern auditing stays available.
 *     None of them substitutes for the TTI budget.
 *
 * That the audit genuinely computes TTI rather than aliasing another metric was verified
 * by a controlled experiment: two pages identical except for a 2-second long task starting
 * after LCP gave TTI 64 ms → 4,035 ms while LCP moved 64 ms → 80 ms. Recorded in
 * `docs/reports/PHASE_6_REPORT.md` §13.
 *
 * **Under what conditions.** A cold load of the National Overview: the view the budget
 * names: from a local static server serving the production `next build` export, in
 * headless Chrome, with Lighthouse's **simulated desktop throttling**: 40 ms RTT,
 * 10 Mbps, and a **4x CPU slowdown**. The profile is fixed here rather than taken from
 * the machine, so the number means the same thing on a laptop and in CI.
 *
 * The 4x CPU slowdown is deliberate and is the reason this is a real gate. Unthrottled,
 * this page reaches interactive in about 1.4 s on the development machine, which would
 * make the budget unfalsifiable on any modern hardware. The 4x profile is Lighthouse's
 * own desktop default and approximates a mid-range machine rather than a developer's.
 *
 * `--runs=N` takes the MEDIAN of N runs. Lighthouse's simulation is deterministic given a
 * trace, but the trace comes from a real browser on a shared machine, so a single run can
 * be perturbed by whatever else is happening. Three runs is the default.
 */

import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

import lighthouse from "lighthouse";

import { recordBenchmark } from "./perf-provenance.mjs";
import puppeteer from "puppeteer";

const BUDGET_SECONDS = 3.0;
const PORT = Number(process.env.PERF_PORT ?? 4399);
const URL_UNDER_TEST = `http://localhost:${PORT}/`;
/** The national surface is 53,208 cells. Far below it means the page failed to
 *  load its data, and the measurement would be of an error page. */
const MIN_CELLS = 50000;

/**
 * Lighthouse's own CPU benchmark, below which this machine is not performing as the
 * reference environment and its numbers must not be compared against the budget.
 *
 * §11.3 (amendment A27) makes TTI an ENVIRONMENT-DEPENDENT budget. That cuts both ways: as
 * well as not comparing an arbitrary runner's figure against 3.0 s, this machine's own
 * figure is only admissible while it is behaving like the reference environment.
 *
 * Derived from measurement, not chosen: quiescent runs on the reference machine report
 * 4032-4136. Under eight competing CPU burners the same machine reports 2840 and TTI rises
 * from 2.91 s to 3.84 s: the contention, not the application. The floor is set at 3500,
 * about 85% of the observed quiescent range, which admits normal variation and rejects the
 * loaded case. It is a VALIDITY GUARD of the same class as refusing an empty page: it
 * changes which measurements may be reported, never the budget they are reported against.
 */
const REFERENCE_BENCHMARK_INDEX_FLOOR = 3500;

const RUNS = Number(
  process.argv.find((a) => a.startsWith("--runs="))?.split("=")[1] ?? 3,
);

/** Lighthouse's desktop profile, pinned so the number is comparable across machines. */
const CONFIG = {
  extends: "lighthouse:default",
  settings: {
    formFactor: "desktop",
    throttlingMethod: "simulate",
    throttling: {
      rttMs: 40,
      throughputKbps: 10 * 1024,
      cpuSlowdownMultiplier: 4,
      requestLatencyMs: 0,
      downloadThroughputKbps: 0,
      uploadThroughputKbps: 0,
    },
    screenEmulation: {
      mobile: false, width: 1440, height: 900, deviceScaleFactor: 1, disabled: false,
    },
    onlyCategories: ["performance"],
    // A cold load every time: no disk cache, no service worker, no prior state.
    disableStorageReset: false,
  },
};

const server = spawn("node", [fileURLToPath(new URL("../serve-static.mjs", import.meta.url))], {
  env: { ...process.env, PORT: String(PORT) },
  stdio: "ignore",
});
const stop = () => server.kill();
process.on("exit", stop);

await new Promise((resolve) => setTimeout(resolve, 700));

// PRE-FLIGHT: the page must actually load the national surface.
//
// Without the published artifacts the National Overview renders its error state, which is
// fast: measured at 0.96 s, a comfortable "PASS" against a 3.0 s budget while measuring a
// page with no map and no data. That is the worst kind of green. The measurement is
// refused unless the layer really holds the national surface.
{
  const browser = await puppeteer.launch({
    headless: true, args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });
  try {
    const page = await browser.newPage();
    await page.goto(URL_UNDER_TEST, { waitUntil: "networkidle0", timeout: 120000 });
    // REPRESENTED cells, not drawn polygons. The national view aggregates for display, so
    // it legitimately draws ~4,000 parents covering all 53,208 cells; asking for drawn
    // polygons here would fail a page that loaded its data perfectly well. The point of
    // this guard is only to refuse a page that loaded NOTHING, which measures 0.96 s and
    // "passes" comfortably.
    const cells = await page
      .waitForFunction(() => window.__voltgapNativeCells ?? 0, { timeout: 60000 })
      .then((handle) => handle.jsonValue())
      .catch(() => 0);
    if (Number(cells) < MIN_CELLS) {
      console.error(
        `FAIL: the page under test loaded ${cells} cells, fewer than the ${MIN_CELLS} ` +
          "the national surface holds. Time to interactive measured against a page that " +
          "did not load its data is meaningless, and it passes easily. Run " +
          "`make artifacts` first. See docs/reports/PLAN_CHANGE_6.md.",
      );
      process.exit(1);
    }
    console.log(
      `  page under test holds ${Number(cells).toLocaleString()} cells ` +
        "(represented; the national view aggregates these for display)",
    );
  } finally {
    await browser.close().catch(() => {});
  }
}

// A FRESH browser per run. Lighthouse tears down the page it navigated, and reusing one
// browser across runs makes the next run race that teardown - which surfaced as
// `ConnectionClosedError` rather than as a number, i.e. a harness failure that could be
// mistaken for a budget breach. A cold browser is also what "cold load" should mean.
const results = [];
for (let run = 1; run <= RUNS; run += 1) {
  const browser = await puppeteer.launch({
    headless: true,
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });
  try {
    const port = Number(new URL(browser.wsEndpoint()).port);
    const report = await lighthouse(
      URL_UNDER_TEST, { port, output: "json", logLevel: "silent" }, CONFIG,
    );
    const audits = report.lhr.audits;
    if (audits.interactive?.numericValue === undefined) {
      // If a future Lighthouse stops computing it, this must fail loudly rather than
      // quietly falling back to a metric that is not the pre-registered criterion.
      console.error(
        "FAIL: this Lighthouse build does not emit the `interactive` audit, so the " +
          "pre-registered TTI criterion cannot be measured. Do NOT substitute LCP, TBT " +
          "or INP; amend docs/reports/PLAN_CHANGE_6.md for an owner decision.",
      );
      process.exit(1);
    }
    results.push({
      tti: audits.interactive.numericValue / 1000,
      fcp: audits["first-contentful-paint"].numericValue / 1000,
      lcp: audits["largest-contentful-paint"].numericValue / 1000,
      tbt: audits["total-blocking-time"].numericValue,
      cls: audits["cumulative-layout-shift"].numericValue,
      benchmarkIndex: report.lhr.environment.benchmarkIndex,
      si: audits["speed-index"].numericValue / 1000,
      score: report.lhr.categories.performance.score,
      lighthouseVersion: report.lhr.lighthouseVersion,
      chrome: report.lhr.environment.hostUserAgent.match(/Chrome\/[\d.]+/)?.[0] ?? "?",
    });
    console.log(
      `  run ${run}/${RUNS}   TTI ${results.at(-1).tti.toFixed(2)}s   ` +
        `FCP ${results.at(-1).fcp.toFixed(2)}s   LCP ${results.at(-1).lcp.toFixed(2)}s   ` +
        `TBT ${results.at(-1).tbt.toFixed(0)}ms   ` +
        `benchmarkIndex ${results.at(-1).benchmarkIndex.toFixed(0)}`,
    );
  } finally {
    await browser.close().catch(() => {});
  }
}
stop();

const median = (values) => {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
};

const tti = median(results.map((r) => r.tti));
const benchmarkIndex = median(results.map((r) => r.benchmarkIndex));

// VALIDITY GUARD. Refuse to compare against the budget when this machine was not
// performing as the reference environment. Reported as "not measured", never as a pass or
// a fail of the application.
if (benchmarkIndex < REFERENCE_BENCHMARK_INDEX_FLOOR) {
  console.error("");
  console.error(
    `NOT MEASURED: median Lighthouse benchmarkIndex ${benchmarkIndex.toFixed(0)} is below ` +
      `the ${REFERENCE_BENCHMARK_INDEX_FLOOR} floor for this reference environment ` +
      `(quiescent range 4032-4136), so the machine was contended during measurement.`,
  );
  console.error(
    `  The observed median was ${tti.toFixed(2)} s, and it is NOT evidence about the ` +
      `${BUDGET_SECONDS.toFixed(1)} s budget either way: measured contention inflates it ` +
      "by roughly 0.9 s. Re-run on a quiescent machine.",
  );
  console.error(
    "  This is a validity guard, not a budget failure. See CLAUDE.md 11.3 amendment A27.",
  );
  process.exit(2);
}
console.log("");
console.log("Cold load of the National Overview, Lighthouse simulated desktop");
console.log("throttling: 40 ms RTT, 10 Mbps, 4x CPU slowdown.");
console.log(`Lighthouse ${results[0].lighthouseVersion}, ${results[0].chrome}.`);
console.log(
  `Machine validity: median benchmarkIndex ${benchmarkIndex.toFixed(0)} ` +
    `(floor ${REFERENCE_BENCHMARK_INDEX_FLOOR}).`,
);
console.log("");
console.log("  PRE-REGISTERED CRITERION (CLAUDE.md 11.3). Time to Interactive is a LEGACY");
console.log("  metric: unscored and hidden in Lighthouse >= 10, still computed by it.");
console.log("  It is not a Core Web Vital and not a current Lighthouse scored metric.");
console.log(`  median Time to Interactive      ${tti.toFixed(2)} s   (budget ${BUDGET_SECONDS.toFixed(1)} s)`);
console.log("");
console.log("  Contemporary diagnostics, reported but NOT substituted for the budget:");
console.log(`  median First Contentful Paint   ${median(results.map((r) => r.fcp)).toFixed(2)} s`);
console.log(`  median Largest Contentful Paint ${median(results.map((r) => r.lcp)).toFixed(2)} s`);
console.log(`  median Total Blocking Time      ${median(results.map((r) => r.tbt)).toFixed(0)} ms`);
console.log(`  median Cumulative Layout Shift  ${median(results.map((r) => r.cls)).toFixed(3)}`);
console.log(`  median Speed Index              ${median(results.map((r) => r.si)).toFixed(2)} s`);
console.log(`  median performance score        ${(median(results.map((r) => r.score)) * 100).toFixed(0)} / 100`);
console.log("");

recordBenchmark("time_to_interactive", {
  budget_seconds: BUDGET_SECONDS,
  measured_seconds: Number(tti.toFixed(3)),
  within_budget: tti <= BUDGET_SECONDS,
  metric: "Lighthouse `interactive` audit (Time to Interactive)",
  metric_status:
    "LEGACY. Removed from the Lighthouse performance score and report display in " +
    "Lighthouse 10 (registered as weight 0, group hidden); still computed in full. NOT a " +
    "Core Web Vital and NOT a current Lighthouse scored metric. Retained because " +
    "CLAUDE.md 11.3 pre-registered it.",
  enforcement_class: "environment-dependent (CLAUDE.md 11.3, amendment A27)",
  harness: "web/scripts/perf-tti.mjs",
  runs: RUNS,
  aggregation: "median",
  lighthouse_version: results[0].lighthouseVersion,
  benchmark_index_median: Math.round(benchmarkIndex),
  benchmark_index_floor: REFERENCE_BENCHMARK_INDEX_FLOOR,
  benchmark_index_note:
    "Lighthouse's own CPU benchmark for the machine during measurement. Quiescent runs " +
    "on the reference environment report 4032-4136; under eight competing CPU burners " +
    "the same machine reports 2840 and TTI rises 2.91 s -> 3.84 s. Below the floor the " +
    "harness refuses to report against the budget at all.",
  chrome: results[0].chrome,
  throttling: CONFIG.settings.throttling,
  form_factor: CONFIG.settings.formFactor,
  throttling_method: CONFIG.settings.throttlingMethod,
  host_dependence:
    "Lighthouse `simulate` normalises the NETWORK but derives CPU task durations from a " +
    "trace taken on this host. Same code and profile measured 2.38 s at " +
    "cpuSlowdownMultiplier 1, 2.86 s at 4, 3.40 s at 8, 3.96 s at 12. An absolute value " +
    "from a different machine is not comparable with this one.",
  validity_guard:
    `refuses to report unless the page under test holds at least ${MIN_CELLS} cells`,
  diagnostics_not_substitutes: {
    first_contentful_paint_s: Number(median(results.map((r) => r.fcp)).toFixed(3)),
    largest_contentful_paint_s: Number(median(results.map((r) => r.lcp)).toFixed(3)),
    total_blocking_time_ms: Math.round(median(results.map((r) => r.tbt))),
    cumulative_layout_shift: Number(median(results.map((r) => r.cls)).toFixed(4)),
    speed_index_s: Number(median(results.map((r) => r.si)).toFixed(3)),
    performance_score: median(results.map((r) => r.score)),
  },
});

if (tti > BUDGET_SECONDS) {
  console.error(
    `FAIL: Time to Interactive ${tti.toFixed(2)} s exceeds the ${BUDGET_SECONDS.toFixed(1)} s budget ` +
      `by ${(tti - BUDGET_SECONDS).toFixed(2)} s.`,
  );
  process.exit(1);
}
console.log(
  `PASS: Time to Interactive ${tti.toFixed(2)} s of ${BUDGET_SECONDS.toFixed(1)} s ` +
    `(${((tti / BUDGET_SECONDS) * 100).toFixed(1)}% of budget).`,
);
