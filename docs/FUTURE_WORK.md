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
