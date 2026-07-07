# Wind and Interconnector Correlation Pack

## Scope and conventions

- Requested interconnector window: 2021-07-01 00:00:00+00:00 to 2026-06-30 22:30:00+00:00.
- Actual overlapping wind/interconnector window used in correlations: 2021-07-01 00:00:00+00:00 to 2025-12-31 23:30:00+00:00.
- Wind actual output is the BMU `metered` series converted from half-hour MWh to average MW.
- Wind before curtailment uses `metered - BAV`, matching the previous `metered_minus_bav` workflow.
- Wind `halfHourEndTime` is shifted back 30 minutes before joining to interconnector `startTime`.
- Positive interconnector signed MW means GB import; negative means GB export.
- A negative correlation with signed MW means higher wind tends to coincide with more export or less import.

## Fleet headline

- Daily fleet correlation with actual wind output: r=-0.12 using 1644 daily observations.
- Daily fleet correlation with pre-curtailment wind proxy: r=-0.13 using 1644 daily observations.
- In the lowest pre-curtailment wind quintile, fleet position averaged 2,911 MW with import share 82.2%.
- In the highest pre-curtailment wind quintile, fleet position averaged 1,422 MW with export share 32.7%.
- High-wind fleet position is -1,489 MW lower than low-wind position on the signed import-positive scale.
- Strongest tested fleet lag correlation is at 0.0 hours (r=-0.18); positive lag means wind leads interconnector position.

## Interconnector differences

Links most export-aligned with high pre-curtailment wind on a daily signed-MW basis:
- INTNSL: r=-0.20, mean signed 840 MW.
- INTNEM: r=-0.16, mean signed 330 MW.
- INTFR: r=-0.15, mean signed 666 MW.

Links most import-aligned with high pre-curtailment wind on a daily signed-MW basis:
- INTGRNL: r=+0.35, mean signed -349 MW.
- INTIRL: r=+0.17, mean signed -174 MW.
- INTEW: r=+0.10, mean signed -144 MW.

## Seasonal signal

- Winter: daily fleet signed-MW correlation with pre-curtailment wind is r=-0.10 across 392 observations.
- Spring: daily fleet signed-MW correlation with pre-curtailment wind is r=-0.11 across 368 observations.
- Summer: daily fleet signed-MW correlation with pre-curtailment wind is r=-0.24 across 429 observations.
- Autumn: daily fleet signed-MW correlation with pre-curtailment wind is r=-0.15 across 455 observations.

## Recommended exhibits

- `figures/fleet_daily_wind_and_interconnector_position.html` - time-series context for wind and fleet BM position.
- `figures/fleet_daily_scatter_wind_actual_mw.html` and `figures/fleet_daily_scatter_wind_before_curtailment_mw.html` - direct daily relationship against each wind metric.
- `figures/daily_signed_correlation_heatmap.html` - interconnector-by-interconnector comparison of daily signed-MW correlations.
- `figures/position_by_before_curtailment_wind_bucket.html` - how each link behaves from low-wind to high-wind conditions.

## Output tables

- `wind_half_hourly_timeseries.csv` - aggregate wind actual and before-curtailment proxy in MWh and MW.
- `interconnector_wind_join_half_hourly_long.csv` - joined half-hourly data by interconnector and fleet.
- `interconnector_wind_join_half_hourly_wide.csv` - one row per timestamp with wind and signed-MW columns.
- `interconnector_wind_join_daily.csv` and `interconnector_wind_join_monthly.csv` - daily/monthly analysis tables.
- `correlation_summary.csv` - half-hourly, daily, and monthly correlations for actual and before-curtailment wind.
- `correlation_by_season.csv` and `correlation_by_month_of_year.csv` - daily correlations by seasonal slices.
- `wind_level_bucket_summary.csv` - import/export levels and shares by wind quintile.
- `lag_correlation_summary.csv` - tested lag correlations for signed-MW position.

## Coverage note

- Fleet daily rows available for the joined period: 1,644.
- The wind settlement input currently determines the end of the joined window. Refresh the wind BMU settlement folder to extend the analysis past that date.
