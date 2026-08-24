-- Intermediate: state EV registration totals by vintage.
--
-- G8: these are STOCK, never sales, and the published total row must be excluded
-- before any aggregation. The adapter ingested it unchanged (A15); this is where it
-- is removed, visibly and testably. AFDC labels the row 'United States'; the
-- delivered seed file labels it 'Total'.
SELECT
    vintage,
    jurisdiction,
    ev_count,
    'stock' AS measure_type
FROM stg_state_ev_registrations
WHERE jurisdiction NOT IN ('United States', 'Total')
  AND jurisdiction IS NOT NULL
  AND jurisdiction <> ''
  AND ev_count IS NOT NULL
