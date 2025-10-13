#!/usr/bin/env python3
"""Generate raw and FEC-corrected FoM tables and plots."""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import math
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BER_TARGETS = (1e-15, 1e-30)
LOG_BER_MARGIN = 1e-3
LOG_MIN_VALUE = 1e-300
SUMMARY_ROOT_CANDIDATES = (ROOT / "paperdata",)
ENCODER_TOP = "rs_encoder_wrapper"
SYNDROME_TOP = "rs_syndrome"
DECODER_TOP = "rs_decoder"
@dataclass(frozen=True)
class ScalingModel:
    node_nm: int
    coeffs: tuple[float, float, float]
    vdd: float

    def energy_factor(self) -> float:
        a2, a1, a0 = self.coeffs
        v = self.vdd
        return a2 * v**2 + a1 * v + a0


ENERGY_MODELS = {
    45: ScalingModel(45, (1.018, -0.3107, 0.1539), 1.10),
    32: ScalingModel(32, (0.8367, -0.4341, 0.1701), 0.97),
    20: ScalingModel(20, (0.3730, -0.1582, 0.04104), 0.90),
    16: ScalingModel(16, (0.2958, -0.1241, 0.03024), 0.86),
    14: ScalingModel(14, (0.2363, -0.09675, 0.02239), 0.86),
    10: ScalingModel(10, (0.2068, -0.09311, 0.02375), 0.83),
     7: ScalingModel(7, (0.1776, -0.09097, 0.02447), 0.80),
}

TSMC_SUB7_SCALING = {
    # Public TSMC guidance: N5 ~30% power reduction vs N7, N3 ~30% vs N5.
    # Values are relative multipliers to ASAP7's energy factor.
    5: 0.70,
    3: 0.49,  # 0.70 (N5/N7) * 0.70 (N3/N5)
}


BASE_DATASET_NODES = {
    "ASAP7": 7,
    "NanGate45": 45,
}


def choose_dataset(process_nm: float) -> str:
    # ASAP7 models advanced nodes; NanGate45 covers larger processes.
    return "ASAP7" if process_nm <= 16 else "NanGate45"


def map_process_to_model(process_nm: float) -> int:
    # Map an arbitrary process to the closest defined scaling model.
    return min(ENERGY_MODELS.keys(), key=lambda node: abs(process_nm - node))


def tsmc_scaling_factor(process_nm: float) -> tuple[float, int]:
    key = min(TSMC_SUB7_SCALING.keys(), key=lambda node: abs(process_nm - node))
    return TSMC_SUB7_SCALING[key], key


def load_links(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = df.rename(columns={"Reach (mm)": "Reach_mm", "Gbps/mm": "Gbps_per_mm", "pJ/bit": "pJ_per_bit"})
    return df


def rows_matching_log_ber(df: pd.DataFrame, column: str, target: float) -> pd.DataFrame:
    if column not in df.columns or target <= 0.0:
        return df.iloc[0:0]

    series = df[column].astype(float)
    positive = series > 0.0
    if not positive.any():
        return df.iloc[0:0]

    log_target = math.log10(target)
    log_values = series[positive].map(lambda value: math.log10(value))
    distances = (log_values - log_target).abs()
    min_distance = distances.min()
    tolerance = 1e-12
    matching_idx = distances[distances <= min_distance + tolerance].index
    return df.loc[matching_idx]


def log_ber_distance(a: float, b: float) -> float:
    if a <= 0.0 or b <= 0.0:
        return float("inf")
    return abs(math.log10(a) - math.log10(b))


def corrected_codeword_probability(n: int, t: int, m_bits: int, p_b: float) -> float:
    if t <= 0 or p_b <= 0.0:
        return 0.0
    if p_b >= 1.0:
        return 1.0

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


def _lookup_df(table_multi: pd.DataFrame, table_single: Optional[pd.DataFrame], n: int, k: int, column: str) -> float:
    if isinstance(table_multi.index, pd.MultiIndex):
        key = (n, k)
        if key in table_multi.index:
            value = table_multi.loc[key, column]
            if isinstance(value, pd.Series):
                value = value.iloc[0]
            return float(value)
    if table_single is not None and n in table_single.index:
        value = table_single.loc[n, column]
        if isinstance(value, pd.Series):
            value = value.iloc[0]
        return float(value)
    raise KeyError(f"No entry for N={n}, K={k} in column '{column}'")


def _lookup_series(series_multi: pd.Series, series_single: Optional[pd.Series], n: int, k: int) -> float:
    if isinstance(series_multi.index, pd.MultiIndex):
        key = (n, k)
        if key in series_multi.index:
            value = series_multi.loc[key]
            if isinstance(value, pd.Series):
                value = value.iloc[0]
            return float(value)
    if series_single is not None and n in series_single.index:
        value = series_single.loc[n]
        if isinstance(value, pd.Series):
            value = value.iloc[0]
        return float(value)
    raise KeyError(f"No GF entry for N={n}, K={k}")


def load_summary_tables() -> dict[str, dict[str, pd.DataFrame]]:
    tables: dict[str, dict[str, pd.DataFrame]] = {}
    for tech in BASE_DATASET_NODES:
        path = find_summary_path(tech)
        summary = pd.read_csv(path)
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
        energy_map_n = summary.pivot_table(index="N", columns="top", values="energy_pj_per_bit")
        area_map = summary.pivot_table(index=["N", "K"], columns="top", values="area")
        area_map_n = summary.pivot_table(index="N", columns="top", values="area")
        clk_map = summary.pivot_table(index=["N", "K"], columns="top", values="CLK_NS")
        clk_map_n = summary.pivot_table(index="N", columns="top", values="CLK_NS")
        gf_map = summary.set_index(["N", "K"])["GF_WIDTH"].sort_index()
        gf_map_n = summary.groupby("N")["GF_WIDTH"].first()

        tables[tech] = {
            "energy": energy_map,
            "energy_n": energy_map_n,
            "area": area_map,
            "area_n": area_map_n,
            "clk": clk_map,
            "clk_n": clk_map_n,
            "gf": gf_map,
            "gf_n": gf_map_n,
        }

    return tables


def closest_row_by_ber(df: pd.DataFrame, target_ber: float) -> pd.Series:
    ber_col = "plot_ber" if "plot_ber" in df.columns else "input_preFEC_BER"
    ber_values = df[ber_col].astype(float)
    meets_target = ber_values >= target_ber

    if meets_target.any():
        subset = df.loc[meets_target]
        if "t" in subset.columns:
            subset = subset.sort_values(["t", ber_col], ascending=[True, True])
        else:
            subset = subset.sort_values(ber_col, ascending=True)
        return subset.iloc[0]

    subset = df
    if "t" in subset.columns:
        subset = subset.sort_values(["t", ber_col], ascending=[False, False])
    else:
        subset = subset.sort_values(ber_col, ascending=False)
    return subset.iloc[0]


def compute_metrics() -> pd.DataFrame:
    links = load_links(ROOT / "link_examples.csv")
    fec_data = {
        name: pd.read_csv(ROOT / "plots" / f"{name.lower()}_total_energy_rate_vs_ber.csv")
        for name in BASE_DATASET_NODES
    }

    summary_tables = load_summary_tables()

    rows = []
    for _, link in links.iterrows():
        process_nm = link["Process"]
        dataset = choose_dataset(process_nm)
        base_node = BASE_DATASET_NODES[dataset]
        fec_df = fec_data[dataset]
        link_ber = float(link["BER"])

        fec_df = fec_df.copy()
        if "BER Target" in fec_df.columns:
            fec_df["BER Target"] = fec_df["BER Target"].astype(float)

        energy_factor_base = ENERGY_MODELS[base_node].energy_factor()
        if process_nm < 7:
            tsmc_scale, tsmc_ref = tsmc_scaling_factor(process_nm)
            energy_factor_target = energy_factor_base * tsmc_scale
            target_node = tsmc_ref
            scaling_source = f"TSMC_public_{tsmc_ref}nm"
        else:
            target_node = map_process_to_model(process_nm)
            energy_factor_target = ENERGY_MODELS[target_node].energy_factor()
            scaling_source = f"Polynomial_{target_node}nm"

        gbps_per_mm = link["Gbps_per_mm"]
        link_energy = link["pJ_per_bit"]
        reach_mm = link["Reach_mm"]

        for target_ber in BER_TARGETS:
            code_rate = 1.0
            fec_energy = 0.0
            fec_energy_scaled = 0.0
            fec_area_per_gbps = 0.0

            per_block = {
                "encoder": 0.0,
                "syndrome": 0.0,
                "decoder": 0.0,
            }

            p_corr = 0.0

            if link_ber > target_ber and log_ber_distance(link_ber, target_ber) > LOG_BER_MARGIN:
                target_df = fec_df
                if "BER Target" in fec_df.columns:
                    target_rows = rows_matching_log_ber(fec_df, "BER Target", target_ber)
                    if not target_rows.empty:
                        target_df = target_rows

                if "t" in target_df.columns:
                    correcting_df = target_df[target_df["t"] > 0]
                    if not correcting_df.empty:
                        target_df = correcting_df

                fec_row = closest_row_by_ber(target_df, link_ber)
                tables = summary_tables.get(dataset)
                if tables is None:
                    pass
                else:
                    n = int(fec_row.get("n", 0)) if "n" in fec_row else 0
                    t = int(fec_row.get("t", 0)) if "t" in fec_row else 0
                    k_val = int(fec_row.get("k", 0)) if "k" in fec_row else 0

                    if t != 0 and n > 0 and k_val > 0 and k_val < n:
                        energy_map = tables["energy"]
                        energy_map_n = tables.get("energy_n")
                        area_map = tables["area"]
                        area_map_n = tables.get("area_n")
                        clk_map = tables["clk"]
                        clk_map_n = tables.get("clk_n")
                        gf_map = tables["gf"]
                        gf_map_n = tables.get("gf_n")

                        try:
                            enc_energy = _lookup_df(energy_map, energy_map_n, n, k_val, ENCODER_TOP)
                            syn_energy = _lookup_df(energy_map, energy_map_n, n, k_val, SYNDROME_TOP)
                            dec_energy = _lookup_df(energy_map, energy_map_n, n, k_val, DECODER_TOP)
                            symbol_bits = int(_lookup_series(gf_map, gf_map_n, n, k_val))
                        except KeyError:
                            pass
                        else:
                            code_rate = float(fec_row.get("rate", code_rate))
                            p_corr = corrected_codeword_probability(n, t, symbol_bits, link_ber)

                            fec_energy = enc_energy + syn_energy + p_corr * (dec_energy - syn_energy)
                            fec_energy_scaled = fec_energy * (energy_factor_target / energy_factor_base)

                            per_block = {
                                "encoder": enc_energy,
                                "syndrome": syn_energy,
                                "decoder": dec_energy,
                            }

                            try:
                                area_encoder = _lookup_df(area_map, area_map_n, n, k_val, ENCODER_TOP)
                                area_syndrome = _lookup_df(area_map, area_map_n, n, k_val, SYNDROME_TOP)
                                area_decoder = _lookup_df(area_map, area_map_n, n, k_val, DECODER_TOP)
                                clk_ns = _lookup_df(clk_map, clk_map_n, n, k_val, DECODER_TOP)
                                decoder_cycles = (2.0 ** symbol_bits) / k_val
                                throughput_bps = code_rate * symbol_bits / (decoder_cycles * clk_ns * 1e-9)
                                if throughput_bps > 0:
                                    throughput_gbps = throughput_bps / 1e9
                                    fec_area_per_gbps = (area_total_um2 := area_encoder + area_syndrome + area_decoder) / 1e6 / throughput_gbps
                                else:
                                    fec_area_per_gbps = float("nan")
                            except KeyError:
                                fec_area_per_gbps = float("nan")

            fom_raw = gbps_per_mm / link_energy
            numerator = gbps_per_mm * code_rate
            denom_unscaled = (link_energy / code_rate) + fec_energy
            denom_scaled = (link_energy / code_rate) + fec_energy_scaled

            rows.append(
                {
                    "Name": link["Name"],
                    "Process_nm": process_nm,
                    "Reach_mm": reach_mm,
                    "Gbps_per_mm": gbps_per_mm,
                    "Link_pJ_per_bit": link_energy,
                    "BER": link_ber,
                    "BER_target": target_ber,
                    "Chosen_FEC_dataset": dataset,
                    "Base_node_nm": base_node,
                    "Target_model_node_nm": target_node,
                    "FEC_code_rate": code_rate,
                    "FEC_energy_pJ_source": fec_energy,
                    "FEC_energy_pJ_scaled": fec_energy_scaled,
                    "FoM_raw": fom_raw,
                    "FoM_fec_unscaled": numerator / denom_unscaled,
                    "FoM_fec_scaled": numerator / denom_scaled,
                    "Energy_factor_base": energy_factor_base,
                    "Energy_factor_target": energy_factor_target,
                    "Energy_scaling_source": scaling_source,
                    "FEC_area_per_gbps_scaled": fec_area_per_gbps,
                    "FEC_p_correctable": p_corr,
                    "FEC_encoder_energy_pJ": per_block["encoder"],
                    "FEC_syndrome_energy_pJ": per_block["syndrome"],
                    "FEC_decoder_energy_pJ": per_block["decoder"],
                }
            )

    return pd.DataFrame(rows)


def write_outputs(df: pd.DataFrame) -> None:
    df_sorted = df.sort_values(["Name", "BER_target"]).reset_index(drop=True)
    out_csv = ROOT / "plots" / "reach_vs_fom_scaled.csv"
    df_sorted.to_csv(out_csv, index=False)

    sns.set_style("darkgrid")
    fig, ax = plt.subplots(figsize=(8/1.3, 5/1.3))
    ordered_names = list(dict.fromkeys(df_sorted["Name"]))
    colors = sns.color_palette("tab10", len(ordered_names))
    name_to_color = dict(zip(ordered_names, colors))

    target_markers = {
        1e-12: "x",
        1e-15: "+",
        1e-20: "s",
        1e-25: "d",
        1e-30: "^",
    }

    for name in ordered_names:
        group = df_sorted[df_sorted["Name"] == name]
        if group.empty:
            continue

        color = name_to_color[name]
        reach = group.iloc[0]["Reach_mm"]
        fom_raw = group.iloc[0]["FoM_raw"]

        ax.scatter(reach, fom_raw, marker="1", color=color, s=55)
        ax.annotate(
            name,
            (reach, fom_raw),
            textcoords="offset points",
            xytext=(6, 4),
            fontsize=8,
            color=color,
        )

        for _, row in group.iterrows():
            target_ber = row["BER_target"]
            marker = target_markers.get(target_ber, "D")
            fom_scaled = row["FoM_fec_scaled"]

            ax.scatter(reach, fom_scaled, marker=marker, color=color, s=55)
            ax.plot([reach, reach], [fom_raw, fom_scaled], color=color, linewidth=0.9)

    ax.set_xscale("log")
    ax.set_xlim(xmax=1e5)
    ax.set_yscale("log")
    ax.set_xlabel("Reach (mm)")
    ax.set_ylabel("FoM (Gbps/mm)/(pJ/bit)")
    formatted_targets = ", ".join(f"{t:.0e}" for t in BER_TARGETS)
    ax.set_title(f"Reach vs FoM (Raw vs FEC @ {formatted_targets})")
    ax.grid(True, which="both", linestyle="--", linewidth=0.6)

    from matplotlib.lines import Line2D

    legend_handles = [
        Line2D([0], [0], marker="1", color="black", markerfacecolor="black", markersize=6, linestyle="None", label="Raw FoM")
    ]
    for target_ber in BER_TARGETS:
        marker = target_markers[target_ber]
        legend_handles.append(
            Line2D(
                [0],
                [0],
                marker=marker,
                color="black",
                markerfacecolor="black",
                markersize=6,
                linestyle="None",
                label=f"FEC FoM @ {target_ber:.0e}",
            )
        )
    ax.legend(handles=legend_handles, loc="lower left")

    fig.tight_layout()
    fig.savefig(ROOT / "plots" / "reach_vs_fom_raw_vs_fec.png", dpi=200)


def main() -> None:
    df = compute_metrics()
    write_outputs(df)


if __name__ == "__main__":
    main()
