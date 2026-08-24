-- Mart: EV stock by state and vintage. Stock, never sales (G8).
-- The published total row has been removed in the intermediate layer.
SELECT
    jurisdiction                         AS state,
    vintage,
    ev_count,
    measure_type,
    CAST('{computed_at}' AS VARCHAR)     AS computed_at,
    CAST('{source_vintages}' AS VARCHAR) AS source_vintages
FROM int_state_totals
