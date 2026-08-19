# Seed data manifest

These are the initial local files. They are a **starting point only**. Phase 0 verifies
every one of them against its live source and records the findings in `SOURCES.yml`. Do not
treat any property described here as verified until Phase 0 confirms it.

All row counts below were measured on the files as delivered.

| File | Rows | Description | Known issues (see CLAUDE.md section 5) |
|---|---|---|---|
| `alt_fuel_stations__Dec_11_2024_.csv` | 79,618 data rows, 75 columns | AFDC national alternative fuel stations snapshot, 11 Dec 2024. All rows are `Fuel Type Code = ELEC`. | G1, G2, G3, G4, G10, G11, G14 |
| `alt_fuel_stations__Dec_10_2024_.csv` | 985 data rows | Minnesota-scoped AFDC extract, 10 Dec 2024. Same schema as the national file. | Same as above |
| `EV_Registration_Counts_by_State.csv` | 52 data rows | State-level EV registration counts. Includes a `Total` row that must be excluded. Undated. | G8, G9 |
| `County_EV_Registrations_Summary.csv` | 87 data rows | Minnesota county EV registrations. Single point in time. Contains blank values. | G13 |
| `county_ev_counts.csv` | 84 rows x 106 columns | **Illinois monthly county panel, 2017-11 to 2024-11.** Wide format, one column per county. Trailing columns include `Chicago`, `Unknown County`, `Total Count` which are not counties. | G13 |
| `IL_StationsData.csv` | 1,626 data rows | Illinois charging stations, reduced column set. | G2 |
| `Simplified_EV_Charging_Stations.csv` | 985 data rows | Minnesota charging stations, six columns only. | Overlaps the Dec 10 file |
| `IEA_Global_EV_Data_2024.csv` | 12,654 data rows | IEA global EV data. 54 regions. `category` has three values: `Historical`, `Projection-STEPS`, `Projection-APS`. | **G5, G6, G7 — critical** |
| `ev_launch_data.csv` | 90 data rows | EV model specifications with launch year. Currency fields are strings with `$` and commas. | Parsing only |
| `Electric__Power_Transmission_Lines.geojson` | 94,216 features, ~138 MB | HIFLD transmission lines. Properties include `VOLTAGE`, `VOLT_CLASS`, `OWNER`, `STATUS`. Geometry is MultiLineString. | **G12 — never load as GeoJSON in a browser** |

## Measured properties of the national AFDC file

Verified directly. Use these as expected-range anchors in `SOURCES.yml`, and re-verify
against the live API in Phase 0.

```
Total station records:            79,618
Status Code = E  (available):     73,972
Status Code = T  (temp. unavail): 5,217
Status Code = P  (planned):       429
Access Code = public:             74,956
Access Code = private:            4,662

Port totals (sum of the three count columns, nulls treated as zero):
  EV Level1 EVSE Num:               3,018
  EV Level2 EVSE Num:             173,892
  EV DC Fast Count:                51,752
  Total ports:                    228,662

Exact duplicate (Latitude, Longitude) rows:  1,756
Rows with null Open Date:                      455
Open Date range:                    1995-08-30 to 2024-12-11
EV Pricing populated:                        19.5%
EV Connector Types null:                        45

Top networks: ChargePoint 40,415 | Non-Networked 9,635 | Blink 7,338 |
              Tesla Destination 4,955 | Shell Recharge 2,713 | Tesla 2,491
```

Note the ratio that matters: **79,618 station records represent 228,662 ports.** Counting
records as capacity understates supply by roughly a factor of three, unevenly across states.

## Measured property of the IEA file (the trap)

USA `EV sales` rows summed by category, projection years only:

```
Projection-APS    2025    3,281,740
                  2030    9,696,900
                  2035   12,917,200
Projection-STEPS  2025    3,223,680
                  2030    9,543,500
                  2035   12,642,700
```

STEPS and APS are **alternative scenarios**. Summing them yields 25,559,900 for 2035, which
exceeds total annual US light vehicle sales and is not a real figure. Any query touching IEA
projections must filter `category` explicitly. Projection years present are only 2025, 2030,
and 2035.

## A note on the state registration file

Oregon reports 6,436, which falls below Kansas (11,271), Iowa (9,031), and Maine (7,377).
That ordering is implausible and indicates inconsistent reporting vintages across states.
Phase 0 should attempt to establish the vintage of each state's figure. Flag low-confidence
states in the data rather than silently using the numbers.

---

## Correction — 2026-08-19 (Phase 0)

*Appended, not edited. The original text above is preserved as delivered.*

The closing section "A note on the state registration file" is factually wrong about
`EV_Registration_Counts_by_State.csv` and has been superseded.

**It states:** "Oregon reports 6,436, which falls below Kansas (11,271), Iowa (9,031), and
Maine (7,377). That ordering is implausible and indicates inconsistent reporting vintages
across states."

**The delivered file records:** Oregon **64,361**, Kansas 11,271, Iowa 9,031, Maine 7,377,
Total 3,555,445 (which equals the sum of the 51 jurisdiction rows exactly). File SHA-256
`4c72eeace1defeddf7dddeaedf4f65ffff970b4c2ce8090184fd6408076bb7ad`.

Oregon is 64,361, not 6,436; the stated figure appears to be a truncation. At 64,361 the
ordering is unremarkable.

**The general claim also fails.** Phase 0 dated the file: rounding every value half-up to the
nearest 100 reproduces the AFDC 2023 vintage for **51 of 51** jurisdictions, and 0 of 51 for
either 2022 or 2024. The file is one internally consistent vintage, not a mixture.

Domain rule G9 was rewritten as a result. See `docs/reports/PLAN_CHANGE_0.md` §8 and
`CLAUDE.md` §19 A1.

**One further discrepancy:** the table above states `ev_launch_data.csv` has 90 data rows; it
parses to **91**.
