-- Staging: AFDC state EV registration vintages, 2016-2025, unioned with a vintage tag.
-- The published 'United States' total row is INGESTED HERE UNCHANGED; domain rule G8
-- removes it in the intermediate layer (amendment A15).
SELECT
    CAST(vintage AS VARCHAR)                                        AS vintage,
    CAST("State" AS VARCHAR)                                        AS jurisdiction,
    TRY_CAST(replace("Electric (EV)", ',', '') AS BIGINT)           AS ev_count,
    TRY_CAST(replace("Plug-In Hybrid Electric (PHEV)", ',', '') AS BIGINT) AS phev_count
FROM raw_afdc_state_ev_registrations
