# Presentation Outline - GB Interconnector BM Operating History

Analysis window: 2021-07-01 00:00 UTC to 2026-06-30 22:30 UTC.
Sign convention: positive raw `generation` is treated as GB import; positive signed values mean GB import.
Capacity convention: `% capacity` uses `capacity_reference.csv`, defaulting to observed absolute peak MW unless a supplied capacity file is present.

## Deck Structure

Use the first section to establish the full system story, then move into one drill-down slide per link. The drill-down slides should use the same layout so the audience can compare behaviour quickly.

## Section 1 - Full Fleet Picture

### Slide 1 - Title and Client Question

Purpose: frame the question as operating behaviour, not just volume.

Suggested title: `GB interconnectors in the BM: five-year operating history`.

Key message: we are showing how often each link imported/exported, at what level, how seasonal the operation is, and whether links tend to move together or offset each other.

Visuals: none, or a simple map/list of the interconnector set.

### Slide 2 - Data, Sign Convention, and Capacity Normalisation

Purpose: make the basis of the analysis explicit before showing results.

Key points:
- Analysis covers 2021-07-01 to 2026-06-30.
- Half-hourly BM values are used from `HH_data`.
- Import is shown as positive, export as negative.
- Direction shares use the configured near-zero deadband.
- Comparative utilisation charts use `% capacity`, based on `capacity_reference.csv`.

Visuals: `capacity_reference.csv` as a compact table or footnote.

### Slide 3 - Fleet Headline

Purpose: answer the headline question for the GB interconnector fleet.

Key points:
- Fleet imported for 78.1% of half-hours and exported for 21.8%.
- Mean fleet position was 2,452 MW, or 17.0% of observed fleet capacity.
- Net energy was 107,458 GWh over the window.

Visuals: `figures/direction_share_by_interconnector.png` and/or `figures/net_energy_by_interconnector.png`.

### Slide 4 - Which Links Drove Net Imports and Exports?

Purpose: show contribution by interconnector and separate structural importers from exporters.

Key points:
- Import driver: INTNSL net 33,185 GWh, importing 82.1% of half-hours.
- Import driver: INTFR net 31,407 GWh, importing 72.6% of half-hours.
- Import driver: INTELEC net 15,435 GWh, importing 68.2% of half-hours.
- Export driver: INTIRL net -7,970 GWh, exporting 69.5% of half-hours.
- Export driver: INTEW net -6,470 GWh, exporting 52.8% of half-hours.
- Export driver: INTGRNL net -4,196 GWh, exporting 82.9% of half-hours.

Visuals: `figures/net_energy_by_interconnector.png`.

### Slide 5 - Direction Duty Cycle

Purpose: show how often each link imports, exports, or sits near zero.

Key points:
- This is the cleanest answer to `how often are they exporting/importing?`.
- Highlight links with sustained export behaviour and links with a material near-zero share.

Visuals: `figures/direction_share_by_interconnector.png`.

### Slide 6 - Capacity-Normalised Utilisation

Purpose: avoid misleading comparisons caused by different link sizes.

Key points:
- Use `% capacity` to compare behaviour across different-size assets.
- Show which links spend most time at high import or high export utilisation.
- Keep MW charts for system impact; use `% capacity` charts for like-for-like operating behaviour.

Visuals: `figures/pct_capacity_bands_by_interconnector.png` and `figures/month_of_year_pct_capacity_heatmap.png`.

### Slide 7 - Collapsed Seasonal Shape

Purpose: show how the typical year behaves after collapsing the five-year history.

Key points:
- Winter: mean 2,693 MW, 18.7% capacity, import share 81.7%.
- Spring: mean 3,187 MW, 22.1% capacity, import share 84.3%.
- Summer: mean 2,229 MW, 15.5% capacity, import share 73.7%.
- Autumn: mean 1,695 MW, 11.8% capacity, import share 72.9%.
- Strongest collapsed month: Mar at 27.9% capacity.
- Weakest collapsed month: Sep at 10.9% capacity.

Visuals: `figures/season_pct_capacity_heatmap.png`, `figures/fleet_month_of_year_pct_capacity_profile.png`, and `figures/month_of_year_pct_capacity_heatmap.png`.

### Slide 8 - Calendar-Time Regime Changes

Purpose: show the time history, not only the collapsed seasonal average.

Key points:
- Use this to show structural changes from new links, outages, or changing market conditions.
- Present MW for system effect and `% capacity` for comparable asset behaviour.

Visuals: `figures/monthly_mean_signed_mw_heatmap.png` and `figures/calendar_month_pct_capacity_heatmap.png`.

### Slide 9 - Rolling Regimes and Recent Direction

Purpose: show persistence and changes in import/export regimes over time.

Key points:
- Use 30-day and 90-day rolling fleet position to avoid over-reading half-hour volatility.
- Identify periods where the fleet moved toward weaker imports or stronger imports.

Visuals: `figures/fleet_rolling_net_mw.png`.

### Slide 10 - Within-Day Shape by Season

Purpose: show whether the fleet has a systematic diurnal operating pattern.

Key points:
- Compare seasonal diurnal curves rather than individual noisy half-hours.
- Use this slide to discuss whether interconnectors are responding to daily price/spread patterns.

Visuals: `figures/fleet_diurnal_by_season.png`.

### Slide 11 - Coordination Across Interconnectors

Purpose: show whether links tend to move together or offset each other.

Key points:
- Strong co-movement: INTELEC with INTIFA2 at r=0.77.
- Strong co-movement: INTELEC with INTFR at r=0.75.
- Strong co-movement: INTFR with INTIFA2 at r=0.75.
- Strong offset: INTFR with INTIRL at r=-0.41.
- Strong offset: INTELEC with INTIRL at r=-0.39.
- Strong offset: INTIFA2 with INTIRL at r=-0.38.

Visuals: `figures/flow_correlation_heatmap.png`, `figures/direction_alignment_heatmap.png`, and `figures/direction_opposition_heatmap.png`.

### Slide 12 - Fleet Takeaways

Purpose: close the fleet section before moving to individual link pages.

Key points:
- GB interconnector BM operation is net import-oriented at fleet level, but not uniformly across links.
- Ireland/Northern Ireland links are structurally export-leaning in this dataset; France/Norway/Belgium/Netherlands links are import-leaning.
- Capacity-normalised charts are essential for fair link-to-link comparisons.
- Seasonal behaviour is visible after collapsing the history, with spring strongest and autumn weakest at fleet level.

Visuals: small multiples or a four-bullet summary.

## Section 2 - One Slide Per Interconnector

Recommended slide layout for every link:
- Left: `figures/interconnectors/<ID>_operating_profile.png`, or use modular PNGs from `figures/interconnectors/subfigures/`.
- Right top: headline stats, direction shares, mean MW, mean % capacity, net GWh.
- Right middle: seasonal/month context.
- Right bottom: coordination context and interpretation.

### Slide 13 - North Sea Link (INTNSL) (INTNSL)

Purpose: explain this link as a net importer and show how its behaviour differs from the fleet.

Headline stats:
- Direction: import; import 82.1%, export 15.6%, near zero 2.3%.
- Mean position: 798 MW, 43.2% capacity.
- Net energy: 33,185 GWh.
- Typical level when importing/exporting: 1,094 MW import, 639 MW export.
- Direction switching: 23.9 switches per 30 days.

Seasonal and monthly context:
- Strongest month-of-year: Jul at 54.7% capacity (1,011 MW).
- Weakest or most export-leaning month-of-year: Oct at 36.0% capacity (665 MW).
- Strongest season: Summer at 47.6% capacity.
- Weakest or most export-leaning season: Winter at 40.1% capacity.

Coordination context:
- Highest positive MW co-movement with INTFR: r=0.36.
- Strongest MW offset with INTIRL: r=-0.25.
- Highest same-direction share with INTFR: 71.3%.
- Highest opposite-direction share with INTGRNL: 72.8%.

Suggested visuals:
- `figures/interconnectors/INTNSL_operating_profile.png`.
- Modular options: `figures/interconnectors/subfigures/INTNSL_daily_rolling.png`, `INTNSL_month_of_year_pct_capacity.png`, `INTNSL_seasonal_direction_share.png`, and `INTNSL_level_bands_pct_capacity.png`.
- Refer back to `figures/month_of_year_pct_capacity_heatmap.png` or `figures/season_pct_capacity_heatmap.png` for cross-link comparison.

Presenter note: keep the interpretation focused on direction, utilisation, seasonality, and whether the link moves with or against the wider interconnector fleet.

### Slide 14 - France(IFA) (INTFR)

Purpose: explain this link as a net importer and show how its behaviour differs from the fleet.

Headline stats:
- Direction: import; import 72.6%, export 23.7%, near zero 3.7%.
- Mean position: 717 MW, 27.3% capacity.
- Net energy: 31,407 GWh.
- Typical level when importing/exporting: 1,203 MW import, 663 MW export.
- Direction switching: 40.1 switches per 30 days.

Seasonal and monthly context:
- Strongest month-of-year: Mar at 39.8% capacity (1,046 MW).
- Weakest or most export-leaning month-of-year: Oct at 16.3% capacity (429 MW).
- Strongest season: Spring at 32.9% capacity.
- Weakest or most export-leaning season: Autumn at 18.8% capacity.

Coordination context:
- Highest positive MW co-movement with INTELEC: r=0.75.
- Strongest MW offset with INTIRL: r=-0.41.
- Highest same-direction share with INTELEC: 79.8%.
- Highest opposite-direction share with INTGRNL: 81.3%.

Suggested visuals:
- `figures/interconnectors/INTFR_operating_profile.png`.
- Modular options: `figures/interconnectors/subfigures/INTFR_daily_rolling.png`, `INTFR_month_of_year_pct_capacity.png`, `INTFR_seasonal_direction_share.png`, and `INTFR_level_bands_pct_capacity.png`.
- Refer back to `figures/month_of_year_pct_capacity_heatmap.png` or `figures/season_pct_capacity_heatmap.png` for cross-link comparison.

Presenter note: keep the interpretation focused on direction, utilisation, seasonality, and whether the link moves with or against the wider interconnector fleet.

### Slide 15 - Eleclink (INTELEC) (INTELEC)

Purpose: explain this link as a net importer and show how its behaviour differs from the fleet.

Headline stats:
- Direction: import; import 68.2%, export 19.5%, near zero 12.3%.
- Mean position: 429 MW, 34.1% capacity.
- Net energy: 15,435 GWh.
- Typical level when importing/exporting: 816 MW import, 650 MW export.
- Direction switching: 24.2 switches per 30 days.

Seasonal and monthly context:
- Strongest month-of-year: Apr at 61.6% capacity (777 MW).
- Weakest or most export-leaning month-of-year: Oct at 8.9% capacity (112 MW).
- Strongest season: Spring at 60.5% capacity.
- Weakest or most export-leaning season: Autumn at 14.4% capacity.

Coordination context:
- Highest positive MW co-movement with INTIFA2: r=0.77.
- Strongest MW offset with INTIRL: r=-0.39.
- Highest same-direction share with INTFR: 79.8%.
- Highest opposite-direction share with INTGRNL: 77.0%.

Suggested visuals:
- `figures/interconnectors/INTELEC_operating_profile.png`.
- Modular options: `figures/interconnectors/subfigures/INTELEC_daily_rolling.png`, `INTELEC_month_of_year_pct_capacity.png`, `INTELEC_seasonal_direction_share.png`, and `INTELEC_level_bands_pct_capacity.png`.
- Refer back to `figures/month_of_year_pct_capacity_heatmap.png` or `figures/season_pct_capacity_heatmap.png` for cross-link comparison.

Presenter note: keep the interpretation focused on direction, utilisation, seasonality, and whether the link moves with or against the wider interconnector fleet.

### Slide 16 - IFA2 (INTIFA2) (INTIFA2)

Purpose: explain this link as a net importer and show how its behaviour differs from the fleet.

Headline stats:
- Direction: import; import 61.8%, export 38.2%, near zero 0.1%.
- Mean position: 328 MW, 20.2% capacity.
- Net energy: 14,387 GWh.
- Typical level when importing/exporting: 786 MW import, 411 MW export.
- Direction switching: 33.3 switches per 30 days.

Seasonal and monthly context:
- Strongest month-of-year: Mar at 35.8% capacity (581 MW).
- Weakest or most export-leaning month-of-year: Nov at 2.4% capacity (39 MW).
- Strongest season: Spring at 32.7% capacity.
- Weakest or most export-leaning season: Autumn at 9.6% capacity.

Coordination context:
- Highest positive MW co-movement with INTELEC: r=0.77.
- Strongest MW offset with INTIRL: r=-0.38.
- Highest same-direction share with INTFR: 79.2%.
- Highest opposite-direction share with INTGRNL: 73.4%.

Suggested visuals:
- `figures/interconnectors/INTIFA2_operating_profile.png`.
- Modular options: `figures/interconnectors/subfigures/INTIFA2_daily_rolling.png`, `INTIFA2_month_of_year_pct_capacity.png`, `INTIFA2_seasonal_direction_share.png`, and `INTIFA2_level_bands_pct_capacity.png`.
- Refer back to `figures/month_of_year_pct_capacity_heatmap.png` or `figures/season_pct_capacity_heatmap.png` for cross-link comparison.

Presenter note: keep the interpretation focused on direction, utilisation, seasonality, and whether the link moves with or against the wider interconnector fleet.

### Slide 17 - Belgium (Nemolink) (INTNEM)

Purpose: explain this link as a net importer and show how its behaviour differs from the fleet.

Headline stats:
- Direction: import; import 68.7%, export 28.9%, near zero 2.4%.
- Mean position: 326 MW, 23.9% capacity.
- Net energy: 14,297 GWh.
- Typical level when importing/exporting: 712 MW import, 565 MW export.
- Direction switching: 68.2 switches per 30 days.

Seasonal and monthly context:
- Strongest month-of-year: Mar at 38.1% capacity (521 MW).
- Weakest or most export-leaning month-of-year: Jun at 5.8% capacity (79 MW).
- Strongest season: Winter at 28.2% capacity.
- Weakest or most export-leaning season: Summer at 17.2% capacity.

Coordination context:
- Highest positive MW co-movement with INTNED: r=0.69.
- Strongest MW offset with INTGRNL: r=-0.26.
- Highest same-direction share with INTNED: 73.1%.
- Highest opposite-direction share with INTGRNL: 64.3%.

Suggested visuals:
- `figures/interconnectors/INTNEM_operating_profile.png`.
- Modular options: `figures/interconnectors/subfigures/INTNEM_daily_rolling.png`, `INTNEM_month_of_year_pct_capacity.png`, `INTNEM_seasonal_direction_share.png`, and `INTNEM_level_bands_pct_capacity.png`.
- Refer back to `figures/month_of_year_pct_capacity_heatmap.png` or `figures/season_pct_capacity_heatmap.png` for cross-link comparison.

Presenter note: keep the interpretation focused on direction, utilisation, seasonality, and whether the link moves with or against the wider interconnector fleet.

### Slide 18 - Netherlands(BritNed) (INTNED)

Purpose: explain this link as a net importer and show how its behaviour differs from the fleet.

Headline stats:
- Direction: import; import 59.2%, export 31.4%, near zero 9.4%.
- Mean position: 233 MW, 16.6% capacity.
- Net energy: 10,220 GWh.
- Typical level when importing/exporting: 743 MW import, 660 MW export.
- Direction switching: 65.0 switches per 30 days.

Seasonal and monthly context:
- Strongest month-of-year: Mar at 36.9% capacity (518 MW).
- Weakest or most export-leaning month-of-year: Jun at 4.8% capacity (68 MW).
- Strongest season: Winter at 26.6% capacity.
- Weakest or most export-leaning season: Summer at 8.9% capacity.

Coordination context:
- Highest positive MW co-movement with INTNEM: r=0.69.
- Strongest MW offset with INTGRNL: r=-0.22.
- Highest same-direction share with INTNEM: 73.1%.
- Highest opposite-direction share with INTGRNL: 54.6%.

Suggested visuals:
- `figures/interconnectors/INTNED_operating_profile.png`.
- Modular options: `figures/interconnectors/subfigures/INTNED_daily_rolling.png`, `INTNED_month_of_year_pct_capacity.png`, `INTNED_seasonal_direction_share.png`, and `INTNED_level_bands_pct_capacity.png`.
- Refer back to `figures/month_of_year_pct_capacity_heatmap.png` or `figures/season_pct_capacity_heatmap.png` for cross-link comparison.

Presenter note: keep the interpretation focused on direction, utilisation, seasonality, and whether the link moves with or against the wider interconnector fleet.

### Slide 19 - Denmark (Viking link) (INTVKL)

Purpose: explain this link as a net importer and show how its behaviour differs from the fleet.

Headline stats:
- Direction: import; import 61.4%, export 31.6%, near zero 7.0%.
- Mean position: 326 MW, 13.2% capacity.
- Net energy: 7,162 GWh.
- Typical level when importing/exporting: 894 MW import, 702 MW export.
- Direction switching: 60.1 switches per 30 days.

Seasonal and monthly context:
- Strongest month-of-year: Jan at 20.8% capacity (515 MW).
- Weakest or most export-leaning month-of-year: Aug at 1.5% capacity (37 MW).
- Strongest season: Winter at 17.3% capacity.
- Weakest or most export-leaning season: Summer at 8.5% capacity.

Coordination context:
- Highest positive MW co-movement with INTNED: r=0.59.
- Strongest MW offset with INTGRNL: r=-0.14.
- Highest same-direction share with INTNEM: 67.1%.
- Highest opposite-direction share with INTGRNL: 56.3%.

Suggested visuals:
- `figures/interconnectors/INTVKL_operating_profile.png`.
- Modular options: `figures/interconnectors/subfigures/INTVKL_daily_rolling.png`, `INTVKL_month_of_year_pct_capacity.png`, `INTVKL_seasonal_direction_share.png`, and `INTVKL_level_bands_pct_capacity.png`.
- Refer back to `figures/month_of_year_pct_capacity_heatmap.png` or `figures/season_pct_capacity_heatmap.png` for cross-link comparison.

Presenter note: keep the interpretation focused on direction, utilisation, seasonality, and whether the link moves with or against the wider interconnector fleet.

### Slide 20 - Ireland (Greenlink) (INTGRNL)

Purpose: explain this link as a net exporter and show how its behaviour differs from the fleet.

Headline stats:
- Direction: export; import 14.1%, export 82.9%, near zero 3.0%.
- Mean position: -338 MW, -65.3% capacity.
- Net energy: -4,196 GWh.
- Typical level when importing/exporting: 206 MW import, 443 MW export.
- Direction switching: 36.7 switches per 30 days.

Seasonal and monthly context:
- Strongest month-of-year: Feb at -46.4% capacity (-240 MW).
- Weakest or most export-leaning month-of-year: May at -79.7% capacity (-413 MW).
- Strongest season: Winter at -55.4% capacity.
- Weakest or most export-leaning season: Spring at -71.4% capacity.

Coordination context:
- Highest positive MW co-movement with INTIRL: r=0.74.
- Strongest MW offset with INTNEM: r=-0.26.
- Highest same-direction share with INTIRL: 82.1%.
- Highest opposite-direction share with INTFR: 81.3%.

Suggested visuals:
- `figures/interconnectors/INTGRNL_operating_profile.png`.
- Modular options: `figures/interconnectors/subfigures/INTGRNL_daily_rolling.png`, `INTGRNL_month_of_year_pct_capacity.png`, `INTGRNL_seasonal_direction_share.png`, and `INTGRNL_level_bands_pct_capacity.png`.
- Refer back to `figures/month_of_year_pct_capacity_heatmap.png` or `figures/season_pct_capacity_heatmap.png` for cross-link comparison.

Presenter note: keep the interpretation focused on direction, utilisation, seasonality, and whether the link moves with or against the wider interconnector fleet.

### Slide 21 - Ireland(East-West) (INTEW)

Purpose: explain this link as a net exporter and show how its behaviour differs from the fleet.

Headline stats:
- Direction: export; import 16.9%, export 52.8%, near zero 30.3%.
- Mean position: -148 MW, -25.1% capacity.
- Net energy: -6,470 GWh.
- Typical level when importing/exporting: 231 MW import, 353 MW export.
- Direction switching: 37.9 switches per 30 days.

Seasonal and monthly context:
- Strongest month-of-year: Dec at -13.7% capacity (-80 MW).
- Weakest or most export-leaning month-of-year: Jun at -35.5% capacity (-209 MW).
- Strongest season: Winter at -17.7% capacity.
- Weakest or most export-leaning season: Summer at -32.0% capacity.

Coordination context:
- Highest positive MW co-movement with INTIRL: r=0.73.
- Strongest MW offset with INTFR: r=-0.37.
- Highest same-direction share with INTIRL: 64.3%.
- Highest opposite-direction share with INTFR: 53.1%.

Suggested visuals:
- `figures/interconnectors/INTEW_operating_profile.png`.
- Modular options: `figures/interconnectors/subfigures/INTEW_daily_rolling.png`, `INTEW_month_of_year_pct_capacity.png`, `INTEW_seasonal_direction_share.png`, and `INTEW_level_bands_pct_capacity.png`.
- Refer back to `figures/month_of_year_pct_capacity_heatmap.png` or `figures/season_pct_capacity_heatmap.png` for cross-link comparison.

Presenter note: keep the interpretation focused on direction, utilisation, seasonality, and whether the link moves with or against the wider interconnector fleet.

### Slide 22 - Northern Ireland(Moyle) (INTIRL)

Purpose: explain this link as a net exporter and show how its behaviour differs from the fleet.

Headline stats:
- Direction: export; import 24.5%, export 69.5%, near zero 6.0%.
- Mean position: -182 MW, -26.7% capacity.
- Net energy: -7,970 GWh.
- Typical level when importing/exporting: 217 MW import, 338 MW export.
- Direction switching: 54.1 switches per 30 days.

Seasonal and monthly context:
- Strongest month-of-year: Dec at -15.1% capacity (-103 MW).
- Weakest or most export-leaning month-of-year: May at -36.1% capacity (-247 MW).
- Strongest season: Winter at -18.4% capacity.
- Weakest or most export-leaning season: Spring at -32.5% capacity.

Coordination context:
- Highest positive MW co-movement with INTGRNL: r=0.74.
- Strongest MW offset with INTFR: r=-0.41.
- Highest same-direction share with INTGRNL: 82.1%.
- Highest opposite-direction share with INTFR: 68.8%.

Suggested visuals:
- `figures/interconnectors/INTIRL_operating_profile.png`.
- Modular options: `figures/interconnectors/subfigures/INTIRL_daily_rolling.png`, `INTIRL_month_of_year_pct_capacity.png`, `INTIRL_seasonal_direction_share.png`, and `INTIRL_level_bands_pct_capacity.png`.
- Refer back to `figures/month_of_year_pct_capacity_heatmap.png` or `figures/season_pct_capacity_heatmap.png` for cross-link comparison.

Presenter note: keep the interpretation focused on direction, utilisation, seasonality, and whether the link moves with or against the wider interconnector fleet.

## Optional Appendix

### Slide 23 - Method and Caveats

Key points:
- Sign convention should be verified against the data source; rerun with `--positive-direction export` if the source convention is reversed.
- `% capacity` uses observed peak by default; replace with supplied nameplate capacities via `interconnector_capacities.csv` when available.
- Newer links have shorter operating histories, so collapsed seasonal comparisons should be interpreted with that context.
- Near-zero shares can reflect outages, ramping, or commercial non-use; do not treat them as outage-only without operational validation.
