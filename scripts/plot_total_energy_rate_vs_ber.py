#!/usr/bin/env python3
"""Generate energy and rate vs BER plots without external sweep dependencies."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Iterable, List, Optional, Tuple, TypedDict

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

import gen_k_sweep


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

SUMMARY_TECHS = ("ASAP7", "NanGate45")
SUMMARY_ROOT_CANDIDATES = (ROOT / "paperdata",)

DECODER_TOP = "rs_decoder"
ENCODER_TOP = "rs_encoder_wrapper"
SYNDROME_TOP = "rs_syndrome"


EnergyRow = TypedDict(
    "EnergyRow",
    {
        "tech": str,
        "BER Target": float,
        "input_preFEC_BER": float,
        "n": int,
        "t": int,
        "rate": float,
        "energy": float,
        "p_correctable": float,
        "m_bits": int,
    },
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plot total energy and rate vs BER")
    parser.add_argument("--selection", type=Path, default=Path("rsfec_selection_m8_n86.csv"),
                        help="precomputed sweep CSV; default uses rsfec_selection_m8_n86.csv")
    parser.add_argument("--save-selection", type=Path, help="optional path to save generated sweep data")
    parser.add_argument("--k", type=int, help="force a specific data-symbol count K when generating a sweep")
    parser.add_argument("--min-exp", type=float, default=-27.0, help="minimum BER exponent (e.g., -27 for 1e-27)")
    parser.add_argument("--max-exp", type=float, default=-3.0, help="maximum BER exponent (e.g., -3 for 1e-3)")
    parser.add_argument("--step", type=float, default=0.5, help="log-scale step size in decades")
    parser.add_argument("--target", type=float, action="append", dest="targets", help="target post-FEC BER (repeatable)")
    parser.add_argument("--n", type=int, action="append", dest="n_filter", help="restrict to specific block length N (repeatable)")
    return parser.parse_args()


def load_or_generate_selection(
    args: argparse.Namespace, targets: Iterable[float]
) -> Tuple[pd.DataFrame, list[float]]:
    if args.selection is not None:
        df = pd.read_csv(args.selection)
    else:
        df = gen_k_sweep.generate_sweep(
            k=args.k,
            exp_start=args.max_exp,
            exp_stop=args.min_exp,
            exp_step=-abs(args.step),
            targets=list(targets),
        )
        if args.save_selection is not None:
            args.save_selection.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(args.save_selection, index=False)

    df = df.dropna(subset=["n", "t"]).copy()
    df["target_post_BER"] = df["target_post_BER"].astype(float)
    target_list = sorted(set(targets))
    df["target_post_BER"] = df["target_post_BER"].apply(lambda val: match_target_ber(val, target_list))
    df = df.dropna(subset=["target_post_BER"])
    df["n"] = df["n"].astype(int)
    df["t"] = df["t"].astype(int)

    if args.n_filter:
        df = df[df["n"].isin(args.n_filter)]

    if df.empty:
        raise ValueError("No sweep entries match the provided filters/targets")

    df.sort_values(["target_post_BER", "input_preFEC_BER"], inplace=True)

    return df, target_list


def match_target_ber(value: float, targets: Iterable[float]) -> Optional[float]:
    if value <= 0.0:
        return None

    for target in targets:
        if math.isclose(value, target, rel_tol=1e-9, abs_tol=max(1e-40, abs(target) * 1e-9)):
            return float(target)
    return None


def find_summary_path(tech: str) -> Path:
    tech_dir = f"{tech.lower()}_code_sweep"
    for base in SUMMARY_ROOT_CANDIDATES:
        candidate = base / tech_dir / "summary.csv"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"summary.csv for {tech} not found in expected directories")


def _cycles_per_symbol(row: pd.Series) -> float:
    top = row.get("top", "")
    n = pd.to_numeric(row.get("N"), errors="coerce")
    k = pd.to_numeric(row.get("K"), errors="coerce")
    m_bits = pd.to_numeric(row.get("GF_WIDTH"), errors="coerce")
    if pd.isna(k) or k == 0:
        return float("nan")
    if top == DECODER_TOP:
        return (2.0 ** float(m_bits)) / float(k)
    if top == ENCODER_TOP:
        return float(n) / float(k)
    return 1.0


def p_correctable(n: int, t: int, p_b: float, m_bits: int) -> float:
    if t <= 0:
        return 0.0
    p_s = 1.0 - (1.0 - p_b) ** m_bits
    if p_s <= 0.0:
        return 0.0
    if p_s >= 1.0:
        return 1.0

    log1m = math.log1p(-p_s)
    total = 0.0
    for i in range(1, min(t, n) + 1):
        logc = math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1)
        logpmf = logc + i * math.log(p_s) + (n - i) * log1m
        total += math.exp(logpmf)
    return min(max(total, 0.0), 1.0)


def build_dataset(selection: pd.DataFrame) -> pd.DataFrame:
    selection = (
        selection.sort_values(
            ["target_post_BER", "input_preFEC_BER", "t"],
            ascending=[True, False, True],
        )
        .drop_duplicates(subset=["target_post_BER", "input_preFEC_BER"], keep="first")
        .reset_index(drop=True)
    )

    rows: List[EnergyRow] = []
    for tech in SUMMARY_TECHS:
        summary_path = find_summary_path(tech)
        summary = pd.read_csv(summary_path)
        summary["N"] = pd.to_numeric(summary["N"], errors="coerce")
        summary["K"] = pd.to_numeric(summary["K"], errors="coerce")
        summary["GF_WIDTH"] = pd.to_numeric(summary["GF_WIDTH"], errors="coerce")
        summary["cycles"] = summary.apply(_cycles_per_symbol, axis=1)
        summary["energy_pj_per_bit"] = (
            summary["total_dyn_mw"]
            * summary["CLK_NS"]
            * summary["cycles"]
            / ((summary["K"] / summary["N"]) * summary["GF_WIDTH"])
        )
        energy_map = summary.pivot_table(index=["N", "K"], columns="top", values="energy_pj_per_bit")

        for _, sel_row in selection.iterrows():
            n = int(sel_row["n"])
            t = int(sel_row.get("t", 0))
            k_val = int(sel_row.get("k", 0))

            if t != 0 and (n, k_val) not in energy_map.index:
                continue
            if t != 0 and k_val >= n:
                continue

            if t == 0:
                enc_energy = syn_energy = dec_energy = 0.0
            else:
                try:
                    enc_energy = energy_map.loc[(n, k_val), ENCODER_TOP]
                    syn_energy = energy_map.loc[(n, k_val), SYNDROME_TOP]
                    dec_energy = energy_map.loc[(n, k_val), DECODER_TOP]
                except KeyError:
                    continue

            p_in = float(sel_row["input_preFEC_BER"])
            rate = float(sel_row["rate"])
            target = float(sel_row["target_post_BER"])

            if "m" in sel_row and not pd.isna(sel_row["m"]):
                symbol_bits = int(sel_row["m"])
            else:
                gf_widths = summary.loc[(summary["N"] == n) & (summary["K"] == k_val), "GF_WIDTH"]
                if gf_widths.empty():
                    continue
                symbol_bits = int(gf_widths.iloc[0])

            p_corr = p_correctable(n, t, p_in, symbol_bits)
            total_energy = enc_energy + syn_energy + p_corr * dec_energy

            rows.append(
                {
                    "tech": tech,
                    "BER Target": target,
                    "input_preFEC_BER": p_in,
                    "n": n,
                    "k": k_val,
                    "t": t,
                    "rate": rate,
                    "energy": total_energy,
                    "p_correctable": p_corr,
                    "m_bits": symbol_bits,
                }
            )

    dataset = pd.DataFrame(rows)
    if dataset.empty:
        return dataset
    dataset = dataset[dataset["input_preFEC_BER"] > 0].copy()
    dataset = dataset.sort_values(["tech", "BER Target", "input_preFEC_BER", "t"]).reset_index(drop=True)
    dataset = dataset.drop_duplicates(subset=["tech", "BER Target", "input_preFEC_BER", "t"], keep="last")
    return dataset


def plot_outputs(df: pd.DataFrame, targets: list[float], k: Optional[int]) -> None:
    out_dir = ROOT / "plots"
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_dir / "total_energy_rate_vs_ber.csv", index=False)

    sns.set_style("darkgrid")
    for tech in SUMMARY_TECHS:
        data = df[df["tech"] == tech]
        if data.empty:
            continue
        data_sorted = data.sort_values(["BER Target", "input_preFEC_BER"], ascending=[True, False])
        data_sorted.to_csv(out_dir / f"{tech.lower()}_total_energy_rate_vs_ber.csv", index=False)

        symbol_bits = int(data_sorted["m_bits"].iloc[0]) if "m_bits" in data_sorted and not data_sorted["m_bits"].isna().all() else 0
        k_label = f"k={k}" if k is not None else "best-k"

        plot_data = data_sorted[data_sorted["input_preFEC_BER"] > 0].copy()
        # Drop the K=N "no-FEC" operating point (t=0). It has energy=0 by
        # construction and skews the x-range into ultra-low BERs, creating a
        # distracting "tail" in vs-BER plots.
        if "t" in plot_data.columns:
            plot_data = plot_data[pd.to_numeric(plot_data["t"], errors="coerce").fillna(0).astype(int) > 0].copy()
        if plot_data.empty:
            continue

        plt.figure(figsize=(8, 5))
        positive_ber = plot_data["input_preFEC_BER"]
        x_min = positive_ber.min()
        x_max = positive_ber.max()
        x_right = min(0.5, x_max * 1.1)

        sns.lineplot(
            data=plot_data,
            x="input_preFEC_BER",
            y="energy",
            hue="BER Target",
            style="BER Target",
            marker="o",
        )
        plt.xscale("log")
        plt.xlim(x_min, x_right)
        plt.xlabel("Input Pre-FEC BER")
        plt.ylabel("Total energy per bit (pJ/bit)")
        targets_str = ", ".join(f"{t:.0e}" for t in targets)
        if symbol_bits > 0:
            title_prefix = f"{tech} RS(m={symbol_bits}, {k_label})"
        else:
            title_prefix = f"{tech} RS({k_label})"
        plt.title(f"{title_prefix} Energy/bit vs Input BER (targets: {targets_str})")
        plt.tight_layout()
        plt.savefig(out_dir / f"{tech.lower()}_energy_vs_ber.pdf")
        plt.savefig(out_dir / f"{tech.lower()}_energy_vs_ber.png", dpi=180)
        plt.close()

        plt.figure(figsize=(8, 5))
        sns.lineplot(
            data=plot_data,
            x="input_preFEC_BER",
            y="rate",
            hue="BER Target",
            style="BER Target",
            marker="o",
        )
        plt.xscale("log")
        plt.xlim(x_min, x_right)
        plt.xlabel("Input Pre-FEC BER")
        plt.ylabel("Code rate (k/n)")
        plt.title(f"{title_prefix} Rate vs Input BER (targets: {targets_str})")
        plt.tight_layout()
        plt.savefig(out_dir / f"{tech.lower()}_rate_vs_ber.pdf")
        plt.savefig(out_dir / f"{tech.lower()}_rate_vs_ber.png", dpi=180)
        plt.close()


def main() -> None:
    args = parse_args()
    targets_input = sorted(set(args.targets)) if args.targets else [1e-15, 1e-27]
    selection, targets = load_or_generate_selection(args, targets_input)
    dataset = build_dataset(selection)
    if dataset.empty:
        raise ValueError("No dataset rows produced; check sweep/summary overlap")
    plot_outputs(dataset, targets, args.k)


if __name__ == "__main__":
    main()
