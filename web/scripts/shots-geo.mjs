/**
 * Screenshot evidence for the layer-hierarchy and geography pass.
 *
 * Captures the same views at national, state and local zoom so the reviewer can judge the
 * thing that was actually wrong: whether the analytical surface and the geographic
 * reference layer can be read at the same time.
 */
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer";

const PORT = 4396;
const server = spawn("node", [fileURLToPath(new URL("../serve-static.mjs", import.meta.url))],
  { env: { ...process.env, PORT: String(PORT) }, stdio: "ignore" });
process.on("exit", () => server.kill());
await new Promise((r) => setTimeout(r, 900));

const browser = await puppeteer.launch({
  headless: true, args: ["--no-sandbox", "--enable-gpu", "--window-size=1440,900"],
});

const open = async (path) => {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });
  await page.goto(`http://localhost:${PORT}${path}`, { waitUntil: "networkidle0" });
  await new Promise((r) => setTimeout(r, 9000));
  return page;
};
const settle = (ms = 3500) => new Promise((r) => setTimeout(r, ms));
const flyTo = async (page, center, zoom) => {
  await page.evaluate(([c, z]) => window.__voltgapMap.jumpTo({ center: c, zoom: z }),
    [center, zoom]);
  await settle();
};
const save = async (page, name) => {
  await page.screenshot({ path: `../docs/evidence/ux/geo-${name}.png` });
  console.log(name);
};

// The three zoom bands item 44 names, on the demand surface.
{
  const page = await open("/");
  await save(page, "demand-national");
  await flyTo(page, [-120.5, 47.4], 6.2);
  await save(page, "demand-state");
  await flyTo(page, [-122.33, 47.61], 9.5);
  await save(page, "demand-local");
  await page.close();
}

// The geography control: U.S. -> Washington -> Texas -> reset.
{
  const page = await open("/");
  await page.select("#geography", "53");
  await settle(4500);
  await save(page, "demand-washington");
  const waCells = await page.evaluate(() => window.__voltgapLayerCells ?? null);
  await page.select("#geography", "48");
  await settle(4500);
  await save(page, "demand-texas");
  const txCells = await page.evaluate(() => window.__voltgapLayerCells ?? null);
  await page.click(".geo-reset");
  await settle(4500);
  await save(page, "demand-reset");
  const usCells = await page.evaluate(() => window.__voltgapLayerCells ?? null);
  console.log(JSON.stringify({ waCells, txCells, usCells }));
  await page.close();
}

// Charging gaps: the whole universe, then a lens highlighting a subset of it.
{
  const page = await open("/access/");
  await save(page, "gaps-all");
  await page.evaluate(() => {
    const b = [...document.querySelectorAll(".segmented button")]
      .find((x) => x.textContent.includes("Most people"));
    b.click();
  });
  await settle(4500);
  await save(page, "gaps-people-national");
  await page.select("#geography", "53");
  await settle(4500);
  await save(page, "gaps-people-washington");
  await page.close();
}

await browser.close();
process.exit(0);
