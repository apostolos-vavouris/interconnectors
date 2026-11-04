# 2024 Import/Export Level Distribution Percentiles

The run covers the full 2024 calendar year.

Percentiles are calculated separately for import and export operating periods. That means import P10/P50/P90 use only half-hours where the series is importing, while export P10/P50/P90 use only half-hours where the series is exporting. Exports are shown as positive MW magnitudes.

## Fleet Readout

- Importing half-hours: 15,968 (90.9% of operational periods).
- Exporting half-hours: 1,600 (9.1% of operational periods).
- Near-zero half-hours: 0 (0.0% of operational periods).
- Fleet import distribution: P10 1,606 MW, P50 4,560 MW, P90 6,608 MW.
- Fleet export distribution: P10 228 MW, P50 1,330 MW, P90 3,889 MW.

For minimum operating-limit style figures, the low directional percentiles (especially P5, P10, and P20) are usually more useful than P0 because P0 is the single smallest non-near-zero half-hour after the deadband filter.

## Largest Median Directional Levels

### Import

| Interconnector | Direction half-hours | Direction share | P10 MW | P50 MW | P90 MW |
|---|---:|---:|---:|---:|---:|
| TOTAL_GB_INTERCONNECTORS | 15,968 | 90.9% | 1,606 | 4,560 | 6,608 |
| INTNSL | 15,936 | 90.7% | 698 | 1,398 | 1,400 |
| INTFR | 16,064 | 91.4% | 698 | 1,260 | 2,002 |
| INTELEC | 12,098 | 68.9% | 463 | 996 | 998 |
| INTIFA2 | 10,257 | 58.4% | 399 | 992 | 992 |

### Export

| Interconnector | Direction half-hours | Direction share | P10 MW | P50 MW | P90 MW |
|---|---:|---:|---:|---:|---:|
| TOTAL_GB_INTERCONNECTORS | 1,600 | 9.1% | 228 | 1,330 | 3,889 |
| INTNED | 5,071 | 28.9% | 176 | 688 | 1,016 |
| INTVKL | 4,507 | 25.7% | 128 | 638 | 1,092 |
| INTFR | 1,485 | 8.5% | 72 | 592 | 1,682 |
| INTEW | 13,648 | 77.7% | 114 | 528 | 532 |

## Outputs

- `import_export_level_percentiles_2024.csv` - long-form percentile table.
- `import_export_level_percentiles_wide_2024.csv` - one row per series and direction with P0-P100 columns.
- `import_export_level_pdf_bins_2024.csv` - binned probability-density table used by the PDF-style plots.
- `import_export_direction_sample_summary_2024.csv` - import/export/near-zero sample sizes and mean levels.
- `figures/import_level_percentile_distribution_2024.html` - import distribution plot.
- `figures/export_level_percentile_distribution_2024.html` - export distribution plot.
- `figures/interconnectors/pdf_distributions/*_level_pdf_distribution_2024.html` - one probability-density distribution plot per interconnector and fleet total.
- `figures/interconnectors/cdf_distributions/*_level_cdf_distribution_2024.html` - one cumulative distribution plot per interconnector and fleet total.
