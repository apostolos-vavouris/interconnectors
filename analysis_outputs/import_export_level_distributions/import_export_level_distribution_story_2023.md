# 2023 Import/Export Level Distribution Percentiles

The run covers the full 2023 calendar year.

Percentiles are calculated separately for import and export operating periods. That means import P10/P50/P90 use only half-hours where the series is importing, while export P10/P50/P90 use only half-hours where the series is exporting. Exports are shown as positive MW magnitudes.

## Fleet Readout

- Importing half-hours: 14,206 (81.1% of operational periods).
- Exporting half-hours: 3,303 (18.9% of operational periods).
- Near-zero half-hours: 9 (0.1% of operational periods).
- Fleet import distribution: P10 914 MW, P50 3,821 MW, P90 6,181 MW.
- Fleet export distribution: P10 238 MW, P50 1,416 MW, P90 3,445 MW.

For minimum operating-limit style figures, the low directional percentiles (especially P5, P10, and P20) are usually more useful than P0 because P0 is the single smallest non-near-zero half-hour after the deadband filter.

## Largest Median Directional Levels

### Import

| Interconnector | Direction half-hours | Direction share | P10 MW | P50 MW | P90 MW |
|---|---:|---:|---:|---:|---:|
| TOTAL_GB_INTERCONNECTORS | 14,206 | 81.1% | 914 | 3,821 | 6,181 |
| INTNSL | 15,457 | 88.2% | 693 | 1,296 | 1,400 |
| INTFR | 13,676 | 78.1% | 266 | 996 | 1,958 |
| INTNED | 11,432 | 65.3% | 244 | 872 | 1,050 |
| INTELEC | 13,325 | 76.1% | 182 | 828 | 998 |

### Export

| Interconnector | Direction half-hours | Direction share | P10 MW | P50 MW | P90 MW |
|---|---:|---:|---:|---:|---:|
| TOTAL_GB_INTERCONNECTORS | 3,303 | 18.9% | 238 | 1,416 | 3,445 |
| INTNED | 5,119 | 29.2% | 172 | 644 | 1,014 |
| INTFR | 3,724 | 21.3% | 86 | 590 | 1,454 |
| INTNSL | 1,451 | 8.3% | 6 | 454 | 1,452 |
| INTIRL | 13,705 | 78.2% | 144 | 428 | 452 |

## Outputs

- `import_export_level_percentiles_2023.csv` - long-form percentile table.
- `import_export_level_percentiles_wide_2023.csv` - one row per series and direction with P0-P100 columns.
- `import_export_level_pdf_bins_2023.csv` - binned probability-density table used by the PDF-style plots.
- `import_export_direction_sample_summary_2023.csv` - import/export/near-zero sample sizes and mean levels.
- `figures/import_level_percentile_distribution_2023.html` - import distribution plot.
- `figures/export_level_percentile_distribution_2023.html` - export distribution plot.
- `figures/interconnectors/pdf_distributions/*_level_pdf_distribution_2023.html` - one probability-density distribution plot per interconnector and fleet total.
- `figures/interconnectors/cdf_distributions/*_level_cdf_distribution_2023.html` - one cumulative distribution plot per interconnector and fleet total.
