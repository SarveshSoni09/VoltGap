-- Staging: AFDC charging units, one row per unit record.
--
-- charging_unit_record_key is SYNTHETIC and PER-SNAPSHOT. It is not a physical
-- identifier and must never be used to track a unit across refreshes: the source
-- exposes no unit identifier, and 65.9% of unit rows are byte-identical to another
-- row, so only row order separates them (CLAUDE.md section 6.1.1, impact log I-1).
--
-- unit_port_count is 1 for every unit in the national export: an AFDC charging unit
-- IS one port. No cabinet grain exists in the source.
SELECT
    CAST(charging_unit_record_key AS VARCHAR)       AS charging_unit_record_key,
    CAST(station_id AS VARCHAR)                     AS station_id,
    TRY_CAST(record_ordinal AS INTEGER)             AS record_ordinal,
    CAST(station_state AS VARCHAR)                  AS state,
    CAST(station_status_code AS VARCHAR)            AS status_code,
    CAST(station_access_code AS VARCHAR)            AS access_code,
    CAST(unit_network AS VARCHAR)                   AS ev_network,
    CAST(unit_charging_level AS VARCHAR)            AS charging_level,
    TRY_CAST(unit_port_count AS INTEGER)            AS port_count,
    TRY_CAST(station_latitude AS DOUBLE)            AS latitude,
    TRY_CAST(station_longitude AS DOUBLE)           AS longitude,
    TRY_CAST(connector_J1772_port_count AS INTEGER)      AS c_j1772_ports,
    TRY_CAST(connector_J1772_power_kw AS DOUBLE)         AS c_j1772_kw,
    TRY_CAST(connector_J1772COMBO_port_count AS INTEGER) AS c_j1772combo_ports,
    TRY_CAST(connector_J1772COMBO_power_kw AS DOUBLE)    AS c_j1772combo_kw,
    TRY_CAST(connector_CHADEMO_port_count AS INTEGER)    AS c_chademo_ports,
    TRY_CAST(connector_CHADEMO_power_kw AS DOUBLE)       AS c_chademo_kw,
    TRY_CAST(connector_TESLA_port_count AS INTEGER)      AS c_tesla_ports,
    TRY_CAST(connector_TESLA_power_kw AS DOUBLE)         AS c_tesla_kw,
    TRY_CAST(connector_J3271_port_count AS INTEGER)      AS c_j3271_ports,
    TRY_CAST(connector_J3271_power_kw AS DOUBLE)         AS c_j3271_kw,
    TRY_CAST(connector_NEMA515_port_count AS INTEGER)    AS c_nema515_ports,
    TRY_CAST(connector_NEMA515_power_kw AS DOUBLE)       AS c_nema515_kw,
    TRY_CAST(connector_NEMA520_port_count AS INTEGER)    AS c_nema520_ports,
    TRY_CAST(connector_NEMA520_power_kw AS DOUBLE)       AS c_nema520_kw,
    TRY_CAST(connector_NEMA1450_port_count AS INTEGER)   AS c_nema1450_ports,
    TRY_CAST(connector_NEMA1450_power_kw AS DOUBLE)      AS c_nema1450_kw
FROM raw_afdc_charging_units
