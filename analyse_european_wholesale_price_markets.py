"""Analyse European hourly wholesale electricity prices relative to GB.

The source dataset contains one country-level hourly price series per market.
It does not distinguish bidding zones within multi-zone countries. All times are
analysed in UTC and all prices are expected to use the source unit EUR/MWh.

Conventions
-----------
* ``spread_gb_minus_market`` = GB price - comparison-market price.
* A positive spread means GB is more expensive than the comparison market.
* A positive lag means the comparison market leads GB. For example, +3 hours
  correlates the market price/change at t-3 with GB at t.
* Lag correlations are descriptive. In particular, price-level correlations
  can be inflated by common trends and serial correlation, so first-difference
  lag results are also reported and should receive more weight.
"""

from __future__ import annotations

import argparse
import math
import re
import textwrap
from itertools import combinations
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


DEFAULT_DATA_PATH = (
    Path.home()
    / "Documents"
    / "My Work"
    / "european_wholesale_electricity_price_data_hourly"
)
DEFAULT_OUTPUT_DIR = Path("analysis_outputs") / "european_wholesale_price_markets"
EXPECTED_COLUMNS = {
    "Country",
    "ISO3 Code",
    "Datetime (UTC)",
    "Price (EUR/MWhe)",
}
SEASON_ORDER = ["Winter", "Spring", "Summer", "Autumn"]
SPREAD_BINS = [
    -math.inf,
    -100,
    -50,
    -25,
    -10,
    -5,
    -1,
    1,
    5,
    10,
    25,
    50,
    100,
    math.inf,
]
SPREAD_LABELS = [
    "market_gt_gb_100_plus",
    "market_gt_gb_50_100",
    "market_gt_gb_25_50",
    "market_gt_gb_10_25",
    "market_gt_gb_5_10",
    "market_gt_gb_1_5",
    "near_parity_1",
    "gb_gt_market_1_5",
    "gb_gt_market_5_10",
    "gb_gt_market_10_25",
    "gb_gt_market_25_50",
    "gb_gt_market_50_100",
    "gb_gt_market_100_plus",
]
SPREAD_DISPLAY = {
    "market_gt_gb_100_plus": "Market > GB by >100",
    "market_gt_gb_50_100": "Market > GB by 50-100",
    "market_gt_gb_25_50": "Market > GB by 25-50",
    "market_gt_gb_10_25": "Market > GB by 10-25",
    "market_gt_gb_5_10": "Market > GB by 5-10",
    "market_gt_gb_1_5": "Market > GB by 1-5",
    "near_parity_1": "Within +/-1",
    "gb_gt_market_1_5": "GB > market by 1-5",
    "gb_gt_market_5_10": "GB > market by 5-10",
    "gb_gt_market_10_25": "GB > market by 10-25",
    "gb_gt_market_25_50": "GB > market by 25-50",
    "gb_gt_market_50_100": "GB > market by 50-100",
    "gb_gt_market_100_plus": "GB > market by >100",
}


def parse_number_list(value: str, cast: type = int) -> list:
    values = [cast(part.strip()) for part in value.split(",") if part.strip()]
    if not values:
        raise argparse.ArgumentTypeError("Provide at least one comma-separated number.")
    return values


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare European hourly wholesale electricity markets with GB and "
            "generate historical, seasonal, rolling, lag and tail-event analysis."
        )
    )
    parser.add_argument(
        "--data-path",
        type=Path,
        default=DEFAULT_DATA_PATH,
        help=(
            "Directory containing all_countries.csv/country CSVs, or a single "
            "long-form CSV."
        ),
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--gb-country", default="United Kingdom")
    parser.add_argument("--start", default=None, help="Inclusive UTC start timestamp.")
    parser.add_argument("--end", default=None, help="Inclusive UTC end timestamp.")
    parser.add_argument(
        "--markets",
        default=None,
        help="Optional comma-separated country names. GB is added automatically.",
    )
    parser.add_argument(
        "--lags-hours",
        default="-168,-72,-48,-24,-12,-6,-3,-1,0,1,3,6,12,24,48,72,168",
        help="Comma-separated lags. Positive values mean the comparison market leads GB.",
    )
    parser.add_argument(
        "--rolling-windows-days",
        default="30,90,365",
        help="Comma-separated daily rolling windows.",
    )
    parser.add_argument(
        "--pairwise-lags-hours",
        default="-24,-6,-1,0,1,6,24",
        help=(
            "Comma-separated lags for all-market-pair hourly-change correlations. "
            "Positive values mean market B leads market A."
        ),
    )
    parser.add_argument(
        "--pairwise-rolling-windows-days",
        default="90,365",
        help="Comma-separated pairwise rolling windows, sampled at month end.",
    )
    parser.add_argument(
        "--pairwise-clusters",
        type=int,
        default=6,
        help="Number of hourly-price-change clusters in the pairwise comparison.",
    )
    parser.add_argument("--recent-years", type=int, default=3)
    parser.add_argument("--price-deadband", type=float, default=1.0)
    parser.add_argument("--minimum-overlap-hours", type=int, default=24 * 30)
    parser.add_argument("--minimum-hours-per-day", type=int, default=18)
    parser.add_argument(
        "--histogram-bin-width",
        type=float,
        default=5.0,
        help="Spread-distribution bin width in EUR/MWh.",
    )
    parser.add_argument("--no-figures", action="store_true")
    parser.add_argument(
        "--no-pairwise",
        action="store_true",
        help="Skip the all-market-pair extension and retain only GB comparisons.",
    )
    return parser.parse_args()


def write_csv(df: pd.DataFrame, path: Path, *, index: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=index)


def safe_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def season_from_month(month: pd.Series) -> pd.Series:
    return pd.Series(
        np.select(
            [month.isin([12, 1, 2]), month.isin([3, 4, 5]), month.isin([6, 7, 8])],
            ["Winter", "Spring", "Summer"],
            default="Autumn",
        ),
        index=month.index,
    )


def parse_timestamp(value: str | None) -> pd.Timestamp | None:
    if value is None:
        return None
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert("UTC").tz_localize(None)
    return timestamp


def find_input_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if not path.exists():
        raise FileNotFoundError(f"Price data path not found: {path}")
    combined = path / "all_countries.csv"
    if combined.exists():
        return [combined]
    files = sorted(path.glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"No CSV files found under {path}")
    return files


def read_price_data(
    path: Path,
    selected_countries: set[str] | None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    source_rows: list[dict[str, object]] = []
    for file in find_input_files(path):
        header = pd.read_csv(file, nrows=0)
        missing = EXPECTED_COLUMNS - set(header.columns)
        if missing:
            raise ValueError(f"{file} is missing required columns: {sorted(missing)}")
        frame = pd.read_csv(
            file,
            usecols=list(EXPECTED_COLUMNS),
            dtype={"Country": "string", "ISO3 Code": "string", "Price (EUR/MWhe)": "float64"},
        )
        if selected_countries:
            frame = frame[frame["Country"].isin(selected_countries)].copy()
        source_rows.append(
            {
                "source_file": str(file.resolve()),
                "rows_read_after_market_filter": len(frame),
                "file_size_bytes": file.stat().st_size,
            }
        )
        frames.append(frame)
    if not frames:
        raise ValueError("No price rows were read.")
    prices = pd.concat(frames, ignore_index=True)
    prices = prices.rename(
        columns={
            "ISO3 Code": "iso3",
            "Datetime (UTC)": "timestamp_utc",
            "Price (EUR/MWhe)": "price_eur_mwh",
        }
    )
    prices["timestamp_utc"] = pd.to_datetime(prices["timestamp_utc"], errors="coerce")
    prices["price_eur_mwh"] = pd.to_numeric(prices["price_eur_mwh"], errors="coerce")
    return prices, pd.DataFrame(source_rows)


def longest_missing_run_hours(valid_index: pd.DatetimeIndex) -> int:
    if len(valid_index) < 2:
        return 0
    gaps = valid_index.to_series().sort_values().diff().dt.total_seconds().div(3600).sub(1)
    return int(max(0, gaps.max(skipna=True)))


def clean_and_summarise_source(
    raw: pd.DataFrame,
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    quality_rows: list[dict[str, object]] = []
    for (country, iso3), group in raw.groupby(["Country", "iso3"], dropna=False, observed=True):
        valid_time = group["timestamp_utc"].notna()
        valid_price = group["price_eur_mwh"].notna()
        valid = valid_time & valid_price
        valid_index = pd.DatetimeIndex(group.loc[valid, "timestamp_utc"].sort_values().unique())
        first = valid_index.min() if len(valid_index) else pd.NaT
        last = valid_index.max() if len(valid_index) else pd.NaT
        expected = int((last - first) / pd.Timedelta(hours=1)) + 1 if pd.notna(first) else 0
        quality_rows.append(
            {
                "market": country,
                "iso3": iso3,
                "source_rows": len(group),
                "valid_rows": int(valid.sum()),
                "missing_timestamp_rows": int((~valid_time).sum()),
                "missing_price_rows": int((valid_time & ~valid_price).sum()),
                "duplicate_market_timestamp_rows": int(
                    group.loc[valid_time].duplicated(["Country", "timestamp_utc"], keep=False).sum()
                ),
                "first_valid_timestamp_utc": first,
                "last_valid_timestamp_utc": last,
                "expected_hourly_rows_between_first_last": expected,
                "hourly_coverage_share": len(valid_index) / expected if expected else np.nan,
                "longest_internal_gap_hours": longest_missing_run_hours(valid_index),
            }
        )

    clean = raw.dropna(subset=["Country", "timestamp_utc", "price_eur_mwh"]).copy()
    if start is not None:
        clean = clean[clean["timestamp_utc"] >= start]
    if end is not None:
        clean = clean[clean["timestamp_utc"] <= end]

    duplicate_summary = (
        clean.groupby(["Country", "timestamp_utc"], observed=True)
        .agg(
            duplicate_rows=("price_eur_mwh", "size"),
            minimum_price_eur_mwh=("price_eur_mwh", "min"),
            maximum_price_eur_mwh=("price_eur_mwh", "max"),
        )
        .reset_index()
    )
    duplicate_summary = duplicate_summary[duplicate_summary["duplicate_rows"] > 1].copy()
    clean = (
        clean.groupby(["Country", "timestamp_utc"], as_index=False, observed=True)
        .agg(iso3=("iso3", "first"), price_eur_mwh=("price_eur_mwh", "mean"))
        .sort_values(["timestamp_utc", "Country"])
    )
    return clean, pd.DataFrame(quality_rows), duplicate_summary


def describe_prices(clean: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for (market, iso3), group in clean.groupby(["Country", "iso3"], observed=True):
        price = group["price_eur_mwh"]
        q = price.quantile([0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99])
        rows.append(
            {
                "market": market,
                "iso3": iso3,
                "first_timestamp_utc": group["timestamp_utc"].min(),
                "last_timestamp_utc": group["timestamp_utc"].max(),
                "observations": len(group),
                "mean_price_eur_mwh": price.mean(),
                "median_price_eur_mwh": q.loc[0.50],
                "std_price_eur_mwh": price.std(),
                "minimum_price_eur_mwh": price.min(),
                "p01_price_eur_mwh": q.loc[0.01],
                "p05_price_eur_mwh": q.loc[0.05],
                "p10_price_eur_mwh": q.loc[0.10],
                "p25_price_eur_mwh": q.loc[0.25],
                "p75_price_eur_mwh": q.loc[0.75],
                "p90_price_eur_mwh": q.loc[0.90],
                "p95_price_eur_mwh": q.loc[0.95],
                "p99_price_eur_mwh": q.loc[0.99],
                "maximum_price_eur_mwh": price.max(),
                "negative_price_share": price.lt(0).mean(),
                "zero_or_negative_price_share": price.le(0).mean(),
                "price_above_100_share": price.gt(100).mean(),
                "price_above_200_share": price.gt(200).mean(),
                "price_above_500_share": price.gt(500).mean(),
            }
        )
    return pd.DataFrame(rows).sort_values("market")


def safe_corr(left: pd.Series, right: pd.Series, method: str = "pearson") -> float:
    paired = pd.concat([left, right], axis=1).dropna()
    if len(paired) < 3 or paired.iloc[:, 0].nunique() < 2 or paired.iloc[:, 1].nunique() < 2:
        return np.nan
    return paired.iloc[:, 0].corr(paired.iloc[:, 1], method=method)


def contiguous_hourly_changes(pair: pd.DataFrame) -> pd.DataFrame:
    pair = pair.dropna().sort_index()
    changes = pair.diff()
    contiguous = pair.index.to_series().diff().eq(pd.Timedelta(hours=1))
    return changes.loc[contiguous.to_numpy()].dropna()


def linear_slope_per_year(dates: pd.Series | pd.DatetimeIndex, values: pd.Series) -> float:
    date_series = pd.Series(pd.to_datetime(dates).to_numpy(), index=values.index)
    valid = values.notna() & date_series.notna()
    if valid.sum() < 2 or values.loc[valid].nunique() < 2:
        return np.nan
    years = (date_series.loc[valid] - date_series.loc[valid].min()).dt.total_seconds() / (365.25 * 86400)
    return float(np.polyfit(years, values.loc[valid].astype(float), 1)[0])


def median_pairwise_slope_per_year(years: pd.Series, values: pd.Series) -> float:
    valid = pd.DataFrame({"year": years, "value": values}).dropna().sort_values("year")
    if len(valid) < 2:
        return np.nan
    slopes: list[float] = []
    year_values = valid["year"].to_numpy(dtype=float)
    observations = valid["value"].to_numpy(dtype=float)
    for left in range(len(valid) - 1):
        for right in range(left + 1, len(valid)):
            year_gap = year_values[right] - year_values[left]
            if year_gap:
                slopes.append((observations[right] - observations[left]) / year_gap)
    return float(np.median(slopes)) if slopes else np.nan


def ols_gb_on_market(pair: pd.DataFrame) -> tuple[float, float, float]:
    paired = pair.dropna()
    if len(paired) < 3 or paired["market_price_eur_mwh"].nunique() < 2:
        return np.nan, np.nan, np.nan
    slope, intercept = np.polyfit(
        paired["market_price_eur_mwh"].to_numpy(),
        paired["gb_price_eur_mwh"].to_numpy(),
        1,
    )
    corr = safe_corr(paired["gb_price_eur_mwh"], paired["market_price_eur_mwh"])
    return float(slope), float(intercept), float(corr**2)


def make_market_pair(wide: pd.DataFrame, gb_country: str, market: str) -> pd.DataFrame:
    pair = wide[[gb_country, market]].rename(
        columns={gb_country: "gb_price_eur_mwh", market: "market_price_eur_mwh"}
    )
    pair = pair.dropna().sort_index()
    pair["spread_gb_minus_market_eur_mwh"] = (
        pair["gb_price_eur_mwh"] - pair["market_price_eur_mwh"]
    )
    pair["absolute_spread_eur_mwh"] = pair["spread_gb_minus_market_eur_mwh"].abs()
    return pair


def pair_summary(
    pair: pd.DataFrame,
    market: str,
    iso3: str,
    deadband: float,
    recent_years: int,
) -> dict[str, object]:
    spread = pair["spread_gb_minus_market_eur_mwh"]
    changes = contiguous_hourly_changes(pair[["gb_price_eur_mwh", "market_price_eur_mwh"]])
    slope, intercept, r_squared = ols_gb_on_market(pair)
    recent_cutoff = pair.index.max() - pd.DateOffset(years=recent_years)
    recent = pair[pair.index >= recent_cutoff]
    return {
        "market": market,
        "iso3": iso3,
        "overlap_start_utc": pair.index.min(),
        "overlap_end_utc": pair.index.max(),
        "overlap_observations": len(pair),
        "overlap_years": (pair.index.max() - pair.index.min()).total_seconds() / (365.25 * 86400),
        "gb_mean_price_eur_mwh": pair["gb_price_eur_mwh"].mean(),
        "market_mean_price_eur_mwh": pair["market_price_eur_mwh"].mean(),
        "mean_spread_gb_minus_market_eur_mwh": spread.mean(),
        "median_spread_gb_minus_market_eur_mwh": spread.median(),
        "mean_absolute_spread_eur_mwh": spread.abs().mean(),
        "median_absolute_spread_eur_mwh": spread.abs().median(),
        "p90_absolute_spread_eur_mwh": spread.abs().quantile(0.90),
        "p95_absolute_spread_eur_mwh": spread.abs().quantile(0.95),
        "gb_higher_share": spread.gt(deadband).mean(),
        "market_higher_share": spread.lt(-deadband).mean(),
        "near_parity_share": spread.abs().le(deadband).mean(),
        "within_5_eur_share": spread.abs().le(5).mean(),
        "within_10_eur_share": spread.abs().le(10).mean(),
        "price_level_pearson_correlation": safe_corr(
            pair["gb_price_eur_mwh"], pair["market_price_eur_mwh"]
        ),
        "price_level_spearman_correlation": safe_corr(
            pair["gb_price_eur_mwh"], pair["market_price_eur_mwh"], "spearman"
        ),
        "hourly_change_pearson_correlation": safe_corr(
            changes["gb_price_eur_mwh"], changes["market_price_eur_mwh"]
        ),
        "hourly_change_spearman_correlation": safe_corr(
            changes["gb_price_eur_mwh"], changes["market_price_eur_mwh"], "spearman"
        ),
        "ols_gb_on_market_slope": slope,
        "ols_gb_on_market_intercept_eur_mwh": intercept,
        "ols_gb_on_market_r_squared": r_squared,
        "recent_window_years": recent_years,
        "recent_mean_spread_gb_minus_market_eur_mwh": recent[
            "spread_gb_minus_market_eur_mwh"
        ].mean(),
        "recent_mean_absolute_spread_eur_mwh": recent["absolute_spread_eur_mwh"].mean(),
        "recent_price_level_pearson_correlation": safe_corr(
            recent["gb_price_eur_mwh"], recent["market_price_eur_mwh"]
        ),
    }


def grouped_relationship_summary(
    pair: pd.DataFrame,
    market: str,
    iso3: str,
    group_values: pd.Series,
    group_name: str,
    deadband: float,
) -> pd.DataFrame:
    work = pair.copy()
    work[group_name] = group_values.to_numpy()
    rows: list[dict[str, object]] = []
    for group_value, group in work.groupby(group_name, observed=True):
        spread = group["spread_gb_minus_market_eur_mwh"]
        rows.append(
            {
                "market": market,
                "iso3": iso3,
                group_name: group_value,
                "observations": len(group),
                "gb_mean_price_eur_mwh": group["gb_price_eur_mwh"].mean(),
                "market_mean_price_eur_mwh": group["market_price_eur_mwh"].mean(),
                "mean_spread_gb_minus_market_eur_mwh": spread.mean(),
                "median_spread_gb_minus_market_eur_mwh": spread.median(),
                "mean_absolute_spread_eur_mwh": spread.abs().mean(),
                "p90_absolute_spread_eur_mwh": spread.abs().quantile(0.90),
                "gb_higher_share": spread.gt(deadband).mean(),
                "market_higher_share": spread.lt(-deadband).mean(),
                "near_parity_share": spread.abs().le(deadband).mean(),
                "price_level_pearson_correlation": safe_corr(
                    group["gb_price_eur_mwh"], group["market_price_eur_mwh"]
                ),
                "price_level_spearman_correlation": safe_corr(
                    group["gb_price_eur_mwh"], group["market_price_eur_mwh"], "spearman"
                ),
            }
        )
    return pd.DataFrame(rows)


def build_calendar_summaries(
    pair: pd.DataFrame,
    market: str,
    iso3: str,
    deadband: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    timestamps = pd.Series(pair.index, index=pair.index)
    annual = grouped_relationship_summary(
        pair, market, iso3, timestamps.dt.year, "year", deadband
    )
    annual["expected_hours_in_calendar_year"] = annual["year"].map(
        lambda year: int(
            (pd.Timestamp(f"{int(year) + 1}-01-01") - pd.Timestamp(f"{int(year)}-01-01"))
            / pd.Timedelta(hours=1)
        )
    )
    annual["calendar_year_coverage_share"] = (
        annual["observations"] / annual["expected_hours_in_calendar_year"]
    )
    annual["complete_calendar_year_90pct"] = annual["calendar_year_coverage_share"].ge(0.90)
    monthly = grouped_relationship_summary(
        pair,
        market,
        iso3,
        timestamps.dt.to_period("M").astype(str),
        "year_month",
        deadband,
    )
    seasons = season_from_month(timestamps.dt.month)
    seasonal = grouped_relationship_summary(pair, market, iso3, seasons, "season", deadband)
    month_profile = grouped_relationship_summary(
        pair, market, iso3, timestamps.dt.month, "month", deadband
    )
    month_profile["month_name"] = pd.to_datetime(
        month_profile["month"], format="%m"
    ).dt.strftime("%b")
    hour_profile = grouped_relationship_summary(
        pair, market, iso3, timestamps.dt.hour, "hour_utc", deadband
    )
    return annual, monthly, seasonal, month_profile, hour_profile


def build_month_hour_profile(pair: pd.DataFrame, market: str, iso3: str) -> pd.DataFrame:
    work = pair.copy()
    work["month"] = work.index.month
    work["hour_utc"] = work.index.hour
    return (
        work.groupby(["month", "hour_utc"], observed=True)
        .agg(
            observations=("spread_gb_minus_market_eur_mwh", "size"),
            mean_spread_gb_minus_market_eur_mwh=(
                "spread_gb_minus_market_eur_mwh",
                "mean",
            ),
            median_spread_gb_minus_market_eur_mwh=(
                "spread_gb_minus_market_eur_mwh",
                "median",
            ),
            mean_absolute_spread_eur_mwh=("absolute_spread_eur_mwh", "mean"),
        )
        .reset_index()
        .assign(market=market, iso3=iso3)
    )


def build_lag_summary(
    pair: pd.DataFrame,
    market: str,
    iso3: str,
    lags: Iterable[int],
) -> pd.DataFrame:
    full_index = pd.date_range(pair.index.min(), pair.index.max(), freq="h")
    prices = pair[["gb_price_eur_mwh", "market_price_eur_mwh"]].reindex(full_index)
    changes = prices.diff()
    rows: list[dict[str, object]] = []
    for metric, data in (("price_level", prices), ("hourly_first_difference", changes)):
        for lag in lags:
            joined = pd.concat(
                [
                    data["gb_price_eur_mwh"].rename("gb"),
                    data["market_price_eur_mwh"].shift(lag).rename("market_lagged"),
                ],
                axis=1,
            ).dropna()
            rows.append(
                {
                    "market": market,
                    "iso3": iso3,
                    "metric": metric,
                    "lag_hours_market_leads_if_positive": lag,
                    "observations": len(joined),
                    "pearson_correlation": safe_corr(joined["gb"], joined["market_lagged"]),
                    "spearman_correlation": safe_corr(
                        joined["gb"], joined["market_lagged"], "spearman"
                    ),
                }
            )
    return pd.DataFrame(rows)


def build_daily_and_rolling(
    pair: pd.DataFrame,
    market: str,
    iso3: str,
    windows: Iterable[int],
    minimum_hours_per_day: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    daily = pair.resample("D").agg(
        gb_price_eur_mwh=("gb_price_eur_mwh", "mean"),
        market_price_eur_mwh=("market_price_eur_mwh", "mean"),
        spread_gb_minus_market_eur_mwh=("spread_gb_minus_market_eur_mwh", "mean"),
        mean_absolute_hourly_spread_eur_mwh=("absolute_spread_eur_mwh", "mean"),
        observations=("spread_gb_minus_market_eur_mwh", "size"),
    )
    daily = daily[daily["observations"] >= minimum_hours_per_day].copy()
    daily["market"] = market
    daily["iso3"] = iso3
    daily = daily.reset_index(names="date_utc")

    base = daily.set_index("date_utc").sort_index()
    rolling_frames: list[pd.DataFrame] = []
    for window in windows:
        min_periods = max(10, math.ceil(window * 0.70))
        rolling = pd.DataFrame(index=base.index)
        rolling["rolling_gb_mean_price_eur_mwh"] = base["gb_price_eur_mwh"].rolling(
            window, min_periods=min_periods
        ).mean()
        rolling["rolling_market_mean_price_eur_mwh"] = base[
            "market_price_eur_mwh"
        ].rolling(window, min_periods=min_periods).mean()
        rolling["rolling_mean_spread_gb_minus_market_eur_mwh"] = base[
            "spread_gb_minus_market_eur_mwh"
        ].rolling(window, min_periods=min_periods).mean()
        rolling["rolling_mean_absolute_hourly_spread_eur_mwh"] = base[
            "mean_absolute_hourly_spread_eur_mwh"
        ].rolling(window, min_periods=min_periods).mean()
        rolling["rolling_daily_price_correlation"] = base["gb_price_eur_mwh"].rolling(
            window, min_periods=min_periods
        ).corr(base["market_price_eur_mwh"])
        rolling["window_days"] = window
        rolling["market"] = market
        rolling["iso3"] = iso3
        rolling_frames.append(rolling.reset_index(names="date_utc"))
    return daily, pd.concat(rolling_frames, ignore_index=True)


def build_spread_bands(
    pair: pd.DataFrame,
    market: str,
    iso3: str,
) -> pd.DataFrame:
    work = pair.copy()
    work["spread_band"] = pd.cut(
        work["spread_gb_minus_market_eur_mwh"],
        bins=SPREAD_BINS,
        labels=SPREAD_LABELS,
        include_lowest=True,
    )
    summary = (
        work.groupby("spread_band", observed=False)
        .agg(
            observations=("spread_gb_minus_market_eur_mwh", "size"),
            mean_gb_price_eur_mwh=("gb_price_eur_mwh", "mean"),
            mean_market_price_eur_mwh=("market_price_eur_mwh", "mean"),
            mean_spread_gb_minus_market_eur_mwh=(
                "spread_gb_minus_market_eur_mwh",
                "mean",
            ),
            median_spread_gb_minus_market_eur_mwh=(
                "spread_gb_minus_market_eur_mwh",
                "median",
            ),
        )
        .reset_index()
    )
    summary["observation_share"] = summary["observations"] / len(work)
    summary["spread_band_order"] = np.arange(len(summary))
    summary["spread_band_display"] = summary["spread_band"].astype(str).map(SPREAD_DISPLAY).fillna(
        summary["spread_band"].astype(str)
    )
    summary["market"] = market
    summary["iso3"] = iso3
    return summary


def build_spread_runs(
    pair: pd.DataFrame,
    market: str,
    iso3: str,
    deadband: float,
) -> pd.DataFrame:
    full_index = pd.date_range(pair.index.min(), pair.index.max(), freq="h")
    spread = pair["spread_gb_minus_market_eur_mwh"].reindex(full_index)
    state = pd.Series(
        np.select(
            [spread.gt(deadband), spread.lt(-deadband), spread.notna()],
            ["gb_higher", "market_higher", "near_parity"],
            default="missing",
        ),
        index=full_index,
    )
    run_id = state.ne(state.shift()).cumsum()
    runs = (
        pd.DataFrame({"state": state, "run_id": run_id})
        .groupby(["state", "run_id"], observed=True)
        .size()
        .rename("run_hours")
        .reset_index()
    )
    runs = runs[runs["state"] != "missing"]
    summary = (
        runs.groupby("state", observed=True)["run_hours"]
        .agg(number_of_runs="size", mean_run_hours="mean", median_run_hours="median", maximum_run_hours="max")
        .reset_index()
    )
    summary["p90_run_hours"] = runs.groupby("state", observed=True)["run_hours"].quantile(0.90).to_numpy()
    summary["p95_run_hours"] = runs.groupby("state", observed=True)["run_hours"].quantile(0.95).to_numpy()
    summary["market"] = market
    summary["iso3"] = iso3
    return summary


def build_tail_events(pair: pd.DataFrame, market: str, iso3: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    quantiles = [0.01, 0.05, 0.10, 0.90, 0.95, 0.99]
    for trigger_name, trigger_col, other_col in (
        ("GB", "gb_price_eur_mwh", "market_price_eur_mwh"),
        ("comparison_market", "market_price_eur_mwh", "gb_price_eur_mwh"),
    ):
        trigger = pair[trigger_col]
        other = pair[other_col]
        for quantile in quantiles:
            threshold = trigger.quantile(quantile)
            is_low = quantile < 0.5
            event_mask = trigger.le(threshold) if is_low else trigger.ge(threshold)
            event = pair[event_mask]
            other_threshold = other.quantile(quantile)
            same_tail = (
                event[other_col].le(other_threshold).mean()
                if is_low
                else event[other_col].ge(other_threshold).mean()
            )
            rows.append(
                {
                    "market": market,
                    "iso3": iso3,
                    "trigger_market": trigger_name,
                    "tail": "low" if is_low else "high",
                    "quantile": quantile,
                    "event_label": f"P{int(round(quantile * 100)):02d}",
                    "trigger_threshold_eur_mwh": threshold,
                    "observations": len(event),
                    "mean_gb_price_eur_mwh": event["gb_price_eur_mwh"].mean(),
                    "mean_market_price_eur_mwh": event["market_price_eur_mwh"].mean(),
                    "mean_spread_gb_minus_market_eur_mwh": event[
                        "spread_gb_minus_market_eur_mwh"
                    ].mean(),
                    "median_spread_gb_minus_market_eur_mwh": event[
                        "spread_gb_minus_market_eur_mwh"
                    ].median(),
                    "mean_absolute_spread_eur_mwh": event["absolute_spread_eur_mwh"].mean(),
                    "other_market_same_tail_share": same_tail,
                }
            )
    return pd.DataFrame(rows)


def build_spread_histogram(
    pair: pd.DataFrame,
    market: str,
    iso3: str,
    bin_width: float,
) -> pd.DataFrame:
    spread = pair["spread_gb_minus_market_eur_mwh"].dropna()
    low = math.floor(spread.quantile(0.001) / bin_width) * bin_width
    high = math.ceil(spread.quantile(0.999) / bin_width) * bin_width
    if high <= low:
        high = low + bin_width
    edges = np.arange(low, high + 2 * bin_width, bin_width)
    clipped = spread.clip(low, high)
    counts, edges = np.histogram(clipped, bins=edges)
    return pd.DataFrame(
        {
            "market": market,
            "iso3": iso3,
            "bin_left_eur_mwh": edges[:-1],
            "bin_right_eur_mwh": edges[1:],
            "bin_midpoint_eur_mwh": (edges[:-1] + edges[1:]) / 2,
            "observations": counts,
            "probability": counts / counts.sum(),
            "bin_width_eur_mwh": bin_width,
            "lower_tail_clipped_at_eur_mwh": low,
            "upper_tail_clipped_at_eur_mwh": high,
        }
    )


def make_pairwise_market_pair(wide: pd.DataFrame, market_a: str, market_b: str) -> pd.DataFrame:
    pair = wide[[market_a, market_b]].rename(
        columns={market_a: "market_a_price_eur_mwh", market_b: "market_b_price_eur_mwh"}
    )
    pair = pair.dropna().sort_index()
    pair["spread_a_minus_b_eur_mwh"] = (
        pair["market_a_price_eur_mwh"] - pair["market_b_price_eur_mwh"]
    )
    pair["absolute_spread_eur_mwh"] = pair["spread_a_minus_b_eur_mwh"].abs()
    return pair


def spread_run_metrics(spread: pd.Series, deadband: float) -> dict[str, float]:
    full_index = pd.date_range(spread.index.min(), spread.index.max(), freq="h")
    values = spread.reindex(full_index).to_numpy(dtype=float)
    state = np.full(len(values), 9, dtype=np.int8)
    valid = np.isfinite(values)
    state[valid & (values > deadband)] = 1
    state[valid & (values < -deadband)] = -1
    state[valid & (np.abs(values) <= deadband)] = 0
    if not len(state):
        return {}
    starts = np.flatnonzero(np.r_[True, state[1:] != state[:-1]])
    ends = np.r_[starts[1:], len(state)]
    run_states = state[starts]
    run_lengths = ends - starts
    output: dict[str, float] = {}
    for code, label in ((1, "market_a_higher"), (-1, "market_b_higher"), (0, "near_parity")):
        lengths = run_lengths[run_states == code]
        output[f"{label}_run_count"] = float(len(lengths))
        output[f"{label}_median_run_hours"] = float(np.median(lengths)) if len(lengths) else np.nan
        output[f"{label}_p90_run_hours"] = float(np.quantile(lengths, 0.90)) if len(lengths) else np.nan
        output[f"{label}_maximum_run_hours"] = float(lengths.max()) if len(lengths) else np.nan
    return output


def pairwise_market_summary(
    pair: pd.DataFrame,
    market_a: str,
    market_b: str,
    iso3_a: str,
    iso3_b: str,
    deadband: float,
    recent_years: int,
) -> dict[str, object]:
    spread = pair["spread_a_minus_b_eur_mwh"]
    price_columns = ["market_a_price_eur_mwh", "market_b_price_eur_mwh"]
    changes = contiguous_hourly_changes(pair[price_columns])
    recent_cutoff = pair.index.max() - pd.DateOffset(years=recent_years)
    recent = pair[pair.index >= recent_cutoff]
    market_a_price = pair["market_a_price_eur_mwh"]
    market_b_price = pair["market_b_price_eur_mwh"]
    a_p05, a_p95 = market_a_price.quantile([0.05, 0.95])
    b_p05, b_p95 = market_b_price.quantile([0.05, 0.95])
    a_high = market_a_price.ge(a_p95)
    b_high = market_b_price.ge(b_p95)
    a_low = market_a_price.le(a_p05)
    b_low = market_b_price.le(b_p05)
    signed_quantiles = spread.quantile([0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95])
    summary: dict[str, object] = {
        "market_a": market_a,
        "iso3_a": iso3_a,
        "market_b": market_b,
        "iso3_b": iso3_b,
        "spread_definition": "market_a price - market_b price",
        "overlap_start_utc": pair.index.min(),
        "overlap_end_utc": pair.index.max(),
        "overlap_observations": len(pair),
        "overlap_years": (pair.index.max() - pair.index.min()).total_seconds() / (365.25 * 86400),
        "market_a_mean_price_eur_mwh": market_a_price.mean(),
        "market_b_mean_price_eur_mwh": market_b_price.mean(),
        "mean_spread_a_minus_b_eur_mwh": spread.mean(),
        "median_spread_a_minus_b_eur_mwh": spread.median(),
        "p05_spread_a_minus_b_eur_mwh": signed_quantiles.loc[0.05],
        "p10_spread_a_minus_b_eur_mwh": signed_quantiles.loc[0.10],
        "p25_spread_a_minus_b_eur_mwh": signed_quantiles.loc[0.25],
        "p75_spread_a_minus_b_eur_mwh": signed_quantiles.loc[0.75],
        "p90_spread_a_minus_b_eur_mwh": signed_quantiles.loc[0.90],
        "p95_spread_a_minus_b_eur_mwh": signed_quantiles.loc[0.95],
        "spread_standard_deviation_eur_mwh": spread.std(),
        "mean_absolute_spread_eur_mwh": spread.abs().mean(),
        "median_absolute_spread_eur_mwh": spread.abs().median(),
        "p90_absolute_spread_eur_mwh": spread.abs().quantile(0.90),
        "p95_absolute_spread_eur_mwh": spread.abs().quantile(0.95),
        "market_a_higher_share": spread.gt(deadband).mean(),
        "market_b_higher_share": spread.lt(-deadband).mean(),
        "near_parity_share": spread.abs().le(deadband).mean(),
        "within_5_eur_share": spread.abs().le(5).mean(),
        "within_10_eur_share": spread.abs().le(10).mean(),
        "two_way_price_signal_balance": 2
        * min(spread.gt(deadband).mean(), spread.lt(-deadband).mean()),
        "price_level_pearson_correlation": safe_corr(market_a_price, market_b_price),
        "price_level_spearman_correlation": safe_corr(market_a_price, market_b_price, "spearman"),
        "hourly_change_pearson_correlation": safe_corr(
            changes["market_a_price_eur_mwh"], changes["market_b_price_eur_mwh"]
        ),
        "hourly_change_spearman_correlation": safe_corr(
            changes["market_a_price_eur_mwh"],
            changes["market_b_price_eur_mwh"],
            "spearman",
        ),
        "recent_window_years": recent_years,
        "recent_mean_spread_a_minus_b_eur_mwh": recent["spread_a_minus_b_eur_mwh"].mean(),
        "recent_mean_absolute_spread_eur_mwh": recent["absolute_spread_eur_mwh"].mean(),
        "recent_price_level_pearson_correlation": safe_corr(
            recent["market_a_price_eur_mwh"], recent["market_b_price_eur_mwh"]
        ),
        "market_b_high_p95_share_when_market_a_high_p95": b_high[a_high].mean(),
        "market_a_high_p95_share_when_market_b_high_p95": a_high[b_high].mean(),
        "joint_high_p95_share": (a_high & b_high).mean(),
        "market_b_low_p05_share_when_market_a_low_p05": b_low[a_low].mean(),
        "market_a_low_p05_share_when_market_b_low_p05": a_low[b_low].mean(),
        "joint_low_p05_share": (a_low & b_low).mean(),
        "mean_spread_when_market_a_high_p95_eur_mwh": spread[a_high].mean(),
        "mean_spread_when_market_b_high_p95_eur_mwh": spread[b_high].mean(),
    }
    summary.update(spread_run_metrics(spread, deadband))
    return summary


def pairwise_grouped_summary(
    pair: pd.DataFrame,
    market_a: str,
    market_b: str,
    iso3_a: str,
    iso3_b: str,
    group_values: pd.Series | pd.Index,
    group_name: str,
    deadband: float,
) -> pd.DataFrame:
    work = pair.copy()
    work[group_name] = np.asarray(group_values)
    rows: list[dict[str, object]] = []
    for group_value, group in work.groupby(group_name, observed=True):
        spread = group["spread_a_minus_b_eur_mwh"]
        rows.append(
            {
                "market_a": market_a,
                "iso3_a": iso3_a,
                "market_b": market_b,
                "iso3_b": iso3_b,
                group_name: group_value,
                "observations": len(group),
                "market_a_mean_price_eur_mwh": group["market_a_price_eur_mwh"].mean(),
                "market_b_mean_price_eur_mwh": group["market_b_price_eur_mwh"].mean(),
                "mean_spread_a_minus_b_eur_mwh": spread.mean(),
                "median_spread_a_minus_b_eur_mwh": spread.median(),
                "mean_absolute_spread_eur_mwh": spread.abs().mean(),
                "p90_absolute_spread_eur_mwh": spread.abs().quantile(0.90),
                "market_a_higher_share": spread.gt(deadband).mean(),
                "market_b_higher_share": spread.lt(-deadband).mean(),
                "near_parity_share": spread.abs().le(deadband).mean(),
                "within_5_eur_share": spread.abs().le(5).mean(),
                "price_level_pearson_correlation": safe_corr(
                    group["market_a_price_eur_mwh"], group["market_b_price_eur_mwh"]
                ),
            }
        )
    return pd.DataFrame(rows)


def build_pairwise_calendar_summaries(
    pair: pd.DataFrame,
    market_a: str,
    market_b: str,
    iso3_a: str,
    iso3_b: str,
    deadband: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    timestamp = pd.Series(pair.index, index=pair.index)
    annual = pairwise_grouped_summary(
        pair, market_a, market_b, iso3_a, iso3_b, timestamp.dt.year, "year", deadband
    )
    annual["expected_hours_in_calendar_year"] = annual["year"].map(
        lambda year: int(
            (pd.Timestamp(f"{int(year) + 1}-01-01") - pd.Timestamp(f"{int(year)}-01-01"))
            / pd.Timedelta(hours=1)
        )
    )
    annual["calendar_year_coverage_share"] = (
        annual["observations"] / annual["expected_hours_in_calendar_year"]
    )
    annual["complete_calendar_year_90pct"] = annual["calendar_year_coverage_share"].ge(0.90)
    seasonal = pairwise_grouped_summary(
        pair,
        market_a,
        market_b,
        iso3_a,
        iso3_b,
        season_from_month(timestamp.dt.month),
        "season",
        deadband,
    )
    month_profile = pairwise_grouped_summary(
        pair, market_a, market_b, iso3_a, iso3_b, timestamp.dt.month, "month", deadband
    )
    month_profile["month_name"] = pd.to_datetime(
        month_profile["month"], format="%m"
    ).dt.strftime("%b")
    return annual, seasonal, month_profile


def build_pairwise_rolling_monthly(
    pair: pd.DataFrame,
    market_a: str,
    market_b: str,
    iso3_a: str,
    iso3_b: str,
    windows: Iterable[int],
    minimum_hours_per_day: int,
) -> pd.DataFrame:
    daily = pair.resample("D").agg(
        market_a_price_eur_mwh=("market_a_price_eur_mwh", "mean"),
        market_b_price_eur_mwh=("market_b_price_eur_mwh", "mean"),
        mean_spread_a_minus_b_eur_mwh=("spread_a_minus_b_eur_mwh", "mean"),
        mean_absolute_hourly_spread_eur_mwh=("absolute_spread_eur_mwh", "mean"),
        observations=("spread_a_minus_b_eur_mwh", "size"),
    )
    daily = daily[daily["observations"] >= minimum_hours_per_day]
    frames: list[pd.DataFrame] = []
    for window in windows:
        min_periods = max(10, math.ceil(window * 0.70))
        rolling = pd.DataFrame(index=daily.index)
        rolling["rolling_mean_spread_a_minus_b_eur_mwh"] = daily[
            "mean_spread_a_minus_b_eur_mwh"
        ].rolling(window, min_periods=min_periods).mean()
        rolling["rolling_mean_absolute_hourly_spread_eur_mwh"] = daily[
            "mean_absolute_hourly_spread_eur_mwh"
        ].rolling(window, min_periods=min_periods).mean()
        rolling["rolling_daily_price_correlation"] = daily[
            "market_a_price_eur_mwh"
        ].rolling(window, min_periods=min_periods).corr(daily["market_b_price_eur_mwh"])
        sampled = rolling.resample("ME").last().dropna(how="all")
        sampled["window_days"] = window
        sampled["market_a"] = market_a
        sampled["iso3_a"] = iso3_a
        sampled["market_b"] = market_b
        sampled["iso3_b"] = iso3_b
        frames.append(sampled.reset_index(names="month_end_utc"))
    return pd.concat(frames, ignore_index=True)


def array_pearson(left: np.ndarray, right: np.ndarray) -> tuple[int, float]:
    valid = np.isfinite(left) & np.isfinite(right)
    observations = int(valid.sum())
    if observations < 3:
        return observations, np.nan
    x = left[valid].astype(float)
    y = right[valid].astype(float)
    x -= x.mean()
    y -= y.mean()
    denominator = math.sqrt(float(np.dot(x, x) * np.dot(y, y)))
    if denominator == 0:
        return observations, np.nan
    return observations, float(np.dot(x, y) / denominator)


def lagged_array_views(
    market_a_values: np.ndarray,
    market_b_values: np.ndarray,
    lag: int,
) -> tuple[np.ndarray, np.ndarray]:
    if lag > 0:
        return market_a_values[lag:], market_b_values[:-lag]
    if lag < 0:
        offset = abs(lag)
        return market_a_values[:-offset], market_b_values[offset:]
    return market_a_values, market_b_values


def build_pairwise_lag_summary(
    regular_wide: pd.DataFrame,
    pair_keys: list[tuple[str, str]],
    iso3_lookup: dict[str, str],
    lags: Iterable[int],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    changes = regular_wide.diff()
    rows: list[dict[str, object]] = []
    for market_a, market_b in pair_keys:
        a_values = changes[market_a].to_numpy(dtype=float)
        b_values = changes[market_b].to_numpy(dtype=float)
        for lag in lags:
            left, right = lagged_array_views(a_values, b_values, lag)
            observations, correlation = array_pearson(left, right)
            rows.append(
                {
                    "market_a": market_a,
                    "iso3_a": iso3_lookup.get(market_a, ""),
                    "market_b": market_b,
                    "iso3_b": iso3_lookup.get(market_b, ""),
                    "metric": "hourly_first_difference",
                    "lag_hours_market_b_leads_market_a_if_positive": lag,
                    "observations": observations,
                    "pearson_correlation": correlation,
                }
            )
    summary = pd.DataFrame(rows)
    candidates = summary[summary["lag_hours_market_b_leads_market_a_if_positive"] != 0].copy()
    candidates["absolute_pearson_correlation"] = candidates["pearson_correlation"].abs()
    best = (
        candidates.sort_values("absolute_pearson_correlation", ascending=False)
        .groupby(["market_a", "iso3_a", "market_b", "iso3_b"], observed=True, as_index=False)
        .first()
        .rename(
            columns={
                "lag_hours_market_b_leads_market_a_if_positive": "best_nonzero_lag_hours_market_b_leads_market_a_if_positive",
                "observations": "best_nonzero_lag_observations",
                "pearson_correlation": "best_nonzero_lag_pearson_correlation",
            }
        )
    )
    return summary, best


def pairwise_spread_trend_summary(
    annual: pd.DataFrame,
    pair_summary_df: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for (market_a, market_b), group in annual.groupby(["market_a", "market_b"], observed=True):
        group = group.sort_values("year")
        complete = group[group["complete_calendar_year_90pct"]].copy()
        recent = complete.tail(3)
        complete_dates = pd.to_datetime(complete["year"].astype(str) + "-07-01")
        recent_dates = pd.to_datetime(recent["year"].astype(str) + "-07-01")
        summary_row = pair_summary_df[
            (pair_summary_df["market_a"] == market_a) & (pair_summary_df["market_b"] == market_b)
        ].iloc[0]
        rows.append(
            {
                "market_a": market_a,
                "iso3_a": summary_row["iso3_a"],
                "market_b": market_b,
                "iso3_b": summary_row["iso3_b"],
                "annual_periods": len(group),
                "complete_calendar_years_used": len(complete),
                "first_complete_calendar_year": complete["year"].min() if not complete.empty else np.nan,
                "last_complete_calendar_year": complete["year"].max() if not complete.empty else np.nan,
                "mean_spread_trend_eur_mwh_per_year": linear_slope_per_year(
                    complete_dates,
                    complete["mean_spread_a_minus_b_eur_mwh"].reset_index(drop=True),
                ),
                "mean_absolute_spread_trend_eur_mwh_per_year": linear_slope_per_year(
                    complete_dates,
                    complete["mean_absolute_spread_eur_mwh"].reset_index(drop=True),
                ),
                "robust_median_absolute_spread_trend_eur_mwh_per_year": median_pairwise_slope_per_year(
                    complete["year"].reset_index(drop=True),
                    complete["mean_absolute_spread_eur_mwh"].reset_index(drop=True),
                ),
                "recent_3_complete_year_absolute_spread_trend_eur_mwh_per_year": linear_slope_per_year(
                    recent_dates,
                    recent["mean_absolute_spread_eur_mwh"].reset_index(drop=True),
                ),
                "price_correlation_trend_per_year": linear_slope_per_year(
                    complete_dates,
                    complete["price_level_pearson_correlation"].reset_index(drop=True),
                ),
            }
        )
    return pd.DataFrame(rows)


def pairwise_matrix(
    summary: pd.DataFrame,
    markets: list[str],
    value_column: str,
    *,
    reverse_sign: bool = False,
    diagonal_value: float = np.nan,
) -> pd.DataFrame:
    values = np.full((len(markets), len(markets)), np.nan, dtype=float)
    np.fill_diagonal(values, diagonal_value)
    matrix = pd.DataFrame(values, index=markets, columns=markets)
    for row in summary.itertuples(index=False):
        value = getattr(row, value_column)
        matrix.loc[row.market_a, row.market_b] = value
        matrix.loc[row.market_b, row.market_a] = -value if reverse_sign else value
    matrix.index.name = "market"
    return matrix.reset_index()


def cluster_markets(
    hourly_change_correlation_matrix: pd.DataFrame,
    iso3_lookup: dict[str, str],
    cluster_count: int,
) -> pd.DataFrame:
    correlation = hourly_change_correlation_matrix.set_index("market").astype(float)
    correlation = correlation.reindex(index=correlation.columns, columns=correlation.columns)
    correlation = correlation.fillna(0).clip(-1, 1)
    correlation_values = correlation.to_numpy(copy=True)
    np.fill_diagonal(correlation_values, 1.0)
    correlation = pd.DataFrame(
        correlation_values, index=correlation.index, columns=correlation.columns
    )
    try:
        from scipy.cluster.hierarchy import fcluster, leaves_list, linkage
        from scipy.spatial.distance import squareform

        distance = np.sqrt(np.maximum(0, (1 - correlation.to_numpy()) / 2))
        np.fill_diagonal(distance, 0)
        hierarchy = linkage(squareform(distance, checks=False), method="average")
        labels = fcluster(hierarchy, t=min(cluster_count, len(correlation)), criterion="maxclust")
        ordering = leaves_list(hierarchy)
        order_lookup = {int(position): rank + 1 for rank, position in enumerate(ordering)}
        rows = [
            {
                "market": market,
                "iso3": iso3_lookup.get(market, ""),
                "price_change_cluster": int(labels[position]),
                "cluster_heatmap_order": order_lookup[position],
            }
            for position, market in enumerate(correlation.index)
        ]
    except ImportError:
        rows = [
            {
                "market": market,
                "iso3": iso3_lookup.get(market, ""),
                "price_change_cluster": np.nan,
                "cluster_heatmap_order": position + 1,
            }
            for position, market in enumerate(correlation.index)
        ]
    return pd.DataFrame(rows).sort_values("cluster_heatmap_order")


def build_pairwise_market_outputs(
    wide: pd.DataFrame,
    iso3_lookup: dict[str, str],
    deadband: float,
    recent_years: int,
    minimum_overlap_hours: int,
    minimum_hours_per_day: int,
    rolling_windows: Iterable[int],
    lag_hours: Iterable[int],
    cluster_count: int,
) -> dict[str, pd.DataFrame]:
    markets = sorted(wide.columns.tolist())
    pair_keys: list[tuple[str, str]] = []
    summary_rows: list[dict[str, object]] = []
    annual_frames: list[pd.DataFrame] = []
    seasonal_frames: list[pd.DataFrame] = []
    month_frames: list[pd.DataFrame] = []
    rolling_frames: list[pd.DataFrame] = []
    excluded_rows: list[dict[str, object]] = []
    all_pairs = list(combinations(markets, 2))
    for number, (market_a, market_b) in enumerate(all_pairs, start=1):
        pair = make_pairwise_market_pair(wide, market_a, market_b)
        if len(pair) < minimum_overlap_hours:
            excluded_rows.append(
                {
                    "market_a": market_a,
                    "iso3_a": iso3_lookup.get(market_a, ""),
                    "market_b": market_b,
                    "iso3_b": iso3_lookup.get(market_b, ""),
                    "overlap_observations": len(pair),
                    "reason": f"fewer than {minimum_overlap_hours} overlapping hours",
                }
            )
            continue
        pair_keys.append((market_a, market_b))
        iso3_a = iso3_lookup.get(market_a, "")
        iso3_b = iso3_lookup.get(market_b, "")
        summary_rows.append(
            pairwise_market_summary(
                pair, market_a, market_b, iso3_a, iso3_b, deadband, recent_years
            )
        )
        annual, seasonal, month_profile = build_pairwise_calendar_summaries(
            pair, market_a, market_b, iso3_a, iso3_b, deadband
        )
        annual_frames.append(annual)
        seasonal_frames.append(seasonal)
        month_frames.append(month_profile)
        rolling_frames.append(
            build_pairwise_rolling_monthly(
                pair,
                market_a,
                market_b,
                iso3_a,
                iso3_b,
                rolling_windows,
                minimum_hours_per_day,
            )
        )
        if number % 50 == 0 or number == len(all_pairs):
            print(f"Pairwise markets: processed {number}/{len(all_pairs)} candidate pairs")

    summary = pd.DataFrame(summary_rows).sort_values(["market_a", "market_b"])
    annual = pd.concat(annual_frames, ignore_index=True)
    seasonal = pd.concat(seasonal_frames, ignore_index=True)
    month_profile = pd.concat(month_frames, ignore_index=True)
    rolling = pd.concat(rolling_frames, ignore_index=True)
    trends = pairwise_spread_trend_summary(annual, summary)
    regular_index = pd.date_range(wide.index.min(), wide.index.max(), freq="h")
    regular_wide = wide[markets].reindex(regular_index)
    lag_summary, best_lag = build_pairwise_lag_summary(
        regular_wide, pair_keys, iso3_lookup, lag_hours
    )

    matrices = {
        "mean_absolute_spread_matrix": pairwise_matrix(
            summary, markets, "mean_absolute_spread_eur_mwh", diagonal_value=0
        ),
        "recent_mean_absolute_spread_matrix": pairwise_matrix(
            summary, markets, "recent_mean_absolute_spread_eur_mwh", diagonal_value=0
        ),
        "mean_signed_spread_matrix": pairwise_matrix(
            summary,
            markets,
            "mean_spread_a_minus_b_eur_mwh",
            reverse_sign=True,
            diagonal_value=0,
        ),
        "near_parity_share_matrix": pairwise_matrix(
            summary, markets, "near_parity_share", diagonal_value=1
        ),
        "within_5_eur_share_matrix": pairwise_matrix(
            summary, markets, "within_5_eur_share", diagonal_value=1
        ),
        "price_level_correlation_matrix": pairwise_matrix(
            summary, markets, "price_level_pearson_correlation", diagonal_value=1
        ),
        "hourly_change_correlation_matrix": pairwise_matrix(
            summary, markets, "hourly_change_pearson_correlation", diagonal_value=1
        ),
        "two_way_signal_balance_matrix": pairwise_matrix(
            summary, markets, "two_way_price_signal_balance", diagonal_value=0
        ),
        "joint_high_p95_share_matrix": pairwise_matrix(
            summary, markets, "joint_high_p95_share", diagonal_value=0.05
        ),
        "absolute_spread_trend_matrix": pairwise_matrix(
            trends,
            markets,
            "mean_absolute_spread_trend_eur_mwh_per_year",
            diagonal_value=0,
        ),
        "recent_absolute_spread_trend_matrix": pairwise_matrix(
            trends,
            markets,
            "recent_3_complete_year_absolute_spread_trend_eur_mwh_per_year",
            diagonal_value=0,
        ),
        "best_lag_hours_matrix": pairwise_matrix(
            best_lag,
            markets,
            "best_nonzero_lag_hours_market_b_leads_market_a_if_positive",
            reverse_sign=True,
            diagonal_value=0,
        ),
    }
    clusters = cluster_markets(
        matrices["hourly_change_correlation_matrix"], iso3_lookup, cluster_count
    )
    return {
        "summary": summary,
        "annual": annual,
        "seasonal": seasonal,
        "month_profile": month_profile,
        "rolling": rolling,
        "trends": trends,
        "lag_summary": lag_summary,
        "best_lag": best_lag,
        "clusters": clusters,
        "excluded_pairs": pd.DataFrame(excluded_rows),
        **matrices,
    }


def annual_trend_summary(annual: pd.DataFrame, pair_summary_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for market, group in annual.groupby("market", observed=True):
        group = group.sort_values("year")
        complete = group[group["complete_calendar_year_90pct"]].copy()
        recent = complete.tail(3)
        complete_dates = pd.to_datetime(complete["year"].astype(str) + "-07-01")
        recent_dates = pd.to_datetime(recent["year"].astype(str) + "-07-01")
        row = pair_summary_df[pair_summary_df["market"] == market].iloc[0]
        rows.append(
            {
                "market": market,
                "iso3": row["iso3"],
                "annual_periods": len(group),
                "first_year": group["year"].min(),
                "last_year": group["year"].max(),
                "complete_calendar_years_used": len(complete),
                "first_complete_calendar_year": complete["year"].min() if not complete.empty else np.nan,
                "last_complete_calendar_year": complete["year"].max() if not complete.empty else np.nan,
                "mean_spread_trend_eur_mwh_per_year": linear_slope_per_year(
                    complete_dates,
                    complete["mean_spread_gb_minus_market_eur_mwh"].reset_index(drop=True),
                ),
                "mean_absolute_spread_trend_eur_mwh_per_year": linear_slope_per_year(
                    complete_dates,
                    complete["mean_absolute_spread_eur_mwh"].reset_index(drop=True),
                ),
                "robust_median_absolute_spread_trend_eur_mwh_per_year": median_pairwise_slope_per_year(
                    complete["year"].reset_index(drop=True),
                    complete["mean_absolute_spread_eur_mwh"].reset_index(drop=True),
                ),
                "recent_3_complete_year_absolute_spread_trend_eur_mwh_per_year": linear_slope_per_year(
                    recent_dates,
                    recent["mean_absolute_spread_eur_mwh"].reset_index(drop=True),
                ),
                "price_correlation_trend_per_year": linear_slope_per_year(
                    complete_dates,
                    complete["price_level_pearson_correlation"].reset_index(drop=True),
                ),
                "market_mean_price_trend_eur_mwh_per_year": linear_slope_per_year(
                    complete_dates,
                    complete["market_mean_price_eur_mwh"].reset_index(drop=True),
                ),
                "gb_higher_share_trend_per_year": linear_slope_per_year(
                    complete_dates,
                    complete["gb_higher_share"].reset_index(drop=True),
                ),
            }
        )
    return pd.DataFrame(rows)


def best_lags(lag_summary: pd.DataFrame) -> pd.DataFrame:
    candidates = lag_summary[lag_summary["lag_hours_market_leads_if_positive"] != 0].copy()
    candidates["absolute_pearson_correlation"] = candidates["pearson_correlation"].abs()
    best = (
        candidates.sort_values("absolute_pearson_correlation", ascending=False)
        .groupby(["market", "iso3", "metric"], observed=True, as_index=False)
        .first()
    )
    return best.rename(
        columns={
            "lag_hours_market_leads_if_positive": "best_nonzero_lag_hours_market_leads_if_positive",
            "pearson_correlation": "best_nonzero_lag_pearson_correlation",
            "spearman_correlation": "best_nonzero_lag_spearman_correlation",
            "observations": "best_nonzero_lag_observations",
        }
    )


def build_screening_summary(
    pair_summary_df: pd.DataFrame,
    trends: pd.DataFrame,
    lag_best: pd.DataFrame,
    tails: pd.DataFrame,
    run_summary: pd.DataFrame,
) -> pd.DataFrame:
    change_lag = lag_best[lag_best["metric"] == "hourly_first_difference"][
        [
            "market",
            "best_nonzero_lag_hours_market_leads_if_positive",
            "best_nonzero_lag_pearson_correlation",
        ]
    ]
    gb_p95 = tails[
        (tails["trigger_market"] == "GB") & (tails["event_label"] == "P95")
    ][
        [
            "market",
            "mean_spread_gb_minus_market_eur_mwh",
            "other_market_same_tail_share",
        ]
    ].rename(
        columns={
            "mean_spread_gb_minus_market_eur_mwh": "mean_gb_p95_event_spread_eur_mwh",
            "other_market_same_tail_share": "market_also_in_own_high_tail_share_during_gb_p95",
        }
    )
    runs_wide = run_summary.pivot(index="market", columns="state", values="p90_run_hours")
    runs_wide = runs_wide.rename(
        columns={
            "gb_higher": "gb_higher_p90_run_hours",
            "market_higher": "market_higher_p90_run_hours",
            "near_parity": "near_parity_p90_run_hours",
        }
    ).reset_index()
    screening = (
        pair_summary_df.merge(trends, on=["market", "iso3"], how="left")
        .merge(change_lag, on="market", how="left")
        .merge(gb_p95, on="market", how="left")
        .merge(runs_wide, on="market", how="left")
    )
    screening["two_way_price_signal_balance"] = (
        2 * screening[["gb_higher_share", "market_higher_share"]].min(axis=1)
    )
    rank_metrics = {
        "rank_mean_absolute_spread_desc": ("mean_absolute_spread_eur_mwh", False),
        "rank_price_level_correlation_desc": ("price_level_pearson_correlation", False),
        "rank_hourly_change_correlation_desc": ("hourly_change_pearson_correlation", False),
        "rank_two_way_signal_balance_desc": ("two_way_price_signal_balance", False),
        "rank_gb_p95_event_spread_desc": ("mean_gb_p95_event_spread_eur_mwh", False),
        "rank_recent_absolute_spread_desc": ("recent_mean_absolute_spread_eur_mwh", False),
    }
    for output_col, (source_col, ascending) in rank_metrics.items():
        screening[output_col] = screening[source_col].rank(
            method="min", ascending=ascending, na_option="bottom"
        )
    return screening.sort_values("mean_absolute_spread_eur_mwh", ascending=False)


def generate_figures(
    output_dir: Path,
    pair_summaries: pd.DataFrame,
    annual: pd.DataFrame,
    monthly: pd.DataFrame,
    rolling: pd.DataFrame,
    lag_summary: pd.DataFrame,
    month_hour: pd.DataFrame,
    histograms: pd.DataFrame,
    correlation_matrix: pd.DataFrame,
    pairwise_outputs: dict[str, pd.DataFrame] | None = None,
) -> None:
    try:
        import plotly.express as px
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError as exc:
        print(f"Plotly unavailable ({exc}); skipping figures.")
        return

    figure_dir = output_dir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)

    def finish(fig, title: str, path: Path, height: int = 650) -> None:
        fig.update_layout(
            title=title,
            template="plotly_white",
            height=height,
            margin=dict(l=70, r=35, t=80, b=65),
            font=dict(size=13),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.write_html(path, include_plotlyjs="cdn", full_html=True)

    overview = pair_summaries.sort_values("price_level_pearson_correlation")
    fig = px.bar(
        overview,
        x="price_level_pearson_correlation",
        y="market",
        orientation="h",
        color="hourly_change_pearson_correlation",
        color_continuous_scale="RdBu_r",
        color_continuous_midpoint=0,
        labels={
            "price_level_pearson_correlation": "Hourly price-level correlation",
            "hourly_change_pearson_correlation": "Hourly-change correlation",
            "market": "",
        },
    )
    finish(fig, "GB price correlation by comparison market", figure_dir / "gb_market_price_correlations.html", 800)

    fig = px.scatter(
        pair_summaries,
        x="price_level_pearson_correlation",
        y="mean_absolute_spread_eur_mwh",
        color="mean_spread_gb_minus_market_eur_mwh",
        hover_name="market",
        text="iso3",
        color_continuous_scale="RdBu_r",
        color_continuous_midpoint=0,
        labels={
            "price_level_pearson_correlation": "Hourly price-level correlation with GB",
            "mean_absolute_spread_eur_mwh": "Mean absolute GB-market spread (EUR/MWh)",
            "mean_spread_gb_minus_market_eur_mwh": "Mean GB premium (EUR/MWh)",
        },
    )
    fig.update_traces(textposition="top center")
    finish(fig, "Price co-movement and price separation relative to GB", figure_dir / "screening_correlation_vs_spread.html")

    corr_plot = correlation_matrix.set_index("market")
    fig = px.imshow(
        corr_plot,
        color_continuous_scale="RdBu_r",
        zmin=-1,
        zmax=1,
        aspect="auto",
        labels=dict(color="Pearson correlation"),
    )
    finish(fig, "Hourly wholesale price correlation across markets", figure_dir / "all_market_price_correlation_matrix.html", 850)

    annual_heat = annual.pivot(index="market", columns="year", values="mean_absolute_spread_eur_mwh")
    fig = px.imshow(
        annual_heat,
        color_continuous_scale="Viridis",
        aspect="auto",
        labels=dict(color="Mean absolute spread (EUR/MWh)"),
    )
    finish(fig, "Annual mean absolute price spread versus GB", figure_dir / "annual_absolute_spread_heatmap.html", 850)

    change_lags = lag_summary[lag_summary["metric"] == "hourly_first_difference"].pivot(
        index="market",
        columns="lag_hours_market_leads_if_positive",
        values="pearson_correlation",
    )
    fig = px.imshow(
        change_lags,
        color_continuous_scale="RdBu_r",
        zmin=-1,
        zmax=1,
        aspect="auto",
        labels=dict(color="Pearson correlation"),
    )
    finish(
        fig,
        "Lag correlation of hourly price changes (positive lag means market leads GB)",
        figure_dir / "hourly_change_lag_correlation_heatmap.html",
        850,
    )

    if pairwise_outputs:
        pairwise_dir = figure_dir / "pairwise_markets"
        cluster_order = pairwise_outputs["clusters"].sort_values("cluster_heatmap_order")[
            "market"
        ].tolist()

        def ordered_matrix(key: str) -> pd.DataFrame:
            matrix = pairwise_outputs[key].set_index("market")
            available = [market for market in cluster_order if market in matrix.index]
            return matrix.reindex(index=available, columns=available)

        pairwise_heatmaps = [
            (
                "mean_absolute_spread_matrix",
                "Mean absolute hourly spread between every market pair",
                "mean_absolute_spread_heatmap.html",
                "Mean absolute spread (EUR/MWh)",
                "Viridis",
                None,
                None,
            ),
            (
                "recent_mean_absolute_spread_matrix",
                "Recent mean absolute hourly spread between every market pair",
                "recent_mean_absolute_spread_heatmap.html",
                "Mean absolute spread (EUR/MWh)",
                "Viridis",
                None,
                None,
            ),
            (
                "mean_signed_spread_matrix",
                "Mean signed spread: row market minus column market",
                "mean_signed_spread_heatmap.html",
                "Row - column (EUR/MWh)",
                "RdBu_r",
                "symmetric",
                None,
            ),
            (
                "within_5_eur_share_matrix",
                "Share of hours with pairwise prices within EUR 5/MWh",
                "within_5_eur_share_heatmap.html",
                "Share within EUR 5/MWh",
                "Blues",
                0,
                1,
            ),
            (
                "hourly_change_correlation_matrix",
                "Hourly price-change correlation between every market pair",
                "hourly_change_correlation_heatmap.html",
                "Pearson correlation",
                "RdBu_r",
                -1,
                1,
            ),
            (
                "recent_absolute_spread_trend_matrix",
                "Recent three-complete-year trend in absolute pairwise spread",
                "recent_absolute_spread_trend_heatmap.html",
                "EUR/MWh per year",
                "RdBu_r",
                "symmetric",
                None,
            ),
            (
                "best_lag_hours_matrix",
                "Best tested non-zero hourly-change lag (column leads row if positive)",
                "best_lag_hours_heatmap.html",
                "Lag hours",
                "RdBu_r",
                -24,
                24,
            ),
        ]
        for key, title, filename, color_label, colorscale, lower, upper in pairwise_heatmaps:
            matrix = ordered_matrix(key)
            zmin = lower
            zmax = upper
            if lower == "symmetric":
                limit = np.nanquantile(np.abs(matrix.to_numpy(dtype=float)), 0.98)
                zmin, zmax = -limit, limit
            fig = px.imshow(
                matrix,
                color_continuous_scale=colorscale,
                zmin=zmin,
                zmax=zmax,
                aspect="auto",
                labels=dict(color=color_label),
            )
            finish(fig, title, pairwise_dir / filename, 920)

        top_pairs = pairwise_outputs["summary"].query("overlap_years >= 3").nlargest(
            25, "recent_mean_absolute_spread_eur_mwh"
        ).copy()
        top_pairs["market_pair"] = top_pairs["market_a"] + " - " + top_pairs["market_b"]
        top_pairs = top_pairs.sort_values("recent_mean_absolute_spread_eur_mwh")
        fig = px.bar(
            top_pairs,
            x="recent_mean_absolute_spread_eur_mwh",
            y="market_pair",
            orientation="h",
            color="hourly_change_pearson_correlation",
            color_continuous_scale="RdBu_r",
            color_continuous_midpoint=0,
            labels={
                "recent_mean_absolute_spread_eur_mwh": "Recent mean absolute spread (EUR/MWh)",
                "market_pair": "",
                "hourly_change_pearson_correlation": "Hourly-change correlation",
            },
        )
        finish(
            fig,
            "Largest recent pairwise price separations (minimum three-year overlap)",
            pairwise_dir / "largest_recent_pairwise_spreads.html",
            850,
        )

    for market in pair_summaries["market"]:
        slug = safe_slug(market)
        market_dir = figure_dir / "markets" / slug
        market_monthly = monthly[monthly["market"] == market].copy()
        market_monthly["date"] = pd.to_datetime(market_monthly["year_month"] + "-01")
        fig = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.10,
            subplot_titles=("Monthly mean prices", "Monthly GB minus market spread"),
        )
        fig.add_trace(
            go.Scatter(x=market_monthly["date"], y=market_monthly["gb_mean_price_eur_mwh"], name="GB"),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=market_monthly["date"],
                y=market_monthly["market_mean_price_eur_mwh"],
                name=market,
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=market_monthly["date"],
                y=market_monthly["mean_spread_gb_minus_market_eur_mwh"],
                name="GB - market",
                line=dict(color="#c0392b"),
            ),
            row=2,
            col=1,
        )
        fig.add_hline(y=0, line_width=1, line_color="#555", row=2, col=1)
        fig.update_yaxes(title_text="EUR/MWh", row=1, col=1)
        fig.update_yaxes(title_text="EUR/MWh", row=2, col=1)
        finish(fig, f"{market}: monthly prices and GB spread", market_dir / "monthly_prices_and_spread.html", 760)

        market_rolling = rolling[
            (rolling["market"] == market) & (rolling["window_days"] == 365)
        ]
        fig = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.10,
            subplot_titles=("365-day daily-price correlation", "365-day mean absolute hourly spread"),
        )
        fig.add_trace(
            go.Scatter(
                x=market_rolling["date_utc"],
                y=market_rolling["rolling_daily_price_correlation"],
                name="Correlation",
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=market_rolling["date_utc"],
                y=market_rolling["rolling_mean_absolute_hourly_spread_eur_mwh"],
                name="Absolute spread",
                line=dict(color="#c0392b"),
            ),
            row=2,
            col=1,
        )
        fig.update_yaxes(title_text="Correlation", range=[-1, 1], row=1, col=1)
        fig.update_yaxes(title_text="EUR/MWh", row=2, col=1)
        finish(fig, f"{market}: rolling convergence with GB", market_dir / "rolling_365d_convergence.html", 760)

        market_mh = month_hour[month_hour["market"] == market].pivot(
            index="month", columns="hour_utc", values="mean_spread_gb_minus_market_eur_mwh"
        )
        max_abs = np.nanquantile(np.abs(market_mh.to_numpy()), 0.98)
        fig = px.imshow(
            market_mh,
            color_continuous_scale="RdBu_r",
            zmin=-max_abs,
            zmax=max_abs,
            aspect="auto",
            labels=dict(x="Hour UTC", y="Month", color="GB - market (EUR/MWh)"),
        )
        finish(fig, f"{market}: mean GB spread by month and hour", market_dir / "month_hour_spread_heatmap.html")

        market_lags = lag_summary[lag_summary["market"] == market]
        fig = px.line(
            market_lags,
            x="lag_hours_market_leads_if_positive",
            y="pearson_correlation",
            color="metric",
            markers=True,
            labels={
                "lag_hours_market_leads_if_positive": "Lag hours (positive = market leads GB)",
                "pearson_correlation": "Pearson correlation",
                "metric": "Metric",
            },
        )
        fig.add_vline(x=0, line_width=1, line_color="#555")
        finish(fig, f"{market}: price lead-lag relationship with GB", market_dir / "lag_correlation_profile.html")

        market_hist = histograms[histograms["market"] == market]
        fig = px.bar(
            market_hist,
            x="bin_midpoint_eur_mwh",
            y="probability",
            labels={
                "bin_midpoint_eur_mwh": "GB - market spread (EUR/MWh)",
                "probability": "Probability",
            },
        )
        fig.add_vline(x=0, line_width=1, line_color="#555")
        finish(fig, f"{market}: hourly GB price-spread distribution", market_dir / "spread_distribution.html")

        market_annual = annual[annual["market"] == market].sort_values("year")
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(
            go.Scatter(x=market_annual["year"], y=market_annual["gb_mean_price_eur_mwh"], name="GB mean price"),
            secondary_y=False,
        )
        fig.add_trace(
            go.Scatter(
                x=market_annual["year"],
                y=market_annual["market_mean_price_eur_mwh"],
                name=f"{market} mean price",
            ),
            secondary_y=False,
        )
        fig.add_trace(
            go.Bar(
                x=market_annual["year"],
                y=market_annual["mean_absolute_spread_eur_mwh"],
                name="Mean absolute spread",
                opacity=0.35,
            ),
            secondary_y=True,
        )
        fig.update_yaxes(title_text="Mean price (EUR/MWh)", secondary_y=False)
        fig.update_yaxes(title_text="Mean absolute spread (EUR/MWh)", secondary_y=True)
        finish(fig, f"{market}: annual prices and separation from GB", market_dir / "annual_price_relationship.html")


def format_number(value: object, decimals: int = 2) -> str:
    if value is None or pd.isna(value):
        return "n.a."
    return f"{float(value):,.{decimals}f}"


def format_percent(value: object, decimals: int = 1) -> str:
    if value is None or pd.isna(value):
        return "n.a."
    return f"{float(value) * 100:.{decimals}f}%"


def write_story(
    output_dir: Path,
    gb_country: str,
    pair_summaries: pd.DataFrame,
    trends: pd.DataFrame,
    lag_best: pd.DataFrame,
    tails: pd.DataFrame,
    source_path: Path,
) -> None:
    strongest_corr = pair_summaries.nlargest(5, "price_level_pearson_correlation")
    weakest_corr = pair_summaries.nsmallest(5, "price_level_pearson_correlation")
    largest_spread = pair_summaries.nlargest(5, "mean_absolute_spread_eur_mwh")
    valid_trends = trends.dropna(subset=["mean_absolute_spread_trend_eur_mwh_per_year"])
    converging = valid_trends[valid_trends["mean_absolute_spread_trend_eur_mwh_per_year"] < 0].nsmallest(
        5, "mean_absolute_spread_trend_eur_mwh_per_year"
    )
    diverging = valid_trends[valid_trends["mean_absolute_spread_trend_eur_mwh_per_year"] > 0].nlargest(
        5, "mean_absolute_spread_trend_eur_mwh_per_year"
    )
    least_diverging = valid_trends.nsmallest(5, "mean_absolute_spread_trend_eur_mwh_per_year")
    recent_trends = trends.dropna(
        subset=["recent_3_complete_year_absolute_spread_trend_eur_mwh_per_year"]
    )
    recent_converging = recent_trends[
        recent_trends["recent_3_complete_year_absolute_spread_trend_eur_mwh_per_year"] < 0
    ].nsmallest(5, "recent_3_complete_year_absolute_spread_trend_eur_mwh_per_year")
    recent_diverging = recent_trends[
        recent_trends["recent_3_complete_year_absolute_spread_trend_eur_mwh_per_year"] > 0
    ].nlargest(5, "recent_3_complete_year_absolute_spread_trend_eur_mwh_per_year")
    best_change_lags = lag_best[lag_best["metric"] == "hourly_first_difference"].copy()
    best_change_lags["abs_corr"] = best_change_lags[
        "best_nonzero_lag_pearson_correlation"
    ].abs()
    best_change_lags = best_change_lags.nlargest(5, "abs_corr")
    gb_p95 = tails[
        (tails["trigger_market"] == "GB") & (tails["event_label"] == "P95")
    ].nlargest(5, "mean_spread_gb_minus_market_eur_mwh")

    start = pair_summaries["overlap_start_utc"].min()
    end = pair_summaries["overlap_end_utc"].max()
    lines = [
        "# European Wholesale Electricity Prices Relative to GB",
        "",
        "## Scope and conventions",
        "",
        f"- Source: `{source_path}`.",
        f"- GB benchmark: {gb_country}.",
        f"- Pairwise comparison window across the available markets spans {start} to {end}; each market uses its own overlap with GB.",
        "- Prices use the source unit EUR/MWh and timestamps use UTC.",
        "- Spread is `GB price - comparison-market price`. Positive values mean GB is more expensive.",
        "- The dataset contains one country-level series per market. It is not a true bidding-zone dataset for countries with multiple internal zones.",
        "",
        "## Main historical signals",
        "",
        "Highest hourly price-level correlations with GB:",
        "",
    ]
    for _, row in strongest_corr.iterrows():
        lines.append(
            f"- {row['market']}: r={format_number(row['price_level_pearson_correlation'])}; "
            f"hourly-change r={format_number(row['hourly_change_pearson_correlation'])}; "
            f"mean absolute spread={format_number(row['mean_absolute_spread_eur_mwh'], 1)} EUR/MWh."
        )
    lines.extend(["", "Lowest hourly price-level correlations with GB:", ""])
    for _, row in weakest_corr.iterrows():
        lines.append(
            f"- {row['market']}: r={format_number(row['price_level_pearson_correlation'])}; "
            f"hourly-change r={format_number(row['hourly_change_pearson_correlation'])}; "
            f"mean absolute spread={format_number(row['mean_absolute_spread_eur_mwh'], 1)} EUR/MWh."
        )
    lines.extend(["", "Largest average absolute price separations from GB:", ""])
    for _, row in largest_spread.iterrows():
        lines.append(
            f"- {row['market']}: {format_number(row['mean_absolute_spread_eur_mwh'], 1)} EUR/MWh; "
            f"GB is higher {format_percent(row['gb_higher_share'])} of overlapping hours and the market is higher {format_percent(row['market_higher_share'])}."
        )
    lines.extend(
        [
            "",
            "## Convergence and divergence",
            "",
            "Trends use calendar years with at least 90% hourly coverage; partial first and last years are excluded.",
            "",
        ]
    )
    if converging.empty:
        lines.extend(
            [
                "No market with enough complete-year history has a negative full-period fitted trend in mean absolute spread. The smallest positive slopes are:",
                "",
            ]
        )
        for _, row in least_diverging.iterrows():
            lines.append(
                f"- {row['market']}: +{format_number(row['mean_absolute_spread_trend_eur_mwh_per_year'])} EUR/MWh per year; "
                f"robust median slope {format_number(row['robust_median_absolute_spread_trend_eur_mwh_per_year'])}."
            )
    else:
        lines.extend(["Markets with the strongest negative fitted trends (descriptive convergence):", ""])
        for _, row in converging.iterrows():
            lines.append(
                f"- {row['market']}: {format_number(row['mean_absolute_spread_trend_eur_mwh_per_year'])} EUR/MWh per year; "
                f"robust median slope {format_number(row['robust_median_absolute_spread_trend_eur_mwh_per_year'])}."
            )
    lines.extend(["", "Most positive fitted trends (descriptive divergence):", ""])
    for _, row in diverging.iterrows():
        lines.append(
            f"- {row['market']}: +{format_number(row['mean_absolute_spread_trend_eur_mwh_per_year'])} EUR/MWh per year; "
            f"robust median slope {format_number(row['robust_median_absolute_spread_trend_eur_mwh_per_year'])}."
        )
    lines.extend(["", "Recent direction using each market's last three complete calendar years:", ""])
    if recent_converging.empty:
        lines.append("- No market shows a negative recent fitted absolute-spread trend.")
    else:
        for _, row in recent_converging.iterrows():
            lines.append(
                f"- {row['market']}: {format_number(row['recent_3_complete_year_absolute_spread_trend_eur_mwh_per_year'])} EUR/MWh per year (recent convergence)."
            )
    if not recent_diverging.empty:
        lines.append("")
        lines.append("Largest recent positive absolute-spread trends:")
        lines.append("")
        for _, row in recent_diverging.iterrows():
            lines.append(
                f"- {row['market']}: +{format_number(row['recent_3_complete_year_absolute_spread_trend_eur_mwh_per_year'])} EUR/MWh per year."
            )
    lines.extend(
        [
            "",
            "Even after excluding partial years, straight-line slopes remain sensitive to the 2021-2023 energy-price shock. Compare the OLS slope, robust median slope, recent three-complete-year slope and rolling figures before treating a trend as structural.",
            "",
            "## Lead-lag checks",
            "",
            "Strongest tested non-zero lag relationships in hourly price changes:",
            "",
        ]
    )
    for _, row in best_change_lags.iterrows():
        lag = int(row["best_nonzero_lag_hours_market_leads_if_positive"])
        interpretation = "comparison market leads GB" if lag > 0 else "GB leads comparison market"
        lag_unit = "hour" if abs(lag) == 1 else "hours"
        lines.append(
            f"- {row['market']}: best tested lag {lag:+d} {lag_unit} ({interpretation}), "
            f"r={format_number(row['best_nonzero_lag_pearson_correlation'])}."
        )
    lines.extend(
        [
            "",
            "Lag peaks do not establish causality. Common fundamentals, market-gate timing, time-zone conventions, autocorrelation and shared interconnection can all produce lead-lag patterns.",
            "",
            "## GB high-price periods",
            "",
            "Largest average GB premiums during GB P95 high-price hours:",
            "",
        ]
    )
    for _, row in gb_p95.iterrows():
        lines.append(
            f"- {row['market']}: mean GB-market spread {format_number(row['mean_spread_gb_minus_market_eur_mwh'], 1)} EUR/MWh; "
            f"the comparison market is simultaneously in its own high tail {format_percent(row['other_market_same_tail_share'])} of those hours."
        )
    lines.extend(
        [
            "",
            "## How to use this for future-link screening",
            "",
            "- `future_connection_screening_summary.csv` deliberately keeps separate indicators instead of combining them into one investment score. Large and persistent spreads indicate price separation, while correlation and tail coincidence indicate how often scarcity is shared.",
            "- High average spreads alone do not imply an attractive interconnector. A feasibility case also needs zonal rather than country-average prices, route-specific losses, capacity and outage assumptions, congestion and curtailment modelling, network constraints, capex, regulation, market coupling and cannibalisation after the link is built.",
            "- Give more weight to stable signals across annual, seasonal, rolling and tail-event views than to a full-period average.",
            "- Use first-difference lag correlations for short-run timing. Price-level correlations mainly describe broad co-movement and common regimes.",
            "",
            "## Output guide",
            "",
            "- `market_price_summary.csv`: each market's standalone price distribution and volatility.",
            "- `gb_market_relationship_summary.csv`: full-period GB comparison for every market.",
            "- `annual_market_summary.csv`, `monthly_market_summary.csv`, `seasonal_market_summary.csv`: historical and seasonal relationship tables.",
            "- `rolling_daily_metrics.csv.gz`: 30/90/365-day rolling correlations, prices and spreads.",
            "- `lag_correlation_summary.csv` and `best_lag_summary.csv`: price-level and first-difference lead-lag checks.",
            "- `tail_event_summary.csv`: GB and comparison-market low/high price-tail coincidence.",
            "- `spread_band_summary.csv` and `spread_run_summary.csv`: magnitude bands and persistence of directional price signals.",
            "- `future_connection_screening_summary.csv`: descriptive comparison table for early-stage screening.",
            "- `figures/markets/<market>/`: six figures for each comparison market.",
        ]
    )
    (output_dir / "story.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def append_pairwise_story(
    output_dir: Path,
    pairwise_outputs: dict[str, pd.DataFrame],
) -> None:
    summary = pairwise_outputs["summary"].copy()
    trends = pairwise_outputs["trends"].copy()
    clusters = pairwise_outputs["clusters"].copy()
    established = summary[summary["overlap_years"] >= 3].copy()
    established["high_tail_conditional_coincidence"] = established[
        [
            "market_b_high_p95_share_when_market_a_high_p95",
            "market_a_high_p95_share_when_market_b_high_p95",
        ]
    ].mean(axis=1)
    largest = established.nlargest(8, "recent_mean_absolute_spread_eur_mwh")
    closest = established.nsmallest(8, "recent_mean_absolute_spread_eur_mwh")
    lowest_tail = established.nsmallest(6, "high_tail_conditional_coincidence")
    highest_tail = established.nlargest(6, "high_tail_conditional_coincidence")
    trend_eligible = trends[trends["complete_calendar_years_used"] >= 3].dropna(
        subset=["recent_3_complete_year_absolute_spread_trend_eur_mwh_per_year"]
    )
    recent_converging = trend_eligible.nsmallest(
        6, "recent_3_complete_year_absolute_spread_trend_eur_mwh_per_year"
    )
    recent_diverging = trend_eligible.nlargest(
        6, "recent_3_complete_year_absolute_spread_trend_eur_mwh_per_year"
    )
    lines = [
        "",
        "## Pairwise spreads between all markets",
        "",
        f"The pairwise layer analyses {len(summary):,} eligible market pairs. Each signed spread is `market A price - market B price`; symmetric metrics such as absolute spread and correlation are identical in either direction.",
        "",
        "Largest recent mean absolute spreads among pairs with at least three years of overlap:",
        "",
    ]
    for _, row in largest.iterrows():
        lines.append(
            f"- {row['market_a']} / {row['market_b']}: {format_number(row['recent_mean_absolute_spread_eur_mwh'], 1)} EUR/MWh; "
            f"hourly-change correlation {format_number(row['hourly_change_pearson_correlation'])}."
        )
    lines.extend(["", "Closest recent price pairs:", ""])
    for _, row in closest.iterrows():
        lines.append(
            f"- {row['market_a']} / {row['market_b']}: {format_number(row['recent_mean_absolute_spread_eur_mwh'], 1)} EUR/MWh; "
            f"within EUR 5/MWh for {format_percent(row['within_5_eur_share'])} of the full overlap."
        )
    lines.extend(
        [
            "",
            "Strongest recent convergence in absolute spread:",
            "",
        ]
    )
    for _, row in recent_converging.iterrows():
        value = row["recent_3_complete_year_absolute_spread_trend_eur_mwh_per_year"]
        direction = "converging" if value < 0 else "still widening"
        lines.append(
            f"- {row['market_a']} / {row['market_b']}: {format_number(value)} EUR/MWh per year ({direction})."
        )
    lines.extend(["", "Largest recent widening in absolute spread:", ""])
    for _, row in recent_diverging.iterrows():
        value = row["recent_3_complete_year_absolute_spread_trend_eur_mwh_per_year"]
        lines.append(
            f"- {row['market_a']} / {row['market_b']}: +{format_number(value)} EUR/MWh per year."
        )
    lines.extend(
        [
            "",
            "Lowest conditional P95 high-price coincidence (greater scarcity diversification):",
            "",
        ]
    )
    for _, row in lowest_tail.iterrows():
        lines.append(
            f"- {row['market_a']} / {row['market_b']}: {format_percent(row['high_tail_conditional_coincidence'])}."
        )
    lines.extend(["", "Highest conditional P95 high-price coincidence:", ""])
    for _, row in highest_tail.iterrows():
        lines.append(
            f"- {row['market_a']} / {row['market_b']}: {format_percent(row['high_tail_conditional_coincidence'])}."
        )
    lines.extend(["", "Hourly price-change clusters:", ""])
    for cluster, group in clusters.groupby("price_change_cluster", observed=True):
        markets = ", ".join(group.sort_values("cluster_heatmap_order")["market"])
        lines.append(f"- Cluster {int(cluster)}: {markets}.")
    lines.extend(
        [
            "",
            "Pairwise outputs:",
            "",
            "- `pairwise_market_spread_summary.csv`: complete distribution, direction, correlation, tail and persistence metrics for every eligible pair.",
            "- `pairwise_market_annual_summary.csv`, `pairwise_market_seasonal_summary.csv`, and `pairwise_market_month_of_year_summary.csv`: time and seasonal cuts.",
            "- `pairwise_market_rolling_monthly.csv.gz`: month-end snapshots of rolling pairwise spread and correlation metrics.",
            "- `pairwise_market_spread_trend_summary.csv`: complete-year OLS, robust and recent convergence checks.",
            "- `pairwise_market_lag_correlation_summary.csv` and `pairwise_market_best_lag_summary.csv`: hourly-change lags; positive lag means market B leads market A.",
            "- `pairwise_*_matrix.csv`: presentation-ready matrices for spreads, convergence, correlation, price proximity, tail coincidence and lag direction.",
            "- `market_price_change_clusters.csv`: hierarchical clusters based on hourly price-change correlation.",
            "- `figures/pairwise_markets/`: pairwise heatmaps and the largest recent price-separation chart.",
        ]
    )
    story_path = output_dir / "story.md"
    with story_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main() -> None:
    args = parse_args()
    start = parse_timestamp(args.start)
    end = parse_timestamp(args.end)
    if start is not None and end is not None and start > end:
        raise ValueError("--start must be on or before --end")
    lags = parse_number_list(args.lags_hours, int)
    rolling_windows = parse_number_list(args.rolling_windows_days, int)
    pairwise_lags = parse_number_list(args.pairwise_lags_hours, int)
    pairwise_rolling_windows = parse_number_list(args.pairwise_rolling_windows_days, int)
    if args.price_deadband < 0:
        raise ValueError("--price-deadband must be non-negative")
    if args.histogram_bin_width <= 0:
        raise ValueError("--histogram-bin-width must be positive")
    if args.pairwise_clusters < 1:
        raise ValueError("--pairwise-clusters must be at least 1")

    selected = None
    if args.markets:
        selected = {market.strip() for market in args.markets.split(",") if market.strip()}
        selected.add(args.gb_country)

    raw, source_files = read_price_data(args.data_path, selected)
    clean, quality, duplicates = clean_and_summarise_source(raw, start, end)
    if args.gb_country not in set(clean["Country"]):
        raise ValueError(f"GB benchmark market not found after filtering: {args.gb_country}")

    iso3_lookup = clean.groupby("Country", observed=True)["iso3"].first().to_dict()
    wide = clean.pivot(index="timestamp_utc", columns="Country", values="price_eur_mwh").sort_index()
    markets = [column for column in wide.columns if column != args.gb_country]
    if not markets:
        raise ValueError("No comparison markets are available after filtering.")

    market_prices = describe_prices(clean)
    pair_rows: list[dict[str, object]] = []
    annual_frames: list[pd.DataFrame] = []
    monthly_frames: list[pd.DataFrame] = []
    seasonal_frames: list[pd.DataFrame] = []
    month_profile_frames: list[pd.DataFrame] = []
    hour_profile_frames: list[pd.DataFrame] = []
    month_hour_frames: list[pd.DataFrame] = []
    lag_frames: list[pd.DataFrame] = []
    daily_frames: list[pd.DataFrame] = []
    rolling_frames: list[pd.DataFrame] = []
    band_frames: list[pd.DataFrame] = []
    run_frames: list[pd.DataFrame] = []
    tail_frames: list[pd.DataFrame] = []
    histogram_frames: list[pd.DataFrame] = []
    excluded_rows: list[dict[str, object]] = []

    for number, market in enumerate(markets, start=1):
        pair = make_market_pair(wide, args.gb_country, market)
        if len(pair) < args.minimum_overlap_hours:
            excluded_rows.append(
                {
                    "market": market,
                    "iso3": iso3_lookup.get(market),
                    "overlap_observations": len(pair),
                    "reason": f"fewer than {args.minimum_overlap_hours} overlapping hours",
                }
            )
            print(f"[{number}/{len(markets)}] Skipping {market}: only {len(pair):,} overlapping hours")
            continue
        iso3 = iso3_lookup.get(market, "")
        print(f"[{number}/{len(markets)}] Analysing {market}: {len(pair):,} overlapping hours")
        pair_rows.append(pair_summary(pair, market, iso3, args.price_deadband, args.recent_years))
        annual, monthly, seasonal, month_profile, hour_profile = build_calendar_summaries(
            pair, market, iso3, args.price_deadband
        )
        annual_frames.append(annual)
        monthly_frames.append(monthly)
        seasonal_frames.append(seasonal)
        month_profile_frames.append(month_profile)
        hour_profile_frames.append(hour_profile)
        month_hour_frames.append(build_month_hour_profile(pair, market, iso3))
        lag_frames.append(build_lag_summary(pair, market, iso3, lags))
        daily, rolling = build_daily_and_rolling(
            pair,
            market,
            iso3,
            rolling_windows,
            args.minimum_hours_per_day,
        )
        daily_frames.append(daily)
        rolling_frames.append(rolling)
        band_frames.append(build_spread_bands(pair, market, iso3))
        run_frames.append(build_spread_runs(pair, market, iso3, args.price_deadband))
        tail_frames.append(build_tail_events(pair, market, iso3))
        histogram_frames.append(
            build_spread_histogram(pair, market, iso3, args.histogram_bin_width)
        )

    if not pair_rows:
        raise ValueError("No market has enough overlapping observations for analysis.")

    pair_summaries = pd.DataFrame(pair_rows).sort_values("market")
    annual = pd.concat(annual_frames, ignore_index=True)
    monthly = pd.concat(monthly_frames, ignore_index=True)
    seasonal = pd.concat(seasonal_frames, ignore_index=True)
    month_profile = pd.concat(month_profile_frames, ignore_index=True)
    hour_profile = pd.concat(hour_profile_frames, ignore_index=True)
    month_hour = pd.concat(month_hour_frames, ignore_index=True)
    lag_summary = pd.concat(lag_frames, ignore_index=True)
    daily = pd.concat(daily_frames, ignore_index=True)
    rolling = pd.concat(rolling_frames, ignore_index=True)
    bands = pd.concat(band_frames, ignore_index=True)
    runs = pd.concat(run_frames, ignore_index=True)
    tails = pd.concat(tail_frames, ignore_index=True)
    histograms = pd.concat(histogram_frames, ignore_index=True)
    trends = annual_trend_summary(annual, pair_summaries)
    lag_best = best_lags(lag_summary)
    screening = build_screening_summary(pair_summaries, trends, lag_best, tails, runs)

    pairwise_outputs: dict[str, pd.DataFrame] | None = None
    if not args.no_pairwise:
        print("Building all-market pairwise price-spread analysis")
        pairwise_outputs = build_pairwise_market_outputs(
            wide,
            iso3_lookup,
            args.price_deadband,
            args.recent_years,
            args.minimum_overlap_hours,
            args.minimum_hours_per_day,
            pairwise_rolling_windows,
            pairwise_lags,
            args.pairwise_clusters,
        )

    analysed_markets = [args.gb_country] + pair_summaries["market"].tolist()
    correlation = wide[analysed_markets].corr(min_periods=args.minimum_overlap_hours)
    correlation.index.name = "market"
    correlation = correlation.reset_index()

    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    write_csv(source_files, output / "source_files.csv")
    write_csv(quality, output / "source_data_quality_summary.csv")
    write_csv(duplicates, output / "duplicate_market_timestamp_summary.csv")
    write_csv(pd.DataFrame(excluded_rows), output / "excluded_markets.csv")
    write_csv(market_prices, output / "market_price_summary.csv")
    write_csv(pair_summaries, output / "gb_market_relationship_summary.csv")
    write_csv(correlation, output / "all_market_price_correlation_matrix.csv")
    write_csv(annual, output / "annual_market_summary.csv")
    write_csv(monthly, output / "monthly_market_summary.csv")
    write_csv(seasonal, output / "seasonal_market_summary.csv")
    write_csv(month_profile, output / "month_of_year_market_profile.csv")
    write_csv(hour_profile, output / "hour_of_day_market_profile.csv")
    write_csv(month_hour, output / "month_hour_spread_profile.csv")
    write_csv(daily, output / "daily_market_summary.csv")
    rolling.to_csv(output / "rolling_daily_metrics.csv.gz", index=False, compression="gzip")
    write_csv(lag_summary, output / "lag_correlation_summary.csv")
    write_csv(lag_best, output / "best_lag_summary.csv")
    write_csv(bands, output / "spread_band_summary.csv")
    write_csv(runs, output / "spread_run_summary.csv")
    write_csv(tails, output / "tail_event_summary.csv")
    write_csv(histograms, output / "spread_distribution_bins.csv")
    write_csv(trends, output / "annual_trend_summary.csv")
    write_csv(screening, output / "future_connection_screening_summary.csv")
    if pairwise_outputs:
        write_csv(pairwise_outputs["summary"], output / "pairwise_market_spread_summary.csv")
        write_csv(pairwise_outputs["annual"], output / "pairwise_market_annual_summary.csv")
        write_csv(pairwise_outputs["seasonal"], output / "pairwise_market_seasonal_summary.csv")
        write_csv(
            pairwise_outputs["month_profile"],
            output / "pairwise_market_month_of_year_summary.csv",
        )
        pairwise_outputs["rolling"].to_csv(
            output / "pairwise_market_rolling_monthly.csv.gz",
            index=False,
            compression="gzip",
        )
        write_csv(
            pairwise_outputs["trends"],
            output / "pairwise_market_spread_trend_summary.csv",
        )
        write_csv(
            pairwise_outputs["lag_summary"],
            output / "pairwise_market_lag_correlation_summary.csv",
        )
        write_csv(
            pairwise_outputs["best_lag"],
            output / "pairwise_market_best_lag_summary.csv",
        )
        write_csv(
            pairwise_outputs["clusters"], output / "market_price_change_clusters.csv"
        )
        write_csv(
            pairwise_outputs["excluded_pairs"], output / "pairwise_market_excluded_pairs.csv"
        )
        pairwise_matrix_files = {
            "mean_absolute_spread_matrix": "pairwise_mean_absolute_spread_matrix.csv",
            "recent_mean_absolute_spread_matrix": "pairwise_recent_mean_absolute_spread_matrix.csv",
            "mean_signed_spread_matrix": "pairwise_mean_signed_spread_matrix.csv",
            "near_parity_share_matrix": "pairwise_near_parity_share_matrix.csv",
            "within_5_eur_share_matrix": "pairwise_within_5_eur_share_matrix.csv",
            "price_level_correlation_matrix": "pairwise_price_level_correlation_matrix.csv",
            "hourly_change_correlation_matrix": "pairwise_hourly_change_correlation_matrix.csv",
            "two_way_signal_balance_matrix": "pairwise_two_way_signal_balance_matrix.csv",
            "joint_high_p95_share_matrix": "pairwise_joint_high_p95_share_matrix.csv",
            "absolute_spread_trend_matrix": "pairwise_absolute_spread_trend_matrix.csv",
            "recent_absolute_spread_trend_matrix": "pairwise_recent_absolute_spread_trend_matrix.csv",
            "best_lag_hours_matrix": "pairwise_best_lag_hours_matrix.csv",
        }
        for key, filename in pairwise_matrix_files.items():
            write_csv(pairwise_outputs[key], output / filename)

    run_config = pd.DataFrame(
        [
            ("source_path", str(args.data_path.resolve())),
            ("gb_country", args.gb_country),
            ("analysis_start_utc", clean["timestamp_utc"].min()),
            ("analysis_end_utc", clean["timestamp_utc"].max()),
            ("comparison_markets_analysed", len(pair_summaries)),
            ("comparison_markets_excluded", len(excluded_rows)),
            ("price_unit", "EUR/MWh"),
            ("spread_definition", "GB price - comparison-market price"),
            ("price_deadband_eur_mwh", args.price_deadband),
            ("lag_convention", "positive lag means comparison market leads GB"),
            ("lags_hours", ",".join(map(str, lags))),
            ("rolling_windows_days", ",".join(map(str, rolling_windows))),
            ("recent_years", args.recent_years),
            ("minimum_overlap_hours", args.minimum_overlap_hours),
            ("minimum_hours_per_day", args.minimum_hours_per_day),
            ("pairwise_analysis_enabled", not args.no_pairwise),
            ("pairwise_lags_hours", ",".join(map(str, pairwise_lags))),
            ("pairwise_rolling_windows_days", ",".join(map(str, pairwise_rolling_windows))),
            ("pairwise_price_change_clusters", args.pairwise_clusters),
            (
                "eligible_pairwise_market_pairs",
                len(pairwise_outputs["summary"]) if pairwise_outputs else 0,
            ),
            ("source_granularity_warning", "one country-level price series; not internal bidding zones"),
        ],
        columns=["key", "value"],
    )
    write_csv(run_config, output / "run_config.csv")
    write_story(
        output,
        args.gb_country,
        pair_summaries,
        trends,
        lag_best,
        tails,
        args.data_path.resolve(),
    )
    if pairwise_outputs:
        append_pairwise_story(output, pairwise_outputs)
    if not args.no_figures:
        generate_figures(
            output,
            pair_summaries,
            annual,
            monthly,
            rolling,
            lag_summary,
            month_hour,
            histograms,
            correlation,
            pairwise_outputs,
        )
    print(f"Written European wholesale-price analysis to {output.resolve()}")


if __name__ == "__main__":
    main()
