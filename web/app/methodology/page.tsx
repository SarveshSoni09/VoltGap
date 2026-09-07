import Link from "next/link";

import { TocNav } from "../../components/TocNav";
import {
  CEJST_NOTE,
  DEPLOYMENT_ALIGNMENT_NOTE,
  GRID_PROXIMITY_NOTE,
  INTERACTIVE_SOLVER_NOTE,
  NOT_OPTIMALITY_NOTE,
  VALIDATION_TERMS,
} from "../../lib/vocabulary";

/**
 * The technical record: a case study for an engineer or an analyst who wants to check the
 * work rather than take it on trust.
 *
 * Every figure quoted here is copied from an accepted phase evidence artifact or gate run
 * and is reproducible from the repository. Nothing is strengthened for presentation — the
 * headline historical-deployment-alignment result is negative against a population
 * baseline and is reported as such, in the same size type as everything else.
 *
 * The plain-language version lives at /how-it-works. This page assumes the reader wants
 * the detail and does not apologise for it.
 */
export const metadata = {
  title: "Methodology & Architecture — VoltGap",
  description:
    "The full technical record: data sources, pipeline, models, validation, uncertainty, " +
    "spatial representation, optimization, frontend engineering, testing and limitations.",
};

const SECTIONS = [
  { id: "problem", label: "A. Problem definition" },
  { id: "architecture", label: "B. System architecture" },
  { id: "sources", label: "C. Data sources" },
  { id: "acquisition", label: "D. Acquisition & provenance" },
  { id: "canonical", label: "E. Cleaning & canonicalization" },
  { id: "missing", label: "F. Missing data" },
  { id: "supply", label: "G. Charging supply model" },
  { id: "access", label: "H. Charging-access model" },
  { id: "demand", label: "I. Demand model" },
  { id: "uncertainty", label: "J. Uncertainty & confidence" },
  { id: "leakage", label: "K. Temporal leakage protection" },
  { id: "h3", label: "L. H3 & spatial representation" },
  { id: "screening", label: "M. Road & candidate screening" },
  { id: "optimization", label: "N. Portfolio optimization" },
  { id: "browser-solver", label: "O. Browser interactive solver" },
  { id: "alignment", label: "P. Historical deployment alignment" },
  { id: "robustness", label: "Q. Cross-objective robustness" },
  { id: "frontend", label: "R. Frontend architecture" },
  { id: "performance", label: "S. Browser performance" },
  { id: "testing", label: "T. Testing & quality" },
  { id: "reproducibility", label: "U. Reproducibility" },
  { id: "limitations", label: "V. Known limitations" },
  { id: "stack", label: "W. Technology stack" },
] as const;

/** The pipeline, as a stage list the diagram and the prose both read from. */
const PIPELINE = [
  { stage: "Public data sources", detail: "62 contracted entries across 12+ dataset families" },
  { stage: "Source verification & caching", detail: "schema discovery, SHA-256, content validation" },
  { stage: "Canonical data models", detail: "DuckDB staging → intermediate → marts, Pandera-validated" },
  { stage: "Supply / access / demand modeling", detail: "power ladder, population-weighted distance, Poisson GLM" },
  { stage: "Geospatial H3 processing", detail: "resolution 6 national, block-weighted allocation" },
  { stage: "Candidate generation", detail: "inhabited, road-proximate, unsaturated" },
  { stage: "Offline optimization & validation", detail: "PuLP + CBC ε-constraint, three validation tracks" },
  { stage: "Static publication artifacts", detail: "11 MB of Parquet + JSON, checksummed in a manifest" },
  { stage: "Next.js / TypeScript frontend", detail: "static export, no server runtime" },
  { stage: "Browser workers, solver, maps", detail: "Parquet decode, H3 geometry, greedy re-solve, deck.gl" },
] as const;

const SOURCES = [
  {
    provider: "NREL / AFDC",
    dataset: "Alternative Fuel Station Locator — stations",
    grain: "Station record (one network's presence at a site)",
    vintage: "Current snapshot; frozen seed 2024-12-11",
    role: "Existing charging supply, access distance, historical reconstruction",
    limits: "A row is a station, never a count of ports. Open dates approximate (G10).",
  },
  {
    provider: "NREL / AFDC",
    dataset: "EV charging units (JSON primary, CSV fallback)",
    grain: "One row per EVSE",
    vintage: "Current snapshot",
    role: "Port counts, connector types, reported power",
    limits: "No unit identifier; 65.9% of rows byte-identical to another. No longitudinal unit identity is claimed.",
  },
  {
    provider: "NREL / AFDC",
    dataset: "State EV registration counts, 10 annual vintages",
    grain: "State",
    vintage: "2016–2025",
    role: "Demand reconciliation totals; backtest constraint at each origin",
    limits: "Stock, not sales (G8). Contains a US total row excluded before aggregation.",
  },
  {
    provider: "Atlas EV Hub",
    dataset: "State vehicle registrations, 14 states",
    grain: "ZIP or county",
    vintage: "State-specific",
    role: "Sub-state anchoring, demand model fitting and validation",
    limits: "ZIP is a mail-route collection, not an area; allocation to tracts carries measured error.",
  },
  {
    provider: "Washington State",
    dataset: "Electric vehicle population",
    grain: "Census tract",
    vintage: "State release",
    role: "The only tract-grain registration evidence; used to measure allocation error",
    limits: "Excluded from the headline validation aggregate because it is development evidence.",
  },
  {
    provider: "US Census Bureau",
    dataset: "American Community Survey 5-year (API + bulk)",
    grain: "Census tract",
    vintage: "2018–2023 editions, selected per prediction cutoff",
    role: "Demand features, equity indicators, home-charging covariates",
    limits: "Release date differs from data period; the backtest selects on release date.",
  },
  {
    provider: "US Census Bureau",
    dataset: "TIGER/Line tracts and blocks",
    grain: "Tract, block",
    vintage: "2020 / 2024",
    role: "Geography for allocation and access",
    limits: "Tract boundaries changed between 2010 and 2020 geographies.",
  },
  {
    provider: "US Census Bureau",
    dataset: "TIGER/Line primary & secondary roads",
    grain: "Road feature (S1100, S1200)",
    vintage: "2024",
    role: "Candidate screening by road proximity",
    limits: "Proximity is not buildability, and local streets (S1400) are excluded by design.",
  },
  {
    provider: "US Census Bureau",
    dataset: "Centers of population (tract, block group, block) + PL 94-171",
    grain: "Block and above",
    vintage: "2010 and 2020",
    role: "Population weighting for access and allocation",
    limits: "The 2010 edition is retained solely for vintage-correct backtesting.",
  },
  {
    provider: "HUD / USPS",
    dataset: "ZIP–tract crosswalk",
    grain: "ZIP ↔ tract",
    vintage: "Quarterly release",
    role: "Weighted allocation of ZIP-grain registrations to tracts",
    limits: "An approximation of an approximation; its error is measured, not assumed.",
  },
  {
    provider: "NREL",
    dataset: "County home charging access",
    grain: "County",
    vintage: "Parametric scenario surface",
    role: "Exploratory index only",
    limits: "942,600 rows = 3,142 counties × 3 scenarios × 100 fleet-penetration levels. Not an observation of any date, so excluded from the siting objective.",
  },
  {
    provider: "CEQ (archived)",
    dataset: "CEJST disadvantaged-community classification",
    grain: "Census tract",
    vintage: "Archived; framework revoked 2025-01-20",
    role: "Opt-in historical overlay",
    limits: "Labelled with its vintage everywhere; never described as current policy compliance.",
  },
  {
    provider: "HIFLD",
    dataset: "Electric power transmission lines",
    grain: "Line feature",
    vintage: "Snapshot",
    role: "Optional contextual display layer",
    limits: "138 MB / 94,216 features; never loaded as GeoJSON in a browser (G12). Context, not a constraint.",
  },
  {
    provider: "IEA",
    dataset: "Global EV Outlook",
    grain: "Country",
    vintage: "2024",
    role: "Context and regression fixtures only",
    limits: "Scenario categories must be filtered explicitly or they double count (G5).",
  },
] as const;

const UNUSED = [
  { id: "eGRID (EPA)", why: "Reachable and contracted, but no Core calculation consumes it. Retained as Optional/Future Work rather than given an invented consumer." },
  { id: "FHWA traffic", why: "Entered the design only for a backtest fallback that was never triggered, because ten annual registration vintages exist. No Core consumer." },
  { id: "EIA electricity prices", why: "Optional tier, for a charger-economics model that is not part of Core." },
  { id: "National substation dataset", why: "Five independent searches failed to locate an authoritative national dataset. Per D8 no substitute was adopted, so there is no substation-proximity filter at all." },
] as const;

export default function Methodology() {
  return (
    <div className="methodology">
      <TocNav sections={SECTIONS} />

      <div className="prose method-body">
        <h1>Methodology &amp; Architecture</h1>
        <p className="standfirst">
          VoltGap is a static, zero-recurring-cost decision-support application built from
          public data. This page is the full technical record — the pipeline, the models,
          the three separate validations, the engineering, and every limitation that is
          still open. It is written to be checked, not admired.
        </p>
        <p>
          Looking for the short version? <Link href="/how-it-works/">How it works</Link>{" "}
          explains the product in about a minute.
        </p>

        <div className="note warn">
          <strong>{NOT_OPTIMALITY_NOTE}</strong>
        </div>

        {/* ---------------------------------------------------------------- A */}
        <h2 id="problem">A. Problem definition</h2>
        <p>
          <strong>The planning question.</strong> Given a budget and a set of policy
          priorities, where should the next EV charging infrastructure be built in the
          United States, and how confident should we be in that answer? The second half of
          that sentence carries as much weight as the first.
        </p>
        <p>
          <strong>Intended users.</strong> Infrastructure planners, charge point operators,
          state energy offices, and researchers — people who already understand the domain
          and need a defensible shortlist rather than a verdict.
        </p>
        <p>
          <strong>Decision-support framing.</strong> VoltGap narrows roughly 53,000
          populated areas to a ranked portfolio you can argue about. It does not decide.
          Every output carries the evidence underneath it, and the interface is built so
          that a weak estimate cannot be mistaken for a strong one.
        </p>
        <p>
          <strong>Outputs.</strong> A national demand and access surface; a charging-access
          gap analysis with a live distance threshold; a ranked candidate portfolio for a
          chosen state, budget and priority; a published ε-constraint tradeoff frontier;
          and CSV / GeoJSON export.
        </p>
        <p>
          <strong>Explicitly out of scope.</strong> A general EV statistics browser, a
          consumer charger finder, a vehicle comparison tool, real-time charger
          availability, and any claim about grid interconnection feasibility.
        </p>

        {/* ---------------------------------------------------------------- B */}
        <h2 id="architecture">B. System architecture</h2>
        <p>
          Everything analytical happens offline, in Python. The browser receives finished
          artifacts and re-derives nothing. That single decision explains most of the rest
          of the architecture.
        </p>

        <ol className="pipeline-diagram" aria-label="VoltGap processing pipeline">
          {PIPELINE.map((step, i) => (
            <li key={step.stage}>
              <div className="pd-box">
                <span className="pd-n">{i + 1}</span>
                <div>
                  <strong>{step.stage}</strong>
                  <span className="pd-detail">{step.detail}</span>
                </div>
              </div>
            </li>
          ))}
        </ol>

        <h3>Why offline computation plus static serving</h3>
        <ul>
          <li>
            <strong>Cost.</strong> A hard project constraint is zero recurring cost. No
            paid API, no managed database, no keyed tile provider, no serverless function.
            A static export satisfies that by construction rather than by discipline.
          </li>
          <li>
            <strong>Reproducibility.</strong> An analytical result computed once, checksummed
            and published is auditable. The same result recomputed per request, from a
            drifting source, is not.
          </li>
          <li>
            <strong>Honesty about provenance.</strong> Because the browser cannot recompute
            the models, it also cannot quietly diverge from them. The figures on screen are
            the figures the gate verified.
          </li>
          <li>
            <strong>Failure behaviour.</strong> If a refresh breaks, the previous artifacts
            stay live and the interface reports their age. A stale-but-correct site beats a
            fresh-but-broken one.
          </li>
        </ul>
        <p>
          The cost is that interactivity must be re-implemented in the browser where it is
          genuinely needed — which is exactly one place, the portfolio solver (§O).
        </p>

        {/* ---------------------------------------------------------------- C */}
        <h2 id="sources">C. Data sources</h2>
        <p>
          The source contract holds <strong>62 entries</strong> spanning{" "}
          <strong>12+ federal, state and open dataset families</strong>. Ten of those
          entries are annual registration vintages of one AFDC series, and fourteen are
          per-state registration releases, which is why the entry count and the family
          count differ so much.
        </p>

        <div className="table-scroll">
          <table className="src">
            <thead>
              <tr>
                <th>Provider</th><th>Dataset</th><th>Grain</th>
                <th>Vintage</th><th>Role in VoltGap</th><th>Important limitations</th>
              </tr>
            </thead>
            <tbody>
              {SOURCES.map((s) => (
                <tr key={s.dataset}>
                  <td>{s.provider}</td>
                  <td>{s.dataset}</td>
                  <td>{s.grain}</td>
                  <td>{s.vintage}</td>
                  <td>{s.role}</td>
                  <td className="lim">{s.limits}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h3>Present in the repository, not consumed by Core</h3>
        <p>
          These are labelled rather than quietly listed among the working sources. A source
          is not retained because it appeared in an early architecture sketch.
        </p>
        <ul>
          {UNUSED.map((u) => (
            <li key={u.id}><strong>{u.id}.</strong> {u.why}</li>
          ))}
        </ul>

        {/* ---------------------------------------------------------------- D */}
        <h2 id="acquisition">D. Data acquisition and provenance</h2>
        <p>
          Each source has one adapter behind a common interface handling retrieval, retry,
          caching and vintage stamping. Adapters may decode, decompress, stream and reshape
          — mechanical, lossless work — but they may not drop or filter rows. Business
          filtering happens later, in SQL, where it is visible and testable.
        </p>
        <ul>
          <li><strong>Schema discovery.</strong> A probe fetches a bounded sample, dumps the live schema verbatim, counts rows, computes per-field missingness and measures the rate limit empirically. Expectations are never taken from documentation alone.</li>
          <li><strong>Contract vs observation.</strong> The reviewed contract and the generated observations live in separate files, so a live refresh cannot quietly rewrite what was expected.</li>
          <li><strong>Provenance.</strong> Every retrieved payload records SHA-256, byte size, retrieval time and resolved vintage. Every derived table carries <code>computed_at</code> and a map of the source vintages that produced it.</li>
          <li><strong>Raw preservation.</strong> Raw responses are cached immutably; replay fixtures make the whole pipeline runnable without network access.</li>
          <li><strong>Authentication.</strong> Four API keys live only in a git-ignored environment file, are never logged, and never appear in an artifact.</li>
        </ul>

        <h3>Case study: an HTTP 200 that was not data</h3>
        <p>
          The Census API answers an unauthenticated request with{" "}
          <strong>HTTP 200 and an HTML &ldquo;Missing Key&rdquo; page</strong> — not a 4xx,
          not a JSON error. A status-code check passes. A naive cache then stores that HTML
          under the key of a legitimate ACS request, and every later run reads poisoned data
          from a cache that looks healthy.
        </p>
        <p>
          The fix is that adapters validate <em>content</em>, not status: the response must
          parse as the expected shape before it is admitted to the cache. This is why the
          rule is content validation rather than status checking, and it is the clearest
          example in the project of why &ldquo;the request succeeded&rdquo; is not the same
          claim as &ldquo;the data arrived&rdquo;.
        </p>

        {/* ---------------------------------------------------------------- E */}
        <h2 id="canonical">E. Cleaning and canonicalization</h2>
        <p>
          Raw source fields become canonical tables through DuckDB SQL in three layers —
          staging (typing and renaming only), intermediate (joins, allocation, entity
          resolution), marts (published tables). Every model has a matching Pandera schema
          checked after execution, and a schema violation fails the build and blocks
          publication.
        </p>
        <ul>
          <li><strong>Geographic identifiers.</strong> Joins are on FIPS, never on name — both Minnesota and Illinois have a Cook County (G13).</li>
          <li><strong>Connector taxonomy.</strong> Eight raw values normalise through an explicit table, and <em>both</em> raw and normalised values are preserved, because Tesla / NACS / J3400 naming has changed over time.</li>
          <li><strong>Charging level from the source.</strong> L1 / L2 / DCFC comes from the record&rsquo;s own field, never inferred from a connector name. NEMA 5-15, 5-20 and 14-50 are connector standards, not level designations.</li>
          <li><strong>Public operational filtering.</strong> Supply counts only status <code>E</code> (available) and access <code>public</code>. In the reference snapshot that is 73,972 of 79,618 stations, with 4,662 private records excluded.</li>
        </ul>

        <h3>Why exact coordinate duplicates are not deleted</h3>
        <p>
          The reference snapshot contains 1,756 exact coordinate duplicate pairs. The
          tempting cleanup — drop them as data errors — would be wrong. They are typically{" "}
          <strong>co-located infrastructure from different networks</strong>: two real
          operators at one real location. So they are <em>aggregated</em> into one site for
          coverage and their ports <em>summed</em> for capacity, and never removed. Deleting
          them would silently erase real charging capacity from the supply model.
        </p>
        <p>
          The same logic governs the entity hierarchy. The charging-unit export carries no
          unit identifier, and 65.9% of its rows are byte-identical to another row — yet row
          counts reconcile to each station&rsquo;s reported totals for 99.975% of stations
          (89,665 of 89,687). The duplicates are therefore real distinct physical units that
          are indistinguishable in every reported attribute. Physical identity is not
          manufactured to paper over that: the hierarchy stops at{" "}
          <code>charging_unit</code>, keys are labelled synthetic and per-snapshot, and no
          longitudinal unit identity is claimed anywhere.
        </p>

        {/* ---------------------------------------------------------------- F */}
        <h2 id="missing">F. Missing data and imperfect source semantics</h2>
        <p>
          There is no generic imputation step. Each gap is handled by a rule that records
          what was done, and every value carries its own provenance so a reader can tell
          the difference between a measurement and an inference.
        </p>

        <div className="table-scroll">
          <table>
            <thead>
              <tr><th>Status</th><th>Meaning</th><th>Example</th></tr>
            </thead>
            <tbody>
              <tr><td><strong>Observed / reported</strong></td><td>The source states this value for this object</td><td>Connector power reported by AFDC</td></tr>
              <tr><td><strong>Empirically derived</strong></td><td>Computed from other reported records of the same kind</td><td>Median power for a (network, connector) pair</td></tr>
              <tr><td><strong>Modeled</strong></td><td>Produced by a fitted model</td><td>Tract EV counts from demographics</td></tr>
              <tr><td><strong>Reconstructed</strong></td><td>Assembled retrospectively from a current snapshot</td><td>The historical charging network at a past date</td></tr>
              <tr><td><strong>Unavailable</strong></td><td>Excluded rather than substituted</td><td>Home charging access in the backtest</td></tr>
            </tbody>
          </table>
        </div>

        <h3>The power resolution ladder</h3>
        <p>
          Every port carries <code>power_kw</code>, <code>power_source</code> and{" "}
          <code>power_confidence</code>, resolved in order:
        </p>
        <ol>
          <li><strong>Reported</strong> — the source states the power. High confidence.</li>
          <li><strong>Empirical fallback</strong> — the median for the same (network, connector type) pair, computed only from rung 1 records, and only where the sample meets a documented minimum. Medium confidence.</li>
          <li><strong>Type default</strong> — a documented value from configuration, each with a cited justification. Low confidence.</li>
        </ol>
        <p>
          No power value is hard-coded in Python, and the share of capacity resting on
          rung 1 is published rather than averaged away.
        </p>

        <h3>Exclusion in preference to approximation</h3>
        <p>
          Where a historically appropriate value cannot be reconstructed, the feature is{" "}
          <strong>dropped from the backtest entirely</strong> rather than approximated with
          a modern value. Home charging access is the clearest case: one undated scenario
          surface exists, so it cannot be given a 2020 value, and it is excluded from every
          retrospective fit even though it is available to the live model. Every such
          exclusion is enumerated rather than left implicit, and where a source is degraded
          the degradation is flagged in the data and surfaced in the interface.
        </p>

        {/* ---------------------------------------------------------------- G */}
        <h2 id="supply">G. Charging supply model</h2>
        <p>
          A station record is one network&rsquo;s presence at a location. A record with one
          Level 2 plug and a record with forty DC fast stalls are both a single row, so row
          counts are never treated as capacity. Sites are formed by spatial clustering of
          station coordinates (DBSCAN, ~50 m) rather than by rounding coordinates, which
          would split locations arbitrarily at grid boundaries.
        </p>

        <h3>Case study: connectors that are not independent capacity</h3>
        <p>
          <strong>16,610 charging units expose more than one connector standard on a single
          service port</strong> — CHAdeMO + CCS (7,071), CCS + NACS (5,168), J1772 + NACS
          (3,283). These are alternative interfaces to the same physical stall, not separate
          stalls.
        </p>
        <p>
          A unit offering CCS at 200 kW and CHAdeMO at 100 kW contributes{" "}
          <strong>200 kW</strong> of simultaneous capacity, not 300 kW. Summing connector
          power as though every connector were an independently usable port would have
          overstated national public charging capacity by{" "}
          <strong>2,104,242 kW — 2.1 GW, or 10.69%</strong>.
        </p>
        <p>
          Two quantities are therefore modelled separately and may never substitute for one
          another: <strong>generic service capacity</strong> (how many vehicles can be
          served simultaneously, and at what non-overlapping power) and{" "}
          <strong>connector-compatible capacity</strong> (what is available to a vehicle
          using a given standard, which may overlap physically). Outputs per cell include
          L1 / L2 / DCFC port counts, capacity, site count, and the share of capacity
          resting on reported rather than inferred power.
        </p>

        {/* ---------------------------------------------------------------- H */}
        <h2 id="access">H. Charging-access model</h2>
        <p>
          Access is measured from <strong>population-weighted centroids</strong>, not
          geometric ones. In a large rural tract the population often occupies one corner,
          and a geometric centroid would place people in empty land — sometimes tens of
          kilometres from where they live.
        </p>
        <p>
          Distance is straight-line great-circle to the nearest operational public DC fast
          charging site, computed with a spatial index. Straight-line distance understates
          real travel distance, so <strong>a reported gap is a lower bound on the true
          gap</strong>. Drive-time isochrones would be more accurate and are out of scope
          for this release.
        </p>
        <p>
          <strong>No single threshold is presented as correct.</strong> The distance
          threshold is a live control, and the interface ships a sensitivity curve showing
          how the affected population changes across the whole range — because the choice
          of threshold is a policy judgement, not a measurement.
        </p>
        <p>
          <strong>Why the stronger word is avoided.</strong> A term implying that an area
          has no charging at all would overstate this measure. It covers DC fast charging
          only, and an area counted as a gap may well have Level 2 charging available.
          Calling it a <strong>DCFC access gap</strong> names what was actually measured,
          and nothing more.
        </p>

        {/* ---------------------------------------------------------------- I */}
        <h2 id="demand">I. Demand model</h2>
        <p>
          <strong>Objective.</strong> Estimate EV counts per census tract, then allocate to
          H3 cells, from demographics and geography alone.
        </p>
        <p>
          <strong>Feature families.</strong> Household income and its distribution, housing
          tenure, units in structure, vehicles available per household, population density,
          commute distance and mode, urban/rural classification, and educational attainment.
        </p>

        <div className="note warn">
          <strong>Existing charging supply is excluded from the demand model, and a test
          enforces it.</strong> Charger counts, port counts, network presence and
          distance-to-charger are unavailable to the primary feature set. Existing
          infrastructure is an <em>outcome</em> of past investment decisions; using it to
          predict demand and then using that demand to site new infrastructure would launder
          historical deployment patterns into &ldquo;need&rdquo;, systematically suppressing
          the underserved areas the system exists to find. Supply features do improve fit.
          That is precisely the problem.
        </div>

        <p>
          <strong>Estimator.</strong> A Poisson GLM with a log link
          (<code>sklearn.linear_model.PoissonRegressor</code>), exposure carried as the
          sample weight — equivalent to a Poisson regression with{" "}
          <code>log(exposure)</code> as an offset, which is the natural form for count data
          over populations of very different sizes.
        </p>
        <p>
          <strong>Reconciliation.</strong> Tract estimates are constrained to reproduce
          reliable county totals where they exist and state totals everywhere else. Both the
          unreconciled and reconciled estimates are evaluated, so the contribution of the
          constraint is visible rather than assumed.
        </p>

        <h3>Validation result — demand model validation</h3>
        <p>
          Leave-one-state-out across <strong>14 independent states</strong> with sub-state
          registration evidence, scored at each held-out state&rsquo;s native granularity:
        </p>
        <div className="table-scroll">
          <table>
            <thead><tr><th>Estimate</th><th className="num">Weighted WAPE</th></tr></thead>
            <tbody>
              <tr><td>Unreconciled</td><td className="num"><code>0.3809</code></td></tr>
              <tr><td>Reconciled</td><td className="num"><code>0.3203</code></td></tr>
            </tbody>
          </table>
        </div>
        <p>
          <strong>Washington&rsquo;s role, stated precisely.</strong> It is the only state
          publishing registrations at census-tract grain, which makes it the natural holdout
          for measuring the ZIP→tract allocation error the model depends on. Because it was
          used for that measurement, it is <strong>excluded from the headline aggregate</strong>
          — scoring the model on Washington would be scoring it on its own development
          evidence.
        </p>

        {/* ---------------------------------------------------------------- J */}
        <h2 id="uncertainty">J. Uncertainty and confidence</h2>
        <p>
          Every modeled area carries a continuous uncertainty score built from five
          components: prediction interval width; an out-of-distribution score measuring how
          unlike the training distribution the area is; constraint slack, or how far
          reconciliation moved the raw estimate; a penalty for degraded sources; and a
          geographic transformation penalty reflecting how far the value sits from the
          nearest real registration observation.
        </p>
        <p>
          The continuous score is primary. The A / B / C tier shown in the interface is a{" "}
          <strong>presentation layer</strong> over it, defined by documented thresholds, and
          is never geography-based.
        </p>

        <h3>Local anchoring is not direct observation</h3>
        <p>
          This distinction is the one most easily lost, so the data model keeps two
          independent fields rather than collapsing them into one label.{" "}
          <strong>Evidence grain</strong> records the finest actual observed registration
          evidence, as one of <code>native_tract</code>, <code>zip_anchored</code>,{" "}
          <code>county_anchored</code> or <code>state_total_only</code>.{" "}
          <strong>Estimate method</strong> records what was done to produce the value, as
          one of <code>directly_observed</code>, <code>crosswalked</code>,{" "}
          <code>modeled</code> or <code>modeled_high_uncertainty</code>. Naming the schema
          literals rather than paraphrasing them matters here: in this project only
          Washington&rsquo;s tract-grain registrations ever carry the first value of
          either field.
        </p>
        <p>
          A tract built from ZIP-grain observations is <em>anchored</em> to real sub-state
          data, but the tract value itself was never observed. So{" "}
          <strong>the highest tier is labelled &ldquo;sub-state anchored&rdquo;, never
          &ldquo;observed&rdquo;</strong>, and a copy lint fails the build if that word
          appears against it. In human terms the interface says &ldquo;based on local
          registration data&rdquo; first and gives the technical vocabulary second.
        </p>

        {/* ---------------------------------------------------------------- K */}
        <h2 id="leakage">K. Temporal leakage protection</h2>
        <p>
          Retrospective validation is worthless if the model can see the future. The rule is
          enforced at runtime, not documented as a convention:
        </p>
        <pre className="rule"><code>assert feature_release_date &lt;= prediction_cutoff</code></pre>
        <p>
          The harness calls this before every backtest fit and raises rather than proceeding.
          A deliberately poisoned feature set is a committed negative test: if the guard ever
          stops raising, the suite fails.
        </p>
        <ul>
          <li>
            <strong>Release date, not data period.</strong> The distinction matters more than
            it sounds. The 2016–2020 ACS 5-year estimates describe a period ending in 2020
            but were <em>released on 2022-03-17</em>. For a 2022-01-01 origin the data period
            looks safe and the edition is still inadmissible, because nobody could have held
            it at the cutoff. Selection is on release date throughout.
          </li>
          <li><strong>Three rolling origins</strong> — 2020, 2021 and 2022 — each predicting the following 24 months.</li>
          <li><strong>ACS vintage handling.</strong> Each origin resolves to the contemporaneous edition; where a release date cannot be established, resolution falls back to the older vintage.</li>
          <li><strong>Road geometry is excluded.</strong> The 2024 TIGER road network did not exist at any origin, so it takes no part in the backtest even though it screens candidates in the live model.</li>
          <li><strong>Unreconstructable features are excluded, not approximated</strong>, and each exclusion is enumerated in the validation documentation.</li>
        </ul>

        {/* ---------------------------------------------------------------- L */}
        <h2 id="h3">L. H3 and spatial representation</h2>
        <p>
          The country is divided into consistent hexagonal geographic cells, so datasets
          drawn on completely different boundaries — census tracts, ZIP codes, counties,
          point locations — can be compared and modelled on one spatial framework.
        </p>

        <svg className="h3-figure" viewBox="0 0 460 150" role="img"
             aria-label="Irregular administrative boundaries on the left, a uniform hexagonal grid on the right">
          <g fill="none" strokeWidth="1.5">
            <path d="M14 20 L70 12 L104 44 L86 96 L30 108 L8 62 Z" stroke="var(--ink-faint)" />
            <path d="M104 44 L150 30 L168 78 L120 118 L86 96 Z" stroke="var(--ink-faint)" />
            <path d="M70 12 L140 18 L150 30 L104 44 Z" stroke="var(--ink-faint)" />
            <path d="M30 108 L86 96 L120 118 L96 140 L44 134 Z" stroke="var(--ink-faint)" />
          </g>
          <text x="88" y="12" textAnchor="middle" className="h3-label">tracts, ZIPs, counties</text>
          <path d="M196 75 L244 75 M236 68 L244 75 L236 82" stroke="var(--ink-faint)"
                strokeWidth="1.5" fill="none" />
          <g fill="none" stroke="var(--accent)" strokeWidth="1.5" opacity="0.85">
            {[0, 1, 2].map((row) =>
              [0, 1, 2, 3].map((col) => {
                const w = 34, h = 30;
                const cx = 288 + col * w * 0.75;
                const cy = 40 + row * h + (col % 2) * (h / 2);
                const pts = Array.from({ length: 6 }, (_, k) => {
                  const a = (Math.PI / 180) * (60 * k);
                  return `${(cx + (w / 2) * Math.cos(a)).toFixed(1)},${(cy + (h / 2) * Math.sin(a)).toFixed(1)}`;
                }).join(" ");
                return <polygon key={`${row}-${col}`} points={pts} />;
              }),
            )}
          </g>
          <text x="352" y="12" textAnchor="middle" className="h3-label">one H3 grid</text>
        </svg>

        <ul>
          <li>
            <strong>Why hexagons.</strong> Every neighbour shares an edge and sits at the
            same distance from the centre. On a square grid, diagonal neighbours are 41%
            further away than orthogonal ones, which distorts any distance or adjacency
            reasoning built on top.
          </li>
          <li>
            <strong>Resolution 6 nationally</strong> — <strong>53,208 populated cells</strong>,
            averaging roughly 36 km². Resolution 8 is reserved for metro drill-down.
          </li>
          <li>
            <strong>Stable through boundary changes.</strong> H3 cells do not move when the
            Census redraws tracts. This is what makes the 2010→2020 tract-geography break
            immaterial to the backtest ranking metrics, since every one of them is a
            cell-ranking metric.
          </li>
          <li>
            <strong>Mapping different grains onto the grid.</strong> Tract quantities are
            allocated using <strong>block-level population weights</strong>, never area
            weights — area weighting assumes population is spread uniformly inside a tract,
            which is badly wrong in large rural ones.
          </li>
          <li>
            <strong>Display generalization.</strong> At national zoom the map draws coarser
            parent cells for legibility. This is presentation only: the analytical surface
            stays at resolution 6, and a test proves the roll-up conserves every additive
            quantity exactly.
          </li>
        </ul>

        {/* ---------------------------------------------------------------- M */}
        <h2 id="screening">M. Road and candidate screening</h2>
        <p>A cell is a candidate unless it fails one of three screens:</p>
        <ul>
          <li><strong>Uninhabited</strong> — no census population inside the cell.</li>
          <li><strong>Beyond the primary/secondary road network</strong> — more than 5.0 km from a TIGER/Line 2024 <code>S1100</code> or <code>S1200</code> road. Local streets (<code>S1400</code>) are excluded by design.</li>
          <li><strong>Already saturated</strong> — existing fast-charging ports already ample for the cell&rsquo;s estimated demand.</li>
        </ul>
        <p>
          <strong>There is no substation-proximity filter.</strong> Five independent searches
          failed to locate an authoritative national substation dataset — the best candidate
          held 128 features against a national figure on the order of 55,000–80,000. Rather
          than substitute transmission-line distance and treat it as equivalent, the filter
          simply does not exist, and Core siting functions without it. {GRID_PROXIMITY_NOTE}
        </p>

        <h3>Case study: a distance that was measured to the wrong thing</h3>
        <p>
          The original implementation measured each cell centroid to the nearest road{" "}
          <strong>vertex</strong>, to avoid adding a geometry dependency. That is wrong in a
          specific and dangerous way: a long straight segment can pass close to a cell while
          both of its endpoints are far away.
        </p>
        <p>The synthetic regression fixture built to expose it:</p>
        <div className="table-scroll">
          <table>
            <thead><tr><th>Quantity</th><th className="num">Value</th></tr></thead>
            <tbody>
              <tr><td>A two-vertex road, length</td><td className="num">~76 km</td></tr>
              <tr><td>Cell centroid to the middle of that road</td><td className="num"><strong>2.22 km</strong></td></tr>
              <tr><td>Distance by nearest vertex</td><td className="num">37.98 km</td></tr>
              <tr><td>Overestimate</td><td className="num"><strong>17×</strong></td></tr>
              <tr><td>Vertex method at the 5.0 km filter</td><td className="num">cell <strong>excluded</strong></td></tr>
              <tr><td>Corrected method at the 5.0 km filter</td><td className="num">cell <strong>admitted</strong></td></tr>
            </tbody>
          </table>
        </div>
        <p>
          The replacement measures distance to the nearest <em>point on</em> the nearest
          segment, with three properties that are individually tested: the reported number is
          a real great-circle distance to a real place on a real road; it can never exceed
          the vertex distance, since a vertex is itself a point on the segment; and segments
          are formed only within a single road feature, so the end of one road is never
          joined to the start of another.
        </p>
        <p>
          <strong>Independent validation across the six frontier states.</strong> Mean error
          0.7–4.5 m, worst single cell 666.9 m, and — the number that matters —{" "}
          <strong>zero cells changed side of the 5.0 km threshold in any state</strong>.
          Candidate counts are identical and every Jaccard index is exactly{" "}
          <code>1.000000</code>. Portfolio overlap is 1.000 at 5, 20 and 50 sites, with
          demand and equity deltas of exactly 0.00.
        </p>
        <div className="note">
          <strong>The defect was real, the fix was necessary, and it moved nothing.</strong>{" "}
          The practical error sits far below the worst case because the longest segments
          happen not to lie near candidate cells in this snapshot. That is a property of this
          data, not a guarantee — which is exactly why the method was corrected rather than
          the outcome accepted. On sparser geometry, or at a tighter threshold, the same
          defect would change results.
        </div>

        {/* ---------------------------------------------------------------- N */}
        <h2 id="optimization">N. Portfolio optimization</h2>
        <p>
          The published analytical frontier is a mixed-integer program, solved offline with{" "}
          <strong>PuLP</strong> and the <strong>CBC</strong> solver, maximising covered
          demand subject to a budget and a minimum equity coverage:
        </p>
        <pre className="rule"><code>{`maximize   Σ demand_i · y_i
subject to Σ cost_j · x_j ≤ B
           Σ equity_pop_i · y_i ≥ ε        ← the ε-constraint
           y_i ≤ Σ_{j ∈ N(i)} x_j
           x_j, y_i ∈ {0,1}`}</code></pre>
        <p>
          Budget is expressed as a <strong>number of sites</strong>, because no defensible
          national cost model exists. That makes the problem cardinality-constrained rather
          than truly budgeted, and it is described that way rather than implying a dollar
          figure the data cannot support.
        </p>
        <p>
          ε sweeps a documented range, and the objectives are then{" "}
          <strong>reversed</strong> — maximise equity coverage subject to a minimum demand
          coverage — as a check. The frontier is computed <strong>per state</strong>: sixteen
          national integer programs would not fit a free CI runner, so the scope is stated
          rather than the compute quietly reduced.
        </p>
        <p>
          <strong>Why weighted-sum scalarization is not enough.</strong> Sweeping objective
          weights cannot recover unsupported Pareto-efficient points on an integer program —
          entire regions of the true frontier are invisible to it, no matter how finely the
          weights are swept. The published frontier therefore comes from ε-constraint
          solutions, and sweeping weights and calling the result a Pareto frontier is
          explicitly treated as a mistake to avoid.
        </p>
        <p>
          <strong>Result: 96 of 96 frontier solves reached <code>optimal</code> solver
          status</strong>, every reported gap <code>0.0</code>.
        </p>
        <div className="note warn">
          <strong>What &ldquo;optimal&rdquo; means here, precisely.</strong> The solver
          proved the optimum <em>of the declared mathematical formulation</em> — of that
          objective, over that candidate set, under those constraints. It says nothing about
          whether those are the right sites in the world. There is no ground truth for
          real-world siting, so no result on this page can establish it.
        </div>

        {/* ---------------------------------------------------------------- O */}
        <h2 id="browser-solver">O. Browser interactive solver</h2>
        <p>
          Exact CBC solving stays offline: it needs a solver binary, and interactive
          latency is incompatible with proving optimality on an integer program. The Studio
          instead runs a <strong>greedy marginal-gain solver in TypeScript, inside a Web
          Worker</strong>, so dragging a budget slider never blocks the interface.
        </p>
        <p>
          Performance is asserted against a <strong>real Texas fixture</strong> rather than a
          synthetic one, with a budget of <strong>≤ 2 seconds</strong> per re-solve. The
          slowest observed solve in the release gate was <strong>0.0288 s</strong>.
        </p>
        <p>{INTERACTIVE_SOLVER_NOTE}</p>
        <div className="note warn">
          <strong>No approximation bound is claimed, anywhere.</strong> The familiar
          textbook guarantee for greedy submodular maximisation holds under a{" "}
          <em>cardinality</em> constraint. The Studio exposes objective weights and
          constraint toggles, making this weighted multi-objective selection under additional
          constraints — a different problem class, where that theorem&rsquo;s assumptions do
          not hold. Measured shortfalls against exact offline solves are published instead:
          the worst observed was <strong>3.14%</strong> (Montana at 20 sites) across eighteen
          problems. That is an observation, not a bound.
        </div>

        {/* ---------------------------------------------------------------- P */}
        <h2 id="alignment">P. Historical deployment alignment</h2>
        <div className="note warn"><strong>{DEPLOYMENT_ALIGNMENT_NOTE}</strong></div>
        <p>
          Three rolling origins, each predicting the following 24 months, with the vintage
          guard of §K active throughout.
        </p>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Origin</th><th className="num">Deployments</th>
                <th className="num">Model top decile</th><th className="num">Population</th>
                <th className="num">vs random</th><th className="num">vs population</th>
              </tr>
            </thead>
            <tbody>
              <tr><td>2020</td><td className="num">18,189</td><td className="num">0.6452</td><td className="num">0.7766</td><td className="num">6.72×</td><td className="num">0.83×</td></tr>
              <tr><td>2021</td><td className="num">22,168</td><td className="num">0.6216</td><td className="num">0.7554</td><td className="num">6.39×</td><td className="num">0.82×</td></tr>
              <tr><td>2022</td><td className="num">20,533</td><td className="num">0.5713</td><td className="num">0.7063</td><td className="num">5.89×</td><td className="num">0.81×</td></tr>
            </tbody>
          </table>
        </div>
        <div className="note warn">
          <strong>This is a negative result and it is reported as one.</strong> The model
          strongly outperforms random and an existing-network baseline, but it does{" "}
          <strong>not</strong> outperform a simple population baseline at any origin. For
          reproducing where the industry actually built next,{" "}
          <strong>population is the better predictor</strong>. That is a negative
          historical-deployment-alignment result. It is not evidence of siting failure — the
          industry&rsquo;s own choices are not ground truth — and it is not itself evidence
          for or against excluding supply features from the demand model.
        </div>

        <h3>Case study: a baseline that was misleading by variance</h3>
        <p>
          The random baseline was originally estimated from <strong>one</strong> seeded
          permutation. It is unbiased, but deployment counts are heavily concentrated, so a
          single shuffle either lands on the busy cells or does not.
        </p>
        <p>
          Over 400 draws at the 2020 origin, top-decile capture has mean{" "}
          <code>0.0976</code> and standard deviation <code>0.0137</code>. The shipped
          single-seed draw was <code>0.0687</code> — at <strong>percentile 0</strong>, below
          the 5th percentile of <code>0.0759</code>. It had overstated lift as{" "}
          <strong>9.40×</strong>. The baseline is now the mean over 200 draws with its spread
          published, and the corrected figures are the 6.72 / 6.39 / 5.89 above. The lift
          against population was unchanged, because that baseline was never noisy.
        </p>

        <h3>Reconstruction limits</h3>
        <p>
          The historical network is an <strong>approximate reconstruction</strong>: a current
          snapshot plus open dates cannot recover stations that closed, left the feed, or
          changed port counts. It is survivorship-biased and the bias grows with age.
        </p>
        <p>
          Capacity carries a further caveat. Power comes from the current snapshot attributed
          to each station&rsquo;s open date, so a surviving upgraded station carries its
          present power while closed stations are absent entirely.{" "}
          <strong>The biases compete and the net direction is unknown</strong>, so no
          direction is claimed for the reconstructed totals or for any capture fraction
          computed from them. An earlier draft did claim a direction; that claim was
          withdrawn.
        </p>

        {/* ---------------------------------------------------------------- Q */}
        <h2 id="robustness">Q. Cross-objective robustness</h2>
        <p>
          Portfolios optimized on one objective, then scored on objectives that were never in
          that loss function — six evaluation outcomes (population served, demand covered,
          equity coverage, accessibility improvement, estimated utilization, cost efficiency)
          against four baselines (population-weighted, demand-only, existing-network
          proximity, and random).
        </p>
        <div className="table-scroll">
          <table>
            <thead><tr><th>Portfolio</th><th>Scored on</th><th className="num">Share of best achievable</th></tr></thead>
            <tbody>
              <tr><td>Demand-first</td><td>Equity coverage</td><td className="num"><strong>79.6%</strong></td></tr>
              <tr><td>Equity-first</td><td>Demand coverage</td><td className="num"><strong>81.9%</strong></td></tr>
            </tbody>
          </table>
        </div>
        <p>
          <strong>This is a tradeoff, not a win.</strong> Reporting that the optimizer
          performs well on its own objective would be circular. Each portfolio gives up
          roughly a fifth of the other objective&rsquo;s best achievable value, which means
          the choice of priority genuinely changes the answer — and that is why the interface
          exposes the priority as a control rather than choosing one on the user&rsquo;s
          behalf.
        </p>

        <h3>The three validations are never interchangeable</h3>
        <div className="table-scroll">
          <table>
            <thead><tr><th>Term</th><th>What it evaluates</th><th>Method</th></tr></thead>
            <tbody>
              {Object.values(VALIDATION_TERMS).map((term) => (
                <tr key={term.name}>
                  <td><strong>{term.name}</strong></td>
                  <td>{term.evaluates}</td>
                  <td>{term.method}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p>
          These evaluate different things by different methods. Conflating them would let a
          result about one be read as a result about another — the reason a lint checks the
          vocabulary across code, documentation and interface copy alike.
        </p>

        {/* ---------------------------------------------------------------- R */}
        <h2 id="frontend">R. Frontend architecture</h2>
        <p>
          <strong>Next.js</strong> (App Router) with <strong>React</strong> and{" "}
          <strong>TypeScript in strict mode</strong>, built with{" "}
          <code>output: &quot;export&quot;</code> so the whole application is static files.
          Any accidental use of a server-only feature fails the build rather than quietly
          requiring a runtime. Maps are <strong>MapLibre GL JS</strong> for the basemap with{" "}
          <strong>deck.gl</strong> layers interleaved into the same WebGL context.
        </p>
        <p>
          <strong>Artifacts in, no analytics re-implemented.</strong> The browser reads
          published Parquet and JSON and never recomputes a model. The one genuine exception
          is the greedy portfolio solver of §O, which exists because interactive re-solving
          is the point of the Studio — and its results are checked against the offline solver
          rather than trusted.
        </p>
        <p>
          Interleaving matters for more than looks: the analytical fill is inserted{" "}
          <em>beneath</em> the basemap&rsquo;s road and label layers, so city names and state
          borders stay readable through the surface. A map that renders every polygon
          correctly and hides the geography underneath has still failed as a map.
        </p>

        {/* ---------------------------------------------------------------- S */}
        <h2 id="performance">S. Browser performance engineering</h2>
        <p>
          The first working national view took <strong>4.94 s</strong> to interactive
          against a <strong>3.0 s</strong> budget. Two things dominated: decoding a
          multi-megabyte Parquet file on the main thread, and allocating one JavaScript
          object per cell for 53,208 cells.
        </p>
        <div className="table-scroll">
          <table>
            <thead><tr><th>Change</th><th>Effect</th></tr></thead>
            <tbody>
              <tr><td>Parquet decoding moved to a Web Worker</td><td>Main thread free during load</td></tr>
              <tr><td>Columnar typed arrays instead of row objects</td><td>No 53K-object allocation</td></tr>
              <tr><td>Transferable buffers across the worker boundary</td><td>Zero-copy handoff</td></tr>
              <tr><td>H3 boundary generation in a second worker</td><td>Geometry off the critical path</td></tr>
              <tr><td>Binary <code>SolidPolygonLayer</code> with per-vertex colours</td><td>No per-feature iteration in deck.gl</td></tr>
              <tr><td>Dependency reduction</td><td>Parquet reader moved into a worker chunk</td></tr>
            </tbody>
          </table>
        </div>
        <div className="table-scroll">
          <table>
            <thead><tr><th>Measure</th><th className="num">Before</th><th className="num">After optimization</th><th className="num">This release</th></tr></thead>
            <tbody>
              <tr><td>App shell, gzipped</td><td className="num">307.4 KB</td><td className="num">218.9 KB</td><td className="num"><strong>229.6 KB</strong></td></tr>
              <tr><td>Time to interactive</td><td className="num">4.94 s</td><td className="num">2.84 s</td><td className="num"><strong>2.94 s</strong></td></tr>
              <tr><td>National map, sustained</td><td className="num">—</td><td className="num">58.0 fps</td><td className="num"><strong>60.0 fps</strong></td></tr>
              <tr><td>Cells in the analytical surface</td><td className="num" colSpan={3}>53,208</td></tr>
            </tbody>
          </table>
        </div>
        <p>
          The shell grew from 218.9 KB to 229.6 KB as the exploration features landed. That
          is reported rather than quietly compared against the older figure; it remains 38.3%
          of the 600 KB budget.
        </p>

        <h3>Benchmark validity</h3>
        <p>
          A performance number from a machine that could not have produced it is worse than
          no number, so the harnesses refuse rather than report. The frame-rate harness
          rejects software rendering, an absent WebGL context, or fewer than 50,000 rendered
          cells, and it first drives the identical camera path with the analytical layer{" "}
          <em>off</em> — a strictly cheaper scene — reporting{" "}
          <strong>not measured</strong> if even that cannot hold the budget. The
          time-to-interactive harness requires a minimum cell count, so it cannot pass on an
          error page, and enforces a floor on the machine&rsquo;s own benchmark index.
        </p>
        <p>
          Both guards have caught real problems: a run that &ldquo;passed&rdquo; in 0.96 s
          against a page with no data, and a genuine frame-rate regression that a contended
          machine was briefly blamed for. A validity guard can only ever turn a failure into{" "}
          <em>not measured</em> — never a failure into a pass.
        </p>

        {/* ---------------------------------------------------------------- T */}
        <h2 id="testing">T. Testing and quality engineering</h2>
        <div className="table-scroll">
          <table>
            <thead><tr><th>Layer</th><th>What it does</th></tr></thead>
            <tbody>
              <tr><td><strong>pytest + coverage</strong></td><td>100% line <em>and</em> branch coverage on every result-computing package; ≥70% repository-wide</td></tr>
              <tr><td><strong>Ruff, mypy --strict</strong></td><td>Lint and full static typing across 148 source files</td></tr>
              <tr><td><strong>Regression suites</strong></td><td>One test per documented source domain rule, replayed at every later gate</td></tr>
              <tr><td><strong>Source-contract tests</strong></td><td>Schema hashes and row-count ranges; drift is reported, not absorbed</td></tr>
              <tr><td><strong>Leakage negative test</strong></td><td>A poisoned feature set must raise; if it stops raising, the suite fails</td></tr>
              <tr><td><strong>Frontend parity tests</strong></td><td>Browser-derived figures recomputed independently from the published artifact</td></tr>
              <tr><td><strong>Copy / claim lint</strong></td><td>15 rules over 235 files, blocking prohibited claims in code, docs and interface copy alike</td></tr>
              <tr><td><strong>Performance guards</strong></td><td>Bundle budget, render check, interactivity and frame-rate harnesses with validity floors</td></tr>
              <tr><td><strong>Determinism</strong></td><td>Semantic hash equality under pinned inputs, volatile metadata excluded</td></tr>
              <tr><td><strong>GitHub Actions</strong></td><td>Runs everything a hosted runner can honestly measure, and reports the rest as not executed</td></tr>
            </tbody>
          </table>
        </div>
        <div className="note warn">
          <strong>Coverage is not correctness, and this project has the receipts.</strong>{" "}
          At 100% coverage, with every test passing, the analytical map layer once rendered
          nothing at all — three simultaneous defects, none of which any existing test could
          see, because a populated layer is not a visible layer. The pixel-level render check
          that now exists was added <em>after</em> that, and its first version would itself
          have passed the defect: the broken layer still changed 5.22% of pixels while
          drawing white. It needed a palette assertion to become meaningful. Similarly, the
          road-distance defect of §M was found by reasoning about the method, not by any
          failing test.
        </div>

        {/* ---------------------------------------------------------------- U */}
        <h2 id="reproducibility">U. Reproducibility</h2>
        <ul>
          <li><strong>Immutable raw inputs.</strong> Retrieved payloads are cached with checksums; replay fixtures let the pipeline run with no network access.</li>
          <li><strong>Deterministic transforms.</strong> Same pinned snapshots + same code + same configuration ⇒ same semantic output.</li>
          <li><strong>Semantic hashing.</strong> Byte equality is impossible when every table carries <code>computed_at</code>, so volatile metadata is excluded and everything else — including source vintages — is hashed. A live refresh producing different artifacts is <em>not</em> a determinism failure; treating it as one would push the pipeline toward suppressing real upstream change.</li>
          <li><strong>Artifacts and manifest.</strong> Every published file carries SHA-256, row count, column list, build time and the full source-vintage map.</li>
          <li><strong>Gate process.</strong> Each phase ends with acceptance criteria, coverage thresholds, every prior phase&rsquo;s suite replayed, a forward-viability check and a written report. A phase that breaks an earlier gate has not passed its own.</li>
          <li><strong>Clean-build validation.</strong> The full rebuild is exercised from a clean checkout.</li>
        </ul>

        {/* ---------------------------------------------------------------- V */}
        <h2 id="limitations">V. Known limitations</h2>
        <p>
          These are open. They are listed here at full strength rather than softened, because
          a limitation that only appears in an appendix is not really disclosed.
        </p>
        <ul className="limitations">
          <li><strong>Historical network survivorship.</strong> Stations that closed or left the feed are invisible to the reconstruction, and the bias grows with age.</li>
          <li><strong>Reconstructed capacity has no known bias direction.</strong> Competing effects; neither the totals nor the capture fractions carry a claimed direction.</li>
          <li><strong>Demand uncertainty is real and uneven.</strong> Only one state publishes tract-grain registrations; elsewhere values are anchored to coarser observations or modeled from a state total.</li>
          <li><strong>Access distance is straight-line</strong>, so every reported gap is a lower bound on the true one.</li>
          <li><strong>No interconnection feasibility is claimed.</strong> {GRID_PROXIMITY_NOTE}</li>
          <li><strong>Archived equity overlay.</strong> {CEJST_NOTE}</li>
          <li><strong>Home charging access is excluded from the objective</strong> — the available dataset is a parametric scenario surface indexed by assumed fleet penetration, not an observation of any date.</li>
          <li><strong>Budget is a site count, not money.</strong> No defensible national cost model exists, so the problem is cardinality-constrained.</li>
          <li><strong>A place name does not uniquely identify a cell.</strong> Labels are the population-dominant county, so one portfolio can contain several areas sharing a name, distinguished by rank.</li>
          <li><strong>Time to interactive is reference-environment sensitive.</strong> Same code and profile: 2.38 s unthrottled, 2.94 s at the shipped 4× CPU profile, 3.40 s at 8×. The figure is only meaningful on the documented environment.</li>
          <li><strong>Per-cell map detail is pointer-only.</strong> Keyboard and touch access to the hover card was not built; the Studio&rsquo;s table carries the same information on any device.</li>
          <li><strong>The unmoderated usability check has not been run.</strong> It is the one Phase 6 acceptance criterion still outstanding at release, and it is recorded as outstanding rather than waived.</li>
          <li><strong>The published tile set is a Parquet point layer</strong> rather than vector tiles, because the tiling toolchain was unavailable in this build environment. It renders acceptably at national and state zoom but does not page in by viewport.</li>
        </ul>

        {/* ---------------------------------------------------------------- W */}
        <h2 id="stack">W. Technology stack</h2>
        <p>Only what the repository actually uses.</p>
        <div className="stack">
          <div><h4>Languages</h4><p>Python 3.12, TypeScript, JavaScript, SQL</p></div>
          <div><h4>Data</h4><p>DuckDB, pandas, NumPy, Pandera, Apache Parquet, pyogrio</p></div>
          <div><h4>Modeling</h4><p>scikit-learn — <code>PoissonRegressor</code> (Poisson GLM, log link), <code>Ridge</code> and <code>HistGradientBoostingRegressor</code> as comparators, <code>DBSCAN</code> for site clustering, <code>BallTree</code> for spatial queries</p></div>
          <div><h4>Geospatial</h4><p>H3 (Python and JS, version-matched), Census TIGER/Line, haversine point-to-segment distance with CSR-offset polyline indexing</p></div>
          <div><h4>Optimization</h4><p>PuLP with CBC offline; greedy marginal-gain solver in TypeScript in-browser</p></div>
          <div><h4>Frontend</h4><p>Next.js (static export), React, TypeScript strict, MapLibre GL JS, deck.gl, hyparquet</p></div>
          <div><h4>Performance</h4><p>Web Workers, transferable typed arrays, Lighthouse, Puppeteer, pngjs</p></div>
          <div><h4>Engineering</h4><p>uv, pytest, Ruff, mypy strict, Vitest, ESLint, GitHub Actions, deterministic gate tooling</p></div>
        </div>

        <div className="cta quiet">
          <p>
            The full phase reports, assumption ledger and impact log live in the repository
            alongside the code. Every figure on this page is reproducible from them.
          </p>
          <div className="cta-row">
            <Link className="btn" href="/how-it-works/">Back to the short version</Link>
            <Link className="btn primary" href="/studio/">Plan locations</Link>
          </div>
        </div>
      </div>
    </div>
  );
}
