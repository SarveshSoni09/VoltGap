-- Intermediate: station entity with business rules applied and made visible.
--
-- G2: Status Code has three values; only 'E' is operational supply.
-- G3: Access Code includes 'private', which is not public supply.
-- Both are expressed as FLAGS rather than as a WHERE clause, so the canonical table
-- keeps every station and downstream models choose their own filter explicitly. A row
-- is one network's presence at a site, never capacity (G1).
SELECT
    station_id,
    station_name,
    state,
    city,
    zip,
    status_code,
    access_code,
    ev_network,
    latitude,
    longitude,
    open_date,
    facility_type,
    owner_type_code,
    coalesce(evse_count_l1, 0)   AS evse_count_l1,
    coalesce(evse_count_l2, 0)   AS evse_count_l2,
    coalesce(evse_count_dcfc, 0) AS evse_count_dcfc,
    ev_connector_types_raw,
    -- G14: EV Connector Types is a space-delimited concatenated string in the bulk
    -- CSV, not a normalised field. Split it rather than matching substrings.
    CASE
        WHEN ev_connector_types_raw IS NULL OR ev_connector_types_raw = '' THEN []
        ELSE str_split(trim(ev_connector_types_raw), ' ')
    END                          AS ev_connector_types,
    (status_code = 'E')          AS is_operational,
    (access_code = 'public')     AS is_public,
    (status_code = 'E' AND access_code = 'public') AS is_public_operational
FROM stg_afdc_stations
