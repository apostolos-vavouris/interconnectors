# All Available Data Import/Export Level Distribution Percentiles

The run covers all available half-hourly data from 2021-01-01 00:00:00+00:00 to 2026-06-30 22:30:00+00:00.

Percentiles are calculated separately for import and export operating periods. That means import P10/P50/P90 use only half-hours where the series is importing, while export P10/P50/P90 use only half-hours where the series is exporting. Exports are shown as positive MW magnitudes.

## Fleet Readout

- Importing half-hours: 76,832 (79.8% of operational periods).
- Exporting half-hours: 19,444 (20.2% of operational periods).
- Near-zero half-hours: 24 (0.0% of operational periods).
- Fleet import distribution: P10 1,054 MW, P50 3,658 MW, P90 6,266 MW.
- Fleet export distribution: P10 316 MW, P50 1,904 MW, P90 4,458 MW.

For minimum operating-limit style figures, the low directional percentiles (especially P5, P10, and P20) are usually more useful than P0 because P0 is the single smallest non-near-zero half-hour after the deadband filter.

## Largest Median Directional Levels

### Import

| Interconnector | Direction half-hours | Direction share | P10 MW | P50 MW | P90 MW |
|---|---:|---:|---:|---:|---:|
| TOTAL_GB_INTERCONNECTORS | 76,832 | 79.8% | 1,054 | 3,658 | 6,266 |
| INTFR | 71,786 | 74.5% | 438 | 1,354 | 2,002 |
| INTNSL | 68,260 | 82.1% | 546 | 1,298 | 1,398 |
| INTELEC | 49,009 | 68.2% | 296 | 996 | 998 |
| INTVKL | 26,921 | 61.4% | 254 | 976 | 1,422 |

### Export

| Interconnector | Direction half-hours | Direction share | P10 MW | P50 MW | P90 MW |
|---|---:|---:|---:|---:|---:|
| TOTAL_GB_INTERCONNECTORS | 19,444 | 20.2% | 316 | 1,904 | 4,458 |
| INTELEC | 14,038 | 19.5% | 80 | 804 | 1,024 |
| INTVKL | 13,868 | 31.6% | 144 | 750 | 1,094 |
| INTNED | 27,598 | 28.7% | 180 | 698 | 1,044 |
| INTFR | 21,302 | 22.1% | 90 | 678 | 1,032 |

## Outputs

- `import_export_level_percentiles_all_data.csv` - long-form percentile table.
- `import_export_level_percentiles_wide_all_data.csv` - one row per series and direction with P0-P100 columns.
- `import_export_level_pdf_bins_all_data.csv` - binned probability-density table used by the PDF-style plots.
- `import_export_direction_sample_summary_all_data.csv` - import/export/near-zero sample sizes and mean levels.
- `figures/import_level_percentile_distribution_all_data.html` - import distribution plot.
- `figures/export_level_percentile_distribution_all_data.html` - export distribution plot.
- `figures/interconnectors/pdf_distributions/*_level_pdf_distribution_all_data.html` - one probability-density distribution plot per interconnector and fleet total.
- `figures/interconnectors/cdf_distributions/*_level_cdf_distribution_all_data.html` - one cumulative distribution plot per interconnector and fleet total.
