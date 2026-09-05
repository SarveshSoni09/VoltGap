"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { CardAnchor } from "../../components/CardAnchor";
import { Disclosure } from "../../components/Disclosure";
import { FeatureCard } from "../../components/FeatureCard";
import { cellBoundaries, type Boundaries } from "../../lib/data/geometry";
import { hexRow, loadHexTable, type HexRow } from "../../lib/data/hexes";
import { STATE_NAMES } from "../../lib/data/states";
import type { ColumnTable } from "../../lib/data/table";
import { downloadBlob, toCsv, toGeoJson, type PortfolioRow } from "../../lib/exporters";
import { buildCandidates } from "../../lib/optimizer/candidates";
import type { Outgoing, SolvedMessage } from "../../lib/optimizer/worker";
import { areaName, cohortOf, headlineReason, reasonsFor } from "../../lib/reasons";
import { perVertexColors } from "../../lib/render";
import { formatCompact, formatCount } from "../../lib/scales";
import {
  RECOMMENDATION_NOTE,
  TIER_DESCRIPTIONS,
  TIER_LABELS,
  TIER_LABELS_PLAIN,
  type Tier,
} from "../../lib/vocabulary";

const HexMap = dynamic(() => import("../../components/HexMap"), {
  ssr: false,
  loading: () => <div className="loading">Loading map…</div>,
});

const STATES = ["53", "47", "30", "50", "48", "06"] as const;

/** Plain presets over the objective weights. Advanced exposes the slider itself. */
const PRIORITIES = [
  { id: "demand", label: "Demand", weight: 1.0,
    hint: "Favour areas with the most estimated EV demand." },
  { id: "balanced", label: "Balanced", weight: 0.6,
    hint: "Weigh demand and underserved population together." },
  { id: "underserved", label: "Underserved communities", weight: 0.2,
    hint: "Favour areas reaching more lower-income households." },
] as const;

/** Map colours. Selection is a shape difference, not a shade difference. */
const SELECTED: readonly [number, number, number, number] = [255, 193, 61, 255];
const ELIGIBLE: readonly [number, number, number, number] = [120, 132, 152, 70];

export default function SitingStudio() {
  const [table, setTable] = useState<ColumnTable | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [state, setState] = useState<string>("53");
  const [budget, setBudget] = useState(20);
  const [priority, setPriority] = useState<string>("balanced");
  const [demandWeight, setDemandWeight] = useState(0.6);
  const [advanced, setAdvanced] = useState(false);
  /** Where the reader came from, so the page acknowledges it rather than resetting them. */
  const [arrivedFrom, setArrivedFrom] = useState<{ page: string; note: string } | null>(null);
  const [result, setResult] = useState<SolvedMessage | null>(null);
  const [openRow, setOpenRow] = useState<string | null>(null);
  const [boundaries, setBoundaries] = useState<Boundaries | null>(null);
  /**
   * Map and table are two views of one list, so they share one hover.
   *
   * `hover` is whichever area the reader is pointing at, wherever they are pointing: the
   * map highlights its marker, the table highlights its row, and the card describes it.
   * Without this the two halves of the page were separate documents that happened to sit
   * beside each other.
   */
  const [hover, setHover] = useState<string | null>(null);
  const [cursor, setCursor] = useState({ x: 0, y: 0 });
  /**
   * Where the hover came from. A card summoned by the table must not appear at the last
   * place the mouse happened to be on the map — it parks in the corner instead, which is
   * also where a pinned card sits, so the reader's eye has one place to look.
   */
  const [hoverFrom, setHoverFrom] = useState<"map" | "table">("map");
  const [pinned, setPinned] = useState<string | null>(null);
  const [focus, setFocus] =
    useState<{ longitude: number; latitude: number; zoom: number } | null>(null);
  const worker = useRef<Worker | null>(null);
  const rowRefs = useRef(new Map<string, HTMLTableRowElement>());

  useEffect(() => {
    loadHexTable().then(setTable).catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    // Cross-page context. A reader who clicked "plan locations in Washington" from another
    // view should land on Washington, and should be told that is why they are looking at
    // it. The link carries only WHERE to look — it never changes what the optimiser
    // computes, and the threshold travels as a sentence, not as a solver input.
    const params = new URLSearchParams(window.location.search);
    const wanted = params.get("state");
    if (wanted !== null && STATE_NAMES[wanted] !== undefined) setState(wanted);
    const from = params.get("from");
    if (from === "gaps") {
      const km = params.get("threshold");
      setArrivedFrom({
        page: "Charging gaps",
        note: km === null
          ? "You came from the charging-gaps map."
          : `You came from the charging-gaps map, where "far" was set to ${km} km. ` +
            "That setting describes the gap; it is not used to choose these areas.",
      });
    } else if (from === "national") {
      setArrivedFrom({
        page: "National overview",
        note: "You came from the national demand map.",
      });
    }
  }, []);

  useEffect(() => {
    const instance = new Worker(
      new URL("../../lib/optimizer/worker.ts", import.meta.url), { type: "module" });
    instance.onmessage = (event: MessageEvent<Outgoing>) => {
      if (event.data.kind === "solved") setResult(event.data);
      else setError(event.data.message);
    };
    worker.current = instance;
    return () => {
      instance.terminate();
      worker.current = null;
    };
  }, []);

  const effectiveWeight = advanced
    ? demandWeight
    : (PRIORITIES.find((p) => p.id === priority)?.weight ?? 0.6);

  const stateRows = useMemo<HexRow[]>(() => {
    if (table === null) return [];
    const states = table.strs("state_fips");
    const out: HexRow[] = [];
    for (let i = 0; i < table.length; i += 1) {
      if (states[i] === state) out.push(hexRow(table, i));
    }
    return out;
  }, [table, state]);

  const candidateSet = useMemo(
    () => (stateRows.length === 0 ? null : buildCandidates(stateRows, 2.0)),
    [stateRows],
  );

  useEffect(() => {
    if (worker.current === null || candidateSet === null) return;
    worker.current.postMessage({
      kind: "load",
      candidates: candidateSet.candidates,
      coverage: [...candidateSet.coverage.entries()],
    });
    worker.current.postMessage({
      kind: "solve", budget,
      weights: { demand: effectiveWeight, equity: 1 - effectiveWeight },
    });
  }, [candidateSet, budget, effectiveWeight]);

  const selected = useMemo(() => new Set(result?.selected ?? []), [result]);
  const byIndex = useMemo(
    () => new Map(stateRows.map((r) => [r.h3_index, r])), [stateRows]);

  // Only ELIGIBLE areas are drawn. Screened-out geography is not candidate data and is
  // not rendered as if it were: the map answers "where are the recommended areas", and
  // everything drawn is something that could have been chosen.
  const eligible = useMemo(
    () => (candidateSet === null
      ? []
      : candidateSet.candidates.map((c) => byIndex.get(c.h3_index)).filter(
          (r): r is HexRow => r !== undefined)),
    [candidateSet, byIndex],
  );

  useEffect(() => {
    if (eligible.length === 0) {
      setBoundaries(null);
      return;
    }
    let cancelled = false;
    cellBoundaries(eligible.map((r) => r.h3_index)).then((b) => {
      if (!cancelled) setBoundaries(b);
    });
    return () => { cancelled = true; };
  }, [eligible]);

  const colors = useMemo<Uint8Array | null>(() => {
    if (boundaries === null || eligible.length === 0) return null;
    return perVertexColors(boundaries, (cell) => {
      const row = eligible[cell];
      if (row === undefined) return ELIGIBLE;
      return selected.has(row.h3_index) ? SELECTED : ELIGIBLE;
    });
  }, [boundaries, eligible, selected]);

  const cohort = useMemo(() => cohortOf(eligible), [eligible]);

  useEffect(() => {
    // A rank means nothing across a re-solve, so nothing carries over from the last one.
    setHover(null);
    setPinned(null);
    setOpenRow(null);
  }, [state, budget, effectiveWeight]);

  const selectedMarkers = useMemo(
    () =>
      (result?.selected ?? []).flatMap((index, i) => {
        const row = byIndex.get(index);
        return row === undefined
          ? []
          : [{ longitude: row.longitude, latitude: row.latitude, rank: i + 1 }];
      }),
    [result, byIndex],
  );

  const portfolio = useMemo<PortfolioRow[]>(() => {
    if (result === null) return [];
    return result.selected.flatMap((index, i) => {
      const row = byIndex.get(index);
      if (row === undefined) return [];
      return [{
        h3_index: row.h3_index, latitude: row.latitude, longitude: row.longitude,
        rank: i + 1, demand_bev: row.demand_bev,
        equity_population: row.equity_population, population: row.population,
        uncertainty_score: row.uncertainty_score,
        confidence_tier: row.confidence_tier,
        dominant_evidence_grain: row.dominant_evidence_grain,
        sub_state_anchored_share: row.sub_state_anchored_share,
        existing_dcfc_ports: row.dcfc_ports,
        km_to_nearest_dcfc_site: row.km_to_nearest_dcfc_site,
      }];
    });
  }, [result, byIndex]);

  /** Rank by h3 index, so map and table agree on what "#4" means. */
  const rankOf = useMemo(
    () => new Map((result?.selected ?? []).map((index, i) => [index, i + 1])),
    [result],
  );

  /** Focuses the map and the table on one area, from either side of the page. */
  const reveal = useCallback((h3: string) => {
    const row = byIndex.get(h3);
    if (row === undefined) return;
    setPinned(h3);
    setOpenRow(h3);
    setFocus({ longitude: row.longitude, latitude: row.latitude, zoom: 8.5 });
    // Two frames later, and instantly rather than smoothly.
    //
    // Opening the row inserts a detail row that moves the target, so a scroll issued in
    // the same tick aims at the pre-expansion position; and React replacing the rows on
    // that re-render cancels a smooth scroll part-way, which is what left the table
    // sitting at 7.5 px instead of at rank 13. Waiting for the committed layout and
    // jumping outright is both correct and uninterruptible.
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        const node = rowRefs.current.get(h3);
        const wrap = node?.closest(".tablewrap");
        if (node === undefined || !(wrap instanceof HTMLElement)) return;
        const offset = node.getBoundingClientRect().top - wrap.getBoundingClientRect().top;
        wrap.scrollTop += offset - wrap.clientHeight / 2 + node.clientHeight / 2;
      });
    });
  }, [byIndex]);

  const cardRow = useMemo(() => {
    const h3 = pinned ?? hover;
    return h3 === null ? null : (byIndex.get(h3) ?? null);
  }, [pinned, hover, byIndex]);

  const centre = useMemo(() => {
    if (eligible.length === 0) return undefined;
    const lat = eligible.reduce((s, r) => s + r.latitude, 0) / eligible.length;
    const lon = eligible.reduce((s, r) => s + r.longitude, 0) / eligible.length;
    return { latitude: lat, longitude: lon, zoom: 5.8 };
  }, [eligible]);

  const exportCsv = useCallback(() => {
    downloadBlob(`voltgap_${state}.csv`, "text/csv", toCsv(portfolio));
  }, [portfolio, state]);
  const exportGeoJson = useCallback(() => {
    downloadBlob(`voltgap_${state}.geojson`, "application/geo+json",
      JSON.stringify(toGeoJson(portfolio), null, 2));
  }, [portfolio, state]);

  if (error !== null) return <div className="error">{error}</div>;

  const stateName = STATE_NAMES[state] ?? state;
  const withoutCharging = portfolio.filter((r) => r.existing_dcfc_ports === 0).length;
  const higherReliability = portfolio.filter((r) => r.confidence_tier === "A").length;
  const demandCovered = result?.demandCovered ?? 0;
  const equityCovered = result?.equityCovered ?? 0;

  return (
    <div className="view">
      <aside className="sidebar">
        <div className="lede">
          <h1>Plan new charging locations</h1>
          <p>
            Choose where and how much, and VoltGap shows candidate areas worth
            considering.
          </p>
        </div>

        {arrivedFrom !== null && (
          <div className="arrived">
            <strong>{arrivedFrom.page}</strong>
            <p>{arrivedFrom.note}</p>
          </div>
        )}

        <div className="field">
          <label htmlFor="state">Where</label>
          <select id="state" value={state} onChange={(e) => setState(e.target.value)}>
            {STATES.map((fips) => (
              <option key={fips} value={fips}>{STATE_NAMES[fips] ?? fips}</option>
            ))}
          </select>
        </div>

        <div className="field">
          <label htmlFor="budget">How many new locations can you fund?</label>
          <input
            id="budget" type="range" min={1} max={100} step={1}
            value={budget} onChange={(e) => setBudget(Number(e.target.value))}
          />
          <div className="rangeval">{budget} areas</div>
        </div>

        <div className="field">
          <label>What matters most?</label>
          <div className="segmented">
            {PRIORITIES.map((p) => (
              <button
                key={p.id}
                className={priority === p.id && !advanced ? "on" : ""}
                onClick={() => { setPriority(p.id); setAdvanced(false); }}
              >
                {p.label}
              </button>
            ))}
          </div>
          <p className="hint">
            {advanced
              ? "Custom weighting in use."
              : PRIORITIES.find((p) => p.id === priority)?.hint}
          </p>
        </div>

        <Disclosure question="Advanced weighting" tone="quiet">
          <p>
            The preset above sets the balance between the two objectives. Set it directly
            here.
          </p>
          <input
            type="range" min={0} max={1} step={0.05} value={demandWeight}
            onChange={(e) => { setDemandWeight(Number(e.target.value)); setAdvanced(true); }}
          />
          <p>
            {Math.round(effectiveWeight * 100)}% estimated demand,{" "}
            {Math.round((1 - effectiveWeight) * 100)}% underserved population.
          </p>
        </Disclosure>

        {result !== null && (
          <>
            <h3>Your {stateName} portfolio</h3>
            <div className="figures">
              <div className="figure">
                <div className="n">{result.selected.length}</div>
                <div className="l">candidate areas</div>
              </div>
              <div className="figure">
                <div className="n">{formatCompact(demandCovered)}</div>
                <div className="l">estimated EVs in range</div>
              </div>
              <div className="figure">
                <div className="n">{formatCompact(equityCovered)}</div>
                <div className="l">underserved population reached</div>
              </div>
              <div className="figure">
                <div className="n">{withoutCharging}</div>
                <div className="l">with no fast charging today</div>
              </div>
            </div>
            <div className="chips">
              <span className="chip a">{higherReliability} higher reliability</span>
              <span className="chip b">
                {portfolio.length - higherReliability} modelled
              </span>
            </div>
            <div className="row" style={{ marginTop: "0.8rem" }}>
              <button onClick={exportCsv}>Export CSV</button>
              <button onClick={exportGeoJson}>Export GeoJSON</button>
            </div>
          </>
        )}

        <Disclosure question="About these recommendations">
          <p>{RECOMMENDATION_NOTE}</p>
          <p>
            <a href="/methodology/">Learn how this works</a>
          </p>
        </Disclosure>

        {candidateSet !== null && (
          <Disclosure question="How were areas screened?" tone="quiet">
            <p>
              {formatCompact(candidateSet.candidates.length)} eligible areas were
              evaluated in {stateName}. Screened out:
            </p>
            <table>
              <tbody>
                <tr>
                  <td>outside the road-proximity range</td>
                  <td className="num">
                    {candidateSet.excluded.beyond_primary_secondary_road_network ?? 0}
                  </td>
                </tr>
                <tr>
                  <td>already well served</td>
                  <td className="num">{candidateSet.excluded.already_saturated ?? 0}</td>
                </tr>
                <tr>
                  <td>nobody lives there</td>
                  <td className="num">{candidateSet.excluded.uninhabited ?? 0}</td>
                </tr>
              </tbody>
            </table>
            <p style={{ marginTop: "0.5rem" }}>
              There is no electrical-grid filter: no authoritative national substation
              dataset exists, so siting works without one.
            </p>
          </Disclosure>
        )}
      </aside>

      <div className="canvas" style={{ display: "grid", gridTemplateRows: "1fr auto" }}>
        <div style={{ position: "relative" }}>
          {table === null ? (
            <div className="loading">Loading areas…</div>
          ) : (
            <>
              <div className="mapsummary">
                <div>
                  {stateName} · <strong>{result?.selected.length ?? 0}</strong> of{" "}
                  {formatCompact(eligible.length)} eligible areas selected
                </div>
                <div className="places">
                  Hover or click a numbered area to find it in the table below.
                </div>
              </div>
              <HexMap
                boundaries={boundaries}
                colors={colors}
                selected={selectedMarkers}
                initialViewState={centre}
                highlightRank={hover === null ? null : (rankOf.get(hover) ?? null)}
                focus={focus}
                onHoverCell={(index, x, y) => {
                  setHover(index === null ? null : (eligible[index]?.h3_index ?? null));
                  setCursor({ x, y });
                  setHoverFrom("map");
                }}
                onPickCell={(index) => {
                  const h3 = index === null ? null : eligible[index]?.h3_index;
                  if (h3 !== undefined && h3 !== null) reveal(h3);
                }}
                onHoverSelected={(rank, x, y) => {
                  if (rank === null) return;
                  const picked = result?.selected[rank - 1];
                  if (picked !== undefined) {
                    setHover(picked);
                    setCursor({ x, y });
                    setHoverFrom("map");
                  }
                }}
                onPickSelected={(rank) => {
                  if (rank === null) return;
                  const picked = result?.selected[rank - 1];
                  if (picked !== undefined) reveal(picked);
                }}
              />
              {cardRow !== null && (
                <CardAnchor
                  pinned={pinned !== null || hoverFrom === "table"}
                  x={cursor.x}
                  y={cursor.y}
                  onClose={
                    pinned === null
                      ? undefined
                      : () => { setPinned(null); setOpenRow(null); }
                  }
                >
                  <FeatureCard
                    rank={rankOf.get(cardRow.h3_index)}
                    place={areaName(cardRow, rankOf.get(cardRow.h3_index) ?? 0)}
                    primaryLabel={
                      rankOf.has(cardRow.h3_index)
                        ? "In your portfolio"
                        : "Eligible, not selected"
                    }
                    primaryValue={formatCompact(cardRow.demand_bev) + " estimated EVs"}
                    facts={[
                      { label: "Underserved population",
                        value: formatCompact(cardRow.equity_population) },
                      { label: "Existing fast charging",
                        value: formatCount(cardRow.dcfc_ports) },
                      { label: "Nearest fast charging",
                        value: cardRow.km_to_nearest_dcfc_site.toFixed(0) + " km" },
                    ]}
                    reasons={reasonsFor(cardRow, cohort).slice(0, 2)}
                    reliability={{
                      label: TIER_LABELS_PLAIN[cardRow.confidence_tier],
                      tier: cardRow.confidence_tier,
                    }}
                    technical={
                      pinned === null
                        ? undefined
                        : [
                            { label: "H3 cell", value: cardRow.h3_index },
                            { label: "Uncertainty score",
                              value: cardRow.uncertainty_score.toFixed(3) },
                            { label: "Centroid",
                              value: `${cardRow.latitude.toFixed(4)}, ${cardRow.longitude.toFixed(4)}` },
                          ]
                    }
                  />
                </CardAnchor>
              )}
              <div className="legend">
                <div>{stateName}</div>
                <div className="swatches">
                  <span className="sw">
                    <i style={{ background: "rgb(255,193,61)" }} />
                    selected for this portfolio ({result?.selected.length ?? 0})
                  </span>
                  <span className="sw">
                    <i style={{ background: "rgba(120,132,152,0.45)" }} />
                    other eligible areas
                  </span>
                  <span className="sw">
                    <i className="hollow" />
                    not a candidate — screened out or unpopulated
                  </span>
                </div>
              </div>
            </>
          )}
        </div>
        <div className="tablewrap">
          <table>
            <thead>
              <tr>
                <th className="num">Rank</th>
                <th>Area</th>
                <th>Why it stands out</th>
                <th className="num">Estimated EV demand</th>
                <th className="num">Underserved population</th>
                <th className="num">Existing fast charging</th>
                <th>Estimate reliability</th>
              </tr>
            </thead>
            <tbody>
              {portfolio.map((row) => {
                const source = byIndex.get(row.h3_index);
                const open = openRow === row.h3_index;
                return (
                  <>
                    <tr
                      key={row.h3_index}
                      ref={(node) => {
                        if (node === null) rowRefs.current.delete(row.h3_index);
                        else rowRefs.current.set(row.h3_index, node);
                      }}
                      onMouseEnter={() => { setHover(row.h3_index); setHoverFrom("table"); }}
                      onMouseLeave={() => setHover(null)}
                      onClick={() => {
                        if (open) {
                          setOpenRow(null);
                          setPinned(null);
                        } else {
                          reveal(row.h3_index);
                        }
                      }}
                      className={[
                        open ? "open" : "",
                        hover === row.h3_index ? "linked" : "",
                      ].filter(Boolean).join(" ")}
                    >
                      <td className="num">{row.rank}</td>
                      <td>{source ? areaName(source, row.rank) : `Area ${row.rank}`}</td>
                      <td className="why">
                        {source ? headlineReason(source, cohort) : "—"}
                      </td>
                      <td className="num">{formatCompact(row.demand_bev)}</td>
                      <td className="num">{formatCompact(row.equity_population)}</td>
                      <td className="num">
                        {row.existing_dcfc_ports === 0
                          ? "none"
                          : row.existing_dcfc_ports.toFixed(0)}
                      </td>
                      <td>
                        <span
                          className={`tier ${row.confidence_tier.toLowerCase()}`}
                          title={TIER_DESCRIPTIONS[row.confidence_tier]}
                        >
                          <span className="dot" />
                          {TIER_LABELS_PLAIN[row.confidence_tier]}
                        </span>
                      </td>
                    </tr>
                    {open && source && (
                      <tr key={`${row.h3_index}-d`} className="detail">
                        <td />
                        <td colSpan={6}>
                          <strong>Why this area ranked highly</strong>
                          <ul>
                            {reasonsFor(source, cohort).map((reason) => (
                              <li key={reason}>{reason}</li>
                            ))}
                          </ul>
                          <details>
                            <summary>Technical details</summary>
                            <dl>
                              <dt>H3 cell</dt>
                              <dd>{row.h3_index}</dd>
                              <dt>Uncertainty score</dt>
                              <dd>{row.uncertainty_score.toFixed(3)}</dd>
                              <dt>Confidence tier</dt>
                              <dd>
                                {TIER_LABELS[row.confidence_tier]} (
                                {row.dominant_evidence_grain})
                              </dd>
                              <dt>Centroid</dt>
                              <dd>
                                {row.latitude.toFixed(4)}, {row.longitude.toFixed(4)}
                              </dd>
                            </dl>
                          </details>
                        </td>
                      </tr>
                    )}
                  </>
                );
              })}
            </tbody>
          </table>
          {portfolio.length === 0 && (
            <p className="hint" style={{ padding: "0.8rem 1rem" }}>
              Adjust the budget to select areas.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
