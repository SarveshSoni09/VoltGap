#!/usr/bin/env node
/**
 * Cold-user semantics, checked against what a person actually reads.
 *
 * These views are client-rendered, so the static HTML is only a shell: the legend, the
 * candidate table, the disclosure contents and every number arrive after hydration. A
 * check against the emitted HTML would pass while the visible page said something else.
 * So this drives a real browser, waits for the data, and reads `innerText`: including
 * the text inside every collapsed section, which it opens first.
 *
 * It cannot judge whether the writing is good. It checks the specific things a first
 * reading depends on, each of which was wrong before this pass: that the product says
 * what it is before how it works, that the map explains its colours and its empty areas,
 * that internal identifiers are not presented as user-facing concepts, that reliability is
 * described without being overstated, and that the claim safeguards survived the rewrite.
 */

import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

import puppeteer from "puppeteer";

const PORT = Number(process.env.PERF_PORT ?? 4392);
const server = spawn(
  "node", [fileURLToPath(new URL("../serve-static.mjs", import.meta.url))],
  { env: { ...process.env, PORT: String(PORT) }, stdio: "ignore" },
);
const stop = () => server.kill();
process.on("exit", stop);
await new Promise((r) => setTimeout(r, 700));

const browser = await puppeteer.launch({
  headless: true, args: ["--no-sandbox", "--disable-dev-shm-usage", "--enable-gpu"],
});

let failed = 0;
/**
 * Does the text ASSERT this phrase, or deny it?
 *
 * The interface deliberately contains sentences like "nothing here is validated as the
 * best place to build". A plain substring search flags that as a forbidden claim, which
 * is precisely backwards. This looks at what precedes the phrase.
 */
const asserts = (text, phrase) => {
  const lower = text.toLowerCase();
  let from = 0;
  for (;;) {
    const at = lower.indexOf(phrase, from);
    if (at === -1) return false;
    const before = lower.slice(Math.max(0, at - 90), at);
    const negated = /\b(not|never|no|nothing|does not|cannot|without|avoid)\b[^.]*$/.test(
      before,
    );
    if (!negated) return true;
    from = at + phrase.length;
  }
};

const check = (page, description, condition) => {
  if (!condition) {
    console.error(`  FAIL  [${page}] ${description}`);
    failed += 1;
  }
};

async function read(path) {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 1000, deviceScaleFactor: 1 });
  await page.goto(`http://localhost:${PORT}${path}`, {
    waitUntil: "networkidle0", timeout: 120000,
  });
  await new Promise((r) => setTimeout(r, 7000));
  // Open every collapsed section: the depth is meant to be reachable, and a reader who
  // clicks must find the precise wording there.
  await page.evaluate(() => {
    document.querySelectorAll(".disclose-q").forEach((b) => b.click());
    // Expand the first candidate row too: its reasons and technical details are the
    // depth this pass promises is reachable, and a reader reaches them by clicking.
    const firstRow = document.querySelector(".tablewrap tbody tr");
    if (firstRow instanceof HTMLElement) firstRow.click();
  });
  await new Promise((r) => setTimeout(r, 400));
  await page.evaluate(() => {
    document.querySelectorAll("details").forEach((d) => d.setAttribute("open", ""));
  });
  await new Promise((r) => setTimeout(r, 400));
  const text = await page.evaluate(() => document.body.innerText);
  const collapsedText = await page.evaluate(() => {
    // What is visible BEFORE opening anything: the first-read experience.
    document.querySelectorAll(".disclose-a").forEach((d) => d.remove());
    return document.body.innerText;
  });
  await page.close();
  return { text, collapsedText };
}

const national = await read("/");
const access = await read("/access/");
const studio = await read("/studio/");
const methodology = await read("/methodology/");
const pages = { national, access, studio, methodology };

// --- 1. the product explains itself before it explains its methods -------------------
for (const [name, p] of Object.entries(pages)) {
  check(name, "the shell states the question the product answers",
    p.text.includes("Where should the next EV chargers go?"));
}
check("national", "leads with what it answers",
  national.text.includes("Where is EV demand highest?"));
check("access", "leads with what it answers",
  access.text.includes("Where is charging access weakest?"));
check("studio", "leads with what it answers",
  studio.text.includes("Plan new charging locations"));
check("methodology", "leads with what it answers",
  methodology.text.includes("How it works"));

// The first read must not open with methodology.
for (const jargon of ["sub-state anchored", "evidence grain", "reconcil", "propensity"]) {
  check("national", `first read does not open with "${jargon}"`,
    !national.collapsedText.toLowerCase().includes(jargon.toLowerCase()));
}

// --- 2. the map explains its own colours and gaps ------------------------------------
check("national", "says what the colour means",
  national.collapsedText.includes("Brighter areas have more estimated EV demand"));
check("national", "says what the empty areas mean",
  national.collapsedText.includes("no estimate") &&
    national.collapsedText.toLowerCase().includes("nobody lives"));
check("national", "says when it is grouping areas for display",
  national.collapsedText.includes("grouped for display"));

// --- 3. internal identifiers are not user-facing -------------------------------------
check("studio", "no raw H3 index is a visible column", !/\bCELL\b/.test(studio.collapsedText));
check("studio", "H3 stays available under Technical details",
  studio.text.includes("Technical details") && studio.text.includes("H3 cell"));
const SNAKE = ["demand_bev", "equity_population", "km_to_nearest_dcfc_site", "dcfc_ports",
  "sub_state_anchored_share", "state_fips", "passes_road_filter",
  "beyond_primary_secondary_road_network", "already_saturated"];
for (const [name, p] of Object.entries(pages)) {
  for (const leak of SNAKE) {
    check(name, `no column name "${leak}" is shown`, !p.text.includes(leak));
  }
}
// Headings are uppercased by CSS, and innerText reports what is rendered, so compare
// case-insensitively: the capitalisation is presentational, the wording is not.
for (const heading of ["Rank", "Area", "Why it stands out", "Estimated EV demand",
  "Underserved population", "Existing fast charging", "Estimate reliability"]) {
  check("studio", `uses the plain column heading "${heading}"`,
    studio.collapsedText.toLowerCase().includes(heading.toLowerCase()));
}
for (const preset of ["Demand", "Balanced", "Underserved communities"]) {
  check("studio", `offers the "${preset}" priority`, studio.collapsedText.includes(preset));
}
check("studio", "hides raw weights behind Advanced weighting",
  studio.text.includes("Advanced weighting"));
check("studio", "explains what the budget number counts",
  studio.collapsedText.includes("How many new locations can you fund?"));
check("studio", "does not call a site count a dollar budget",
  !/\$\s*\d/.test(studio.collapsedText.split("Underserved")[0] ?? ""));

// --- 4. every selected area is explained ---------------------------------------------
check("studio", "explains why areas ranked highly",
  studio.text.includes("Why this area ranked highly"));
const reasons = [...studio.text.matchAll(/(Among the highest|Reaches|Above-average|No public fast charging|Nearest fast charging|Existing fast charging is thin)/g)];
check("studio", "reasons vary between rows, rather than repeating one sentence",
  new Set(reasons.map((m) => m[0])).size >= 2);

// --- 5. reliability is plain but never overstated -------------------------------------
check("studio", "names reliability plainly", studio.collapsedText.includes("Higher reliability"));
for (const [name, p] of Object.entries(pages)) {
  // The pages legitimately say "anchored, NOT directly observed". What must never appear
  // is the claim itself.
  check(name, "never claims an estimate is directly observed",
    !asserts(p.text, "directly observed"));
}
check("studio", "the precise wording is reachable",
  studio.text.includes("sub-state anchored"));
check("methodology", "the technical record is intact",
  ["Historical deployment alignment", "Demand model validation",
    "Cross-objective robustness", "No approximation bound is claimed"]
    .every((t) => methodology.text.includes(t)));

// --- 6. claim safeguards --------------------------------------------------------------
for (const [name, p] of Object.entries(pages)) {
  const lower = p.text.toLowerCase();
  for (const banned of ["optimal place", "best place to build", "grid feasible",
    "interconnection ready"]) {
    check(name, `does not claim "${banned}"`, !asserts(lower, banned));
  }
}
check("studio", "says what it is not claiming",
  studio.text.includes("does not claim they are the right places to build"));
check("methodology", "still reports the negative validation result",
  methodology.text.includes("negative result"));

// --- 7. every map answers "where am I looking, and what does this mean?" --------------
//
// The three views used to be a picture, a table and a picture-with-a-table: a reader could
// see that somewhere mattered without being able to ask which somewhere. These checks
// drive the real hover and click paths, because a card that exists in the source and never
// appears on screen is not an answer.

/** Hovers the middle of a map and reads whatever card appears. */
async function hoverMap(path, at = { x: 0.5, y: 0.45 }) {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 1000, deviceScaleFactor: 1 });
  await page.goto(`http://localhost:${PORT}${path}`, {
    waitUntil: "networkidle0", timeout: 120000,
  });
  await new Promise((r) => setTimeout(r, 8000));
  const box = await page.evaluate(() => {
    const canvas = document.querySelector(".canvas canvas");
    if (canvas === null) return null;
    const r = canvas.getBoundingClientRect();
    return { x: r.x, y: r.y, width: r.width, height: r.height };
  });
  if (box === null) {
    await page.close();
    return { hovered: "", pinned: "", hasMap: false };
  }
  // Several attempts across the map: not every pixel is over a populated cell.
  let hovered = "";
  const points = [at, { x: 0.45, y: 0.5 }, { x: 0.55, y: 0.4 }, { x: 0.5, y: 0.55 },
    { x: 0.4, y: 0.45 }, { x: 0.6, y: 0.5 }, { x: 0.5, y: 0.35 }];
  let landed = null;
  for (const point of points) {
    const px = box.x + box.width * point.x;
    const py = box.y + box.height * point.y;
    await page.mouse.move(px, py);
    await new Promise((r) => setTimeout(r, 500));
    hovered = await page.evaluate(
      () => document.querySelector(".fcard")?.innerText ?? "");
    if (hovered !== "") { landed = { px, py }; break; }
  }
  let pinned = "";
  if (landed !== null) {
    await page.mouse.click(landed.px, landed.py);
    await new Promise((r) => setTimeout(r, 700));
    await page.evaluate(() => {
      document.querySelectorAll(".fcard details").forEach(
        (d) => d.setAttribute("open", ""));
    });
    pinned = await page.evaluate(
      () => document.querySelector(".fcard")?.innerText ?? "");
  }
  await page.close();
  return { hovered, pinned, hasMap: true };
}

const nationalMap = await hoverMap("/");
const accessMap = await hoverMap("/access/");
const studioMap = await hoverMap("/studio/?state=53");

for (const [name, map] of Object.entries({
  national: nationalMap, access: accessMap, studio: studioMap,
})) {
  check(name, "has a map at all", map.hasMap);
  check(name, "hovering an area says what it is", map.hovered !== "");
  // A county and a state. Never a street address, which an H3 centroid cannot support,
  // and never a bare H3 index, which answers nothing.
  check(name, "names the place in words a reader recognises",
    /,\s*[A-Z]{2}\b/.test(map.hovered));
  check(name, "does not put a raw H3 index in the hover card",
    !/\b8[0-9a-f]{14}\b/.test(map.hovered));
  check(name, "clicking pins a card with the technical detail behind a disclosure",
    map.pinned.includes("Technical details"));
  check(name, "the pinned card is where the H3 index lives",
    /\b8[0-9a-f]{14}\b/.test(map.pinned));
}

check("national", "the hover card leads with the metric the map is showing",
  nationalMap.hovered.toLowerCase().includes("estimated evs"));
check("access", "the hover card leads with the threshold the reader set",
  /people beyond \d/i.test(accessMap.hovered));
check("studio", "the hover card says whether the area is in the portfolio",
  /in your portfolio|eligible, not selected/i.test(studioMap.hovered));

// --- 8. the charging-gaps threshold moves the map, not only the numbers ---------------
//
// The defect this replaced: the control recomputed four figures while the page showed no
// geography at all, so nothing on screen moved and the control read as broken.
{
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 1000, deviceScaleFactor: 1 });
  await page.goto(`http://localhost:${PORT}/access/`, {
    waitUntil: "networkidle0", timeout: 120000,
  });
  await new Promise((r) => setTimeout(r, 8000));
  const summaryAt = async (value) => {
    await page.evaluate((km) => {
      const slider = document.querySelector("#threshold");
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype, "value").set;
      setter.call(slider, String(km));
      slider.dispatchEvent(new Event("input", { bubbles: true }));
    }, value);
    await new Promise((r) => setTimeout(r, 3000));
    return page.evaluate(() => ({
      strip: document.querySelector(".mapsummary")?.innerText ?? "",
      legend: document.querySelector(".legend")?.innerText ?? "",
    }));
  };
  const tight = await summaryAt(5);
  const loose = await summaryAt(45);
  await page.close();

  check("access", "the threshold is stated above the map", tight.strip.includes("5.0 km"));
  check("access", "and in the legend", tight.legend.includes("5.0 km"));
  check("access", "moving the threshold changes the mapped geography",
    tight.strip !== loose.strip && loose.strip.includes("45.0 km"));
  const people = (t) => Number((/([\d.]+)M people beyond/.exec(t) ?? [0, "0"])[1]);
  check("access", "a tighter definition of far affects more people, on the map too",
    people(tight.strip) > people(loose.strip));
}

// --- 9. the studio's map and table are one list --------------------------------------
{
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 1000, deviceScaleFactor: 1 });
  await page.goto(`http://localhost:${PORT}/studio/?state=53`, {
    waitUntil: "networkidle0", timeout: 120000,
  });
  await new Promise((r) => setTimeout(r, 8000));

  // Hovering a row must highlight it, so the eye can follow it to the map.
  // The table scrolls: the last row starts below the fold, and a mouse move to its
  // unscrolled coordinates would land on whatever is drawn there instead.
  await page.evaluate(() => {
    const rows = document.querySelectorAll(".tablewrap tbody tr");
    const target = rows[rows.length - 1];
    if (target instanceof HTMLElement) target.scrollIntoView({ block: "center" });
  });
  await new Promise((r) => setTimeout(r, 400));
  const rowBox = await page.evaluate(() => {
    const rows = document.querySelectorAll(".tablewrap tbody tr");
    const target = rows[rows.length - 1];
    if (!(target instanceof HTMLElement)) return null;
    const r = target.getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2, text: target.innerText };
  });
  check("studio", "the portfolio table has rows to point at", rowBox !== null);
  let linked = false;
  let scrolled = false;
  let cardFromRow = "";
  if (rowBox !== null) {
    await page.mouse.move(rowBox.x, rowBox.y);
    await new Promise((r) => setTimeout(r, 500));
    linked = await page.evaluate(
      () => document.querySelector(".tablewrap tr.linked") !== null);
    cardFromRow = await page.evaluate(
      () => document.querySelector(".fcard")?.innerText ?? "");
    // Clicking the LAST row must bring it into view and open it: this is the same code
    // path a click on its map marker uses, and it silently did nothing before.
    await page.evaluate(() => {
      const rows = document.querySelectorAll(".tablewrap tbody tr");
      const target = rows[rows.length - 1];
      if (target instanceof HTMLElement) target.click();
    });
    await new Promise((r) => setTimeout(r, 900));
    scrolled = await page.evaluate(() => {
      const wrap = document.querySelector(".tablewrap");
      const open = wrap?.querySelector("tr.open");
      if (!(wrap instanceof HTMLElement) || !(open instanceof HTMLElement)) return false;
      const offset = open.getBoundingClientRect().top - wrap.getBoundingClientRect().top;
      return offset >= 0 && offset <= wrap.clientHeight;
    });
  }
  await page.close();

  check("studio", "hovering a table row highlights it", linked);
  check("studio", "hovering a table row describes that area", cardFromRow !== "");
  check("studio", "the same identity appears in the card and the row",
    rowBox !== null && cardFromRow.includes(
      (/([A-Z][A-Za-z .'-]+ (?:County|Parish|Borough|Census Area|City|Municipality)), ([A-Z]{2})/
        .exec(rowBox.text) ?? [""])[0]));
  check("studio", "selecting a row brings it into view", scrolled);
}

await browser.close();
stop();

if (failed > 0) {
  console.error(`\nFAIL: ${failed} cold-user check(s) failed.`);
  process.exit(1);
}
console.log("PASS: the interface reads correctly to someone who knows nothing about it.");
