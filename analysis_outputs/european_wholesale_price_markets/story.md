# European Wholesale Electricity Prices Relative to GB

## Scope and conventions

- Source: `C:\Users\Work\Documents\My Work\european_wholesale_electricity_price_data_hourly`.
- GB benchmark: United Kingdom.
- Pairwise comparison window across the available markets spans 2016-06-29 23:00:00 to 2026-10-29 23:00:00; each market uses its own overlap with GB.
- Prices use the source unit EUR/MWh and timestamps use UTC.
- Spread is `GB price - comparison-market price`. Positive values mean GB is more expensive.
- The dataset contains one country-level series per market. It is not a true bidding-zone dataset for countries with multiple internal zones.

## Main historical signals

Highest hourly price-level correlations with GB:

- Belgium: r=0.86; hourly-change r=0.34; mean absolute spread=20.5 EUR/MWh.
- Netherlands: r=0.86; hourly-change r=0.29; mean absolute spread=20.7 EUR/MWh.
- Switzerland: r=0.85; hourly-change r=0.29; mean absolute spread=22.3 EUR/MWh.
- Austria: r=0.85; hourly-change r=0.28; mean absolute spread=24.6 EUR/MWh.
- France: r=0.85; hourly-change r=0.30; mean absolute spread=24.7 EUR/MWh.

Lowest hourly price-level correlations with GB:

- North Macedonia: r=0.53; hourly-change r=0.36; mean absolute spread=33.0 EUR/MWh.
- Albania: r=0.54; hourly-change r=0.36; mean absolute spread=49.8 EUR/MWh.
- Finland: r=0.56; hourly-change r=0.15; mean absolute spread=50.7 EUR/MWh.
- Montenegro: r=0.59; hourly-change r=0.36; mean absolute spread=29.1 EUR/MWh.
- Estonia: r=0.64; hourly-change r=0.13; mean absolute spread=40.2 EUR/MWh.

Largest average absolute price separations from GB:

- Finland: 50.7 EUR/MWh; GB is higher 82.6% of overlapping hours and the market is higher 15.1%.
- Albania: 49.8 EUR/MWh; GB is higher 30.5% of overlapping hours and the market is higher 67.7%.
- Sweden: 49.0 EUR/MWh; GB is higher 92.1% of overlapping hours and the market is higher 5.8%.
- Norway: 44.4 EUR/MWh; GB is higher 93.0% of overlapping hours and the market is higher 5.6%.
- Estonia: 40.2 EUR/MWh; GB is higher 71.6% of overlapping hours and the market is higher 25.3%.

## Convergence and divergence

Trends use calendar years with at least 90% hourly coverage; partial first and last years are excluded.

No market with enough complete-year history has a negative full-period fitted trend in mean absolute spread. The smallest positive slopes are:

- Austria: +1.36 EUR/MWh per year; robust median slope 2.05.
- North Macedonia: +1.37 EUR/MWh per year; robust median slope 1.37.
- Germany: +1.38 EUR/MWh per year; robust median slope 1.19.
- Luxembourg: +1.38 EUR/MWh per year; robust median slope 1.19.
- Belgium: +1.56 EUR/MWh per year; robust median slope 0.97.

Most positive fitted trends (descriptive divergence):

- Finland: +8.28 EUR/MWh per year; robust median slope 6.49.
- Sweden: +7.23 EUR/MWh per year; robust median slope 5.79.
- Spain: +5.81 EUR/MWh per year; robust median slope 4.46.
- Portugal: +5.75 EUR/MWh per year; robust median slope 4.27.
- Norway: +5.71 EUR/MWh per year; robust median slope 4.60.

Recent direction using each market's last three complete calendar years:

- Denmark: -1.85 EUR/MWh per year (recent convergence).
- Sweden: -1.67 EUR/MWh per year (recent convergence).
- Norway: -0.86 EUR/MWh per year (recent convergence).

Largest recent positive absolute-spread trends:

- France: +9.74 EUR/MWh per year.
- Hungary: +6.28 EUR/MWh per year.
- Estonia: +6.27 EUR/MWh per year.
- Lithuania: +6.06 EUR/MWh per year.
- Latvia: +5.72 EUR/MWh per year.

Even after excluding partial years, straight-line slopes remain sensitive to the 2021-2023 energy-price shock. Compare the OLS slope, robust median slope, recent three-complete-year slope and rolling figures before treating a trend as structural.

## Lead-lag checks

Strongest tested non-zero lag relationships in hourly price changes:

- Ireland: best tested lag -24 hours (GB leads comparison market), r=0.48.
- Albania: best tested lag +1 hour (comparison market leads GB), r=0.43.
- North Macedonia: best tested lag +1 hour (comparison market leads GB), r=0.43.
- Montenegro: best tested lag +1 hour (comparison market leads GB), r=0.40.
- Germany: best tested lag +1 hour (comparison market leads GB), r=0.31.

Lag peaks do not establish causality. Common fundamentals, market-gate timing, time-zone conventions, autocorrelation and shared interconnection can all produce lead-lag patterns.

## GB high-price periods

Largest average GB premiums during GB P95 high-price hours:

- Sweden: mean GB-market spread 189.5 EUR/MWh; the comparison market is simultaneously in its own high tail 53.9% of those hours.
- Norway: mean GB-market spread 179.9 EUR/MWh; the comparison market is simultaneously in its own high tail 60.4% of those hours.
- Spain: mean GB-market spread 164.2 EUR/MWh; the comparison market is simultaneously in its own high tail 42.5% of those hours.
- Portugal: mean GB-market spread 163.9 EUR/MWh; the comparison market is simultaneously in its own high tail 42.5% of those hours.
- Poland: mean GB-market spread 160.3 EUR/MWh; the comparison market is simultaneously in its own high tail 47.3% of those hours.

## How to use this for future-link screening

- `future_connection_screening_summary.csv` deliberately keeps separate indicators instead of combining them into one investment score. Large and persistent spreads indicate price separation, while correlation and tail coincidence indicate how often scarcity is shared.
- High average spreads alone do not imply an attractive interconnector. A feasibility case also needs zonal rather than country-average prices, route-specific losses, capacity and outage assumptions, congestion and curtailment modelling, network constraints, capex, regulation, market coupling and cannibalisation after the link is built.
- Give more weight to stable signals across annual, seasonal, rolling and tail-event views than to a full-period average.
- Use first-difference lag correlations for short-run timing. Price-level correlations mainly describe broad co-movement and common regimes.

## Output guide

- `market_price_summary.csv`: each market's standalone price distribution and volatility.
- `gb_market_relationship_summary.csv`: full-period GB comparison for every market.
- `annual_market_summary.csv`, `monthly_market_summary.csv`, `seasonal_market_summary.csv`: historical and seasonal relationship tables.
- `rolling_daily_metrics.csv.gz`: 30/90/365-day rolling correlations, prices and spreads.
- `lag_correlation_summary.csv` and `best_lag_summary.csv`: price-level and first-difference lead-lag checks.
- `tail_event_summary.csv`: GB and comparison-market low/high price-tail coincidence.
- `spread_band_summary.csv` and `spread_run_summary.csv`: magnitude bands and persistence of directional price signals.
- `future_connection_screening_summary.csv`: descriptive comparison table for early-stage screening.
- `figures/markets/<market>/`: six figures for each comparison market.

## Pairwise spreads between all markets

The pairwise layer analyses 527 eligible market pairs. Each signed spread is `market A price - market B price`; symmetric metrics such as absolute spread and correlation are identical in either direction.

Largest recent mean absolute spreads among pairs with at least three years of overlap:

- Finland / Italy: 87.8 EUR/MWh; hourly-change correlation 0.28.
- Finland / Ireland: 87.1 EUR/MWh; hourly-change correlation 0.15.
- Italy / Sweden: 81.4 EUR/MWh; hourly-change correlation 0.41.
- Finland / North Macedonia: 81.1 EUR/MWh; hourly-change correlation 0.18.
- Finland / Romania: 80.4 EUR/MWh; hourly-change correlation 0.26.
- Finland / Montenegro: 80.3 EUR/MWh; hourly-change correlation 0.18.
- Finland / Hungary: 79.9 EUR/MWh; hourly-change correlation 0.27.
- Finland / Serbia: 79.4 EUR/MWh; hourly-change correlation 0.28.

Closest recent price pairs:

- Germany / Luxembourg: 0.0 EUR/MWh; within EUR 5/MWh for 100.0% of the full overlap.
- Latvia / Lithuania: 0.7 EUR/MWh; within EUR 5/MWh for 97.8% of the full overlap.
- Portugal / Spain: 1.2 EUR/MWh; within EUR 5/MWh for 97.3% of the full overlap.
- Bulgaria / Romania: 3.4 EUR/MWh; within EUR 5/MWh for 65.4% of the full overlap.
- Croatia / Slovenia: 3.9 EUR/MWh; within EUR 5/MWh for 86.9% of the full overlap.
- Hungary / Romania: 7.0 EUR/MWh; within EUR 5/MWh for 81.7% of the full overlap.
- Belgium / Netherlands: 7.9 EUR/MWh; within EUR 5/MWh for 67.6% of the full overlap.
- Germany / Netherlands: 8.6 EUR/MWh; within EUR 5/MWh for 57.5% of the full overlap.

Strongest recent convergence in absolute spread:

- France / Sweden: -6.51 EUR/MWh per year (converging).
- Italy / Serbia: -6.36 EUR/MWh per year (converging).
- Bulgaria / Greece: -5.21 EUR/MWh per year (converging).
- Portugal / Sweden: -5.05 EUR/MWh per year (converging).
- Norway / Portugal: -5.00 EUR/MWh per year (converging).
- Greece / Hungary: -4.82 EUR/MWh per year (converging).

Largest recent widening in absolute spread:

- France / Serbia: +19.20 EUR/MWh per year.
- France / Hungary: +16.39 EUR/MWh per year.
- France / Slovenia: +16.03 EUR/MWh per year.
- Croatia / France: +15.27 EUR/MWh per year.
- France / Italy: +14.52 EUR/MWh per year.
- France / Slovakia: +14.47 EUR/MWh per year.

Lowest conditional P95 high-price coincidence (greater scarcity diversification):

- Finland / Montenegro: 14.1%.
- Finland / North Macedonia: 14.2%.
- Latvia / Spain: 22.6%.
- Latvia / Portugal: 22.6%.
- Lithuania / Spain: 23.2%.
- Lithuania / Portugal: 23.2%.

Highest conditional P95 high-price coincidence:

- Germany / Luxembourg: 100.0%.
- Portugal / Spain: 99.8%.
- Latvia / Lithuania: 97.3%.
- Croatia / Slovenia: 96.6%.
- Hungary / Romania: 93.5%.
- Czechia / Germany: 92.0%.

Hourly price-change clusters:

- Cluster 1: Ireland, United Kingdom.
- Cluster 2: Portugal, Spain.
- Cluster 3: Estonia, Latvia, Lithuania.
- Cluster 4: Norway, Finland, Sweden.
- Cluster 5: France, Albania, Italy, Montenegro, Bulgaria, Greece, North Macedonia, Serbia, Slovakia, Croatia, Slovenia, Hungary, Romania, Poland, Switzerland, Belgium, Netherlands, Denmark, Czechia, Austria, Germany, Luxembourg.
- Cluster 6: Moldova.

Pairwise outputs:

- `pairwise_market_spread_summary.csv`: complete distribution, direction, correlation, tail and persistence metrics for every eligible pair.
- `pairwise_market_annual_summary.csv`, `pairwise_market_seasonal_summary.csv`, and `pairwise_market_month_of_year_summary.csv`: time and seasonal cuts.
- `pairwise_market_rolling_monthly.csv.gz`: month-end snapshots of rolling pairwise spread and correlation metrics.
- `pairwise_market_spread_trend_summary.csv`: complete-year OLS, robust and recent convergence checks.
- `pairwise_market_lag_correlation_summary.csv` and `pairwise_market_best_lag_summary.csv`: hourly-change lags; positive lag means market B leads market A.
- `pairwise_*_matrix.csv`: presentation-ready matrices for spreads, convergence, correlation, price proximity, tail coincidence and lag direction.
- `market_price_change_clusters.csv`: hierarchical clusters based on hourly price-change correlation.
- `figures/pairwise_markets/`: pairwise heatmaps and the largest recent price-separation chart.
