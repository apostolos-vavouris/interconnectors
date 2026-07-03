"""Analyse GB interconnector half-hourly BM operating history.

The input files are expected to live in ``HH_data`` and contain:

    startTime, settlementPeriod, generation

By default the script treats positive ``generation`` as GB import and negative
``generation`` as GB export. If the upstream sign convention is confirmed to be
the opposite, rerun with ``--positive-direction export``.
"""

from __future__ import annotations

import argparse
import calendar
import math
import textwrap
from itertools import combinations
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


HH_HOURS = 0.5
GWH_PER_MW_HALF_HOUR = HH_HOURS / 1000.0

SEASON_BY_MONTH = {
    12: "Winter",
    1: "Winter",
    2: "Winter",
    3: "Spring",
    4: "Spring",
    5: "Spring",
    6: "Summer",
    7: "Summer",
    8: "Summer",
    9: "Autumn",
    10: "Autumn",
    11: "Autumn",
}

LEVEL_BINS = [
    -math.inf,
    -1500,
    -1000,
    -500,
    -250,
    -50,
    50,
    250,
    500,
    1000,
    1500,
    math.inf,
]
LEVEL_LABELS = [
    "export_gt_1500_mw",
    "export_1000_1500_mw",
    "export_500_1000_mw",
    "export_250_500_mw",
    "export_50_250_mw",
    "near_zero_abs_le_50_mw",
    "import_50_250_mw",
    "import_250_500_mw",
    "import_500_1000_mw",
    "import_1000_1500_mw",
    "import_gt_1500_mw",
]

PCT_CAPACITY_BINS = [-math.inf, -75, -50, -25, -5, 5, 25, 50, 75, math.inf]
PCT_CAPACITY_LABELS = [
    "export_gt_75pct_capacity",
    "export_50_75pct_capacity",
    "export_25_50pct_capacity",
    "export_5_25pct_capacity",
    "near_zero_abs_le_5pct_capacity",
    "import_5_25pct_capacity",
    "import_25_50pct_capacity",
    "import_50_75pct_capacity",
    "import_gt_75pct_capacity",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate operating statistics and charts for GB interconnector BM half-hourly data."
    )
    parser.add_argument("--data-dir", type=Path, default=Path("HH_data"), help="Folder containing one CSV per interconnector.")
    parser.add_argument(
        "--metadata",
        type=Path,
        default=Path("interconnectors_names.csv"),
        help="Optional interconnector metadata CSV.",
    )
    parser.add_argument(
        "--capacity-file",
        type=Path,
        default=Path("interconnector_capacities.csv"),
        help=(
            "Optional CSV with interconnectorId,capacity_mw. If absent, capacity is inferred "
            "from the max absolute observed MW in the analysis window."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("analysis_outputs") / "bm_interconnector_history",
        help="Folder to write tables, figures, and story.md.",
    )
    parser.add_argument(
        "--years",
        type=int,
        default=5,
        help="Default lookback length when --start is not supplied. Uses the latest timestamp in the data.",
    )
    parser.add_argument("--start", type=str, default=None, help="Inclusive analysis start timestamp, e.g. 2021-07-01.")
    parser.add_argument("--end", type=str, default=None, help="Inclusive analysis end timestamp, e.g. 2026-06-30T22:30Z.")
    parser.add_argument(
        "--positive-direction",
        choices=["import", "export"],
        default="import",
        help="How to interpret positive values in the raw generation column.",
    )
    parser.add_argument(
        "--deadband-mw",
        type=float,
        default=1.0,
        help="Absolute MW threshold treated as near-zero for direction shares and switching metrics.",
    )
    parser.add_argument("--no-charts", action="store_true", help="Skip PNG chart generation.")
    return parser.parse_args()


def normalise_timestamp(value: str | pd.Timestamp | None) -> pd.Timestamp | None:
    if value is None:
        return None
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def infer_default_start(latest_ts: pd.Timestamp, years: int) -> pd.Timestamp:
    """Return a clean whole-day lookback start.

    With data ending on 2026-06-30 22:30 UTC, this returns 2021-07-01 00:00 UTC:
    five complete years by settlement date, rather than a mid-evening timestamp.
    """

    latest_day = latest_ts.floor("D")
    return latest_day - pd.DateOffset(years=years) + pd.Timedelta(days=1)


def read_metadata(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["interconnectorId", "interconnectorName", "interconnectorBiddingZone", "StartedOperations"])

    metadata = pd.read_csv(path)
    metadata = metadata.loc[:, ~metadata.columns.str.startswith("Unnamed")]
    expected = {"interconnectorId", "interconnectorName", "interconnectorBiddingZone"}
    missing = expected.difference(metadata.columns)
    if missing:
        raise ValueError(f"Metadata file {path} is missing expected columns: {sorted(missing)}")
    return metadata


def read_half_hourly_data(data_dir: Path, metadata: pd.DataFrame, positive_direction: str) -> pd.DataFrame:
    files = sorted(data_dir.glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"No CSV files found in {data_dir}")

    frames: list[pd.DataFrame] = []
    for path in files:
        df = pd.read_csv(path)
        required = {"startTime", "settlementPeriod", "generation"}
        missing = required.difference(df.columns)
        if missing:
            raise ValueError(f"{path} is missing expected columns: {sorted(missing)}")

        df = df[["startTime", "settlementPeriod", "generation"]].copy()
        df["startTime"] = pd.to_datetime(df["startTime"], utc=True, errors="raise")
        df["settlementPeriod"] = pd.to_numeric(df["settlementPeriod"], errors="coerce").astype("Int64")
        df["raw_generation_mw"] = pd.to_numeric(df["generation"], errors="coerce")
        df = df.drop(columns=["generation"])
        df["interconnectorId"] = path.stem
        frames.append(df)

    data = pd.concat(frames, ignore_index=True)
    if data["raw_generation_mw"].isna().any():
        nulls = data.loc[data["raw_generation_mw"].isna(), "interconnectorId"].value_counts().to_dict()
        raise ValueError(f"Null or non-numeric generation values found: {nulls}")

    sign = 1 if positive_direction == "import" else -1
    data["signed_mw"] = data["raw_generation_mw"] * sign
    data["import_mw"] = data["signed_mw"].clip(lower=0)
    data["export_mw"] = (-data["signed_mw"]).clip(lower=0)

    if not metadata.empty:
        data = data.merge(metadata, how="left", on="interconnectorId")
    else:
        data["interconnectorName"] = data["interconnectorId"]
        data["interconnectorBiddingZone"] = pd.NA
        data["StartedOperations"] = pd.NA

    data["interconnectorName"] = data["interconnectorName"].fillna(data["interconnectorId"])
    data["interconnectorBiddingZone"] = data["interconnectorBiddingZone"].fillna("Unknown")
    return data.sort_values(["interconnectorId", "startTime"]).reset_index(drop=True)


def add_calendar_fields(df: pd.DataFrame, deadband_mw: float) -> pd.DataFrame:
    out = df.copy()
    out["date"] = out["startTime"].dt.floor("D")
    out["year"] = out["startTime"].dt.year
    out["month"] = out["startTime"].dt.month
    out["calendar_month"] = out["startTime"].dt.strftime("%Y-%m")
    out["season"] = out["month"].map(SEASON_BY_MONTH)
    out["season_year"] = out["year"] + (out["month"] == 12).astype(int)
    out["week"] = out["startTime"].dt.isocalendar().week.astype(int)
    out["hour_utc"] = out["startTime"].dt.hour + out["startTime"].dt.minute / 60.0
    out["import_gwh"] = out["import_mw"] * GWH_PER_MW_HALF_HOUR
    out["export_gwh"] = out["export_mw"] * GWH_PER_MW_HALF_HOUR
    out["net_gwh"] = out["signed_mw"] * GWH_PER_MW_HALF_HOUR
    out["direction_state"] = np.select(
        [out["signed_mw"] > deadband_mw, out["signed_mw"] < -deadband_mw],
        ["import", "export"],
        default="near_zero",
    )
    out["flow_band_mw"] = pd.cut(out["signed_mw"], bins=LEVEL_BINS, labels=LEVEL_LABELS, right=True)
    return out


def build_capacity_reference(df: pd.DataFrame, capacity_file: Path) -> pd.DataFrame:
    peaks = (
        df.groupby(["interconnectorId", "interconnectorName"], sort=True)
        .agg(
            observed_import_peak_mw=("import_mw", "max"),
            observed_export_peak_mw=("export_mw", "max"),
            observed_abs_peak_mw=("signed_mw", lambda s: s.abs().max()),
            observed_abs_p99_mw=("signed_mw", lambda s: s.abs().quantile(0.99)),
            observed_abs_p95_mw=("signed_mw", lambda s: s.abs().quantile(0.95)),
        )
        .reset_index()
    )
    peaks["capacity_mw"] = peaks["observed_abs_peak_mw"]
    peaks["capacity_source"] = "observed_abs_peak_in_analysis_window"

    if capacity_file.exists():
        supplied = pd.read_csv(capacity_file)
        required = {"interconnectorId", "capacity_mw"}
        missing = required.difference(supplied.columns)
        if missing:
            raise ValueError(f"{capacity_file} is missing expected columns: {sorted(missing)}")
        supplied = supplied[["interconnectorId", "capacity_mw"] + [col for col in ["capacity_source"] if col in supplied.columns]].copy()
        supplied["capacity_mw"] = pd.to_numeric(supplied["capacity_mw"], errors="raise")
        supplied["capacity_source"] = supplied.get("capacity_source", "supplied_capacity_file")
        supplied["capacity_source"] = supplied["capacity_source"].fillna("supplied_capacity_file")
        peaks = peaks.merge(supplied, on="interconnectorId", how="left", suffixes=("", "_supplied"))
        has_supplied = peaks["capacity_mw_supplied"].notna()
        peaks.loc[has_supplied, "capacity_mw"] = peaks.loc[has_supplied, "capacity_mw_supplied"]
        peaks.loc[has_supplied, "capacity_source"] = peaks.loc[has_supplied, "capacity_source_supplied"]
        peaks = peaks.drop(columns=[col for col in ["capacity_mw_supplied", "capacity_source_supplied"] if col in peaks.columns])

    total = {
        "interconnectorId": "TOTAL_GB_INTERCONNECTORS",
        "interconnectorName": "GB interconnector fleet total",
        "observed_import_peak_mw": df.groupby("startTime")["import_mw"].sum().max(),
        "observed_export_peak_mw": df.groupby("startTime")["export_mw"].sum().max(),
        "observed_abs_peak_mw": df.groupby("startTime")["signed_mw"].sum().abs().max(),
        "observed_abs_p99_mw": df.groupby("startTime")["signed_mw"].sum().abs().quantile(0.99),
        "observed_abs_p95_mw": df.groupby("startTime")["signed_mw"].sum().abs().quantile(0.95),
        "capacity_mw": peaks["capacity_mw"].sum(),
        "capacity_source": "sum_of_interconnector_capacity_mw",
    }
    return pd.concat([peaks, pd.DataFrame([total])], ignore_index=True)


def add_capacity_fields(df: pd.DataFrame, capacity_reference: pd.DataFrame) -> pd.DataFrame:
    out = df.merge(
        capacity_reference[["interconnectorId", "capacity_mw", "capacity_source"]],
        on="interconnectorId",
        how="left",
    )
    if out["capacity_mw"].isna().any():
        missing = sorted(out.loc[out["capacity_mw"].isna(), "interconnectorId"].unique())
        raise ValueError(f"Missing capacity reference for: {missing}")

    out["signed_pct_capacity"] = out["signed_mw"] / out["capacity_mw"] * 100.0
    out["import_pct_capacity"] = out["import_mw"] / out["capacity_mw"] * 100.0
    out["export_pct_capacity"] = out["export_mw"] / out["capacity_mw"] * 100.0
    out["abs_pct_capacity"] = out["signed_mw"].abs() / out["capacity_mw"] * 100.0
    out["flow_band_pct_capacity"] = pd.cut(
        out["signed_pct_capacity"],
        bins=PCT_CAPACITY_BINS,
        labels=PCT_CAPACITY_LABELS,
        right=True,
    )
    return out


def direction_switch_count(states: Iterable[str]) -> int:
    directional = [state for state in states if state in {"import", "export"}]
    if len(directional) <= 1:
        return 0
    return int(sum(current != previous for previous, current in zip(directional, directional[1:])))


def longest_true_run_hours(mask: pd.Series) -> float:
    if mask.empty:
        return 0.0
    groups = (mask != mask.shift()).cumsum()
    run_lengths = mask.groupby(groups).sum()
    return float(run_lengths.max() * HH_HOURS) if len(run_lengths) else 0.0


def expected_half_hours(first: pd.Timestamp, last: pd.Timestamp) -> int:
    if pd.isna(first) or pd.isna(last):
        return 0
    return int(((last - first) / pd.Timedelta(minutes=30)) + 1)


def pct(part: float, whole: float) -> float:
    if whole == 0 or pd.isna(whole):
        return np.nan
    return part / whole * 100.0


def summarise_group(g: pd.DataFrame, deadband_mw: float) -> dict[str, object]:
    g = g.sort_values("startTime")
    n = len(g)
    first = g["startTime"].min()
    last = g["startTime"].max()
    expected = expected_half_hours(first, last)
    states = g["direction_state"]
    switches = direction_switch_count(states)
    days = max((last - first) / pd.Timedelta(days=1), HH_HOURS / 24.0)

    import_mask = states == "import"
    export_mask = states == "export"
    zero_mask = states == "near_zero"
    abs_mw = g["signed_mw"].abs()
    capacity_mw = g["capacity_mw"].iloc[0] if "capacity_mw" in g.columns else np.nan

    row = {
        "interconnectorId": g["interconnectorId"].iloc[0],
        "interconnectorName": g["interconnectorName"].iloc[0],
        "interconnectorBiddingZone": g["interconnectorBiddingZone"].iloc[0],
        "capacity_mw": capacity_mw,
        "first_timestamp": first,
        "last_timestamp": last,
        "observations": n,
        "expected_half_hours_between_first_last": expected,
        "missing_half_hours_between_first_last": max(expected - n, 0),
        "coverage_pct_between_first_last": pct(n, expected),
        "duration_hours": n * HH_HOURS,
        "import_share_pct": import_mask.mean() * 100.0,
        "export_share_pct": export_mask.mean() * 100.0,
        "near_zero_share_pct": zero_mask.mean() * 100.0,
        "dominant_direction": "import"
        if import_mask.mean() > export_mask.mean()
        else "export"
        if export_mask.mean() > import_mask.mean()
        else "balanced",
        "mean_signed_mw": g["signed_mw"].mean(),
        "median_signed_mw": g["signed_mw"].median(),
        "p05_signed_mw": g["signed_mw"].quantile(0.05),
        "p25_signed_mw": g["signed_mw"].quantile(0.25),
        "p75_signed_mw": g["signed_mw"].quantile(0.75),
        "p95_signed_mw": g["signed_mw"].quantile(0.95),
        "mean_import_mw_when_importing": g.loc[import_mask, "import_mw"].mean(),
        "mean_export_mw_when_exporting": g.loc[export_mask, "export_mw"].mean(),
        "max_import_mw": g["import_mw"].max(),
        "max_export_mw": g["export_mw"].max(),
        "observed_abs_peak_mw": abs_mw.max(),
        "observed_abs_p95_mw": abs_mw.quantile(0.95),
        "mean_signed_pct_capacity": g["signed_pct_capacity"].mean() if "signed_pct_capacity" in g.columns else np.nan,
        "median_signed_pct_capacity": g["signed_pct_capacity"].median() if "signed_pct_capacity" in g.columns else np.nan,
        "p05_signed_pct_capacity": g["signed_pct_capacity"].quantile(0.05) if "signed_pct_capacity" in g.columns else np.nan,
        "p95_signed_pct_capacity": g["signed_pct_capacity"].quantile(0.95) if "signed_pct_capacity" in g.columns else np.nan,
        "mean_import_pct_capacity_when_importing": g.loc[import_mask, "import_pct_capacity"].mean()
        if "import_pct_capacity" in g.columns
        else np.nan,
        "mean_export_pct_capacity_when_exporting": g.loc[export_mask, "export_pct_capacity"].mean()
        if "export_pct_capacity" in g.columns
        else np.nan,
        "observed_abs_peak_pct_capacity": g["abs_pct_capacity"].max() if "abs_pct_capacity" in g.columns else np.nan,
        "observed_abs_p95_pct_capacity": g["abs_pct_capacity"].quantile(0.95) if "abs_pct_capacity" in g.columns else np.nan,
        "import_gwh": g["import_gwh"].sum(),
        "export_gwh": g["export_gwh"].sum(),
        "net_gwh": g["net_gwh"].sum(),
        "abs_flow_gwh": (abs_mw * GWH_PER_MW_HALF_HOUR).sum(),
        "direction_switches_ignoring_near_zero": switches,
        "direction_switches_per_30d": switches / days * 30.0,
        "share_abs_ge_500mw_pct": (abs_mw >= 500).mean() * 100.0,
        "share_abs_ge_1000mw_pct": (abs_mw >= 1000).mean() * 100.0,
        "share_abs_ge_1500mw_pct": (abs_mw >= 1500).mean() * 100.0,
        "share_import_ge_1000mw_pct": (g["import_mw"] >= 1000).mean() * 100.0,
        "share_export_ge_1000mw_pct": (g["export_mw"] >= 1000).mean() * 100.0,
        "longest_near_zero_run_hours": longest_true_run_hours(zero_mask.reset_index(drop=True)),
        "deadband_mw": deadband_mw,
    }
    return row


def summarise_by_interconnector(df: pd.DataFrame, deadband_mw: float) -> pd.DataFrame:
    rows = [summarise_group(group, deadband_mw) for _, group in df.groupby("interconnectorId", sort=True)]
    return pd.DataFrame(rows).sort_values("interconnectorId")


def summarise_periods(df: pd.DataFrame, group_cols: list[str], deadband_mw: float) -> pd.DataFrame:
    rows = []
    for keys, group in df.groupby(group_cols, sort=True):
        summary = summarise_group(group, deadband_mw)
        if not isinstance(keys, tuple):
            keys = (keys,)
        for col, value in zip(group_cols, keys):
            summary[col] = value
        rows.append(summary)
    out = pd.DataFrame(rows)
    return out[group_cols + [col for col in out.columns if col not in group_cols]]


def add_month_names(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "month" in out.columns:
        out["month_name"] = out["month"].astype(int).map(lambda month: calendar.month_abbr[month])
    return out


def build_fleet_half_hourly(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, metadata_cols: list[str]) -> pd.DataFrame:
    full_index = pd.date_range(start=start, end=end, freq="30min", tz="UTC")
    wide = df.pivot_table(index="startTime", columns="interconnectorId", values="signed_mw", aggfunc="first")
    wide = wide.reindex(full_index)
    total = pd.DataFrame(
        {
            "startTime": wide.index,
            "signed_mw": wide.fillna(0).sum(axis=1),
            "available_interconnector_count": wide.notna().sum(axis=1),
            "missing_interconnector_count": wide.shape[1] - wide.notna().sum(axis=1),
        }
    )
    total["raw_generation_mw"] = total["signed_mw"]
    total["import_mw"] = total["signed_mw"].clip(lower=0)
    total["export_mw"] = (-total["signed_mw"]).clip(lower=0)
    total["settlementPeriod"] = (
        total["startTime"].dt.hour * 2 + (total["startTime"].dt.minute // 30) + 1
    ).astype("Int64")
    total["interconnectorId"] = "TOTAL_GB_INTERCONNECTORS"
    total["interconnectorName"] = "GB interconnector fleet total"
    total["interconnectorBiddingZone"] = "Fleet"
    for col in metadata_cols:
        if col not in total.columns:
            total[col] = pd.NA
    return total


def daily_stats(df: pd.DataFrame) -> pd.DataFrame:
    grouped = df.groupby(["interconnectorId", "interconnectorName", "date"], sort=True)
    out = grouped.agg(
        observations=("signed_mw", "size"),
        mean_signed_mw=("signed_mw", "mean"),
        mean_signed_pct_capacity=("signed_pct_capacity", "mean"),
        median_signed_mw=("signed_mw", "median"),
        p10_signed_mw=("signed_mw", lambda s: s.quantile(0.10)),
        p90_signed_mw=("signed_mw", lambda s: s.quantile(0.90)),
        p10_signed_pct_capacity=("signed_pct_capacity", lambda s: s.quantile(0.10)),
        p90_signed_pct_capacity=("signed_pct_capacity", lambda s: s.quantile(0.90)),
        import_share_pct=("direction_state", lambda s: (s == "import").mean() * 100.0),
        export_share_pct=("direction_state", lambda s: (s == "export").mean() * 100.0),
        near_zero_share_pct=("direction_state", lambda s: (s == "near_zero").mean() * 100.0),
        import_gwh=("import_gwh", "sum"),
        export_gwh=("export_gwh", "sum"),
        net_gwh=("net_gwh", "sum"),
    )
    return out.reset_index()


def add_rolling_windows(daily: pd.DataFrame, windows: list[int]) -> pd.DataFrame:
    parts = []
    for _, group in daily.groupby("interconnectorId", sort=True):
        group = group.sort_values("date").copy()
        for window in windows:
            min_periods = max(3, window // 3)
            obs = group["observations"].rolling(window, min_periods=min_periods).sum()
            import_obs = (group["observations"] * group["import_share_pct"] / 100.0).rolling(
                window, min_periods=min_periods
            ).sum()
            export_obs = (group["observations"] * group["export_share_pct"] / 100.0).rolling(
                window, min_periods=min_periods
            ).sum()
            group[f"rolling_{window}d_mean_signed_mw"] = group["mean_signed_mw"].rolling(
                window, min_periods=min_periods
            ).mean()
            group[f"rolling_{window}d_mean_signed_pct_capacity"] = group["mean_signed_pct_capacity"].rolling(
                window, min_periods=min_periods
            ).mean()
            group[f"rolling_{window}d_import_share_pct"] = import_obs / obs * 100.0
            group[f"rolling_{window}d_export_share_pct"] = export_obs / obs * 100.0
            group[f"rolling_{window}d_import_gwh"] = group["import_gwh"].rolling(window, min_periods=min_periods).sum()
            group[f"rolling_{window}d_export_gwh"] = group["export_gwh"].rolling(window, min_periods=min_periods).sum()
            group[f"rolling_{window}d_net_gwh"] = group["net_gwh"].rolling(window, min_periods=min_periods).sum()
        parts.append(group)
    return pd.concat(parts, ignore_index=True)


def seasonal_weekly_envelope(daily: pd.DataFrame) -> pd.DataFrame:
    temp = daily.copy()
    temp["week"] = temp["date"].dt.isocalendar().week.astype(int)
    grouped = temp.groupby(["interconnectorId", "interconnectorName", "week"], sort=True)
    out = grouped.agg(
        samples=("mean_signed_mw", "size"),
        mean_signed_mw=("mean_signed_mw", "mean"),
        p10_signed_mw=("mean_signed_mw", lambda s: s.quantile(0.10)),
        p25_signed_mw=("mean_signed_mw", lambda s: s.quantile(0.25)),
        median_signed_mw=("mean_signed_mw", "median"),
        p75_signed_mw=("mean_signed_mw", lambda s: s.quantile(0.75)),
        p90_signed_mw=("mean_signed_mw", lambda s: s.quantile(0.90)),
        mean_signed_pct_capacity=("mean_signed_pct_capacity", "mean"),
        p10_signed_pct_capacity=("mean_signed_pct_capacity", lambda s: s.quantile(0.10)),
        p25_signed_pct_capacity=("mean_signed_pct_capacity", lambda s: s.quantile(0.25)),
        median_signed_pct_capacity=("mean_signed_pct_capacity", "median"),
        p75_signed_pct_capacity=("mean_signed_pct_capacity", lambda s: s.quantile(0.75)),
        p90_signed_pct_capacity=("mean_signed_pct_capacity", lambda s: s.quantile(0.90)),
        mean_import_share_pct=("import_share_pct", "mean"),
        mean_export_share_pct=("export_share_pct", "mean"),
    )
    return out.reset_index()


def diurnal_profile(df: pd.DataFrame) -> pd.DataFrame:
    grouped = df.groupby(["interconnectorId", "interconnectorName", "season", "settlementPeriod", "hour_utc"], sort=True)
    out = grouped.agg(
        observations=("signed_mw", "size"),
        mean_signed_mw=("signed_mw", "mean"),
        mean_signed_pct_capacity=("signed_pct_capacity", "mean"),
        p10_signed_mw=("signed_mw", lambda s: s.quantile(0.10)),
        median_signed_mw=("signed_mw", "median"),
        p90_signed_mw=("signed_mw", lambda s: s.quantile(0.90)),
        p10_signed_pct_capacity=("signed_pct_capacity", lambda s: s.quantile(0.10)),
        median_signed_pct_capacity=("signed_pct_capacity", "median"),
        p90_signed_pct_capacity=("signed_pct_capacity", lambda s: s.quantile(0.90)),
        import_share_pct=("direction_state", lambda s: (s == "import").mean() * 100.0),
        export_share_pct=("direction_state", lambda s: (s == "export").mean() * 100.0),
    )
    return out.reset_index()


def level_bucket_summary(df: pd.DataFrame) -> pd.DataFrame:
    grouped = df.groupby(["interconnectorId", "interconnectorName", "flow_band_mw"], observed=False, sort=True)
    out = grouped.agg(observations=("signed_mw", "size")).reset_index()
    totals = out.groupby("interconnectorId")["observations"].transform("sum")
    out["duration_hours"] = out["observations"] * HH_HOURS
    out["duration_share_pct"] = out["observations"] / totals * 100.0
    return out


def pct_capacity_bucket_summary(df: pd.DataFrame) -> pd.DataFrame:
    grouped = df.groupby(["interconnectorId", "interconnectorName", "flow_band_pct_capacity"], observed=False, sort=True)
    out = grouped.agg(observations=("signed_pct_capacity", "size")).reset_index()
    totals = out.groupby("interconnectorId")["observations"].transform("sum")
    out["duration_hours"] = out["observations"] * HH_HOURS
    out["duration_share_pct"] = out["observations"] / totals * 100.0
    return out


def interconnector_wide_flow(df: pd.DataFrame) -> pd.DataFrame:
    return df.pivot_table(index="startTime", columns="interconnectorId", values="signed_mw", aggfunc="first").sort_index()


def flow_correlation_outputs(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    wide = interconnector_wide_flow(df)
    matrix = wide.corr(min_periods=48)
    matrix_out = matrix.reset_index().rename(columns={"interconnectorId": "interconnectorId"})

    rows = []
    for left, right in combinations(matrix.columns, 2):
        common = wide[[left, right]].dropna()
        rows.append(
            {
                "interconnectorId_a": left,
                "interconnectorId_b": right,
                "common_half_hours": len(common),
                "pearson_signed_mw_corr": common[left].corr(common[right]) if len(common) >= 48 else np.nan,
                "mean_a_signed_mw": common[left].mean() if len(common) else np.nan,
                "mean_b_signed_mw": common[right].mean() if len(common) else np.nan,
            }
        )
    return matrix_out, pd.DataFrame(rows)


def direction_alignment_outputs(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    states = df.pivot_table(index="startTime", columns="interconnectorId", values="direction_state", aggfunc="first").sort_index()
    ids = list(states.columns)

    pair_rows = []
    for left, right in combinations(ids, 2):
        common = states[[left, right]].dropna()
        n = len(common)
        if n == 0:
            continue
        left_state = common[left]
        right_state = common[right]
        both_import = (left_state.eq("import") & right_state.eq("import")).sum()
        both_export = (left_state.eq("export") & right_state.eq("export")).sum()
        opposite = (
            (left_state.eq("import") & right_state.eq("export"))
            | (left_state.eq("export") & right_state.eq("import"))
        ).sum()
        near_zero_involved = (left_state.eq("near_zero") | right_state.eq("near_zero")).sum()
        pair_rows.append(
            {
                "interconnectorId_a": left,
                "interconnectorId_b": right,
                "common_half_hours": n,
                "same_direction_share_pct": (both_import + both_export) / n * 100.0,
                "opposite_direction_share_pct": opposite / n * 100.0,
                "near_zero_involved_share_pct": near_zero_involved / n * 100.0,
                "both_import_share_pct": both_import / n * 100.0,
                "both_export_share_pct": both_export / n * 100.0,
                "a_import_b_export_share_pct": (left_state.eq("import") & right_state.eq("export")).mean() * 100.0,
                "a_export_b_import_share_pct": (left_state.eq("export") & right_state.eq("import")).mean() * 100.0,
            }
        )

    conditional_rows = []
    for focal in ids:
        for other in ids:
            if focal == other:
                continue
            common = states[[focal, other]].dropna()
            for focal_state in ["import", "export"]:
                subset = common[common[focal] == focal_state]
                n = len(subset)
                conditional_rows.append(
                    {
                        "focal_interconnectorId": focal,
                        "other_interconnectorId": other,
                        "focal_state": focal_state,
                        "observations": n,
                        "other_import_share_pct": (subset[other].eq("import").mean() * 100.0) if n else np.nan,
                        "other_export_share_pct": (subset[other].eq("export").mean() * 100.0) if n else np.nan,
                        "other_near_zero_share_pct": (subset[other].eq("near_zero").mean() * 100.0) if n else np.nan,
                    }
                )

    return pd.DataFrame(pair_rows), pd.DataFrame(conditional_rows)


def write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def format_num(value: float, decimals: int = 0) -> str:
    if pd.isna(value):
        return "n/a"
    return f"{value:,.{decimals}f}"


def format_pct(value: float, decimals: int = 1) -> str:
    if pd.isna(value):
        return "n/a"
    return f"{value:.{decimals}f}%"


def build_story(
    output_dir: Path,
    summary: pd.DataFrame,
    fleet_summary: pd.Series,
    monthly: pd.DataFrame,
    season_overall: pd.DataFrame,
    month_of_year: pd.DataFrame,
    flow_corr_pairwise: pd.DataFrame,
    direction_pairwise: pd.DataFrame,
    analysis_start: pd.Timestamp,
    analysis_end: pd.Timestamp,
    positive_direction: str,
    deadband_mw: float,
) -> None:
    top_import = summary.sort_values("net_gwh", ascending=False).head(3)
    top_export = summary.sort_values("net_gwh", ascending=True).head(3)
    most_switching = summary.sort_values("direction_switches_per_30d", ascending=False).head(3)
    zero_heavy = summary.sort_values("near_zero_share_pct", ascending=False).head(3)
    positive_corr = flow_corr_pairwise.sort_values("pearson_signed_mw_corr", ascending=False).head(3)
    negative_corr = flow_corr_pairwise.sort_values("pearson_signed_mw_corr", ascending=True).head(3)
    same_direction = direction_pairwise.sort_values("same_direction_share_pct", ascending=False).head(3)
    opposite_direction = direction_pairwise.sort_values("opposite_direction_share_pct", ascending=False).head(3)

    latest_month = monthly["calendar_month"].max()
    latest_month_rows = monthly[monthly["calendar_month"] == latest_month].sort_values("mean_signed_mw", ascending=False)
    season_order = ["Winter", "Spring", "Summer", "Autumn"]
    fleet_season = season_overall[season_overall["interconnectorId"] == "TOTAL_GB_INTERCONNECTORS"].copy()
    fleet_season["season"] = pd.Categorical(fleet_season["season"], categories=season_order, ordered=True)
    fleet_season = fleet_season.sort_values("season")
    fleet_months = month_of_year[month_of_year["interconnectorId"] == "TOTAL_GB_INTERCONNECTORS"].copy()
    fleet_months = fleet_months.sort_values("month")
    strongest_import_month = fleet_months.sort_values("mean_signed_mw", ascending=False).head(1)
    weakest_import_month = fleet_months.sort_values("mean_signed_mw", ascending=True).head(1)
    seasonal_range = (
        month_of_year[month_of_year["interconnectorId"] != "TOTAL_GB_INTERCONNECTORS"]
        .groupby(["interconnectorId", "interconnectorName"], as_index=False)
        .agg(
            monthly_mean_min_mw=("mean_signed_mw", "min"),
            monthly_mean_max_mw=("mean_signed_mw", "max"),
            monthly_mean_min_pct_capacity=("mean_signed_pct_capacity", "min"),
            monthly_mean_max_pct_capacity=("mean_signed_pct_capacity", "max"),
        )
    )
    seasonal_range["monthly_mean_range_mw"] = seasonal_range["monthly_mean_max_mw"] - seasonal_range["monthly_mean_min_mw"]
    seasonal_range["monthly_mean_range_pct_capacity"] = (
        seasonal_range["monthly_mean_max_pct_capacity"] - seasonal_range["monthly_mean_min_pct_capacity"]
    )
    most_seasonal = seasonal_range.sort_values("monthly_mean_range_pct_capacity", ascending=False).head(3)

    lines = [
        "# GB Interconnector BM Operating History",
        "",
        f"Analysis window: {analysis_start.strftime('%Y-%m-%d %H:%M UTC')} to {analysis_end.strftime('%Y-%m-%d %H:%M UTC')}.",
        "",
        "Sign convention used in this pack:",
        f"- Positive raw `generation` is treated as GB {positive_direction}.",
        f"- Direction shares use a +/-{deadband_mw:g} MW deadband around zero.",
        "- Positive `signed_mw` in the output tables means GB import; negative means GB export.",
        "- `% capacity` metrics use `capacity_reference.csv`; by default this is the observed absolute peak MW in the analysis window unless a supplied capacity file is provided.",
        "",
        "## Headline Story",
        "",
        (
            f"Across the fleet, the BM interconnector position was importing for "
            f"{format_pct(fleet_summary['import_share_pct'])} of observed half-hours, exporting for "
            f"{format_pct(fleet_summary['export_share_pct'])}, and near zero for "
            f"{format_pct(fleet_summary['near_zero_share_pct'])}. The mean net position was "
            f"{format_num(fleet_summary['mean_signed_mw'])} MW, giving net energy of "
            f"{format_num(fleet_summary['net_gwh'])} GWh over the analysis window."
        ),
        "",
        "The clearest slide story is not just whether each link imported or exported, but how stable that operating mode was:",
        "- Direction duty cycle: share of time importing, exporting, and near zero.",
        "- Level distribution: time spent in MW bands, separately for import and export.",
        "- Rolling regime: 30-day and 90-day rolling net MW and direction shares.",
        "- Seasonality: monthly heatmap plus weekly seasonal envelope for expected import/export range.",
        "- Operational intensity: direction switching, sustained high-flow shares, and long near-zero runs as an outage/low-use proxy.",
        "",
        "## Seasonal and Monthly Shape",
        "",
        "Fleet seasonal averages:",
    ]

    for _, row in fleet_season.iterrows():
        lines.append(
            f"- {row['season']}: mean {format_num(row['mean_signed_mw'])} MW, "
            f"{format_num(row['mean_signed_pct_capacity'], 1)}% of fleet capacity, "
            f"import share {format_pct(row['import_share_pct'])}, export share {format_pct(row['export_share_pct'])}."
        )

    if not strongest_import_month.empty and not weakest_import_month.empty:
        strong = strongest_import_month.iloc[0]
        weak = weakest_import_month.iloc[0]
        lines.extend(
            [
                "",
                (
                    f"The strongest fleet import month-of-year is {strong['month_name']} "
                    f"at {format_num(strong['mean_signed_mw'])} MW "
                    f"({format_num(strong['mean_signed_pct_capacity'], 1)}% capacity) on average. "
                    f"The weakest or most export-leaning month-of-year is {weak['month_name']} at "
                    f"{format_num(weak['mean_signed_mw'])} MW ({format_num(weak['mean_signed_pct_capacity'], 1)}% capacity)."
                ),
                "",
                "Links with the largest month-of-year swing in mean signed % capacity:",
            ]
        )
        for _, row in most_seasonal.iterrows():
            lines.append(
                f"- {row['interconnectorName']} ({row['interconnectorId']}): "
                f"{format_num(row['monthly_mean_range_pct_capacity'], 1)} percentage-point range "
                f"({format_num(row['monthly_mean_range_mw'])} MW) between its lowest and highest month-of-year averages."
            )

    lines.extend(
        [
            "",
        "## Links Driving Net Imports",
        "",
        ]
    )

    for _, row in top_import.iterrows():
        lines.append(
            f"- {row['interconnectorName']} ({row['interconnectorId']}): net {format_num(row['net_gwh'])} GWh, "
            f"importing {format_pct(row['import_share_pct'])} of half-hours; mean import level when importing "
            f"{format_num(row['mean_import_mw_when_importing'])} MW."
        )

    lines.extend(["", "## Links Driving Net Exports", ""])
    for _, row in top_export.iterrows():
        lines.append(
            f"- {row['interconnectorName']} ({row['interconnectorId']}): net {format_num(row['net_gwh'])} GWh, "
            f"exporting {format_pct(row['export_share_pct'])} of half-hours; mean export level when exporting "
            f"{format_num(row['mean_export_mw_when_exporting'])} MW."
        )

    lines.extend(["", "## Most Directionally Dynamic Links", ""])
    for _, row in most_switching.iterrows():
        lines.append(
            f"- {row['interconnectorName']} ({row['interconnectorId']}): "
            f"{format_num(row['direction_switches_per_30d'], 1)} import/export switches per 30 days, "
            f"with {format_pct(row['near_zero_share_pct'])} near-zero operation."
        )

    lines.extend(["", "## Interconnector Coordination", ""])
    lines.append("Strongest positive signed-MW co-movement:")
    for _, row in positive_corr.iterrows():
        lines.append(
            f"- {row['interconnectorId_a']} and {row['interconnectorId_b']}: "
            f"Pearson correlation {format_num(row['pearson_signed_mw_corr'], 2)} over "
            f"{format_num(row['common_half_hours'])} common half-hours."
        )
    lines.append("")
    lines.append("Strongest offsetting signed-MW relationships:")
    for _, row in negative_corr.iterrows():
        lines.append(
            f"- {row['interconnectorId_a']} and {row['interconnectorId_b']}: "
            f"Pearson correlation {format_num(row['pearson_signed_mw_corr'], 2)} over "
            f"{format_num(row['common_half_hours'])} common half-hours."
        )
    lines.append("")
    lines.append("Highest same-direction operating shares:")
    for _, row in same_direction.iterrows():
        lines.append(
            f"- {row['interconnectorId_a']} and {row['interconnectorId_b']}: "
            f"same direction {format_pct(row['same_direction_share_pct'])}, opposite direction "
            f"{format_pct(row['opposite_direction_share_pct'])}."
        )
    lines.append("")
    lines.append("Highest opposite-direction operating shares:")
    for _, row in opposite_direction.iterrows():
        lines.append(
            f"- {row['interconnectorId_a']} and {row['interconnectorId_b']}: "
            f"opposite direction {format_pct(row['opposite_direction_share_pct'])}, same direction "
            f"{format_pct(row['same_direction_share_pct'])}."
        )

    lines.extend(["", "## Highest Near-Zero Shares", ""])
    for _, row in zero_heavy.iterrows():
        lines.append(
            f"- {row['interconnectorName']} ({row['interconnectorId']}): near zero for "
            f"{format_pct(row['near_zero_share_pct'])}; longest near-zero run "
            f"{format_num(row['longest_near_zero_run_hours'], 1)} hours."
        )

    lines.extend(["", f"## Latest Month Snapshot ({latest_month})", ""])
    for _, row in latest_month_rows.iterrows():
        lines.append(
            f"- {row['interconnectorName']} ({row['interconnectorId']}): mean {format_num(row['mean_signed_mw'])} MW, "
            f"import share {format_pct(row['import_share_pct'])}, export share {format_pct(row['export_share_pct'])}."
        )

    lines.extend(
        [
            "",
            "## Suggested Exhibit Pack",
            "",
            "1. `figures/direction_share_by_interconnector.*` - simple answer to how often each link imported, exported, or sat near zero.",
            "2. `figures/net_energy_by_interconnector.*` - which links have been net importers/exporters over the period.",
            "3. `figures/monthly_mean_signed_mw_heatmap.*` - regime changes and seasonality by link.",
            "4. `figures/fleet_rolling_net_mw.*` - whether the total GB interconnector BM position was tightening or relaxing.",
            "5. `figures/fleet_weekly_seasonal_envelope.*` - expected seasonal range across the five-year history.",
            "6. `figures/fleet_diurnal_by_season.*` - whether operation changes materially within day and season.",
            "7. `figures/flow_correlation_heatmap.*` and `figures/direction_alignment_heatmap.*` - whether links tend to move together or offset each other.",
            "8. `figures/fleet_month_of_year_profile.*`, `figures/month_of_year_mean_heatmap.*`, and `figures/season_direction_share_by_interconnector.*` - seasonal/month shape across the fleet and each link.",
            "9. `figures/month_of_year_pct_capacity_heatmap.*`, `figures/season_pct_capacity_heatmap.*`, and `figures/pct_capacity_bands_by_interconnector.*` - capacity-normalised comparative views.",
            "10. `figures/interconnectors/*_operating_profile.*` - one profile per interconnector for appendix or drill-down.",
            "",
            "## Tables Written",
            "",
            "- `interconnector_summary.csv`",
            "- `fleet_summary.csv`",
            "- `capacity_reference.csv`",
            "- `monthly_summary.csv`",
            "- `seasonal_summary.csv`",
            "- `season_overall_summary.csv`",
            "- `month_of_year_summary.csv`",
            "- `season_month_summary.csv`",
            "- `daily_timeseries.csv`",
            "- `rolling_windows.csv`",
            "- `weekly_seasonal_envelope.csv`",
            "- `diurnal_profile_by_season.csv`",
            "- `level_bucket_summary.csv`",
            "- `pct_capacity_bucket_summary.csv`",
            "- `interconnector_flow_correlation_matrix.csv`",
            "- `interconnector_flow_correlation_pairwise.csv`",
            "- `interconnector_direction_alignment_pairwise.csv`",
            "- `interconnector_conditional_direction_shares.csv`",
            "- `fleet_half_hourly_timeseries.csv`",
            "",
            "Caveat: this pack uses the observed BM half-hourly `generation` values and an explicit sign assumption. If the source uses the opposite sign convention for interconnectors, rerun with `--positive-direction export` and the import/export labels will flip.",
            "",
        ]
    )

    (output_dir / "story.md").write_text("\n".join(lines), encoding="utf-8")


def pair_context(pairwise: pd.DataFrame, interconnector_id: str, value_col: str, ascending: bool) -> pd.Series | None:
    rows = pairwise[
        (pairwise["interconnectorId_a"] == interconnector_id) | (pairwise["interconnectorId_b"] == interconnector_id)
    ].copy()
    if rows.empty:
        return None
    return rows.sort_values(value_col, ascending=ascending).iloc[0]


def other_interconnector(row: pd.Series, interconnector_id: str) -> str:
    return row["interconnectorId_b"] if row["interconnectorId_a"] == interconnector_id else row["interconnectorId_a"]


def build_presentation_outline(
    output_dir: Path,
    summary: pd.DataFrame,
    fleet_summary: pd.Series,
    season_overall: pd.DataFrame,
    month_of_year: pd.DataFrame,
    flow_corr_pairwise: pd.DataFrame,
    direction_pairwise: pd.DataFrame,
    analysis_start: pd.Timestamp,
    analysis_end: pd.Timestamp,
    positive_direction: str,
) -> None:
    """Write a slide-by-slide outline for a presentation deck."""

    lines = [
        "# Presentation Outline - GB Interconnector BM Operating History",
        "",
        f"Analysis window: {analysis_start.strftime('%Y-%m-%d %H:%M UTC')} to {analysis_end.strftime('%Y-%m-%d %H:%M UTC')}.",
        f"Sign convention: positive raw `generation` is treated as GB {positive_direction}; positive signed values mean GB import.",
        "Capacity convention: `% capacity` uses `capacity_reference.csv`, defaulting to observed absolute peak MW unless a supplied capacity file is present.",
        "",
        "## Deck Structure",
        "",
        "Use the first section to establish the full system story, then move into one drill-down slide per link. The drill-down slides should use the same layout so the audience can compare behaviour quickly.",
        "",
        "## Section 1 - Full Fleet Picture",
        "",
        "### Slide 1 - Title and Client Question",
        "",
        "Purpose: frame the question as operating behaviour, not just volume.",
        "",
        "Suggested title: `GB interconnectors in the BM: five-year operating history`.",
        "",
        "Key message: we are showing how often each link imported/exported, at what level, how seasonal the operation is, and whether links tend to move together or offset each other.",
        "",
        "Visuals: none, or a simple map/list of the interconnector set.",
        "",
        "### Slide 2 - Data, Sign Convention, and Capacity Normalisation",
        "",
        "Purpose: make the basis of the analysis explicit before showing results.",
        "",
        "Key points:",
        f"- Analysis covers {analysis_start.strftime('%Y-%m-%d')} to {analysis_end.strftime('%Y-%m-%d')}.",
        "- Half-hourly BM values are used from `HH_data`.",
        "- Import is shown as positive, export as negative.",
        "- Direction shares use the configured near-zero deadband.",
        "- Comparative utilisation charts use `% capacity`, based on `capacity_reference.csv`.",
        "",
        "Visuals: `capacity_reference.csv` as a compact table or footnote.",
        "",
        "### Slide 3 - Fleet Headline",
        "",
        "Purpose: answer the headline question for the GB interconnector fleet.",
        "",
        "Key points:",
        f"- Fleet imported for {format_pct(fleet_summary['import_share_pct'])} of half-hours and exported for {format_pct(fleet_summary['export_share_pct'])}.",
        f"- Mean fleet position was {format_num(fleet_summary['mean_signed_mw'])} MW, or {format_num(fleet_summary['mean_signed_pct_capacity'], 1)}% of observed fleet capacity.",
        f"- Net energy was {format_num(fleet_summary['net_gwh'])} GWh over the window.",
        "",
        "Visuals: `figures/direction_share_by_interconnector.png` and/or `figures/net_energy_by_interconnector.png`.",
        "",
        "### Slide 4 - Which Links Drove Net Imports and Exports?",
        "",
        "Purpose: show contribution by interconnector and separate structural importers from exporters.",
        "",
        "Key points:",
    ]

    top_import = summary.sort_values("net_gwh", ascending=False).head(3)
    top_export = summary.sort_values("net_gwh", ascending=True).head(3)
    for _, row in top_import.iterrows():
        lines.append(
            f"- Import driver: {row['interconnectorId']} net {format_num(row['net_gwh'])} GWh, importing {format_pct(row['import_share_pct'])} of half-hours."
        )
    for _, row in top_export.iterrows():
        lines.append(
            f"- Export driver: {row['interconnectorId']} net {format_num(row['net_gwh'])} GWh, exporting {format_pct(row['export_share_pct'])} of half-hours."
        )

    lines.extend(
        [
            "",
            "Visuals: `figures/net_energy_by_interconnector.png`.",
            "",
            "### Slide 5 - Direction Duty Cycle",
            "",
            "Purpose: show how often each link imports, exports, or sits near zero.",
            "",
            "Key points:",
            "- This is the cleanest answer to `how often are they exporting/importing?`.",
            "- Highlight links with sustained export behaviour and links with a material near-zero share.",
            "",
            "Visuals: `figures/direction_share_by_interconnector.png`.",
            "",
            "### Slide 6 - Capacity-Normalised Utilisation",
            "",
            "Purpose: avoid misleading comparisons caused by different link sizes.",
            "",
            "Key points:",
            "- Use `% capacity` to compare behaviour across different-size assets.",
            "- Show which links spend most time at high import or high export utilisation.",
            "- Keep MW charts for system impact; use `% capacity` charts for like-for-like operating behaviour.",
            "",
            "Visuals: `figures/pct_capacity_bands_by_interconnector.png` and `figures/month_of_year_pct_capacity_heatmap.png`.",
            "",
            "### Slide 7 - Collapsed Seasonal Shape",
            "",
            "Purpose: show how the typical year behaves after collapsing the five-year history.",
            "",
            "Key points:",
        ]
    )

    fleet_seasons = season_overall[season_overall["interconnectorId"] == "TOTAL_GB_INTERCONNECTORS"].copy()
    fleet_seasons["season"] = pd.Categorical(
        fleet_seasons["season"], categories=["Winter", "Spring", "Summer", "Autumn"], ordered=True
    )
    for _, row in fleet_seasons.sort_values("season").iterrows():
        lines.append(
            f"- {row['season']}: mean {format_num(row['mean_signed_mw'])} MW, {format_num(row['mean_signed_pct_capacity'], 1)}% capacity, import share {format_pct(row['import_share_pct'])}."
        )

    strongest_month = month_of_year[month_of_year["interconnectorId"] == "TOTAL_GB_INTERCONNECTORS"].sort_values(
        "mean_signed_pct_capacity", ascending=False
    ).iloc[0]
    weakest_month = month_of_year[month_of_year["interconnectorId"] == "TOTAL_GB_INTERCONNECTORS"].sort_values(
        "mean_signed_pct_capacity", ascending=True
    ).iloc[0]
    lines.extend(
        [
            f"- Strongest collapsed month: {strongest_month['month_name']} at {format_num(strongest_month['mean_signed_pct_capacity'], 1)}% capacity.",
            f"- Weakest collapsed month: {weakest_month['month_name']} at {format_num(weakest_month['mean_signed_pct_capacity'], 1)}% capacity.",
            "",
            "Visuals: `figures/season_pct_capacity_heatmap.png`, `figures/fleet_month_of_year_pct_capacity_profile.png`, and `figures/month_of_year_pct_capacity_heatmap.png`.",
            "",
            "### Slide 8 - Calendar-Time Regime Changes",
            "",
            "Purpose: show the time history, not only the collapsed seasonal average.",
            "",
            "Key points:",
            "- Use this to show structural changes from new links, outages, or changing market conditions.",
            "- Present MW for system effect and `% capacity` for comparable asset behaviour.",
            "",
            "Visuals: `figures/monthly_mean_signed_mw_heatmap.png` and `figures/calendar_month_pct_capacity_heatmap.png`.",
            "",
            "### Slide 9 - Rolling Regimes and Recent Direction",
            "",
            "Purpose: show persistence and changes in import/export regimes over time.",
            "",
            "Key points:",
            "- Use 30-day and 90-day rolling fleet position to avoid over-reading half-hour volatility.",
            "- Identify periods where the fleet moved toward weaker imports or stronger imports.",
            "",
            "Visuals: `figures/fleet_rolling_net_mw.png`.",
            "",
            "### Slide 10 - Within-Day Shape by Season",
            "",
            "Purpose: show whether the fleet has a systematic diurnal operating pattern.",
            "",
            "Key points:",
            "- Compare seasonal diurnal curves rather than individual noisy half-hours.",
            "- Use this slide to discuss whether interconnectors are responding to daily price/spread patterns.",
            "",
            "Visuals: `figures/fleet_diurnal_by_season.png`.",
            "",
            "### Slide 11 - Coordination Across Interconnectors",
            "",
            "Purpose: show whether links tend to move together or offset each other.",
            "",
            "Key points:",
        ]
    )

    positive_corr = flow_corr_pairwise.sort_values("pearson_signed_mw_corr", ascending=False).head(3)
    negative_corr = flow_corr_pairwise.sort_values("pearson_signed_mw_corr", ascending=True).head(3)
    for _, row in positive_corr.iterrows():
        lines.append(
            f"- Strong co-movement: {row['interconnectorId_a']} with {row['interconnectorId_b']} at r={format_num(row['pearson_signed_mw_corr'], 2)}."
        )
    for _, row in negative_corr.iterrows():
        lines.append(
            f"- Strong offset: {row['interconnectorId_a']} with {row['interconnectorId_b']} at r={format_num(row['pearson_signed_mw_corr'], 2)}."
        )

    lines.extend(
        [
            "",
            "Visuals: `figures/flow_correlation_heatmap.png`, `figures/direction_alignment_heatmap.png`, and `figures/direction_opposition_heatmap.png`.",
            "",
            "### Slide 12 - Fleet Takeaways",
            "",
            "Purpose: close the fleet section before moving to individual link pages.",
            "",
            "Key points:",
            "- GB interconnector BM operation is net import-oriented at fleet level, but not uniformly across links.",
            "- Ireland/Northern Ireland links are structurally export-leaning in this dataset; France/Norway/Belgium/Netherlands links are import-leaning.",
            "- Capacity-normalised charts are essential for fair link-to-link comparisons.",
            "- Seasonal behaviour is visible after collapsing the history, with spring strongest and autumn weakest at fleet level.",
            "",
            "Visuals: small multiples or a four-bullet summary.",
            "",
            "## Section 2 - One Slide Per Interconnector",
            "",
            "Recommended slide layout for every link:",
            "- Left: `figures/interconnectors/<ID>_operating_profile.png`, or use modular PNGs from `figures/interconnectors/subfigures/`.",
            "- Right top: headline stats, direction shares, mean MW, mean % capacity, net GWh.",
            "- Right middle: seasonal/month context.",
            "- Right bottom: coordination context and interpretation.",
            "",
        ]
    )

    slide_number = 13
    ordered = summary.sort_values("net_gwh", ascending=False)
    for _, row in ordered.iterrows():
        interconnector_id = row["interconnectorId"]
        months = month_of_year[month_of_year["interconnectorId"] == interconnector_id]
        seasons = season_overall[season_overall["interconnectorId"] == interconnector_id]
        strong_month = months.sort_values("mean_signed_pct_capacity", ascending=False).iloc[0]
        weak_month = months.sort_values("mean_signed_pct_capacity", ascending=True).iloc[0]
        strong_season = seasons.sort_values("mean_signed_pct_capacity", ascending=False).iloc[0]
        weak_season = seasons.sort_values("mean_signed_pct_capacity", ascending=True).iloc[0]
        co_move = pair_context(flow_corr_pairwise, interconnector_id, "pearson_signed_mw_corr", ascending=False)
        offset = pair_context(flow_corr_pairwise, interconnector_id, "pearson_signed_mw_corr", ascending=True)
        same_direction = pair_context(direction_pairwise, interconnector_id, "same_direction_share_pct", ascending=False)
        opposite_direction = pair_context(direction_pairwise, interconnector_id, "opposite_direction_share_pct", ascending=False)

        role = "net importer" if row["net_gwh"] > 0 else "net exporter" if row["net_gwh"] < 0 else "balanced link"
        lines.extend(
            [
                f"### Slide {slide_number} - {row['interconnectorName']} ({interconnector_id})",
                "",
                f"Purpose: explain this link as a {role} and show how its behaviour differs from the fleet.",
                "",
                "Headline stats:",
                f"- Direction: {row['dominant_direction']}; import {format_pct(row['import_share_pct'])}, export {format_pct(row['export_share_pct'])}, near zero {format_pct(row['near_zero_share_pct'])}.",
                f"- Mean position: {format_num(row['mean_signed_mw'])} MW, {format_num(row['mean_signed_pct_capacity'], 1)}% capacity.",
                f"- Net energy: {format_num(row['net_gwh'])} GWh.",
                f"- Typical level when importing/exporting: {format_num(row['mean_import_mw_when_importing'])} MW import, {format_num(row['mean_export_mw_when_exporting'])} MW export.",
                f"- Direction switching: {format_num(row['direction_switches_per_30d'], 1)} switches per 30 days.",
                "",
                "Seasonal and monthly context:",
                f"- Strongest month-of-year: {strong_month['month_name']} at {format_num(strong_month['mean_signed_pct_capacity'], 1)}% capacity ({format_num(strong_month['mean_signed_mw'])} MW).",
                f"- Weakest or most export-leaning month-of-year: {weak_month['month_name']} at {format_num(weak_month['mean_signed_pct_capacity'], 1)}% capacity ({format_num(weak_month['mean_signed_mw'])} MW).",
                f"- Strongest season: {strong_season['season']} at {format_num(strong_season['mean_signed_pct_capacity'], 1)}% capacity.",
                f"- Weakest or most export-leaning season: {weak_season['season']} at {format_num(weak_season['mean_signed_pct_capacity'], 1)}% capacity.",
                "",
                "Coordination context:",
            ]
        )
        if co_move is not None:
            lines.append(
                f"- Highest positive MW co-movement with {other_interconnector(co_move, interconnector_id)}: r={format_num(co_move['pearson_signed_mw_corr'], 2)}."
            )
        if offset is not None:
            lines.append(
                f"- Strongest MW offset with {other_interconnector(offset, interconnector_id)}: r={format_num(offset['pearson_signed_mw_corr'], 2)}."
            )
        if same_direction is not None:
            lines.append(
                f"- Highest same-direction share with {other_interconnector(same_direction, interconnector_id)}: {format_pct(same_direction['same_direction_share_pct'])}."
            )
        if opposite_direction is not None:
            lines.append(
                f"- Highest opposite-direction share with {other_interconnector(opposite_direction, interconnector_id)}: {format_pct(opposite_direction['opposite_direction_share_pct'])}."
            )
        lines.extend(
            [
                "",
                "Suggested visuals:",
                f"- `figures/interconnectors/{safe_filename(interconnector_id)}_operating_profile.png`.",
                f"- Modular options: `figures/interconnectors/subfigures/{safe_filename(interconnector_id)}_daily_rolling.png`, `{safe_filename(interconnector_id)}_month_of_year_pct_capacity.png`, `{safe_filename(interconnector_id)}_seasonal_direction_share.png`, and `{safe_filename(interconnector_id)}_level_bands_pct_capacity.png`.",
                "- Refer back to `figures/month_of_year_pct_capacity_heatmap.png` or `figures/season_pct_capacity_heatmap.png` for cross-link comparison.",
                "",
                "Presenter note: keep the interpretation focused on direction, utilisation, seasonality, and whether the link moves with or against the wider interconnector fleet.",
                "",
            ]
        )
        slide_number += 1

    lines.extend(
        [
            "## Optional Appendix",
            "",
            f"### Slide {slide_number} - Method and Caveats",
            "",
            "Key points:",
            "- Sign convention should be verified against the data source; rerun with `--positive-direction export` if the source convention is reversed.",
            "- `% capacity` uses observed peak by default; replace with supplied nameplate capacities via `interconnector_capacities.csv` when available.",
            "- Newer links have shorter operating histories, so collapsed seasonal comparisons should be interpreted with that context.",
            "- Near-zero shares can reflect outages, ramping, or commercial non-use; do not treat them as outage-only without operational validation.",
            "",
        ]
    )

    (output_dir / "presentation_outline.md").write_text("\n".join(lines), encoding="utf-8")


def require_matplotlib():
    try:
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
        from matplotlib.colors import TwoSlopeNorm
    except ImportError as exc:
        raise RuntimeError(
            "matplotlib is required for charts. Install it or rerun with --no-charts."
        ) from exc
    return plt, mdates, TwoSlopeNorm


def plot_direction_share(summary: pd.DataFrame, figure_dir: Path) -> None:
    plt, _, _ = require_matplotlib()
    data = summary.sort_values("import_share_pct")
    y = np.arange(len(data))
    fig, ax = plt.subplots(figsize=(10, 5.8))
    ax.barh(y, data["export_share_pct"], color="#c43c39", label="Export")
    ax.barh(y, data["near_zero_share_pct"], left=data["export_share_pct"], color="#b8b8b8", label="Near zero")
    ax.barh(
        y,
        data["import_share_pct"],
        left=data["export_share_pct"] + data["near_zero_share_pct"],
        color="#2f6db2",
        label="Import",
    )
    ax.set_yticks(y)
    ax.set_yticklabels(data["interconnectorId"])
    ax.set_xlim(0, 100)
    ax.set_xlabel("Share of half-hours (%)")
    ax.set_title("Direction Share by Interconnector")
    ax.legend(ncols=3, loc="lower center", bbox_to_anchor=(0.5, -0.22))
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(figure_dir / "direction_share_by_interconnector.png", dpi=160)
    plt.close(fig)


def plot_net_energy(summary: pd.DataFrame, figure_dir: Path) -> None:
    plt, _, _ = require_matplotlib()
    data = summary.sort_values("net_gwh")
    colors = np.where(data["net_gwh"] >= 0, "#2f6db2", "#c43c39")
    fig, ax = plt.subplots(figsize=(10, 5.8))
    ax.barh(data["interconnectorId"], data["net_gwh"], color=colors)
    ax.axvline(0, color="#333333", linewidth=1)
    ax.set_xlabel("Net energy (GWh, import positive)")
    ax.set_title("Net Import/Export Energy by Interconnector")
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(figure_dir / "net_energy_by_interconnector.png", dpi=160)
    plt.close(fig)


def plot_monthly_heatmap(monthly: pd.DataFrame, figure_dir: Path) -> None:
    plt, _, TwoSlopeNorm = require_matplotlib()
    pivot = monthly.pivot_table(index="interconnectorId", columns="calendar_month", values="mean_signed_mw", aggfunc="mean")
    pivot = pivot.reindex(sorted(pivot.index))
    max_abs = float(np.nanmax(np.abs(pivot.to_numpy()))) if pivot.size else 1.0
    norm = TwoSlopeNorm(vmin=-max_abs, vcenter=0, vmax=max_abs)

    fig, ax = plt.subplots(figsize=(14, 5.5))
    image = ax.imshow(pivot.to_numpy(), aspect="auto", cmap="RdBu", norm=norm)
    ax.set_yticks(np.arange(len(pivot.index)))
    ax.set_yticklabels(pivot.index)
    month_labels = list(pivot.columns)
    tick_positions = np.arange(0, len(month_labels), max(1, len(month_labels) // 12))
    ax.set_xticks(tick_positions)
    ax.set_xticklabels([month_labels[i] for i in tick_positions], rotation=45, ha="right")
    ax.set_title("Monthly Mean BM Position (MW, Import Positive)")
    cbar = fig.colorbar(image, ax=ax)
    cbar.set_label("Mean signed MW")
    fig.tight_layout()
    fig.savefig(figure_dir / "monthly_mean_signed_mw_heatmap.png", dpi=160)
    plt.close(fig)


def plot_fleet_rolling(rolling: pd.DataFrame, figure_dir: Path) -> None:
    plt, mdates, _ = require_matplotlib()
    data = rolling[rolling["interconnectorId"] == "TOTAL_GB_INTERCONNECTORS"].sort_values("date")
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(data["date"], data["rolling_30d_mean_signed_mw"], color="#2f6db2", label="30-day mean")
    ax.plot(data["date"], data["rolling_90d_mean_signed_mw"], color="#222222", linewidth=2, label="90-day mean")
    ax.axhline(0, color="#777777", linewidth=1)
    ax.set_ylabel("MW (import positive)")
    ax.set_title("Fleet Rolling Net BM Position")
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.grid(alpha=0.25)
    ax.legend()
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(figure_dir / "fleet_rolling_net_mw.png", dpi=160)
    plt.close(fig)


def plot_weekly_envelope(envelope: pd.DataFrame, figure_dir: Path) -> None:
    plt, _, _ = require_matplotlib()
    data = envelope[envelope["interconnectorId"] == "TOTAL_GB_INTERCONNECTORS"].sort_values("week")
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.fill_between(data["week"], data["p10_signed_mw"], data["p90_signed_mw"], color="#9bbce3", alpha=0.35, label="p10-p90")
    ax.fill_between(data["week"], data["p25_signed_mw"], data["p75_signed_mw"], color="#4b83c3", alpha=0.35, label="p25-p75")
    ax.plot(data["week"], data["median_signed_mw"], color="#111111", label="Median")
    ax.axhline(0, color="#777777", linewidth=1)
    ax.set_xlabel("ISO week of year")
    ax.set_ylabel("Daily mean MW (import positive)")
    ax.set_title("Fleet Weekly Seasonal Envelope")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(figure_dir / "fleet_weekly_seasonal_envelope.png", dpi=160)
    plt.close(fig)


def plot_fleet_diurnal(diurnal: pd.DataFrame, figure_dir: Path) -> None:
    plt, _, _ = require_matplotlib()
    data = diurnal[diurnal["interconnectorId"] == "TOTAL_GB_INTERCONNECTORS"].sort_values(["season", "hour_utc"])
    colors = {"Winter": "#1b4f8f", "Spring": "#3f8c4a", "Summer": "#e0a526", "Autumn": "#9a4b2f"}
    fig, ax = plt.subplots(figsize=(11, 5))
    for season, group in data.groupby("season", sort=False):
        ax.plot(group["hour_utc"], group["mean_signed_mw"], label=season, color=colors.get(season))
    ax.axhline(0, color="#777777", linewidth=1)
    ax.set_xlabel("UTC hour")
    ax.set_ylabel("Mean MW (import positive)")
    ax.set_title("Fleet Diurnal BM Position by Season")
    ax.set_xlim(0, 23.5)
    ax.grid(alpha=0.25)
    ax.legend(ncols=4)
    fig.tight_layout()
    fig.savefig(figure_dir / "fleet_diurnal_by_season.png", dpi=160)
    plt.close(fig)


def plot_level_buckets(bucket_summary: pd.DataFrame, figure_dir: Path) -> None:
    plt, _, _ = require_matplotlib()
    data = bucket_summary[bucket_summary["interconnectorId"] != "TOTAL_GB_INTERCONNECTORS"].copy()
    pivot = data.pivot_table(
        index="interconnectorId", columns="flow_band_mw", values="duration_share_pct", aggfunc="sum", fill_value=0
    )
    pivot = pivot.reindex(columns=LEVEL_LABELS).sort_index()
    colors = [
        "#7f1d1d",
        "#b72f2f",
        "#d45a55",
        "#e98b85",
        "#f2b8b4",
        "#c7c7c7",
        "#bcd3ef",
        "#86afd9",
        "#5489c7",
        "#2f6db2",
        "#174a88",
    ]
    fig, ax = plt.subplots(figsize=(12, 6))
    bottom = np.zeros(len(pivot))
    for label, color in zip(LEVEL_LABELS, colors):
        values = pivot[label].to_numpy()
        ax.barh(pivot.index, values, left=bottom, label=label, color=color)
        bottom += values
    ax.set_xlim(0, 100)
    ax.set_xlabel("Share of half-hours (%)")
    ax.set_title("Flow Level Bands by Interconnector")
    ax.grid(axis="x", alpha=0.25)
    ax.legend(loc="center left", bbox_to_anchor=(1.0, 0.5), fontsize=8)
    fig.tight_layout()
    fig.savefig(figure_dir / "level_bands_by_interconnector.png", dpi=160)
    plt.close(fig)


def require_plotly():
    try:
        import plotly.graph_objects as go
    except ImportError as exc:
        raise RuntimeError(
            "No chart backend is available. Install matplotlib, install plotly, or rerun with --no-charts."
        ) from exc
    return go


def plotly_layout(fig, title: str) -> None:
    fig.update_layout(
        title=title,
        template="plotly_white",
        font={"family": "Arial, sans-serif", "size": 12},
        legend={"orientation": "h", "yanchor": "bottom", "y": -0.25, "xanchor": "center", "x": 0.5},
        margin={"l": 80, "r": 40, "t": 70, "b": 80},
    )


def plotly_direction_share(summary: pd.DataFrame, figure_dir: Path) -> None:
    go = require_plotly()
    data = summary.sort_values("import_share_pct")
    fig = go.Figure()
    fig.add_bar(
        y=data["interconnectorId"],
        x=data["export_share_pct"],
        name="Export",
        orientation="h",
        marker_color="#c43c39",
    )
    fig.add_bar(
        y=data["interconnectorId"],
        x=data["near_zero_share_pct"],
        name="Near zero",
        orientation="h",
        marker_color="#b8b8b8",
    )
    fig.add_bar(
        y=data["interconnectorId"],
        x=data["import_share_pct"],
        name="Import",
        orientation="h",
        marker_color="#2f6db2",
    )
    fig.update_layout(barmode="stack", xaxis_title="Share of half-hours (%)", yaxis_title="")
    plotly_layout(fig, "Direction Share by Interconnector")
    fig.write_html(figure_dir / "direction_share_by_interconnector.html", include_plotlyjs="directory")


def plotly_net_energy(summary: pd.DataFrame, figure_dir: Path) -> None:
    go = require_plotly()
    data = summary.sort_values("net_gwh")
    colors = np.where(data["net_gwh"] >= 0, "#2f6db2", "#c43c39")
    fig = go.Figure(
        go.Bar(
            y=data["interconnectorId"],
            x=data["net_gwh"],
            orientation="h",
            marker_color=colors,
            name="Net GWh",
        )
    )
    fig.add_vline(x=0, line_color="#333333", line_width=1)
    fig.update_layout(xaxis_title="Net energy (GWh, import positive)", yaxis_title="", showlegend=False)
    plotly_layout(fig, "Net Import/Export Energy by Interconnector")
    fig.write_html(figure_dir / "net_energy_by_interconnector.html", include_plotlyjs="directory")


def plotly_monthly_heatmap(monthly: pd.DataFrame, figure_dir: Path) -> None:
    go = require_plotly()
    pivot = monthly.pivot_table(index="interconnectorId", columns="calendar_month", values="mean_signed_mw", aggfunc="mean")
    pivot = pivot.reindex(sorted(pivot.index))
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
    fig.update_layout(xaxis_title="", yaxis_title="")
    plotly_layout(fig, "Monthly Mean BM Position (MW, Import Positive)")
    fig.write_html(figure_dir / "monthly_mean_signed_mw_heatmap.html", include_plotlyjs="directory")


def plotly_fleet_rolling(rolling: pd.DataFrame, figure_dir: Path) -> None:
    go = require_plotly()
    data = rolling[rolling["interconnectorId"] == "TOTAL_GB_INTERCONNECTORS"].sort_values("date")
    fig = go.Figure()
    fig.add_scatter(x=data["date"], y=data["rolling_30d_mean_signed_mw"], mode="lines", name="30-day mean", line_color="#2f6db2")
    fig.add_scatter(x=data["date"], y=data["rolling_90d_mean_signed_mw"], mode="lines", name="90-day mean", line_color="#222222")
    fig.add_hline(y=0, line_color="#777777", line_width=1)
    fig.update_layout(xaxis_title="", yaxis_title="MW (import positive)")
    plotly_layout(fig, "Fleet Rolling Net BM Position")
    fig.write_html(figure_dir / "fleet_rolling_net_mw.html", include_plotlyjs="directory")


def plotly_weekly_envelope(envelope: pd.DataFrame, figure_dir: Path) -> None:
    go = require_plotly()
    data = envelope[envelope["interconnectorId"] == "TOTAL_GB_INTERCONNECTORS"].sort_values("week")
    fig = go.Figure()
    fig.add_scatter(
        x=data["week"],
        y=data["p90_signed_mw"],
        mode="lines",
        line={"width": 0},
        showlegend=False,
        hoverinfo="skip",
    )
    fig.add_scatter(
        x=data["week"],
        y=data["p10_signed_mw"],
        mode="lines",
        fill="tonexty",
        fillcolor="rgba(75, 131, 195, 0.22)",
        line={"width": 0},
        name="p10-p90",
    )
    fig.add_scatter(x=data["week"], y=data["p75_signed_mw"], mode="lines", line={"width": 0}, showlegend=False, hoverinfo="skip")
    fig.add_scatter(
        x=data["week"],
        y=data["p25_signed_mw"],
        mode="lines",
        fill="tonexty",
        fillcolor="rgba(75, 131, 195, 0.36)",
        line={"width": 0},
        name="p25-p75",
    )
    fig.add_scatter(x=data["week"], y=data["median_signed_mw"], mode="lines", name="Median", line_color="#111111")
    fig.add_hline(y=0, line_color="#777777", line_width=1)
    fig.update_layout(xaxis_title="ISO week of year", yaxis_title="Daily mean MW (import positive)")
    plotly_layout(fig, "Fleet Weekly Seasonal Envelope")
    fig.write_html(figure_dir / "fleet_weekly_seasonal_envelope.html", include_plotlyjs="directory")


def plotly_fleet_diurnal(diurnal: pd.DataFrame, figure_dir: Path) -> None:
    go = require_plotly()
    data = diurnal[diurnal["interconnectorId"] == "TOTAL_GB_INTERCONNECTORS"].sort_values(["season", "hour_utc"])
    colors = {"Winter": "#1b4f8f", "Spring": "#3f8c4a", "Summer": "#e0a526", "Autumn": "#9a4b2f"}
    fig = go.Figure()
    for season, group in data.groupby("season", sort=False):
        fig.add_scatter(
            x=group["hour_utc"],
            y=group["mean_signed_mw"],
            mode="lines",
            name=season,
            line_color=colors.get(season),
        )
    fig.add_hline(y=0, line_color="#777777", line_width=1)
    fig.update_layout(xaxis_title="UTC hour", yaxis_title="Mean MW (import positive)")
    plotly_layout(fig, "Fleet Diurnal BM Position by Season")
    fig.write_html(figure_dir / "fleet_diurnal_by_season.html", include_plotlyjs="directory")


def plotly_level_buckets(bucket_summary: pd.DataFrame, figure_dir: Path) -> None:
    go = require_plotly()
    data = bucket_summary[bucket_summary["interconnectorId"] != "TOTAL_GB_INTERCONNECTORS"].copy()
    pivot = data.pivot_table(
        index="interconnectorId", columns="flow_band_mw", values="duration_share_pct", aggfunc="sum", fill_value=0
    )
    pivot = pivot.reindex(columns=LEVEL_LABELS).sort_index()
    colors = [
        "#7f1d1d",
        "#b72f2f",
        "#d45a55",
        "#e98b85",
        "#f2b8b4",
        "#c7c7c7",
        "#bcd3ef",
        "#86afd9",
        "#5489c7",
        "#2f6db2",
        "#174a88",
    ]
    fig = go.Figure()
    for label, color in zip(LEVEL_LABELS, colors):
        fig.add_bar(y=pivot.index, x=pivot[label], name=label, orientation="h", marker_color=color)
    fig.update_layout(barmode="stack", xaxis_title="Share of half-hours (%)", yaxis_title="")
    plotly_layout(fig, "Flow Level Bands by Interconnector")
    fig.write_html(figure_dir / "level_bands_by_interconnector.html", include_plotlyjs="directory")


def plotly_pct_capacity_buckets(bucket_summary: pd.DataFrame, figure_dir: Path) -> None:
    go = require_plotly()
    data = bucket_summary[bucket_summary["interconnectorId"] != "TOTAL_GB_INTERCONNECTORS"].copy()
    pivot = data.pivot_table(
        index="interconnectorId",
        columns="flow_band_pct_capacity",
        values="duration_share_pct",
        aggfunc="sum",
        fill_value=0,
    )
    pivot = pivot.reindex(columns=PCT_CAPACITY_LABELS).sort_index()
    colors = [
        "#8a1c1c",
        "#c43c39",
        "#e27d78",
        "#f0b2ad",
        "#c7c7c7",
        "#bcd3ef",
        "#86afd9",
        "#4b83c3",
        "#174a88",
    ]
    fig = go.Figure()
    for label, color in zip(PCT_CAPACITY_LABELS, colors):
        fig.add_bar(y=pivot.index, x=pivot[label], name=label, orientation="h", marker_color=color)
    fig.update_layout(barmode="stack", xaxis_title="Share of half-hours (%)", yaxis_title="")
    plotly_layout(fig, "Flow Utilisation Bands by Interconnector (% Capacity)")
    fig.write_html(figure_dir / "pct_capacity_bands_by_interconnector.html", include_plotlyjs="directory")


def plotly_fleet_month_of_year(month_of_year: pd.DataFrame, figure_dir: Path) -> None:
    go = require_plotly()
    from plotly.subplots import make_subplots

    data = month_of_year[month_of_year["interconnectorId"] == "TOTAL_GB_INTERCONNECTORS"].sort_values("month")
    colors = np.where(data["mean_signed_mw"] >= 0, "#2f6db2", "#c43c39")
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_bar(
        x=data["month_name"],
        y=data["mean_signed_mw"],
        name="Mean signed MW",
        marker_color=colors,
        secondary_y=False,
    )
    fig.add_scatter(
        x=data["month_name"],
        y=data["import_share_pct"],
        name="Import share",
        mode="lines+markers",
        line_color="#174a88",
        secondary_y=True,
    )
    fig.add_scatter(
        x=data["month_name"],
        y=data["export_share_pct"],
        name="Export share",
        mode="lines+markers",
        line_color="#9b2724",
        secondary_y=True,
    )
    fig.add_hline(y=0, line_color="#777777", line_width=1, secondary_y=False)
    fig.update_yaxes(title_text="Mean MW (import positive)", secondary_y=False)
    fig.update_yaxes(title_text="Direction share (%)", range=[0, 100], secondary_y=True)
    fig.update_layout(xaxis_title="")
    plotly_layout(fig, "Fleet Month-of-Year BM Profile")
    fig.write_html(figure_dir / "fleet_month_of_year_profile.html", include_plotlyjs="directory")


def plotly_fleet_month_of_year_pct_capacity(month_of_year: pd.DataFrame, figure_dir: Path) -> None:
    go = require_plotly()
    data = month_of_year[month_of_year["interconnectorId"] == "TOTAL_GB_INTERCONNECTORS"].sort_values("month")
    colors = np.where(data["mean_signed_pct_capacity"] >= 0, "#2f6db2", "#c43c39")
    fig = go.Figure(
        go.Bar(
            x=data["month_name"],
            y=data["mean_signed_pct_capacity"],
            name="Mean signed % capacity",
            marker_color=colors,
        )
    )
    fig.add_hline(y=0, line_color="#777777", line_width=1)
    fig.update_layout(xaxis_title="", yaxis_title="Mean position (% capacity, import positive)")
    plotly_layout(fig, "Fleet Month-of-Year BM Profile (% Capacity)")
    fig.write_html(figure_dir / "fleet_month_of_year_pct_capacity_profile.html", include_plotlyjs="directory")


def plotly_month_of_year_heatmap(month_of_year: pd.DataFrame, figure_dir: Path) -> None:
    go = require_plotly()
    data = month_of_year.copy()
    pivot = data.pivot_table(index="interconnectorId", columns="month", values="mean_signed_mw", aggfunc="mean")
    order = ["TOTAL_GB_INTERCONNECTORS"] + sorted(
        interconnector_id for interconnector_id in pivot.index if interconnector_id != "TOTAL_GB_INTERCONNECTORS"
    )
    pivot = pivot.reindex(index=order, columns=list(range(1, 13)))
    labels = [calendar.month_abbr[month] for month in pivot.columns]
    max_abs = float(np.nanmax(np.abs(pivot.to_numpy()))) if pivot.size else 1.0
    fig = go.Figure(
        go.Heatmap(
            z=pivot.to_numpy(),
            x=labels,
            y=list(pivot.index),
            colorscale="RdBu",
            zmin=-max_abs,
            zmax=max_abs,
            colorbar={"title": "Mean signed MW"},
        )
    )
    fig.update_layout(xaxis_title="", yaxis_title="")
    plotly_layout(fig, "Month-of-Year Mean BM Position by Interconnector")
    fig.write_html(figure_dir / "month_of_year_mean_heatmap.html", include_plotlyjs="directory")


def ordered_interconnector_ids(df: pd.DataFrame) -> list[str]:
    return ["TOTAL_GB_INTERCONNECTORS"] + sorted(
        interconnector_id
        for interconnector_id in df["interconnectorId"].unique()
        if interconnector_id != "TOTAL_GB_INTERCONNECTORS"
    )


def plotly_month_of_year_pct_capacity_heatmap(month_of_year: pd.DataFrame, figure_dir: Path) -> None:
    go = require_plotly()
    pivot = month_of_year.pivot_table(
        index="interconnectorId",
        columns="month",
        values="mean_signed_pct_capacity",
        aggfunc="mean",
    )
    pivot = pivot.reindex(index=ordered_interconnector_ids(month_of_year), columns=list(range(1, 13)))
    labels = [calendar.month_abbr[month] for month in pivot.columns]
    fig = go.Figure(
        go.Heatmap(
            z=pivot.to_numpy(),
            x=labels,
            y=list(pivot.index),
            colorscale="RdBu",
            zmin=-100,
            zmax=100,
            zmid=0,
            colorbar={"title": "% capacity"},
        )
    )
    fig.update_layout(xaxis_title="", yaxis_title="")
    plotly_layout(fig, "Collapsed Month-of-Year Mean Position (% Capacity, Import Positive)")
    fig.write_html(figure_dir / "month_of_year_pct_capacity_heatmap.html", include_plotlyjs="directory")


def plotly_calendar_month_pct_capacity_heatmap(monthly: pd.DataFrame, figure_dir: Path) -> None:
    go = require_plotly()
    pivot = monthly.pivot_table(
        index="interconnectorId",
        columns="calendar_month",
        values="mean_signed_pct_capacity",
        aggfunc="mean",
    )
    pivot = pivot.reindex(index=ordered_interconnector_ids(monthly))
    fig = go.Figure(
        go.Heatmap(
            z=pivot.to_numpy(),
            x=list(pivot.columns),
            y=list(pivot.index),
            colorscale="RdBu",
            zmin=-100,
            zmax=100,
            zmid=0,
            colorbar={"title": "% capacity"},
        )
    )
    fig.update_layout(xaxis_title="", yaxis_title="")
    plotly_layout(fig, "Calendar Month Mean Position (% Capacity, Import Positive)")
    fig.write_html(figure_dir / "calendar_month_pct_capacity_heatmap.html", include_plotlyjs="directory")


def plotly_season_pct_capacity_heatmap(season_overall: pd.DataFrame, figure_dir: Path) -> None:
    go = require_plotly()
    season_order = ["Winter", "Spring", "Summer", "Autumn"]
    pivot = season_overall.pivot_table(
        index="interconnectorId",
        columns="season",
        values="mean_signed_pct_capacity",
        aggfunc="mean",
    )
    pivot = pivot.reindex(index=ordered_interconnector_ids(season_overall), columns=season_order)
    fig = go.Figure(
        go.Heatmap(
            z=pivot.to_numpy(),
            x=season_order,
            y=list(pivot.index),
            colorscale="RdBu",
            zmin=-100,
            zmax=100,
            zmid=0,
            colorbar={"title": "% capacity"},
        )
    )
    fig.update_layout(xaxis_title="", yaxis_title="")
    plotly_layout(fig, "Collapsed Seasonal Mean Position (% Capacity, Import Positive)")
    fig.write_html(figure_dir / "season_pct_capacity_heatmap.html", include_plotlyjs="directory")


def plotly_season_direction_heatmap(season_overall: pd.DataFrame, figure_dir: Path) -> None:
    go = require_plotly()
    from plotly.subplots import make_subplots

    season_order = ["Winter", "Spring", "Summer", "Autumn"]
    data = season_overall.copy()
    order = ["TOTAL_GB_INTERCONNECTORS"] + sorted(
        interconnector_id
        for interconnector_id in data["interconnectorId"].unique()
        if interconnector_id != "TOTAL_GB_INTERCONNECTORS"
    )
    import_pivot = data.pivot_table(index="interconnectorId", columns="season", values="import_share_pct", aggfunc="mean")
    export_pivot = data.pivot_table(index="interconnectorId", columns="season", values="export_share_pct", aggfunc="mean")
    import_pivot = import_pivot.reindex(index=order, columns=season_order)
    export_pivot = export_pivot.reindex(index=order, columns=season_order)

    fig = make_subplots(
        rows=1,
        cols=2,
        subplot_titles=["Import share", "Export share"],
        horizontal_spacing=0.12,
    )
    fig.add_trace(
        go.Heatmap(
            z=import_pivot.to_numpy(),
            x=season_order,
            y=list(import_pivot.index),
            zmin=0,
            zmax=100,
            colorscale="Blues",
            colorbar={"title": "%", "x": 0.46},
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Heatmap(
            z=export_pivot.to_numpy(),
            x=season_order,
            y=list(export_pivot.index),
            zmin=0,
            zmax=100,
            colorscale="Reds",
            colorbar={"title": "%", "x": 1.0},
        ),
        row=1,
        col=2,
    )
    fig.update_layout(xaxis_title="", xaxis2_title="", yaxis_title="", yaxis2_title="")
    plotly_layout(fig, "Seasonal Direction Share by Interconnector")
    fig.write_html(figure_dir / "season_direction_share_by_interconnector.html", include_plotlyjs="directory")


def pairwise_matrix(pairwise: pd.DataFrame, value_col: str, diagonal_value: float) -> pd.DataFrame:
    ids = sorted(set(pairwise["interconnectorId_a"]).union(pairwise["interconnectorId_b"]))
    matrix = pd.DataFrame(np.nan, index=ids, columns=ids, dtype=float)
    for interconnector_id in ids:
        matrix.loc[interconnector_id, interconnector_id] = diagonal_value
    for _, row in pairwise.iterrows():
        left = row["interconnectorId_a"]
        right = row["interconnectorId_b"]
        matrix.loc[left, right] = row[value_col]
        matrix.loc[right, left] = row[value_col]
    return matrix


def plotly_matrix_heatmap(matrix: pd.DataFrame, figure_dir: Path, filename: str, title: str, zmin: float, zmax: float) -> None:
    go = require_plotly()
    fig = go.Figure(
        go.Heatmap(
            z=matrix.to_numpy(),
            x=list(matrix.columns),
            y=list(matrix.index),
            colorscale="RdBu",
            zmin=zmin,
            zmax=zmax,
            text=np.round(matrix.to_numpy(), 2),
            texttemplate="%{text}",
            colorbar={"title": "Value"},
        )
    )
    fig.update_layout(xaxis_title="", yaxis_title="")
    plotly_layout(fig, title)
    fig.write_html(figure_dir / filename, include_plotlyjs="directory")


def plotly_correlation_and_alignment(
    flow_corr_matrix: pd.DataFrame,
    direction_pairwise: pd.DataFrame,
    conditional_direction: pd.DataFrame,
    figure_dir: Path,
) -> None:
    ids = [col for col in flow_corr_matrix.columns if col != "interconnectorId"]
    corr_matrix = flow_corr_matrix.set_index("interconnectorId")[ids].astype(float)
    plotly_matrix_heatmap(
        corr_matrix,
        figure_dir,
        "flow_correlation_heatmap.html",
        "Signed MW Correlation Between Interconnectors",
        -1,
        1,
    )

    same_matrix = pairwise_matrix(direction_pairwise, "same_direction_share_pct", 100.0)
    plotly_matrix_heatmap(
        same_matrix,
        figure_dir,
        "direction_alignment_heatmap.html",
        "Same-Direction Operating Share (%)",
        0,
        100,
    )

    opposite_matrix = pairwise_matrix(direction_pairwise, "opposite_direction_share_pct", 0.0)
    plotly_matrix_heatmap(
        opposite_matrix,
        figure_dir,
        "direction_opposition_heatmap.html",
        "Opposite-Direction Operating Share (%)",
        0,
        100,
    )

    for focal_state, value_col, filename, title in [
        (
            "import",
            "other_import_share_pct",
            "conditional_import_alignment_heatmap.html",
            "When Focal Link Imports, Share of Time Other Link Also Imports (%)",
        ),
        (
            "export",
            "other_export_share_pct",
            "conditional_export_alignment_heatmap.html",
            "When Focal Link Exports, Share of Time Other Link Also Exports (%)",
        ),
    ]:
        subset = conditional_direction[conditional_direction["focal_state"] == focal_state]
        matrix = subset.pivot_table(
            index="focal_interconnectorId",
            columns="other_interconnectorId",
            values=value_col,
            aggfunc="first",
        )
        ids = sorted(set(matrix.index).union(matrix.columns))
        matrix = matrix.reindex(index=ids, columns=ids)
        for interconnector_id in ids:
            matrix.loc[interconnector_id, interconnector_id] = 100.0
        plotly_matrix_heatmap(matrix, figure_dir, filename, title, 0, 100)


def safe_filename(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)


def plotly_interconnector_profiles(
    summary: pd.DataFrame,
    monthly: pd.DataFrame,
    month_of_year: pd.DataFrame,
    season_overall: pd.DataFrame,
    rolling: pd.DataFrame,
    envelope: pd.DataFrame,
    bucket_summary: pd.DataFrame,
    figure_dir: Path,
) -> None:
    go = require_plotly()
    from plotly.subplots import make_subplots

    individual_dir = figure_dir / "interconnectors"
    individual_dir.mkdir(parents=True, exist_ok=True)

    for _, summary_row in summary.sort_values("interconnectorId").iterrows():
        interconnector_id = summary_row["interconnectorId"]
        name = summary_row["interconnectorName"]
        r = rolling[rolling["interconnectorId"] == interconnector_id].sort_values("date")
        m = monthly[monthly["interconnectorId"] == interconnector_id].sort_values("calendar_month")
        moy = month_of_year[month_of_year["interconnectorId"] == interconnector_id].sort_values("month")
        season = season_overall[season_overall["interconnectorId"] == interconnector_id].copy()
        season["season"] = pd.Categorical(season["season"], categories=["Winter", "Spring", "Summer", "Autumn"], ordered=True)
        season = season.sort_values("season")
        e = envelope[envelope["interconnectorId"] == interconnector_id].sort_values("week")
        b = bucket_summary[
            (bucket_summary["interconnectorId"] == interconnector_id) & (bucket_summary["observations"] > 0)
        ].copy()
        b["flow_band_mw"] = pd.Categorical(b["flow_band_mw"], categories=LEVEL_LABELS, ordered=True)
        b = b.sort_values("flow_band_mw")

        fig = make_subplots(
            rows=6,
            cols=1,
            vertical_spacing=0.075,
            row_heights=[0.28, 0.20, 0.18, 0.18, 0.18, 0.22],
            subplot_titles=[
                "Daily and rolling signed MW",
                "Monthly mean signed MW",
                "Month-of-year mean signed MW",
                "Seasonal direction share",
                "Weekly seasonal envelope",
                "Flow level duration share",
            ],
        )

        fig.add_scatter(
            x=r["date"],
            y=r["mean_signed_mw"],
            mode="lines",
            name="Daily mean",
            line={"color": "rgba(120,120,120,0.35)", "width": 1},
            row=1,
            col=1,
        )
        fig.add_scatter(
            x=r["date"],
            y=r["rolling_30d_mean_signed_mw"],
            mode="lines",
            name="30-day mean",
            line_color="#2f6db2",
            row=1,
            col=1,
        )
        fig.add_scatter(
            x=r["date"],
            y=r["rolling_90d_mean_signed_mw"],
            mode="lines",
            name="90-day mean",
            line_color="#222222",
            row=1,
            col=1,
        )

        monthly_colors = np.where(m["mean_signed_mw"] >= 0, "#2f6db2", "#c43c39")
        fig.add_bar(
            x=m["calendar_month"],
            y=m["mean_signed_mw"],
            name="Monthly mean",
            marker_color=monthly_colors,
            showlegend=False,
            row=2,
            col=1,
        )

        moy_colors = np.where(moy["mean_signed_mw"] >= 0, "#2f6db2", "#c43c39")
        fig.add_bar(
            x=moy["month_name"],
            y=moy["mean_signed_mw"],
            name="Month-of-year mean",
            marker_color=moy_colors,
            showlegend=False,
            row=3,
            col=1,
        )

        fig.add_bar(
            x=season["season"].astype(str),
            y=season["export_share_pct"],
            name="Export share",
            marker_color="#c43c39",
            row=4,
            col=1,
        )
        fig.add_bar(
            x=season["season"].astype(str),
            y=season["near_zero_share_pct"],
            name="Near zero share",
            marker_color="#b8b8b8",
            row=4,
            col=1,
        )
        fig.add_bar(
            x=season["season"].astype(str),
            y=season["import_share_pct"],
            name="Import share",
            marker_color="#2f6db2",
            row=4,
            col=1,
        )

        fig.add_scatter(x=e["week"], y=e["p90_signed_mw"], mode="lines", line={"width": 0}, showlegend=False, row=5, col=1)
        fig.add_scatter(
            x=e["week"],
            y=e["p10_signed_mw"],
            mode="lines",
            fill="tonexty",
            fillcolor="rgba(75, 131, 195, 0.22)",
            line={"width": 0},
            name="p10-p90",
            row=5,
            col=1,
        )
        fig.add_scatter(
            x=e["week"],
            y=e["median_signed_mw"],
            mode="lines",
            name="Seasonal median",
            line_color="#111111",
            row=5,
            col=1,
        )

        fig.add_bar(
            x=b["duration_share_pct"],
            y=b["flow_band_mw"].astype(str),
            orientation="h",
            name="Duration share",
            marker_color="#6f8fb9",
            showlegend=False,
            row=6,
            col=1,
        )

        fig.add_hline(y=0, line_color="#777777", line_width=1, row=1, col=1)
        fig.add_hline(y=0, line_color="#777777", line_width=1, row=2, col=1)
        fig.add_hline(y=0, line_color="#777777", line_width=1, row=3, col=1)
        fig.add_hline(y=0, line_color="#777777", line_width=1, row=5, col=1)
        fig.update_yaxes(title_text="MW", row=1, col=1)
        fig.update_yaxes(title_text="MW", row=2, col=1)
        fig.update_yaxes(title_text="MW", row=3, col=1)
        fig.update_yaxes(title_text="Share (%)", range=[0, 100], row=4, col=1)
        fig.update_yaxes(title_text="MW", row=5, col=1)
        fig.update_xaxes(title_text="ISO week", row=5, col=1)
        fig.update_xaxes(title_text="Share of half-hours (%)", row=6, col=1)
        fig.update_layout(
            title=f"{interconnector_id} Operating Profile - {name}",
            template="plotly_white",
            barmode="stack",
            height=1500,
            font={"family": "Arial, sans-serif", "size": 12},
            legend={"orientation": "h", "yanchor": "bottom", "y": -0.04, "xanchor": "center", "x": 0.5},
            margin={"l": 90, "r": 40, "t": 90, "b": 80},
        )
        fig.write_html(
            individual_dir / f"{safe_filename(interconnector_id)}_operating_profile.html",
            include_plotlyjs="directory",
        )


def plotly_interconnector_subfigures(
    summary: pd.DataFrame,
    monthly: pd.DataFrame,
    month_of_year: pd.DataFrame,
    season_overall: pd.DataFrame,
    rolling: pd.DataFrame,
    envelope: pd.DataFrame,
    bucket_summary: pd.DataFrame,
    pct_capacity_buckets: pd.DataFrame,
    figure_dir: Path,
) -> None:
    go = require_plotly()
    subfigure_dir = figure_dir / "interconnectors" / "subfigures"
    subfigure_dir.mkdir(parents=True, exist_ok=True)

    season_order = ["Winter", "Spring", "Summer", "Autumn"]
    for _, summary_row in summary.sort_values("interconnectorId").iterrows():
        interconnector_id = summary_row["interconnectorId"]
        name = summary_row["interconnectorName"]
        prefix = safe_filename(interconnector_id)

        r = rolling[rolling["interconnectorId"] == interconnector_id].sort_values("date")
        m = monthly[monthly["interconnectorId"] == interconnector_id].sort_values("calendar_month")
        moy = month_of_year[month_of_year["interconnectorId"] == interconnector_id].sort_values("month")
        season = season_overall[season_overall["interconnectorId"] == interconnector_id].copy()
        season["season"] = pd.Categorical(season["season"], categories=season_order, ordered=True)
        season = season.sort_values("season")
        e = envelope[envelope["interconnectorId"] == interconnector_id].sort_values("week")
        b = bucket_summary[
            (bucket_summary["interconnectorId"] == interconnector_id) & (bucket_summary["observations"] > 0)
        ].copy()
        b["flow_band_mw"] = pd.Categorical(b["flow_band_mw"], categories=LEVEL_LABELS, ordered=True)
        b = b.sort_values("flow_band_mw")
        pct_b = pct_capacity_buckets[
            (pct_capacity_buckets["interconnectorId"] == interconnector_id)
            & (pct_capacity_buckets["observations"] > 0)
        ].copy()
        pct_b["flow_band_pct_capacity"] = pd.Categorical(
            pct_b["flow_band_pct_capacity"], categories=PCT_CAPACITY_LABELS, ordered=True
        )
        pct_b = pct_b.sort_values("flow_band_pct_capacity")

        fig = go.Figure()
        fig.add_scatter(
            x=r["date"],
            y=r["mean_signed_mw"],
            mode="lines",
            name="Daily mean",
            line={"color": "rgba(120,120,120,0.35)", "width": 1},
        )
        fig.add_scatter(x=r["date"], y=r["rolling_30d_mean_signed_mw"], mode="lines", name="30-day mean", line_color="#2f6db2")
        fig.add_scatter(x=r["date"], y=r["rolling_90d_mean_signed_mw"], mode="lines", name="90-day mean", line_color="#222222")
        fig.add_hline(y=0, line_color="#777777", line_width=1)
        fig.update_layout(xaxis_title="", yaxis_title="MW (import positive)", height=520)
        plotly_layout(fig, f"{interconnector_id} Daily and Rolling BM Position - {name}")
        fig.write_html(subfigure_dir / f"{prefix}_daily_rolling.html", include_plotlyjs="directory")

        monthly_colors = np.where(m["mean_signed_mw"] >= 0, "#2f6db2", "#c43c39")
        fig = go.Figure(go.Bar(x=m["calendar_month"], y=m["mean_signed_mw"], marker_color=monthly_colors, name="Monthly mean"))
        fig.add_hline(y=0, line_color="#777777", line_width=1)
        fig.update_layout(xaxis_title="", yaxis_title="MW (import positive)", height=520, showlegend=False)
        plotly_layout(fig, f"{interconnector_id} Monthly Mean BM Position - {name}")
        fig.write_html(subfigure_dir / f"{prefix}_monthly_history.html", include_plotlyjs="directory")

        month_colors = np.where(moy["mean_signed_pct_capacity"] >= 0, "#2f6db2", "#c43c39")
        fig = go.Figure(
            go.Bar(
                x=moy["month_name"],
                y=moy["mean_signed_pct_capacity"],
                marker_color=month_colors,
                name="Month-of-year mean",
            )
        )
        fig.add_hline(y=0, line_color="#777777", line_width=1)
        fig.update_layout(xaxis_title="", yaxis_title="% capacity (import positive)", height=520, showlegend=False)
        plotly_layout(fig, f"{interconnector_id} Collapsed Month-of-Year Position (% Capacity) - {name}")
        fig.write_html(subfigure_dir / f"{prefix}_month_of_year_pct_capacity.html", include_plotlyjs="directory")

        fig = go.Figure()
        fig.add_bar(x=season["season"].astype(str), y=season["export_share_pct"], name="Export", marker_color="#c43c39")
        fig.add_bar(x=season["season"].astype(str), y=season["near_zero_share_pct"], name="Near zero", marker_color="#b8b8b8")
        fig.add_bar(x=season["season"].astype(str), y=season["import_share_pct"], name="Import", marker_color="#2f6db2")
        fig.update_layout(barmode="stack", xaxis_title="", yaxis_title="Share of half-hours (%)", yaxis_range=[0, 100], height=520)
        plotly_layout(fig, f"{interconnector_id} Seasonal Direction Share - {name}")
        fig.write_html(subfigure_dir / f"{prefix}_seasonal_direction_share.html", include_plotlyjs="directory")

        fig = go.Figure()
        fig.add_scatter(x=e["week"], y=e["p90_signed_mw"], mode="lines", line={"width": 0}, showlegend=False, hoverinfo="skip")
        fig.add_scatter(
            x=e["week"],
            y=e["p10_signed_mw"],
            mode="lines",
            fill="tonexty",
            fillcolor="rgba(75, 131, 195, 0.22)",
            line={"width": 0},
            name="p10-p90",
        )
        fig.add_scatter(x=e["week"], y=e["median_signed_mw"], mode="lines", name="Median", line_color="#111111")
        fig.add_hline(y=0, line_color="#777777", line_width=1)
        fig.update_layout(xaxis_title="ISO week", yaxis_title="Daily mean MW (import positive)", height=520)
        plotly_layout(fig, f"{interconnector_id} Weekly Seasonal Envelope - {name}")
        fig.write_html(subfigure_dir / f"{prefix}_weekly_seasonal_envelope.html", include_plotlyjs="directory")

        fig = go.Figure(
            go.Bar(
                x=b["duration_share_pct"],
                y=b["flow_band_mw"].astype(str),
                orientation="h",
                marker_color="#6f8fb9",
                name="MW band share",
            )
        )
        fig.update_layout(xaxis_title="Share of half-hours (%)", yaxis_title="", height=560, showlegend=False)
        plotly_layout(fig, f"{interconnector_id} Flow Level Duration Share - {name}")
        fig.write_html(subfigure_dir / f"{prefix}_level_bands_mw.html", include_plotlyjs="directory")

        fig = go.Figure(
            go.Bar(
                x=pct_b["duration_share_pct"],
                y=pct_b["flow_band_pct_capacity"].astype(str),
                orientation="h",
                marker_color="#6f8fb9",
                name="% capacity band share",
            )
        )
        fig.update_layout(xaxis_title="Share of half-hours (%)", yaxis_title="", height=560, showlegend=False)
        plotly_layout(fig, f"{interconnector_id} Utilisation Duration Share (% Capacity) - {name}")
        fig.write_html(subfigure_dir / f"{prefix}_level_bands_pct_capacity.html", include_plotlyjs="directory")


def generate_plotly_charts(
    output_dir: Path,
    summary: pd.DataFrame,
    monthly: pd.DataFrame,
    month_of_year: pd.DataFrame,
    season_overall: pd.DataFrame,
    rolling: pd.DataFrame,
    envelope: pd.DataFrame,
    diurnal: pd.DataFrame,
    bucket_summary: pd.DataFrame,
    pct_capacity_buckets: pd.DataFrame,
    flow_corr_matrix: pd.DataFrame,
    direction_pairwise: pd.DataFrame,
    conditional_direction: pd.DataFrame,
) -> None:
    figure_dir = output_dir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    plotly_direction_share(summary, figure_dir)
    plotly_net_energy(summary, figure_dir)
    plotly_monthly_heatmap(monthly, figure_dir)
    plotly_fleet_rolling(rolling, figure_dir)
    plotly_weekly_envelope(envelope, figure_dir)
    plotly_fleet_diurnal(diurnal, figure_dir)
    plotly_level_buckets(bucket_summary, figure_dir)
    plotly_pct_capacity_buckets(pct_capacity_buckets, figure_dir)
    plotly_fleet_month_of_year(month_of_year, figure_dir)
    plotly_fleet_month_of_year_pct_capacity(month_of_year, figure_dir)
    plotly_month_of_year_heatmap(month_of_year, figure_dir)
    plotly_month_of_year_pct_capacity_heatmap(month_of_year, figure_dir)
    plotly_calendar_month_pct_capacity_heatmap(monthly, figure_dir)
    plotly_season_pct_capacity_heatmap(season_overall, figure_dir)
    plotly_season_direction_heatmap(season_overall, figure_dir)
    plotly_correlation_and_alignment(flow_corr_matrix, direction_pairwise, conditional_direction, figure_dir)
    plotly_interconnector_profiles(
        summary,
        monthly,
        month_of_year,
        season_overall,
        rolling,
        envelope,
        bucket_summary,
        figure_dir,
    )
    plotly_interconnector_subfigures(
        summary,
        monthly,
        month_of_year,
        season_overall,
        rolling,
        envelope,
        bucket_summary,
        pct_capacity_buckets,
        figure_dir,
    )


def generate_charts(
    output_dir: Path,
    summary: pd.DataFrame,
    monthly: pd.DataFrame,
    month_of_year: pd.DataFrame,
    season_overall: pd.DataFrame,
    rolling: pd.DataFrame,
    envelope: pd.DataFrame,
    diurnal: pd.DataFrame,
    bucket_summary: pd.DataFrame,
    pct_capacity_buckets: pd.DataFrame,
    flow_corr_matrix: pd.DataFrame,
    direction_pairwise: pd.DataFrame,
    conditional_direction: pd.DataFrame,
) -> None:
    figure_dir = output_dir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    try:
        plot_direction_share(summary, figure_dir)
        plot_net_energy(summary, figure_dir)
        plot_monthly_heatmap(monthly, figure_dir)
        plot_fleet_rolling(rolling, figure_dir)
        plot_weekly_envelope(envelope, figure_dir)
        plot_fleet_diurnal(diurnal, figure_dir)
        plot_level_buckets(bucket_summary, figure_dir)
        try:
            plotly_pct_capacity_buckets(pct_capacity_buckets, figure_dir)
            plotly_fleet_month_of_year(month_of_year, figure_dir)
            plotly_fleet_month_of_year_pct_capacity(month_of_year, figure_dir)
            plotly_month_of_year_heatmap(month_of_year, figure_dir)
            plotly_month_of_year_pct_capacity_heatmap(month_of_year, figure_dir)
            plotly_calendar_month_pct_capacity_heatmap(monthly, figure_dir)
            plotly_season_pct_capacity_heatmap(season_overall, figure_dir)
            plotly_season_direction_heatmap(season_overall, figure_dir)
            plotly_correlation_and_alignment(flow_corr_matrix, direction_pairwise, conditional_direction, figure_dir)
            plotly_interconnector_profiles(
                summary,
                monthly,
                month_of_year,
                season_overall,
                rolling,
                envelope,
                bucket_summary,
                figure_dir,
            )
            plotly_interconnector_subfigures(
                summary,
                monthly,
                month_of_year,
                season_overall,
                rolling,
                envelope,
                bucket_summary,
                pct_capacity_buckets,
                figure_dir,
            )
        except RuntimeError as exc:
            print(f"{exc} Skipping Plotly-only seasonal/correlation/per-interconnector HTML profiles.")
    except RuntimeError as exc:
        print(f"{exc} Falling back to Plotly HTML charts.")
        generate_plotly_charts(
            output_dir,
            summary,
            monthly,
            month_of_year,
            season_overall,
            rolling,
            envelope,
            diurnal,
            bucket_summary,
            pct_capacity_buckets,
            flow_corr_matrix,
            direction_pairwise,
            conditional_direction,
        )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    metadata = read_metadata(args.metadata)
    data = read_half_hourly_data(args.data_dir, metadata, args.positive_direction)

    latest_ts = data["startTime"].max()
    earliest_ts = data["startTime"].min()
    analysis_start = normalise_timestamp(args.start) or infer_default_start(latest_ts, args.years)
    analysis_end = normalise_timestamp(args.end) or latest_ts

    if analysis_start < earliest_ts:
        analysis_start = earliest_ts
    if analysis_end > latest_ts:
        analysis_end = latest_ts
    if analysis_start > analysis_end:
        raise ValueError(f"Analysis start {analysis_start} is after end {analysis_end}")

    data = data[(data["startTime"] >= analysis_start) & (data["startTime"] <= analysis_end)].copy()
    capacity_reference = build_capacity_reference(data, args.capacity_file)
    data = add_calendar_fields(data, args.deadband_mw)
    data = add_capacity_fields(data, capacity_reference)

    metadata_cols = [col for col in ["StartedOperations"] if col in data.columns]
    fleet = build_fleet_half_hourly(data, analysis_start, analysis_end, metadata_cols)
    fleet = add_calendar_fields(fleet, args.deadband_mw)
    fleet = add_capacity_fields(fleet, capacity_reference)

    combined = pd.concat([data, fleet], ignore_index=True, sort=False)

    summary = summarise_by_interconnector(data, args.deadband_mw)
    fleet_summary = summarise_by_interconnector(fleet, args.deadband_mw).iloc[0]

    monthly = summarise_periods(combined, ["interconnectorId", "calendar_month"], args.deadband_mw)
    seasonal = summarise_periods(combined, ["interconnectorId", "season_year", "season"], args.deadband_mw)
    season_overall = summarise_periods(combined, ["interconnectorId", "season"], args.deadband_mw)
    month_of_year = add_month_names(summarise_periods(combined, ["interconnectorId", "month"], args.deadband_mw))
    season_month = add_month_names(summarise_periods(combined, ["interconnectorId", "season", "month"], args.deadband_mw))
    daily = daily_stats(combined)
    rolling = add_rolling_windows(daily, windows=[7, 30, 90])
    envelope = seasonal_weekly_envelope(daily)
    diurnal = diurnal_profile(combined)
    buckets = level_bucket_summary(combined)
    pct_buckets = pct_capacity_bucket_summary(combined)
    flow_corr_matrix, flow_corr_pairwise = flow_correlation_outputs(data)
    direction_pairwise, conditional_direction = direction_alignment_outputs(data)

    write_csv(summary, args.output_dir / "interconnector_summary.csv")
    write_csv(pd.DataFrame([fleet_summary]), args.output_dir / "fleet_summary.csv")
    write_csv(capacity_reference, args.output_dir / "capacity_reference.csv")
    write_csv(monthly, args.output_dir / "monthly_summary.csv")
    write_csv(seasonal, args.output_dir / "seasonal_summary.csv")
    write_csv(season_overall, args.output_dir / "season_overall_summary.csv")
    write_csv(month_of_year, args.output_dir / "month_of_year_summary.csv")
    write_csv(season_month, args.output_dir / "season_month_summary.csv")
    write_csv(daily, args.output_dir / "daily_timeseries.csv")
    write_csv(rolling, args.output_dir / "rolling_windows.csv")
    write_csv(envelope, args.output_dir / "weekly_seasonal_envelope.csv")
    write_csv(diurnal, args.output_dir / "diurnal_profile_by_season.csv")
    write_csv(buckets, args.output_dir / "level_bucket_summary.csv")
    write_csv(pct_buckets, args.output_dir / "pct_capacity_bucket_summary.csv")
    write_csv(flow_corr_matrix, args.output_dir / "interconnector_flow_correlation_matrix.csv")
    write_csv(flow_corr_pairwise, args.output_dir / "interconnector_flow_correlation_pairwise.csv")
    write_csv(direction_pairwise, args.output_dir / "interconnector_direction_alignment_pairwise.csv")
    write_csv(conditional_direction, args.output_dir / "interconnector_conditional_direction_shares.csv")
    write_csv(
        fleet[
            [
                "startTime",
                "signed_mw",
                "capacity_mw",
                "signed_pct_capacity",
                "import_mw",
                "export_mw",
                "import_pct_capacity",
                "export_pct_capacity",
                "import_gwh",
                "export_gwh",
                "net_gwh",
                "direction_state",
                "available_interconnector_count",
                "missing_interconnector_count",
            ]
        ],
        args.output_dir / "fleet_half_hourly_timeseries.csv",
    )

    build_story(
        args.output_dir,
        summary,
        fleet_summary,
        monthly,
        season_overall,
        month_of_year,
        flow_corr_pairwise,
        direction_pairwise,
        analysis_start,
        analysis_end,
        args.positive_direction,
        args.deadband_mw,
    )
    build_presentation_outline(
        args.output_dir,
        summary,
        fleet_summary,
        season_overall,
        month_of_year,
        flow_corr_pairwise,
        direction_pairwise,
        analysis_start,
        analysis_end,
        args.positive_direction,
    )

    run_config = textwrap.dedent(
        f"""\
        analysis_start,{analysis_start}
        analysis_end,{analysis_end}
        positive_direction,{args.positive_direction}
        deadband_mw,{args.deadband_mw}
        input_data_dir,{args.data_dir}
        metadata_file,{args.metadata}
        capacity_file,{args.capacity_file if args.capacity_file.exists() else "not supplied; observed peak used"}
        """
    )
    (args.output_dir / "run_config.csv").write_text(run_config, encoding="utf-8")

    if not args.no_charts:
        generate_charts(
            args.output_dir,
            summary,
            monthly,
            month_of_year,
            season_overall,
            rolling,
            envelope,
            diurnal,
            buckets,
            pct_buckets,
            flow_corr_matrix,
            direction_pairwise,
            conditional_direction,
        )

    print(f"Wrote analysis pack to {args.output_dir}")
    print(f"Analysis window: {analysis_start} to {analysis_end}")
    print(f"Positive raw generation treated as GB {args.positive_direction}")


if __name__ == "__main__":
    main()
