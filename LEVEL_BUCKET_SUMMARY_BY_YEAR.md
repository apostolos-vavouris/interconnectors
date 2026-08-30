# Year-Specific Level Bucket Summaries

Use this when you want a `level_bucket_summary.csv` equivalent for one calendar
year only, for example `level_bucket_summary_2025_operational.csv`.

The method uses the existing `analyse_bm_interconnector_history.py` script and
filters the analysis window to the selected year. Interconnectors contribute
only where operational half-hourly rows exist in `HH_data`.

## One-Year Command

Run from the `interconnectors` repo:

```powershell
cd C:\Users\Work\Documents\GitHub\interconnectors

$Year = 2025
$Start = "{0}-01-01T00:00Z" -f $Year
$End = "{0}-12-31T23:30Z" -f $Year
$TempOut = Join-Path $env:TEMP "bm_interconnector_history_${Year}_operational"
$Destination = ".\analysis_outputs\bm_interconnector_history\level_bucket_summary_${Year}_operational.csv"

..\elexon-iris\.venv\Scripts\python.exe .\analyse_bm_interconnector_history.py --start $Start --end $End --output-dir $TempOut --no-charts
Copy-Item -LiteralPath (Join-Path $TempOut "level_bucket_summary.csv") -Destination $Destination -Force
```

Change only `$Year` to regenerate another year, such as `2024`, `2023`, or
`2022`.

## Example For 2024

```powershell
cd C:\Users\Work\Documents\GitHub\interconnectors

$Year = 2024
$Start = "{0}-01-01T00:00Z" -f $Year
$End = "{0}-12-31T23:30Z" -f $Year
$TempOut = Join-Path $env:TEMP "bm_interconnector_history_${Year}_operational"
$Destination = ".\analysis_outputs\bm_interconnector_history\level_bucket_summary_${Year}_operational.csv"

..\elexon-iris\.venv\Scripts\python.exe .\analyse_bm_interconnector_history.py --start $Start --end $End --output-dir $TempOut --no-charts
Copy-Item -LiteralPath (Join-Path $TempOut "level_bucket_summary.csv") -Destination $Destination -Force
```

The final file will be:

```text
analysis_outputs/bm_interconnector_history/level_bucket_summary_2024_operational.csv
```

## Validation Checks

Check the row count:

```powershell
(Import-Csv -LiteralPath $Destination).Count
```

Check the included interconnectors:

```powershell
Import-Csv -LiteralPath $Destination |
    Group-Object interconnectorId |
    Select-Object Name,Count |
    Format-Table -AutoSize
```

Each interconnector included should normally have `11` rows, one for each MW
flow band.

Check the operational date coverage from the temporary run:

```powershell
Import-Csv -LiteralPath (Join-Path $TempOut "interconnector_summary.csv") |
    Select-Object interconnectorId,first_timestamp,last_timestamp,observations,coverage_pct_between_first_last |
    Format-Table -AutoSize
```

## Notes

- Keep `--no-charts` when you only need the CSV.
- The temporary output folder can be deleted afterwards.
- Do not set `--output-dir` to `analysis_outputs/bm_interconnector_history`
  for this task unless you intend to overwrite the main five-year analysis pack.
- The output schema is the same as `level_bucket_summary.csv`:
  `interconnectorId`, `interconnectorName`, `flow_band_mw`, `observations`,
  `duration_hours`, and `duration_share_pct`.
