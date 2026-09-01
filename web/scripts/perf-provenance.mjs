/**
 * Benchmark provenance and reference-environment metadata.
 *
 * CLAUDE.md §11.3 (amendment A27) makes TTI and sustained frame rate
 * **environment-dependent** budgets: their numeric values are only meaningful on a
 * documented reference environment. That documentation cannot live in prose, because prose
 * cannot be checked and drifts from the machine that actually produced the number.
 *
 * Each harness writes its result here, together with the environment that produced it, and
 * PR CI asserts the record exists and is well formed without re-measuring anything.
 */

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { arch, cpus, platform, release, totalmem } from "node:os";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

export const PROVENANCE_PATH = fileURLToPath(
  new URL("../../docs/evidence/P6-1_performance.json", import.meta.url),
);

/** The machine, described well enough that a reader can judge whether it resembles theirs. */
export function referenceEnvironment() {
  const cores = cpus();
  return {
    platform: `${platform()} ${release()}`,
    arch: arch(),
    cpu_model: cores[0]?.model ?? "unknown",
    cpu_cores: cores.length,
    total_memory_gb: Math.round(totalmem() / 1024 ** 3),
    node: process.version,
  };
}

function read() {
  try {
    return JSON.parse(readFileSync(PROVENANCE_PATH, "utf8"));
  } catch {
    return {};
  }
}

/**
 * Record one benchmark's result. Merges rather than overwrites, because the two harnesses
 * run as separate processes and each owns one key.
 */
export function recordBenchmark(name, payload) {
  const existing = read();
  const merged = {
    note:
      "Benchmark provenance for the ENVIRONMENT-DEPENDENT performance budgets of " +
      "CLAUDE.md 11.3 (amendment A27). These numeric values are only meaningful on the " +
      "reference environment recorded with each of them. An absolute figure measured on " +
      "an undocumented runner is NOT evidence about these budgets, and PR CI does not " +
      "produce one.",
    ...existing,
    [name]: {
      ...payload,
      reference_environment: referenceEnvironment(),
      measured_at: new Date().toISOString(),
    },
  };
  mkdirSync(dirname(PROVENANCE_PATH), { recursive: true });
  writeFileSync(PROVENANCE_PATH, `${JSON.stringify(merged, null, 2)}\n`);
  return merged;
}
