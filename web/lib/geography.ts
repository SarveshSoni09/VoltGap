/**
 * Where the reader is looking, and what changes when they change it.
 *
 * The geography control exists because the product asks a national question but is answered
 * locally: a planner works in one state, and reaching Washington by dragging the map from
 * a view of the whole country is not navigation, it is a chore.
 *
 * **Selecting a state filters the analysis, it does not only move the camera.** That choice
 * is deliberate and is stated in the interface, because the two are not interchangeable:
 * under a camera-only reading the figures beside the map would keep describing the country
 * while the map showed one state, and every denominator on the page would silently mean
 * something other than what the reader sees. `tests/geography.test.ts` asserts the parity
 * that this choice requires: a state's published figures equal the aggregate of the cells
 * drawn for it.
 */

/**
 * Two-letter code to full name. Distinct from `lib/data/states.ts`, which maps FIPS to
 * name for the six states the published frontier covers: that one answers "can the Studio
 * plan here", this one answers "what is this place called".
 *
 * Reference data, not a dataset: it is the naming the Census
 * publishes and does not change with a data refresh. Which of these actually appear in the
 * control is decided by the loaded artifact, never by this list, so a state with no
 * published cells cannot be offered as a choice.
 */
export const STATE_NAMES_BY_CODE: Readonly<Record<string, string>> = {
  AL: "Alabama", AK: "Alaska", AZ: "Arizona", AR: "Arkansas", CA: "California",
  CO: "Colorado", CT: "Connecticut", DE: "Delaware", DC: "District of Columbia",
  FL: "Florida", GA: "Georgia", HI: "Hawaii", ID: "Idaho", IL: "Illinois",
  IN: "Indiana", IA: "Iowa", KS: "Kansas", KY: "Kentucky", LA: "Louisiana",
  ME: "Maine", MD: "Maryland", MA: "Massachusetts", MI: "Michigan", MN: "Minnesota",
  MS: "Mississippi", MO: "Missouri", MT: "Montana", NE: "Nebraska", NV: "Nevada",
  NH: "New Hampshire", NJ: "New Jersey", NM: "New Mexico", NY: "New York",
  NC: "North Carolina", ND: "North Dakota", OH: "Ohio", OK: "Oklahoma", OR: "Oregon",
  PA: "Pennsylvania", PR: "Puerto Rico", RI: "Rhode Island", SC: "South Carolina",
  SD: "South Dakota", TN: "Tennessee", TX: "Texas", UT: "Utah", VT: "Vermont",
  VA: "Virginia", WA: "Washington", WV: "West Virginia", WI: "Wisconsin",
  WY: "Wyoming",
};

/** The national selection. Not a state code, and never rendered as one. */
export const NATIONAL = "US";

export interface Bounds {
  readonly west: number;
  readonly south: number;
  readonly east: number;
  readonly north: number;
}

/** The frame "the whole country" means: the lower 48 with room for Alaska and Hawaii. */
export const US_BOUNDS: Bounds = { west: -168, south: 18, east: -66, north: 66 };

export interface StateOption {
  /** FIPS, because that is what both published artifacts key on (domain rule G13). */
  readonly fips: string;
  readonly code: string;
  readonly name: string;
}

/**
 * The states the loaded data actually contains, in alphabetical order.
 *
 * Built from the artifact rather than from `STATE_NAMES` so the control can never offer a
 * geography that would come back empty. A FIPS with no code in the data is skipped rather
 * than shown as a bare number.
 */
export function statesPresent(
  fipsColumn: readonly string[], codeColumn: readonly string[],
): StateOption[] {
  const seen = new Map<string, string>();
  for (let i = 0; i < fipsColumn.length; i += 1) {
    const fips = fipsColumn[i] ?? "";
    const code = codeColumn[i] ?? "";
    if (fips === "" || code === "" || seen.has(fips)) continue;
    seen.set(fips, code);
  }
  const out: StateOption[] = [];
  for (const [fips, code] of seen) {
    const name = STATE_NAMES_BY_CODE[code];
    if (name === undefined) continue;
    out.push({ fips, code, name });
  }
  return out.sort((a, b) => a.name.localeCompare(b.name));
}

/**
 * The extent of a set of points, padded so the state does not touch the window edge.
 *
 * Computed from the cells being displayed rather than from a boundary file, which keeps
 * the camera and the analysis describing the same set: if a state's cells are what the
 * page is about, the frame around them is the honest frame.
 */
export function boundsOf(
  points: readonly { readonly longitude: number; readonly latitude: number }[],
  padDegrees = 0.6,
): Bounds | null {
  if (points.length === 0) return null;
  let west = Infinity, south = Infinity, east = -Infinity, north = -Infinity;
  for (const p of points) {
    if (!Number.isFinite(p.longitude) || !Number.isFinite(p.latitude)) continue;
    if (p.longitude < west) west = p.longitude;
    if (p.longitude > east) east = p.longitude;
    if (p.latitude < south) south = p.latitude;
    if (p.latitude > north) north = p.latitude;
  }
  if (!Number.isFinite(west) || !Number.isFinite(south)) return null;
  return {
    west: west - padDegrees, south: south - padDegrees,
    east: east + padDegrees, north: north + padDegrees,
  };
}

/**
 * FIPS to full state name, built from the loaded artifact.
 *
 * Needed because the published surfaces key on FIPS (domain rule G13: county and state
 * names collide, FIPS does not) while a reader needs a name. Without it a summary line
 * reads "Mostly in Texas (195.3k), 39 (139.9k), 20 (121.8k)", which is what shipped before
 * this was added: `lib/data/states.ts` covers only the six states the frontier publishes,
 * so every other FIPS fell through to its own digits.
 */
export function nameByFips(options: readonly StateOption[]): Map<string, string> {
  const out = new Map<string, string>();
  for (const o of options) out.set(o.fips, o.name);
  return out;
}

/** How the current geography is named in prose, so every view words it identically. */
export function geographyLabel(state: StateOption | null): string {
  return state === null ? "the United States" : state.name;
}

/**
 * How a ranked subset is named, given the geography it was ranked within.
 *
 * The wording carries the scope because the scope changes the mathematics. A national
 * top-100 by distance is 71 cells in Alaska and 17 in Montana; the same request scoped to
 * Washington is a different question with a different answer, and a control that silently
 * switched between them depending on the camera would be reporting two things under one
 * name.
 */
export function scopedLabel(base: string, state: StateOption | null): string {
  return state === null ? `${base} nationally` : `${base} in ${state.name}`;
}
