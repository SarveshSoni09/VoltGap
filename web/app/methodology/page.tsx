import {
  CEJST_NOTE,
  DEPLOYMENT_ALIGNMENT_NOTE,
  GRID_PROXIMITY_NOTE,
  INTERACTIVE_SOLVER_NOTE,
  NOT_OPTIMALITY_NOTE,
  VALIDATION_TERMS,
} from "../../lib/vocabulary";

/**
 * A first-class view, not a footer link (§11.1).
 *
 * Every number quoted here is copied from the accepted Phase 3, 4 and 5 evidence
 * artifacts. Nothing is strengthened for presentation: the headline validation result is
 * negative against the population baseline and is reported that way.
 */
export default function Methodology() {
  return (
    <div className="prose">
      <h1>Methodology &amp; Validation</h1>
      <p>
        VoltGap estimates where EV charging demand is, what supply already exists, and
        which cells a budget could most usefully cover. This page states what has been
        validated, what has not, and what the numbers cannot support.
      </p>

      <div className="note warn">
        <strong>{NOT_OPTIMALITY_NOTE}</strong>
      </div>

      <h2>Three separate validations, never interchangeable</h2>
      <p>
        These evaluate different things by different methods. Conflating them would let a
        result about one be read as a result about another.
      </p>
      <table>
        <thead>
          <tr><th>Term</th><th>What it evaluates</th><th>Method</th></tr>
        </thead>
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

      <h2>Demand model validation</h2>
      <p>
        Leave-one-state-out across 14 independent states with sub-state registration
        evidence. Aggregate weighted WAPE <code>0.3809</code> unreconciled and{" "}
        <code>0.3203</code> reconciled.
      </p>
      <p>
        <strong>Washington is excluded from the headline aggregate.</strong> It is the only
        state publishing registrations at tract grain, and it was used to measure the
        geographic allocation error the model relies on, so scoring the model on it would
        be scoring it on its own development evidence.
      </p>
      <p>
        No supply-derived feature enters the demand model. Charger counts, port counts and
        distance-to-charger are excluded by a test, not by convention: existing
        infrastructure is an outcome of past investment, and using it to predict demand
        would launder historical deployment patterns into &ldquo;need&rdquo;, suppressing
        exactly the underserved areas this system exists to find.
      </p>

      <h2>Historical deployment alignment</h2>
      <div className="note warn"><strong>{DEPLOYMENT_ALIGNMENT_NOTE}</strong></div>
      <p>
        Three rolling origins, each predicting the following 24 months, with a runtime
        vintage guard asserting that no feature postdates its prediction cutoff.
      </p>
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
      <div className="note warn">
        <strong>This is a negative result, and it is reported as one.</strong> The model
        strongly outperforms random and the existing-network baseline, but does{" "}
        <strong>not</strong> outperform a simple population baseline for reproducing
        subsequent industry deployment locations at any origin. That is a negative
        historical-deployment-alignment result. It is not evidence of siting failure, and
        it is not itself evidence for or against the decision to exclude supply features
        from the demand model.
      </div>
      <p>
        Reconstructed capacity carries a further caveat: power values come from the current
        snapshot attributed to each station&rsquo;s open date, so an upgraded station carries
        its present power. Stations that closed are absent entirely. The biases compete and
        the net direction is <strong>unknown</strong>, so no bias direction is claimed for
        the reconstructed totals or for the capture fractions computed from them.
      </p>

      <h2>Cross-objective robustness</h2>
      <p>
        Portfolios optimized on one objective, scored on objectives that were never in that
        loss function. The result is an exposed tradeoff, not a win: a demand-first
        portfolio reaches <code>79.6%</code> of the best achievable equity coverage, and an
        equity-first portfolio reaches <code>81.9%</code> of the best achievable demand
        coverage.
      </p>

      <h2>What the interactive solver does and does not claim</h2>
      <p>{INTERACTIVE_SOLVER_NOTE}</p>
      <p>
        With a single objective, uniform costs and no further constraint, greedy selection
        on this problem would be cardinality-constrained maximum coverage, where a formal
        approximation guarantee applies. <strong>That is not this problem.</strong> The
        Studio exposes objective weights and constraint toggles, making it a weighted
        multi-objective selection under additional constraints, and the guarantee does not
        carry over. <strong>No approximation bound is claimed anywhere.</strong> Measured
        shortfalls against exact offline solves are reported instead — the worst observed
        was <code>3.14%</code> across eighteen problems, which is an observation, not a
        bound.
      </p>

      <h2>Limits worth stating plainly</h2>
      <ul>
        <li>
          <strong>Confidence tiers.</strong> Tier A means <em>sub-state anchored</em>, not
          observed. Only Washington publishes registrations at tract grain; the rest is
          allocated from ZIP or county observations, or modeled from a state total.
        </li>
        <li>
          <strong>Access distance is straight-line.</strong> It understates real travel
          distance, so a reported gap is a lower bound on the true gap.
        </li>
        <li>
          <strong>The historical network is an approximate reconstruction.</strong> A
          current snapshot plus open dates cannot recover stations that closed or changed,
          so it is survivorship-biased and the bias grows with age.
        </li>
        <li><strong>Grid.</strong> {GRID_PROXIMITY_NOTE}</li>
        <li><strong>Archived equity overlay.</strong> {CEJST_NOTE}</li>
        <li>
          <strong>Home charging access is excluded</strong> from the siting objective. The
          available dataset is a parametric scenario surface indexed by assumed fleet
          penetration, not an observation of any date.
        </li>
      </ul>
    </div>
  );
}
