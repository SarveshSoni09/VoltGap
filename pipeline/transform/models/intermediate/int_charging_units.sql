-- Intermediate: charging units, joined to their station parent.
--
-- Every unit carries port_count = 1 in the national export, so one AFDC charging unit
-- is one port. The canonical model therefore stops here: no cabinet grain exists in
-- the source, and no `ports` table is populated because no stable port identity is
-- recoverable (CLAUDE.md 6.1.1; Phase 1 identifiability measurements m2, m5, m7).
SELECT
    u.charging_unit_record_key,
    u.station_id,
    u.record_ordinal,
    u.state,
    u.status_code,
    u.access_code,
    u.ev_network,
    u.charging_level,
    coalesce(u.port_count, 0)                       AS port_count,
    u.latitude,
    u.longitude,
    (u.status_code = 'E' AND u.access_code = 'public') AS is_public_operational,
    -- Sum of connector-specific port counts. Where this exceeds port_count, one
    -- physical port exposes more than one connector standard (measurement m4).
    coalesce(u.c_j1772_ports, 0) + coalesce(u.c_j1772combo_ports, 0)
      + coalesce(u.c_chademo_ports, 0) + coalesce(u.c_tesla_ports, 0)
      + coalesce(u.c_j3271_ports, 0) + coalesce(u.c_nema515_ports, 0)
      + coalesce(u.c_nema520_ports, 0) + coalesce(u.c_nema1450_ports, 0)
                                                    AS connector_port_sum,
    (coalesce(u.c_j1772_ports, 0) + coalesce(u.c_j1772combo_ports, 0)
      + coalesce(u.c_chademo_ports, 0) + coalesce(u.c_tesla_ports, 0)
      + coalesce(u.c_j3271_ports, 0) + coalesce(u.c_nema515_ports, 0)
      + coalesce(u.c_nema520_ports, 0) + coalesce(u.c_nema1450_ports, 0)
     ) > coalesce(u.port_count, 0)                  AS is_multi_connector_port
FROM stg_afdc_charging_units u
