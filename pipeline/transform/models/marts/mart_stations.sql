-- Mart: one row per AFDC station record, joined to its resolved site.
-- A row is one network's presence at a site, never a unit of capacity (G1).
SELECT
    s.station_id,
    a.site_id,
    s.station_name,
    s.state,
    s.city,
    s.zip,
    s.status_code,
    s.access_code,
    s.ev_network,
    s.latitude,
    s.longitude,
    s.open_date,
    s.facility_type,
    s.evse_count_l1,
    s.evse_count_l2,
    s.evse_count_dcfc,
    s.ev_connector_types,
    s.is_operational,
    s.is_public,
    s.is_public_operational,
    CAST('{computed_at}' AS VARCHAR)     AS computed_at,
    CAST('{source_vintages}' AS VARCHAR) AS source_vintages
FROM int_stations s
LEFT JOIN computed_site_assignments a ON a.station_id = s.station_id
