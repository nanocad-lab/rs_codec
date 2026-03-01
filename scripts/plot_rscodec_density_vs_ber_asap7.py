#!/usr/bin/env python3
"""
Plot RS-FEC throughput density vs input BER (ASAP7).

This script reads the area/throughput dataset produced by
`scripts/plot_area_throughput_vs_ber_asap7.py` and emits a compact, two-panel
figure suitable for a two-column paper:

  (a) Gbps/mm   : info throughput divided by sqrt(area) (square-footprint equiv.)
  (b) Gbps/mm^2 : info throughput density (throughput / area)

Notes
  - Throughput is the *information* throughput used in the rs_codec area/throughput
    sweep (decoder-limited).
  - "Gbps/mm" is an equivalent linear density assuming a square footprint; it is
    intended only as a simple 1-D proxy for comparing against shoreline-limited
    constraints.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import pandas as pd
import seaborn as sns


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--in-csv",
        type=Path,
        default=ROOT / "plots" / "area_per_gbps_vs_ber_asap7.csv",
        help="Input CSV from plot_area_throughput_vs_ber_asap7.py",
    )
    ap.add_argument(
        "--target-post-ber",
        type=float,
        default=1e-27,
        help="If set, filter to a single target_post_BER (default: 1e-27). Use 0 to keep all targets.",
    )
    ap.add_argument(
        "--outdir",
        type=Path,
        default=ROOT / "plots",
        help="Output directory for plots/CSVs",
    )
    ap.add_argument("--style", type=str, default="darkgrid", help="Seaborn style (e.g., whitegrid, darkgrid)")
    ap.add_argument("--paper", action="store_true", help="Paper-friendly formatting (white background, no titles).")
    # Paper-figure geometry tuning (subplots_adjust fractions).
    ap.add_argument("--paper-left", type=float, default=0.125, help="subplots_adjust left for paper plot")
    ap.add_argument("--paper-right", type=float, default=0.993, help="subplots_adjust right for paper plot")
    ap.add_argument("--paper-bottom", type=float, default=0.162, help="subplots_adjust bottom for paper plot")
    ap.add_argument("--paper-top", type=float, default=0.953, help="subplots_adjust top for paper plot")
    ap.add_argument("--paper-wspace", type=float, default=0.35, help="subplots_adjust wspace for paper plot")
    ap.add_argument(
        "--debug-clip",
        action="store_true",
        help="Print tightbbox slack (px) to help tune paper subplots_adjust without clipping.",
    )
    return ap.parse_args()


def _print_tightbbox_slack(fig: plt.Figure, *, label: str) -> None:
    """Print slack between the figure boundary and the tight content bbox (pixels)."""

    try:
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
    except Exception:
        return

    tight_in = fig.get_tightbbox(renderer)
    if tight_in is None:
        return

    tight_px = tight_in.transformed(fig.dpi_scale_trans)
    fig_px = fig.bbox
    left = float(tight_px.x0)
    bottom = float(tight_px.y0)
    right = float(fig_px.x1 - tight_px.x1)
    top = float(fig_px.y1 - tight_px.y1)
    print(f"{label}: tightbbox slack [px] left={left:.1f} right={right:.1f} bottom={bottom:.1f} top={top:.1f}")
    if min(left, right, bottom, top) < 0.0:
        print(f"WARNING: {label}: content extends outside figure bounds; clipping is likely.")


def _try_cast_float(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").astype(float)


def sci_tick_formatter(x: float, _pos: int) -> str:
    """Format ticks like 200000 -> 2e5 (instead of 200000 or 2e+05)."""
    if x == 0:
        return "0"
    ax = abs(float(x))
    if ax < 1e4:
        if ax >= 1.0:
            return f"{x:.0f}"
        return f"{x:g}"
    s = f"{x:.1e}"
    s = s.replace("e+0", "e").replace("e+", "e").replace("e-0", "e-")
    s = s.replace(".0e", "e")
    return s


def main() -> int:
    args = parse_args()
    in_csv = Path(args.in_csv)
    if not in_csv.is_file():
        raise FileNotFoundError(f"Missing input CSV: {in_csv}")

    df = pd.read_csv(in_csv)
    required = {"target_post_BER", "input_preFEC_BER", "area_total_mm2", "throughput_gbps"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Input CSV missing columns: {sorted(missing)}")

    df["target_post_BER"] = _try_cast_float(df["target_post_BER"])
    df["input_preFEC_BER"] = _try_cast_float(df["input_preFEC_BER"])
    df["area_total_mm2"] = _try_cast_float(df["area_total_mm2"])
    df["throughput_gbps"] = _try_cast_float(df["throughput_gbps"])
    df = df.dropna(subset=["target_post_BER", "input_preFEC_BER", "area_total_mm2", "throughput_gbps"]).copy()
    df = df[df["area_total_mm2"] > 0.0].copy()

    target_filter: Optional[float] = float(args.target_post_ber) if float(args.target_post_ber) > 0.0 else None
    if target_filter is not None:
        df = df[df["target_post_BER"] == target_filter].copy()
        if df.empty:
            raise ValueError(f"No rows for target_post_BER={target_filter:g} in {in_csv}")

    df["Gbps_per_mm2"] = df["throughput_gbps"] / df["area_total_mm2"]
    df["Gbps_per_mm"] = df["throughput_gbps"] / df["area_total_mm2"].apply(math.sqrt)
    df = df.sort_values(["target_post_BER", "input_preFEC_BER"]).reset_index(drop=True)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    df.to_csv(outdir / "rscodec_density_vs_input_BER_asap7.csv", index=False)

    style = args.style
    if args.paper and style == "darkgrid":
        style = "whitegrid"
    sns.set_style(style)
    if args.paper:
        sns.set_context("paper", font_scale=1.0)
        plt.rcParams.update(
            {
                "font.size": 9,
                "axes.labelsize": 9,
                "xtick.labelsize": 7,
                "ytick.labelsize": 7,
                "legend.fontsize": 7,
                "legend.title_fontsize": 7,
                "lines.linewidth": 2.0,
                "lines.markersize": 3.0,
            }
        )
        fig, (ax_mm, ax_mm2) = plt.subplots(1, 2, figsize=(3.5, 1.7), sharex=True)
    else:
        fig, (ax_mm, ax_mm2) = plt.subplots(1, 2, figsize=(7.5, 3.0), sharex=True)

    # Single-target plots are the common case for the paper.
    targets = sorted(df["target_post_BER"].unique())
    colors = sns.color_palette("tab10", len(targets))
    for color, target in zip(colors, targets):
        sub = df[df["target_post_BER"] == target].sort_values("input_preFEC_BER")
        label = f"target {target:.0e}" if len(targets) > 1 else None
        ax_mm.plot(sub["input_preFEC_BER"], sub["Gbps_per_mm"], marker="o", linewidth=2, color=color, label=label)
        ax_mm2.plot(sub["input_preFEC_BER"], sub["Gbps_per_mm2"], marker="o", linewidth=2, color=color, label=label)

    for ax in (ax_mm, ax_mm2):
        ax.set_xscale("log")
        ax.set_xlabel("" if args.paper else "Input pre-FEC BER")
        ax.yaxis.set_major_formatter(ticker.FuncFormatter(sci_tick_formatter))
        ax.grid(True, which="both", linestyle=":", linewidth=0.5)

    if args.paper:
        ax_mm.set_ylabel("")
        ax_mm2.set_ylabel("")
    else:
        ax_mm.set_ylabel("Info throughput density (Gbps/mm)")
        ax_mm2.set_ylabel("Info throughput density (Gbps/mm²)")

    if len(targets) > 1 and not args.paper:
        ax_mm.legend(loc="best", framealpha=1.0, facecolor="white", title="Target post-FEC BER")

    if args.paper:
        # Use a fixed subplot geometry so the two-panel paper figures align
        # across different y-axis label widths (log vs linear, etc.).
        fig.subplots_adjust(
            left=float(args.paper_left),
            right=float(args.paper_right),
            bottom=float(args.paper_bottom),
            top=float(args.paper_top),
            wspace=float(args.paper_wspace),
        )
    else:
        fig.tight_layout()
    if args.paper:
        if args.debug_clip:
            _print_tightbbox_slack(fig, label=str(outdir / "rscodec_density_vs_input_BER_asap7"))
        fig.savefig(outdir / "rscodec_density_vs_input_BER_asap7.pdf")
        fig.savefig(outdir / "rscodec_density_vs_input_BER_asap7.png", dpi=180)
    else:
        fig.savefig(outdir / "rscodec_density_vs_input_BER_asap7.pdf", bbox_inches="tight")
        fig.savefig(outdir / "rscodec_density_vs_input_BER_asap7.png", dpi=180, bbox_inches="tight")
    plt.close(fig)

    print(f"Wrote: {outdir / 'rscodec_density_vs_input_BER_asap7.pdf'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
