-- Staging: Atlas EV Hub state DMV registrations, unioned across states.
-- Source geography is declared explicitly per row and is never inferred from column
-- naming (CLAUDE.md section 7.5.1). 11 states publish USPS ZIP Code, 3 publish county.
SELECT
    CAST("State" AS VARCHAR)                        AS state,
    CAST(source_geography_type AS VARCHAR)          AS source_geography_type,
    CAST(source_geography_id AS VARCHAR)            AS source_geography_id,
    CAST(try_strptime("Registration Date", '%-m/%-d/%Y') AS DATE) AS registration_date,
    CAST("Vehicle Make" AS VARCHAR)                 AS vehicle_make,
    CAST("Vehicle Model" AS VARCHAR)                AS vehicle_model,
    CAST("Drivetrain Type" AS VARCHAR)              AS drivetrain_type,
    TRY_CAST("Vehicle Count" AS BIGINT)             AS vehicle_count,
    CAST("DMV Snapshot ID" AS VARCHAR)              AS dmv_snapshot_id,
    CAST("DMV Snapshot (Date)" AS VARCHAR)          AS dmv_snapshot_label,
    CAST("Latest DMV Snapshot Flag" AS VARCHAR)     AS latest_snapshot_flag
FROM raw_atlas_registrations
