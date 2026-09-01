#!/usr/bin/env node
/**
 * Wait for the machine to quiesce before an environment-dependent benchmark.
 *
 * The authoritative gate runs ~20 minutes of full-load work — the whole test suite under
 * coverage, a national artifact rebuild, a production frontend build — and then measures
 * time to interactive and frame rate. Measuring a performance benchmark on a machine still
 * working through that describes the gate's own load, not the application: measured on the
 * reference machine, eight competing CPU burners moved TTI from 2.91 s to 3.84 s.
 *
 * This is part of establishing the reference conditions, not part of the measurement. It
 * changes no threshold and no measured quantity. The benchmark's own validity guard —
 * Lighthouse's `benchmarkIndex` against a documented floor — independently verifies that
 * the wait actually worked, and refuses to report if it did not.
 */

import { cpus, loadavg } from "node:os";

/** Load per core below which the machine counts as quiescent for benchmarking. */
const QUIESCENT_LOAD_PER_CORE = 0.6;
const TIMEOUT_MS = Number(process.env.PERF_SETTLE_TIMEOUT_MS ?? 180_000);
const POLL_MS = 5_000;

const cores = cpus().length;
const target = QUIESCENT_LOAD_PER_CORE * cores;
const started = Date.now();

process.stdout.write(
  `  waiting for the machine to quiesce: load per core <= ${QUIESCENT_LOAD_PER_CORE} ` +
    `(${cores} cores, target load ${target.toFixed(1)})\n`,
);

while (Date.now() - started < TIMEOUT_MS) {
  const load = loadavg()[0];
  if (load <= target) {
    process.stdout.write(
      `  settled after ${((Date.now() - started) / 1000).toFixed(0)} s, ` +
        `load ${load.toFixed(2)}\n`,
    );
    process.exit(0);
  }
  await new Promise((resolve) => setTimeout(resolve, POLL_MS));
}

// Not fatal on its own: the benchmark's benchmarkIndex guard is the authority on whether
// the measurement is admissible. This only reports that the wait did not achieve its goal.
process.stdout.write(
  `  did NOT settle within ${TIMEOUT_MS / 1000} s (load ${loadavg()[0].toFixed(2)}). ` +
    "Proceeding; the benchmark's own validity guard decides whether its result counts.\n",
);
