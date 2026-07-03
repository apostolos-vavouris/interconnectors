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

To export every HTML figure and per-interconnector subfigure to PNG for use in
PowerPoint, run:

```powershell
python export_figures_to_png.py --overwrite
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
- `capacity_reference.csv` - capacity basis used for `% capacity` metrics. If `interconnector_capacities.csv` is absent, this defaults to observed absolute peak MW in the analysis window.
- `interconnector_summary.csv` - duty cycle, MW levels, energy, switching, and near-zero metrics by link.
- `fleet_summary.csv` - aggregate GB interconnector BM position.
- `monthly_summary.csv` and `seasonal_summary.csv` - seasonal operating regimes.
- `season_overall_summary.csv`, `month_of_year_summary.csv`, and `season_month_summary.csv` - season and month-of-year climatology across the fleet and per interconnector.
- `rolling_windows.csv` - 7, 30, and 90 day rolling trend metrics.
- `weekly_seasonal_envelope.csv` - seasonal envelope by ISO week.
- `diurnal_profile_by_season.csv` - within-day profiles by season.
- `level_bucket_summary.csv` - share of time spent in import/export MW bands.
- `pct_capacity_bucket_summary.csv` - share of time spent in import/export utilisation bands.
- `interconnector_flow_correlation_matrix.csv` and `interconnector_flow_correlation_pairwise.csv` - signed-MW co-movement between links.
- `interconnector_direction_alignment_pairwise.csv` and `interconnector_conditional_direction_shares.csv` - whether links import/export together or offset each other.
- `figures/` - charts for the recommended exhibit pack. The script writes PNGs
  when `matplotlib` is available, otherwise it falls back to interactive Plotly
  HTML files.
- `figures/interconnectors/subfigures/` - separate modular charts for each
  interconnector, intended for one-slide-per-link presentation layouts.
