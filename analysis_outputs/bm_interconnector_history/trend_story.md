# GB Interconnector Five-Year Rolling Trend

Analysis window: 2021-07-01 to 2026-06-30. Positive MW means GB importing; negative MW means GB exporting.

Method: compare the first and last 90 valid days of each 30-day rolling daily mean, then cross-check with the linear slope across the rolling series. Fleet percentage metrics use active fleet capacity, i.e. only interconnectors with data in each settlement period.

Recommended visuals: `figures/fleet_rolling_trend_context.*`, `figures/fleet_annual_import_export_trend.*`, `figures/interconnector_trend_delta_by_link.*`, and `figures/interconnector_rolling_trend_small_multiples.*`.

## Fleet Readout

- Overall label: no clear directional trend.
- 30-day rolling mean position moved from 3,602 MW to 3,623 MW, a change of 20 MW.
- On an active-capacity basis, the same position moved from 43.4% to 25.2%, a change of -18.2 percentage points.
- Linear slope across the rolling series is 586 MW/year with R2 0.19.
- Import share moved by -12.2 percentage points; export share moved by 12.1 percentage points.
- Mean active fleet capacity across the window was 12,464 MW, with 8.6 links active on average.
- Interpretation: the endpoint comparison is broadly flat; the positive slope is mainly a consequence of the deep 2022 trough, so this is better read as volatile rather than a sustained import/export trend.

Annual fleet cross-check:

- 2021: mean 2,769 MW (31.2% of active capacity), import share 93.2%, export share 6.6%, active capacity 9,192 MW.
- 2022: mean -484 MW (-3.8% of active capacity), import share 42.8%, export share 57.1%, active capacity 10,893 MW.
- 2023: mean 2,667 MW (23.4% of active capacity), import share 81.1%, export share 18.9%, active capacity 11,412 MW.
- 2024: mean 3,791 MW (27.3% of active capacity), import share 90.9%, export share 9.1%, active capacity 13,880 MW.
- 2025: mean 3,327 MW (23.2% of active capacity), import share 88.1%, export share 11.8%, active capacity 14,357 MW.
- 2026: mean 3,146 MW (21.8% of active capacity), import share 82.4%, export share 17.6%, active capacity 14,398 MW.

## Link-Level Readout

- INTELEC (Eleclink (INTELEC)): more importing. 30-day mean moved 1,538 MW (-635 to 904 MW); import share delta 95.8 pp, export share delta -79.1 pp.
- INTNED (Netherlands(BritNed)): more exporting. 30-day mean moved -599 MW (801 to 202 MW); import share delta -38.3 pp, export share delta 32.9 pp.
- INTNEM (Belgium (Nemolink)): more exporting. 30-day mean moved -464 MW (850 to 386 MW); import share delta -24.2 pp, export share delta 26.2 pp.
- INTFR (France(IFA)): mixed or step-change pattern. 30-day mean moved -333 MW (1,515 to 1,183 MW); import share delta 7.8 pp, export share delta 2.4 pp.
- INTVKL (Denmark (Viking link)): more exporting. 30-day mean moved -254 MW (528 to 274 MW); import share delta -20.6 pp, export share delta 13.2 pp.
- INTIRL (Northern Ireland(Moyle)): more exporting. 30-day mean moved -55 MW (-207 to -262 MW); import share delta -7.7 pp, export share delta 3.6 pp.
- INTGRNL (Ireland (Greenlink)): more exporting. 30-day mean moved -55 MW (-302 to -357 MW); import share delta -4.0 pp, export share delta 4.2 pp.
- INTEW (Ireland(East-West)): no clear directional trend. 30-day mean moved 20 MW (-169 to -148 MW); import share delta -5.1 pp, export share delta -17.3 pp.
- INTNSL (North Sea Link (INTNSL)): no clear directional trend. 30-day mean moved 19 MW (631 to 650 MW); import share delta -19.5 pp, export share delta 19.7 pp.
- INTIFA2 (IFA2 (INTIFA2)): no clear directional trend. 30-day mean moved -15 MW (807 to 792 MW); import share delta -10.7 pp, export share delta 10.8 pp.

## How To Use This

- more exporting: 5 series.
- no clear directional trend: 4 series.
- more importing: 1 series.
- mixed or step-change pattern: 1 series.

Use `rolling_trend_summary.csv` for the compact evidence table and `annual_trend_summary.csv` for the year-by-year check. The fleet row is `TOTAL_GB_INTERCONNECTORS`.
