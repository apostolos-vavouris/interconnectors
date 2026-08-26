# Interconnector Flow and Price Spread Relationship

Analysis window: 2021-07-01 to 2026-06-30.

Spread convention: `price_spread_gb_minus_zone = GB price - bidding-zone price`. Positive spread means GB is more expensive than the linked market, so GB import is the price-aligned direction. Negative spread means export is price-aligned.
Near parity is defined as absolute spread <= 1.0 in the price-file units.

Visuals: `figures/spread_flow_correlation_by_interconnector.*`, `figures/spread_band_mean_flow_heatmap.*`, `figures/spread_direction_alignment_by_interconnector.*`, `figures/spread_lag_correlation_heatmap.*`, and `figures/daily_spread_flow_scatter_by_interconnector.*`.

## Headline

- Average absolute half-hourly correlation between spread and signed MW is 0.36 across interconnectors.
- Positive correlation means flows tend to move towards GB when GB is higher priced and away from GB when the linked market is higher priced.

## Strongest Price-Flow Relationships

- INTVKL (DK): Pearson 0.59, Spearman 0.75, OLS slope 12.6 MW per price unit, directional alignment 86.9%.
- INTELEC (FR): Pearson 0.59, Spearman 0.68, OLS slope 7.2 MW per price unit, directional alignment 86.6%.
- INTIFA2 (FR): Pearson 0.50, Spearman 0.68, OLS slope 5.2 MW per price unit, directional alignment 75.7%.
- INTNEM (B): Pearson 0.46, Spearman 0.73, OLS slope 5.3 MW per price unit, directional alignment 82.2%.
- INTFR (FR): Pearson 0.43, Spearman 0.62, OLS slope 6.3 MW per price unit, directional alignment 85.7%.

Weakest relationships:

- INTGRNL (IRL): Pearson 0.02, directional alignment 67.1%.
- INTIRL (IRL): Pearson 0.19, directional alignment 66.9%.
- INTEW (IRL): Pearson 0.21, directional alignment 69.2%.

## Directional Alignment

- INTNSL: 89.4% of directional price-signal half-hours align with flow direction; 10.6% counter the spread.
- INTVKL: 86.9% of directional price-signal half-hours align with flow direction; 13.1% counter the spread.
- INTELEC: 86.6% of directional price-signal half-hours align with flow direction; 13.4% counter the spread.
- INTFR: 85.7% of directional price-signal half-hours align with flow direction; 14.3% counter the spread.
- INTNEM: 82.2% of directional price-signal half-hours align with flow direction; 17.8% counter the spread.

Lower-alignment links to inspect:
- INTEW: aligned 69.2%, counter 30.8%.
- INTGRNL: aligned 67.1%, counter 32.9%.
- INTIRL: aligned 66.9%, counter 33.1%.

## Spread Bands

- INTELEC: strongest net import band is `GB > zone by 50-100` (843 MW); strongest net export band is `Zone > GB by 50-100` (-812 MW).
- INTEW: strongest net import band is `GB > zone by >100` (111 MW); strongest net export band is `Zone > GB by >100` (-228 MW).
- INTFR: strongest net import band is `GB > zone by 50-100` (1,313 MW); strongest net export band is `Zone > GB by >100` (-730 MW).
- INTGRNL: least export-leaning band is `GB > zone by 50-100` (-302 MW); strongest net export band is `GB > zone by >100` (-360 MW).
- INTIFA2: strongest net import band is `GB > zone by >100` (793 MW); strongest net export band is `Zone > GB by >100` (-908 MW).
- INTIRL: strongest net import band is `GB > zone by >100` (50 MW); strongest net export band is `Zone > GB by 50-100` (-233 MW).
- INTNED: strongest net import band is `GB > zone by >100` (880 MW); strongest net export band is `Zone > GB by >100` (-651 MW).
- INTNEM: strongest net import band is `GB > zone by >100` (938 MW); strongest net export band is `Zone > GB by >100` (-764 MW).
- INTNSL: strongest net import band is `GB > zone by 50-100` (1,077 MW); strongest net export band is `Zone > GB by 50-100` (-1,050 MW).
- INTVKL: strongest net import band is `GB > zone by 50-100` (1,031 MW); strongest net export band is `Zone > GB by 50-100` (-886 MW).

## Daily and Lag Checks

- Daily INTVKL: Pearson 0.72 between daily mean spread and daily mean signed MW.
- Daily INTELEC: Pearson 0.70 between daily mean spread and daily mean signed MW.
- Daily INTIFA2: Pearson 0.68 between daily mean spread and daily mean signed MW.

Best lag by absolute correlation, where positive lag means spread leads flow:
- INTELEC: 0 hours, Pearson 0.59.
- INTEW: -24 hours, Pearson 0.35.
- INTFR: 0 hours, Pearson 0.43.
- INTGRNL: -24 hours, Pearson 0.25.
- INTIFA2: 0 hours, Pearson 0.50.
- INTIRL: -24 hours, Pearson 0.33.
- INTNED: 0 hours, Pearson 0.43.
- INTNEM: 0 hours, Pearson 0.46.
- INTNSL: 0 hours, Pearson 0.22.
- INTVKL: 0 hours, Pearson 0.59.

## Tables Written

- `price_spread_correlation_summary.csv`
- `price_spread_correlation_by_frequency.csv`
- `price_spread_band_summary.csv`
- `price_spread_quantile_summary.csv`
- `price_spread_direction_alignment_summary.csv`
- `price_spread_lag_correlation_summary.csv`
- `price_spread_daily_summary.csv`
- `price_spread_monthly_summary.csv`
- `interconnector_price_spread_join_coverage.csv`
- `interconnector_price_spread_join_half_hourly.csv.gz`
