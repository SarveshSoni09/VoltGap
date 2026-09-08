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
  title: "How it works: VoltGap",
  description:
    "How VoltGap helps planners explore where additional EV charging may be worth " +
    "considering, and what it deliberately does not claim.",
};

const JOURNEY = [
  {
    n: 1,
    title: "Understand EV demand",
    body:
      "Estimate where electric vehicles are concentrated, from public vehicle " +
      "registration data and census demographics. States publish registrations at " +
      "different levels of detail, so some areas rest on better evidence than others. " +
      "Every estimate carries a rating saying which.",
  },
  {
    n: 2,
    title: "Find charging-access gaps",
    body:
      "Measure how far people live from existing public fast charging. Distances are " +
      "weighted by where the population actually sits, not by the centre of a map " +
      "shape, which in a large rural tract can be tens of kilometres out. Areas beyond " +
      "the distance you choose make up the access gap.",
  },
  {
    n: 3,
    title: "Screen feasible candidate areas",
    body:
      "Drop areas that fail three screens: nobody lives there, no primary or secondary " +
      "road runs within 5 km, or existing fast charging is already ample for the " +
      "estimated demand. What survives is the candidate set.",
  },
  {
    n: 4,
    title: "Build a portfolio",
    body:
      "Choose a state, how many locations you can fund, and what to prioritise. The " +
      "Siting Studio returns a ranked set of candidate areas, and for each one says " +
      "what makes it stand out from the areas around it.",
  },
  {
    n: 5,
    title: "Explore tradeoffs",
    body:
      "Compare what the portfolio covers against what a different priority would have " +
      "chosen: more estimated demand, or more underserved population. Measured on the " +
      "published frontier, a demand-first portfolio reaches 79.6% of the best " +
      "achievable equity coverage. No single ordering wins on everything, so the " +
      "tradeoff is worth seeing rather than hiding.",
  },
] as const;

const LIMITS = [
  {
    claim: "These are candidate areas, not verdicts.",
    body:
      "The ranking reflects the objective you selected and the data available. No " +
      "dataset records the right answer for where a charger should go, so nothing " +
      "here can be checked against one.",
  },
  {
    claim: "Being near power lines does not mean you can connect to them.",
    body:
      "Whether a site can be connected depends on local utility network limits and " +
      "make-ready work. None of that is in any public national dataset, so VoltGap " +
      "treats proximity as context and makes no feasibility claim.",
  },
  {
    claim: "The estimates carry real uncertainty.",
    body:
      "Only Washington publishes registrations at neighbourhood level. Elsewhere the " +
      "figures are estimated from broader totals. Every area carries a reliability " +
      "rating showing how much evidence sits underneath it.",
  },
  {
    claim: "Matching past industry behaviour is not the same as being right.",
    body:
      "One check compares the model's priority areas against where the industry " +
      "actually built next. Companies build for land availability, grants and " +
      "commercial strategy, so agreeing with them would partly mean reproducing their " +
      "biases. On that test a simple population baseline beats the model at every " +
      "date tested, which is reported rather than buried.",
  },
] as const;

export default function HowItWorks() {
  return (
    <div className="prose howto">
      <h1>Where should the next EV chargers go?</h1>
      <p className="standfirst">
        Public and private money is going into EV charging now, and the question of{" "}
        <em>where</em> is usually answered one spreadsheet at a time. VoltGap answers it
        from public data instead, and shows the evidence behind each answer.
      </p>

      <p>
        VoltGap combines EV registrations, charging infrastructure, demographics and
        road-access data to estimate where additional charging may be worth investigating.
        It narrows about 53,000 populated areas to a shortlist you can argue with. It does
        not decide.
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
        <p>Start with a map, or go straight to building a portfolio.</p>
        <div className="cta-row">
          <Link className="btn" href="/">See EV demand</Link>
          <Link className="btn" href="/access/">Find charging gaps</Link>
          <Link className="btn primary" href="/studio/">Plan locations</Link>
        </div>
      </div>

      <h2>What VoltGap does not claim</h2>
      <p>
        A siting tool that overstates its certainty is harder to argue with than one that
        says nothing, so these limits are part of the product rather than a footnote.
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
          <strong>Want the technical details?</strong> The data sources, the models, the
          three validations, the engineering, and every open limitation are written up in
          full.
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
