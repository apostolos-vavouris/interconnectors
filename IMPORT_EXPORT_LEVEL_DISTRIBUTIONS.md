# Import/Export Level Distribution Runs

Use this when you want import and export operating-level percentiles, PDFs, and
CDFs for each GB interconnector and for the aggregate fleet total.

The script calculates import and export levels independently:

- Import levels use only half-hours where the series is importing.
- Export levels use only half-hours where the series is exporting.
- Export levels are reported as positive MW magnitudes.
- `PDF` here means probability distribution function, not a PDF document.

## Run One Calendar Year

Run from the `interconnectors` repo:

```powershell
cd C:\Users\Work\Documents\GitHub\interconnectors

$Year = 2025
..\elexon-iris\.venv\Scripts\python.exe .\analyse_yearly_import_export_level_percentiles.py --year $Year
```

Change only `$Year` to run another year, for example `2024`, `2023`, or `2022`.

## Run All Available Data

Use `--all-data` instead of `--year`:

```powershell
cd C:\Users\Work\Documents\GitHub\interconnectors

..\elexon-iris\.venv\Scripts\python.exe .\analyse_yearly_import_export_level_percentiles.py --all-data
```

The all-data outputs use the suffix `all_data`, for example:

```text
analysis_outputs/import_export_level_distributions/import_export_level_percentiles_wide_all_data.csv
```

## Refresh PNG Figures

The analysis script writes interactive HTML figures. To create or refresh PNGs
for PowerPoint, run:

```powershell
..\elexon-iris\.venv\Scripts\python.exe .\export_figures_to_png.py --figures-dir .\analysis_outputs\import_export_level_distributions\figures --overwrite
```

This exports every HTML figure under the distribution figures folder, including
year-specific and all-data plots if both have been generated.

## Useful Options

Use a smaller MW bin width for more granular PDF and CDF plots:

```powershell
..\elexon-iris\.venv\Scripts\python.exe .\analyse_yearly_import_export_level_percentiles.py --year 2025 --pdf-bin-width-mw 50
```

Skip figure generation when you only need CSVs:

```powershell
..\elexon-iris\.venv\Scripts\python.exe .\analyse_yearly_import_export_level_percentiles.py --year 2025 --no-figures
```

If the raw data sign convention is confirmed to be the opposite of the default,
rerun with:

```powershell
..\elexon-iris\.venv\Scripts\python.exe .\analyse_yearly_import_export_level_percentiles.py --year 2025 --positive-direction export
```

By default the PDF-style plots are one chart per interconnector. To also create
the old all-interconnector PDF overlays, add:

```powershell
--include-combined-pdf-figures
```

## Outputs

All outputs are written to:

```text
analysis_outputs/import_export_level_distributions/
```

For a selected period suffix such as `2025` or `all_data`, the key CSVs are:

- `import_export_level_percentiles_<period>.csv` - long-form percentile table.
- `import_export_level_percentiles_wide_<period>.csv` - one row per interconnector or fleet total and direction, with P0, P5, P10, P20, P30, P40, P50, P60, P70, P75, P85, P90, P95, and P100 columns.
- `import_export_level_pdf_bins_<period>.csv` - binned probability table behind the PDF and CDF plots.
- `import_export_direction_sample_summary_<period>.csv` - import, export, and near-zero sample sizes and mean levels.
- `import_export_level_distribution_story_<period>.md` - compact readout for the selected period.
- `run_config_<period>.csv` - run settings and effective data window.

The key figure folders are:

- `figures/interconnectors/pdf_distributions/` - one PDF-style import/export distribution plot per interconnector and one for the aggregate fleet total.
- `figures/interconnectors/cdf_distributions/` - one import/export cumulative distribution plot per interconnector and one for the aggregate fleet total.
- `figures/import_level_percentile_distribution_<period>.*` and `figures/export_level_percentile_distribution_<period>.*` - percentile curves across the fleet and individual interconnectors.

## Validation Checks

Check the number of rows in the wide percentile table:

```powershell
$Period = "2025"      # or "all_data"
(Import-Csv -LiteralPath ".\analysis_outputs\import_export_level_distributions\import_export_level_percentiles_wide_${Period}.csv").Count
```

For a full year with 10 interconnectors plus the fleet total, this should
normally be `22`: 11 series times 2 directions.

Check the generated per-interconnector CDF PNGs:

```powershell
$Period = "2025"      # or "all_data"
(Get-ChildItem -LiteralPath .\analysis_outputs\import_export_level_distributions\figures\interconnectors\cdf_distributions -Filter "*_${Period}.png").Count
```

For the same 10 interconnectors plus the fleet total, this should normally be
`11`.
