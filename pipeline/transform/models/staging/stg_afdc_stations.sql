-- Staging: AFDC station records. Typing and renaming ONLY.
-- No filtering here: domain rules G2 (Status Code) and G3 (Access Code) are business
-- logic and are applied in the intermediate layer (CLAUDE.md section 9, amendment A15).
-- A row is one network's presence at a site, never a unit of capacity (G1).
SELECT
    CAST(id AS VARCHAR)                             AS station_id,
    CAST(station_name AS VARCHAR)                   AS station_name,
    CAST(state AS VARCHAR)                          AS state,
    CAST(city AS VARCHAR)                           AS city,
    CAST(zip AS VARCHAR)                            AS zip,
    CAST(status_code AS VARCHAR)                    AS status_code,
    CAST(access_code AS VARCHAR)                    AS access_code,
    CAST(ev_network AS VARCHAR)                     AS ev_network,
    TRY_CAST(latitude AS DOUBLE)                    AS latitude,
    TRY_CAST(longitude AS DOUBLE)                   AS longitude,
    TRY_CAST(open_date AS DATE)                     AS open_date,
    CAST(facility_type AS VARCHAR)                  AS facility_type,
    CAST(owner_type_code AS VARCHAR)                AS owner_type_code,
    TRY_CAST(ev_level1_evse_num AS INTEGER)         AS evse_count_l1,
    TRY_CAST(ev_level2_evse_num AS INTEGER)         AS evse_count_l2,
    TRY_CAST(ev_dc_fast_num AS INTEGER)             AS evse_count_dcfc,
    CAST(ev_connector_types AS VARCHAR)             AS ev_connector_types_raw,
    CAST(ev_pricing AS VARCHAR)                     AS ev_pricing,
    CAST(date_last_confirmed AS VARCHAR)            AS date_last_confirmed
FROM raw_afdc_stations
