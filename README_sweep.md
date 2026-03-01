# RS Codec Synthesis Sweeps (Synopsys Design Compiler)

This repo includes a multi-configuration **Synopsys Design Compiler** sweep flow to extract
**area / power / timing** for RS-FEC blocks (`rs_encoder_wrapper`, `rs_syndrome`, `rs_decoder`, etc.).

## Environment setup

```bash
# Example (bash/zsh); adjust for your Synopsys install.
export SNPS="/path/to/Synopsys"
source "$SNPS/Design_Complier/vS-2021.06-SP4/SETUP"
```

## Config files (paper defaults)

Code sweeps (vary `K` at a fixed clock period):
- ASAP7: `config/sweep_code_n86_asap7.txt`
- NanGate45: `config/sweep_code_n86_nangate45.txt`

Frequency sweeps (vary clock period for a single code point):
- ASAP7: `config/sweep_freq_n86_asap7.txt`
- NanGate45: `config/sweep_freq_n86_nangate45.txt`

### Config format

Whitespace-separated, `#` for comments:

`N K GF_WIDTH clock_ps [library_dir] [top]`

Notes:
- `GF_WIDTH` is the **symbol bit width** (e.g. `8` ⇒ GF(2^8)=GF256).
- `clock_ps` is the target clock period in **picoseconds**.
- Set token 5 (`library_dir`) to `-` and pass `DEFAULT_LIB_DIR` via `dc_shell -x` (or via `--define` in the parallel runner).

Example:

`86 82 8 800.0 - rs_decoder`

## Run the sweep

ASAP7 code sweep (default wrapper):

```bash
dc_shell -f scripts/run_asap7.tcl \
  -x "set DEFAULT_LIB_DIR /path/to/asap7/TT"
```

NanGate45 code sweep (default wrapper):

```bash
dc_shell -f scripts/run_nangate45.tcl \
  -x "set DEFAULT_LIB_DIR /path/to/NanGate45/db"
```

Override the config / output root (example: ASAP7 freq sweep):

```bash
dc_shell -f scripts/run_asap7.tcl \
  -x "set CONFIG_FILE config/sweep_freq_n86_asap7.txt" \
  -x "set OUT_ROOT data/asap7_freq_sweep" \
  -x "set DEFAULT_LIB_DIR /path/to/asap7/TT"
```

### Parallel workers

```bash
python3 scripts/run_sweep_parallel.py \
  --config config/sweep_code_n86_asap7.txt \
  --out-root data/asap7_code_sweep \
  --num-workers 4 \
  --define DEFAULT_LIB_DIR=/path/to/asap7/TT
```

## Outputs

- Per-run directory: `<OUT_ROOT>/<label>/` (default: `data/<tech>_code_sweep/<label>/`)
  - `generated/`: run-specific `generic_types.vhd` and substituted RS_GF variants
  - `.WORK/`: DC work library
  - `reports/`: `*_timing.rep`, `*_power.rep`, `*_area.rep`, etc.
  - Netlist and constraints: `<top>.netlist.v`, `<top>.sdc`, `<top>.compile.ddc`
- Summary CSV: `<OUT_ROOT>/summary.csv`
  - Columns: `label,top,N,K,GF_WIDTH,CLK_NS,area,wns,total_dyn_mw`

## Supported tops

- `rs_encoder_wrapper`
- `rs_encoder`
- `rs_decoder`
- `rs_syndrome`
- `rs_syndrome_unit`

## Troubleshooting

- `dc_shell: command not found`: source your DC setup script (see above).
- `Library dir not found` / `No .db found`: check `DEFAULT_LIB_DIR` (and that it contains compiled `.db` files).
- `Can't find port 'clk'/'rst'`: the top must expose `clk` and `rst` (all supported tops do).
