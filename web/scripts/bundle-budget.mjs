#!/usr/bin/env node
/**
 * CI-enforced bundle budget. CLAUDE.md §11.3: "App shell, gzipped ≤ 600 KB", and "CI fails
 * on bundle budget violation".
 *
 * **What "app shell" means here, stated so the number cannot be gamed.** It is the
 * JavaScript a browser must download and execute before the first view is interactive:
 * the framework chunks plus every chunk statically reachable from a route entry. Chunks
 * that arrive only through a dynamic `import()` - deck.gl and MapLibre, which the map
 * pulls in after first paint - are reported separately and are NOT counted against the
 * shell, because the shell renders and responds without them.
 *
 * Measured as real gzip of the emitted files, not an estimate from a bundler report.
 */

import { gzipSync } from "node:zlib";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

// fileURLToPath, not URL.pathname: a space in the repository path would be
// percent-encoded and every read would fail on a directory that exists.
const OUT = fileURLToPath(new URL("../out/", import.meta.url));
const SHELL_BUDGET_BYTES = 600 * 1024;

function walk(dir) {
  const found = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) found.push(...walk(full));
    else found.push(full);
  }
  return found;
}

const files = walk(OUT);
const scripts = files.filter((f) => f.endsWith(".js"));

// Chunks referenced from the emitted HTML are what the browser fetches up front. A chunk
// reachable only through a dynamic import appears in no <script> tag.
const html = files.filter((f) => f.endsWith(".html"));
const referenced = new Set();
for (const page of html) {
  const text = readFileSync(page, "utf8");
  for (const match of text.matchAll(/\/_next\/static\/[^"'\\)\s]+?\.js/g)) {
    referenced.add(match[0].replace(/^\//, ""));
  }
}

// Chunks the App Router build emits but never loads. Next ships pages-router
// `framework-*` and `main-*` alongside the App Router's own `main-app-*`, which IS
// referenced and IS counted. Naming them keeps the shell total honest: they are neither
// shell nor lazily imported, they are simply never fetched.
const NEVER_FETCHED = /\/(framework|main)-[0-9a-f]+\.js$/;

let shellBytes = 0;
let lazyBytes = 0;
const shellFiles = [];
const lazyFiles = [];
const unusedFiles = [];
for (const file of scripts) {
  const rel = relative(OUT, file);
  const gz = gzipSync(readFileSync(file)).length;
  if (referenced.has(rel)) {
    shellBytes += gz;
    shellFiles.push([rel, gz]);
  } else if (NEVER_FETCHED.test(rel)) {
    unusedFiles.push([rel, gz]);
  } else {
    lazyBytes += gz;
    lazyFiles.push([rel, gz]);
  }
}

const kb = (b) => `${(b / 1024).toFixed(1)} KB`;
shellFiles.sort((a, b) => b[1] - a[1]);
lazyFiles.sort((a, b) => b[1] - a[1]);

console.log("App shell (fetched before first interaction), gzipped:");
for (const [name, size] of shellFiles.slice(0, 8)) {
  console.log(`  ${kb(size).padStart(10)}  ${name}`);
}
if (shellFiles.length > 8) console.log(`  … ${shellFiles.length - 8} more`);
console.log(`  ${"-".repeat(10)}`);
console.log(`  ${kb(shellBytes).padStart(10)}  TOTAL  (budget ${kb(SHELL_BUDGET_BYTES)})`);
console.log("");
console.log("Lazily loaded (dynamic import, after first paint), gzipped:");
for (const [name, size] of lazyFiles.slice(0, 5)) {
  console.log(`  ${kb(size).padStart(10)}  ${name}`);
}
console.log(`  ${kb(lazyBytes).padStart(10)}  TOTAL (not counted against the shell)`);
console.log("");
if (unusedFiles.length > 0) {
  console.log("Emitted but never referenced by any page (pages-router leftovers):");
  for (const [name, size] of unusedFiles) console.log(`  ${kb(size).padStart(10)}  ${name}`);
  console.log("");
}

if (shellBytes > SHELL_BUDGET_BYTES) {
  console.error(
    `FAIL: app shell is ${kb(shellBytes)}, over the ${kb(SHELL_BUDGET_BYTES)} budget ` +
      `by ${kb(shellBytes - SHELL_BUDGET_BYTES)}.`,
  );
  process.exit(1);
}
console.log(
  `PASS: app shell ${kb(shellBytes)} of ${kb(SHELL_BUDGET_BYTES)} ` +
    `(${((shellBytes / SHELL_BUDGET_BYTES) * 100).toFixed(1)}% of budget).`,
);
