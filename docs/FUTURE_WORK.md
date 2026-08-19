# Future work

Everything that tempts a redesign mid-build (CLAUDE.md §18.9). Ideas here are recorded
and deliberately **not** acted on.

## Raised in Phase 0

| Idea | Why it is tempting | Why it waits |
|---|---|---|
| Retrieve full Atlas EV Hub state files and reconstruct the complete DMV snapshot series per state | Would turn 14 states into a genuine sub-state longitudinal panel, far stronger than the single Illinois panel, and would strengthen §10.2 deployment alignment considerably | ~3.4 GB across 14 files. Phase 0's job is to establish the contract, not to ingest. This is Phase 1/3 work and should be planned as such, not smuggled into Phase 0. |
| Obtain archived AFDC station snapshots to replace the survivorship-biased reconstruction | Would remove the single largest caveat on §10.2 (domain rule G11) | CLAUDE.md §10.2.5 explicitly routes this here rather than into a redesign. No archive source has been located. |
| Build a ZIP-to-tract crosswalk from HUD USPS crosswalk files | 11 of the 16 states with sub-state registration data are ZIP-grain | Belongs to Phase 3 where the demand model needs it. Recorded as assumption A-0.7. |
| Use the NREL home charging scenario surface at the EV-share slice closest to current fleet penetration, treating it as approximately current | Would let home charging into the primary objective rather than the exploratory index | Choosing a slice is a modelling decision dressed as a data decision. §7.2's fallback is unambiguous once the shares are established as non-current, and Phase 0 established that. Raised as an open question for the reviewer instead. |
| Mirror the CEJST archive copy locally and serve it from R2 | Removes a third-party single point of failure (assumption A-0.10) | Cheap and probably right, but it is Phase 6 hosting work. |
| Per-source drift tolerances calibrated from observed behaviour over several refreshes | The provisional ±20% default is a guess for most sources | Needs several observations to calibrate against. Assumption A-0.13. |
| Probe the AFDC `electric-networks` endpoint to enumerate network names authoritatively | Would help site clustering and the empirical power fallback in §7.1 rung 2 | Not needed for the Phase 0 contract, and the AFDC quota is scarce until a personal key exists. |

## Added by the Phase 0 review (2026-08-19)

| Idea | Why it is tempting | Why it waits |
|---|---|---|
| Give eGRID a consumer: avoided-emissions estimates, electricity carbon-intensity analysis, carbon-aware siting, emissions-per-mile comparison, environmental-benefit scenarios | eGRID is confirmed reachable and the data are good | None of these is required by the Core decision engine. eGRID is demoted to Optional/Future Work (`CLAUDE.md` §7.12). **Do not invent an emissions feature in order to justify keeping the source.** Promote it only if a concrete Core consumer appears |
| Promote home charging access into the primary siting objective | It is one of the strongest available predictors of public charging need | Settled by owner decision A7 and explicitly not reopenable in Phase 3. The NREL dataset is a parametric scenario surface, so any slice of it is a modelling choice. Revisit only if new empirical data materially changes the source situation |
| Regional substation datasets from individual utilities or state agencies | Would restore genuine grid proximity where a trustworthy source exists | `CLAUDE.md` §7.9 already permits this as an *optional* per-region feature with source provenance. It is not Core work and must never become a national constraint by accretion |
| Semantic copy linting beyond phrase matching | Would catch paraphrased optimality and feasibility claims | Owner decision A9 accepts a rule-based guard for Phase 1; Phase 5 may extend it. Do not build an NLP layer for this |
