-- Mart: sub-state registration observations with explicit geographic provenance.
--
-- Every row carries evidence_grain and estimate_method, never collapsed into a single
-- label (CLAUDE.md 7.4.1). No ZIP-derived or county-derived value may ever be labelled
-- directly_observed at TRACT grain; at this layer nothing has been allocated, so each
-- row is directly observed at its own source geography and says so.
SELECT
    state,
    source_geography_type,
    source_geography_id,
    vintage,
    dmv_snapshot_id,
    is_latest_snapshot,
    ev_count,
    evidence_grain,
    estimate_method,
    CAST('{computed_at}' AS VARCHAR)     AS computed_at,
    CAST('{source_vintages}' AS VARCHAR) AS source_vintages
FROM int_observed_subregion_ev
