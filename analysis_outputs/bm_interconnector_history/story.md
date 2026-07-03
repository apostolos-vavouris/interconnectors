# GB Interconnector BM Operating History

Analysis window: 2021-07-01 00:00 UTC to 2026-06-30 22:30 UTC.

Sign convention used in this pack:
- Positive raw `generation` is treated as GB import.
- Direction shares use a +/-1 MW deadband around zero.
- Positive `signed_mw` in the output tables means GB import; negative means GB export.
- `% capacity` metrics use `capacity_reference.csv`; by default this is the observed absolute peak MW in the analysis window unless a supplied capacity file is provided.

## Headline Story

Across the fleet, the BM interconnector position was importing for 78.1% of observed half-hours, exporting for 21.8%, and near zero for 0.1%. The mean net position was 2,452 MW, giving net energy of 107,458 GWh over the analysis window.

The clearest slide story is not just whether each link imported or exported, but how stable that operating mode was:
- Direction duty cycle: share of time importing, exporting, and near zero.
- Level distribution: time spent in MW bands, separately for import and export.
- Rolling regime: 30-day and 90-day rolling net MW and direction shares.
- Seasonality: monthly heatmap plus weekly seasonal envelope for expected import/export range.
- Operational intensity: direction switching, sustained high-flow shares, and long near-zero runs as an outage/low-use proxy.

## Seasonal and Monthly Shape

Fleet seasonal averages:
- Winter: mean 2,693 MW, 18.7% of fleet capacity, import share 81.7%, export share 18.2%.
- Spring: mean 3,187 MW, 22.1% of fleet capacity, import share 84.3%, export share 15.7%.
- Summer: mean 2,229 MW, 15.5% of fleet capacity, import share 73.7%, export share 26.2%.
- Autumn: mean 1,695 MW, 11.8% of fleet capacity, import share 72.9%, export share 27.0%.

The strongest fleet import month-of-year is Mar at 4,023 MW (27.9% capacity) on average. The weakest or most export-leaning month-of-year is Sep at 1,566 MW (10.9% capacity).

Links with the largest month-of-year swing in mean signed % capacity:
- Eleclink (INTELEC) (INTELEC): 52.7 percentage-point range (664 MW) between its lowest and highest month-of-year averages.
- IFA2 (INTIFA2) (INTIFA2): 33.3 percentage-point range (542 MW) between its lowest and highest month-of-year averages.
- Ireland (Greenlink) (INTGRNL): 33.3 percentage-point range (173 MW) between its lowest and highest month-of-year averages.

## Links Driving Net Imports

- North Sea Link (INTNSL) (INTNSL): net 33,185 GWh, importing 82.1% of half-hours; mean import level when importing 1,094 MW.
- France(IFA) (INTFR): net 31,407 GWh, importing 72.6% of half-hours; mean import level when importing 1,203 MW.
- Eleclink (INTELEC) (INTELEC): net 15,435 GWh, importing 68.2% of half-hours; mean import level when importing 816 MW.

## Links Driving Net Exports

- Northern Ireland(Moyle) (INTIRL): net -7,970 GWh, exporting 69.5% of half-hours; mean export level when exporting 338 MW.
- Ireland(East-West) (INTEW): net -6,470 GWh, exporting 52.8% of half-hours; mean export level when exporting 353 MW.
- Ireland (Greenlink) (INTGRNL): net -4,196 GWh, exporting 82.9% of half-hours; mean export level when exporting 443 MW.

## Most Directionally Dynamic Links

- Belgium (Nemolink) (INTNEM): 68.2 import/export switches per 30 days, with 2.4% near-zero operation.
- Netherlands(BritNed) (INTNED): 65.0 import/export switches per 30 days, with 9.4% near-zero operation.
- Denmark (Viking link) (INTVKL): 60.1 import/export switches per 30 days, with 7.0% near-zero operation.

## Interconnector Coordination

Strongest positive signed-MW co-movement:
- INTELEC and INTIFA2: Pearson correlation 0.77 over 71,898 common half-hours.
- INTELEC and INTFR: Pearson correlation 0.75 over 71,898 common half-hours.
- INTFR and INTIFA2: Pearson correlation 0.75 over 87,614 common half-hours.

Strongest offsetting signed-MW relationships:
- INTFR and INTIRL: Pearson correlation -0.41 over 87,614 common half-hours.
- INTELEC and INTIRL: Pearson correlation -0.39 over 71,898 common half-hours.
- INTIFA2 and INTIRL: Pearson correlation -0.38 over 87,614 common half-hours.

Highest same-direction operating shares:
- INTGRNL and INTIRL: same direction 82.1%, opposite direction 2.9%.
- INTELEC and INTFR: same direction 79.8%, opposite direction 6.1%.
- INTFR and INTIFA2: same direction 79.2%, opposite direction 17.0%.

Highest opposite-direction operating shares:
- INTFR and INTGRNL: opposite direction 81.3%, same direction 15.7%.
- INTELEC and INTGRNL: opposite direction 77.0%, same direction 13.8%.
- INTGRNL and INTIFA2: opposite direction 73.4%, same direction 23.6%.

## Highest Near-Zero Shares

- Ireland(East-West) (INTEW): near zero for 30.3%; longest near-zero run 1,087.0 hours.
- Eleclink (INTELEC) (INTELEC): near zero for 12.3%; longest near-zero run 2,263.0 hours.
- Netherlands(BritNed) (INTNED): near zero for 9.4%; longest near-zero run 127.0 hours.

## Latest Month Snapshot (2026-06)

- GB interconnector fleet total (TOTAL_GB_INTERCONNECTORS): mean 3,165 MW, import share 81.8%, export share 18.0%.
- France(IFA) (INTFR): mean 1,252 MW, import share 96.6%, export share 3.3%.
- North Sea Link (INTNSL) (INTNSL): mean 950 MW, import share 91.5%, export share 8.2%.
- Eleclink (INTELEC) (INTELEC): mean 816 MW, import share 97.8%, export share 1.0%.
- IFA2 (INTIFA2) (INTIFA2): mean 463 MW, import share 59.6%, export share 40.4%.
- Netherlands(BritNed) (INTNED): mean 143 MW, import share 57.0%, export share 40.3%.
- Belgium (Nemolink) (INTNEM): mean 106 MW, import share 59.4%, export share 40.3%.
- Denmark (Viking link) (INTVKL): mean 95 MW, import share 51.9%, export share 48.1%.
- Northern Ireland(Moyle) (INTIRL): mean -204 MW, import share 12.6%, export share 65.4%.
- Ireland(East-West) (INTEW): mean -210 MW, import share 6.5%, export share 59.6%.
- Ireland (Greenlink) (INTGRNL): mean -247 MW, import share 6.9%, export share 59.8%.

## Suggested Exhibit Pack

1. `figures/direction_share_by_interconnector.*` - simple answer to how often each link imported, exported, or sat near zero.
2. `figures/net_energy_by_interconnector.*` - which links have been net importers/exporters over the period.
3. `figures/monthly_mean_signed_mw_heatmap.*` - regime changes and seasonality by link.
4. `figures/fleet_rolling_net_mw.*` - whether the total GB interconnector BM position was tightening or relaxing.
5. `figures/fleet_weekly_seasonal_envelope.*` - expected seasonal range across the five-year history.
6. `figures/fleet_diurnal_by_season.*` - whether operation changes materially within day and season.
7. `figures/flow_correlation_heatmap.*` and `figures/direction_alignment_heatmap.*` - whether links tend to move together or offset each other.
8. `figures/fleet_month_of_year_profile.*`, `figures/month_of_year_mean_heatmap.*`, and `figures/season_direction_share_by_interconnector.*` - seasonal/month shape across the fleet and each link.
9. `figures/month_of_year_pct_capacity_heatmap.*`, `figures/season_pct_capacity_heatmap.*`, and `figures/pct_capacity_bands_by_interconnector.*` - capacity-normalised comparative views.
10. `figures/interconnectors/*_operating_profile.*` - one profile per interconnector for appendix or drill-down.

## Tables Written

- `interconnector_summary.csv`
- `fleet_summary.csv`
- `capacity_reference.csv`
- `monthly_summary.csv`
- `seasonal_summary.csv`
- `season_overall_summary.csv`
- `month_of_year_summary.csv`
- `season_month_summary.csv`
- `daily_timeseries.csv`
- `rolling_windows.csv`
- `weekly_seasonal_envelope.csv`
- `diurnal_profile_by_season.csv`
- `level_bucket_summary.csv`
- `pct_capacity_bucket_summary.csv`
- `interconnector_flow_correlation_matrix.csv`
- `interconnector_flow_correlation_pairwise.csv`
- `interconnector_direction_alignment_pairwise.csv`
- `interconnector_conditional_direction_shares.csv`
- `fleet_half_hourly_timeseries.csv`

Caveat: this pack uses the observed BM half-hourly `generation` values and an explicit sign assumption. If the source uses the opposite sign convention for interconnectors, rerun with `--positive-direction export` and the import/export labels will flip.
