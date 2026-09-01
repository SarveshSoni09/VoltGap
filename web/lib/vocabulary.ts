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
  demand_bev: "Estimated BEV demand",
  dcfc_ports: "Existing DC fast ports",
  km_to_nearest_dcfc_site: "DCFC access gap (km to nearest site)",
  priority: "Priority score",
} as const;

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

/** Shown on the historical deployment alignment result. Phase 5's finding was negative. */
export const DEPLOYMENT_ALIGNMENT_NOTE =
  "This measures whether model priorities match where industry actually built. It does not establish that those deployments were optimal, that the model identifies causally correct siting decisions, or that operators should have followed the model.";

/** Shown on the archived CEJST overlay. */
export const CEJST_NOTE =
  "Archived historical equity classification. Executive Order 14008, which established Justice40, was revoked on 20 January 2025, so this reflects a policy framework no longer in force.";

/** Shown on any grid-adjacent context. D6. */
export const GRID_PROXIMITY_NOTE =
  "Grid proximity is a distance proxy only. Distance to electrical infrastructure says nothing about whether a site can actually be connected there, at what cost, or on what timeline. None of that is measured by this project.";
