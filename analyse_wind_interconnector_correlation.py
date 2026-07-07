"""Correlate GB wind BMU output with GB interconnector BM operation.

This script joins the existing interconnector half-hourly BM data in ``HH_data``
with the wind BMU settlement time series produced in the sibling
``elexon-iris`` repository.

Wind conventions:
  - ``metered`` is treated as actual wind output.
  - ``metered - bav`` is treated as the pre-curtailment proxy, matching the
    previous ``metered_minus_bav`` wind workflow.
  - Wind settlement files store half-hour energy at ``halfHourEndTime``. The
    script subtracts 30 minutes and converts MWh to average MW before joining
    to interconnector ``startTime``.

Interconnector conventions:
  - Positive raw ``generation`` is treated as GB import by default.
  - Positive ``signed_mw`` means GB import; negative means GB export.
"""

from __future__ import annotations

import argparse
import calendar
import math
import textwrap
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

SEASON_ORDER = ["Winter", "Spring", "Summer", "Autumn"]

WIND_METRICS = {
    "wind_actual_mw": "Actual wind output",
    "wind_before_curtailment_mw": "Wind before curtailment proxy",
}

FLOW_METRICS = {
    "signed_mw": "Signed interconnector position",
    "import_mw": "Import magnitude",
    "export_mw": "Export magnitude",
}

WIND_BUCKET_LABELS = [
    "lowest_20pct",
    "20_40pct",
    "40_60pct",
    "60_80pct",
    "highest_20pct",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Correlate aggregate GB wind BMU output with interconnector BM operation."
    )
    parser.add_argument(
        "--interconnector-data-dir",
        type=Path,
        default=Path("HH_data"),
        help="Folder containing one half-hourly CSV per interconnector.",
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        default=Path("interconnectors_names.csv"),
        help="Optional interconnector metadata CSV.",
    )
    parser.add_argument(
        "--wind-settlement-dir",
        type=Path,
        default=Path("..") / "elexon-iris" / "wind_bmu_best_settlement_timeseries",
        help="Folder containing per-wind-BMU best settlement CSVs from elexon-iris.",
    )
    parser.add_argument(
        "--interconnector-run-config",
        type=Path,
        default=Path("analysis_outputs") / "bm_interconnector_history" / "run_config.csv",
        help="Optional run_config.csv from the existing interconnector history pack.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("analysis_outputs") / "wind_interconnector_correlation",
        help="Folder to write joined data, correlation tables, figures, and story.md.",
    )
    parser.add_argument("--start", type=str, default=None, help="Inclusive analysis start timestamp.")
    parser.add_argument("--end", type=str, default=None, help="Inclusive analysis end timestamp.")
    parser.add_argument(
        "--years",
        type=int,
        default=5,
        help="Default lookback length when no start is supplied and no run_config.csv is available.",
    )
    parser.add_argument(
        "--positive-direction",
        choices=["import", "export"],
        default="import",
        help="How to interpret positive raw interconnector generation.",
    )
    parser.add_argument(
        "--deadband-mw",
        type=float,
        default=1.0,
        help="Absolute MW threshold treated as near-zero for direction shares.",
    )
    parser.add_argument(
        "--min-correlation-observations",
        type=int,
        default=48,
        help="Minimum paired observations required before calculating a correlation.",
    )
    parser.add_argument("--no-figures", action="store_true", help="Skip Plotly figure generation.")
    return parser.parse_args()


def normalise_timestamp(value: str | pd.Timestamp | None) -> pd.Timestamp | None:
    if value in (None, ""):
        return None
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def infer_default_start(latest_ts: pd.Timestamp, years: int) -> pd.Timestamp:
    latest_day = latest_ts.floor("D")
    return latest_day - pd.DateOffset(years=years) + pd.Timedelta(days=1)


def read_run_config(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    config = pd.read_csv(path, header=None, names=["key", "value"])
    return dict(zip(config["key"], config["value"]))


def read_metadata(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["interconnectorId", "interconnectorName", "interconnectorBiddingZone"])

    metadata = pd.read_csv(path)
    metadata = metadata.loc[:, ~metadata.columns.str.startswith("Unnamed")]
    expected = {"interconnectorId", "interconnectorName", "interconnectorBiddingZone"}
    missing = expected.difference(metadata.columns)
    if missing:
        raise ValueError(f"Metadata file {path} is missing expected columns: {sorted(missing)}")
    return metadata


def read_interconnector_data(
    data_dir: Path,
    metadata: pd.DataFrame,
    positive_direction: str,
) -> pd.DataFrame:
    files = sorted(data_dir.glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"No interconnector CSV files found in {data_dir}")

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
        raise ValueError(f"Null or non-numeric interconnector generation values found: {nulls}")

    sign = 1 if positive_direction == "import" else -1
    data["signed_mw"] = data["raw_generation_mw"] * sign
    data["import_mw"] = data["signed_mw"].clip(lower=0)
    data["export_mw"] = (-data["signed_mw"]).clip(lower=0)

    if not metadata.empty:
        data = data.merge(metadata, how="left", on="interconnectorId")
    else:
        data["interconnectorName"] = data["interconnectorId"]
        data["interconnectorBiddingZone"] = pd.NA

    data["interconnectorName"] = data["interconnectorName"].fillna(data["interconnectorId"])
    data["interconnectorBiddingZone"] = data["interconnectorBiddingZone"].fillna("Unknown")
    return data.sort_values(["interconnectorId", "startTime"]).reset_index(drop=True)


def filter_window(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    return df[(df["startTime"] >= start) & (df["startTime"] <= end)].copy()


def add_flow_calendar_fields(df: pd.DataFrame, deadband_mw: float) -> pd.DataFrame:
    out = df.copy()
    out["date"] = out["startTime"].dt.floor("D")
    out["year"] = out["startTime"].dt.year
    out["month"] = out["startTime"].dt.month
    out["month_name"] = out["month"].map(lambda month: calendar.month_name[int(month)])
    out["calendar_month"] = out["startTime"].dt.strftime("%Y-%m")
    out["day_of_week"] = out["startTime"].dt.dayofweek
    out["day_name"] = out["startTime"].dt.day_name()
    out["hour_utc"] = out["startTime"].dt.hour + out["startTime"].dt.minute / 60.0
    out["season"] = out["month"].map(SEASON_BY_MONTH)
    out["season_year"] = out["year"] + (out["month"] == 12).astype(int)
    if "import_gwh" not in out.columns:
        out["import_gwh"] = out["import_mw"] * GWH_PER_MW_HALF_HOUR
    if "export_gwh" not in out.columns:
        out["export_gwh"] = out["export_mw"] * GWH_PER_MW_HALF_HOUR
    if "net_gwh" not in out.columns:
        out["net_gwh"] = out["signed_mw"] * GWH_PER_MW_HALF_HOUR
    out["direction_state"] = np.select(
        [out["signed_mw"] > deadband_mw, out["signed_mw"] < -deadband_mw],
        ["import", "export"],
        default="near_zero",
    )
    return out


def build_fleet_interconnector(data: pd.DataFrame) -> pd.DataFrame:
    wide = data.pivot_table(index="startTime", columns="interconnectorId", values="signed_mw", aggfunc="first")
    total = pd.DataFrame(
        {
            "startTime": wide.index,
            "signed_mw": wide.fillna(0).sum(axis=1).to_numpy(),
            "available_interconnector_count": wide.notna().sum(axis=1).to_numpy(),
            "missing_interconnector_count": (wide.shape[1] - wide.notna().sum(axis=1)).to_numpy(),
        }
    )
    total["raw_generation_mw"] = total["signed_mw"]
    total["import_mw"] = total["signed_mw"].clip(lower=0)
    total["export_mw"] = (-total["signed_mw"]).clip(lower=0)
    total["interconnectorId"] = "TOTAL_GB_INTERCONNECTORS"
    total["interconnectorName"] = "GB interconnector fleet total"
    total["interconnectorBiddingZone"] = "Fleet"
    total["settlementPeriod"] = pd.NA
    return total


def resolve_window(
    args: argparse.Namespace,
    interconnector_data: pd.DataFrame,
) -> tuple[pd.Timestamp, pd.Timestamp, dict[str, str]]:
    run_config = read_run_config(args.interconnector_run_config)

    end = normalise_timestamp(args.end) or normalise_timestamp(run_config.get("analysis_end"))
    if end is None:
        end = interconnector_data["startTime"].max()

    start = normalise_timestamp(args.start) or normalise_timestamp(run_config.get("analysis_start"))
    if start is None:
        start = infer_default_start(end, args.years)

    if start > end:
        raise ValueError(f"Analysis start {start} is after end {end}")
    return start, end, run_config


def wind_settlement_files(wind_dir: Path) -> list[Path]:
    files = []
    for path in sorted(wind_dir.glob("*.csv")):
        lower_name = path.name.lower()
        if "manifest" in lower_name or "failure" in lower_name or lower_name.startswith("_"):
            continue
        files.append(path)
    if not files:
        raise FileNotFoundError(f"No wind BMU settlement CSVs found in {wind_dir}")
    return files


def aggregate_wind_settlement(
    wind_dir: Path,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    total: pd.DataFrame | None = None
    rows: list[dict[str, object]] = []

    for path in wind_settlement_files(wind_dir):
        try:
            frame = pd.read_csv(path, usecols=["halfHourEndTime", "metered", "bav"])
        except ValueError as exc:
            raise ValueError(f"{path} is missing one of halfHourEndTime, metered, bav") from exc

        frame["startTime"] = pd.to_datetime(frame["halfHourEndTime"], utc=True, errors="coerce") - pd.Timedelta(minutes=30)
        frame = frame[(frame["startTime"] >= start) & (frame["startTime"] <= end)].copy()
        if frame.empty:
            rows.append(
                {
                    "bm_unit_id": path.stem,
                    "rows_in_requested_window": 0,
                    "first_startTime": pd.NaT,
                    "last_startTime": pd.NaT,
                    "total_actual_mwh": 0.0,
                    "total_before_curtailment_mwh": 0.0,
                }
            )
            continue

        frame["metered"] = pd.to_numeric(frame["metered"], errors="coerce")
        frame["bav"] = pd.to_numeric(frame["bav"], errors="coerce").fillna(0.0)
        frame = frame.dropna(subset=["startTime", "metered"])
        frame["wind_actual_mwh"] = frame["metered"]
        frame["wind_before_curtailment_mwh"] = frame["metered"] - frame["bav"]

        grouped = frame.groupby("startTime", sort=True)[["wind_actual_mwh", "wind_before_curtailment_mwh"]].sum()
        total = grouped if total is None else total.add(grouped, fill_value=0.0)

        rows.append(
            {
                "bm_unit_id": path.stem,
                "rows_in_requested_window": len(frame),
                "first_startTime": frame["startTime"].min(),
                "last_startTime": frame["startTime"].max(),
                "total_actual_mwh": frame["wind_actual_mwh"].sum(),
                "total_before_curtailment_mwh": frame["wind_before_curtailment_mwh"].sum(),
            }
        )

    if total is None or total.empty:
        raise ValueError(f"No wind settlement rows overlapped {start} to {end}")

    wind = total.reset_index().sort_values("startTime")
    wind["wind_actual_mw"] = wind["wind_actual_mwh"] / HH_HOURS
    wind["wind_before_curtailment_mw"] = wind["wind_before_curtailment_mwh"] / HH_HOURS
    wind["wind_curtailment_proxy_mw"] = wind["wind_before_curtailment_mw"] - wind["wind_actual_mw"]
    wind["wind_bav_net_mw"] = -wind["wind_curtailment_proxy_mw"]
    wind = wind[
        [
            "startTime",
            "wind_actual_mwh",
            "wind_before_curtailment_mwh",
            "wind_actual_mw",
            "wind_before_curtailment_mw",
            "wind_curtailment_proxy_mw",
            "wind_bav_net_mw",
        ]
    ]

    source_summary = pd.DataFrame(rows).sort_values("bm_unit_id")
    return wind, source_summary


def join_wind_and_interconnectors(
    interconnector_data: pd.DataFrame,
    wind: pd.DataFrame,
    deadband_mw: float,
) -> pd.DataFrame:
    joined = interconnector_data.merge(wind, on="startTime", how="inner")
    joined = add_flow_calendar_fields(joined, deadband_mw)
    return joined.sort_values(["interconnectorId", "startTime"]).reset_index(drop=True)


def build_wide_join(joined: pd.DataFrame) -> pd.DataFrame:
    flows = joined.pivot_table(index="startTime", columns="interconnectorId", values="signed_mw", aggfunc="first")
    flows = flows.add_prefix("signed_mw_").reset_index()
    wind_cols = [
        "startTime",
        "wind_actual_mw",
        "wind_before_curtailment_mw",
        "wind_curtailment_proxy_mw",
    ]
    wind = joined[wind_cols].drop_duplicates("startTime")
    return wind.merge(flows, on="startTime", how="left").sort_values("startTime")


def aggregate_joined(joined: pd.DataFrame, granularity: str, deadband_mw: float) -> pd.DataFrame:
    if granularity == "daily":
        group_cols = ["interconnectorId", "interconnectorName", "date"]
    elif granularity == "monthly":
        group_cols = ["interconnectorId", "interconnectorName", "calendar_month"]
    else:
        raise ValueError(f"Unsupported granularity: {granularity}")

    out = (
        joined.groupby(group_cols, sort=True)
        .agg(
            observations=("signed_mw", "size"),
            signed_mw=("signed_mw", "mean"),
            import_mw=("import_mw", "mean"),
            export_mw=("export_mw", "mean"),
            import_gwh=("import_gwh", "sum"),
            export_gwh=("export_gwh", "sum"),
            net_gwh=("net_gwh", "sum"),
            wind_actual_mw=("wind_actual_mw", "mean"),
            wind_before_curtailment_mw=("wind_before_curtailment_mw", "mean"),
            wind_curtailment_proxy_mw=("wind_curtailment_proxy_mw", "mean"),
        )
        .reset_index()
    )

    if granularity == "daily":
        out["startTime"] = pd.to_datetime(out["date"], utc=True)
    else:
        month_start = pd.to_datetime(out["calendar_month"] + "-01", utc=True)
        out["startTime"] = month_start
        out["date"] = month_start

    out = add_flow_calendar_fields(out, deadband_mw)
    return out


def correlation_values(
    group: pd.DataFrame,
    wind_col: str,
    flow_col: str,
    min_observations: int,
) -> dict[str, object]:
    pairs = group[[wind_col, flow_col]].replace([np.inf, -np.inf], np.nan).dropna()
    observations = len(pairs)
    if observations < min_observations or pairs[wind_col].nunique() < 2 or pairs[flow_col].nunique() < 2:
        pearson = np.nan
        spearman = np.nan
    else:
        pearson = pairs[wind_col].corr(pairs[flow_col], method="pearson")
        spearman = pairs[wind_col].corr(pairs[flow_col], method="spearman")

    return {
        "observations": observations,
        "pearson_corr": pearson,
        "spearman_corr": spearman,
        "wind_mean_mw": pairs[wind_col].mean() if observations else np.nan,
        "wind_p10_mw": pairs[wind_col].quantile(0.10) if observations else np.nan,
        "wind_p90_mw": pairs[wind_col].quantile(0.90) if observations else np.nan,
        "flow_mean_mw": pairs[flow_col].mean() if observations else np.nan,
        "flow_p10_mw": pairs[flow_col].quantile(0.10) if observations else np.nan,
        "flow_p90_mw": pairs[flow_col].quantile(0.90) if observations else np.nan,
    }


def build_correlation_table(
    data: pd.DataFrame,
    granularity: str,
    min_observations: int,
    extra_group_cols: Iterable[str] = (),
) -> pd.DataFrame:
    group_cols = ["interconnectorId", "interconnectorName", *extra_group_cols]
    rows: list[dict[str, object]] = []
    for keys, group in data.groupby(group_cols, sort=True, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        base = dict(zip(group_cols, keys))
        for wind_col, wind_label in WIND_METRICS.items():
            for flow_col, flow_label in FLOW_METRICS.items():
                rows.append(
                    {
                        **base,
                        "granularity": granularity,
                        "wind_metric": wind_col,
                        "wind_metric_label": wind_label,
                        "flow_metric": flow_col,
                        "flow_metric_label": flow_label,
                        **correlation_values(group, wind_col, flow_col, min_observations),
                    }
                )
    return pd.DataFrame(rows)


def build_lag_correlation_table(
    joined: pd.DataFrame,
    min_observations: int,
    lag_hours: Iterable[float] = (-24, -12, -6, -3, 0, 3, 6, 12, 24),
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for (interconnector_id, interconnector_name), group in joined.groupby(
        ["interconnectorId", "interconnectorName"], sort=True
    ):
        group = group.sort_values("startTime").reset_index(drop=True)
        for wind_col, wind_label in WIND_METRICS.items():
            for lag_hour in lag_hours:
                lag_periods = int(round(lag_hour / HH_HOURS))
                work = group[["signed_mw", wind_col]].copy()
                work["lagged_wind_mw"] = work[wind_col].shift(lag_periods)
                values = correlation_values(work, "lagged_wind_mw", "signed_mw", min_observations)
                rows.append(
                    {
                        "interconnectorId": interconnector_id,
                        "interconnectorName": interconnector_name,
                        "wind_metric": wind_col,
                        "wind_metric_label": wind_label,
                        "flow_metric": "signed_mw",
                        "flow_metric_label": FLOW_METRICS["signed_mw"],
                        "wind_lag_hours": lag_hour,
                        "lag_interpretation": (
                            "positive means wind leads interconnector position"
                            if lag_hour > 0
                            else "negative means wind follows interconnector position"
                            if lag_hour < 0
                            else "same half-hour"
                        ),
                        **values,
                    }
                )
    return pd.DataFrame(rows)


def assign_wind_buckets(wind: pd.DataFrame, wind_col: str) -> pd.DataFrame:
    out = wind[["startTime", wind_col]].copy()
    rank = out[wind_col].rank(method="first")
    out["wind_bucket"] = pd.qcut(rank, q=5, labels=WIND_BUCKET_LABELS)
    return out[["startTime", "wind_bucket"]]


def build_wind_bucket_summary(joined: pd.DataFrame, wind: pd.DataFrame, deadband_mw: float) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for wind_col, wind_label in WIND_METRICS.items():
        bucketed = joined.merge(assign_wind_buckets(wind, wind_col), on="startTime", how="left")
        grouped = (
            bucketed.groupby(["interconnectorId", "interconnectorName", "wind_bucket"], observed=False, sort=True)
            .agg(
                observations=("signed_mw", "size"),
                mean_wind_mw=(wind_col, "mean"),
                min_wind_mw=(wind_col, "min"),
                max_wind_mw=(wind_col, "max"),
                mean_signed_mw=("signed_mw", "mean"),
                median_signed_mw=("signed_mw", "median"),
                mean_import_mw=("import_mw", "mean"),
                mean_export_mw=("export_mw", "mean"),
                net_gwh=("net_gwh", "sum"),
                import_half_hours=("signed_mw", lambda s: (s > deadband_mw).sum()),
                export_half_hours=("signed_mw", lambda s: (s < -deadband_mw).sum()),
                near_zero_half_hours=("signed_mw", lambda s: (s.abs() <= deadband_mw).sum()),
            )
            .reset_index()
        )
        grouped["wind_metric"] = wind_col
        grouped["wind_metric_label"] = wind_label
        grouped["import_share_pct"] = grouped["import_half_hours"] / grouped["observations"] * 100.0
        grouped["export_share_pct"] = grouped["export_half_hours"] / grouped["observations"] * 100.0
        grouped["near_zero_share_pct"] = grouped["near_zero_half_hours"] / grouped["observations"] * 100.0
        rows.append(grouped)

    out = pd.concat(rows, ignore_index=True)
    out["wind_bucket"] = out["wind_bucket"].astype(str)
    return out[
        [
            "wind_metric",
            "wind_metric_label",
            "interconnectorId",
            "interconnectorName",
            "wind_bucket",
            "observations",
            "mean_wind_mw",
            "min_wind_mw",
            "max_wind_mw",
            "mean_signed_mw",
            "median_signed_mw",
            "mean_import_mw",
            "mean_export_mw",
            "net_gwh",
            "import_half_hours",
            "export_half_hours",
            "near_zero_half_hours",
            "import_share_pct",
            "export_share_pct",
            "near_zero_share_pct",
        ]
    ]


def format_num(value: object, digits: int = 0) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value):,.{digits}f}"


def format_corr(value: object) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value):+.2f}"


def format_pct(value: object) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value):.1f}%"


def metric_label(metric: str) -> str:
    return WIND_METRICS.get(metric, metric)


def flow_label(metric: str) -> str:
    return FLOW_METRICS.get(metric, metric)


def write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def write_run_config(
    path: Path,
    args: argparse.Namespace,
    requested_start: pd.Timestamp,
    requested_end: pd.Timestamp,
    joined: pd.DataFrame,
    wind: pd.DataFrame,
    source_summary: pd.DataFrame,
) -> None:
    config = pd.DataFrame(
        [
            ("requested_analysis_start", requested_start),
            ("requested_analysis_end", requested_end),
            ("overlap_start", joined["startTime"].min()),
            ("overlap_end", joined["startTime"].max()),
            ("wind_first_startTime", wind["startTime"].min()),
            ("wind_last_startTime", wind["startTime"].max()),
            ("positive_interconnector_direction", args.positive_direction),
            ("deadband_mw", args.deadband_mw),
            ("wind_settlement_dir", args.wind_settlement_dir),
            ("interconnector_data_dir", args.interconnector_data_dir),
            ("wind_source_files", source_summary["bm_unit_id"].nunique()),
            ("wind_source_rows_in_requested_window", int(source_summary["rows_in_requested_window"].sum())),
            ("joined_half_hour_rows", len(joined)),
            ("joined_timestamps", joined["startTime"].nunique()),
        ],
        columns=["key", "value"],
    )
    write_csv(config, path)


def write_plotly_figure(fig: object, html_path: Path) -> None:
    html_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fig.write_html(html_path, include_plotlyjs="directory")
    except Exception as exc:  # pragma: no cover - only relevant when plotly IO fails
        print(f"Could not write {html_path}: {exc}")
        return

    png_path = html_path.with_suffix(".png")
    try:
        fig.write_image(png_path, scale=2)
    except Exception:
        pass


def plotly_layout(fig: object, title: str, height: int = 520) -> None:
    fig.update_layout(
        title=title,
        template="plotly_white",
        height=height,
        margin={"l": 70, "r": 40, "t": 80, "b": 70},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0},
    )


def generate_figures(
    output_dir: Path,
    daily: pd.DataFrame,
    correlation_summary: pd.DataFrame,
    bucket_summary: pd.DataFrame,
) -> None:
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except Exception as exc:
        print(f"Plotly is not available ({exc}). Skipping figures.")
        return

    figure_dir = output_dir / "figures"
    fleet_daily = daily[daily["interconnectorId"] == "TOTAL_GB_INTERCONNECTORS"].sort_values("date")

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_scatter(
        x=fleet_daily["date"],
        y=fleet_daily["wind_actual_mw"],
        mode="lines",
        name="Actual wind MW",
        line={"color": "#2f6db2", "width": 1.4},
        secondary_y=False,
    )
    fig.add_scatter(
        x=fleet_daily["date"],
        y=fleet_daily["wind_before_curtailment_mw"],
        mode="lines",
        name="Before curtailment MW",
        line={"color": "#6aa84f", "width": 1.2},
        secondary_y=False,
    )
    fig.add_scatter(
        x=fleet_daily["date"],
        y=fleet_daily["signed_mw"],
        mode="lines",
        name="Fleet interconnector signed MW",
        line={"color": "#222222", "width": 1.2},
        secondary_y=True,
    )
    plotly_layout(fig, "Fleet Daily Wind Output and Interconnector Position", height=560)
    fig.update_yaxes(title_text="Wind MW", secondary_y=False)
    fig.update_yaxes(title_text="Interconnector signed MW", secondary_y=True)
    write_plotly_figure(fig, figure_dir / "fleet_daily_wind_and_interconnector_position.html")

    season_colors = {"Winter": "#4b83c3", "Spring": "#5ba36b", "Summer": "#d7a92b", "Autumn": "#b35b45"}
    for wind_col, wind_name in WIND_METRICS.items():
        fig = go.Figure()
        for season in SEASON_ORDER:
            data = fleet_daily[fleet_daily["season"] == season]
            fig.add_scatter(
                x=data[wind_col],
                y=data["signed_mw"],
                mode="markers",
                name=season,
                marker={"color": season_colors.get(season), "size": 6, "opacity": 0.55},
                text=data["date"].dt.strftime("%Y-%m-%d"),
                hovertemplate="%{text}<br>Wind: %{x:,.0f} MW<br>IC: %{y:,.0f} MW<extra></extra>",
            )

        pairs = fleet_daily[[wind_col, "signed_mw"]].dropna()
        if len(pairs) >= 2 and pairs[wind_col].nunique() >= 2:
            x_min, x_max = pairs[wind_col].min(), pairs[wind_col].max()
            slope, intercept = np.polyfit(pairs[wind_col], pairs["signed_mw"], 1)
            x_line = np.array([x_min, x_max])
            fig.add_scatter(
                x=x_line,
                y=slope * x_line + intercept,
                mode="lines",
                name="OLS line",
                line={"color": "#111111", "width": 2},
            )

        plotly_layout(fig, f"Fleet Daily Signed Interconnector Position vs {wind_name}", height=560)
        fig.update_xaxes(title_text=wind_name + " (MW)")
        fig.update_yaxes(title_text="Interconnector signed MW (import positive, export negative)")
        write_plotly_figure(fig, figure_dir / f"fleet_daily_scatter_{wind_col}.html")

    daily_signed = correlation_summary[
        (correlation_summary["granularity"] == "daily")
        & (correlation_summary["flow_metric"] == "signed_mw")
    ].copy()
    daily_signed["wind_metric_label_short"] = daily_signed["wind_metric"].map(
        {
            "wind_actual_mw": "Actual",
            "wind_before_curtailment_mw": "Before curtailment",
        }
    )
    pivot = daily_signed.pivot_table(
        index="interconnectorId",
        columns="wind_metric_label_short",
        values="pearson_corr",
        aggfunc="first",
    )
    ordered_ids = [idx for idx in pivot.index if idx != "TOTAL_GB_INTERCONNECTORS"] + [
        idx for idx in pivot.index if idx == "TOTAL_GB_INTERCONNECTORS"
    ]
    pivot = pivot.reindex(ordered_ids)
    fig = go.Figure(
        go.Heatmap(
            z=pivot.to_numpy(dtype=float),
            x=list(pivot.columns),
            y=list(pivot.index),
            colorscale="RdBu",
            zmid=0,
            text=np.round(pivot.to_numpy(dtype=float), 2),
            texttemplate="%{text}",
            colorbar={"title": "Pearson r"},
        )
    )
    plotly_layout(fig, "Daily Correlation: Wind Output vs Signed Interconnector Position", height=620)
    fig.update_xaxes(title_text="")
    fig.update_yaxes(title_text="")
    write_plotly_figure(fig, figure_dir / "daily_signed_correlation_heatmap.html")

    before_buckets = bucket_summary[
        bucket_summary["wind_metric"].eq("wind_before_curtailment_mw")
    ].copy()
    pivot = before_buckets.pivot_table(
        index="interconnectorId",
        columns="wind_bucket",
        values="mean_signed_mw",
        aggfunc="first",
    )
    pivot = pivot.reindex(index=ordered_ids, columns=WIND_BUCKET_LABELS)
    fig = go.Figure(
        go.Heatmap(
            z=pivot.to_numpy(dtype=float),
            x=WIND_BUCKET_LABELS,
            y=list(pivot.index),
            colorscale="RdBu",
            zmid=0,
            colorbar={"title": "Mean signed MW"},
        )
    )
    plotly_layout(fig, "Mean Interconnector Position by Pre-Curtailment Wind Quintile", height=650)
    fig.update_xaxes(title_text="Wind output bucket")
    fig.update_yaxes(title_text="")
    write_plotly_figure(fig, figure_dir / "position_by_before_curtailment_wind_bucket.html")


def best_row(
    table: pd.DataFrame,
    interconnector_id: str,
    wind_metric: str,
    flow_metric: str,
    granularity: str,
) -> pd.Series | None:
    rows = table[
        (table["interconnectorId"] == interconnector_id)
        & (table["wind_metric"] == wind_metric)
        & (table["flow_metric"] == flow_metric)
        & (table["granularity"] == granularity)
    ]
    if rows.empty:
        return None
    return rows.iloc[0]


def write_story(
    output_dir: Path,
    requested_start: pd.Timestamp,
    requested_end: pd.Timestamp,
    joined: pd.DataFrame,
    daily: pd.DataFrame,
    correlation_summary: pd.DataFrame,
    correlation_by_season: pd.DataFrame,
    bucket_summary: pd.DataFrame,
    lag_summary: pd.DataFrame,
) -> None:
    fleet_actual = best_row(correlation_summary, "TOTAL_GB_INTERCONNECTORS", "wind_actual_mw", "signed_mw", "daily")
    fleet_before = best_row(
        correlation_summary,
        "TOTAL_GB_INTERCONNECTORS",
        "wind_before_curtailment_mw",
        "signed_mw",
        "daily",
    )

    signed_daily = correlation_summary[
        (correlation_summary["granularity"] == "daily")
        & (correlation_summary["flow_metric"] == "signed_mw")
        & (correlation_summary["interconnectorId"] != "TOTAL_GB_INTERCONNECTORS")
        & (correlation_summary["wind_metric"] == "wind_before_curtailment_mw")
    ].dropna(subset=["pearson_corr"])

    strongest_export = signed_daily.sort_values("pearson_corr").head(3)
    strongest_import = signed_daily.sort_values("pearson_corr", ascending=False).head(3)

    fleet_buckets = bucket_summary[
        (bucket_summary["interconnectorId"] == "TOTAL_GB_INTERCONNECTORS")
        & (bucket_summary["wind_metric"] == "wind_before_curtailment_mw")
    ].copy()
    low_bucket = fleet_buckets[fleet_buckets["wind_bucket"] == "lowest_20pct"]
    high_bucket = fleet_buckets[fleet_buckets["wind_bucket"] == "highest_20pct"]
    low = low_bucket.iloc[0] if not low_bucket.empty else None
    high = high_bucket.iloc[0] if not high_bucket.empty else None

    fleet_seasons = correlation_by_season[
        (correlation_by_season["interconnectorId"] == "TOTAL_GB_INTERCONNECTORS")
        & (correlation_by_season["wind_metric"] == "wind_before_curtailment_mw")
        & (correlation_by_season["flow_metric"] == "signed_mw")
    ].copy()
    fleet_seasons["season"] = pd.Categorical(fleet_seasons["season"], categories=SEASON_ORDER, ordered=True)
    fleet_seasons = fleet_seasons.sort_values("season")

    fleet_lags = lag_summary[
        (lag_summary["interconnectorId"] == "TOTAL_GB_INTERCONNECTORS")
        & (lag_summary["wind_metric"] == "wind_before_curtailment_mw")
    ].dropna(subset=["pearson_corr"])
    strongest_lag = None
    if not fleet_lags.empty:
        strongest_lag = fleet_lags.iloc[fleet_lags["pearson_corr"].abs().argmax()]

    lines = [
        "# Wind and Interconnector Correlation Pack",
        "",
        "## Scope and conventions",
        "",
        f"- Requested interconnector window: {requested_start} to {requested_end}.",
        f"- Actual overlapping wind/interconnector window used in correlations: {joined['startTime'].min()} to {joined['startTime'].max()}.",
        "- Wind actual output is the BMU `metered` series converted from half-hour MWh to average MW.",
        "- Wind before curtailment uses `metered - BAV`, matching the previous `metered_minus_bav` workflow.",
        "- Wind `halfHourEndTime` is shifted back 30 minutes before joining to interconnector `startTime`.",
        "- Positive interconnector signed MW means GB import; negative means GB export.",
        "- A negative correlation with signed MW means higher wind tends to coincide with more export or less import.",
        "",
        "## Fleet headline",
        "",
    ]

    if fleet_actual is not None and fleet_before is not None:
        lines.extend(
            [
                f"- Daily fleet correlation with actual wind output: r={format_corr(fleet_actual['pearson_corr'])} using {int(fleet_actual['observations'])} daily observations.",
                f"- Daily fleet correlation with pre-curtailment wind proxy: r={format_corr(fleet_before['pearson_corr'])} using {int(fleet_before['observations'])} daily observations.",
            ]
        )

    if low is not None and high is not None:
        delta = high["mean_signed_mw"] - low["mean_signed_mw"]
        lines.extend(
            [
                f"- In the lowest pre-curtailment wind quintile, fleet position averaged {format_num(low['mean_signed_mw'])} MW with import share {format_pct(low['import_share_pct'])}.",
                f"- In the highest pre-curtailment wind quintile, fleet position averaged {format_num(high['mean_signed_mw'])} MW with export share {format_pct(high['export_share_pct'])}.",
                f"- High-wind fleet position is {format_num(delta)} MW lower than low-wind position on the signed import-positive scale.",
            ]
        )

    if strongest_lag is not None:
        lines.append(
            f"- Strongest tested fleet lag correlation is at {format_num(strongest_lag['wind_lag_hours'], 1)} hours "
            f"(r={format_corr(strongest_lag['pearson_corr'])}); positive lag means wind leads interconnector position."
        )

    lines.extend(["", "## Interconnector differences", ""])
    if not strongest_export.empty:
        lines.append("Links most export-aligned with high pre-curtailment wind on a daily signed-MW basis:")
        for _, row in strongest_export.iterrows():
            lines.append(f"- {row['interconnectorId']}: r={format_corr(row['pearson_corr'])}, mean signed {format_num(row['flow_mean_mw'])} MW.")
    if not strongest_import.empty:
        lines.append("")
        lines.append("Links most import-aligned with high pre-curtailment wind on a daily signed-MW basis:")
        for _, row in strongest_import.iterrows():
            lines.append(f"- {row['interconnectorId']}: r={format_corr(row['pearson_corr'])}, mean signed {format_num(row['flow_mean_mw'])} MW.")

    lines.extend(["", "## Seasonal signal", ""])
    if fleet_seasons.empty:
        lines.append("- No seasonal fleet correlations could be calculated.")
    else:
        for _, row in fleet_seasons.iterrows():
            lines.append(
                f"- {row['season']}: daily fleet signed-MW correlation with pre-curtailment wind is "
                f"r={format_corr(row['pearson_corr'])} across {int(row['observations'])} observations."
            )

    latest_daily = daily[daily["interconnectorId"] == "TOTAL_GB_INTERCONNECTORS"]
    lines.extend(
        [
            "",
            "## Recommended exhibits",
            "",
            "- `figures/fleet_daily_wind_and_interconnector_position.html` - time-series context for wind and fleet BM position.",
            "- `figures/fleet_daily_scatter_wind_actual_mw.html` and `figures/fleet_daily_scatter_wind_before_curtailment_mw.html` - direct daily relationship against each wind metric.",
            "- `figures/daily_signed_correlation_heatmap.html` - interconnector-by-interconnector comparison of daily signed-MW correlations.",
            "- `figures/position_by_before_curtailment_wind_bucket.html` - how each link behaves from low-wind to high-wind conditions.",
            "",
            "## Output tables",
            "",
            "- `wind_half_hourly_timeseries.csv` - aggregate wind actual and before-curtailment proxy in MWh and MW.",
            "- `interconnector_wind_join_half_hourly_long.csv` - joined half-hourly data by interconnector and fleet.",
            "- `interconnector_wind_join_half_hourly_wide.csv` - one row per timestamp with wind and signed-MW columns.",
            "- `interconnector_wind_join_daily.csv` and `interconnector_wind_join_monthly.csv` - daily/monthly analysis tables.",
            "- `correlation_summary.csv` - half-hourly, daily, and monthly correlations for actual and before-curtailment wind.",
            "- `correlation_by_season.csv` and `correlation_by_month_of_year.csv` - daily correlations by seasonal slices.",
            "- `wind_level_bucket_summary.csv` - import/export levels and shares by wind quintile.",
            "- `lag_correlation_summary.csv` - tested lag correlations for signed-MW position.",
            "",
            "## Coverage note",
            "",
            f"- Fleet daily rows available for the joined period: {len(latest_daily):,}.",
            "- The wind settlement input currently determines the end of the joined window. Refresh the wind BMU settlement folder to extend the analysis past that date.",
        ]
    )

    (output_dir / "story.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    metadata = read_metadata(args.metadata)
    raw_interconnectors = read_interconnector_data(args.interconnector_data_dir, metadata, args.positive_direction)
    requested_start, requested_end, _run_config = resolve_window(args, raw_interconnectors)
    interconnectors = filter_window(raw_interconnectors, requested_start, requested_end)
    if interconnectors.empty:
        raise ValueError(f"No interconnector rows overlapped {requested_start} to {requested_end}")

    fleet = build_fleet_interconnector(interconnectors)
    combined_interconnectors = pd.concat([interconnectors, fleet], ignore_index=True, sort=False)

    print(f"Aggregating wind BMU settlement data from {args.wind_settlement_dir}...")
    wind, wind_source_summary = aggregate_wind_settlement(args.wind_settlement_dir, requested_start, requested_end)
    print(f"Wind timestamps in requested window: {len(wind):,}")

    joined = join_wind_and_interconnectors(combined_interconnectors, wind, args.deadband_mw)
    if joined.empty:
        raise ValueError("No overlapping half-hours between wind and interconnector data.")

    wide = build_wide_join(joined)
    daily = aggregate_joined(joined, "daily", args.deadband_mw)
    monthly = aggregate_joined(joined, "monthly", args.deadband_mw)

    correlation_summary = pd.concat(
        [
            build_correlation_table(joined, "half_hourly", args.min_correlation_observations),
            build_correlation_table(daily, "daily", max(10, math.ceil(args.min_correlation_observations / 48))),
            build_correlation_table(monthly, "monthly", 6),
        ],
        ignore_index=True,
    )
    correlation_by_season = build_correlation_table(daily, "daily", 10, extra_group_cols=["season"])
    correlation_by_month = build_correlation_table(daily, "daily", 10, extra_group_cols=["month", "month_name"])
    wind_bucket_summary = build_wind_bucket_summary(joined, wind, args.deadband_mw)
    lag_summary = build_lag_correlation_table(joined, args.min_correlation_observations)

    write_csv(wind, args.output_dir / "wind_half_hourly_timeseries.csv")
    write_csv(wind_source_summary, args.output_dir / "wind_source_summary.csv")
    write_csv(joined, args.output_dir / "interconnector_wind_join_half_hourly_long.csv")
    write_csv(wide, args.output_dir / "interconnector_wind_join_half_hourly_wide.csv")
    write_csv(daily, args.output_dir / "interconnector_wind_join_daily.csv")
    write_csv(monthly, args.output_dir / "interconnector_wind_join_monthly.csv")
    write_csv(correlation_summary, args.output_dir / "correlation_summary.csv")
    write_csv(correlation_by_season, args.output_dir / "correlation_by_season.csv")
    write_csv(correlation_by_month, args.output_dir / "correlation_by_month_of_year.csv")
    write_csv(wind_bucket_summary, args.output_dir / "wind_level_bucket_summary.csv")
    write_csv(lag_summary, args.output_dir / "lag_correlation_summary.csv")
    write_run_config(
        args.output_dir / "run_config.csv",
        args,
        requested_start,
        requested_end,
        joined,
        wind,
        wind_source_summary,
    )

    write_story(
        args.output_dir,
        requested_start,
        requested_end,
        joined,
        daily,
        correlation_summary,
        correlation_by_season,
        wind_bucket_summary,
        lag_summary,
    )

    if not args.no_figures:
        generate_figures(args.output_dir, daily, correlation_summary, wind_bucket_summary)

    print(f"Written wind/interconnector correlation pack to {args.output_dir}")
    print(
        textwrap.dedent(
            f"""
            Overlap used: {joined['startTime'].min()} to {joined['startTime'].max()}
            Joined half-hour rows: {len(joined):,}
            Unique joined timestamps: {joined['startTime'].nunique():,}
            """
        ).strip()
    )


if __name__ == "__main__":
    main()
