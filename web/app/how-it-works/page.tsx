import Link from "next/link";

/**
 * The plain-language entry point, for a reader who has never heard of VoltGap.
 *
 * The technical record lives at /methodology. This page deliberately does NOT mention H3,
 * Poisson regression, the ε-constraint, CBC, ACS vintage rules or the evidence-grain
 * vocabulary: a reader who needs those follows the link at the bottom, and a reader who
 * does not should still finish knowing what the product is and what it refuses to claim.
 *
 * The limits section is not a disclaimer footer. Overstating what a siting tool knows is
 * the characteristic failure of this genre, so what VoltGap does not claim is part of the
 * explanation of what it is.
 */
export const metadata = {
  title: "How it works — VoltGap",
  description:
    "How VoltGap helps planners explore where additional EV charging may be worth " +
    "considering, and what it deliberately does not claim.",
};

const JOURNEY = [
  {
    n: 1,
    title: "Understand EV demand",
    body:
      "Estimate where electric vehicles are concentrated, using public vehicle " +
      "registration data and census demographics. Registration data is published at " +
      "different levels of detail by different states, so some areas rest on stronger " +
      "evidence than others — and every estimate says which it is.",
  },
  {
    n: 2,
    title: "Find charging-access gaps",
    body:
      "Measure how far people live from existing public fast charging, weighting by " +
      "where the population actually is rather than by the centre of a map shape. " +
      "Areas beyond a distance you choose are the access gap.",
  },
  {
    n: 3,
    title: "Screen feasible candidate areas",
    body:
      "Remove areas that fail the project's screening rules: nobody lives there, no " +
      "major road runs near enough, or the area already has ample charging for its " +
      "estimated demand. What survives is the candidate set.",
  },
  {
    n: 4,
    title: "Build a portfolio",
    body:
      "Choose a state, how many locations you can fund, and what you are optimising " +
      "for. VoltGap returns a ranked set of candidate areas and explains why each one " +
      "stands out from the others around it.",
  },
  {
    n: 5,
    title: "Explore tradeoffs",
    body:
      "Compare what the portfolio covers against what a different priority would have " +
      "chosen — more estimated demand, or more underserved population. Seeing what you " +
      "give up is the point; there is no single ordering that is best on everything.",
  },
] as const;

const LIMITS = [
  {
    claim: "These are candidate areas, not verdicts.",
    body:
      "VoltGap ranks areas against the objective you selected, from the data it has. " +
      "There is no dataset anywhere that records the right answer for where a charger " +
      "should go, so nothing here can be checked against one.",
  },
  {
    claim: "Being near power lines does not mean you can connect to them.",
    body:
      "Whether a site can actually be connected depends on local utility network " +
      "limits and make-ready work, none of which is in any public national dataset. " +
      "Proximity is context, not feasibility.",
  },
  {
    claim: "The estimates carry real uncertainty.",
    body:
      "Only one state publishes registrations at neighbourhood level. Elsewhere the " +
      "figures are estimated from broader totals, and every area carries a reliability " +
      "rating saying how much evidence sits underneath it.",
  },
  {
    claim: "Matching past industry behaviour is not the same as being right.",
    body:
      "One check asks whether the model's priority areas match where the industry " +
      "actually built afterwards. Companies build for land availability, grants and " +
      "commercial strategy, so agreeing with them would partly mean reproducing their " +
      "biases. It is a sanity check, not a score.",
  },
] as const;

export default function HowItWorks() {
  return (
    <div className="prose howto">
      <h1>Where should the next EV chargers go?</h1>
      <p className="standfirst">
        Public money and private capital are being spent on electric-vehicle charging right
        now, and the question of <em>where</em> is mostly answered with intuition, one
        spreadsheet at a time. VoltGap is an attempt to answer it with public data, in the
        open, without overstating what the data can support.
      </p>

      <p>
        VoltGap combines estimated EV demand, existing charging access, community
        characteristics and infrastructure constraints to help planners explore where
        additional charging investment may have the most value. It is a decision-support
        tool: it narrows tens of thousands of areas down to a shortlist you can reason
        about, and shows its working at every step.
      </p>

      <h2>The five steps</h2>
      <ol className="journey">
        {JOURNEY.map((step) => (
          <li key={step.n}>
            <span className="jn" aria-hidden="true">{step.n}</span>
            <div>
              <h3>{step.title}</h3>
              <p>{step.body}</p>
            </div>
          </li>
        ))}
      </ol>

      <div className="cta">
        <p>Start with the map, or go straight to planning a portfolio.</p>
        <div className="cta-row">
          <Link className="btn" href="/">See EV demand</Link>
          <Link className="btn" href="/access/">Find charging gaps</Link>
          <Link className="btn primary" href="/studio/">Plan locations</Link>
        </div>
      </div>

      <h2>What VoltGap does not claim</h2>
      <p>
        This matters as much as what it does claim. A tool that quietly overstates its
        certainty is worse than no tool, because it is harder to argue with.
      </p>
      <dl className="limits">
        {LIMITS.map((limit) => (
          <div key={limit.claim}>
            <dt>{limit.claim}</dt>
            <dd>{limit.body}</dd>
          </div>
        ))}
      </dl>

      <div className="cta quiet">
        <p>
          <strong>Want the technical details?</strong> The models, the data sources, the
          three separate validations, the engineering, and every open limitation are
          written up in full.
        </p>
        <div className="cta-row">
          <Link className="btn primary" href="/methodology/">
            Explore Methodology &amp; Architecture
          </Link>
        </div>
      </div>
    </div>
  );
}
