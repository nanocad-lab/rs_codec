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
BER_TARGETS = (1e-12, 1e-15, 1e-20, 1e-25, 1e-30)
LOG_BER_MARGIN = 1e-3
LOG_MIN_VALUE = 1e-300


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


def lookup_fec_area_per_gbps(
    area_df: Optional[pd.DataFrame],
    tech: str,
    target_ber: float,
    input_ber: float,
) -> float:
    if area_df is None or area_df.empty:
        return float("nan")

    data = area_df[area_df["tech"] == tech]
    if data.empty:
        return float("nan")

    target_rows = rows_matching_log_ber(data, "target_post_BER", target_ber)
    if not target_rows.empty:
        data = target_rows

    if "input_preFEC_BER" not in data.columns or "area_per_gbps" not in data.columns:
        return float("nan")

    series = data["input_preFEC_BER"].astype(float)
    positive = series > 0.0
    if not positive.any():
        return float("nan")

    log_input = math.log10(max(input_ber, LOG_MIN_VALUE))
    log_values = series[positive].map(lambda value: math.log10(value))
    distances = (log_values - log_input).abs()
    idx = distances.idxmin()
    return float(data.loc[idx, "area_per_gbps"])


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

    area_path = ROOT / "plots" / "area_per_gbps_vs_ber.csv"
    if area_path.exists():
        area_df: Optional[pd.DataFrame] = pd.read_csv(area_path)
        for col in ["target_post_BER", "input_preFEC_BER", "area_per_gbps"]:
            if col in area_df.columns:
                area_df[col] = area_df[col].astype(float)
    else:
        area_df = None

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
            fec_area_per_gbps = lookup_fec_area_per_gbps(area_df, dataset, target_ber, link_ber)

            if link_ber > target_ber and log_ber_distance(link_ber, target_ber) > LOG_BER_MARGIN:
                target_df = fec_df
                if "BER Target" in fec_df.columns:
                    target_rows = rows_matching_log_ber(fec_df, "BER Target", target_ber)
                    if not target_rows.empty:
                        target_df = target_rows

                fec_row = closest_row_by_ber(target_df, link_ber)
                if "t" in fec_row and not pd.isna(fec_row["t"]) and int(fec_row["t"]) == 0:
                    code_rate = 1.0
                    fec_energy = 0.0
                    fec_energy_scaled = 0.0
                else:
                    code_rate = float(fec_row["rate"])
                    fec_energy = float(fec_row["energy"])
                    fec_energy_scaled = fec_energy * (energy_factor_target / energy_factor_base)

                fec_area_per_gbps = lookup_fec_area_per_gbps(
                    area_df,
                    dataset,
                    target_ber,
                    float(fec_row.get("input_preFEC_BER", link_ber)),
                )

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
                }
            )

    return pd.DataFrame(rows)


def write_outputs(df: pd.DataFrame) -> None:
    df_sorted = df.sort_values(["Name", "BER_target"]).reset_index(drop=True)
    out_csv = ROOT / "plots" / "reach_vs_fom_scaled.csv"
    df_sorted.to_csv(out_csv, index=False)

    sns.set_style("darkgrid")
    fig, ax = plt.subplots(figsize=(8, 5))
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
