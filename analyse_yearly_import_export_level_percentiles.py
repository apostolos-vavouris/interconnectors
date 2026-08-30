"""Analyse year-specific import and export level distributions.

This script calculates conditional import/export percentiles for each
interconnector and for the aggregate GB interconnector fleet total. Import
percentiles use only half-hours where the selected series is importing; export
percentiles use only half-hours where it is exporting, with export reported as a
positive MW magnitude.
"""

from __future__ import annotations

import argparse
import textwrap
from pathlib import Path

import numpy as np
import pandas as pd

from analyse_bm_interconnector_history import (
    add_calendar_fields,
    add_capacity_fields,
    build_capacity_reference,
    build_fleet_half_hourly,
    format_num,
    format_pct,
    normalise_timestamp,
    read_half_hourly_data,
    read_metadata,
    write_csv,
)


PERCENTILES = [0, 5, 10, 20, 30, 40, 50, 60, 70, 75, 85, 90, 95, 100]
PERCENTILE_COLUMNS = [f"P{percentile}" for percentile in PERCENTILES]
FLEET_ID = "TOTAL_GB_INTERCONNECTORS"
FLEET_NAME = "GB interconnector fleet total"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Calculate selected-year conditional import/export level "
            "percentiles for GB interconnectors and the aggregate fleet."
        )
    )
    period = parser.add_mutually_exclusive_group(required=True)
    period.add_argument("--year", type=int, default=None, help="Calendar year to analyse, e.g. 2025.")
    period.add_argument(
        "--all-data",
        action="store_true",
        help="Analyse the full available half-hourly data window instead of a single calendar year.",
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
        help="Interconnector metadata CSV.",
    )
    parser.add_argument(
        "--capacity-file",
        type=Path,
        default=Path("interconnector_capacities.csv"),
        help="Optional capacity reference CSV. If absent, observed peak MW is used.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("analysis_outputs") / "import_export_level_distributions",
        help="Output folder for CSVs, plots, and narrative.",
    )
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
        help="Absolute MW threshold treated as near-zero when selecting import/export half-hours.",
    )
    parser.add_argument(
        "--pdf-bin-width-mw",
        type=float,
        default=100.0,
        help="MW bin width for probability-density distribution plots and CSVs.",
    )
    parser.add_argument(
        "--include-combined-pdf-figures",
        action="store_true",
        help="Also write the old all-series PDF-style overlays. By default the script writes one PDF-style plot per interconnector/fleet series.",
    )
    parser.add_argument("--no-figures", action="store_true", help="Skip distribution plots.")
    return parser.parse_args()


def year_window(year: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    return (
        normalise_timestamp(f"{year}-01-01T00:00Z"),
        normalise_timestamp(f"{year}-12-31T23:30Z"),
    )


def period_labels(args: argparse.Namespace) -> tuple[str, str]:
    if args.all_data:
        return "all_data", "All Available Data"
    return str(args.year), str(args.year)


def ordered_series_ids(df: pd.DataFrame) -> list[str]:
    physical = sorted(interconnector_id for interconnector_id in df["interconnectorId"].dropna().unique() if interconnector_id != FLEET_ID)
    return [FLEET_ID] + physical


def series_sort_key(interconnector_id: str) -> tuple[int, str]:
    return (0, "") if interconnector_id == FLEET_ID else (1, interconnector_id)


def build_analysis_series(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]:
    metadata = read_metadata(args.metadata)
    data = read_half_hourly_data(args.interconnector_data_dir, metadata, args.positive_direction)
    available_start = data["startTime"].min()
    available_end = data["startTime"].max()
    if args.all_data:
        requested_start, requested_end = available_start, available_end
    else:
        requested_start, requested_end = year_window(args.year)

    analysis_start = max(requested_start, available_start)
    analysis_end = min(requested_end, available_end)
    if analysis_start > analysis_end:
        period_label, _ = period_labels(args)
        raise ValueError(
            f"No interconnector data overlaps {period_label}. "
            f"Available half-hourly data runs from {available_start} to {available_end}."
        )

    data = data[(data["startTime"] >= analysis_start) & (data["startTime"] <= analysis_end)].copy()
    if data.empty:
        period_label, _ = period_labels(args)
        raise ValueError(f"No interconnector rows found in the selected window for {period_label}.")

    capacity_reference = build_capacity_reference(data, args.capacity_file)
    data = add_calendar_fields(data, args.deadband_mw)
    data = add_capacity_fields(data, capacity_reference)
    data["aggregation_level"] = "interconnector"

    metadata_cols = [col for col in ["StartedOperations"] if col in data.columns]
    fleet = build_fleet_half_hourly(data, analysis_start, analysis_end, metadata_cols)
    fleet = fleet[fleet["available_interconnector_count"] > 0].copy()
    fleet = add_calendar_fields(fleet, args.deadband_mw)
    fleet = add_capacity_fields(fleet, capacity_reference)
    fleet["aggregation_level"] = "fleet_total"

    combined = pd.concat([fleet, data], ignore_index=True, sort=False)
    combined = combined.sort_values(["aggregation_level", "interconnectorId", "startTime"]).reset_index(drop=True)
    return combined, requested_start, requested_end, analysis_start, analysis_end


def build_direction_sample_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for keys, group in df.groupby(["aggregation_level", "interconnectorId", "interconnectorName"], dropna=False, sort=False):
        aggregation_level, interconnector_id, interconnector_name = keys
        observations = int(len(group))
        import_mask = group["direction_state"].eq("import")
        export_mask = group["direction_state"].eq("export")
        near_zero_mask = group["direction_state"].eq("near_zero")
        import_observations = int(import_mask.sum())
        export_observations = int(export_mask.sum())
        near_zero_observations = int(near_zero_mask.sum())
        rows.append(
            {
                "aggregation_level": aggregation_level,
                "interconnectorId": interconnector_id,
                "interconnectorName": interconnector_name,
                "first_timestamp": group["startTime"].min(),
                "last_timestamp": group["startTime"].max(),
                "operational_observations": observations,
                "operational_hours": observations * 0.5,
                "import_observations": import_observations,
                "export_observations": export_observations,
                "near_zero_observations": near_zero_observations,
                "import_share_pct": import_observations / observations * 100.0 if observations else np.nan,
                "export_share_pct": export_observations / observations * 100.0 if observations else np.nan,
                "near_zero_share_pct": near_zero_observations / observations * 100.0 if observations else np.nan,
                "mean_signed_mw": group["signed_mw"].mean(),
                "mean_import_mw_all_half_hours": group["import_mw"].mean(),
                "mean_export_mw_all_half_hours": group["export_mw"].mean(),
                "mean_import_mw_when_importing": group.loc[import_mask, "import_mw"].mean(),
                "mean_export_mw_when_exporting": group.loc[export_mask, "export_mw"].mean(),
                "max_import_mw": group["import_mw"].max(),
                "max_export_mw": group["export_mw"].max(),
                "mean_capacity_mw": group["capacity_mw"].mean() if "capacity_mw" in group.columns else np.nan,
                "mean_active_capacity_mw": group["active_capacity_mw"].mean() if "active_capacity_mw" in group.columns else np.nan,
                "mean_available_interconnector_count": group["available_interconnector_count"].mean()
                if "available_interconnector_count" in group.columns
                else np.nan,
            }
        )

    out = pd.DataFrame(rows)
    out["sort_group"] = out["interconnectorId"].map(lambda value: series_sort_key(str(value))[0])
    out["sort_id"] = out["interconnectorId"].astype(str)
    return out.sort_values(["sort_group", "sort_id"]).drop(columns=["sort_group", "sort_id"]).reset_index(drop=True)


def percentile_level(values: pd.Series, percentile: int) -> float:
    values = values.dropna()
    if values.empty:
        return np.nan
    return float(np.percentile(values.to_numpy(dtype=float), percentile))


def build_percentile_tables(df: pd.DataFrame, period_label: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    for keys, group in df.groupby(["aggregation_level", "interconnectorId", "interconnectorName"], dropna=False, sort=False):
        aggregation_level, interconnector_id, interconnector_name = keys
        operational_observations = int(len(group))
        for direction, metric, level_label in [
            ("import", "import_mw", "import_mw_conditional_on_importing"),
            ("export", "export_mw", "export_mw_positive_magnitude_conditional_on_exporting"),
        ]:
            values = group.loc[group["direction_state"].eq(direction), metric]
            direction_observations = int(values.notna().sum())
            direction_share = direction_observations / operational_observations * 100.0 if operational_observations else np.nan
            for percentile in PERCENTILES:
                rows.append(
                    {
                        "analysis_period": period_label,
                        "aggregation_level": aggregation_level,
                        "interconnectorId": interconnector_id,
                        "interconnectorName": interconnector_name,
                        "direction": direction,
                        "level_metric": level_label,
                        "percentile": percentile,
                        "percentile_label": f"P{percentile}",
                        "level_mw": percentile_level(values, percentile),
                        "direction_observations": direction_observations,
                        "direction_duration_hours": direction_observations * 0.5,
                        "direction_share_of_operational_half_hours_pct": direction_share,
                        "operational_observations": operational_observations,
                        "first_timestamp": group["startTime"].min(),
                        "last_timestamp": group["startTime"].max(),
                    }
                )

    long = pd.DataFrame(rows)
    long["series_sort_group"] = long["interconnectorId"].map(lambda value: series_sort_key(str(value))[0])
    long["series_sort_id"] = long["interconnectorId"].astype(str)
    long = long.sort_values(["series_sort_group", "series_sort_id", "direction", "percentile"]).drop(
        columns=["series_sort_group", "series_sort_id"]
    )
    long = long.reset_index(drop=True)

    index_cols = [
        "analysis_period",
        "aggregation_level",
        "interconnectorId",
        "interconnectorName",
        "direction",
        "level_metric",
        "direction_observations",
        "direction_duration_hours",
        "direction_share_of_operational_half_hours_pct",
        "operational_observations",
        "first_timestamp",
        "last_timestamp",
    ]
    wide = long.pivot_table(index=index_cols, columns="percentile_label", values="level_mw", aggfunc="first").reset_index()
    for column in PERCENTILE_COLUMNS:
        if column not in wide.columns:
            wide[column] = np.nan
    wide["series_sort_group"] = wide["interconnectorId"].map(lambda value: series_sort_key(str(value))[0])
    wide["series_sort_id"] = wide["interconnectorId"].astype(str)
    wide["direction_sort"] = wide["direction"].map({"import": 0, "export": 1}).fillna(2)
    wide = wide.sort_values(["series_sort_group", "series_sort_id", "direction_sort"])
    return (
        long,
        wide[index_cols + PERCENTILE_COLUMNS].reset_index(drop=True),
    )


def build_pdf_bin_table(df: pd.DataFrame, period_label: str, bin_width_mw: float) -> pd.DataFrame:
    if bin_width_mw <= 0:
        raise ValueError("--pdf-bin-width-mw must be greater than zero.")

    rows = []
    for keys, group in df.groupby(["aggregation_level", "interconnectorId", "interconnectorName"], dropna=False, sort=False):
        aggregation_level, interconnector_id, interconnector_name = keys
        for direction, metric, level_label in [
            ("import", "import_mw", "import_mw_conditional_on_importing"),
            ("export", "export_mw", "export_mw_positive_magnitude_conditional_on_exporting"),
        ]:
            values = group.loc[group["direction_state"].eq(direction), metric].dropna().to_numpy(dtype=float)
            if values.size == 0:
                continue

            max_level = max(bin_width_mw, np.ceil(values.max() / bin_width_mw) * bin_width_mw)
            bin_edges = np.arange(0, max_level + bin_width_mw, bin_width_mw)
            if bin_edges[-1] < max_level:
                bin_edges = np.append(bin_edges, max_level)
            counts, edges = np.histogram(values, bins=bin_edges)
            cumulative = np.cumsum(counts) / values.size

            for idx, count in enumerate(counts):
                lower = float(edges[idx])
                upper = float(edges[idx + 1])
                width = upper - lower
                probability = count / values.size if values.size else np.nan
                rows.append(
                    {
                        "analysis_period": period_label,
                        "aggregation_level": aggregation_level,
                        "interconnectorId": interconnector_id,
                        "interconnectorName": interconnector_name,
                        "direction": direction,
                        "level_metric": level_label,
                        "bin_width_mw": width,
                        "bin_lower_mw": lower,
                        "bin_upper_mw": upper,
                        "bin_midpoint_mw": lower + width / 2.0,
                        "bin_observations": int(count),
                        "direction_observations": int(values.size),
                        "probability": probability,
                        "probability_pct": probability * 100.0,
                        "probability_density_per_mw": probability / width if width else np.nan,
                        "cumulative_probability": float(cumulative[idx]),
                        "cumulative_probability_pct": float(cumulative[idx] * 100.0),
                    }
                )

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["series_sort_group"] = out["interconnectorId"].map(lambda value: series_sort_key(str(value))[0])
    out["series_sort_id"] = out["interconnectorId"].astype(str)
    out["direction_sort"] = out["direction"].map({"import": 0, "export": 1}).fillna(2)
    return (
        out.sort_values(["series_sort_group", "series_sort_id", "direction_sort", "bin_lower_mw"])
        .drop(columns=["series_sort_group", "series_sort_id", "direction_sort"])
        .reset_index(drop=True)
    )


def require_plotly():
    try:
        import plotly.graph_objects as go
    except ImportError as exc:
        raise RuntimeError("Plotly is required for figures. Rerun with --no-figures or install plotly.") from exc
    return go


def write_plot_image_if_available(fig, path: Path) -> None:
    try:
        fig.write_image(path)
    except Exception:
        return


def write_matplotlib_distribution_png(figure_data: pd.DataFrame, direction: str, path: Path, period_title: str) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return

    colors = [
        "#2f6db2",
        "#c43c39",
        "#3a8f5a",
        "#9b6bdb",
        "#c8792d",
        "#6b8796",
        "#d25f91",
        "#5d7562",
        "#b5a642",
        "#4b9ca6",
    ]
    fig, ax = plt.subplots(figsize=(13, 7.5))
    for idx, interconnector_id in enumerate(ordered_series_ids(figure_data)):
        subset = figure_data[figure_data["interconnectorId"].eq(interconnector_id)].sort_values("percentile")
        if subset.empty or subset["level_mw"].isna().all():
            continue
        is_fleet = interconnector_id == FLEET_ID
        label = FLEET_NAME if is_fleet else interconnector_id
        color = "#111111" if is_fleet else colors[idx % len(colors)]
        ax.plot(
            subset["percentile"],
            subset["level_mw"],
            marker="o",
            markersize=4.5 if is_fleet else 3.5,
            linewidth=3.0 if is_fleet else 1.6,
            color=color,
            label=label,
        )

    for percentile in [5, 10, 20]:
        ax.axvline(percentile, color="#9aa1a9", linestyle=":", linewidth=1)
    ax.set_title(f"{period_title} {direction.title()} Level Percentile Distribution")
    ax.set_xlabel("Percentile of directional operating half-hours")
    ylabel = "Import MW, conditional on importing" if direction == "import" else "Export MW positive magnitude, conditional on exporting"
    ax.set_ylabel(ylabel)
    ax.set_xticks(PERCENTILES)
    ax.grid(True, axis="y", color="#d9d9d9", linewidth=0.8)
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=4, frameon=False)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(path, dpi=160)
    plt.close(fig)


def plotly_layout(fig, title: str) -> None:
    fig.update_layout(
        title=title,
        template="plotly_white",
        font={"family": "Arial, sans-serif", "size": 12},
        legend={"orientation": "h", "yanchor": "bottom", "y": -0.22, "xanchor": "center", "x": 0.5},
        margin={"l": 80, "r": 40, "t": 80, "b": 95},
        hovermode="x unified",
    )


def generate_figures(long: pd.DataFrame, output_dir: Path, period_label: str, period_title: str) -> None:
    go = require_plotly()
    figure_dir = output_dir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)

    colors = [
        "#2f6db2",
        "#c43c39",
        "#3a8f5a",
        "#9b6bdb",
        "#c8792d",
        "#6b8796",
        "#d25f91",
        "#5d7562",
        "#b5a642",
        "#4b9ca6",
    ]
    direction_titles = {
        "import": "Import Level Percentile Distribution",
        "export": "Export Level Percentile Distribution",
    }
    yaxis_titles = {
        "import": "Import MW, conditional on importing",
        "export": "Export MW positive magnitude, conditional on exporting",
    }

    for direction in ["import", "export"]:
        figure_data = long[long["direction"].eq(direction)].copy()
        fig = go.Figure()
        for idx, interconnector_id in enumerate(ordered_series_ids(figure_data)):
            subset = figure_data[figure_data["interconnectorId"].eq(interconnector_id)].sort_values("percentile")
            if subset.empty or subset["level_mw"].isna().all():
                continue
            is_fleet = interconnector_id == FLEET_ID
            label = FLEET_NAME if is_fleet else interconnector_id
            color = "#111111" if is_fleet else colors[idx % len(colors)]
            fig.add_trace(
                go.Scatter(
                    x=subset["percentile"],
                    y=subset["level_mw"],
                    mode="lines+markers",
                    name=label,
                    line={"width": 4 if is_fleet else 2, "color": color},
                    marker={"size": 7 if is_fleet else 5},
                    hovertemplate=(
                        "%{fullData.name}<br>"
                        "P%{x}: %{y:,.0f} MW<br>"
                        "Directional half-hours: %{customdata[0]:,.0f}<br>"
                        "Directional share: %{customdata[1]:.1f}%"
                        "<extra></extra>"
                    ),
                    customdata=np.column_stack(
                        [
                            subset["direction_observations"].to_numpy(dtype=float),
                            subset["direction_share_of_operational_half_hours_pct"].to_numpy(dtype=float),
                        ]
                    ),
                )
            )

        for percentile in [5, 10, 20]:
            fig.add_vline(x=percentile, line_dash="dot", line_color="#9aa1a9", line_width=1)
        fig.update_layout(
            xaxis_title="Percentile of directional operating half-hours",
            yaxis_title=yaxis_titles[direction],
            xaxis={"tickmode": "array", "tickvals": PERCENTILES},
            height=720,
        )
        plotly_layout(fig, f"{period_title} {direction_titles[direction]}")
        basename = f"{direction}_level_percentile_distribution_{period_label}"
        fig.write_html(figure_dir / f"{basename}.html", include_plotlyjs="directory")
        write_plot_image_if_available(fig, figure_dir / f"{basename}.png")
        if not (figure_dir / f"{basename}.png").exists():
            write_matplotlib_distribution_png(figure_data, direction, figure_dir / f"{basename}.png", period_title)


def generate_pdf_figures(pdf_bins: pd.DataFrame, output_dir: Path, period_label: str, period_title: str) -> None:
    if pdf_bins.empty:
        return

    go = require_plotly()
    figure_dir = output_dir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)

    colors = [
        "#2f6db2",
        "#c43c39",
        "#3a8f5a",
        "#9b6bdb",
        "#c8792d",
        "#6b8796",
        "#d25f91",
        "#5d7562",
        "#b5a642",
        "#4b9ca6",
    ]
    direction_titles = {
        "import": "Import Level PDF Distribution",
        "export": "Export Level PDF Distribution",
    }
    yaxis_titles = {
        "import": "Share of importing half-hours in MW bin (%)",
        "export": "Share of exporting half-hours in MW bin (%)",
    }

    for direction in ["import", "export"]:
        figure_data = pdf_bins[pdf_bins["direction"].eq(direction)].copy()
        if figure_data.empty:
            continue
        fig = go.Figure()
        for idx, interconnector_id in enumerate(ordered_series_ids(figure_data)):
            subset = figure_data[figure_data["interconnectorId"].eq(interconnector_id)].sort_values("bin_midpoint_mw")
            if subset.empty:
                continue
            is_fleet = interconnector_id == FLEET_ID
            label = FLEET_NAME if is_fleet else interconnector_id
            color = "#111111" if is_fleet else colors[idx % len(colors)]
            fig.add_trace(
                go.Scatter(
                    x=subset["bin_midpoint_mw"],
                    y=subset["probability_pct"],
                    mode="lines",
                    name=label,
                    line={"width": 3.5 if is_fleet else 1.8, "color": color, "shape": "hvh"},
                    opacity=1.0 if is_fleet else 0.82,
                    hovertemplate=(
                        "%{fullData.name}<br>"
                        "%{customdata[0]:,.0f}-%{customdata[1]:,.0f} MW<br>"
                        "Share: %{y:.2f}%<br>"
                        "Bin half-hours: %{customdata[2]:,.0f}<br>"
                        "Density per MW: %{customdata[3]:.6f}"
                        "<extra></extra>"
                    ),
                    customdata=np.column_stack(
                        [
                            subset["bin_lower_mw"].to_numpy(dtype=float),
                            subset["bin_upper_mw"].to_numpy(dtype=float),
                            subset["bin_observations"].to_numpy(dtype=float),
                            subset["probability_density_per_mw"].to_numpy(dtype=float),
                        ]
                    ),
                )
            )

        fig.update_layout(
            xaxis_title="Directional operating level bin midpoint (MW)",
            yaxis_title=yaxis_titles[direction],
            height=720,
        )
        plotly_layout(fig, f"{period_title} {direction_titles[direction]}")
        basename = f"{direction}_level_pdf_distribution_{period_label}"
        fig.write_html(figure_dir / f"{basename}.html", include_plotlyjs="directory")
        write_plot_image_if_available(fig, figure_dir / f"{basename}.png")

        fleet_subset = figure_data[figure_data["interconnectorId"].eq(FLEET_ID)].sort_values("bin_midpoint_mw")
        if not fleet_subset.empty:
            fleet_fig = go.Figure(
                go.Scatter(
                    x=fleet_subset["bin_midpoint_mw"],
                    y=fleet_subset["probability_pct"],
                    mode="lines",
                    name=FLEET_NAME,
                    line={"width": 3.5, "color": "#111111", "shape": "hvh"},
                    hovertemplate=(
                        "%{fullData.name}<br>"
                        "%{customdata[0]:,.0f}-%{customdata[1]:,.0f} MW<br>"
                        "Share: %{y:.2f}%<br>"
                        "Bin half-hours: %{customdata[2]:,.0f}<br>"
                        "Density per MW: %{customdata[3]:.6f}"
                        "<extra></extra>"
                    ),
                    customdata=np.column_stack(
                        [
                            fleet_subset["bin_lower_mw"].to_numpy(dtype=float),
                            fleet_subset["bin_upper_mw"].to_numpy(dtype=float),
                            fleet_subset["bin_observations"].to_numpy(dtype=float),
                            fleet_subset["probability_density_per_mw"].to_numpy(dtype=float),
                        ]
                    ),
                )
            )
            fleet_fig.update_layout(
                xaxis_title="Aggregate directional operating level bin midpoint (MW)",
                yaxis_title=yaxis_titles[direction],
                height=720,
                showlegend=False,
            )
            plotly_layout(fleet_fig, f"{period_title} Fleet {direction_titles[direction]}")
            fleet_basename = f"{direction}_level_pdf_distribution_fleet_{period_label}"
            fleet_fig.write_html(figure_dir / f"{fleet_basename}.html", include_plotlyjs="directory")
            write_plot_image_if_available(fleet_fig, figure_dir / f"{fleet_basename}.png")


def safe_filename(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in str(value))


def remove_stale_combined_pdf_figures(output_dir: Path, period_label: str) -> None:
    figure_dir = output_dir / "figures"
    stale_basenames = [
        f"import_level_pdf_distribution_{period_label}",
        f"export_level_pdf_distribution_{period_label}",
        f"import_level_pdf_distribution_fleet_{period_label}",
        f"export_level_pdf_distribution_fleet_{period_label}",
    ]
    for basename in stale_basenames:
        for suffix in [".html", ".png"]:
            path = figure_dir / f"{basename}{suffix}"
            if path.exists():
                path.unlink()


def generate_per_series_pdf_figures(pdf_bins: pd.DataFrame, output_dir: Path, period_label: str, period_title: str) -> None:
    if pdf_bins.empty:
        return

    go = require_plotly()
    figure_dir = output_dir / "figures" / "interconnectors" / "pdf_distributions"
    figure_dir.mkdir(parents=True, exist_ok=True)

    direction_styles = {
        "import": {
            "name": "Import distribution",
            "color": "#2f6db2",
            "metric": "importing",
        },
        "export": {
            "name": "Export distribution",
            "color": "#c43c39",
            "metric": "exporting",
        },
    }

    for interconnector_id in ordered_series_ids(pdf_bins):
        series_data = pdf_bins[pdf_bins["interconnectorId"].eq(interconnector_id)].copy()
        if series_data.empty:
            continue

        interconnector_name = series_data["interconnectorName"].dropna().iloc[0]
        title_label = FLEET_NAME if interconnector_id == FLEET_ID else f"{interconnector_id} - {interconnector_name}"
        fig = go.Figure()

        for direction in ["import", "export"]:
            subset = series_data[series_data["direction"].eq(direction)].sort_values("bin_midpoint_mw")
            if subset.empty:
                continue
            style = direction_styles[direction]
            fig.add_trace(
                go.Scatter(
                    x=subset["bin_midpoint_mw"],
                    y=subset["probability_pct"],
                    mode="lines",
                    name=style["name"],
                    line={"width": 3, "color": style["color"], "shape": "hvh"},
                    hovertemplate=(
                        "%{fullData.name}<br>"
                        "%{customdata[0]:,.0f}-%{customdata[1]:,.0f} MW<br>"
                        "Share: %{y:.2f}% of directional half-hours<br>"
                        "Bin half-hours: %{customdata[2]:,.0f}<br>"
                        "Directional half-hours: %{customdata[3]:,.0f}"
                        "<extra></extra>"
                    ),
                    customdata=np.column_stack(
                        [
                            subset["bin_lower_mw"].to_numpy(dtype=float),
                            subset["bin_upper_mw"].to_numpy(dtype=float),
                            subset["bin_observations"].to_numpy(dtype=float),
                            subset["direction_observations"].to_numpy(dtype=float),
                        ]
                    ),
                )
            )

        fig.update_layout(
            xaxis_title="Directional operating level bin midpoint (MW)",
            yaxis_title="Share of directional half-hours in MW bin (%)",
            height=720,
        )
        plotly_layout(fig, f"{period_title} {title_label} PDF Distribution")
        basename = f"{safe_filename(interconnector_id)}_level_pdf_distribution_{period_label}"
        fig.write_html(figure_dir / f"{basename}.html", include_plotlyjs="directory")
        write_plot_image_if_available(fig, figure_dir / f"{basename}.png")


def generate_per_series_cdf_figures(pdf_bins: pd.DataFrame, output_dir: Path, period_label: str, period_title: str) -> None:
    if pdf_bins.empty:
        return

    go = require_plotly()
    figure_dir = output_dir / "figures" / "interconnectors" / "cdf_distributions"
    figure_dir.mkdir(parents=True, exist_ok=True)

    direction_styles = {
        "import": {
            "name": "Import CDF",
            "color": "#2f6db2",
        },
        "export": {
            "name": "Export CDF",
            "color": "#c43c39",
        },
    }

    for interconnector_id in ordered_series_ids(pdf_bins):
        series_data = pdf_bins[pdf_bins["interconnectorId"].eq(interconnector_id)].copy()
        if series_data.empty:
            continue

        interconnector_name = series_data["interconnectorName"].dropna().iloc[0]
        title_label = FLEET_NAME if interconnector_id == FLEET_ID else f"{interconnector_id} - {interconnector_name}"
        fig = go.Figure()

        for direction in ["import", "export"]:
            subset = series_data[series_data["direction"].eq(direction)].sort_values("bin_upper_mw")
            if subset.empty:
                continue
            style = direction_styles[direction]
            fig.add_trace(
                go.Scatter(
                    x=subset["bin_upper_mw"],
                    y=subset["cumulative_probability_pct"],
                    mode="lines",
                    name=style["name"],
                    line={"width": 3, "color": style["color"], "shape": "hv"},
                    hovertemplate=(
                        "%{fullData.name}<br>"
                        "Up to %{x:,.0f} MW<br>"
                        "Cumulative share: %{y:.2f}%<br>"
                        "Directional half-hours: %{customdata[0]:,.0f}"
                        "<extra></extra>"
                    ),
                    customdata=np.column_stack([subset["direction_observations"].to_numpy(dtype=float)]),
                )
            )

        fig.update_layout(
            xaxis_title="Directional operating level threshold (MW)",
            yaxis_title="Cumulative share of directional half-hours (%)",
            yaxis={"range": [0, 100], "ticksuffix": "%"},
            height=720,
        )
        plotly_layout(fig, f"{period_title} {title_label} CDF Distribution")
        basename = f"{safe_filename(interconnector_id)}_level_cdf_distribution_{period_label}"
        fig.write_html(figure_dir / f"{basename}.html", include_plotlyjs="directory")
        write_plot_image_if_available(fig, figure_dir / f"{basename}.png")


def lookup_percentile(wide: pd.DataFrame, interconnector_id: str, direction: str, percentile: str) -> float:
    subset = wide[wide["interconnectorId"].eq(interconnector_id) & wide["direction"].eq(direction)]
    if subset.empty:
        return np.nan
    return subset.iloc[0].get(percentile, np.nan)


def build_story(
    output_dir: Path,
    wide: pd.DataFrame,
    sample_summary: pd.DataFrame,
    period_label: str,
    period_title: str,
    is_all_data: bool,
    requested_start: pd.Timestamp,
    requested_end: pd.Timestamp,
    analysis_start: pd.Timestamp,
    analysis_end: pd.Timestamp,
) -> None:
    fleet_summary = sample_summary[sample_summary["interconnectorId"].eq(FLEET_ID)].iloc[0]
    fleet_import_p10 = lookup_percentile(wide, FLEET_ID, "import", "P10")
    fleet_import_p50 = lookup_percentile(wide, FLEET_ID, "import", "P50")
    fleet_import_p90 = lookup_percentile(wide, FLEET_ID, "import", "P90")
    fleet_export_p10 = lookup_percentile(wide, FLEET_ID, "export", "P10")
    fleet_export_p50 = lookup_percentile(wide, FLEET_ID, "export", "P50")
    fleet_export_p90 = lookup_percentile(wide, FLEET_ID, "export", "P90")

    if is_all_data:
        coverage_line = f"The run covers all available half-hourly data from {analysis_start} to {analysis_end}."
    elif analysis_start == requested_start and analysis_end == requested_end:
        coverage_line = f"The run covers the full {period_label} calendar year."
    else:
        coverage_line = (
            f"The requested calendar-year window was clipped to available data: "
            f"{analysis_start} to {analysis_end}."
        )

    strongest_import = (
        wide[wide["direction"].eq("import")]
        .sort_values("P50", ascending=False)
        .head(5)[["interconnectorId", "direction_observations", "direction_share_of_operational_half_hours_pct", "P10", "P50", "P90"]]
    )
    strongest_export = (
        wide[wide["direction"].eq("export")]
        .sort_values("P50", ascending=False)
        .head(5)[["interconnectorId", "direction_observations", "direction_share_of_operational_half_hours_pct", "P10", "P50", "P90"]]
    )

    def markdown_table(df: pd.DataFrame) -> list[str]:
        lines = [
            "| Interconnector | Direction half-hours | Direction share | P10 MW | P50 MW | P90 MW |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for _, row in df.iterrows():
            lines.append(
                "| "
                f"{row['interconnectorId']} | "
                f"{format_num(row['direction_observations'])} | "
                f"{format_pct(row['direction_share_of_operational_half_hours_pct'])} | "
                f"{format_num(row['P10'])} | "
                f"{format_num(row['P50'])} | "
                f"{format_num(row['P90'])} |"
            )
        return lines

    lines = [
        f"# {period_title} Import/Export Level Distribution Percentiles",
        "",
        coverage_line,
        "",
        "Percentiles are calculated separately for import and export operating periods. "
        "That means import P10/P50/P90 use only half-hours where the series is importing, "
        "while export P10/P50/P90 use only half-hours where the series is exporting. "
        "Exports are shown as positive MW magnitudes.",
        "",
        "## Fleet Readout",
        "",
        f"- Importing half-hours: {format_num(fleet_summary['import_observations'])} "
        f"({format_pct(fleet_summary['import_share_pct'])} of operational periods).",
        f"- Exporting half-hours: {format_num(fleet_summary['export_observations'])} "
        f"({format_pct(fleet_summary['export_share_pct'])} of operational periods).",
        f"- Near-zero half-hours: {format_num(fleet_summary['near_zero_observations'])} "
        f"({format_pct(fleet_summary['near_zero_share_pct'])} of operational periods).",
        f"- Fleet import distribution: P10 {format_num(fleet_import_p10)} MW, "
        f"P50 {format_num(fleet_import_p50)} MW, P90 {format_num(fleet_import_p90)} MW.",
        f"- Fleet export distribution: P10 {format_num(fleet_export_p10)} MW, "
        f"P50 {format_num(fleet_export_p50)} MW, P90 {format_num(fleet_export_p90)} MW.",
        "",
        "For minimum operating-limit style figures, the low directional percentiles "
        "(especially P5, P10, and P20) are usually more useful than P0 because P0 "
        "is the single smallest non-near-zero half-hour after the deadband filter.",
        "",
        "## Largest Median Directional Levels",
        "",
        "### Import",
        "",
        *markdown_table(strongest_import),
        "",
        "### Export",
        "",
        *markdown_table(strongest_export),
        "",
        "## Outputs",
        "",
        f"- `import_export_level_percentiles_{period_label}.csv` - long-form percentile table.",
        f"- `import_export_level_percentiles_wide_{period_label}.csv` - one row per series and direction with P0-P100 columns.",
        f"- `import_export_level_pdf_bins_{period_label}.csv` - binned probability-density table used by the PDF-style plots.",
        f"- `import_export_direction_sample_summary_{period_label}.csv` - import/export/near-zero sample sizes and mean levels.",
        f"- `figures/import_level_percentile_distribution_{period_label}.html` - import distribution plot.",
        f"- `figures/export_level_percentile_distribution_{period_label}.html` - export distribution plot.",
        f"- `figures/interconnectors/pdf_distributions/*_level_pdf_distribution_{period_label}.html` - one probability-density distribution plot per interconnector and fleet total.",
        f"- `figures/interconnectors/cdf_distributions/*_level_cdf_distribution_{period_label}.html` - one cumulative distribution plot per interconnector and fleet total.",
        "",
    ]
    (output_dir / f"import_export_level_distribution_story_{period_label}.md").write_text("\n".join(lines), encoding="utf-8")


def build_run_config(
    args: argparse.Namespace,
    period_label: str,
    period_title: str,
    requested_start: pd.Timestamp,
    requested_end: pd.Timestamp,
    analysis_start: pd.Timestamp,
    analysis_end: pd.Timestamp,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"key": "analysis_period", "value": period_label},
            {"key": "analysis_period_title", "value": period_title},
            {"key": "year", "value": args.year if args.year is not None else ""},
            {"key": "all_data", "value": args.all_data},
            {"key": "requested_start", "value": requested_start},
            {"key": "requested_end", "value": requested_end},
            {"key": "analysis_start", "value": analysis_start},
            {"key": "analysis_end", "value": analysis_end},
            {"key": "interconnector_data_dir", "value": args.interconnector_data_dir},
            {"key": "metadata", "value": args.metadata},
            {"key": "capacity_file", "value": args.capacity_file},
            {"key": "positive_direction", "value": args.positive_direction},
            {"key": "deadband_mw", "value": args.deadband_mw},
            {"key": "pdf_bin_width_mw", "value": args.pdf_bin_width_mw},
            {"key": "include_combined_pdf_figures", "value": args.include_combined_pdf_figures},
            {"key": "percentiles", "value": ", ".join(f"P{percentile}" for percentile in PERCENTILES)},
            {
                "key": "method",
                "value": (
                    "Import and export percentiles are conditional on the series being in that "
                    "direction; export levels are positive MW magnitudes."
                ),
            },
        ]
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    period_label, period_title = period_labels(args)

    combined, requested_start, requested_end, analysis_start, analysis_end = build_analysis_series(args)
    long, wide = build_percentile_tables(combined, period_label)
    pdf_bins = build_pdf_bin_table(combined, period_label, args.pdf_bin_width_mw)
    sample_summary = build_direction_sample_summary(combined)

    write_csv(long, args.output_dir / f"import_export_level_percentiles_{period_label}.csv")
    write_csv(wide, args.output_dir / f"import_export_level_percentiles_wide_{period_label}.csv")
    write_csv(pdf_bins, args.output_dir / f"import_export_level_pdf_bins_{period_label}.csv")
    write_csv(sample_summary, args.output_dir / f"import_export_direction_sample_summary_{period_label}.csv")
    write_csv(
        build_run_config(args, period_label, period_title, requested_start, requested_end, analysis_start, analysis_end),
        args.output_dir / f"run_config_{period_label}.csv",
    )
    build_story(
        args.output_dir,
        wide,
        sample_summary,
        period_label,
        period_title,
        args.all_data,
        requested_start,
        requested_end,
        analysis_start,
        analysis_end,
    )

    if not args.no_figures:
        generate_figures(long, args.output_dir, period_label, period_title)
        generate_per_series_pdf_figures(pdf_bins, args.output_dir, period_label, period_title)
        generate_per_series_cdf_figures(pdf_bins, args.output_dir, period_label, period_title)
        if args.include_combined_pdf_figures:
            generate_pdf_figures(pdf_bins, args.output_dir, period_label, period_title)
        else:
            remove_stale_combined_pdf_figures(args.output_dir, period_label)

    print(
        textwrap.dedent(
            f"""
            Wrote {period_title} import/export level distribution analysis to {args.output_dir}
            Analysis window: {analysis_start} to {analysis_end}
            Series analysed: {sample_summary.shape[0]}
            Percentile rows: {long.shape[0]}
            PDF-bin rows: {pdf_bins.shape[0]}
            """
        ).strip()
    )


if __name__ == "__main__":
    main()
