-- Intermediate: connectors at (charging_unit_record_key, connector_type) grain.
--
-- AFDC exposes connector-type COUNTS and power on a unit, not identified connectors,
-- so no physical connector_id row is manufactured (CLAUDE.md 6.1.1, amendment A13).
-- Rows with a zero port count are retained so that "this unit does not offer this
-- standard" stays distinguishable from "this unit was never asked about it".
--
-- Eight connector standards are exposed by the JSON API against five in the CSV
-- export; the three NEMA types are Level 1 household outlets the CSV drops entirely.
WITH unpivoted AS (
    SELECT charging_unit_record_key, 'J1772'      AS connector_type,
           c_j1772_ports      AS connector_count, c_j1772_kw      AS power_kw
    FROM stg_afdc_charging_units
    UNION ALL SELECT charging_unit_record_key, 'J1772COMBO', c_j1772combo_ports, c_j1772combo_kw FROM stg_afdc_charging_units
    UNION ALL SELECT charging_unit_record_key, 'CHADEMO',    c_chademo_ports,    c_chademo_kw    FROM stg_afdc_charging_units
    UNION ALL SELECT charging_unit_record_key, 'TESLA',      c_tesla_ports,      c_tesla_kw      FROM stg_afdc_charging_units
    UNION ALL SELECT charging_unit_record_key, 'J3271',      c_j3271_ports,      c_j3271_kw      FROM stg_afdc_charging_units
    UNION ALL SELECT charging_unit_record_key, 'NEMA515',    c_nema515_ports,    c_nema515_kw    FROM stg_afdc_charging_units
    UNION ALL SELECT charging_unit_record_key, 'NEMA520',    c_nema520_ports,    c_nema520_kw    FROM stg_afdc_charging_units
    UNION ALL SELECT charging_unit_record_key, 'NEMA1450',   c_nema1450_ports,   c_nema1450_kw   FROM stg_afdc_charging_units
)
SELECT
    charging_unit_record_key,
    connector_type,
    coalesce(connector_count, 0) AS connector_count,
    power_kw,
    -- Power resolution rung 1 (CLAUDE.md 7.1). Rungs 2 and 3 are Phase 2 work.
    CASE WHEN power_kw IS NOT NULL AND power_kw > 0 THEN 'reported' ELSE NULL END
        AS power_source,
    (power_kw IS NOT NULL AND power_kw > 0) AS has_reported_power,
    -- 0.00 kW is not a valid reported power; 55 such cells exist nationally.
    (power_kw IS NOT NULL AND power_kw = 0)  AS is_zero_power_anomaly
FROM unpivoted
