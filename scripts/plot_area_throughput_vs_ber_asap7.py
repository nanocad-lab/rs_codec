#!/usr/bin/env python3
"""Generate area-per-throughput vs BER plots for configurable sweep settings."""

from __future__ import annotations

import argparse
import math
from itertools import cycle
from pathlib import Path
from typing import Iterable, Iterator, Optional, TypedDict

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

import gen_k_sweep

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

SUMMARY_TECHS = ("ASAP7",)
SUMMARY_ROOT_CANDIDATES = (ROOT / "paperdata",)
DECODER_TOP = "rs_decoder"
ENCODER_TOP = "rs_encoder_wrapper"
STEP_DECADE = 1e-4
STEP_FACTOR = 10 ** STEP_DECADE


AreaRow = TypedDict(
    "AreaRow",
    {
        "tech": str,
        "target_post_BER": float,
        "input_preFEC_BER": float,
        "n": int,
        "rate": float,
        "clk_ns": float,
        "area_total_um2": float,
        "area_total_mm2": float,
        "throughput_gbps": float,
        "area_per_gbps": float,
    },
)


def find_summary_path(tech: str) -> Path:
    tech_dir = f"{tech.lower()}_code_sweep"
    for base in SUMMARY_ROOT_CANDIDATES:
        candidate = base / tech_dir / "summary.csv"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"summary.csv for {tech} not found in expected directories")


def load_or_generate_selection(args: argparse.Namespace, targets: list[float]) -> pd.DataFrame:
    if args.selection is not None:
        df = pd.read_csv(args.selection)
    else:
        df = gen_k_sweep.generate_sweep(
            k=args.k,
            exp_start=args.max_exp,
            exp_stop=args.min_exp,
            exp_step=-abs(args.step),
            targets=targets,
        )
        if args.save_selection is not None:
            args.save_selection.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(args.save_selection, index=False)

    df = df.dropna(subset=["n", "target_post_BER"]).copy()
    df["target_post_BER"] = df["target_post_BER"].astype(float)
    if targets:
        df["target_post_BER"] = df["target_post_BER"].apply(lambda val: match_target_ber(val, targets))
        df = df.dropna(subset=["target_post_BER"])
    df["n"] = df["n"].astype(int)

    if args.n_filter:
        df = df[df["n"].isin(args.n_filter)]

    if df.empty:
        raise ValueError("No sweep entries match the provided filters/targets")

    return df


def match_target_ber(value: float, targets: Iterable[float]) -> Optional[float]:
    if value <= 0.0:
        return None

    for target in targets:
        if math.isclose(value, target, rel_tol=1e-9, abs_tol=max(1e-40, abs(target) * 1e-9)):
            return float(target)
    return None


def _cycles_per_symbol_from_summary(row: pd.Series) -> float:
    top = row.get("top", "")
    try:
        n = float(row["N"])
        k = float(row["K"])
        m_bits = float(row["GF_WIDTH"])
    except (KeyError, TypeError, ValueError):
        return float("nan")
    if k == 0:
        return float("nan")
    if top == DECODER_TOP:
        return (2.0 ** m_bits) / k
    if top == ENCODER_TOP:
        return n / k
    return 1.0


def build_dataset(selection: pd.DataFrame) -> pd.DataFrame:
    rows: list[AreaRow] = []
    for tech in SUMMARY_TECHS:
        summary_path = find_summary_path(tech)
        summary = pd.read_csv(summary_path)
        summary["cycles"] = summary.apply(_cycles_per_symbol_from_summary, axis=1)
        summary["energy"] = (
            summary["total_dyn_mw"]
            * summary["CLK_NS"]
            * summary["cycles"]
            / ((summary["K"] / summary["N"]) * summary["GF_WIDTH"])
        )

        area_map = summary.pivot_table(index=["N", "K"], columns="top", values="area")
        clk_map = summary.pivot_table(index=["N", "K"], columns="top", values="CLK_NS")

        for _, sel in selection.iterrows():
            if int(sel["k"]) >= int(sel["n"]):
                continue
            key = (int(sel["n"]), int(sel["k"]))
            if key not in area_map.index or key not in clk_map.index:
                continue

            try:
                area_encoder = area_map.loc[key, "rs_encoder_wrapper"]
                area_syndrome = area_map.loc[key, "rs_syndrome"]
                area_decoder = area_map.loc[key, DECODER_TOP]
            except KeyError:
                continue

            clk_ns = clk_map.loc[key, DECODER_TOP]
            area_total_um2 = area_encoder + area_syndrome + area_decoder
            area_total_mm2 = area_total_um2 / 1e6

            if "m" in sel and not pd.isna(sel["m"]):
                symbol_bits = int(sel["m"])
            else:
                summary_rows = summary[(summary["N"] == key[0]) & (summary["K"] == key[1])]
                if summary_rows.empty:
                    continue
                symbol_bits = int(summary_rows["GF_WIDTH"].iloc[0])

            k_val = float(sel["k"])
            if not math.isfinite(k_val) or k_val == 0:
                continue
            decoder_cycles = (2.0 ** symbol_bits) / k_val
            if decoder_cycles == 0:
                continue
            throughput_gbps = (
                sel["rate"] * symbol_bits / (decoder_cycles * clk_ns * 1e-9) / 1e9
            )
            if throughput_gbps == 0:
                continue
            area_per_gbps = area_total_mm2 / throughput_gbps

            rows.append(
                {
                    "tech": tech,
                    "target_post_BER": float(sel["target_post_BER"]),
                    "input_preFEC_BER": float(sel["input_preFEC_BER"]),
                    "n": int(sel["n"]),
                    "rate": float(sel["rate"]),
                    "clk_ns": float(clk_ns),
                    "area_total_um2": float(area_total_um2),
                    "area_total_mm2": float(area_total_mm2),
                    "throughput_gbps": float(throughput_gbps),
                    "area_per_gbps": float(area_per_gbps),
                }
            )

    dataset = pd.DataFrame(rows)
    if dataset.empty:
        return dataset

    augmented: list[pd.DataFrame] = []
    for (tech, target), group in dataset.groupby(["tech", "target_post_BER"], sort=False):
        blk = group.sort_values("input_preFEC_BER").copy()
        if blk.empty:
            continue
        first = blk.iloc[0]
        zero_row = first.copy()
        zero_row["input_preFEC_BER"] = float(target)
        zero_row["area_total_um2"] = 0.0
        zero_row["area_total_mm2"] = 0.0
        zero_row["area_per_gbps"] = 0.0
        zero_row["rate"] = 1.0
        step_row = first.copy()
        step_row["input_preFEC_BER"] = float(target) * STEP_FACTOR
        blk = pd.concat([pd.DataFrame([zero_row, step_row]), blk], ignore_index=True)
        augmented.append(blk)

    combined = pd.concat(augmented, ignore_index=True)
    combined = combined.sort_values(["tech", "target_post_BER", "input_preFEC_BER"]).reset_index(drop=True)
    return combined


def plot_area_vs_ber(df: pd.DataFrame, targets: list[float]) -> None:
    out_dir = ROOT / "plots"
    out_dir.mkdir(parents=True, exist_ok=True)
    asap_data = df[df["tech"] == "ASAP7"].copy()
    if asap_data.empty:
        raise ValueError("No ASAP7 data available for plotting")

    asap_data.to_csv(out_dir / "area_per_gbps_vs_ber_asap7.csv", index=False)

    sns.set_style("darkgrid")
    fig, ax = plt.subplots(figsize=(8/1.3, 5/1.3))

    bers_sorted = sorted(targets)
    colors = sns.color_palette("tab10", len(bers_sorted))
    marker_cycle: Iterator[str] = cycle(("o", "s", "d", "^"))

    for color, ber in zip(colors, bers_sorted):
        subset = asap_data[asap_data["target_post_BER"] == ber].sort_values("input_preFEC_BER")
        if subset.empty:
            continue
        marker = next(marker_cycle)
        ax.plot(
            subset["input_preFEC_BER"],
            subset["area_per_gbps"],
            marker=marker,
            color=color,
            linestyle="--",
            label=f"ASAP7 target {ber:.0e}",
        )

    ax.set_xscale("log")
    #x_min = asap_data["input_preFEC_BER"].min()
    x_max = asap_data["input_preFEC_BER"].max()
    #ax.set_xlim(x_min, x_max)
    ax.set_xlim(1e-18, x_max)
    asap_top = asap_data["area_per_gbps"].max() * 1.05
    if asap_top == 0:
        asap_top = 0.01
    ax.set_ylim(0, max(asap_top, 0.0015))
    ax.set_xlabel("Input pre-FEC BER")
    ax.set_ylabel("ASAP7 area per throughput (mm²/Gbps)")

    title_targets = ", ".join(f"{ber:.0e}" for ber in bers_sorted)
    ax.set_title(f"FEC Area per Throughput vs Raw BER (Targets {title_targets})")
    ax.legend(loc="upper left", framealpha=1.0, facecolor="white")

    fig.tight_layout()
    fig.savefig(out_dir / "area_per_gbps_vs_ber_asap7.pdf")
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plot area-per-throughput vs BER")
    parser.add_argument("--selection", type=Path, default=Path("rsfec_selection_m8_n86.csv"),
                        help="precomputed sweep CSV; default uses rsfec_selection_m8_n86.csv")
    parser.add_argument("--save-selection", type=Path, help="optional path to save generated sweep data")
    parser.add_argument("--k", type=int, help="force a specific data-symbol count K when generating sweep data")
    parser.add_argument("--min-exp", type=float, default=-30.0, help="minimum BER exponent (e.g., -30 for 1e-30)")
    parser.add_argument("--max-exp", type=float, default=-3.0, help="maximum BER exponent (e.g., -3 for 1e-3)")
    parser.add_argument("--step", type=float, default=0.5, help="log-scale step size in decades")
    parser.add_argument("--target", type=float, action="append", dest="targets", help="target post-FEC BER (repeatable)")
    parser.add_argument("--n", type=int, action="append", dest="n_filter", help="restrict to specific block length N (repeatable)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    targets = sorted(set(args.targets)) if args.targets else [1e-15, 1e-30]
    selection = load_or_generate_selection(args, targets)
    dataset = build_dataset(selection)
    plot_area_vs_ber(dataset, targets)


if __name__ == "__main__":
    main()
