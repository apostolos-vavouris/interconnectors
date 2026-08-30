# 2025 Import/Export Level Distribution Percentiles

The run covers the full 2025 calendar year.

Percentiles are calculated separately for import and export operating periods. That means import P10/P50/P90 use only half-hours where the series is importing, while export P10/P50/P90 use only half-hours where the series is exporting. Exports are shown as positive MW magnitudes.

## Fleet Readout

- Importing half-hours: 15,442 (88.1% of operational periods).
- Exporting half-hours: 2,076 (11.8% of operational periods).
- Near-zero half-hours: 2 (0.0% of operational periods).
- Fleet import distribution: P10 1,114 MW, P50 4,108 MW, P90 6,690 MW.
- Fleet export distribution: P10 215 MW, P50 1,306 MW, P90 3,750 MW.

For minimum operating-limit style figures, the low directional percentiles (especially P5, P10, and P20) are usually more useful than P0 because P0 is the single smallest non-near-zero half-hour after the deadband filter.

## Largest Median Directional Levels

### Import

| Interconnector | Direction half-hours | Direction share | P10 MW | P50 MW | P90 MW |
|---|---:|---:|---:|---:|---:|
| TOTAL_GB_INTERCONNECTORS | 15,442 | 88.1% | 1,114 | 4,108 | 6,690 |
| INTNSL | 15,605 | 89.1% | 698 | 1,396 | 1,398 |
| INTFR | 16,191 | 92.4% | 578 | 1,366 | 2,004 |
| INTELEC | 13,881 | 79.2% | 416 | 996 | 998 |
| INTIFA2 | 13,922 | 79.5% | 424 | 992 | 992 |

### Export

| Interconnector | Direction half-hours | Direction share | P10 MW | P50 MW | P90 MW |
|---|---:|---:|---:|---:|---:|
| TOTAL_GB_INTERCONNECTORS | 2,076 | 11.8% | 215 | 1,306 | 3,750 |
| INTVKL | 6,172 | 35.2% | 156 | 790 | 1,094 |
| INTNED | 7,250 | 41.4% | 196 | 738 | 1,044 |
| INTNSL | 1,372 | 7.8% | 38 | 664 | 1,446 |
| INTNEM | 6,181 | 35.3% | 102 | 570 | 1,022 |

## Outputs

- `import_export_level_percentiles_2025.csv` - long-form percentile table.
- `import_export_level_percentiles_wide_2025.csv` - one row per series and direction with P0-P100 columns.
- `import_export_level_pdf_bins_2025.csv` - binned probability-density table used by the PDF-style plots.
- `import_export_direction_sample_summary_2025.csv` - import/export/near-zero sample sizes and mean levels.
- `figures/import_level_percentile_distribution_2025.html` - import distribution plot.
- `figures/export_level_percentile_distribution_2025.html` - export distribution plot.
- `figures/interconnectors/pdf_distributions/*_level_pdf_distribution_2025.html` - one probability-density distribution plot per interconnector and fleet total.
- `figures/interconnectors/cdf_distributions/*_level_cdf_distribution_2025.html` - one cumulative distribution plot per interconnector and fleet total.
