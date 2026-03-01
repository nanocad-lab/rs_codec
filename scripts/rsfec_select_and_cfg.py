#!/usr/bin/env python3
"""RS-FEC selector and synthesis-config generator (n=86 over GF(2^8))."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict

import pandas as pd

# ---------- Parameters ----------
m = 8
n_fixed = 86

# Input/output BER design points (override as needed)
worst_input_preFEC_BER = 1e-3
worst_target_post_BER = 1e-27

# Targets to characterize; selection CSV will include thresholds for each
targets = [1e-12, 1e-15, 1e-20, 1e-25, 1e-27]

# Binary-search termination: stop when upper/lower differ by <= this many decades
LOG_BER_TOL = 1e-3
LOG_MIN_VALUE = 1e-300

# Search K values from highest-rate (t = 1) downward in odd steps.
k_max = n_fixed - 2
k_min = 2  # minimum data symbols to explore (adjust as needed)
k_candidates = [k for k in range(k_max, k_min - 1, -2)]

# Synthesis-config formatting
LIB = "-"  # Use '-' placeholder; pass DEFAULT_LIB_DIR at synthesis time.
clock_ps = 5000.0  # 5.0 ns
# -------------------------------

class SelectionResult(TypedDict):
    n: int
    k: int
    m: int
    t: int
    rate: float
    post_ber_est: float


def symbol_error_from_bit_error(p_b: float, m: int) -> float:
    return 1.0 - (1.0 - p_b) ** m

def rs_post_ber(p_b: float, n: int, k: int, m: int) -> float:
    """Approximate post-FEC BER for RS(n,k) over GF(2^m)."""
    if n < k + 2 or ((n - k) % 2) != 0:
        raise ValueError("Invalid RS(n,k): need n >= k+2 and (n-k) even.")
    t = (n - k) // 2
    p_s = symbol_error_from_bit_error(p_b, m)
    if p_s <= 0.0:
        return 0.0
    if p_s >= 1.0:
        return 0.5

    # Binomial tail with weighting 0.5*(i/n); compute in log domain for stability.
    log1m = math.log1p(-p_s)
    logfact = [0.0]
    for i in range(1, n + 1):
        logfact.append(logfact[-1] + math.log(i))
    def logC(nv: int, iv: int) -> float:
        return logfact[nv] - logfact[iv] - logfact[nv - iv]

    ber = 0.0
    for i in range(t + 1, n + 1):
        logpmf = logC(n, i) + i * math.log(p_s) + (n - i) * log1m
        pmf = math.exp(logpmf)
        ber += 0.5 * (i / n) * pmf
    return ber

def best_k_for_target(p_b: float, target: float) -> Optional[SelectionResult]:
    """Return the highest-rate RS(n_fixed,k) that meets the target (if any)."""
    for k in k_candidates:
        post = rs_post_ber(p_b, n_fixed, k, m)
        if post <= target:
            return {
                "n": n_fixed,
                "k": k,
                "m": m,
                "t": (n_fixed - k) // 2,
                "rate": k / n_fixed,
                "post_ber_est": post,
            }
    return None


def minimal_n_for_target(p_b: float, target: float, k: int) -> Optional[SelectionResult]:
    """Compatibility helper for scripts that expect per-k evaluation."""
    if (n_fixed - k) % 2 != 0 or k > n_fixed or k < k_min:
        return None
    post = rs_post_ber(p_b, n_fixed, k, m)
    if post > target:
        return None
    return {
        "n": n_fixed,
        "k": k,
        "m": m,
        "t": (n_fixed - k) // 2,
        "rate": k / n_fixed,
        "post_ber_est": post,
    }


def choose_best_over_k(p_b: float, target: float) -> Optional[SelectionResult]:
    return best_k_for_target(p_b, target)


def max_input_ber_for_target(
    n: int,
    k: int,
    m_bits: int,
    target: float,
    p_max: float,
    *,
    tol: float = 1e-6,
    max_iter: int = 100,
) -> tuple[float, float]:
    """Return (p_b, post_ber) for the largest input BER meeting the target."""

    if target <= 0.0:
        return 0.0, 0.0

    upper_limit = 0.5
    lower = 0.0
    post_lower = rs_post_ber(lower, n, k, m_bits)
    if post_lower > target:
        raise RuntimeError(
            f"RS({n},{k}) cannot reach target {target} even at zero input BER"
        )

    upper = float(max(p_max, 1e-12))
    post_upper = rs_post_ber(upper, n, k, m_bits)

    if post_upper <= target:
        while upper < upper_limit and post_upper <= target:
            lower = upper
            post_lower = post_upper
            next_upper = upper * 2.0 if upper > 0.0 else 1e-12
            if next_upper <= upper:
                break
            upper = min(upper_limit, next_upper)
            post_upper = rs_post_ber(upper, n, k, m_bits)

        if post_upper <= target:
            return upper, min(post_upper, target)

    best_p = lower
    best_post = post_lower
    for _ in range(max_iter):
        mid = 0.5 * (lower + upper)
        post = rs_post_ber(mid, n, k, m_bits)
        if post <= target:
            best_p = mid
            best_post = post
            lower = mid
        else:
            upper = mid

        log_upper = math.log10(max(upper, LOG_MIN_VALUE))
        log_lower = math.log10(max(lower, LOG_MIN_VALUE))
        if abs(log_upper - log_lower) <= LOG_BER_TOL:
            break

    return best_p, min(best_post, target)


def main() -> None:
    if not targets:
        raise ValueError("At least one target BER must be specified.")

    worst_input = worst_input_preFEC_BER
    rows: List[Dict[str, Any]] = []

    worst = best_k_for_target(worst_input, worst_target_post_BER)
    if worst is None:
        raise ValueError(
            f"No RS({n_fixed},k) over GF(2^{m}) meets target {worst_target_post_BER} "
            f"at input BER {worst_input:.2e}"
        )

    max_t = worst["t"]
    t_values = list(range(1, max_t + 1))

    for target in targets:
        # Include a no-FEC option where post-BER equals pre-BER
        rows.append(
            {
                "target_post_BER": target,
                "input_preFEC_BER": float(target),
                "n": n_fixed,
                "k": n_fixed,
                "m": m,
                "t": 0,
                "rate": 1.0,
                "post_ber_est": float(target),
                "note": "no_fec",
            }
        )

        for t in t_values:
            k = n_fixed - 2 * t
            if k <= 0:
                continue
            p_max, post = max_input_ber_for_target(
                n_fixed,
                k,
                m,
                target,
                worst_input,
            )
            rows.append(
                {
                    "target_post_BER": target,
                    "input_preFEC_BER": p_max,
                    "n": n_fixed,
                    "k": k,
                    "m": m,
                    "t": t,
                    "rate": k / n_fixed,
                    "post_ber_est": post,
                    "note": "",
                }
            )

    sel_df = pd.DataFrame(rows)
    sel_df.sort_values(
        ["target_post_BER", "input_preFEC_BER", "t"],
        ascending=[True, False, True],
        inplace=True,
    )
    csv_path = Path("rsfec_selection_m8_n86.csv")
    sel_df.to_csv(csv_path, index=False)

    # Build synthesis config of unique (n,k) found
    uniq = (
        sel_df[sel_df["t"] > 0]
        .dropna(subset=["n", "k"])
        .drop_duplicates(subset=["n", "k", "m"])
        .sort_values(["k", "n"])
    )
    cfg_lines = []
    cfg_lines.append("# RS Codec Synthesis Configs")
    cfg_lines.append("# Format: N K GF_WIDTH clock_ps [library_dir] [top]")
    cfg_lines.append("")
    cfg_lines.append(
        f"# Worst-case FEC analysed: {worst_input:.2e} -> {worst_target_post_BER:.2e}"
    )
    cfg_lines.append("")
    for _, r in uniq.iterrows():
        n, k, t = int(r["n"]), int(r["k"]), int(r["t"])
        cfg_lines.append(f"# RS({n},{k}), GF256 (t={t})")
        for top in ["rs_encoder_wrapper", "rs_syndrome", "rs_decoder"]:
            cfg_lines.append(f"{n} {k} 8 {clock_ps} {LIB} {top}")
        cfg_lines.append("")
    cfg_path = Path(f"config/sweep_code_n{n_fixed}.txt")
    cfg_path.write_text("\n".join(cfg_lines), encoding="utf-8")

    print(f"Wrote: {csv_path}")
    print(f"Wrote: {cfg_path}")


if __name__ == "__main__":
    main()
