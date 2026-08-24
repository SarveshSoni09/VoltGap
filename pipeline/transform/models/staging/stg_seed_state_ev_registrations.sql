-- Staging: the delivered, undated state registration seed file.
-- Phase 0 dated it to the AFDC 2023 vintage (51/51 jurisdictions match after half-up
-- rounding to the nearest 100). The 'Total' row is ingested unchanged; G8 removes it
-- in intermediate.
SELECT
    '2023'                                          AS vintage,
    CAST("State" AS VARCHAR)                        AS jurisdiction,
    TRY_CAST("Registration Count" AS BIGINT)        AS ev_count
FROM raw_seed_state_ev_registrations
