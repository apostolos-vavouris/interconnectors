# GB Interconnector BM History

This repository contains half-hourly BM data for GB interconnectors in `HH_data`.

Run the analysis pack with:

```powershell
python analyse_bm_interconnector_history.py
```

If this machine does not have `python` on PATH, use any environment with
`pandas` and either `plotly` or `matplotlib`, for example:

```powershell
..\elexon-iris\.venv\Scripts\python.exe .\analyse_bm_interconnector_history.py
```

The script writes tables, figures, and a generated narrative to:

```text
analysis_outputs/bm_interconnector_history/
```

For one-calendar-year versions of `level_bucket_summary.csv`, such as
`level_bucket_summary_2025_operational.csv`, use the commands in
[`LEVEL_BUCKET_SUMMARY_BY_YEAR.md`](LEVEL_BUCKET_SUMMARY_BY_YEAR.md).

To calculate one-calendar-year import/export operating-level percentiles for
each interconnector and the aggregate fleet, run:

```powershell
..\elexon-iris\.venv\Scripts\python.exe .\analyse_yearly_import_export_level_percentiles.py --year 2025
```

Change `--year 2025` to the year you want. Outputs are written to:

```text
analysis_outputs/import_export_level_distributions/
```

To run the same percentile, PDF-style distribution, and CDF analysis across all
available half-hourly data, run:

```powershell
..\elexon-iris\.venv\Scripts\python.exe .\analyse_yearly_import_export_level_percentiles.py --all-data
```

For the full runbook, including PNG export and validation checks, see
[`IMPORT_EXPORT_LEVEL_DISTRIBUTIONS.md`](IMPORT_EXPORT_LEVEL_DISTRIBUTIONS.md).

To export every HTML figure and per-interconnector subfigure to PNG for use in
PowerPoint, run:

```powershell
python export_figures_to_png.py --overwrite
```

To correlate aggregate GB wind BMU output with interconnector operation, run:

```powershell
..\elexon-iris\.venv\Scripts\python.exe .\analyse_wind_interconnector_correlation.py
```

This uses `..\elexon-iris\wind_bmu_best_settlement_timeseries`, treats
`metered` as actual wind output, and treats `metered - BAV` as the
pre-curtailment proxy used in the previous wind workflow. Outputs are written
to:

```text
analysis_outputs/wind_interconnector_correlation/
```

To analyse whether GB-vs-bidding-zone price spreads explain interconnector
flows, run:

```powershell
..\elexon-iris\.venv\Scripts\python.exe .\analyse_price_spread_interconnector_correlation.py
```

This joins `bidding_zones_electricity_markets_prices.csv` to the half-hourly
interconnector flows and defines the spread as `GB price - bidding-zone price`.
Outputs are written to:

```text
analysis_outputs/price_spread_interconnector_correlation/
```

To export those wind-correlation HTML figures to PNG, run:

```powershell
..\elexon-iris\.venv\Scripts\python.exe .\export_figures_to_png.py --figures-dir .\analysis_outputs\wind_interconnector_correlation\figures --overwrite
```

By default it uses the latest five-year window available in the CSVs and treats
positive raw `generation` as GB import. If the source convention is confirmed to
be the opposite, rerun with:

```powershell
python analyse_bm_interconnector_history.py --positive-direction export
```

Key outputs:

- `story.md` - generated client-facing narrative and exhibit pack.
- `presentation_outline.md` - slide-by-slide deck outline, including the fleet story and one slide per interconnector.
- `seasonal_interconnector_story.md` - per-interconnector seasonal narrative,
  highlighting strongest import/export seasons and month-of-year shape.
- `capacity_reference.csv` - capacity basis used for `% capacity` metrics. If `interconnector_capacities.csv` is absent, this defaults to observed absolute peak MW in the analysis window.
- `interconnector_summary.csv` - duty cycle, MW levels, energy, switching, and near-zero metrics by link.
- `fleet_summary.csv` - aggregate GB interconnector BM position.
- `direction_share_summary.csv` - import/export/near-zero counts and shares,
  plus mean signed/import/export MW, for each link and the aggregate fleet.
- `monthly_summary.csv` and `seasonal_summary.csv` - seasonal operating regimes.
- `season_overall_summary.csv`, `month_of_year_summary.csv`, and `season_month_summary.csv` - season and month-of-year climatology across the fleet and per interconnector.
- `rolling_windows.csv` - 7, 30, and 90 day rolling trend metrics.
- `rolling_trend_summary.csv` - compact five-year trend readout from the
  30-day rolling series, with import/export direction labels by link and fleet.
- `annual_trend_summary.csv` - year-by-year cross-check, including active
  capacity metrics for the aggregate fleet where not every interconnector was
  operating.
- `fleet_rolling_slope_comparison.csv` - fitted fleet rolling-net-MW slope
  including all data and excluding calendar-year 2022.
- `trend_story.md` - short narrative on whether the fleet and each link have
  shifted towards more imports, more exports, or no clear directional trend.
- `weekly_seasonal_envelope.csv` - seasonal envelope by ISO week.
- `diurnal_profile_by_season.csv` - within-day profiles by season.
- `level_bucket_summary.csv` - share of time spent in import/export MW bands.
- `fleet_level_bucket_summary.csv` - aggregate GB interconnector fleet counts,
  hours, and shares in the same MW import/export bands.
- `pct_capacity_bucket_summary.csv` - share of time spent in import/export utilisation bands.
- `interconnector_flow_correlation_matrix.csv` and `interconnector_flow_correlation_pairwise.csv` - signed-MW co-movement between links.
- `interconnector_direction_alignment_pairwise.csv` and `interconnector_conditional_direction_shares.csv` - whether links import/export together or offset each other.
- `figures/` - charts for the recommended exhibit pack. The script writes PNGs
  when `matplotlib` is available, otherwise it falls back to interactive Plotly
  HTML files.
- `figures/fleet_rolling_trend_context.*`, `figures/fleet_rolling_trend_sensitivity.*`, `figures/fleet_annual_import_export_trend.*`, `figures/interconnector_trend_delta_by_link.*`, and `figures/interconnector_rolling_trend_small_multiples.*` - trend illustrations for the five-year rolling readout.
- `figures/interconnectors/subfigures/` - separate modular charts for each
  interconnector, intended for one-slide-per-link presentation layouts.

Wind/interconnector correlation outputs:

- `story.md` - short narrative for the wind/interconnector relationship.
- `correlation_summary.csv` - half-hourly, daily, and monthly correlations
  against actual wind and pre-curtailment wind.
- `correlation_by_season.csv` and `correlation_by_month_of_year.csv` -
  seasonal and month-of-year correlation cuts.
- `wind_level_bucket_summary.csv` - import/export levels and direction shares
  across low-to-high wind quintiles.
- `wind_low_high_bucket_interconnector_comparison.csv` - low-wind versus
  high-wind comparison table for every interconnector and the aggregate fleet.
- `interconnector_wind_join_half_hourly_wide.csv` - joined wind and signed
  interconnector MW series for further analysis.

Price-spread/interconnector outputs:

- `story.md` - short narrative for the price-spread/flow relationship.
- `price_spread_correlation_summary.csv` - per-interconnector half-hourly
  spread-vs-flow correlation, regression slope, and directional alignment.
- `price_spread_correlation_by_frequency.csv` - half-hourly, daily, and monthly
  correlation cuts.
- `price_spread_band_summary.csv` - import/export levels and direction shares
  across fixed GB-minus-zone spread bands.
- `price_spread_quantile_summary.csv` - same relationship across link-specific
  spread deciles.
- `price_spread_direction_alignment_summary.csv` - whether flow direction
  aligns with, counters, or sits near zero against the price spread signal.
- `price_spread_lag_correlation_summary.csv` - lag sensitivity where positive
  lag means the spread leads the flow.
- `interconnector_price_spread_join_half_hourly.csv.gz` - joined flow and price
  spread data for further analysis.

Year-specific import/export level distribution outputs:

- `import_export_level_percentiles_<year>.csv` - long-form P0, P5, P10, P20, P30, P40, P50, P60, P70, P75, P85, P90, P95, and P100 levels.
- `import_export_level_percentiles_wide_<year>.csv` - one row per interconnector/fleet total and direction, with one column per percentile.
- `import_export_level_pdf_bins_<year>.csv` - binned probability-density table behind the PDF-style distribution plots.
- `import_export_direction_sample_summary_<year>.csv` - import, export, and near-zero sample sizes and mean levels used to interpret the distributions.
- `import_export_level_distribution_story_<year>.md` - compact readout for the selected year.
- `figures/import_level_percentile_distribution_<year>.*` and `figures/export_level_percentile_distribution_<year>.*` - distribution plots across the fleet and individual interconnectors. HTML is always written when figures are enabled; PNG is also written when the local plotting/image-export packages are available.
- `figures/interconnectors/pdf_distributions/*_level_pdf_distribution_<year>.*` - one PDF-style probability distribution plot per interconnector and one for the aggregate fleet total, with import and export distributions shown together.
- `figures/interconnectors/cdf_distributions/*_level_cdf_distribution_<year>.*` - one cumulative distribution plot per interconnector and one for the aggregate fleet total, with import and export CDFs shown together.
