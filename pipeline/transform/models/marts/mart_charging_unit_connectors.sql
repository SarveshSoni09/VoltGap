-- Mart: connectors at (charging_unit_record_key, connector_type) grain.
-- No physical connector_id is manufactured from a count (CLAUDE.md 6.1.1, A13).
SELECT
    c.charging_unit_record_key,
    c.connector_type,
    c.connector_count,
    c.power_kw,
    c.power_source,
    c.has_reported_power,
    c.is_zero_power_anomaly,
    u.charging_level,
    u.is_public_operational,
    CAST('{computed_at}' AS VARCHAR)     AS computed_at,
    CAST('{source_vintages}' AS VARCHAR) AS source_vintages
FROM int_charging_unit_connectors c
JOIN int_charging_units u USING (charging_unit_record_key)
