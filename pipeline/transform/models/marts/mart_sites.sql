-- Mart: physical sites, resolved by DBSCAN clustering of station coordinates.
--
-- G4: exact coordinate duplicates are usually co-located multi-network infrastructure,
-- not duplicate records. They are aggregated into one site for coverage and their
-- ports are SUMMED for capacity. Nothing is deleted.
-- G1: station rows are never counted as capacity; capacity comes from unit counts.
SELECT
    a.site_id,
    any_value(a.site_latitude)                          AS latitude,
    any_value(a.site_longitude)                         AS longitude,
    count(DISTINCT s.station_id)                        AS station_count,
    count(DISTINCT s.ev_network)                        AS network_count,
    any_value(s.state)                                  AS state,
    sum(CASE WHEN s.is_public_operational THEN 1 ELSE 0 END) AS public_operational_stations,
    coalesce(sum(u.unit_count), 0)                      AS charging_unit_count,
    coalesce(sum(u.public_operational_unit_count), 0)   AS public_operational_unit_count,
    CAST('{computed_at}' AS VARCHAR)                    AS computed_at,
    CAST('{source_vintages}' AS VARCHAR)                AS source_vintages
FROM computed_site_assignments a
JOIN int_stations s ON s.station_id = a.station_id
LEFT JOIN (
    SELECT station_id,
           count(*) AS unit_count,
           sum(CASE WHEN is_public_operational THEN 1 ELSE 0 END)
               AS public_operational_unit_count
    FROM int_charging_units
    GROUP BY station_id
) u ON u.station_id = s.station_id
GROUP BY a.site_id
