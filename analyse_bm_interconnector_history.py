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

LEVEL_BAND_METADATA = {
    "export_gt_1500_mw": ("export", ">1500 MW"),
    "export_1000_1500_mw": ("export", "1000-1500 MW"),
    "export_500_1000_mw": ("export", "500-1000 MW"),
    "export_250_500_mw": ("export", "250-500 MW"),
    "export_50_250_mw": ("export", "50-250 MW"),
    "near_zero_abs_le_50_mw": ("near_zero", "<=50 MW"),
    "import_50_250_mw": ("import", "50-250 MW"),
    "import_250_500_mw": ("import", "250-500 MW"),
    "import_500_1000_mw": ("import", "500-1000 MW"),
    "import_1000_1500_mw": ("import", "1000-1500 MW"),
    "import_gt_1500_mw": ("import", ">1500 MW"),
}

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

TREND_LABEL_DISPLAY = {
    "more_importing": "More importing",
    "more_exporting": "More exporting",
    "mixed_or_step_change": "Mixed / step-change",
    "no_clear_pattern": "No clear pattern",
    "insufficient_data": "Insufficient data",
}

TREND_LABEL_COLORS = {
    "more_importing": "#2f6db2",
    "more_exporting": "#c43c39",
    "mixed_or_step_change": "#8a6f2a",
    "no_clear_pattern": "#7f7f7f",
    "insufficient_data": "#b8b8b8",
}


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
    out["day_of_week"] = out["startTime"].dt.dayofweek
    out["day_name"] = out["startTime"].dt.day_name()
    out["day_of_year"] = out["startTime"].dt.dayofyear
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
        "import_half_hours": int(import_mask.sum()),
        "export_half_hours": int(export_mask.sum()),
        "near_zero_half_hours": int(zero_mask.sum()),
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
        "mean_import_mw": g["import_mw"].mean(),
        "mean_export_mw": g["export_mw"].mean(),
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
        "mean_active_capacity_mw": g["active_capacity_mw"].mean() if "active_capacity_mw" in g.columns else np.nan,
        "mean_signed_pct_active_capacity": g["signed_pct_active_capacity"].mean()
        if "signed_pct_active_capacity" in g.columns
        else np.nan,
        "mean_import_pct_active_capacity_when_importing": g.loc[import_mask, "import_pct_active_capacity"].mean()
        if "import_pct_active_capacity" in g.columns
        else np.nan,
        "mean_export_pct_active_capacity_when_exporting": g.loc[export_mask, "export_pct_active_capacity"].mean()
        if "export_pct_active_capacity" in g.columns
        else np.nan,
        "mean_available_interconnector_count": g["available_interconnector_count"].mean()
        if "available_interconnector_count" in g.columns
        else np.nan,
        "mean_missing_interconnector_count": g["missing_interconnector_count"].mean()
        if "missing_interconnector_count" in g.columns
        else np.nan,
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


def add_direction_regime_fields(df: pd.DataFrame) -> pd.DataFrame:
    """Add explicit mostly-import/export labels to an aggregated direction table."""
    out = df.copy()
    required = {"import_share_pct", "export_share_pct", "near_zero_share_pct"}
    if not required.issubset(out.columns):
        return out

    shares = out[["import_share_pct", "export_share_pct", "near_zero_share_pct"]].fillna(-math.inf)
    primary_col = shares.idxmax(axis=1)
    state_map = {
        "import_share_pct": "import",
        "export_share_pct": "export",
        "near_zero_share_pct": "near_zero",
    }
    out["primary_state"] = primary_col.map(state_map)
    out["primary_state_share_pct"] = shares.max(axis=1).replace(-math.inf, np.nan)
    out["import_export_margin_pct"] = out["import_share_pct"] - out["export_share_pct"]
    out["abs_import_export_margin_pct"] = out["import_export_margin_pct"].abs()
    out["direction_bias"] = np.select(
        [out["import_export_margin_pct"] > 0, out["import_export_margin_pct"] < 0],
        ["import", "export"],
        default="balanced",
    )
    out["mostly_direction"] = np.select(
        [
            (out["primary_state"] == "import") & (out["primary_state_share_pct"] >= 50.0),
            (out["primary_state"] == "export") & (out["primary_state_share_pct"] >= 50.0),
            (out["primary_state"] == "near_zero") & (out["primary_state_share_pct"] >= 50.0),
        ],
        ["mostly_import", "mostly_export", "mostly_near_zero"],
        default="mixed",
    )
    return out


def add_daily_timing_fields(daily: pd.DataFrame) -> pd.DataFrame:
    out = add_direction_regime_fields(daily)
    out["date"] = pd.to_datetime(out["date"], utc=True, errors="raise")
    out["year"] = out["date"].dt.year
    out["month"] = out["date"].dt.month
    out["month_name"] = out["month"].astype(int).map(lambda month: calendar.month_abbr[month])
    out["season"] = out["month"].map(SEASON_BY_MONTH)
    out["day_of_week"] = out["date"].dt.dayofweek
    out["day_name"] = out["date"].dt.day_name()
    out["day_of_year"] = out["date"].dt.dayofyear
    return out


def top_direction_days(daily_regimes: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    """Pick the strongest actual-MW import/export dates for each interconnector."""
    rows: list[dict[str, object]] = []
    source = daily_regimes[daily_regimes["interconnectorId"] != "TOTAL_GB_INTERCONNECTORS"].copy()
    for interconnector_id, group in source.groupby("interconnectorId", sort=True):
        group = group.sort_values("date")
        for direction, ascending in [("import", False), ("export", True)]:
            candidates = group[group["direction_bias"] == direction].copy()
            if candidates.empty:
                candidates = group.copy()
            ranked = candidates.sort_values("mean_signed_mw", ascending=ascending).head(top_n)
            for rank, (_, row) in enumerate(ranked.iterrows(), start=1):
                rows.append(
                    {
                        "interconnectorId": interconnector_id,
                        "interconnectorName": row.get("interconnectorName"),
                        "direction": direction,
                        "rank": rank,
                        "date": row["date"],
                        "day_name": row.get("day_name"),
                        "month": row.get("month"),
                        "month_name": row.get("month_name"),
                        "season": row.get("season"),
                        "mean_signed_mw": row.get("mean_signed_mw"),
                        "median_signed_mw": row.get("median_signed_mw"),
                        "import_share_pct": row.get("import_share_pct"),
                        "export_share_pct": row.get("export_share_pct"),
                        "near_zero_share_pct": row.get("near_zero_share_pct"),
                        "mostly_direction": row.get("mostly_direction"),
                        "import_gwh": row.get("import_gwh"),
                        "export_gwh": row.get("export_gwh"),
                        "net_gwh": row.get("net_gwh"),
                    }
                )
    return pd.DataFrame(rows)


def direction_run_summary(daily_regimes: pd.DataFrame) -> pd.DataFrame:
    """Summarise consecutive daily mostly-import/export/near-zero regimes."""
    rows: list[dict[str, object]] = []
    source = daily_regimes[daily_regimes["interconnectorId"] != "TOTAL_GB_INTERCONNECTORS"].copy()
    for interconnector_id, group in source.groupby("interconnectorId", sort=True):
        group = group.sort_values("date").copy()
        run_key = group["mostly_direction"].ne(group["mostly_direction"].shift()).cumsum()
        for _, run in group.groupby(run_key, sort=True):
            first = run.iloc[0]
            rows.append(
                {
                    "interconnectorId": interconnector_id,
                    "interconnectorName": first.get("interconnectorName"),
                    "mostly_direction": first.get("mostly_direction"),
                    "start_date": run["date"].min(),
                    "end_date": run["date"].max(),
                    "days": len(run),
                    "mean_signed_mw": run["mean_signed_mw"].mean(),
                    "median_daily_mean_signed_mw": run["mean_signed_mw"].median(),
                    "mean_import_share_pct": run["import_share_pct"].mean(),
                    "mean_export_share_pct": run["export_share_pct"].mean(),
                    "mean_near_zero_share_pct": run["near_zero_share_pct"].mean(),
                    "net_gwh": run["net_gwh"].sum(),
                    "import_gwh": run["import_gwh"].sum(),
                    "export_gwh": run["export_gwh"].sum(),
                }
            )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(["interconnectorId", "start_date"], kind="mergesort").reset_index(drop=True)


def direction_timing_story(
    output_dir: Path,
    season_regimes: pd.DataFrame,
    month_regimes: pd.DataFrame,
    weekday_regimes: pd.DataFrame,
    top_days: pd.DataFrame,
    runs: pd.DataFrame,
) -> None:
    """Write a compact narrative on when each link mostly imports/exports."""
    lines: list[str] = [
        "# Interconnector Import/Export Timing Patterns",
        "",
        "Positive MW means GB importing. Negative MW means GB exporting.",
        "`mostly_import` / `mostly_export` means that direction is the largest state and covers at least 50% of the grouped half-hours.",
        "",
        "## Per-Interconnector Timing Readout",
        "",
    ]

    ids = sorted(interconnector_id for interconnector_id in month_regimes["interconnectorId"].unique() if interconnector_id != "TOTAL_GB_INTERCONNECTORS")
    for interconnector_id in ids:
        m = month_regimes[month_regimes["interconnectorId"] == interconnector_id].copy()
        s = season_regimes[season_regimes["interconnectorId"] == interconnector_id].copy()
        w = weekday_regimes[weekday_regimes["interconnectorId"] == interconnector_id].copy()
        d = top_days[top_days["interconnectorId"] == interconnector_id].copy()
        r = runs[runs["interconnectorId"] == interconnector_id].copy()
        name = m["interconnectorName"].dropna().iloc[0] if not m.empty else interconnector_id

        import_months = m[m["mostly_direction"] == "mostly_import"].sort_values("mean_signed_mw", ascending=False)
        export_months = m[m["mostly_direction"] == "mostly_export"].sort_values("mean_signed_mw", ascending=True)
        strongest_import_month = import_months.iloc[0] if not import_months.empty else None
        strongest_export_month = export_months.iloc[0] if not export_months.empty else None

        season_order = ["Winter", "Spring", "Summer", "Autumn"]
        s["season"] = pd.Categorical(s["season"], categories=season_order, ordered=True)
        mostly_import_seasons = s[s["mostly_direction"] == "mostly_import"].sort_values("season")
        mostly_export_seasons = s[s["mostly_direction"] == "mostly_export"].sort_values("season")

        weekday_range = w["mean_signed_mw"].max() - w["mean_signed_mw"].min() if not w.empty else np.nan
        weekday_import = w.sort_values("mean_signed_mw", ascending=False).iloc[0] if not w.empty else None
        weekday_export = w.sort_values("mean_signed_mw", ascending=True).iloc[0] if not w.empty else None

        top_import_day = d[d["direction"] == "import"].sort_values("rank").head(1)
        top_export_day = d[d["direction"] == "export"].sort_values("rank").head(1)
        longest_import_run = r[r["mostly_direction"] == "mostly_import"].sort_values("days", ascending=False).head(1)
        longest_export_run = r[r["mostly_direction"] == "mostly_export"].sort_values("days", ascending=False).head(1)

        lines.extend([f"### {interconnector_id} - {name}", ""])
        if not mostly_import_seasons.empty:
            lines.append(
                "- Mostly importing seasons: "
                + ", ".join(
                    f"{row['season']} ({format_num(row['mean_signed_mw'])} MW, import share {format_pct(row['import_share_pct'])})"
                    for _, row in mostly_import_seasons.iterrows()
                )
                + "."
            )
        if not mostly_export_seasons.empty:
            lines.append(
                "- Mostly exporting seasons: "
                + ", ".join(
                    f"{row['season']} ({format_num(row['mean_signed_mw'])} MW, export share {format_pct(row['export_share_pct'])})"
                    for _, row in mostly_export_seasons.iterrows()
                )
                + "."
            )
        if strongest_import_month is not None:
            lines.append(
                f"- Strongest import month-of-year: {strongest_import_month['month_name']} "
                f"at {format_num(strongest_import_month['mean_signed_mw'])} MW on average "
                f"({format_pct(strongest_import_month['import_share_pct'])} import share)."
            )
        if strongest_export_month is not None:
            lines.append(
                f"- Strongest export month-of-year: {strongest_export_month['month_name']} "
                f"at {format_num(strongest_export_month['mean_signed_mw'])} MW on average "
                f"({format_pct(strongest_export_month['export_share_pct'])} export share)."
            )
        if weekday_import is not None and weekday_export is not None:
            lines.append(
                f"- Weekday spread is {format_num(weekday_range)} MW between "
                f"{weekday_export['day_name']} ({format_num(weekday_export['mean_signed_mw'])} MW) and "
                f"{weekday_import['day_name']} ({format_num(weekday_import['mean_signed_mw'])} MW)."
            )
        if not top_import_day.empty:
            row = top_import_day.iloc[0]
            lines.append(
                f"- Highest import day: {pd.Timestamp(row['date']).date()} ({row['day_name']}) at {format_num(row['mean_signed_mw'])} MW daily average."
            )
        if not top_export_day.empty:
            row = top_export_day.iloc[0]
            lines.append(
                f"- Highest export day: {pd.Timestamp(row['date']).date()} ({row['day_name']}) at {format_num(row['mean_signed_mw'])} MW daily average."
            )
        if not longest_import_run.empty:
            row = longest_import_run.iloc[0]
            lines.append(
                f"- Longest mostly-importing daily run: {int(row['days'])} days "
                f"({pd.Timestamp(row['start_date']).date()} to {pd.Timestamp(row['end_date']).date()})."
            )
        if not longest_export_run.empty:
            row = longest_export_run.iloc[0]
            lines.append(
                f"- Longest mostly-exporting daily run: {int(row['days'])} days "
                f"({pd.Timestamp(row['start_date']).date()} to {pd.Timestamp(row['end_date']).date()})."
            )
        lines.append("")

    lines.extend(
        [
            "## Output Tables",
            "",
            "- `direction_timing_season.csv` - season-level mostly importing/exporting regimes.",
            "- `direction_timing_month_of_year.csv` - collapsed month-of-year regimes.",
            "- `direction_timing_weekday.csv` - weekday regimes.",
            "- `direction_timing_daily.csv` - every interconnector/day with mostly-direction labels.",
            "- `direction_timing_top_days.csv` - top import/export dates per interconnector.",
            "- `direction_timing_runs.csv` - consecutive daily mostly-import/export/near-zero periods.",
            "",
        ]
    )
    (output_dir / "direction_timing_story.md").write_text("\n".join(lines), encoding="utf-8")


def build_fleet_half_hourly(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, metadata_cols: list[str]) -> pd.DataFrame:
    full_index = pd.date_range(start=start, end=end, freq="30min", tz="UTC")
    wide = df.pivot_table(index="startTime", columns="interconnectorId", values="signed_mw", aggfunc="first")
    wide = wide.reindex(full_index)
    capacity_wide = df.pivot_table(index="startTime", columns="interconnectorId", values="capacity_mw", aggfunc="first")
    capacity_wide = capacity_wide.reindex(full_index)
    available_mask = wide.notna()
    active_capacity_mw = capacity_wide.where(available_mask).sum(axis=1)
    total = pd.DataFrame(
        {
            "startTime": wide.index,
            "signed_mw": wide.fillna(0).sum(axis=1),
            "active_capacity_mw": active_capacity_mw,
            "available_interconnector_count": wide.notna().sum(axis=1),
            "missing_interconnector_count": wide.shape[1] - wide.notna().sum(axis=1),
        }
    )
    total["raw_generation_mw"] = total["signed_mw"]
    total["import_mw"] = total["signed_mw"].clip(lower=0)
    total["export_mw"] = (-total["signed_mw"]).clip(lower=0)
    active_capacity = total["active_capacity_mw"].replace(0, np.nan)
    total["signed_pct_active_capacity"] = total["signed_mw"] / active_capacity * 100.0
    total["import_pct_active_capacity"] = total["import_mw"] / active_capacity * 100.0
    total["export_pct_active_capacity"] = total["export_mw"] / active_capacity * 100.0
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
    agg_spec = {
        "observations": ("signed_mw", "size"),
        "mean_signed_mw": ("signed_mw", "mean"),
        "mean_import_mw": ("import_mw", "mean"),
        "mean_export_mw": ("export_mw", "mean"),
        "mean_capacity_mw": ("capacity_mw", "mean"),
        "mean_signed_pct_capacity": ("signed_pct_capacity", "mean"),
        "median_signed_mw": ("signed_mw", "median"),
        "p10_signed_mw": ("signed_mw", lambda s: s.quantile(0.10)),
        "p90_signed_mw": ("signed_mw", lambda s: s.quantile(0.90)),
        "p10_signed_pct_capacity": ("signed_pct_capacity", lambda s: s.quantile(0.10)),
        "p90_signed_pct_capacity": ("signed_pct_capacity", lambda s: s.quantile(0.90)),
        "import_share_pct": ("direction_state", lambda s: (s == "import").mean() * 100.0),
        "export_share_pct": ("direction_state", lambda s: (s == "export").mean() * 100.0),
        "near_zero_share_pct": ("direction_state", lambda s: (s == "near_zero").mean() * 100.0),
        "import_gwh": ("import_gwh", "sum"),
        "export_gwh": ("export_gwh", "sum"),
        "net_gwh": ("net_gwh", "sum"),
    }
    optional_agg = {
        "mean_active_capacity_mw": ("active_capacity_mw", "mean"),
        "mean_signed_pct_active_capacity": ("signed_pct_active_capacity", "mean"),
        "mean_import_pct_active_capacity": ("import_pct_active_capacity", "mean"),
        "mean_export_pct_active_capacity": ("export_pct_active_capacity", "mean"),
        "mean_available_interconnector_count": ("available_interconnector_count", "mean"),
        "mean_missing_interconnector_count": ("missing_interconnector_count", "mean"),
    }
    agg_spec.update({name: spec for name, spec in optional_agg.items() if spec[0] in df.columns})
    out = grouped.agg(**agg_spec)
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
            group[f"rolling_{window}d_mean_import_mw"] = group["mean_import_mw"].rolling(
                window, min_periods=min_periods
            ).mean()
            group[f"rolling_{window}d_mean_export_mw"] = group["mean_export_mw"].rolling(
                window, min_periods=min_periods
            ).mean()
            group[f"rolling_{window}d_mean_signed_pct_capacity"] = group["mean_signed_pct_capacity"].rolling(
                window, min_periods=min_periods
            ).mean()
            if "mean_active_capacity_mw" in group.columns:
                group[f"rolling_{window}d_mean_active_capacity_mw"] = group["mean_active_capacity_mw"].rolling(
                    window, min_periods=min_periods
                ).mean()
            if "mean_signed_pct_active_capacity" in group.columns:
                group[f"rolling_{window}d_mean_signed_pct_active_capacity"] = group[
                    "mean_signed_pct_active_capacity"
                ].rolling(window, min_periods=min_periods).mean()
            if "mean_import_pct_active_capacity" in group.columns:
                group[f"rolling_{window}d_mean_import_pct_active_capacity"] = group[
                    "mean_import_pct_active_capacity"
                ].rolling(window, min_periods=min_periods).mean()
            if "mean_export_pct_active_capacity" in group.columns:
                group[f"rolling_{window}d_mean_export_pct_active_capacity"] = group[
                    "mean_export_pct_active_capacity"
                ].rolling(window, min_periods=min_periods).mean()
            if "mean_available_interconnector_count" in group.columns:
                group[f"rolling_{window}d_mean_available_interconnector_count"] = group[
                    "mean_available_interconnector_count"
                ].rolling(window, min_periods=min_periods).mean()
            group[f"rolling_{window}d_import_share_pct"] = import_obs / obs * 100.0
            group[f"rolling_{window}d_export_share_pct"] = export_obs / obs * 100.0
            group[f"rolling_{window}d_import_gwh"] = group["import_gwh"].rolling(window, min_periods=min_periods).sum()
            group[f"rolling_{window}d_export_gwh"] = group["export_gwh"].rolling(window, min_periods=min_periods).sum()
            group[f"rolling_{window}d_net_gwh"] = group["net_gwh"].rolling(window, min_periods=min_periods).sum()
        parts.append(group)
    return pd.concat(parts, ignore_index=True)


def _linear_trend_stats(group: pd.DataFrame, value_col: str, endpoint_days: int = 90) -> dict[str, float]:
    clean = group[["date", value_col]].dropna().sort_values("date")
    if clean.empty:
        return {
            "start_value": np.nan,
            "end_value": np.nan,
            "delta": np.nan,
            "slope_per_year": np.nan,
            "r2": np.nan,
            "endpoint_days_used": 0,
            "trend_observations": 0,
        }

    endpoint_n = min(endpoint_days, max(7, len(clean) // 5))
    endpoint_n = min(endpoint_n, max(1, len(clean) // 2))
    start_value = clean[value_col].head(endpoint_n).mean()
    end_value = clean[value_col].tail(endpoint_n).mean()

    if len(clean) < 2 or clean[value_col].nunique(dropna=True) < 2:
        slope = np.nan
        r2 = np.nan
    else:
        x = (clean["date"] - clean["date"].iloc[0]).dt.total_seconds() / (365.25 * 24 * 60 * 60)
        y = clean[value_col].astype(float)
        slope, intercept = np.polyfit(x.to_numpy(), y.to_numpy(), 1)
        fitted = slope * x + intercept
        ss_res = float(((y - fitted) ** 2).sum())
        ss_tot = float(((y - y.mean()) ** 2).sum())
        r2 = np.nan if ss_tot == 0 else 1.0 - ss_res / ss_tot

    return {
        "start_value": start_value,
        "end_value": end_value,
        "delta": end_value - start_value,
        "slope_per_year": slope,
        "r2": r2,
        "endpoint_days_used": int(endpoint_n),
        "trend_observations": int(len(clean)),
    }


def _trend_label(delta_mw: float, slope_mw_per_year: float, capacity_basis_mw: float, is_fleet: bool) -> str:
    if pd.isna(delta_mw):
        return "insufficient_data"
    default_threshold = 150.0 if is_fleet else 50.0
    capacity_threshold = (0.03 if is_fleet else 0.05) * capacity_basis_mw if not pd.isna(capacity_basis_mw) else np.nan
    material_threshold = max(default_threshold, capacity_threshold) if not pd.isna(capacity_threshold) else default_threshold
    if abs(delta_mw) < material_threshold:
        return "no_clear_pattern"
    if pd.isna(slope_mw_per_year):
        return "more_importing" if delta_mw > 0 else "more_exporting"
    if delta_mw > 0 and slope_mw_per_year >= 0:
        return "more_importing"
    if delta_mw < 0 and slope_mw_per_year <= 0:
        return "more_exporting"
    return "mixed_or_step_change"


def build_rolling_trend_summary(rolling: pd.DataFrame) -> pd.DataFrame:
    rows = []
    metric_map = {
        "mean_signed_mw": "rolling_30d_mean_signed_mw",
        "mean_import_mw": "rolling_30d_mean_import_mw",
        "mean_export_mw": "rolling_30d_mean_export_mw",
        "import_share_pct": "rolling_30d_import_share_pct",
        "export_share_pct": "rolling_30d_export_share_pct",
        "mean_signed_pct_capacity": "rolling_30d_mean_signed_pct_capacity",
        "mean_signed_pct_active_capacity": "rolling_30d_mean_signed_pct_active_capacity",
    }
    for interconnector_id, group in rolling.groupby("interconnectorId", sort=True):
        group = group.sort_values("date").copy()
        row = {
            "interconnectorId": interconnector_id,
            "interconnectorName": group["interconnectorName"].dropna().iloc[0]
            if group["interconnectorName"].notna().any()
            else interconnector_id,
            "first_rolling_date": group["date"].min(),
            "last_rolling_date": group["date"].max(),
            "rolling_days": int(group["date"].nunique()),
            "duration_years": (group["date"].max() - group["date"].min()) / pd.Timedelta(days=365.25),
            "calendar_years_touched": group["date"].dt.year.nunique(),
            "mean_capacity_mw": group["mean_capacity_mw"].mean() if "mean_capacity_mw" in group.columns else np.nan,
            "mean_active_capacity_mw": group["mean_active_capacity_mw"].mean()
            if "mean_active_capacity_mw" in group.columns
            else np.nan,
            "mean_available_interconnector_count": group["mean_available_interconnector_count"].mean()
            if "mean_available_interconnector_count" in group.columns
            else np.nan,
        }
        for metric_name, source_col in metric_map.items():
            if source_col not in group.columns:
                continue
            stats = _linear_trend_stats(group, source_col, endpoint_days=90)
            row[f"start_90d_rolling30_{metric_name}"] = stats["start_value"]
            row[f"end_90d_rolling30_{metric_name}"] = stats["end_value"]
            row[f"delta_rolling30_{metric_name}"] = stats["delta"]
            row[f"slope_rolling30_{metric_name}_per_year"] = stats["slope_per_year"]
            row[f"r2_rolling30_{metric_name}"] = stats["r2"]
            row[f"endpoint_days_used_{metric_name}"] = stats["endpoint_days_used"]
            row[f"trend_observations_{metric_name}"] = stats["trend_observations"]

        is_fleet = interconnector_id == "TOTAL_GB_INTERCONNECTORS"
        capacity_basis = row["mean_active_capacity_mw"] if is_fleet else row["mean_capacity_mw"]
        row["trend_label"] = _trend_label(
            row.get("delta_rolling30_mean_signed_mw", np.nan),
            row.get("slope_rolling30_mean_signed_mw_per_year", np.nan),
            capacity_basis,
            is_fleet,
        )
        rows.append(row)

    return pd.DataFrame(rows).sort_values(
        ["interconnectorId"], key=lambda s: s.ne("TOTAL_GB_INTERCONNECTORS").astype(int).astype(str) + s.astype(str)
    )


def build_trend_story(
    output_dir: Path,
    trend_summary: pd.DataFrame,
    annual_summary: pd.DataFrame,
    analysis_start: pd.Timestamp,
    analysis_end: pd.Timestamp,
) -> None:
    label_text = {
        "more_importing": "more importing",
        "more_exporting": "more exporting",
        "mixed_or_step_change": "mixed or step-change pattern",
        "no_clear_pattern": "no clear directional trend",
        "insufficient_data": "insufficient data",
    }

    lines = [
        "# GB Interconnector Five-Year Rolling Trend",
        "",
        f"Analysis window: {analysis_start.date()} to {analysis_end.date()}. Positive MW means GB importing; negative MW means GB exporting.",
        "",
        "Method: compare the first and last 90 valid days of each 30-day rolling daily mean, then cross-check with the linear slope across the rolling series. Fleet percentage metrics use active fleet capacity, i.e. only interconnectors with data in each settlement period.",
        "",
        "Recommended visuals: `figures/fleet_rolling_trend_context.*`, `figures/fleet_annual_import_export_trend.*`, `figures/interconnector_trend_delta_by_link.*`, and `figures/interconnector_rolling_trend_small_multiples.*`.",
        "",
    ]

    fleet = trend_summary[trend_summary["interconnectorId"] == "TOTAL_GB_INTERCONNECTORS"]
    if not fleet.empty:
        row = fleet.iloc[0]
        label = label_text.get(row["trend_label"], row["trend_label"])
        lines.extend(
            [
                "## Fleet Readout",
                "",
                f"- Overall label: {label}.",
                f"- 30-day rolling mean position moved from {format_num(row['start_90d_rolling30_mean_signed_mw'])} MW to {format_num(row['end_90d_rolling30_mean_signed_mw'])} MW, a change of {format_num(row['delta_rolling30_mean_signed_mw'])} MW.",
                f"- On an active-capacity basis, the same position moved from {format_num(row['start_90d_rolling30_mean_signed_pct_active_capacity'], 1)}% to {format_num(row['end_90d_rolling30_mean_signed_pct_active_capacity'], 1)}%, a change of {format_num(row['delta_rolling30_mean_signed_pct_active_capacity'], 1)} percentage points.",
                f"- Linear slope across the rolling series is {format_num(row['slope_rolling30_mean_signed_mw_per_year'])} MW/year with R2 {format_num(row['r2_rolling30_mean_signed_mw'], 2)}.",
                f"- Import share moved by {format_num(row['delta_rolling30_import_share_pct'], 1)} percentage points; export share moved by {format_num(row['delta_rolling30_export_share_pct'], 1)} percentage points.",
                f"- Mean active fleet capacity across the window was {format_num(row['mean_active_capacity_mw'])} MW, with {format_num(row['mean_available_interconnector_count'], 1)} links active on average.",
            ]
        )
        if row["trend_label"] == "no_clear_pattern" and abs(row["slope_rolling30_mean_signed_mw_per_year"]) > 150:
            lines.append(
                "- Interpretation: the endpoint comparison is broadly flat; the positive slope is mainly a consequence of the deep 2022 trough, so this is better read as volatile rather than a sustained import/export trend."
            )
        lines.append("")

        fleet_annual = annual_summary[annual_summary["interconnectorId"] == "TOTAL_GB_INTERCONNECTORS"].sort_values("year")
        if not fleet_annual.empty:
            lines.extend(["Annual fleet cross-check:", ""])
            for _, annual in fleet_annual.iterrows():
                active_capacity = annual.get("mean_active_capacity_mw", np.nan)
                active_pct = annual.get("mean_signed_pct_active_capacity", np.nan)
                lines.append(
                    f"- {int(annual['year'])}: mean {format_num(annual['mean_signed_mw'])} MW "
                    f"({format_num(active_pct, 1)}% of active capacity), import share {format_pct(annual['import_share_pct'])}, "
                    f"export share {format_pct(annual['export_share_pct'])}, active capacity {format_num(active_capacity)} MW."
                )
            lines.append("")

    links = trend_summary[trend_summary["interconnectorId"] != "TOTAL_GB_INTERCONNECTORS"].copy()
    if not links.empty:
        links["abs_delta_mw"] = links["delta_rolling30_mean_signed_mw"].abs()
        lines.extend(["## Link-Level Readout", ""])
        for _, row in links.sort_values("abs_delta_mw", ascending=False).iterrows():
            label = label_text.get(row["trend_label"], row["trend_label"])
            lines.append(
                f"- {row['interconnectorId']} ({row['interconnectorName']}): {label}. "
                f"30-day mean moved {format_num(row['delta_rolling30_mean_signed_mw'])} MW "
                f"({format_num(row['start_90d_rolling30_mean_signed_mw'])} to {format_num(row['end_90d_rolling30_mean_signed_mw'])} MW); "
                f"import share delta {format_num(row['delta_rolling30_import_share_pct'], 1)} pp, "
                f"export share delta {format_num(row['delta_rolling30_export_share_pct'], 1)} pp."
            )
        lines.append("")

    label_counts = trend_summary["trend_label"].value_counts().rename_axis("trend_label").reset_index(name="interconnector_count")
    lines.extend(["## How To Use This", ""])
    for _, row in label_counts.iterrows():
        lines.append(f"- {label_text.get(row['trend_label'], row['trend_label'])}: {int(row['interconnector_count'])} series.")
    lines.extend(
        [
            "",
            "Use `rolling_trend_summary.csv` for the compact evidence table and `annual_trend_summary.csv` for the year-by-year check. The fleet row is `TOTAL_GB_INTERCONNECTORS`.",
            "",
        ]
    )
    (output_dir / "trend_story.md").write_text("\n".join(lines), encoding="utf-8")


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


def add_level_band_metadata(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["flow_band_mw"] = out["flow_band_mw"].astype(str)
    metadata = out["flow_band_mw"].map(LEVEL_BAND_METADATA)
    out["flow_direction"] = metadata.map(lambda item: item[0] if isinstance(item, tuple) else pd.NA)
    out["mw_band"] = metadata.map(lambda item: item[1] if isinstance(item, tuple) else pd.NA)
    out["level_label"] = np.select(
        [
            out["flow_direction"].eq("export"),
            out["flow_direction"].eq("import"),
            out["flow_direction"].eq("near_zero"),
        ],
        [
            "Export " + out["mw_band"].astype(str),
            "Import " + out["mw_band"].astype(str),
            "Near zero " + out["mw_band"].astype(str),
        ],
        default=out["flow_band_mw"],
    )
    out["flow_band_mw"] = pd.Categorical(out["flow_band_mw"], categories=LEVEL_LABELS, ordered=True)
    return out.sort_values(["interconnectorId", "flow_band_mw"]).reset_index(drop=True)


def build_fleet_level_bucket_summary(bucket_summary: pd.DataFrame) -> pd.DataFrame:
    out = bucket_summary[bucket_summary["interconnectorId"] == "TOTAL_GB_INTERCONNECTORS"].copy()
    out = add_level_band_metadata(out)
    out.insert(0, "aggregation_level", "fleet_total")
    columns = existing_columns(
        out,
        [
            "aggregation_level",
            "interconnectorId",
            "interconnectorName",
            "flow_direction",
            "mw_band",
            "level_label",
            "flow_band_mw",
            "observations",
            "duration_hours",
            "duration_share_pct",
        ],
    )
    return out[columns]


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


def existing_columns(df: pd.DataFrame, columns: list[str]) -> list[str]:
    return [column for column in columns if column in df.columns]


def build_direction_share_summary(summary: pd.DataFrame, fleet_summary: pd.Series | dict[str, object]) -> pd.DataFrame:
    """Return direction-share rows for physical links plus the aggregate fleet."""

    fleet_frame = pd.DataFrame([dict(fleet_summary)])
    out = pd.concat([summary.copy(), fleet_frame], ignore_index=True, sort=False)
    out["aggregation_level"] = np.where(
        out["interconnectorId"].eq("TOTAL_GB_INTERCONNECTORS"),
        "fleet_total",
        "interconnector",
    )
    columns = existing_columns(
        out,
        [
            "aggregation_level",
            "interconnectorId",
            "interconnectorName",
            "interconnectorBiddingZone",
            "observations",
            "duration_hours",
            "import_half_hours",
            "export_half_hours",
            "near_zero_half_hours",
            "import_share_pct",
            "export_share_pct",
            "near_zero_share_pct",
            "dominant_direction",
            "mean_signed_mw",
            "mean_import_mw",
            "mean_export_mw",
            "median_signed_mw",
            "mean_import_mw_when_importing",
            "mean_export_mw_when_exporting",
            "max_import_mw",
            "max_export_mw",
            "import_gwh",
            "export_gwh",
            "net_gwh",
            "abs_flow_gwh",
            "deadband_mw",
        ],
    )
    return out[columns].sort_values(["aggregation_level", "interconnectorId"]).reset_index(drop=True)


def without_capacity_pct_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Return chart-input fields excluding capacity-normalised percentages."""
    excluded_tokens = ("pct_capacity", "abs_pct_capacity")
    columns = [column for column in df.columns if not any(token in column for token in excluded_tokens)]
    return df.loc[:, columns].copy()


def write_figure_input_csv(
    df: pd.DataFrame,
    path: Path,
    manifest_rows: list[dict[str, object]],
    *,
    output_dir: Path,
    figure_basename: str,
    source_table: str,
    notes: str,
) -> None:
    write_csv(df, path)
    manifest_rows.append(
        {
            "figure_basename": figure_basename,
            "csv_path": path.relative_to(output_dir).as_posix(),
            "source_table": source_table,
            "rows": len(df),
            "columns": len(df.columns),
            "notes": notes,
        }
    )


def figure_monthly_columns(df: pd.DataFrame, extra_cols: list[str] | None = None) -> list[str]:
    base_cols = [
        "interconnectorId",
        "interconnectorName",
        "calendar_month",
        "month",
        "month_name",
        "season",
        "season_year",
        "observations",
        "duration_hours",
        "import_share_pct",
        "export_share_pct",
        "near_zero_share_pct",
        "mean_signed_mw",
        "median_signed_mw",
        "p05_signed_mw",
        "p25_signed_mw",
        "p75_signed_mw",
        "p95_signed_mw",
        "mean_import_mw_when_importing",
        "mean_export_mw_when_exporting",
        "max_import_mw",
        "max_export_mw",
        "import_gwh",
        "export_gwh",
        "net_gwh",
        "abs_flow_gwh",
    ]
    return existing_columns(df, (extra_cols or []) + base_cols)


def figure_rolling_columns(df: pd.DataFrame) -> list[str]:
    return existing_columns(
        df,
        [
            "interconnectorId",
            "interconnectorName",
            "date",
            "observations",
            "mean_signed_mw",
            "mean_import_mw",
            "mean_export_mw",
            "median_signed_mw",
            "p10_signed_mw",
            "p90_signed_mw",
            "mean_active_capacity_mw",
            "mean_signed_pct_active_capacity",
            "mean_import_pct_active_capacity",
            "mean_export_pct_active_capacity",
            "mean_available_interconnector_count",
            "rolling_7d_mean_signed_mw",
            "rolling_30d_mean_signed_mw",
            "rolling_90d_mean_signed_mw",
            "rolling_30d_mean_import_mw",
            "rolling_30d_mean_export_mw",
            "rolling_30d_mean_active_capacity_mw",
            "rolling_30d_mean_signed_pct_active_capacity",
            "rolling_30d_mean_import_pct_active_capacity",
            "rolling_30d_mean_export_pct_active_capacity",
            "rolling_30d_mean_available_interconnector_count",
            "import_share_pct",
            "export_share_pct",
            "near_zero_share_pct",
            "rolling_7d_import_share_pct",
            "rolling_30d_import_share_pct",
            "rolling_90d_import_share_pct",
            "rolling_7d_export_share_pct",
            "rolling_30d_export_share_pct",
            "rolling_90d_export_share_pct",
            "import_gwh",
            "export_gwh",
            "net_gwh",
            "rolling_7d_import_gwh",
            "rolling_30d_import_gwh",
            "rolling_90d_import_gwh",
            "rolling_7d_export_gwh",
            "rolling_30d_export_gwh",
            "rolling_90d_export_gwh",
            "rolling_7d_net_gwh",
            "rolling_30d_net_gwh",
            "rolling_90d_net_gwh",
        ],
    )


def figure_envelope_columns(df: pd.DataFrame) -> list[str]:
    return existing_columns(
        df,
        [
            "interconnectorId",
            "interconnectorName",
            "week",
            "samples",
            "mean_signed_mw",
            "p10_signed_mw",
            "p25_signed_mw",
            "median_signed_mw",
            "p75_signed_mw",
            "p90_signed_mw",
            "mean_import_share_pct",
            "mean_export_share_pct",
        ],
    )


def figure_diurnal_columns(df: pd.DataFrame) -> list[str]:
    return existing_columns(
        df,
        [
            "interconnectorId",
            "interconnectorName",
            "season",
            "settlementPeriod",
            "hour_utc",
            "observations",
            "mean_signed_mw",
            "p10_signed_mw",
            "median_signed_mw",
            "p90_signed_mw",
            "import_share_pct",
            "export_share_pct",
        ],
    )


def export_figure_input_data(
    output_dir: Path,
    summary: pd.DataFrame,
    direction_share_summary: pd.DataFrame,
    monthly: pd.DataFrame,
    month_of_year: pd.DataFrame,
    season_overall: pd.DataFrame,
    rolling: pd.DataFrame,
    rolling_trend: pd.DataFrame,
    annual_trend: pd.DataFrame,
    envelope: pd.DataFrame,
    diurnal: pd.DataFrame,
    bucket_summary: pd.DataFrame,
    fleet_level_buckets: pd.DataFrame,
    flow_corr_matrix: pd.DataFrame,
    direction_pairwise: pd.DataFrame,
    conditional_direction: pd.DataFrame,
) -> None:
    """Write presentation-friendly CSV inputs for the figures and subfigures."""
    figure_data_dir = output_dir / "figure_input_data"
    subfigure_data_dir = figure_data_dir / "interconnectors" / "subfigures"
    manifest_rows: list[dict[str, object]] = []

    direction_cols = existing_columns(
        direction_share_summary,
        [
            "aggregation_level",
            "interconnectorId",
            "interconnectorName",
            "interconnectorBiddingZone",
            "observations",
            "duration_hours",
            "import_half_hours",
            "export_half_hours",
            "near_zero_half_hours",
            "import_share_pct",
            "export_share_pct",
            "near_zero_share_pct",
            "dominant_direction",
            "mean_signed_mw",
            "mean_import_mw",
            "mean_export_mw",
            "median_signed_mw",
            "mean_import_mw_when_importing",
            "mean_export_mw_when_exporting",
            "max_import_mw",
            "max_export_mw",
            "import_gwh",
            "export_gwh",
            "net_gwh",
            "abs_flow_gwh",
            "deadband_mw",
        ],
    )
    write_figure_input_csv(
        direction_share_summary[direction_cols].copy(),
        figure_data_dir / "direction_share_by_interconnector.csv",
        manifest_rows,
        output_dir=output_dir,
        figure_basename="direction_share_by_interconnector",
        source_table="direction_share_summary.csv",
        notes="Direction shares, half-hour counts, and aggregate MW/GWh context for each link plus the fleet total row.",
    )

    energy_cols = existing_columns(
        summary,
        ["interconnectorId", "interconnectorName", "import_gwh", "export_gwh", "net_gwh", "abs_flow_gwh", "mean_signed_mw"],
    )
    write_figure_input_csv(
        summary[energy_cols].copy(),
        figure_data_dir / "net_energy_by_interconnector.csv",
        manifest_rows,
        output_dir=output_dir,
        figure_basename="net_energy_by_interconnector",
        source_table="interconnector_summary.csv",
        notes="Net energy chart input with import-positive GWh and mean signed MW.",
    )

    monthly_mw = without_capacity_pct_columns(monthly[figure_monthly_columns(monthly)])
    write_figure_input_csv(
        monthly_mw,
        figure_data_dir / "monthly_mean_signed_mw_heatmap.csv",
        manifest_rows,
        output_dir=output_dir,
        figure_basename="monthly_mean_signed_mw_heatmap",
        source_table="monthly_summary.csv",
        notes="Calendar-month actual MW summary used for the monthly heatmap.",
    )
    write_figure_input_csv(
        monthly_mw[monthly_mw["interconnectorId"] == "TOTAL_GB_INTERCONNECTORS"].copy(),
        figure_data_dir / "fleet_monthly_history_mw.csv",
        manifest_rows,
        output_dir=output_dir,
        figure_basename="fleet_monthly_history_mw",
        source_table="monthly_summary.csv",
        notes="Aggregate GB interconnector fleet monthly actual MW summary.",
    )

    month_of_year_mw = without_capacity_pct_columns(month_of_year[figure_monthly_columns(month_of_year)])
    write_figure_input_csv(
        month_of_year_mw,
        figure_data_dir / "month_of_year_mean_heatmap.csv",
        manifest_rows,
        output_dir=output_dir,
        figure_basename="month_of_year_mean_heatmap",
        source_table="month_of_year_summary.csv",
        notes="Collapsed month-of-year actual MW averages across the analysis years.",
    )
    write_figure_input_csv(
        month_of_year_mw[month_of_year_mw["interconnectorId"] == "TOTAL_GB_INTERCONNECTORS"].copy(),
        figure_data_dir / "fleet_month_of_year_profile_mw.csv",
        manifest_rows,
        output_dir=output_dir,
        figure_basename="fleet_month_of_year_profile",
        source_table="month_of_year_summary.csv",
        notes="Aggregate GB interconnector fleet collapsed month-of-year actual MW profile.",
    )

    season_mw = without_capacity_pct_columns(season_overall[figure_monthly_columns(season_overall)])
    write_figure_input_csv(
        season_mw,
        figure_data_dir / "season_mean_signed_mw.csv",
        manifest_rows,
        output_dir=output_dir,
        figure_basename="season_mean_signed_mw",
        source_table="season_overall_summary.csv",
        notes="Collapsed seasonal actual MW means; MW equivalent of the seasonal % capacity heatmap.",
    )
    write_figure_input_csv(
        season_mw,
        figure_data_dir / "season_direction_share_by_interconnector.csv",
        manifest_rows,
        output_dir=output_dir,
        figure_basename="season_direction_share_by_interconnector",
        source_table="season_overall_summary.csv",
        notes="Seasonal import/export/near-zero shares with actual MW context.",
    )

    fleet_rolling = rolling[rolling["interconnectorId"] == "TOTAL_GB_INTERCONNECTORS"].sort_values("date")
    write_figure_input_csv(
        without_capacity_pct_columns(fleet_rolling[figure_rolling_columns(fleet_rolling)]),
        figure_data_dir / "fleet_rolling_net_mw.csv",
        manifest_rows,
        output_dir=output_dir,
        figure_basename="fleet_rolling_net_mw",
        source_table="rolling_windows.csv",
        notes="Aggregate fleet daily and rolling actual MW/GWh values.",
    )
    fleet_trend_cols = existing_columns(
        fleet_rolling,
        [
            "interconnectorId",
            "interconnectorName",
            "date",
            "rolling_30d_mean_signed_mw",
            "rolling_90d_mean_signed_mw",
            "rolling_30d_mean_import_mw",
            "rolling_30d_mean_export_mw",
            "rolling_30d_import_share_pct",
            "rolling_30d_export_share_pct",
            "rolling_30d_mean_signed_pct_active_capacity",
            "rolling_30d_mean_active_capacity_mw",
            "rolling_30d_mean_available_interconnector_count",
        ],
    )
    write_figure_input_csv(
        fleet_rolling[fleet_trend_cols].copy(),
        figure_data_dir / "fleet_rolling_trend_context.csv",
        manifest_rows,
        output_dir=output_dir,
        figure_basename="fleet_rolling_trend_context",
        source_table="rolling_windows.csv",
        notes="Aggregate 30-day rolling trend context with active-capacity basis for the fleet.",
    )
    fleet_annual = annual_trend[annual_trend["interconnectorId"] == "TOTAL_GB_INTERCONNECTORS"].sort_values("year")
    annual_cols = existing_columns(
        fleet_annual,
        [
            "interconnectorId",
            "interconnectorName",
            "year",
            "mean_signed_mw",
            "mean_import_mw",
            "mean_export_mw",
            "import_share_pct",
            "export_share_pct",
            "near_zero_share_pct",
            "import_gwh",
            "export_gwh",
            "net_gwh",
            "mean_active_capacity_mw",
            "mean_signed_pct_active_capacity",
            "mean_available_interconnector_count",
        ],
    )
    write_figure_input_csv(
        fleet_annual[annual_cols].copy(),
        figure_data_dir / "fleet_annual_import_export_trend.csv",
        manifest_rows,
        output_dir=output_dir,
        figure_basename="fleet_annual_import_export_trend",
        source_table="annual_trend_summary.csv",
        notes="Year-by-year aggregate import/export levels, net flow, and active capacity utilisation.",
    )
    trend_cols = existing_columns(
        rolling_trend,
        [
            "interconnectorId",
            "interconnectorName",
            "trend_label",
            "first_rolling_date",
            "last_rolling_date",
            "duration_years",
            "calendar_years_touched",
            "start_90d_rolling30_mean_signed_mw",
            "end_90d_rolling30_mean_signed_mw",
            "delta_rolling30_mean_signed_mw",
            "delta_rolling30_mean_import_mw",
            "delta_rolling30_mean_export_mw",
            "delta_rolling30_import_share_pct",
            "delta_rolling30_export_share_pct",
            "slope_rolling30_mean_signed_mw_per_year",
            "r2_rolling30_mean_signed_mw",
            "delta_rolling30_mean_signed_pct_active_capacity",
        ],
    )
    write_figure_input_csv(
        rolling_trend[rolling_trend["interconnectorId"] != "TOTAL_GB_INTERCONNECTORS"][trend_cols].copy(),
        figure_data_dir / "interconnector_trend_delta_by_link.csv",
        manifest_rows,
        output_dir=output_dir,
        figure_basename="interconnector_trend_delta_by_link",
        source_table="rolling_trend_summary.csv",
        notes="Per-link trend delta chart input from the 30-day rolling endpoint comparison.",
    )
    rolling_small = rolling[rolling["interconnectorId"] != "TOTAL_GB_INTERCONNECTORS"].copy()
    rolling_small = rolling_small.merge(
        rolling_trend[["interconnectorId", "trend_label"]],
        on="interconnectorId",
        how="left",
    )
    rolling_small_cols = existing_columns(
        rolling_small,
        [
            "interconnectorId",
            "interconnectorName",
            "trend_label",
            "date",
            "rolling_30d_mean_signed_mw",
            "rolling_30d_mean_import_mw",
            "rolling_30d_mean_export_mw",
            "rolling_30d_import_share_pct",
            "rolling_30d_export_share_pct",
        ],
    )
    write_figure_input_csv(
        rolling_small[rolling_small_cols].copy(),
        figure_data_dir / "interconnector_rolling_30d_trends.csv",
        manifest_rows,
        output_dir=output_dir,
        figure_basename="interconnector_rolling_trend_small_multiples",
        source_table="rolling_windows.csv",
        notes="Per-interconnector 30-day rolling signed MW series used for the small-multiple trend chart.",
    )

    fleet_envelope = envelope[envelope["interconnectorId"] == "TOTAL_GB_INTERCONNECTORS"].sort_values("week")
    write_figure_input_csv(
        without_capacity_pct_columns(fleet_envelope[figure_envelope_columns(fleet_envelope)]),
        figure_data_dir / "fleet_weekly_seasonal_envelope.csv",
        manifest_rows,
        output_dir=output_dir,
        figure_basename="fleet_weekly_seasonal_envelope",
        source_table="weekly_seasonal_envelope.csv",
        notes="Aggregate fleet weekly seasonal envelope in actual MW.",
    )

    fleet_diurnal = diurnal[diurnal["interconnectorId"] == "TOTAL_GB_INTERCONNECTORS"].sort_values(["season", "hour_utc"])
    write_figure_input_csv(
        without_capacity_pct_columns(fleet_diurnal[figure_diurnal_columns(fleet_diurnal)]),
        figure_data_dir / "fleet_diurnal_by_season.csv",
        manifest_rows,
        output_dir=output_dir,
        figure_basename="fleet_diurnal_by_season",
        source_table="diurnal_profile_by_season.csv",
        notes="Aggregate fleet diurnal-by-season profile in actual MW.",
    )

    write_figure_input_csv(
        bucket_summary[bucket_summary["interconnectorId"] != "TOTAL_GB_INTERCONNECTORS"].copy(),
        figure_data_dir / "level_bands_by_interconnector_mw.csv",
        manifest_rows,
        output_dir=output_dir,
        figure_basename="level_bands_by_interconnector",
        source_table="level_bucket_summary.csv",
        notes="MW flow-band duration shares by interconnector.",
    )
    write_figure_input_csv(
        fleet_level_buckets.copy(),
        figure_data_dir / "fleet_level_bands_mw.csv",
        manifest_rows,
        output_dir=output_dir,
        figure_basename="fleet_level_bands_mw",
        source_table="fleet_level_bucket_summary.csv",
        notes="Aggregate GB interconnector fleet import/export MW level-band counts and duration shares.",
    )
    write_figure_input_csv(
        flow_corr_matrix.copy(),
        figure_data_dir / "flow_correlation_heatmap.csv",
        manifest_rows,
        output_dir=output_dir,
        figure_basename="flow_correlation_heatmap",
        source_table="interconnector_flow_correlation_matrix.csv",
        notes="Pairwise signed MW correlation matrix.",
    )
    write_figure_input_csv(
        direction_pairwise.copy(),
        figure_data_dir / "direction_alignment_pairwise.csv",
        manifest_rows,
        output_dir=output_dir,
        figure_basename="direction_alignment_and_opposition_heatmaps",
        source_table="interconnector_direction_alignment_pairwise.csv",
        notes="Pairwise direction alignment/opposition shares.",
    )
    write_figure_input_csv(
        conditional_direction.copy(),
        figure_data_dir / "conditional_direction_shares.csv",
        manifest_rows,
        output_dir=output_dir,
        figure_basename="conditional_import_export_alignment_heatmaps",
        source_table="interconnector_conditional_direction_shares.csv",
        notes="Conditional direction shares for import/export alignment heatmaps.",
    )

    for _, summary_row in summary.sort_values("interconnectorId").iterrows():
        interconnector_id = summary_row["interconnectorId"]
        prefix = safe_filename(interconnector_id)

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

        write_figure_input_csv(
            without_capacity_pct_columns(r[figure_rolling_columns(r)]),
            subfigure_data_dir / f"{prefix}_daily_rolling.csv",
            manifest_rows,
            output_dir=output_dir,
            figure_basename=f"{prefix}_daily_rolling",
            source_table="rolling_windows.csv",
            notes="Daily and rolling actual MW/GWh data for the interconnector subfigure.",
        )
        write_figure_input_csv(
            without_capacity_pct_columns(m[figure_monthly_columns(m)]),
            subfigure_data_dir / f"{prefix}_monthly_history.csv",
            manifest_rows,
            output_dir=output_dir,
            figure_basename=f"{prefix}_monthly_history",
            source_table="monthly_summary.csv",
            notes="Calendar-month actual MW data for the interconnector monthly subfigure.",
        )
        write_figure_input_csv(
            without_capacity_pct_columns(moy[figure_monthly_columns(moy)]),
            subfigure_data_dir / f"{prefix}_month_of_year_mw.csv",
            manifest_rows,
            output_dir=output_dir,
            figure_basename=f"{prefix}_month_of_year_mw",
            source_table="month_of_year_summary.csv",
            notes="Actual MW version of the collapsed month-of-year view.",
        )
        write_figure_input_csv(
            without_capacity_pct_columns(season[figure_monthly_columns(season)]),
            subfigure_data_dir / f"{prefix}_seasonal_direction_share.csv",
            manifest_rows,
            output_dir=output_dir,
            figure_basename=f"{prefix}_seasonal_direction_share",
            source_table="season_overall_summary.csv",
            notes="Seasonal direction shares with actual MW/GWh context.",
        )
        write_figure_input_csv(
            without_capacity_pct_columns(e[figure_envelope_columns(e)]),
            subfigure_data_dir / f"{prefix}_weekly_seasonal_envelope.csv",
            manifest_rows,
            output_dir=output_dir,
            figure_basename=f"{prefix}_weekly_seasonal_envelope",
            source_table="weekly_seasonal_envelope.csv",
            notes="Weekly seasonal envelope in actual MW.",
        )
        write_figure_input_csv(
            b.copy(),
            subfigure_data_dir / f"{prefix}_level_bands_mw.csv",
            manifest_rows,
            output_dir=output_dir,
            figure_basename=f"{prefix}_level_bands_mw",
            source_table="level_bucket_summary.csv",
            notes="MW flow-band duration shares for the interconnector.",
        )

    write_csv(pd.DataFrame(manifest_rows), figure_data_dir / "_manifest.csv")


def format_num(value: float, decimals: int = 0) -> str:
    if pd.isna(value):
        return "n/a"
    return f"{value:,.{decimals}f}"


def format_pct(value: float, decimals: int = 1) -> str:
    if pd.isna(value):
        return "n/a"
    return f"{value:.{decimals}f}%"


def build_seasonal_interconnector_story(
    output_dir: Path,
    season_overall: pd.DataFrame,
    month_of_year: pd.DataFrame,
    analysis_start: pd.Timestamp,
    analysis_end: pd.Timestamp,
) -> None:
    """Write a season-focused per-interconnector narrative."""

    season_order = ["Winter", "Spring", "Summer", "Autumn"]
    source = season_overall[season_overall["interconnectorId"] != "TOTAL_GB_INTERCONNECTORS"].copy()
    months_source = month_of_year[month_of_year["interconnectorId"] != "TOTAL_GB_INTERCONNECTORS"].copy()

    def season_phrase(row: pd.Series) -> str:
        return (
            f"{row['season']} {format_num(row['mean_signed_mw'])} MW "
            f"({format_pct(row['import_share_pct'])} import / {format_pct(row['export_share_pct'])} export)"
        )

    lines = [
        "# Seasonal Interconnector Story",
        "",
        f"Analysis window: {analysis_start.strftime('%Y-%m-%d %H:%M UTC')} to {analysis_end.strftime('%Y-%m-%d %H:%M UTC')}.",
        "",
        "Positive MW means GB importing. Negative MW means GB exporting.",
        "This note focuses on whether each link has a stable seasonal regime or a clear seasonal swing.",
        "",
        "## Overall Read",
        "",
        "- The continental links are generally import-led, with spring often the strongest import season.",
        "- The Irish links are export-led across most or all seasons, especially Greenlink and Moyle.",
        "- IFA2 and Eleclink are more seasonal than the headline direction share suggests: both show much weaker or more mixed autumn behaviour.",
        "- North Sea Link remains strongly import-led in every season, while Viking Link is also import-led but with shorter operating history.",
        "",
        "## Per-Interconnector Seasonal Notes",
        "",
    ]

    for interconnector_id in sorted(source["interconnectorId"].unique()):
        seasons = source[source["interconnectorId"] == interconnector_id].copy()
        if seasons.empty:
            continue
        seasons["season"] = pd.Categorical(seasons["season"], categories=season_order, ordered=True)
        seasons = seasons.sort_values("season")

        months = months_source[months_source["interconnectorId"] == interconnector_id].sort_values("month")
        name = seasons["interconnectorName"].dropna().iloc[0]
        max_row = seasons.sort_values("mean_signed_mw", ascending=False).iloc[0]
        min_row = seasons.sort_values("mean_signed_mw", ascending=True).iloc[0]
        seasonal_range_mw = max_row["mean_signed_mw"] - min_row["mean_signed_mw"]
        seasonal_range_pct = seasons["mean_signed_pct_capacity"].max() - seasons["mean_signed_pct_capacity"].min()

        mostly_import = seasons[seasons["mostly_direction"] == "mostly_import"]
        mostly_export = seasons[seasons["mostly_direction"] == "mostly_export"]
        mixed = seasons[~seasons["mostly_direction"].isin(["mostly_import", "mostly_export"])]

        if len(mostly_import) == len(seasons):
            regime = "Consistently import-led across seasons."
        elif len(mostly_export) == len(seasons):
            regime = "Consistently export-led across seasons."
        elif len(mostly_import) > len(mostly_export):
            regime = "Mostly import-led, but with a seasonal weakening or mixed period."
        elif len(mostly_export) > len(mostly_import):
            regime = "Mostly export-led, but with a seasonal weakening or mixed period."
        else:
            regime = "Mixed seasonal regime."

        strongest_month = months.sort_values("mean_signed_mw", ascending=False).iloc[0] if not months.empty else None
        weakest_month = months.sort_values("mean_signed_mw", ascending=True).iloc[0] if not months.empty else None
        max_season_label = "Strongest import season" if max_row["mean_signed_mw"] > 0 else "Least export-leaning season"
        min_season_label = "Most export-leaning season" if min_row["mean_signed_mw"] < 0 else "Weakest import season"

        lines.extend(
            [
                f"### {interconnector_id} - {name}",
                "",
                f"- Seasonal regime: {regime}",
                f"- {max_season_label}: {season_phrase(max_row)}.",
                f"- {min_season_label}: {season_phrase(min_row)}.",
                (
                    f"- Seasonal swing: {format_num(seasonal_range_mw)} MW between those seasons "
                    f"({format_num(seasonal_range_pct, 1)} percentage points of observed capacity)."
                ),
            ]
        )

        if strongest_month is not None and weakest_month is not None:
            strongest_month_label = "strongest import month" if strongest_month["mean_signed_mw"] > 0 else "least export-leaning month"
            weakest_month_label = "most export-leaning month" if weakest_month["mean_signed_mw"] < 0 else "weakest import month"
            lines.append(
                f"- Month shape: {strongest_month_label} is {strongest_month['month_name']} "
                f"({format_num(strongest_month['mean_signed_mw'])} MW); {weakest_month_label} is "
                f"{weakest_month['month_name']} ({format_num(weakest_month['mean_signed_mw'])} MW)."
            )

        if not mixed.empty:
            mixed_bits = ", ".join(
                f"{row['season']} ({format_pct(row['import_share_pct'])} import / {format_pct(row['export_share_pct'])} export)"
                for _, row in mixed.iterrows()
            )
            lines.append(f"- Watch point: mixed seasons are {mixed_bits}.")

        lines.append("")

    output_path = output_dir / "seasonal_interconnector_story.md"
    output_path.write_text("\n".join(lines), encoding="utf-8")


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
            "4. `figures/fleet_rolling_net_mw.*` and `figures/fleet_rolling_trend_context.*` - whether the total GB interconnector BM position was tightening or relaxing, with active-capacity context.",
            "5. `figures/fleet_annual_import_export_trend.*`, `figures/interconnector_trend_delta_by_link.*`, and `figures/interconnector_rolling_trend_small_multiples.*` - five-year import/export trend readout.",
            "6. `figures/fleet_weekly_seasonal_envelope.*` - expected seasonal range across the five-year history.",
            "7. `figures/fleet_diurnal_by_season.*` - whether operation changes materially within day and season.",
            "8. `figures/flow_correlation_heatmap.*` and `figures/direction_alignment_heatmap.*` - whether links tend to move together or offset each other.",
            "9. `figures/fleet_month_of_year_profile.*`, `figures/month_of_year_mean_heatmap.*`, and `figures/season_direction_share_by_interconnector.*` - seasonal/month shape across the fleet and each link.",
            "10. `figures/month_of_year_pct_capacity_heatmap.*`, `figures/season_pct_capacity_heatmap.*`, and `figures/pct_capacity_bands_by_interconnector.*` - capacity-normalised comparative views.",
            "11. `figures/interconnectors/*_operating_profile.*` - one profile per interconnector for appendix or drill-down.",
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
            "- `rolling_trend_summary.csv`",
            "- `annual_trend_summary.csv`",
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


def plot_fleet_level_buckets(fleet_level_buckets: pd.DataFrame, figure_dir: Path) -> None:
    plt, _, _ = require_matplotlib()
    data = fleet_level_buckets.sort_values("flow_band_mw").copy()
    colors = data["flow_direction"].map({"export": "#c43c39", "near_zero": "#b8b8b8", "import": "#2f6db2"}).fillna("#777777")
    fig, ax = plt.subplots(figsize=(12, 5.5))
    ax.bar(data["level_label"], data["duration_share_pct"], color=colors)
    ax.set_ylabel("Share of half-hours (%)")
    ax.set_title("Fleet Import/Export Level Bands")
    ax.tick_params(axis="x", rotation=45)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(figure_dir / "fleet_level_bands_mw.png", dpi=160)
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


def plotly_fleet_rolling_trend_context(
    rolling: pd.DataFrame,
    rolling_trend: pd.DataFrame,
    figure_dir: Path,
) -> None:
    go = require_plotly()
    from plotly.subplots import make_subplots

    data = rolling[rolling["interconnectorId"] == "TOTAL_GB_INTERCONNECTORS"].sort_values("date")
    if data.empty:
        return

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.11,
        row_heights=[0.62, 0.38],
        specs=[[{}], [{"secondary_y": True}]],
        subplot_titles=(
            "Fleet rolling mean MW",
            "Active-capacity utilisation and active fleet size",
        ),
    )
    fig.add_scatter(
        x=data["date"],
        y=data["rolling_30d_mean_signed_mw"],
        mode="lines",
        name="30-day mean MW",
        line={"color": "#2f6db2", "width": 2.2},
        row=1,
        col=1,
    )
    fig.add_scatter(
        x=data["date"],
        y=data["rolling_90d_mean_signed_mw"],
        mode="lines",
        name="90-day mean MW",
        line={"color": "#222222", "width": 1.6},
        row=1,
        col=1,
    )
    fig.add_hline(y=0, line_color="#777777", line_width=1, row=1, col=1)

    trend = rolling_trend[rolling_trend["interconnectorId"] == "TOTAL_GB_INTERCONNECTORS"]
    valid = data.dropna(subset=["rolling_30d_mean_signed_mw"])
    if not trend.empty and not valid.empty:
        trend_row = trend.iloc[0]
        fig.add_scatter(
            x=[valid["date"].iloc[0], valid["date"].iloc[-1]],
            y=[
                trend_row["start_90d_rolling30_mean_signed_mw"],
                trend_row["end_90d_rolling30_mean_signed_mw"],
            ],
            mode="markers+text",
            name="Start/end 90-day average",
            marker={"color": "#111111", "size": 9, "symbol": "diamond"},
            text=["Start", "End"],
            textposition=["bottom center", "top center"],
            row=1,
            col=1,
        )

    if "rolling_30d_mean_signed_pct_active_capacity" in data.columns:
        fig.add_scatter(
            x=data["date"],
            y=data["rolling_30d_mean_signed_pct_active_capacity"],
            mode="lines",
            name="30-day mean % active capacity",
            line={"color": "#2a9d8f", "width": 2},
            row=2,
            col=1,
            secondary_y=False,
        )
        fig.add_hline(y=0, line_color="#777777", line_width=1, row=2, col=1)
        if not trend.empty and not valid.empty:
            trend_row = trend.iloc[0]
            fig.add_scatter(
                x=[valid["date"].iloc[0], valid["date"].iloc[-1]],
                y=[
                    trend_row["start_90d_rolling30_mean_signed_pct_active_capacity"],
                    trend_row["end_90d_rolling30_mean_signed_pct_active_capacity"],
                ],
                mode="markers",
                name="Start/end active-capacity average",
                marker={"color": "#2a9d8f", "size": 8, "symbol": "diamond"},
                row=2,
                col=1,
                secondary_y=False,
            )
    if "rolling_30d_mean_active_capacity_mw" in data.columns:
        fig.add_scatter(
            x=data["date"],
            y=data["rolling_30d_mean_active_capacity_mw"],
            mode="lines",
            name="30-day active capacity MW",
            line={"color": "#6f6f6f", "width": 1.5, "dash": "dash"},
            row=2,
            col=1,
            secondary_y=True,
        )

    fig.update_yaxes(title_text="MW (import positive)", row=1, col=1)
    fig.update_yaxes(title_text="% active capacity", row=2, col=1, secondary_y=False)
    fig.update_yaxes(title_text="Active capacity MW", row=2, col=1, secondary_y=True)
    fig.update_layout(height=780)
    plotly_layout(fig, "Fleet Rolling Trend Context")
    fig.write_html(figure_dir / "fleet_rolling_trend_context.html", include_plotlyjs="directory")


def plotly_fleet_annual_import_export_trend(annual_trend: pd.DataFrame, figure_dir: Path) -> None:
    go = require_plotly()
    from plotly.subplots import make_subplots

    data = annual_trend[annual_trend["interconnectorId"] == "TOTAL_GB_INTERCONNECTORS"].sort_values("year")
    if data.empty:
        return

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_bar(
        x=data["year"],
        y=data["mean_import_mw"],
        name="Mean import MW",
        marker_color="#2f6db2",
        secondary_y=False,
    )
    fig.add_bar(
        x=data["year"],
        y=-data["mean_export_mw"],
        name="Mean export MW",
        marker_color="#c43c39",
        secondary_y=False,
    )
    fig.add_scatter(
        x=data["year"],
        y=data["mean_signed_mw"],
        mode="lines+markers",
        name="Mean signed MW",
        line={"color": "#111111", "width": 2},
        marker={"size": 8},
        secondary_y=False,
    )
    if "mean_signed_pct_active_capacity" in data.columns:
        fig.add_scatter(
            x=data["year"],
            y=data["mean_signed_pct_active_capacity"],
            mode="lines+markers",
            name="% active capacity",
            line={"color": "#2a9d8f", "width": 2, "dash": "dot"},
            marker={"size": 7},
            secondary_y=True,
        )
    fig.add_hline(y=0, line_color="#777777", line_width=1)
    fig.update_layout(barmode="relative", xaxis={"dtick": 1}, height=620)
    fig.update_yaxes(title_text="Mean MW (import positive)", secondary_y=False)
    fig.update_yaxes(title_text="Mean % active capacity", secondary_y=True)
    plotly_layout(fig, "Fleet Annual Import/Export Trend")
    fig.write_html(figure_dir / "fleet_annual_import_export_trend.html", include_plotlyjs="directory")


def plotly_interconnector_trend_delta_by_link(rolling_trend: pd.DataFrame, figure_dir: Path) -> None:
    go = require_plotly()
    data = rolling_trend[rolling_trend["interconnectorId"] != "TOTAL_GB_INTERCONNECTORS"].copy()
    data = data.dropna(subset=["delta_rolling30_mean_signed_mw"]).sort_values("delta_rolling30_mean_signed_mw")
    if data.empty:
        return
    colors = data["trend_label"].map(TREND_LABEL_COLORS).fillna("#7f7f7f")
    labels = data["trend_label"].map(TREND_LABEL_DISPLAY).fillna(data["trend_label"])
    fig = go.Figure(
        go.Bar(
            y=data["interconnectorId"],
            x=data["delta_rolling30_mean_signed_mw"],
            orientation="h",
            marker_color=colors,
            text=data["delta_rolling30_mean_signed_mw"].map(lambda value: f"{value:,.0f} MW"),
            textposition="outside",
            customdata=np.stack(
                [
                    data["interconnectorName"],
                    labels,
                    data["start_90d_rolling30_mean_signed_mw"],
                    data["end_90d_rolling30_mean_signed_mw"],
                    data["delta_rolling30_import_share_pct"],
                    data["delta_rolling30_export_share_pct"],
                ],
                axis=-1,
            ),
            hovertemplate=(
                "<b>%{y}</b><br>%{customdata[0]}<br>"
                "Trend: %{customdata[1]}<br>"
                "Start 90d avg: %{customdata[2]:,.0f} MW<br>"
                "End 90d avg: %{customdata[3]:,.0f} MW<br>"
                "Import share delta: %{customdata[4]:.1f} pp<br>"
                "Export share delta: %{customdata[5]:.1f} pp<extra></extra>"
            ),
        )
    )
    for label, color in TREND_LABEL_COLORS.items():
        if label in set(data["trend_label"]):
            fig.add_scatter(
                x=[None],
                y=[None],
                mode="markers",
                marker={"color": color, "size": 9},
                name=TREND_LABEL_DISPLAY.get(label, label),
            )
    fig.add_vline(x=0, line_color="#777777", line_width=1)
    fig.update_layout(
        xaxis_title="Change in 30-day rolling mean MW (end 90-day average minus start 90-day average)",
        yaxis_title="",
        height=650,
        showlegend=True,
    )
    plotly_layout(fig, "Interconnector Trend Delta by Link")
    fig.write_html(figure_dir / "interconnector_trend_delta_by_link.html", include_plotlyjs="directory")


def plotly_interconnector_rolling_trend_small_multiples(
    rolling: pd.DataFrame,
    rolling_trend: pd.DataFrame,
    figure_dir: Path,
) -> None:
    go = require_plotly()
    from plotly.subplots import make_subplots

    trend_labels = rolling_trend.set_index("interconnectorId")["trend_label"].to_dict()
    ids = sorted(interconnector_id for interconnector_id in rolling["interconnectorId"].unique() if interconnector_id != "TOTAL_GB_INTERCONNECTORS")
    if not ids:
        return
    cols = 2
    rows = math.ceil(len(ids) / cols)
    fig = make_subplots(
        rows=rows,
        cols=cols,
        shared_xaxes=True,
        vertical_spacing=0.08,
        horizontal_spacing=0.08,
        subplot_titles=ids,
    )
    for index, interconnector_id in enumerate(ids):
        row = index // cols + 1
        col = index % cols + 1
        link = rolling[rolling["interconnectorId"] == interconnector_id].sort_values("date")
        label = trend_labels.get(interconnector_id, "no_clear_pattern")
        fig.add_scatter(
            x=link["date"],
            y=link["rolling_30d_mean_signed_mw"],
            mode="lines",
            line={"color": TREND_LABEL_COLORS.get(label, "#7f7f7f"), "width": 1.7},
            name=TREND_LABEL_DISPLAY.get(label, label),
            showlegend=False,
            row=row,
            col=col,
        )
        fig.add_hline(y=0, line_color="#999999", line_width=1, row=row, col=col)
        fig.update_yaxes(title_text="MW", row=row, col=col)

    for label in sorted(set(trend_labels.values())):
        fig.add_scatter(
            x=[None],
            y=[None],
            mode="lines",
            line={"color": TREND_LABEL_COLORS.get(label, "#7f7f7f"), "width": 3},
            name=TREND_LABEL_DISPLAY.get(label, label),
        )

    fig.update_layout(height=max(850, rows * 230), showlegend=True)
    fig.update_xaxes(title_text="")
    plotly_layout(fig, "Interconnector 30-Day Rolling Trend Small Multiples")
    fig.write_html(figure_dir / "interconnector_rolling_trend_small_multiples.html", include_plotlyjs="directory")


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


def plotly_fleet_level_buckets(fleet_level_buckets: pd.DataFrame, figure_dir: Path) -> None:
    go = require_plotly()
    data = fleet_level_buckets.sort_values("flow_band_mw").copy()
    colors = data["flow_direction"].map({"export": "#c43c39", "near_zero": "#b8b8b8", "import": "#2f6db2"}).fillna("#777777")
    fig = go.Figure(
        go.Bar(
            x=data["level_label"],
            y=data["duration_share_pct"],
            marker_color=colors,
            text=data["duration_share_pct"].map(lambda value: f"{value:.1f}%"),
            textposition="outside",
            customdata=np.stack([data["observations"], data["duration_hours"]], axis=-1),
            hovertemplate="%{x}<br>Share: %{y:.2f}%<br>Half-hours: %{customdata[0]:,.0f}<br>Hours: %{customdata[1]:,.1f}<extra></extra>",
        )
    )
    fig.update_layout(xaxis_title="", yaxis_title="Share of half-hours (%)", showlegend=False, height=560)
    fig.update_xaxes(tickangle=45)
    plotly_layout(fig, "Fleet Import/Export Level Bands")
    fig.write_html(figure_dir / "fleet_level_bands_mw.html", include_plotlyjs="directory")


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
    direction_share_summary: pd.DataFrame | None,
    monthly: pd.DataFrame,
    month_of_year: pd.DataFrame,
    season_overall: pd.DataFrame,
    rolling: pd.DataFrame,
    rolling_trend: pd.DataFrame,
    annual_trend: pd.DataFrame,
    envelope: pd.DataFrame,
    diurnal: pd.DataFrame,
    bucket_summary: pd.DataFrame,
    fleet_level_buckets: pd.DataFrame,
    pct_capacity_buckets: pd.DataFrame,
    flow_corr_matrix: pd.DataFrame,
    direction_pairwise: pd.DataFrame,
    conditional_direction: pd.DataFrame,
) -> None:
    figure_dir = output_dir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    direction_data = direction_share_summary if direction_share_summary is not None else summary
    plotly_direction_share(direction_data, figure_dir)
    plotly_net_energy(summary, figure_dir)
    plotly_monthly_heatmap(monthly, figure_dir)
    plotly_fleet_rolling(rolling, figure_dir)
    plotly_fleet_rolling_trend_context(rolling, rolling_trend, figure_dir)
    plotly_fleet_annual_import_export_trend(annual_trend, figure_dir)
    plotly_interconnector_trend_delta_by_link(rolling_trend, figure_dir)
    plotly_interconnector_rolling_trend_small_multiples(rolling, rolling_trend, figure_dir)
    plotly_weekly_envelope(envelope, figure_dir)
    plotly_fleet_diurnal(diurnal, figure_dir)
    plotly_level_buckets(bucket_summary, figure_dir)
    plotly_fleet_level_buckets(fleet_level_buckets, figure_dir)
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
    direction_share_summary: pd.DataFrame | None,
    monthly: pd.DataFrame,
    month_of_year: pd.DataFrame,
    season_overall: pd.DataFrame,
    rolling: pd.DataFrame,
    rolling_trend: pd.DataFrame,
    annual_trend: pd.DataFrame,
    envelope: pd.DataFrame,
    diurnal: pd.DataFrame,
    bucket_summary: pd.DataFrame,
    fleet_level_buckets: pd.DataFrame,
    pct_capacity_buckets: pd.DataFrame,
    flow_corr_matrix: pd.DataFrame,
    direction_pairwise: pd.DataFrame,
    conditional_direction: pd.DataFrame,
) -> None:
    figure_dir = output_dir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    direction_data = direction_share_summary if direction_share_summary is not None else summary
    try:
        plot_direction_share(direction_data, figure_dir)
        plot_net_energy(summary, figure_dir)
        plot_monthly_heatmap(monthly, figure_dir)
        plot_fleet_rolling(rolling, figure_dir)
        plot_weekly_envelope(envelope, figure_dir)
        plot_fleet_diurnal(diurnal, figure_dir)
        plot_level_buckets(bucket_summary, figure_dir)
        plot_fleet_level_buckets(fleet_level_buckets, figure_dir)
        try:
            plotly_fleet_level_buckets(fleet_level_buckets, figure_dir)
            plotly_pct_capacity_buckets(pct_capacity_buckets, figure_dir)
            plotly_fleet_month_of_year(month_of_year, figure_dir)
            plotly_fleet_month_of_year_pct_capacity(month_of_year, figure_dir)
            plotly_month_of_year_heatmap(month_of_year, figure_dir)
            plotly_month_of_year_pct_capacity_heatmap(month_of_year, figure_dir)
            plotly_calendar_month_pct_capacity_heatmap(monthly, figure_dir)
            plotly_season_pct_capacity_heatmap(season_overall, figure_dir)
            plotly_season_direction_heatmap(season_overall, figure_dir)
            plotly_fleet_rolling_trend_context(rolling, rolling_trend, figure_dir)
            plotly_fleet_annual_import_export_trend(annual_trend, figure_dir)
            plotly_interconnector_trend_delta_by_link(rolling_trend, figure_dir)
            plotly_interconnector_rolling_trend_small_multiples(rolling, rolling_trend, figure_dir)
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
            direction_share_summary,
            monthly,
            month_of_year,
            season_overall,
            rolling,
            rolling_trend,
            annual_trend,
            envelope,
            diurnal,
            bucket_summary,
            fleet_level_buckets,
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
    direction_share_summary = build_direction_share_summary(summary, fleet_summary)

    monthly = add_direction_regime_fields(summarise_periods(combined, ["interconnectorId", "calendar_month"], args.deadband_mw))
    seasonal = add_direction_regime_fields(summarise_periods(combined, ["interconnectorId", "season_year", "season"], args.deadband_mw))
    season_overall = add_direction_regime_fields(summarise_periods(combined, ["interconnectorId", "season"], args.deadband_mw))
    month_of_year = add_direction_regime_fields(add_month_names(summarise_periods(combined, ["interconnectorId", "month"], args.deadband_mw)))
    season_month = add_month_names(summarise_periods(combined, ["interconnectorId", "season", "month"], args.deadband_mw))
    weekday = add_direction_regime_fields(summarise_periods(combined, ["interconnectorId", "day_of_week"], args.deadband_mw))
    weekday["day_name"] = weekday["day_of_week"].astype(int).map(lambda day: calendar.day_name[day])
    weekday = weekday.sort_values(["interconnectorId", "day_of_week"], kind="mergesort").reset_index(drop=True)
    annual_trend = add_direction_regime_fields(summarise_periods(combined, ["interconnectorId", "year"], args.deadband_mw))
    daily = daily_stats(combined)
    daily_regimes = add_daily_timing_fields(daily)
    timing_top_days = top_direction_days(daily_regimes)
    timing_runs = direction_run_summary(daily_regimes)
    rolling = add_rolling_windows(daily, windows=[7, 30, 90])
    rolling_trend = build_rolling_trend_summary(rolling)
    envelope = seasonal_weekly_envelope(daily)
    diurnal = diurnal_profile(combined)
    buckets = level_bucket_summary(combined)
    fleet_level_buckets = build_fleet_level_bucket_summary(buckets)
    pct_buckets = pct_capacity_bucket_summary(combined)
    flow_corr_matrix, flow_corr_pairwise = flow_correlation_outputs(data)
    direction_pairwise, conditional_direction = direction_alignment_outputs(data)

    write_csv(summary, args.output_dir / "interconnector_summary.csv")
    write_csv(pd.DataFrame([fleet_summary]), args.output_dir / "fleet_summary.csv")
    write_csv(direction_share_summary, args.output_dir / "direction_share_summary.csv")
    write_csv(capacity_reference, args.output_dir / "capacity_reference.csv")
    write_csv(monthly, args.output_dir / "monthly_summary.csv")
    write_csv(seasonal, args.output_dir / "seasonal_summary.csv")
    write_csv(season_overall, args.output_dir / "season_overall_summary.csv")
    write_csv(month_of_year, args.output_dir / "month_of_year_summary.csv")
    write_csv(season_month, args.output_dir / "season_month_summary.csv")
    write_csv(daily, args.output_dir / "daily_timeseries.csv")
    write_csv(monthly, args.output_dir / "direction_timing_calendar_month.csv")
    write_csv(season_overall, args.output_dir / "direction_timing_season.csv")
    write_csv(month_of_year, args.output_dir / "direction_timing_month_of_year.csv")
    write_csv(weekday, args.output_dir / "direction_timing_weekday.csv")
    write_csv(daily_regimes, args.output_dir / "direction_timing_daily.csv")
    write_csv(timing_top_days, args.output_dir / "direction_timing_top_days.csv")
    write_csv(timing_runs, args.output_dir / "direction_timing_runs.csv")
    write_csv(rolling, args.output_dir / "rolling_windows.csv")
    write_csv(annual_trend, args.output_dir / "annual_trend_summary.csv")
    write_csv(rolling_trend, args.output_dir / "rolling_trend_summary.csv")
    write_csv(envelope, args.output_dir / "weekly_seasonal_envelope.csv")
    write_csv(diurnal, args.output_dir / "diurnal_profile_by_season.csv")
    write_csv(buckets, args.output_dir / "level_bucket_summary.csv")
    write_csv(fleet_level_buckets, args.output_dir / "fleet_level_bucket_summary.csv")
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
                "active_capacity_mw",
                "signed_pct_capacity",
                "signed_pct_active_capacity",
                "import_mw",
                "export_mw",
                "import_pct_capacity",
                "export_pct_capacity",
                "import_pct_active_capacity",
                "export_pct_active_capacity",
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
    export_figure_input_data(
        args.output_dir,
        summary,
        direction_share_summary,
        monthly,
        month_of_year,
        season_overall,
        rolling,
        rolling_trend,
        annual_trend,
        envelope,
        diurnal,
        buckets,
        fleet_level_buckets,
        flow_corr_matrix,
        direction_pairwise,
        conditional_direction,
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
    direction_timing_story(
        args.output_dir,
        season_overall,
        month_of_year,
        weekday,
        timing_top_days,
        timing_runs,
    )
    build_seasonal_interconnector_story(
        args.output_dir,
        season_overall,
        month_of_year,
        analysis_start,
        analysis_end,
    )
    build_trend_story(
        args.output_dir,
        rolling_trend,
        annual_trend,
        analysis_start,
        analysis_end,
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
            direction_share_summary,
            monthly,
            month_of_year,
            season_overall,
            rolling,
            rolling_trend,
            annual_trend,
            envelope,
            diurnal,
            buckets,
            fleet_level_buckets,
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
