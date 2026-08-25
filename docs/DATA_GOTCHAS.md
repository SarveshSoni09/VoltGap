# Data gotchas — domain rules G1 to G14

Properties of the upstream data, not preferences. Each has at least one regression test
in `tests/regression/test_domain_rules.py`, and a completeness test fails if any rule
lacks one. Counts below are measured against the frozen seed fixtures, whose
expectations never drift with the live source.

> **G9 was amended.** The original rule was factually wrong against the delivered data.
> It was corrected through `docs/reports/PLAN_CHANGE_0.md`, approved as Option A with
> modified wording, and logged as amendment A1 in `CLAUDE.md` §19. The corrected rule
> is below; the original is preserved in the plan-change document.

---

## G1 — A station record is not capacity

AFDC station records are **sites of one network's presence**, not ports. A record with
one Level 2 plug and a record with forty DC fast stalls are both one row.

```
national snapshot, 11 Dec 2024
  station records          79,618
  ports (L1 + L2 + DCFC)  228,662
  ratio                      2.87x
```

Counting rows as capacity understates supply by roughly a factor of three, unevenly
across states. Capacity comes from `mart_charging_units`, never from counting
`mart_stations` rows.

*Reproduce:* `test_g1_station_rows_are_not_capacity`.

## G2 — Status Code has three values; only E is operational

```
E  available              73,972
T  temporarily unavailable 5,217
P  planned                   429
```

Expressed as the `is_operational` flag on `mart_stations` rather than as a filter, so
the canonical table keeps every station and each downstream model chooses explicitly.

*Reproduce:* `test_g2_status_code_has_three_values_with_known_counts`.

## G3 — Access Code includes private

```
public   74,956
private   4,662
```

Private stations are not public supply. Carried as `is_public`; combined with G2 into
`is_public_operational`.

*Reproduce:* `test_g3_private_stations_exist_and_are_not_public_supply`.

## G4 — Coordinate duplicates are co-located infrastructure, not duplicate records

1,756 rows share an exact `(Latitude, Longitude)` with an earlier row. These are
usually **co-located multi-network infrastructure**: a site where two or three networks
each operate their own stalls. They are aggregated into one site for coverage and their
ports summed for capacity. **They are never deleted.**

Site resolution uses DBSCAN with the haversine metric at eps 50 m, **not coordinate
rounding**. Rounding creates arbitrary grid-boundary splits: two stations 8 m apart can
round to different cells while two 140 m apart round together.

In the Minnesota fixture, 1,029 stations resolve to 780 sites: 249 stations are
co-located.

*Reproduce:* `test_g4_exact_coordinate_duplicates_exist_in_the_snapshot`,
`test_g4_site_ids_come_from_clustering_not_coordinate_rounding`.

## G5 — IEA scenarios must never be summed

`category` has three values: `Historical`, `Projection-STEPS`, `Projection-APS`. STEPS
and APS are **alternative scenarios**. Summing them double counts: USA EV sales for
2035 come to 25,559,900, which exceeds total annual US light vehicle sales and is not
a real figure. Any query touching IEA projections must filter `category` explicitly.

*Reproduce:* `test_g5_iea_category_has_three_values_and_summing_scenarios_double_counts`.

## G6 — IEA USA projection years are 2025, 2030, 2035 only

Forward projection years are exactly `{2025, 2030, 2035}`. **2026–2029 and 2031–2034
are absent.** Do not interpolate silently.

> **Precision note added in Phase 1.** Both `Projection-` categories *also* restate the
> 2020–2023 historical baseline years inside each scenario, so the set of years
> appearing under a `Projection-` category is `{2020, 2021, 2022, 2023, 2025, 2030,
> 2035}`. "Projection years" means years beyond the last historical year (2023). Every
> projected parameter shares the same year grid.

*Reproduce:* `test_g6_iea_usa_projection_years_are_only_2025_2030_2035`.

## G7 — IEA mode has four vehicle values

`Cars`, `Buses`, `Trucks`, `Vans`. Stacking all four is valid only when the intent is
total fleet.

> **Precision note added in Phase 1.** The file carries a **fifth** `mode` value, `EV`,
> which is not a vehicle class. It appears only on `EV charging points` rows, where
> `powertrain` holds "Publicly available fast" or "Publicly available slow". Stacking
> it with the vehicle modes would be meaningless. The four vehicle modes hold for
> `EV sales` and `EV stock`, which is the rule's actual subject.

*Reproduce:* `test_g7_iea_mode_has_four_vehicle_values`.

## G8 — Registration counts are stock, never sales; exclude the total row

State registration counts are **stock**, not sales, and must never be labelled "EV
sales". The published total row must be excluded before any aggregation. AFDC labels it
`United States`; the delivered seed file labels it `Total`.

```
seed file: 51 jurisdictions sum to 3,555,445, which equals the Total row exactly
live pages: 520 raw rows across 10 vintages -> 510 after removing 10 total rows
```

**Where the removal happens matters.** Per amendment A15, retrieval and staging
preserve source rows: the adapter ingests the total row unchanged, and
`int_state_totals.sql` removes it in the intermediate layer, where it is visible and
testable. The `mart_state_totals` pandera schema then rejects any total row that
survives, as a last line of defence.

*Reproduce:* `test_g8_total_rows_never_reach_the_mart`,
`test_g8_counts_are_labelled_stock_never_sales`.

## G9 — State registration vintage and plausibility validation *(corrected)*

Each ingested state-registration dataset must resolve to a documented vintage,
jurisdiction coverage must be complete for the claimed geography, counts must be
non-negative, and jurisdiction totals must reconcile to the published total where one
exists. The delivered seed file resolves consistently to the 2023 AFDC vintage across
all 51 jurisdictions. Per-capita and year-over-year anomaly screening must be run as a
diagnostic quality check, but an anomalous state is **flagged for review rather than
automatically marked low-confidence**. A low-confidence designation requires
corroborating evidence of a vintage, coverage, definition, or source-quality problem.

**Why the original was wrong.** It asserted that the file mixes reporting vintages
across states, and that Oregon reports 6,436, below Kansas at 11,271 and Iowa at 9,031.
The delivered file records **Oregon at 64,361** — the stated figure looks like a
truncation — and rounding every value half-up to the nearest 100 reproduces the AFDC
**2023** vintage for **51 of 51** jurisdictions (and 0 of 51 for 2022 or 2024). The
file is one internally consistent vintage.

**Why an outlier is not a defect.** A state's genuine EV adoption rate can differ
sharply from its neighbours because of income, state incentives, urbanisation, housing
structure, vehicle preferences, climate, charging policy, electricity prices, commute
patterns, or local market maturity. An outlier is a **diagnostic requiring
investigation**, never proof of a defective source. Automatically downgrading it would
push a fabricated quality signal into the §7.4 uncertainty model.

Seven testable properties: vintage resolved; coverage present; counts non-negative;
published total reconciles; anomaly screening executes; anomalies surface as diagnostic
review flags; **a low-confidence label cannot be assigned solely because a value is
statistically or geographically unusual**.

*Reproduce:* `test_g9_property_1` through `test_g9_property_7_*`.

## G10 — Open Date is approximate

`Open Date` ranges 1995 to the snapshot date, and 455 records have none. AFDC documents
that some dates are approximate and, for automated network feeds, may reflect first
appearance in the Station Locator rather than actual opening.

*Reproduce:* `test_g10_open_dates_span_1995_to_the_snapshot_and_some_are_absent`.

## G11 — A snapshot plus Open Date cannot reconstruct a historical network

Stations that closed, were removed from the feed, changed port counts, or were
power-upgraded are invisible. A backwards reconstruction is monotonically
non-increasing **by construction**: it can only lose stations going back in time, never
gain them. That is the survivorship bias, and it grows with age. Any such output must
be labelled an **approximate reconstruction** everywhere it appears.

*Reproduce:* `test_g11_a_snapshot_plus_open_date_cannot_reconstruct_a_historical_network`.

## G12 — Never load the transmission GeoJSON whole

144,115,564 bytes (137 MiB), 94,216 features. It must be filtered by voltage and tiled.
It is never parsed as a single object anywhere in the pipeline — a streaming reader
decodes one `"properties"` object at a time — and never loaded as GeoJSON in a browser.

A source-scanning test asserts that no line naming the file also calls `json.load`,
`read_text`, `read_bytes`, `geopandas`, or `pyogrio.read`.

*Reproduce:* `test_g12_the_transmission_geojson_is_never_parsed_as_one_object`,
`test_g12_no_code_path_parses_the_transmission_file_whole`.

## G13 — County names collide across states; join on FIPS

Both Minnesota and Illinois have a Cook County — and so does Georgia.

```
MN Cook County  27031
IL Cook County  17031
GA Cook County  13075
```

Note that Minnesota and Illinois share county code **031**; only the state prefix
separates them, so even a bare county code collides. The lookup is keyed by
`(state, county name)` and `resolve_county_fips` **raises rather than guessing**.

The Illinois monthly panel additionally carries trailing columns `Chicago`,
`Unknown County` and `Total Count` which are not counties and must be excluded from any
county aggregation.

*Reproduce:* `test_g13_county_names_collide_across_states_so_joins_must_use_fips`.

## G14 — EV Connector Types is a concatenated string

In the bulk CSV, `EV Connector Types` is a **space-delimited concatenated string**, not
a normalised field. It must be split, never substring-matched: matching `"J1772"` as a
substring also matches `"J1772COMBO"`.

> **Second encoding found in Phase 1.** The JSON API returns the same field as a proper
> array, which the adapter re-serialises to JSON text. Both encodings reach the
> intermediate layer and **both are decoded explicitly**; a leading `[` identifies the
> JSON form. An early implementation split on spaces unconditionally, so a
> two-connector station decoded to a single-element list containing the literal string
> `["CHADEMO","J1772"]`. The G14 regression test caught it before any artifact shipped.

*Reproduce:* `test_g14_connector_types_is_a_space_delimited_string_not_a_normalised_field`,
`test_g14_the_pipeline_splits_rather_than_substring_matches`.
