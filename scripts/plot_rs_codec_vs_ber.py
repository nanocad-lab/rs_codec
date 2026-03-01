#!/usr/bin/env python3
"""
Plot RS-FEC tradeoffs: pJ/bit vs input BER, and code rate vs input BER.

Inputs
- rsfec_selection CSV (e.g., `rsfec_selection_m8_n86.csv`)
  - Must contain columns: `target_post_BER,input_preFEC_BER,n,k,m,t,rate,post_ber_est`.
- synthesis summary CSV (e.g., `paperdata/asap7_code_sweep/summary.csv`)
  - Must contain columns: `label,top,N,K,GF_WIDTH,CLK_NS,area,wns,total_dyn_mw`.

Assumptions
- GF width is taken from the selection file (expect `m=8`).
- Use decoder energy for pJ/bit: `top == 'rs_decoder'`.
- Throughput model (from the referenced paper):
  - Cycles-per-symbol defaults are derived from the code parameters:
    encoder = `n / k`, decoder = `2**m / k`.
  - Information-bit throughput (bits/s) = `rate * m * f_clk / cycles_per_symbol`.
- Energy per information bit pJ/bit = `1e9 * total_dyn_mW / throughput_bits_per_s`.

Outputs
- Figures (PNG + PDF):
  - `plots/rscodec_pj_per_bit_vs_input_BER.png` and `.pdf`
  - `plots/rscodec_rate_vs_input_BER.png` and `.pdf`
- Raw data (CSV):
  - `plots/rscodec_pj_per_bit_vs_input_BER.csv`
  - `plots/rscodec_rate_vs_input_BER.csv`

Usage
  python scripts/plot_rs_codec_vs_ber.py \
    --selection rsfec_selection_m8_n86.csv \
    --summary paperdata/asap7_code_sweep/summary.csv \
    [--top rs_decoder] [--cycles-per-symbol 2] [--outdir plots]
"""

import argparse
import math
from pathlib import Path

import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np


TOP_CHOICES = ["rs_decoder", "rs_encoder_wrapper", "rs_syndrome"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Plot pJ/bit and code rate vs input BER for RS-FEC selections.")
    p.add_argument("--selection", type=Path, default=Path("rsfec_selection_m8_n86.csv"),
                   help="Path to selection CSV produced by rsfec_select_and_cfg.py")
    p.add_argument("--target-post-ber", type=float, default=None,
                   help="If set, filter the selection CSV to a single target_post_BER value.")
    p.add_argument("--summary", type=Path, default=Path("paperdata/asap7_code_sweep/summary.csv"),
                   help="Path to synthesis summary CSV with power and clock info")
    # Non-gated mode: choose a single top; cycles-per-symbol defaults are derived from (N,K,m)
    p.add_argument("--top", type=str, default="rs_decoder",
                   choices=TOP_CHOICES,
                   help="Top block for non-gated pJ/bit computation")
    p.add_argument("--cycles-per-symbol", type=float, default=None,
                   help="Override cycles-per-symbol for --top; default uses n/k for encoder and 2**m/k for decoder")
    # Gated mode: combine syndrome + decoder based on corrected-codeword probability
    p.add_argument("--gated", action="store_true",
                   help="Enable decoder clock gating model: E = E_syndrome + P_correctable * (E_decoder - E_syndrome)")
    p.add_argument("--syndrome-top", type=str, default="rs_syndrome",
                   choices=TOP_CHOICES,
                   help="Top name for syndrome-only energy when --gated")
    p.add_argument("--decoder-top", type=str, default="rs_decoder",
                   choices=TOP_CHOICES,
                   help="Top name for decoder energy when --gated")
    p.add_argument("--syndrome-cycles-per-symbol", type=float, default=1.0,
                   help="Cycles per symbol for the syndrome block when --gated")
    p.add_argument("--decoder-cycles-per-symbol", type=float, default=None,
                   help="Override decoder cycles-per-symbol when --gated; default uses 2**m/k")
    # Encoder contribution
    p.add_argument("--encoder-top", type=str, default="rs_encoder_wrapper",
                   choices=TOP_CHOICES,
                   help="Top name for encoder energy contribution")
    p.add_argument("--encoder-cycles-per-symbol", type=float, default=None,
                   help="Override encoder cycles-per-symbol; default uses n/k")
    p.add_argument("--no-encoder", dest="include_encoder", action="store_false",
                   help="Exclude encoder energy from total pJ/bit")
    p.set_defaults(include_encoder=True)
    p.add_argument("--outdir", type=Path, default=Path("plots"),
                   help="Directory to write output plots")
    p.add_argument("--style", type=str, default="darkgrid",
                   help="Seaborn style (e.g., whitegrid, darkgrid)")
    p.add_argument("--paper", action="store_true",
                   help="Paper-friendly formatting (smaller figures, larger fonts, no titles).")
    # Paper-figure geometry tuning (for combined 2-panel plot).
    p.add_argument("--paper-left", type=float, default=0.125, help="subplots_adjust left for paper combined plot")
    p.add_argument("--paper-right", type=float, default=0.993, help="subplots_adjust right for paper combined plot")
    p.add_argument("--paper-bottom", type=float, default=0.162, help="subplots_adjust bottom for paper combined plot")
    p.add_argument("--paper-top", type=float, default=0.953, help="subplots_adjust top for paper combined plot")
    p.add_argument("--paper-wspace", type=float, default=0.35, help="subplots_adjust wspace for paper combined plot")
    p.add_argument(
        "--debug-clip",
        action="store_true",
        help="Print tightbbox slack (px) to help tune paper subplots_adjust without clipping.",
    )
    return p.parse_args()


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


def load_selection(selection_csv: Path) -> pd.DataFrame:
    df = pd.read_csv(selection_csv)
    required = {"target_post_BER", "input_preFEC_BER", "n", "k", "m", "t", "rate"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Selection CSV missing columns: {sorted(missing)}")
    return df


def load_summary(summary_csv: Path) -> pd.DataFrame:
    df = pd.read_csv(summary_csv)
    required = {"top", "N", "K", "GF_WIDTH", "CLK_NS", "total_dyn_mw"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Summary CSV missing columns: {sorted(missing)}")
    return df


def merge_selection_power_single(selection: pd.DataFrame, summary: pd.DataFrame, top: str,
                                 prefix: str) -> pd.DataFrame:
    """Merge selection with a single-top summary; columns are prefixed."""
    sel = selection.rename(columns={"n": "N", "k": "K"}).copy()
    summ = summary[summary["top"] == top].copy()
    if summ.empty:
        raise ValueError(f"No rows for top='{top}' in summary CSV")
    summ = summ[["N", "K", "GF_WIDTH", "CLK_NS", "total_dyn_mw"]].drop_duplicates(subset=["N", "K"]).copy()
    summ = summ.rename(columns={
        "GF_WIDTH": f"{prefix}GF_WIDTH",
        "CLK_NS": f"{prefix}CLK_NS",
        "total_dyn_mw": f"{prefix}total_dyn_mw",
    })
    merged = sel.merge(summ, on=["N", "K"], how="left")
    mask_no_fec = merged["t"] == 0
    if mask_no_fec.any():
        clk_col = f"{prefix}CLK_NS"
        pwr_col = f"{prefix}total_dyn_mw"
        gf_col = f"{prefix}GF_WIDTH"
        merged.loc[mask_no_fec, gf_col] = merged.loc[mask_no_fec, "m"].astype(float)
        merged.loc[mask_no_fec, clk_col] = merged.loc[mask_no_fec, clk_col].fillna(1.0)
        merged.loc[mask_no_fec, pwr_col] = 0.0
    # Sanity: GF width vs m
    gf_col = f"{prefix}GF_WIDTH"
    mism = merged[(~merged[gf_col].isna()) & (merged[gf_col] != merged["m"])][["N", "K", gf_col, "m"]]
    if not mism.empty:
        print(f"Warning: GF width mismatch ({top}) in merged data; proceeding anyway:\n", mism.head())
    return merged


def compute_metrics_single_top(df: pd.DataFrame, cycles_per_symbol: float, prefix: str = "") -> pd.DataFrame:
    out = df.copy()
    clk_col = f"{prefix}CLK_NS" if prefix else "CLK_NS"
    pwr_col = f"{prefix}total_dyn_mw" if prefix else "total_dyn_mw"
    out[f"{prefix}fclk_hz"] = 1e9 / out[clk_col]
    if np.isscalar(cycles_per_symbol):
        denom = float(cycles_per_symbol)
        denom = np.nan if denom == 0 else denom
        out[f"{prefix}symbols_per_s"] = out[f"{prefix}fclk_hz"] / denom
    else:
        denom = pd.Series(cycles_per_symbol, index=out.index, dtype=float)
        denom = denom.where(denom != 0.0, np.nan)
        out[f"{prefix}symbols_per_s"] = out[f"{prefix}fclk_hz"] / denom
    out[f"{prefix}throughput_bps"] = out["rate"] * out["m"] * out[f"{prefix}symbols_per_s"]
    out[f"{prefix}pj_per_bit"] = 1e9 * out[pwr_col] / out[f"{prefix}throughput_bps"]
    return out


def _encoder_cycles_from_df(df: pd.DataFrame) -> pd.Series:
    n = pd.to_numeric(df["N"], errors="coerce")
    k = pd.to_numeric(df["K"], errors="coerce")
    cycles = n / k
    return cycles.replace([np.inf, -np.inf], np.nan)


def _decoder_cycles_from_df(df: pd.DataFrame) -> pd.Series:
    m_bits = pd.to_numeric(df["m"], errors="coerce")
    k = pd.to_numeric(df["K"], errors="coerce")
    cycles = np.power(2.0, m_bits) / k
    return cycles.replace([np.inf, -np.inf], np.nan)


def _default_cycles_for_top(top: str, df: pd.DataFrame) -> pd.Series:
    if top == "rs_encoder_wrapper":
        return _encoder_cycles_from_df(df)
    if top == "rs_decoder":
        return _decoder_cycles_from_df(df)
    return pd.Series(1.0, index=df.index, dtype=float)


def corrected_codeword_probability(n: int, t: int, m_bits: int, p_b: float) -> float:
    """Probability that a codeword has 1..t symbol errors (correctable),
    given bit-error probability p_b and symbol size m_bits.
    """
    import math
    if t <= 0:
        return 0.0
    # Symbol error probability
    p_s = 1.0 - (1.0 - p_b) ** m_bits
    if p_s <= 0.0:
        return 0.0
    if p_s >= 1.0:
        return 1.0 if t >= 1 else 0.0
    # Sum_{i=1..t} Binom(n,i) p_s^i (1-p_s)^(n-i)
    log1m = math.log1p(-p_s)
    total = 0.0
    # Precompute log factorial via lgamma
    for i in range(1, min(t, n) + 1):
        logC = math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1)
        logpmf = logC + i * math.log(p_s) + (n - i) * log1m
        total += math.exp(logpmf)
    return min(max(total, 0.0), 1.0)


def plot_pj_per_bit_vs_ber(df: pd.DataFrame, outpath: Path, style: str, *, paper: bool = False) -> None:
    effective_style = "whitegrid" if (paper and style == "darkgrid") else style
    sns.set_style(effective_style)
    lw = 4.0 if paper else 2.0
    ms = 7.0 if paper else 4.0
    if paper:
        sns.set_context("paper", font_scale=1.9)
        plt.figure(figsize=(3.5, 2.7))
    else:
        plt.figure(figsize=(7.5, 5.0))
    # Order targets for consistent legend
    # Use formatted labels like '1e-12', '1e-15', '1e-27'
    order = [lbl for _, lbl in sorted({(exp, lbl) for exp, lbl in zip(df["target_exp"], df["target_label"])})]
    ax = sns.lineplot(
        data=df,
        x="input_preFEC_BER",
        y="pj_per_bit",
        hue="target_label",
        hue_order=order,
        marker="o",
        style="target_label",
        dashes=False,
        linewidth=lw,
        markersize=ms,
    )
    ax.set_xscale("log")
    ax.set_yscale("log")
    if paper:
        ax.set_xlabel("")
        ax.set_ylabel("")
    else:
        ax.set_xlabel("Input pre-FEC BER")
        ax.set_ylabel("Energy per info bit (pJ/bit)")
    if not paper:
        ax.set_title("RS Decoder pJ/bit vs Input BER")
    ax.grid(True, which="both", linestyle=":", linewidth=0.5)
    # Seaborn creates a legend by default when hue is used, even for a single
    # curve. Remove it unless we truly have a multi-target plot.
    leg = ax.get_legend()
    if leg is not None:
        leg.remove()
    if df["target_label"].nunique() > 1:
        ax.legend(title="Target post-FEC BER", fontsize=14 if paper else None, title_fontsize=14 if paper else None)
    plt.tight_layout()
    outpath.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(outpath)
    plt.close()


def plot_rate_vs_ber(df: pd.DataFrame, outpath: Path, style: str, *, paper: bool = False) -> None:
    effective_style = "whitegrid" if (paper and style == "darkgrid") else style
    sns.set_style(effective_style)
    lw = 4.0 if paper else 2.0
    ms = 7.0 if paper else 4.0
    if paper:
        sns.set_context("paper", font_scale=1.9)
        plt.figure(figsize=(3.5, 2.7))
    else:
        plt.figure(figsize=(7.5, 5.0))
    order = [lbl for _, lbl in sorted({(exp, lbl) for exp, lbl in zip(df["target_exp"], df["target_label"])})]
    ax = sns.lineplot(
        data=df,
        x="input_preFEC_BER",
        y="rate",
        hue="target_label",
        hue_order=order,
        marker="o",
        style="target_label",
        dashes=False,
        linewidth=lw,
        markersize=ms,
    )
    ax.set_xscale("log")
    if paper:
        ax.set_xlabel("")
        ax.set_ylabel("")
    else:
        ax.set_xlabel("Input pre-FEC BER")
        ax.set_ylabel("Code rate (k/n)")
    if not paper:
        ax.set_title("RS Code Rate vs Input BER")
    ax.set_ylim(0.43, 1.01)
    ax.grid(True, which="both", linestyle=":", linewidth=0.5)
    leg = ax.get_legend()
    if leg is not None:
        leg.remove()
    if df["target_label"].nunique() > 1:
        ax.legend(title="Target post-FEC BER", fontsize=14 if paper else None, title_fontsize=14 if paper else None)
    plt.tight_layout()
    outpath.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(outpath)
    plt.close()


def plot_energy_rate_combined(
    df: pd.DataFrame,
    outpath: Path,
    style: str,
    *,
    paper: bool = False,
    paper_left: float = 0.125,
    paper_right: float = 0.993,
    paper_bottom: float = 0.162,
    paper_top: float = 0.953,
    paper_wspace: float = 0.35,
    debug_clip: bool = False,
) -> None:
    """Two-panel paper figure: (left) pJ/bit vs input BER, (right) rate vs input BER."""

    effective_style = "whitegrid" if (paper and style == "darkgrid") else style
    sns.set_style(effective_style)

    # Drop the K=N "no-FEC" operating point for the combined paper figure.
    # It can show up with pj_per_bit=0 (bypass / missing power data) and would
    # both break log-y plotting and skew the shared-x range into ultra-low BERs.
    df_plot = df.copy()
    k_num = pd.to_numeric(df_plot.get("K"), errors="coerce")
    n_num = pd.to_numeric(df_plot.get("N"), errors="coerce")
    if (k_num.notna() & n_num.notna()).any():
        df_plot = df_plot[~(k_num == n_num)].copy()

    if paper:
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
        fig, (ax_energy, ax_rate) = plt.subplots(1, 2, figsize=(3.5, 1.7), sharex=True)
    else:
        fig, (ax_energy, ax_rate) = plt.subplots(1, 2, figsize=(7.5, 3.0), sharex=True)

    lw = 2.0
    ms = 3.0 if paper else 4.0

    # Order targets for consistent legend
    order = [
        lbl
        for _, lbl in sorted(
            {(exp, lbl) for exp, lbl in zip(df_plot["target_exp"], df_plot["target_label"])}
        )
    ]
    colors = sns.color_palette("tab10", len(order)) if order else []
    label_to_color = dict(zip(order, colors))
    energy_ymin = 1e-2
    for target_label in order:
        sub = df_plot[df_plot["target_label"] == target_label].sort_values("input_preFEC_BER")
        if sub.empty:
            continue
        pj = pd.to_numeric(sub["pj_per_bit"], errors="coerce").astype(float)
        m_energy = (pj > 0.0) & np.isfinite(pj)
        ax_energy.plot(
            sub.loc[m_energy, "input_preFEC_BER"],
            pj[m_energy],
            marker="o",
            linewidth=lw,
            markersize=ms,
            color=label_to_color.get(target_label, None),
            label=target_label,
        )
        ax_rate.plot(
            sub["input_preFEC_BER"],
            sub["rate"],
            marker="o",
            linewidth=lw,
            markersize=ms,
            color=label_to_color.get(target_label, None),
            label=target_label,
        )

    ax_energy.set_xscale("log")
    ax_energy.set_yscale("log")
    ax_rate.set_xscale("log")
    if paper:
        ax_rate.set_ylim(0.4, 1.0)
        ax_rate.yaxis.set_major_locator(ticker.FixedLocator([0.4, 0.6, 0.8, 1.0]))
    else:
        ax_rate.set_ylim(0.43, 1.01)

    # Paper-friendly log-y ticks (avoid minor-grid clutter).
    pj_vals = pd.to_numeric(df_plot["pj_per_bit"], errors="coerce").astype(float)
    pj_vals = pj_vals[(pj_vals > 0.0) & np.isfinite(pj_vals)].copy()
    if not pj_vals.empty:
        y_min = float(pj_vals.min())
        y_max = float(pj_vals.max())
        y_bottom = 10.0 ** math.floor(math.log10(max(y_min, energy_ymin)))
        y_bottom = max(y_bottom, energy_ymin)
        y_top = 10.0 ** math.ceil(math.log10(max(y_max, energy_ymin)))
        if y_top <= y_bottom:
            y_top = y_bottom * 10.0
        if paper and y_min >= 0.4:
            y_bottom = 0.4
        ax_energy.set_ylim(y_bottom, y_top)
        ticks_all = [1e-2, 1e-1, 1e0, 1e1, 1e2]
        ticks = [v for v in ticks_all if y_bottom <= v <= y_top * 1.0000001]
        ax_energy.yaxis.set_major_locator(ticker.FixedLocator(ticks))
    ax_energy.yaxis.set_major_formatter(ticker.LogFormatterMathtext(base=10))
    ax_energy.yaxis.set_minor_locator(ticker.NullLocator())

    for ax in (ax_energy, ax_rate):
        if paper:
            ax.set_xlabel("")
            ax.set_ylabel("")
        ax.grid(True, which="both", linestyle=":", linewidth=0.5)

    # Handle legends: remove axis legends; add a shared legend only if needed.
    if df_plot["target_label"].nunique() > 1:
        handles, labels = ax_energy.get_legend_handles_labels()
        if handles:
            fig.legend(
                handles,
                labels,
                loc="lower center",
                ncol=min(3, len(labels)),
                framealpha=1.0,
                facecolor="white",
                bbox_to_anchor=(0.5, 0.02),
                fontsize=7 if paper else None,
                title_fontsize=7 if paper else None,
                handlelength=1.1,
                handletextpad=0.35,
                borderpad=0.2,
                labelspacing=0.2,
                columnspacing=0.7,
            )
            if paper:
                # Leave extra bottom margin for the shared legend and extra top margin
                # for mathtext ticks (e.g., 10^1) which otherwise get clipped.
                fig.subplots_adjust(
                    left=paper_left,
                    right=paper_right,
                    bottom=max(paper_bottom, 0.28),
                    top=paper_top,
                    wspace=paper_wspace,
                )
            else:
                fig.tight_layout(rect=(0.0, 0.12, 1.0, 1.0))
        else:
            if paper:
                fig.subplots_adjust(
                    left=paper_left,
                    right=paper_right,
                    bottom=paper_bottom,
                    top=paper_top,
                    wspace=paper_wspace,
                )
            else:
                fig.tight_layout()
    else:
        if paper:
            fig.subplots_adjust(
                left=paper_left,
                right=paper_right,
                bottom=paper_bottom,
                top=paper_top,
                wspace=paper_wspace,
            )
        else:
            fig.tight_layout()

    outpath.parent.mkdir(parents=True, exist_ok=True)
    if paper and debug_clip:
        _print_tightbbox_slack(fig, label=str(outpath))
    if paper:
        fig.savefig(outpath.with_suffix(".pdf"))
        fig.savefig(outpath.with_suffix(".png"), dpi=180)
    else:
        fig.savefig(outpath.with_suffix(".pdf"), bbox_inches="tight")
        fig.savefig(outpath.with_suffix(".png"), dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    args = parse_args()

    sel_df = load_selection(args.selection)
    if args.target_post_ber is not None:
        before = len(sel_df)
        sel_df = sel_df[sel_df["target_post_BER"] == float(args.target_post_ber)].copy()
        if sel_df.empty:
            raise ValueError(
                f"--target-post-ber={args.target_post_ber:g} filtered selection CSV to 0 rows (started with {before})."
            )
    sum_df = load_summary(args.summary)

    # Merge summary for required tops
    if args.gated:
        merged = merge_selection_power_single(sel_df, sum_df, args.syndrome_top, prefix="syn_")
        merged = merge_selection_power_single(merged, sum_df, args.decoder_top, prefix="dec_")
        if args.include_encoder:
            merged = merge_selection_power_single(merged, sum_df, args.encoder_top, prefix="enc_")
        # Drop rows missing power for either top
        before = len(merged)
        needed = ["syn_total_dyn_mw", "syn_CLK_NS", "dec_total_dyn_mw", "dec_CLK_NS"]
        if args.include_encoder:
            needed += ["enc_total_dyn_mw", "enc_CLK_NS"]
        merged = merged.dropna(subset=needed).copy()
        missing = before - len(merged)
        if missing:
            print(f"Warning: {missing} selection rows lack matching (N,K) for syndrome/decoder and were dropped.")

        # Compute pJ/bit for each block with their own cycles-per-symbol
        syn_cycles = args.syndrome_cycles_per_symbol
        if syn_cycles is None:
            syn_cycles = _default_cycles_for_top(args.syndrome_top, merged)
        metrics = compute_metrics_single_top(merged, syn_cycles, prefix="syn_")

        dec_cycles = args.decoder_cycles_per_symbol
        if dec_cycles is None:
            dec_cycles = _default_cycles_for_top(args.decoder_top, merged)
        metrics = compute_metrics_single_top(metrics, dec_cycles, prefix="dec_")
        if args.include_encoder:
            enc_cycles = args.encoder_cycles_per_symbol
            if enc_cycles is None:
                enc_cycles = _default_cycles_for_top(args.encoder_top, merged)
            metrics = compute_metrics_single_top(metrics, enc_cycles, prefix="enc_")

        # Compute corrected-codeword probability and effective pJ/bit (gated)
        corr_probs = []
        for _, r in metrics.iterrows():
            n = int(r["N"]) if not pd.isna(r["N"]) else None
            t = int(r["t"]) if not pd.isna(r["t"]) else 0
            m_bits = int(r["m"]) if not pd.isna(r["m"]) else 8
            p_b = float(r["input_preFEC_BER"]) if not pd.isna(r["input_preFEC_BER"]) else 0.0
            pc = corrected_codeword_probability(n, t, m_bits, p_b) if (n is not None) else 0.0
            corr_probs.append(pc)
        metrics["p_correctable"] = corr_probs
        rx_pj = metrics["syn_pj_per_bit"] + metrics["p_correctable"] * metrics["dec_pj_per_bit"]
        metrics["rx_pj_per_bit"] = rx_pj
        if args.include_encoder:
            metrics["total_pj_per_bit"] = metrics["enc_pj_per_bit"] + rx_pj
        else:
            metrics["total_pj_per_bit"] = rx_pj
        # For reference, set nominal throughput columns from decoder path (slow path)
        metrics["fclk_hz"] = metrics["dec_fclk_hz"]
        metrics["throughput_bps"] = metrics["dec_throughput_bps"]
    else:
        merged = merge_selection_power_single(sel_df, sum_df, args.top, prefix="")
        if args.include_encoder:
            merged = merge_selection_power_single(merged, sum_df, args.encoder_top, prefix="enc_")
        before = len(merged)
        needed = ["total_dyn_mw", "CLK_NS"]
        if args.include_encoder:
            needed += ["enc_total_dyn_mw", "enc_CLK_NS"]
        merged = merged.dropna(subset=needed).copy()
        missing = before - len(merged)
        if missing:
            print(f"Warning: {missing} selection rows lack matching (N,K) in summary and were dropped.")

        cycles = args.cycles_per_symbol
        if cycles is None:
            cycles = _default_cycles_for_top(args.top, merged)
        metrics = compute_metrics_single_top(merged, cycles, prefix="")
        if args.include_encoder:
            enc_cycles = args.encoder_cycles_per_symbol
            if enc_cycles is None:
                enc_cycles = _default_cycles_for_top(args.encoder_top, merged)
            metrics = compute_metrics_single_top(metrics, enc_cycles, prefix="enc_")
            metrics["total_pj_per_bit"] = metrics["enc_pj_per_bit"] + metrics["pj_per_bit"]
        else:
            metrics["total_pj_per_bit"] = metrics["pj_per_bit"]

    # Prepare nicely formatted target labels for legend
    def _fmt_label(x: float) -> str:
        if x <= 0:
            return str(x)
        exp = int(round(np.log10(x)))
        return f"1e{exp}"
    metrics["target_exp"] = metrics["target_post_BER"].apply(lambda v: int(round(np.log10(v))) if v > 0 else 0)
    metrics["target_label"] = metrics["target_post_BER"].apply(_fmt_label)

    # Drop the K=N "no-FEC" operating point for vs-BER plots/CSVs. It has
    # pj_per_bit=0 by construction and can both break log-y plotting and skew
    # the x-range into ultra-low BERs (visible as an extra "tail").
    metrics_plot = metrics.copy()
    k_num = pd.to_numeric(metrics_plot.get("K"), errors="coerce")
    n_num = pd.to_numeric(metrics_plot.get("N"), errors="coerce")
    if (k_num.notna() & n_num.notna()).any():
        metrics_plot = metrics_plot[~(k_num == n_num)].copy()

    # Outputs directory and basenames
    outdir = args.outdir
    outdir.mkdir(parents=True, exist_ok=True)
    pj_base = outdir / "rscodec_pj_per_bit_vs_input_BER"
    rate_base = outdir / "rscodec_rate_vs_input_BER"

    # Plots
    # Plot uses total energy per bit
    plot_df = metrics_plot.copy()
    plot_df["pj_per_bit"] = plot_df["total_pj_per_bit"]
    plot_pj_per_bit_vs_ber(plot_df, pj_base.with_suffix('.pdf'), args.style, paper=bool(args.paper))
    plot_pj_per_bit_vs_ber(plot_df, pj_base.with_suffix('.png'), args.style, paper=bool(args.paper))
    plot_rate_vs_ber(metrics_plot, rate_base.with_suffix('.pdf'), args.style, paper=bool(args.paper))
    plot_rate_vs_ber(metrics_plot, rate_base.with_suffix('.png'), args.style, paper=bool(args.paper))
    plot_energy_rate_combined(
        plot_df,
        outdir / "rscodec_energy_rate_vs_input_BER",
        args.style,
        paper=bool(args.paper),
        paper_left=float(args.paper_left),
        paper_right=float(args.paper_right),
        paper_bottom=float(args.paper_bottom),
        paper_top=float(args.paper_top),
        paper_wspace=float(args.paper_wspace),
        debug_clip=bool(args.debug_clip),
    )

    # Raw CSVs
    pj_cols = [
        "target_post_BER", "target_label", "input_preFEC_BER", "N", "K", "t", "rate", "m",
        "total_pj_per_bit"
    ]
    # Optional detailed columns
    if args.include_encoder:
        pj_cols += ["enc_CLK_NS", "enc_total_dyn_mw", "enc_pj_per_bit"]
    if args.gated:
        pj_cols += [
            "syn_CLK_NS", "syn_total_dyn_mw", "syn_pj_per_bit",
            "dec_CLK_NS", "dec_total_dyn_mw", "dec_pj_per_bit",
            "p_correctable", "rx_pj_per_bit",
        ]
    else:
        pj_cols += [
            "CLK_NS", "total_dyn_mw", "fclk_hz", "throughput_bps", "pj_per_bit"
        ]
    pj_df = metrics_plot.loc[:, [c for c in pj_cols if c in metrics_plot.columns]].sort_values(
        ["target_post_BER", "input_preFEC_BER"]
    )
    pj_df.to_csv(pj_base.with_suffix('.csv'), index=False)

    rate_cols = ["target_post_BER", "target_label", "input_preFEC_BER", "N", "K", "t", "rate"]
    rate_df = metrics_plot.loc[:, [c for c in rate_cols if c in metrics_plot.columns]].sort_values(
        ["target_post_BER", "input_preFEC_BER"]
    )
    rate_df.to_csv(rate_base.with_suffix('.csv'), index=False)

    print(f"Wrote plots and CSVs to: {outdir}")


if __name__ == "__main__":
    main()
