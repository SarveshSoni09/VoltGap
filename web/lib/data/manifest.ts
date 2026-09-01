/**
 * `manifest.json` is read before anything else, and drives the freshness indicator.
 *
 * §13.3 requires a refresh health indicator driven by `computed_at`: if the data is older
 * than a configured threshold, the UI says so plainly. The threshold ships **inside** the
 * manifest so the page and the pipeline cannot disagree about what "stale" means.
 */

export const DATA_BASE = process.env.NEXT_PUBLIC_DATA_BASE ?? "/data";

export interface ArtifactRecord {
  readonly name: string;
  readonly bytes: number;
  readonly rows: number;
  readonly sha256: string;
  readonly columns: readonly string[];
}

export interface Manifest {
  readonly computed_at: string;
  readonly stale_after_days: number;
  readonly artifacts: Readonly<Record<string, ArtifactRecord>>;
  readonly source_vintages: Readonly<Record<string, string>>;
  readonly pipeline_phases: Readonly<Record<string, string>>;
  readonly notes: Readonly<Record<string, unknown>>;
}

export interface Freshness {
  readonly computedAt: Date;
  readonly ageDays: number;
  readonly stale: boolean;
  readonly staleAfterDays: number;
  readonly message: string;
}

export async function loadManifest(base: string = DATA_BASE): Promise<Manifest> {
  const response = await fetch(`${base}/manifest.json`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(
      `manifest.json unavailable (HTTP ${response.status}). The application will not ` +
        `render numbers it cannot describe the provenance of.`,
    );
  }
  return (await response.json()) as Manifest;
}

/**
 * Freshness from the manifest's own timestamp and threshold.
 *
 * Says the age plainly rather than hiding it: a stale-but-correct site beats a
 * fresh-but-broken one (§13.2), but only if the reader can tell which one they are looking
 * at.
 */
export function freshness(manifest: Manifest, now: Date = new Date()): Freshness {
  const computedAt = new Date(manifest.computed_at);
  const ageDays = (now.getTime() - computedAt.getTime()) / 86_400_000;
  const stale = ageDays > manifest.stale_after_days;
  return {
    computedAt,
    ageDays,
    stale,
    staleAfterDays: manifest.stale_after_days,
    message: stale
      ? `Data is ${Math.floor(ageDays)} days old, past the ${manifest.stale_after_days}-day refresh threshold. The scheduled refresh may have stopped.`
      : `Data refreshed ${ageDays < 1 ? "today" : `${Math.floor(ageDays)} days ago`}.`,
  };
}
