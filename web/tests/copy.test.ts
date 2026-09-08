import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * Deterministic checks on the copy that actually reaches a reader.
 *
 * These read the built HTML rather than the source, so a string is checked wherever it
 * came from: a page, a shared component, a vocabulary constant, or a document title. A
 * source-level grep would miss text assembled at render time and would flag code comments
 * that no reader ever sees.
 *
 * Only mechanical rules live here. Tone is a review question, not a test, and a lint that
 * tried to score prose quality would produce more false positives than it caught.
 */

const OUT = join(__dirname, "..", "out");

/**
 * Written as an escape on purpose.
 *
 * The literal character must not appear in this file: it is the thing being banned, and a
 * repository-wide sweep for it would otherwise delete the detector along with the copy.
 * That is not hypothetical, it is what happened while this rule was first applied.
 */
const EM_DASH = /\u2014/g;

const ROUTES = [
  ["/", "index.html"],
  ["/access/", "access/index.html"],
  ["/studio/", "studio/index.html"],
  ["/how-it-works/", "how-it-works/index.html"],
  ["/methodology/", "methodology/index.html"],
] as const;

/**
 * Visible text plus the attributes a reader or screen reader is given.
 *
 * Inline scripts are stripped first: Next.js serialises the React tree into them, so every
 * string would otherwise be counted twice, and a match inside serialised JSON gives a
 * useless location. `<title>` is kept deliberately, because the tab name is copy too.
 */
function readableText(html: string): string {
  const withoutScripts = html.replace(/<script[\s\S]*?<\/script>/g, " ");
  const attributes = [...withoutScripts.matchAll(/(?:aria-label|alt|title)="([^"]*)"/g)]
    .map((m) => m[1])
    .join(" ");
  const body = withoutScripts.replace(/<[^>]+>/g, " ");
  return `${body} ${attributes}`;
}

function pages(): { route: string; text: string }[] {
  return ROUTES.map(([route, file]) => ({
    route,
    text: readableText(readFileSync(join(OUT, file), "utf8")),
  }));
}

describe("user-facing copy", () => {
  it.each(ROUTES.map(([route]) => route))("%s contains no em dash", (route) => {
    const page = pages().find((p) => p.route === route);
    expect(page).toBeDefined();
    const found = [...(page?.text ?? "").matchAll(EM_DASH)].map((m) =>
      (page?.text ?? "").slice(Math.max(0, (m.index ?? 0) - 60), (m.index ?? 0) + 60),
    );
    expect(found, `em dash in ${route}: ${JSON.stringify(found.slice(0, 3))}`).toEqual([]);
  });

  /**
   * The §11.5 claim rules, checked against rendered output.
   *
   * The Python copy lint already covers source files, and this is not a substitute for it.
   * It closes a different gap: a prohibited phrase assembled at render time from two
   * legal-looking source fragments would pass the source lint and still reach the screen.
   */
  const FORBIDDEN = [
    "best site",
    "optimal site",
    "optimal location",
    "proven siting",
    "grid feasible",
    "interconnection ready",
    "available grid capacity",
    "transformer headroom",
    "charging desert",
    "Justice40 compliance",
  ];

  it.each(ROUTES.map(([route]) => route))("%s makes no prohibited claim", (route) => {
    const page = pages().find((p) => p.route === route);
    const text = (page?.text ?? "").toLowerCase();
    const hits = FORBIDDEN.filter((phrase) => text.includes(phrase));
    expect(hits, `prohibited claim in ${route}`).toEqual([]);
  });

  it("never labels the highest reliability tier as observed", () => {
    // Tier A is "sub-state anchored": most of it is allocated from ZIP or county
    // registrations, so calling it observed would overstate what is behind the number.
    for (const { route, text } of pages()) {
      expect(/tier a[^.]{0,40}observed/i.test(text), route).toBe(false);
      expect(/observed[^.]{0,20}tier a/i.test(text), route).toBe(false);
    }
  });

  it("states the age of the data as a build, not a refresh", () => {
    // A frozen release has no scheduled refresh to report on. The string lives in a
    // client component, so it is asserted at its source rather than in the static HTML.
    // Only the message templates are checked. The surrounding comment quotes the removed
    // wording on purpose, to record what was wrong with it.
    const source = readFileSync(
      join(__dirname, "..", "lib", "data", "manifest.ts"), "utf8",
    );
    const templates = [...source.matchAll(/`Data[^`]*`/g)].map((m) => m[0]);
    expect(templates.length).toBeGreaterThan(0);
    for (const template of templates) {
      expect(template).not.toMatch(/scheduled refresh/i);
      expect(template).not.toMatch(/refreshed/i);
      expect(template).toMatch(/artifacts built/i);
    }
  });
});
