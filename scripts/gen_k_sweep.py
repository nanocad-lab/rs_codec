#!/usr/bin/env python3
"""Generate RS sweep table across input BER for configurable K."""

from __future__ import annotations

import argparse
import importlib.util
import math
from pathlib import Path
from typing import Iterable, List, Optional, Protocol, Sequence, TypedDict, cast

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

class SelectionResult(TypedDict):
    n: int
    k: int
    m: int
    t: int
    rate: float
    post_ber_est: float


class SelectorModule(Protocol):
    targets: Sequence[float]

    def minimal_n_for_target(self, p_b: float, target: float, k: int) -> Optional[SelectionResult]:
        ...

    def choose_best_over_k(self, p_b: float, target: float) -> Optional[SelectionResult]:
        ...


class SweepRow(TypedDict):
    target_post_BER: float
    input_preFEC_BER: float
    n: Optional[int]
    t: Optional[int]
    rate: Optional[float]
    post_ber_est: Optional[float]


def _load_selector() -> SelectorModule:
    spec_path = ROOT / "scripts" / "rsfec_select_and_cfg.py"
    module_spec = importlib.util.spec_from_file_location("rsfec_select_and_cfg", spec_path)
    if module_spec is None or module_spec.loader is None:
        raise ImportError(f"Could not load module spec for {spec_path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return cast(SelectorModule, module)


def generate_sweep(
    *,
    k: Optional[int] = None,
    exp_start: float = -3.0,
    exp_stop: float = -30.0,
    exp_step: float = -0.5,
    targets: Iterable[float] | None = None,
) -> pd.DataFrame:
    if exp_step == 0:
        raise ValueError("exp_step must be non-zero")

    selector = _load_selector()
    target_list = list(targets) if targets is not None else list(selector.targets)

    step = exp_step if (exp_stop - exp_start) * exp_step > 0 else -exp_step
    stop_adjusted = exp_stop + step / 2.0
    exponents = np.arange(exp_start, stop_adjusted, step)
    p_b_grid = [10.0 ** exp for exp in exponents]

    rows: List[SweepRow] = []
    for target in target_list:
        for p_b in p_b_grid:
            if k is None:
                sol = selector.choose_best_over_k(float(p_b), float(target))
            else:
                sol = selector.minimal_n_for_target(float(p_b), float(target), k)
            if sol is None:
                rows.append(
                    {
                        "target_post_BER": float(target),
                        "input_preFEC_BER": float(p_b),
                        "n": None,
                        "t": None,
                        "rate": None,
                        "post_ber_est": None,
                    }
                )
            else:
                rows.append(
                    {
                        "target_post_BER": float(target),
                        "input_preFEC_BER": float(p_b),
                        "n": sol["n"],
                        "t": sol["t"],
                        "rate": sol["rate"],
                        "post_ber_est": sol["post_ber_est"],
                    }
                )

    df = pd.DataFrame(rows)
    df.sort_values(["target_post_BER", "input_preFEC_BER"], inplace=True)
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate RS(n,k) sweep vs BER using rsfec_select_and_cfg settings")
    parser.add_argument("--k", type=int, help="force a specific data-symbol count K (defaults to best K per target)")
    parser.add_argument("--min-exp", type=float, default=-30.0, help="smallest exponent (e.g., -30 for 1e-30)")
    parser.add_argument("--max-exp", type=float, default=-3.0, help="largest exponent (e.g., -3 for 1e-3)")
    parser.add_argument("--step", type=float, default=0.5, help="step size in decades")
    parser.add_argument("--target", type=float, action="append", dest="targets", help="target post-FEC BER (can repeat)")
    parser.add_argument("--output", type=Path, default=ROOT / "plots" / "k_sweep.csv", help="output CSV path")
    args = parser.parse_args()

    sweep = generate_sweep(
        k=args.k,
        exp_start=args.max_exp,
        exp_stop=args.min_exp,
        exp_step=-abs(args.step),
        targets=args.targets,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    sweep.to_csv(args.output, index=False)
    print(sweep.to_string(index=False, float_format=lambda v: f"{v:.3e}" if isinstance(v, float) else v))
    print(f"\nSaved CSV to {args.output}")


if __name__ == "__main__":
    main()
