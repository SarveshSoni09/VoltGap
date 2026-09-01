"use client";

import { useEffect, useState } from "react";

import { freshness, loadManifest, type Freshness } from "../lib/data/manifest";

/**
 * §13.3: refresh health, driven by `manifest.json.computed_at`. If the data is older than
 * the threshold the manifest itself carries, the UI says so plainly rather than presenting
 * stale numbers as current.
 */
export function FreshnessIndicator() {
  const [state, setState] = useState<Freshness | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    loadManifest()
      .then((manifest) => setState(freshness(manifest)))
      .catch(() => setFailed(true));
  }, []);

  if (failed) {
    return <div className="freshness stale">Data manifest unavailable</div>;
  }
  if (state === null) {
    return <div className="freshness">Checking data freshness…</div>;
  }
  return (
    <div className={state.stale ? "freshness stale" : "freshness"}>
      {state.message}
    </div>
  );
}
