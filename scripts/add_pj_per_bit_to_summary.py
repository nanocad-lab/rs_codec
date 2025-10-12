#!/usr/bin/env python3
"""
Add a pJ/bit column to a synthesis summary CSV using the formula from
IET Computers & Digital Techniques (2021, Silva et al.).

Energy per information bit (pJ/bit) = total_dyn_mW * CLK_NS * cycles_per_symbol / (rate * m)

Where:
- rate = K / N
- m = GF_WIDTH (bits per symbol)
- cycles_per_symbol = 2 for 'rs_decoder' (half-decoder), else 1

The input CSV must contain columns:
  label,top,N,K,GF_WIDTH,CLK_NS,area,wns,total_dyn_mw

The script appends a new column 'pj_per_bit' and overwrites the file.
"""

import csv
from pathlib import Path
from typing import Dict, List, MutableMapping, Optional
import sys


DECODER_TOP = "rs_decoder"


def _to_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    stripped = value.strip()
    if stripped == "":
        return None
    try:
        return float(stripped)
    except ValueError:
        return None


def compute_pj_per_bit(row: MutableMapping[str, Optional[str]]) -> float:
    n = _to_float(row.get("N"))
    k = _to_float(row.get("K"))
    m = _to_float(row.get("GF_WIDTH"))
    clk_ns = _to_float(row.get("CLK_NS"))
    p_mw = _to_float(row.get("total_dyn_mw"))
    top = (row.get("top") or "").strip()

    if n is None or k is None or m is None or clk_ns is None or p_mw is None:
        return float("nan")
    if m == 0 or k == 0 or n == 0:
        return float("nan")

    rate = k / n
    cycles_per_symbol = 2.0 if top == DECODER_TOP else 1.0
    pj = p_mw * clk_ns * cycles_per_symbol / (rate * m)
    return pj


def main(path: Path) -> int:
    # Read CSV
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        rows: List[Dict[str, Optional[str]]] = [dict(row) for row in reader]
        fieldnames: List[str] = list(reader.fieldnames or [])

    # Append new column if not present
    new_col = "pj_per_bit"
    if new_col not in fieldnames:
        fieldnames.append(new_col)

    # Compute values
    for r in rows:
        r[new_col] = f"{compute_pj_per_bit(r):.6f}"

    # Write back
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/asap7_sweep_clock_gate/summary.csv")
    sys.exit(main(target))
