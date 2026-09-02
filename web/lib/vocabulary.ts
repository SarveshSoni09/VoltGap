/**
 * The words this application is allowed to use, in one place.
 *
 * CLAUDE.md §11.5 fixes the vocabulary, and §D3 fixes three validation terms that must
 * never be conflated. Scattering those strings through components would make the copy lint
 * a spelling checker over dozens of files and would let one careless label undo work five
 * phases deep. Every user-visible term that carries a correctness obligation lives here.
 *
 * The rules these encode, restated so a reader of this file alone understands why:
 *
 * - Tier A is **"sub-state anchored"**, never "observed". Most Tier A evidence is ZIP- or
 *   county-anchored rather than a direct tract observation (amendment A3).
 * - A DCFC-only measure is a **"DCFC access gap"**. It is not a statement about Level 2.
 * - Substation and transmission distance is **"grid proximity"**, never feasibility: it
 *   says nothing about hosting capacity, feeder availability, or make-ready cost (D6).
 * - The interactive solver states **no approximation bound** (§7.8, amendment A11).
 * - CEJST is an **archived** overlay carrying its vintage; EO 14008 was revoked on
 *   20 January 2025, so nothing here evaluates current compliance (§8).
 * - Nothing is "optimal". Ground truth for optimal siting does not exist (D3).
 */

/**
 * PLAIN labels, shown by default. A first-time reader should not need the project's
 * vocabulary to read the map.
 *
 * These are looser words for the same three tiers, not different tiers, and they must not
 * overstate: "Higher" means better-evidenced than the others, NOT observed. The precise
 * wording lives in `TIER_LABELS_TECHNICAL` and is shown wherever the distinction matters -
 * tooltips, details panels, exports and Methodology.
 */
export const TIER_LABELS_PLAIN = {
  A: "Higher reliability",
  B: "Modelled",
  C: "Lower reliability",
} as const;

/** The accepted technical wording. Never softened, never replaced in exports or docs. */
export const TIER_LABELS = {
  A: "sub-state anchored",
  B: "modeled",
  C: "low confidence",
} as const;

export type Tier = keyof typeof TIER_LABELS;

export const TIER_DESCRIPTIONS: Record<Tier, string> = {
  A: "Some observed sub-state registration evidence supports this area. Most such evidence is ZIP- or county-grain and was allocated down to tracts, so the value here is anchored, not directly observed.",
  B: "No sub-state registration observation. The value rests on a state total plus the demographic propensity model.",
  C: "No sub-state registration observation, and the uncertainty score is above the documented B/C threshold.",
};

/** One line a non-specialist can act on. The precise version is above. */
export const TIER_SUMMARY: Record<Tier, string> = {
  A: "Local registration data helps support this estimate.",
  B: "Estimated from state totals and local demographics.",
  C: "Estimated from state totals, with wider uncertainty than most areas.",
};

export const EVIDENCE_GRAIN_LABELS = {
  native_tract: "observed at tract grain",
  zip_anchored: "allocated from ZIP-grain observations",
  county_anchored: "allocated from county-grain observations",
  state_total_only: "state total plus model",
} as const;

/** The three D3 validation terms. Never interchangeable, never blended. */
export const VALIDATION_TERMS = {
  demandModel: {
    name: "Demand model validation",
    evaluates: "whether tract-level EV estimates are accurate",
    method: "leave-one-state-out against observed states",
  },
  deploymentAlignment: {
    name: "Historical deployment alignment",
    evaluates: "whether priority areas match where industry actually built",
    method: "vintage-enforced rolling-origin backtest",
  },
  robustness: {
    name: "Cross-objective robustness",
    evaluates:
      "whether a portfolio optimized for one objective also performs on others",
    method: "epsilon-constraint Pareto analysis",
  },
} as const;

export const METRIC_LABELS = {
  demand_bev: "Estimated EV demand",
  dcfc_ports: "Existing fast charging",
  km_to_nearest_dcfc_site: "Distance to fast charging",
  priority: "Priority score",
} as const;

/** The question each metric answers, shown under the map heading. */
export const METRIC_QUESTIONS: Record<MetricKey, string> = {
  demand_bev: "Where are the most electric vehicles expected?",
  dcfc_ports: "Where does public fast charging already exist?",
  km_to_nearest_dcfc_site: "How far is the nearest public fast charging?",
  priority: "Where do demand and underserved population overlap?",
};

/** One sentence telling the reader how to read the colour. */
export const METRIC_LEGEND_HINT: Record<MetricKey, string> = {
  demand_bev: "Brighter areas have more estimated EV demand.",
  dcfc_ports: "Brighter areas have more existing public fast-charging ports.",
  km_to_nearest_dcfc_site: "Brighter areas are further from public fast charging.",
  priority: "Brighter areas score higher on the balance you have set.",
};

/**
 * What the empty parts of the map mean. Measured, not guessed: every published cell
 * carries a demand value, none is excluded from drawing, and the faintest is 41% opaque.
 * The gaps are places where no cell exists, because a cell is created only where census
 * population sits. 78.8% of the US landmass has no cell.
 */
export const NO_DATA_EXPLANATION =
  "Unshaded areas have no estimate because nobody lives there — mostly desert, mountain, forest and federal land. They are not zero demand and not low confidence.";

export type MetricKey = keyof typeof METRIC_LABELS;

/**
 * Shown wherever the interactive solver's output appears. §7.8 and amendment A11: the
 * classic greedy guarantee for submodular maximisation assumes a cardinality constraint
 * on a single objective. This surface exposes objective weights and a budget, which is a
 * different problem class, so no formal bound applies and none is stated. Measured
 * shortfalls against exact CBC solves are reported instead - observations, not guarantees.
 */
export const INTERACTIVE_SOLVER_NOTE =
  "Interactive approximation. Exact offline solutions are used for the published analytical frontier.";

/** Shown wherever a priority ranking appears. */
export const NOT_OPTIMALITY_NOTE =
  "A ranking, not a claim of optimality. No ground truth for optimal siting exists, so nothing here is validated as the best place to build.";

/** The short version, for the primary workflow. The full version stays in Methodology. */
export const RECOMMENDATION_NOTE =
  "These are candidate areas worth considering. VoltGap does not claim they are the right places to build — no data exists that could establish that. Interactive results use a fast approximation; the published tradeoff analysis is computed offline.";

/** What the product is, in one sentence a stranger can read. */
export const PRODUCT_ONE_LINER =
  "Where should the next EV chargers be considered?";

export const PRODUCT_EXPLAINER =
  "VoltGap weighs estimated EV demand, the public charging that already exists, underserved communities, and road access — then shows which areas a given budget could cover.";

/** Shown on the historical deployment alignment result. Phase 5's finding was negative. */
export const DEPLOYMENT_ALIGNMENT_NOTE =
  "This measures whether model priorities match where industry actually built. It does not establish that those deployments were optimal, that the model identifies causally correct siting decisions, or that operators should have followed the model.";

/** Shown on the archived CEJST overlay. */
export const CEJST_NOTE =
  "Archived historical equity classification. Executive Order 14008, which established Justice40, was revoked on 20 January 2025, so this reflects a policy framework no longer in force.";

/** Shown on any grid-adjacent context. D6. */
export const GRID_PROXIMITY_NOTE =
  "Grid proximity is a distance proxy only. Distance to electrical infrastructure says nothing about whether a site can actually be connected there, at what cost, or on what timeline. None of that is measured by this project.";
