# 2021 Import/Export Level Distribution Percentiles

The run covers the full 2021 calendar year.

Percentiles are calculated separately for import and export operating periods. That means import P10/P50/P90 use only half-hours where the series is importing, while export P10/P50/P90 use only half-hours where the series is exporting. Exports are shown as positive MW magnitudes.

## Fleet Readout

- Importing half-hours: 16,572 (94.7% of operational periods).
- Exporting half-hours: 930 (5.3% of operational periods).
- Near-zero half-hours: 3 (0.0% of operational periods).
- Fleet import distribution: P10 1,380 MW, P50 3,172 MW, P90 4,362 MW.
- Fleet export distribution: P10 130 MW, P50 769 MW, P90 1,956 MW.

For minimum operating-limit style figures, the low directional percentiles (especially P5, P10, and P20) are usually more useful than P0 because P0 is the single smallest non-near-zero half-hour after the deadband filter.

## Largest Median Directional Levels

### Import

| Interconnector | Direction half-hours | Direction share | P10 MW | P50 MW | P90 MW |
|---|---:|---:|---:|---:|---:|
| TOTAL_GB_INTERCONNECTORS | 16,572 | 94.7% | 1,380 | 3,172 | 4,362 |
| INTFR | 13,304 | 76.0% | 676 | 1,688 | 2,004 |
| INTNED | 10,792 | 61.7% | 370 | 906 | 1,048 |
| INTNEM | 16,654 | 95.1% | 562 | 902 | 1,020 |
| INTIFA2 | 12,395 | 75.4% | 481 | 874 | 992 |

### Export

| Interconnector | Direction half-hours | Direction share | P10 MW | P50 MW | P90 MW |
|---|---:|---:|---:|---:|---:|
| TOTAL_GB_INTERCONNECTORS | 930 | 5.3% | 130 | 769 | 1,956 |
| INTFR | 2,488 | 14.2% | 134 | 561 | 1,028 |
| INTNEM | 650 | 3.7% | 66 | 418 | 816 |
| INTIRL | 10,425 | 59.6% | 78 | 354 | 456 |
| INTNED | 470 | 2.7% | 104 | 289 | 598 |

## Outputs

- `import_export_level_percentiles_2021.csv` - long-form percentile table.
- `import_export_level_percentiles_wide_2021.csv` - one row per series and direction with P0-P100 columns.
- `import_export_level_pdf_bins_2021.csv` - binned probability-density table used by the PDF-style plots.
- `import_export_direction_sample_summary_2021.csv` - import/export/near-zero sample sizes and mean levels.
- `figures/import_level_percentile_distribution_2021.html` - import distribution plot.
- `figures/export_level_percentile_distribution_2021.html` - export distribution plot.
- `figures/interconnectors/pdf_distributions/*_level_pdf_distribution_2021.html` - one probability-density distribution plot per interconnector and fleet total.
- `figures/interconnectors/cdf_distributions/*_level_cdf_distribution_2021.html` - one cumulative distribution plot per interconnector and fleet total.
