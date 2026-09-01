/**
 * The static export, served for measurement. Deliberately trivial: no compression, no
 * caching headers, no CDN behaviour, so the performance harness measures the application
 * rather than a server's cleverness. Phase 7 adds deployed measurement on real hosting.
 */
import { createServer } from "node:http";
import { existsSync, readFileSync, statSync } from "node:fs";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("./out/", import.meta.url));
const PORT = Number(process.env.PORT ?? 4321);
const TYPES = {
  ".html": "text/html", ".js": "text/javascript", ".css": "text/css",
  ".json": "application/json", ".parquet": "application/octet-stream",
  ".svg": "image/svg+xml", ".ico": "image/x-icon", ".txt": "text/plain",
  ".woff2": "font/woff2", ".map": "application/json",
};

createServer((request, response) => {
  const requested = decodeURIComponent((request.url ?? "/").split("?")[0]);
  // normalize + prefix check: a served directory must not be escapable with "..".
  let path = normalize(join(ROOT, requested));
  if (!path.startsWith(ROOT)) {
    response.writeHead(403).end("forbidden");
    return;
  }
  if (existsSync(path) && statSync(path).isDirectory()) path = join(path, "index.html");
  if (!existsSync(path)) {
    response.writeHead(404).end("not found");
    return;
  }
  response.writeHead(200, {
    "Content-Type": TYPES[extname(path)] ?? "application/octet-stream",
  });
  response.end(readFileSync(path));
}).listen(PORT);
