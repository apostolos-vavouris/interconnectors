"""Export generated Plotly HTML figures to PNG files using headless Edge/Chrome.

This is a lightweight fallback for environments where Plotly is available but
the Python static-image engine, Kaleido, is not installed.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path


DEFAULT_BROWSER_CANDIDATES = [
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export all Plotly HTML figures to PNG screenshots.")
    parser.add_argument(
        "--figures-dir",
        type=Path,
        default=Path("analysis_outputs") / "bm_interconnector_history" / "figures",
        help="Directory containing generated HTML figures.",
    )
    parser.add_argument("--browser", type=Path, default=None, help="Path to msedge.exe or chrome.exe.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing PNG exports.")
    parser.add_argument("--main-width", type=int, default=1600, help="Viewport width for top-level figures.")
    parser.add_argument("--main-height", type=int, default=1000, help="Viewport height for top-level figures.")
    parser.add_argument("--profile-width", type=int, default=1800, help="Viewport width for per-interconnector profiles.")
    parser.add_argument("--profile-height", type=int, default=1700, help="Viewport height for per-interconnector profiles.")
    parser.add_argument("--virtual-time-budget-ms", type=int, default=3000, help="Time budget for Plotly rendering.")
    return parser.parse_args()


def resolve_browser(explicit: Path | None) -> Path:
    if explicit is not None:
        if explicit.exists():
            return explicit
        raise FileNotFoundError(f"Browser executable not found: {explicit}")

    for candidate in DEFAULT_BROWSER_CANDIDATES:
        if candidate.exists():
            return candidate

    for command in ["msedge", "chrome", "chromium"]:
        found = shutil.which(command)
        if found:
            return Path(found)

    raise FileNotFoundError("Could not find Microsoft Edge or Chrome for headless PNG export.")


def figure_viewport(html_path: Path, args: argparse.Namespace) -> tuple[int, int]:
    if html_path.parent.name == "interconnectors":
        return args.profile_width, args.profile_height
    return args.main_width, args.main_height


def file_url(path: Path) -> str:
    return path.resolve().as_uri()


def export_one(browser: Path, html_path: Path, png_path: Path, args: argparse.Namespace) -> tuple[bool, str]:
    width, height = figure_viewport(html_path, args)
    png_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="interconnector_png_export_") as user_data_dir:
        command = [
            str(browser),
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-gpu-compositing",
            "--disable-software-rasterizer",
            "--disable-dev-shm-usage",
            "--disable-d3d11",
            "--disable-features=UseSkiaRenderer,VizDisplayCompositor",
            "--no-first-run",
            "--disable-extensions",
            "--allow-file-access-from-files",
            f"--user-data-dir={user_data_dir}",
            f"--window-size={width},{height}",
            f"--virtual-time-budget={args.virtual_time_budget_ms}",
            f"--screenshot={png_path.resolve()}",
            file_url(html_path),
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)

    if png_path.exists() and png_path.stat().st_size > 0:
        return True, f"wrote {png_path}"
    stderr = (result.stderr or result.stdout or "").strip().splitlines()
    detail = stderr[-1] if stderr else f"browser exited with code {result.returncode}"
    return False, f"failed {html_path}: {detail}"


def main() -> None:
    args = parse_args()
    figures_dir = args.figures_dir
    if not figures_dir.exists():
        raise FileNotFoundError(f"Figures directory not found: {figures_dir}")

    browser = resolve_browser(args.browser)
    html_files = sorted(figures_dir.rglob("*.html"))
    if not html_files:
        raise FileNotFoundError(f"No HTML figures found under {figures_dir}")

    successes = 0
    failures: list[str] = []
    skipped = 0
    for html_path in html_files:
        png_path = html_path.with_suffix(".png")
        if png_path.exists() and not args.overwrite:
            skipped += 1
            continue
        ok, message = export_one(browser, html_path, png_path, args)
        if ok:
            successes += 1
            print(message)
        else:
            failures.append(message)
            print(message)

    print(f"PNG export complete: {successes} written, {skipped} skipped, {len(failures)} failed.")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
