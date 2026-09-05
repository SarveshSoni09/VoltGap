/** Screenshots of the interactions this pass added, for the phase report. */
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer";

const PORT = 4394;
const server = spawn("node", [fileURLToPath(new URL("../serve-static.mjs", import.meta.url))],
  { env: { ...process.env, PORT: String(PORT) }, stdio: "ignore" });
process.on("exit", () => server.kill());
await new Promise((r) => setTimeout(r, 800));

const browser = await puppeteer.launch({
  headless: true, args: ["--no-sandbox", "--enable-gpu", "--window-size=1440,900"],
});
const shot = async (path, name, steps) => {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });
  await page.goto(`http://localhost:${PORT}${path}`, { waitUntil: "networkidle0" });
  await new Promise((r) => setTimeout(r, 9000));
  if (steps) await steps(page);
  await page.screenshot({ path: `../docs/evidence/ux/explore-${name}.png` });
  await page.close();
  console.log(name);
};

const mapPoint = async (page, fx, fy) => {
  const box = await page.evaluate(() => {
    const c = document.querySelector(".canvas canvas").getBoundingClientRect();
    return { x: c.x, y: c.y, w: c.width, h: c.height };
  });
  return { x: box.x + box.w * fx, y: box.y + box.h * fy };
};

await shot("/", "national-hover", async (page) => {
  for (const [fx, fy] of [[0.52, 0.42], [0.45, 0.5], [0.6, 0.45], [0.5, 0.55]]) {
    const p = await mapPoint(page, fx, fy);
    await page.mouse.move(p.x, p.y);
    await new Promise((r) => setTimeout(r, 500));
    if (await page.evaluate(() => document.querySelector(".fcard") !== null)) break;
  }
});

await shot("/access/", "gaps-map", null);

await shot("/access/", "gaps-pinned", async (page) => {
  for (const [fx, fy] of [[0.45, 0.35], [0.5, 0.4], [0.4, 0.45], [0.55, 0.5]]) {
    const p = await mapPoint(page, fx, fy);
    await page.mouse.move(p.x, p.y);
    await new Promise((r) => setTimeout(r, 400));
    if (await page.evaluate(() => document.querySelector(".fcard") !== null)) {
      await page.mouse.click(p.x, p.y);
      await new Promise((r) => setTimeout(r, 800));
      break;
    }
  }
});

await shot("/studio/?state=53", "studio-row-hover", async (page) => {
  await page.evaluate(() => {
    const rows = document.querySelectorAll(".tablewrap tbody tr");
    rows[2]?.scrollIntoView({ block: "center" });
  });
  await new Promise((r) => setTimeout(r, 400));
  const box = await page.evaluate(() => {
    const r = document.querySelectorAll(".tablewrap tbody tr")[2].getBoundingClientRect();
    return { x: r.x + 120, y: r.y + r.height / 2 };
  });
  await page.mouse.move(box.x, box.y);
  await new Promise((r) => setTimeout(r, 700));
});

await browser.close();
server.kill();
