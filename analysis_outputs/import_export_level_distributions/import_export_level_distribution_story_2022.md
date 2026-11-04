# 2022 Import/Export Level Distribution Percentiles

The run covers the full 2022 calendar year.

Percentiles are calculated separately for import and export operating periods. That means import P10/P50/P90 use only half-hours where the series is importing, while export P10/P50/P90 use only half-hours where the series is exporting. Exports are shown as positive MW magnitudes.

## Fleet Readout

- Importing half-hours: 7,490 (42.8% of operational periods).
- Exporting half-hours: 10,006 (57.2% of operational periods).
- Near-zero half-hours: 7 (0.0% of operational periods).
- Fleet import distribution: P10 476 MW, P50 2,242 MW, P90 4,774 MW.
- Fleet export distribution: P10 596 MW, P50 2,729 MW, P90 4,775 MW.

For minimum operating-limit style figures, the low directional percentiles (especially P5, P10, and P20) are usually more useful than P0 because P0 is the single smallest non-near-zero half-hour after the deadband filter.

## Largest Median Directional Levels

### Import

| Interconnector | Direction half-hours | Direction share | P10 MW | P50 MW | P90 MW |
|---|---:|---:|---:|---:|---:|
| TOTAL_GB_INTERCONNECTORS | 7,490 | 42.8% | 476 | 2,242 | 4,774 |
| INTNED | 10,014 | 57.2% | 204 | 816 | 1,054 |
| INTNEM | 9,400 | 53.7% | 170 | 778 | 1,000 |
| INTNSL | 11,239 | 64.2% | 252 | 694 | 1,258 |
| INTIFA2 | 4,029 | 23.0% | 124 | 662 | 992 |

### Export

| Interconnector | Direction half-hours | Direction share | P10 MW | P50 MW | P90 MW |
|---|---:|---:|---:|---:|---:|
| TOTAL_GB_INTERCONNECTORS | 10,006 | 57.2% | 596 | 2,729 | 4,775 |
| INTIFA2 | 13,464 | 76.9% | 110 | 982 | 1,030 |
| INTELEC | 8,341 | 78.6% | 416 | 926 | 1,024 |
| INTFR | 11,948 | 68.3% | 130 | 768 | 1,032 |
| INTNEM | 7,739 | 44.2% | 150 | 744 | 1,022 |

## Outputs

- `import_export_level_percentiles_2022.csv` - long-form percentile table.
- `import_export_level_percentiles_wide_2022.csv` - one row per series and direction with P0-P100 columns.
- `import_export_level_pdf_bins_2022.csv` - binned probability-density table used by the PDF-style plots.
- `import_export_direction_sample_summary_2022.csv` - import/export/near-zero sample sizes and mean levels.
- `figures/import_level_percentile_distribution_2022.html` - import distribution plot.
- `figures/export_level_percentile_distribution_2022.html` - export distribution plot.
- `figures/interconnectors/pdf_distributions/*_level_pdf_distribution_2022.html` - one probability-density distribution plot per interconnector and fleet total.
- `figures/interconnectors/cdf_distributions/*_level_cdf_distribution_2022.html` - one cumulative distribution plot per interconnector and fleet total.
