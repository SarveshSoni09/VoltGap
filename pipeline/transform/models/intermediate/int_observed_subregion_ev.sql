-- Intermediate: sub-state registration observations, with geography provenance.
--
-- CLAUDE.md section 7.5.1: the source geography is declared explicitly and is never
-- inferred from column naming. A USPS ZIP Code is a mail-delivery route collection,
-- not an area, and is NOT interchangeable with a Census ZCTA.
--
-- evidence_grain records the finest observed evidence; estimate_method records what
-- was done to produce the value (CLAUDE.md 7.4.1). At this layer nothing has been
-- allocated yet, so every row is directly observed AT ITS OWN SOURCE GEOGRAPHY.
-- Allocation to tracts happens in pipeline/spatial/crosswalk.py and downgrades
-- estimate_method to 'crosswalked'.
SELECT
    state,
    source_geography_type,
    source_geography_id,
    dmv_snapshot_label                      AS vintage,
    dmv_snapshot_id,
    (lower(latest_snapshot_flag) = 'true')  AS is_latest_snapshot,
    sum(coalesce(vehicle_count, 0))         AS ev_count,
    CASE source_geography_type
        WHEN 'tract'  THEN 'native_tract'
        WHEN 'county' THEN 'county_anchored'
        WHEN 'usps_zip' THEN 'zip_anchored'
        WHEN 'zcta'   THEN 'zip_anchored'
        ELSE 'state_total_only'
    END                                     AS evidence_grain,
    'directly_observed'                     AS estimate_method
FROM stg_atlas_registrations
GROUP BY ALL
