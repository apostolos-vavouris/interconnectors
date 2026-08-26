"""Analyse relationships between bidding-zone price spreads and interconnector flows.

Conventions:
  - Positive interconnector ``signed_mw`` means GB import.
  - Price spread is ``GB price - bidding-zone price``.
  - Positive spread therefore means GB is more expensive than the linked zone,
    so imports to GB are the price-aligned direction.

The price file is hourly. The script joins each half-hourly interconnector
observation to the matching hourly price by flooring the settlement start time
to the hour.
"""

from __future__ import annotations

import argparse
import math
import textwrap
from pathlib import Path

import numpy as np
import pandas as pd

from analyse_bm_interconnector_history import (
    GWH_PER_MW_HALF_HOUR,
    add_calendar_fields,
    add_capacity_fields,
    build_capacity_reference,
    format_num,
    format_pct,
    infer_default_start,
    normalise_timestamp,
    read_half_hourly_data,
    read_metadata,
)


PRICE_ZONE_BY_BIDDING_ZONE = {
    "BELGIUM": "B",
    "DENMARK1": "DK",
    "FRANCE": "FR",
    "IRELAND": "IRL",
    "NETHERLANDS": "NL",
    "NORWAY2": "NO",
}

SPREAD_BINS = [
    -math.inf,
    -100,
    -50,
    -25,
    -10,
    -5,
    0,
    5,
    10,
    25,
    50,
    100,
    math.inf,
]

SPREAD_LABELS = [
    "zone_gt_gb_100_plus",
    "zone_gt_gb_50_100",
    "zone_gt_gb_25_50",
    "zone_gt_gb_10_25",
    "zone_gt_gb_5_10",
    "zone_gt_gb_0_5",
    "gb_gt_zone_0_5",
    "gb_gt_zone_5_10",
    "gb_gt_zone_10_25",
    "gb_gt_zone_25_50",
    "gb_gt_zone_50_100",
    "gb_gt_zone_100_plus",
]

SPREAD_BAND_LABELS = {
    "zone_gt_gb_100_plus": "Zone > GB by >100",
    "zone_gt_gb_50_100": "Zone > GB by 50-100",
    "zone_gt_gb_25_50": "Zone > GB by 25-50",
    "zone_gt_gb_10_25": "Zone > GB by 10-25",
    "zone_gt_gb_5_10": "Zone > GB by 5-10",
    "zone_gt_gb_0_5": "Zone > GB by 0-5",
    "gb_gt_zone_0_5": "GB > zone by 0-5",
    "gb_gt_zone_5_10": "GB > zone by 5-10",
    "gb_gt_zone_10_25": "GB > zone by 10-25",
    "gb_gt_zone_25_50": "GB > zone by 25-50",
    "gb_gt_zone_50_100": "GB > zone by 50-100",
    "gb_gt_zone_100_plus": "GB > zone by >100",
}

SPREAD_DIRECTION_LABELS = {
    "gb_higher_expected_import": "GB higher: import aligned",
    "zone_higher_expected_export": "Zone higher: export aligned",
    "near_parity": "Near parity",
}

ALIGNMENT_LABELS = {
    "aligned_with_price_spread": "Aligned with spread",
    "counter_price_spread": "Counter-spread",
    "flow_near_zero_while_price_signal": "Flow near zero while spread signals",
    "price_near_parity": "Price near parity",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Correlate GB-vs-bidding-zone price spreads with GB interconnector BM flows."
    )
    parser.add_argument("--interconnector-data-dir", type=Path, default=Path("HH_data"))
    parser.add_argument("--metadata", type=Path, default=Path("interconnectors_names.csv"))
    parser.add_argument("--price-file", type=Path, default=Path("bidding_zones_electricity_markets_prices.csv"))
    parser.add_argument("--capacity-file", type=Path, default=Path("interconnector_capacities.csv"))
    parser.add_argument(
        "--interconnector-run-config",
        type=Path,
        default=Path("analysis_outputs") / "bm_interconnector_history" / "run_config.csv",
        help="Existing BM-history run config used to align the default analysis window.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("analysis_outputs") / "price_spread_interconnector_correlation",
    )
    parser.add_argument("--start", type=str, default=None, help="Inclusive analysis start timestamp.")
    parser.add_argument("--end", type=str, default=None, help="Inclusive analysis end timestamp.")
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument(
        "--positive-direction",
        choices=["import", "export"],
        default="import",
        help="How to interpret positive raw interconnector generation.",
    )
    parser.add_argument("--flow-deadband-mw", type=float, default=1.0)
    parser.add_argument(
        "--price-deadband",
        type=float,
        default=1.0,
        help="Absolute spread treated as near parity, in the units of the price file.",
    )
    parser.add_argument(
        "--price-time-shift-hours",
        type=float,
        default=0.0,
        help="Optional shift applied to price timestamps before joining to half-hourly flows.",
    )
    parser.add_argument("--min-correlation-observations", type=int, default=48)
    parser.add_argument("--no-figures", action="store_true")
    return parser.parse_args()


def write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def read_run_config(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    config = pd.read_csv(path, header=None, names=["key", "value"])
    return dict(zip(config["key"], config["value"]))


def read_prices(path: Path, time_shift_hours: float) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Price file not found: {path}")
    prices = pd.read_csv(path)
    if "DateTime" not in prices.columns or "GB" not in prices.columns:
        raise ValueError(f"{path} must contain DateTime and GB columns.")
    price_cols = [col for col in prices.columns if col != "DateTime"]
    prices["price_hour"] = pd.to_datetime(prices["DateTime"], dayfirst=True, errors="raise")
    prices["price_hour"] = prices["price_hour"].dt.tz_localize("UTC") + pd.to_timedelta(time_shift_hours, unit="h")
    for col in price_cols:
        prices[col] = pd.to_numeric(prices[col], errors="coerce")
    prices = prices.drop(columns=["DateTime"]).sort_values("price_hour")
    return prices


def build_zone_mapping(metadata: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    mapping = metadata.loc[:, ["interconnectorId", "interconnectorName", "interconnectorBiddingZone"]].copy()
    mapping["interconnectorBiddingZone"] = mapping["interconnectorBiddingZone"].astype(str).str.upper()
    mapping["price_zone_code"] = mapping["interconnectorBiddingZone"].map(PRICE_ZONE_BY_BIDDING_ZONE)
    price_cols = set(prices.columns) - {"price_hour"}
    missing = mapping[mapping["price_zone_code"].isna() | ~mapping["price_zone_code"].isin(price_cols)]
    if not missing.empty:
        details = missing[["interconnectorId", "interconnectorBiddingZone", "price_zone_code"]].to_dict("records")
        raise ValueError(f"Cannot map some interconnector bidding zones to price columns: {details}")
    return mapping


def melt_prices(prices: pd.DataFrame, zone_codes: list[str]) -> pd.DataFrame:
    cols = ["price_hour", "GB"] + sorted(set(zone_codes))
    price_long = prices[cols].melt(
        id_vars=["price_hour", "GB"],
        value_vars=sorted(set(zone_codes)),
        var_name="price_zone_code",
        value_name="zone_price",
    )
    price_long = price_long.rename(columns={"GB": "gb_price"})
    price_long["price_spread_gb_minus_zone"] = price_long["gb_price"] - price_long["zone_price"]
    return price_long


def choose_analysis_window(
    flows: pd.DataFrame,
    prices: pd.DataFrame,
    run_config: dict[str, str],
    args: argparse.Namespace,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    flow_start = flows["startTime"].min()
    flow_end = flows["startTime"].max()
    price_start = prices["price_hour"].min()
    price_end = prices["price_hour"].max() + pd.Timedelta(minutes=30)
    latest_common = min(flow_end, price_end)

    start = (
        normalise_timestamp(args.start)
        or normalise_timestamp(run_config.get("analysis_start"))
        or infer_default_start(latest_common, args.years)
    )
    end = normalise_timestamp(args.end) or normalise_timestamp(run_config.get("analysis_end")) or latest_common
    start = max(start, flow_start, price_start)
    end = min(end, flow_end, price_end)
    if start > end:
        raise ValueError(f"No overlapping flow/price window: {start} is after {end}")
    return start, end


def add_price_spread_fields(df: pd.DataFrame, price_deadband: float) -> pd.DataFrame:
    out = df.copy()
    out["abs_price_spread"] = out["price_spread_gb_minus_zone"].abs()
    out["price_spread_direction"] = np.select(
        [
            out["price_spread_gb_minus_zone"] > price_deadband,
            out["price_spread_gb_minus_zone"] < -price_deadband,
        ],
        ["gb_higher_expected_import", "zone_higher_expected_export"],
        default="near_parity",
    )
    out["economic_alignment"] = np.select(
        [
            out["price_spread_direction"].eq("near_parity"),
            out["direction_state"].eq("near_zero") & out["price_spread_direction"].ne("near_parity"),
            out["price_spread_direction"].eq("gb_higher_expected_import") & out["direction_state"].eq("import"),
            out["price_spread_direction"].eq("zone_higher_expected_export") & out["direction_state"].eq("export"),
            out["price_spread_direction"].eq("gb_higher_expected_import") & out["direction_state"].eq("export"),
            out["price_spread_direction"].eq("zone_higher_expected_export") & out["direction_state"].eq("import"),
        ],
        [
            "price_near_parity",
            "flow_near_zero_while_price_signal",
            "aligned_with_price_spread",
            "aligned_with_price_spread",
            "counter_price_spread",
            "counter_price_spread",
        ],
        default="other",
    )
    out["spread_band"] = pd.cut(out["price_spread_gb_minus_zone"], SPREAD_BINS, labels=SPREAD_LABELS, right=True)
    out["spread_band_label"] = out["spread_band"].astype(str).map(SPREAD_BAND_LABELS)
    out["flow_sign"] = np.select(
        [out["direction_state"].eq("import"), out["direction_state"].eq("export")],
        [1, -1],
        default=0,
    )
    out["spread_sign"] = np.select(
        [
            out["price_spread_direction"].eq("gb_higher_expected_import"),
            out["price_spread_direction"].eq("zone_higher_expected_export"),
        ],
        [1, -1],
        default=0,
    )
    return out


def join_flows_and_prices(
    flows: pd.DataFrame,
    price_long: pd.DataFrame,
    mapping: pd.DataFrame,
    price_deadband: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    flows = flows.merge(
        mapping[["interconnectorId", "price_zone_code"]],
        on="interconnectorId",
        how="left",
    )
    flows["price_hour"] = flows["startTime"].dt.floor("h")
    joined = flows.merge(price_long, on=["price_hour", "price_zone_code"], how="left")

    coverage = (
        joined.groupby(["interconnectorId", "interconnectorName", "interconnectorBiddingZone", "price_zone_code"], sort=True)
        .agg(
            flow_observations=("signed_mw", "size"),
            joined_price_observations=("price_spread_gb_minus_zone", lambda s: s.notna().sum()),
            missing_price_observations=("price_spread_gb_minus_zone", lambda s: s.isna().sum()),
            first_flow_timestamp=("startTime", "min"),
            last_flow_timestamp=("startTime", "max"),
            first_price_hour=("price_hour", "min"),
            last_price_hour=("price_hour", "max"),
        )
        .reset_index()
    )
    coverage["price_join_coverage_pct"] = coverage["joined_price_observations"] / coverage["flow_observations"] * 100.0

    joined = joined.dropna(subset=["price_spread_gb_minus_zone", "gb_price", "zone_price"]).copy()
    joined = add_price_spread_fields(joined, price_deadband)
    return joined, coverage


def safe_corr(x: pd.Series, y: pd.Series, min_observations: int, method: str = "pearson") -> float:
    data = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(data) < min_observations or data["x"].nunique() < 2 or data["y"].nunique() < 2:
        return np.nan
    return float(data["x"].corr(data["y"], method=method))


def regression_stats(x: pd.Series, y: pd.Series, min_observations: int) -> dict[str, float]:
    data = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(data) < min_observations or data["x"].nunique() < 2 or data["y"].nunique() < 2:
        return {"slope_mw_per_price_unit": np.nan, "intercept_mw": np.nan, "r2": np.nan}
    slope, intercept = np.polyfit(data["x"].to_numpy(dtype=float), data["y"].to_numpy(dtype=float), 1)
    fitted = slope * data["x"] + intercept
    ss_res = float(((data["y"] - fitted) ** 2).sum())
    ss_tot = float(((data["y"] - data["y"].mean()) ** 2).sum())
    return {
        "slope_mw_per_price_unit": float(slope),
        "intercept_mw": float(intercept),
        "r2": np.nan if ss_tot == 0 else 1.0 - ss_res / ss_tot,
    }


def pct(part: float, whole: float) -> float:
    return np.nan if whole == 0 or pd.isna(whole) else part / whole * 100.0


def build_correlation_summary(joined: pd.DataFrame, min_observations: int) -> pd.DataFrame:
    rows = []
    for keys, group in joined.groupby(
        ["interconnectorId", "interconnectorName", "interconnectorBiddingZone", "price_zone_code"],
        sort=True,
    ):
        interconnector_id, name, bidding_zone, price_zone = keys
        directional_signal = group["price_spread_direction"].ne("near_parity") & group["direction_state"].ne("near_zero")
        aligned = group["economic_alignment"].eq("aligned_with_price_spread")
        counter = group["economic_alignment"].eq("counter_price_spread")
        gb_higher = group["price_spread_direction"].eq("gb_higher_expected_import")
        zone_higher = group["price_spread_direction"].eq("zone_higher_expected_export")
        reg = regression_stats(group["price_spread_gb_minus_zone"], group["signed_mw"], min_observations)
        rows.append(
            {
                "interconnectorId": interconnector_id,
                "interconnectorName": name,
                "interconnectorBiddingZone": bidding_zone,
                "price_zone_code": price_zone,
                "observations": len(group),
                "first_timestamp": group["startTime"].min(),
                "last_timestamp": group["startTime"].max(),
                "mean_gb_price": group["gb_price"].mean(),
                "mean_zone_price": group["zone_price"].mean(),
                "mean_price_spread_gb_minus_zone": group["price_spread_gb_minus_zone"].mean(),
                "p10_price_spread": group["price_spread_gb_minus_zone"].quantile(0.10),
                "median_price_spread": group["price_spread_gb_minus_zone"].median(),
                "p90_price_spread": group["price_spread_gb_minus_zone"].quantile(0.90),
                "mean_signed_mw": group["signed_mw"].mean(),
                "mean_signed_pct_capacity": group["signed_pct_capacity"].mean(),
                "pearson_spread_vs_signed_mw": safe_corr(
                    group["price_spread_gb_minus_zone"], group["signed_mw"], min_observations
                ),
                "spearman_spread_vs_signed_mw": safe_corr(
                    group["price_spread_gb_minus_zone"], group["signed_mw"], min_observations, method="spearman"
                ),
                "pearson_spread_vs_signed_pct_capacity": safe_corr(
                    group["price_spread_gb_minus_zone"], group["signed_pct_capacity"], min_observations
                ),
                "pearson_abs_spread_vs_abs_signed_mw": safe_corr(
                    group["abs_price_spread"], group["signed_mw"].abs(), min_observations
                ),
                "pearson_abs_spread_vs_abs_pct_capacity": safe_corr(
                    group["abs_price_spread"], group["abs_pct_capacity"], min_observations
                ),
                "ols_slope_mw_per_price_unit": reg["slope_mw_per_price_unit"],
                "ols_intercept_mw": reg["intercept_mw"],
                "ols_r2": reg["r2"],
                "gb_higher_observations": int(gb_higher.sum()),
                "zone_higher_observations": int(zone_higher.sum()),
                "near_parity_observations": int(group["price_spread_direction"].eq("near_parity").sum()),
                "import_share_when_gb_higher_pct": (group.loc[gb_higher, "direction_state"] == "import").mean() * 100.0,
                "export_share_when_zone_higher_pct": (group.loc[zone_higher, "direction_state"] == "export").mean() * 100.0,
                "mean_signed_mw_when_gb_higher": group.loc[gb_higher, "signed_mw"].mean(),
                "mean_signed_mw_when_zone_higher": group.loc[zone_higher, "signed_mw"].mean(),
                "directional_signal_observations": int(directional_signal.sum()),
                "aligned_observations": int((aligned & directional_signal).sum()),
                "counter_price_observations": int((counter & directional_signal).sum()),
                "aligned_share_of_directional_signal_pct": pct((aligned & directional_signal).sum(), directional_signal.sum()),
                "counter_share_of_directional_signal_pct": pct((counter & directional_signal).sum(), directional_signal.sum()),
            }
        )
    return pd.DataFrame(rows)


def summarise_price_spread_bands(joined: pd.DataFrame) -> pd.DataFrame:
    grouped = joined.groupby(
        [
            "interconnectorId",
            "interconnectorName",
            "interconnectorBiddingZone",
            "price_zone_code",
            "spread_band",
            "spread_band_label",
        ],
        observed=False,
        sort=True,
    )
    out = grouped.agg(
        observations=("signed_mw", "size"),
        mean_price_spread_gb_minus_zone=("price_spread_gb_minus_zone", "mean"),
        median_price_spread_gb_minus_zone=("price_spread_gb_minus_zone", "median"),
        mean_signed_mw=("signed_mw", "mean"),
        median_signed_mw=("signed_mw", "median"),
        mean_signed_pct_capacity=("signed_pct_capacity", "mean"),
        mean_import_mw=("import_mw", "mean"),
        mean_export_mw=("export_mw", "mean"),
        import_share_pct=("direction_state", lambda s: (s == "import").mean() * 100.0),
        export_share_pct=("direction_state", lambda s: (s == "export").mean() * 100.0),
        near_zero_share_pct=("direction_state", lambda s: (s == "near_zero").mean() * 100.0),
        aligned_share_pct=("economic_alignment", lambda s: (s == "aligned_with_price_spread").mean() * 100.0),
        counter_price_share_pct=("economic_alignment", lambda s: (s == "counter_price_spread").mean() * 100.0),
        import_gwh=("import_gwh", "sum"),
        export_gwh=("export_gwh", "sum"),
        net_gwh=("net_gwh", "sum"),
    ).reset_index()
    totals = out.groupby("interconnectorId")["observations"].transform("sum")
    out["duration_hours"] = out["observations"] * 0.5
    out["duration_share_pct"] = out["observations"] / totals * 100.0
    out["spread_band"] = out["spread_band"].astype(str)
    out["spread_band_order"] = out["spread_band"].map({label: index for index, label in enumerate(SPREAD_LABELS)})
    columns = [
        "interconnectorId",
        "interconnectorName",
        "interconnectorBiddingZone",
        "price_zone_code",
        "spread_band_order",
        "spread_band",
        "spread_band_label",
        "observations",
        "duration_hours",
        "duration_share_pct",
        "mean_price_spread_gb_minus_zone",
        "median_price_spread_gb_minus_zone",
        "mean_signed_mw",
        "median_signed_mw",
        "mean_signed_pct_capacity",
        "mean_import_mw",
        "mean_export_mw",
        "import_share_pct",
        "export_share_pct",
        "near_zero_share_pct",
        "aligned_share_pct",
        "counter_price_share_pct",
        "import_gwh",
        "export_gwh",
        "net_gwh",
    ]
    return out[columns].sort_values(["interconnectorId", "spread_band_order"]).reset_index(drop=True)


def summarise_quantile_bands(joined: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for _, group in joined.groupby("interconnectorId", sort=True):
        group = group.copy()
        spread = group["price_spread_gb_minus_zone"]
        quantiles = pd.qcut(spread, q=10, duplicates="drop")
        group["spread_quantile_order"] = quantiles.cat.codes + 1
        group["spread_quantile_band"] = quantiles.astype(str)
        parts.append(group)
    with_quantiles = pd.concat(parts, ignore_index=True)
    grouped = with_quantiles.groupby(
        [
            "interconnectorId",
            "interconnectorName",
            "interconnectorBiddingZone",
            "price_zone_code",
            "spread_quantile_order",
            "spread_quantile_band",
        ],
        sort=True,
    )
    out = grouped.agg(
        observations=("signed_mw", "size"),
        min_price_spread=("price_spread_gb_minus_zone", "min"),
        max_price_spread=("price_spread_gb_minus_zone", "max"),
        mean_price_spread_gb_minus_zone=("price_spread_gb_minus_zone", "mean"),
        mean_signed_mw=("signed_mw", "mean"),
        mean_signed_pct_capacity=("signed_pct_capacity", "mean"),
        import_share_pct=("direction_state", lambda s: (s == "import").mean() * 100.0),
        export_share_pct=("direction_state", lambda s: (s == "export").mean() * 100.0),
        aligned_share_pct=("economic_alignment", lambda s: (s == "aligned_with_price_spread").mean() * 100.0),
        counter_price_share_pct=("economic_alignment", lambda s: (s == "counter_price_spread").mean() * 100.0),
    ).reset_index()
    out["duration_hours"] = out["observations"] * 0.5
    return out.sort_values(["interconnectorId", "spread_quantile_order"]).reset_index(drop=True)


def build_alignment_summary(joined: pd.DataFrame) -> pd.DataFrame:
    counts = (
        joined.groupby(
            [
                "interconnectorId",
                "interconnectorName",
                "interconnectorBiddingZone",
                "price_zone_code",
                "economic_alignment",
            ],
            sort=True,
        )
        .size()
        .rename("observations")
        .reset_index()
    )
    total = counts.groupby("interconnectorId")["observations"].transform("sum")
    counts["duration_hours"] = counts["observations"] * 0.5
    counts["share_pct"] = counts["observations"] / total * 100.0
    counts["economic_alignment_label"] = counts["economic_alignment"].map(ALIGNMENT_LABELS).fillna(counts["economic_alignment"])
    return counts


def period_average(joined: pd.DataFrame, period_col: str) -> pd.DataFrame:
    grouped = joined.groupby(
        ["interconnectorId", "interconnectorName", "interconnectorBiddingZone", "price_zone_code", period_col],
        sort=True,
    )
    out = grouped.agg(
        observations=("signed_mw", "size"),
        mean_price_spread_gb_minus_zone=("price_spread_gb_minus_zone", "mean"),
        mean_signed_mw=("signed_mw", "mean"),
        mean_signed_pct_capacity=("signed_pct_capacity", "mean"),
        mean_abs_price_spread=("abs_price_spread", "mean"),
        mean_abs_signed_mw=("signed_mw", lambda s: s.abs().mean()),
        import_share_pct=("direction_state", lambda s: (s == "import").mean() * 100.0),
        export_share_pct=("direction_state", lambda s: (s == "export").mean() * 100.0),
        aligned_share_pct=("economic_alignment", lambda s: (s == "aligned_with_price_spread").mean() * 100.0),
    ).reset_index()
    return out


def build_frequency_correlation_summary(
    joined: pd.DataFrame,
    daily: pd.DataFrame,
    monthly: pd.DataFrame,
    min_observations: int,
) -> pd.DataFrame:
    frames = {
        "half_hourly": joined.rename(
            columns={
                "price_spread_gb_minus_zone": "mean_price_spread_gb_minus_zone",
                "signed_mw": "mean_signed_mw",
                "signed_pct_capacity": "mean_signed_pct_capacity",
                "abs_price_spread": "mean_abs_price_spread",
            }
        ),
        "daily": daily,
        "monthly": monthly,
    }
    rows = []
    for frequency, frame in frames.items():
        for keys, group in frame.groupby(
            ["interconnectorId", "interconnectorName", "interconnectorBiddingZone", "price_zone_code"],
            sort=True,
        ):
            interconnector_id, name, bidding_zone, price_zone = keys
            signed_col = "mean_signed_mw"
            pct_col = "mean_signed_pct_capacity"
            spread_col = "mean_price_spread_gb_minus_zone"
            rows.append(
                {
                    "frequency": frequency,
                    "interconnectorId": interconnector_id,
                    "interconnectorName": name,
                    "interconnectorBiddingZone": bidding_zone,
                    "price_zone_code": price_zone,
                    "observations": len(group),
                    "pearson_spread_vs_signed_mw": safe_corr(group[spread_col], group[signed_col], min_observations),
                    "spearman_spread_vs_signed_mw": safe_corr(
                        group[spread_col], group[signed_col], min_observations, method="spearman"
                    ),
                    "pearson_spread_vs_signed_pct_capacity": safe_corr(group[spread_col], group[pct_col], min_observations),
                    "pearson_abs_spread_vs_abs_signed_mw": safe_corr(
                        group["mean_abs_price_spread"], group["mean_abs_signed_mw"], min_observations
                    )
                    if "mean_abs_signed_mw" in group.columns
                    else np.nan,
                }
            )
    return pd.DataFrame(rows)


def build_lag_correlation_summary(joined: pd.DataFrame, min_observations: int) -> pd.DataFrame:
    lag_hours = [-24, -12, -6, -3, -1, 0, 1, 3, 6, 12, 24]
    rows = []
    for keys, group in joined.groupby(
        ["interconnectorId", "interconnectorName", "interconnectorBiddingZone", "price_zone_code"],
        sort=True,
    ):
        interconnector_id, name, bidding_zone, price_zone = keys
        group = group.sort_values("startTime").copy()
        for lag in lag_hours:
            lag_steps = int(lag * 2)
            spread = group["price_spread_gb_minus_zone"].shift(lag_steps)
            rows.append(
                {
                    "interconnectorId": interconnector_id,
                    "interconnectorName": name,
                    "interconnectorBiddingZone": bidding_zone,
                    "price_zone_code": price_zone,
                    "spread_leads_flow_hours": lag,
                    "observations": pd.DataFrame({"x": spread, "y": group["signed_mw"]}).dropna().shape[0],
                    "pearson_spread_vs_signed_mw": safe_corr(spread, group["signed_mw"], min_observations),
                    "spearman_spread_vs_signed_mw": safe_corr(spread, group["signed_mw"], min_observations, method="spearman"),
                }
            )
    return pd.DataFrame(rows)


def require_plotly():
    try:
        import plotly.graph_objects as go
        import plotly.express as px
    except ImportError as exc:
        raise RuntimeError("Plotly is required for price-spread figures. Rerun with --no-figures or install plotly.") from exc
    return go, px


def plotly_layout(fig, title: str) -> None:
    fig.update_layout(
        title=title,
        template="plotly_white",
        font={"family": "Arial, sans-serif", "size": 12},
        legend={"orientation": "h", "yanchor": "bottom", "y": -0.25, "xanchor": "center", "x": 0.5},
        margin={"l": 80, "r": 40, "t": 70, "b": 90},
    )


def generate_figures(
    output_dir: Path,
    correlation: pd.DataFrame,
    band_summary: pd.DataFrame,
    alignment: pd.DataFrame,
    lag_correlation: pd.DataFrame,
    daily: pd.DataFrame,
) -> None:
    go, px = require_plotly()
    figure_dir = output_dir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)

    corr = correlation.sort_values("pearson_spread_vs_signed_mw")
    colors = np.where(corr["pearson_spread_vs_signed_mw"] >= 0, "#2f6db2", "#c43c39")
    fig = go.Figure(
        go.Bar(
            y=corr["interconnectorId"],
            x=corr["pearson_spread_vs_signed_mw"],
            orientation="h",
            marker_color=colors,
            text=corr["pearson_spread_vs_signed_mw"].map(lambda value: f"{value:.2f}"),
            textposition="outside",
        )
    )
    fig.add_vline(x=0, line_color="#777777", line_width=1)
    fig.update_layout(xaxis_title="Pearson correlation: GB-zone spread vs signed MW", yaxis_title="", showlegend=False)
    plotly_layout(fig, "Price Spread vs Flow Correlation by Interconnector")
    fig.write_html(figure_dir / "spread_flow_correlation_by_interconnector.html", include_plotlyjs="directory")

    bands = band_summary.copy()
    pivot = bands.pivot_table(
        index="interconnectorId",
        columns="spread_band_label",
        values="mean_signed_mw",
        aggfunc="mean",
    )
    ordered_labels = [SPREAD_BAND_LABELS[label] for label in SPREAD_LABELS]
    pivot = pivot.reindex(index=sorted(pivot.index), columns=ordered_labels)
    max_abs = float(np.nanmax(np.abs(pivot.to_numpy()))) if pivot.size else 1.0
    fig = go.Figure(
        go.Heatmap(
            z=pivot.to_numpy(),
            x=list(pivot.columns),
            y=list(pivot.index),
            colorscale="RdBu",
            zmin=-max_abs,
            zmax=max_abs,
            colorbar={"title": "Mean signed MW"},
        )
    )
    fig.update_layout(xaxis_title="Price spread band (GB price minus zone price)", yaxis_title="", height=680)
    plotly_layout(fig, "Mean Flow by Price Spread Band")
    fig.write_html(figure_dir / "spread_band_mean_flow_heatmap.html", include_plotlyjs="directory")

    align_pivot = alignment.pivot_table(
        index="interconnectorId",
        columns="economic_alignment_label",
        values="share_pct",
        aggfunc="sum",
        fill_value=0,
    )
    alignment_order = [ALIGNMENT_LABELS[key] for key in ALIGNMENT_LABELS]
    align_pivot = align_pivot.reindex(index=sorted(align_pivot.index), columns=alignment_order, fill_value=0)
    fig = go.Figure()
    colors_by_alignment = {
        "Aligned with spread": "#2f6db2",
        "Counter-spread": "#c43c39",
        "Flow near zero while spread signals": "#8f9aa7",
        "Price near parity": "#d9d9d9",
    }
    for col in align_pivot.columns:
        fig.add_bar(
            y=align_pivot.index,
            x=align_pivot[col],
            name=col,
            orientation="h",
            marker_color=colors_by_alignment.get(col, "#999999"),
        )
    fig.update_layout(barmode="stack", xaxis_title="Share of joined half-hours (%)", yaxis_title="", height=650)
    plotly_layout(fig, "Flow Direction Alignment with Price Spread")
    fig.write_html(figure_dir / "spread_direction_alignment_by_interconnector.html", include_plotlyjs="directory")

    lag_pivot = lag_correlation.pivot_table(
        index="interconnectorId",
        columns="spread_leads_flow_hours",
        values="pearson_spread_vs_signed_mw",
        aggfunc="mean",
    )
    lag_pivot = lag_pivot.reindex(index=sorted(lag_pivot.index), columns=sorted(lag_pivot.columns))
    fig = go.Figure(
        go.Heatmap(
            z=lag_pivot.to_numpy(),
            x=list(lag_pivot.columns),
            y=list(lag_pivot.index),
            colorscale="RdBu",
            zmin=-1,
            zmax=1,
            colorbar={"title": "Correlation"},
        )
    )
    fig.update_layout(xaxis_title="Spread leads flow by hours", yaxis_title="", height=620)
    plotly_layout(fig, "Lagged Price Spread vs Flow Correlation")
    fig.write_html(figure_dir / "spread_lag_correlation_heatmap.html", include_plotlyjs="directory")

    scatter = daily.copy()
    scatter["interconnector_label"] = scatter["interconnectorId"] + " - " + scatter["price_zone_code"]
    fig = px.scatter(
        scatter,
        x="mean_price_spread_gb_minus_zone",
        y="mean_signed_mw",
        facet_col="interconnectorId",
        facet_col_wrap=2,
        opacity=0.45,
        color="price_zone_code",
        labels={
            "mean_price_spread_gb_minus_zone": "Daily mean spread (GB - zone)",
            "mean_signed_mw": "Daily mean signed MW",
        },
    )
    fig.add_hline(y=0, line_color="#777777", line_width=1)
    fig.add_vline(x=0, line_color="#777777", line_width=1)
    fig.update_layout(height=1300)
    plotly_layout(fig, "Daily Flow vs Price Spread")
    fig.write_html(figure_dir / "daily_spread_flow_scatter_by_interconnector.html", include_plotlyjs="directory")


def build_story(
    output_dir: Path,
    correlation: pd.DataFrame,
    band_summary: pd.DataFrame,
    alignment_summary: pd.DataFrame,
    frequency_correlation: pd.DataFrame,
    lag_correlation: pd.DataFrame,
    analysis_start: pd.Timestamp,
    analysis_end: pd.Timestamp,
    price_deadband: float,
) -> None:
    corr = correlation.copy()
    corr["abs_corr"] = corr["pearson_spread_vs_signed_mw"].abs()
    top = corr.sort_values("abs_corr", ascending=False).head(5)
    weak = corr.sort_values("abs_corr").head(3)

    directional = correlation.sort_values("aligned_share_of_directional_signal_pct", ascending=False)
    best_alignment = directional.head(5)
    worst_alignment = directional.tail(3)

    daily_corr = frequency_correlation[frequency_correlation["frequency"] == "daily"].copy()
    daily_corr["abs_corr"] = daily_corr["pearson_spread_vs_signed_mw"].abs()
    best_daily = daily_corr.sort_values("abs_corr", ascending=False).head(3)

    best_lags = (
        lag_correlation.assign(abs_corr=lag_correlation["pearson_spread_vs_signed_mw"].abs())
        .sort_values(["interconnectorId", "abs_corr"], ascending=[True, False])
        .groupby("interconnectorId", sort=True)
        .head(1)
    )

    lines = [
        "# Interconnector Flow and Price Spread Relationship",
        "",
        f"Analysis window: {analysis_start.date()} to {analysis_end.date()}.",
        "",
        "Spread convention: `price_spread_gb_minus_zone = GB price - bidding-zone price`. Positive spread means GB is more expensive than the linked market, so GB import is the price-aligned direction. Negative spread means export is price-aligned.",
        f"Near parity is defined as absolute spread <= {format_num(price_deadband, 1)} in the price-file units.",
        "",
        "Recommended visuals: `figures/spread_flow_correlation_by_interconnector.*`, `figures/spread_band_mean_flow_heatmap.*`, `figures/spread_direction_alignment_by_interconnector.*`, `figures/spread_lag_correlation_heatmap.*`, and `figures/daily_spread_flow_scatter_by_interconnector.*`.",
        "",
        "## Headline",
        "",
    ]

    if not corr.empty:
        mean_abs_corr = corr["abs_corr"].mean()
        lines.append(
            f"- Average absolute half-hourly correlation between spread and signed MW is {format_num(mean_abs_corr, 2)} across interconnectors."
        )
        lines.append(
            "- Positive correlation means flows tend to move towards GB when GB is higher priced and away from GB when the linked market is higher priced."
        )
        lines.append("")

    lines.extend(["## Strongest Price-Flow Relationships", ""])
    for _, row in top.iterrows():
        lines.append(
            f"- {row['interconnectorId']} ({row['price_zone_code']}): Pearson {format_num(row['pearson_spread_vs_signed_mw'], 2)}, "
            f"Spearman {format_num(row['spearman_spread_vs_signed_mw'], 2)}, OLS slope {format_num(row['ols_slope_mw_per_price_unit'], 1)} MW per price unit, "
            f"directional alignment {format_pct(row['aligned_share_of_directional_signal_pct'])}."
        )

    lines.extend(["", "Weakest relationships:", ""])
    for _, row in weak.iterrows():
        lines.append(
            f"- {row['interconnectorId']} ({row['price_zone_code']}): Pearson {format_num(row['pearson_spread_vs_signed_mw'], 2)}, "
            f"directional alignment {format_pct(row['aligned_share_of_directional_signal_pct'])}."
        )

    lines.extend(["", "## Directional Alignment", ""])
    for _, row in best_alignment.iterrows():
        lines.append(
            f"- {row['interconnectorId']}: {format_pct(row['aligned_share_of_directional_signal_pct'])} of directional price-signal half-hours align with flow direction; "
            f"{format_pct(row['counter_share_of_directional_signal_pct'])} counter the spread."
        )
    if not worst_alignment.empty:
        lines.append("")
        lines.append("Lower-alignment links to inspect:")
        for _, row in worst_alignment.iterrows():
            lines.append(
                f"- {row['interconnectorId']}: aligned {format_pct(row['aligned_share_of_directional_signal_pct'])}, counter {format_pct(row['counter_share_of_directional_signal_pct'])}."
            )

    lines.extend(["", "## Spread Bands", ""])
    for interconnector_id, group in band_summary[band_summary["observations"] > 0].groupby("interconnectorId", sort=True):
        max_import = group.sort_values("mean_signed_mw", ascending=False).iloc[0]
        max_export = group.sort_values("mean_signed_mw", ascending=True).iloc[0]
        import_label = "strongest net import band" if max_import["mean_signed_mw"] > 0 else "least export-leaning band"
        export_label = "strongest net export band" if max_export["mean_signed_mw"] < 0 else "weakest import band"
        lines.append(
            f"- {interconnector_id}: {import_label} is `{max_import['spread_band_label']}` ({format_num(max_import['mean_signed_mw'])} MW); "
            f"{export_label} is `{max_export['spread_band_label']}` ({format_num(max_export['mean_signed_mw'])} MW)."
        )

    lines.extend(["", "## Daily and Lag Checks", ""])
    for _, row in best_daily.iterrows():
        lines.append(
            f"- Daily {row['interconnectorId']}: Pearson {format_num(row['pearson_spread_vs_signed_mw'], 2)} between daily mean spread and daily mean signed MW."
        )
    lines.append("")
    lines.append("Best lag by absolute correlation, where positive lag means spread leads flow:")
    for _, row in best_lags.iterrows():
        lines.append(
            f"- {row['interconnectorId']}: {format_num(row['spread_leads_flow_hours'], 0)} hours, Pearson {format_num(row['pearson_spread_vs_signed_mw'], 2)}."
        )

    lines.extend(
        [
            "",
            "## Tables Written",
            "",
            "- `price_spread_correlation_summary.csv`",
            "- `price_spread_correlation_by_frequency.csv`",
            "- `price_spread_band_summary.csv`",
            "- `price_spread_quantile_summary.csv`",
            "- `price_spread_direction_alignment_summary.csv`",
            "- `price_spread_lag_correlation_summary.csv`",
            "- `price_spread_daily_summary.csv`",
            "- `price_spread_monthly_summary.csv`",
            "- `interconnector_price_spread_join_coverage.csv`",
            "- `interconnector_price_spread_join_half_hourly.csv.gz`",
            "",
            "Caveat: this uses the price columns as supplied. If GB and continental price series are not already currency-normalised, the spread should be interpreted as a raw index spread rather than a clean arbitrage value.",
            "",
        ]
    )
    (output_dir / "story.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    metadata = read_metadata(args.metadata)
    prices = read_prices(args.price_file, args.price_time_shift_hours)
    mapping = build_zone_mapping(metadata, prices)
    price_long = melt_prices(prices, mapping["price_zone_code"].tolist())

    flows = read_half_hourly_data(args.interconnector_data_dir, metadata, args.positive_direction)
    run_config = read_run_config(args.interconnector_run_config)
    analysis_start, analysis_end = choose_analysis_window(flows, prices, run_config, args)
    flows = flows[(flows["startTime"] >= analysis_start) & (flows["startTime"] <= analysis_end)].copy()
    capacity_reference = build_capacity_reference(flows, args.capacity_file)
    flows = add_calendar_fields(flows, args.flow_deadband_mw)
    flows = add_capacity_fields(flows, capacity_reference)

    joined, coverage = join_flows_and_prices(flows, price_long, mapping, args.price_deadband)
    joined["calendar_month"] = joined["startTime"].dt.strftime("%Y-%m")

    correlation = build_correlation_summary(joined, args.min_correlation_observations)
    band_summary = summarise_price_spread_bands(joined)
    quantile_summary = summarise_quantile_bands(joined)
    alignment_summary = build_alignment_summary(joined)
    daily = period_average(joined, "date")
    monthly = period_average(joined, "calendar_month")
    frequency_correlation = build_frequency_correlation_summary(
        joined,
        daily,
        monthly,
        args.min_correlation_observations,
    )
    lag_correlation = build_lag_correlation_summary(joined, args.min_correlation_observations)

    write_csv(mapping, args.output_dir / "zone_price_mapping.csv")
    write_csv(coverage, args.output_dir / "interconnector_price_spread_join_coverage.csv")
    joined.to_csv(args.output_dir / "interconnector_price_spread_join_half_hourly.csv.gz", index=False)
    write_csv(correlation, args.output_dir / "price_spread_correlation_summary.csv")
    write_csv(frequency_correlation, args.output_dir / "price_spread_correlation_by_frequency.csv")
    write_csv(band_summary, args.output_dir / "price_spread_band_summary.csv")
    write_csv(quantile_summary, args.output_dir / "price_spread_quantile_summary.csv")
    write_csv(alignment_summary, args.output_dir / "price_spread_direction_alignment_summary.csv")
    write_csv(lag_correlation, args.output_dir / "price_spread_lag_correlation_summary.csv")
    write_csv(daily, args.output_dir / "price_spread_daily_summary.csv")
    write_csv(monthly, args.output_dir / "price_spread_monthly_summary.csv")
    write_csv(capacity_reference, args.output_dir / "capacity_reference.csv")

    build_story(
        args.output_dir,
        correlation,
        band_summary,
        alignment_summary,
        frequency_correlation,
        lag_correlation,
        analysis_start,
        analysis_end,
        args.price_deadband,
    )

    run_config_text = textwrap.dedent(
        f"""\
        analysis_start,{analysis_start}
        analysis_end,{analysis_end}
        positive_direction,{args.positive_direction}
        flow_deadband_mw,{args.flow_deadband_mw}
        price_deadband,{args.price_deadband}
        price_time_shift_hours,{args.price_time_shift_hours}
        interconnector_data_dir,{args.interconnector_data_dir}
        price_file,{args.price_file}
        metadata_file,{args.metadata}
        capacity_file,{args.capacity_file if args.capacity_file.exists() else "not supplied; observed peak used"}
        """
    )
    (args.output_dir / "run_config.csv").write_text(run_config_text, encoding="utf-8")

    if not args.no_figures:
        generate_figures(args.output_dir, correlation, band_summary, alignment_summary, lag_correlation, daily)

    print(f"Wrote price-spread analysis pack to {args.output_dir}")
    print(f"Analysis window: {analysis_start} to {analysis_end}")
    print("Spread convention: GB price minus linked-zone price")


if __name__ == "__main__":
    main()
