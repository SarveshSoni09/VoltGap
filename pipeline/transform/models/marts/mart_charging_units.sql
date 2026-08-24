-- Mart: one row per AFDC charging unit record.
--
-- charging_unit_record_key is synthetic and per-snapshot. It carries NO longitudinal
-- physical-unit identity and must never be used to track a unit across refreshes
-- (CLAUDE.md 6.1.1). key_is_synthetic is carried in the data so a consumer cannot
-- mistake it for a stable identifier.
--
-- port_count is 1 for every unit: an AFDC charging unit is one port. There is no
-- cabinet grain in the source, and no `ports` table is populated because no stable
-- port identity is recoverable.
SELECT
    u.charging_unit_record_key,
    u.station_id,
    a.site_id,
    u.record_ordinal,
    u.state,
    u.status_code,
    u.access_code,
    u.ev_network,
    u.charging_level,
    u.port_count,
    u.connector_port_sum,
    u.is_multi_connector_port,
    u.is_public_operational,
    TRUE                                 AS key_is_synthetic,
    FALSE                                AS has_longitudinal_identity,
    CAST('{computed_at}' AS VARCHAR)     AS computed_at,
    CAST('{source_vintages}' AS VARCHAR) AS source_vintages
FROM int_charging_units u
LEFT JOIN computed_site_assignments a ON a.station_id = u.station_id
