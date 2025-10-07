# rs_codec

**If you're already using this repo, see this patch: https://github.com/mateusgs/rs_codec/commit/4ca278ca88efe6b2975cf8431e16ef8106898bb4**

This project comprises the RTL development of a parameterizable RS Codec. It provides both RS encoder and decoder, and the following parameters that can be adjusted in their instantiation:

| Symbol | Description                      | Valid Range |
| ------ | -------------------------------- | ----------- |
| `N`    | Length of the codeword (message) | 2 to 1023   |
| `K`    | Number of message symbols        | 1 to `N-2`  |
| `m`    | Galois Field order (`GF(2^m)`)   | 2 to 10     |

### Further Reading

If you are new to RS codecs, consider the following references:

- Clarke, C.K.P.: *Reed-Solomon Error Correction*, BBC R&D White Paper, WHP, 31, 2002.
- Geisel, W.A.: *Tutorial on Reed-Solomon Error Correction Coding*, Technical Memorandum 102162, NASA, 1990.
- Wicker, S.B., Bhargava, V.K.: *An Introduction to Reed-Solomon Codes*, in Wicker, S.B. (Ed.): *Reed-Solomon Codes and Their Applications* (Wiley-IEEE Press, 1994, 1st edn.), pp. 1-16.

### Top-Level Ports

| Port         | Dir. | Description                           |
| ------------ | ---- | ------------------------------------- |
| `clk`        | I    | System clock                          |
| `rst`        | I    | System reset                          |
| `i_start_cw` | I    | Delimiter of input codeword start     |
| `i_end_cw`   | I    | Delimiter of input codeword end       |
| `i_valid`    | I    | Validity of input symbols             |
| `i_consume`  | I    | Consumes output of the codec          |
| `i_symbol`   | I    | Input data symbol                     |
| `o_start_cw` | O    | Delimiter of output codeword start    |
| `o_end_cw`   | O    | Delimiter of output codeword end      |
| `o_in_ready` | O    | Readiness to accept new input symbols |
| `o_valid`    | O    | Validity of output symbols            |
| `o_error`    | O    | Error indicator                       |
| `o_symbol`   | O    | Output data symbol                    |

### Repository Layout

| Path | Purpose |
| ---- | ------- |
| `rs_codec/rtl/` | Encoder/decoder RTL, component packages, and wrappers. |
| `rs_codec/sim/` | Mentor ModelSim command scripts (`run_tb_*.tcl`) that compile dependencies and launch the testbenches. |
| `rs_codec/formal/` | JasperGold setups (`run_formal*.tcl`, `requirements.tcl`) for encoder/decoder control- and data-path proofs. |
| `rs_codec/syn/` | Quartus project Tcl exported from the original flow; they now call `scripts/syn/run_syn.tcl` to sweep parameter sets. |
| `generic_components/` | Shared RTL, plus formal/simulation helper Tcl scripts. |
| `scripts/` | Design Compiler sweep automation, power/area post-processing, and plotting utilities (detailed below). |
| `config/` | Text files enumerating `(N, K, GF_WIDTH, clock_ps [,lib] [,top])` tuples for ASIC sweeps. |
| `plots/`, `data/`, `newdata/` | Example synthesis results and generated figures. |

### Workflow Overview

1. **Simulation** – Run the ModelSim scripts under `rs_codec/sim/` to compile the RTL hierarchy and execute the encoder/decoder testbenches.
2. **Formal checks** – Use the JasperGold wrappers in `rs_codec/formal/` to prove interface, reset, and functional requirements for encoder and decoder variants.
3. **FPGA synthesis** – Quartus projects (`rs_codec/syn/*/rs_*.tcl`) delegate to `scripts/syn/run_syn.tcl`, which iterates over the parameter lists produced by the corresponding `get_parameters*.tcl` files and appends device-utilisation/`fmax` rows to `quartus_syn_report.csv`.
4. **ASIC synthesis sweeps** – The Design Compiler flow is managed by `scripts/run_sweep.tcl`. Configuration files under `config/` describe the sweep space, and wrappers such as `scripts/run_asap7.tcl`, `scripts/run_nangate45.tcl`, and the Python helper `scripts/run_sweep_parallel.py` orchestrate single-host or multi-worker runs.
5. **Reporting & plots** – Python utilities in `scripts/` (see the next section) parse the aggregated `summary.csv` files, compute energy/throughput metrics, and emit CSV tables and publication-ready figures.

### Design Compiler Sweep (merged from `README_sweep.md`)

- **Environment** – Source the Synopsys Design Compiler/Library Compiler setups before running `dc_shell`.
- **Config format** – Each line in `config/sweep_configs_*.txt` has `N K GF_WIDTH clock_ps [library_dir] [top]`. `GF_WIDTH` is the symbol bit width (e.g., `4 → GF(2^4)`); omit `library_dir` to rely on `DEFAULT_LIB_DIR` passed via `-x`.
- **Automation** – `scripts/run_sweep.tcl` generates per-run copies of `generic_types.vhd` and wrapper files with the requested GF literal, loads `.db` libraries from `library_dir`, applies clock/reset constraints, sets representative switching activity, compiles with `compile_ultra`, and appends `label,top,N,K,GF_WIDTH,CLK_NS,area,wns,total_dyn_mw` to `<OUT_ROOT>/summary.csv`.
- **Convenience wrappers** –
  - ASAP7: `dc_shell -f scripts/run_asap7.tcl -x "set CONFIG_FILE config/sweep_configs_asap7.txt" -x "set OUT_ROOT data/asap7_sweep"`
  - NanGate45: `dc_shell -f scripts/run_nangate45.tcl`
  - Parallel workers: `python3 scripts/run_sweep_parallel.py --config config/sweep_configs_asap7.txt --out-root data/asap7_sweep --num-workers 4`
    (the helper partitions the config file round-robin, launches `dc_shell` instances, and merges the worker summaries).
- **Outputs** – Each run produces `<OUT_ROOT>/<label>/{generated,.WORK,reports}` plus `<label>.compile.ddc`, `<label>.netlist.v`, and `<label>.sdc`. The consolidated CSV feeds the plotting scripts below.
- **Power assumptions** – `i_symbol*` ports toggle with `0.5` probability at `0.5` toggles/cycle, handshake inputs default to non-stalling values, and clocks are propagated post-compile for accurate power.

### Data and Plotting Utilities (`scripts/`)

| Script | Description |
| ------ | ----------- |
| `add_pj_per_bit_to_summary.py` | Adds a `pj_per_bit` column to a DC `summary.csv` using block-specific cycle counts. |
| `energy_analysis.py` | Aggregates encoder/syndrome/decoder sweeps, normalises power units, and plots knee/min-energy points. |
| `gen_k_sweep.py` | Generates `(input BER → minimal N)` sweeps for a fixed `K` by reusing the RS-FEC selector model. |
| `gen_sweep_rs544_m10.py` | Emits a clock-frequency sweep for RS(544,514) over GF10 (ASAP7) in the standard config syntax. |
| `plot_area_throughput_vs_ber.py` | Combines sweep data with minimal-N selections to show area-per-throughput versus input BER (ASAP7 + NanGate45). |
| `plot_energy_vs_n.py` | Compares total (encoder + syndrome + decoder) energy/bit across technologies and block lengths. |
| `plot_rs_codec_vs_ber.py` | Charts pJ/bit and code-rate versus input BER, with optional decoder clock-gating model. |
| `plot_total_energy_rate_vs_ber.py` | Produces combined energy and effective-rate plots using probabilistic decoder activation. |
| `reach_fom_plot.py` | Cross-references link examples with scaled FEC energy models to compute reach figures of merit. |
| `rsfec_select_and_cfg.py` | Selects RS(n,k) solutions for target BERs (GF=8), writes a selection CSV, and generates DC config stubs. |
| `run_sweep_parallel.py` | Splits a config file across multiple `dc_shell` workers and merges the resulting summaries. |

Legacy helpers such as `0.tcl`, `1.tcl`, and `syn.tcl` capture earlier Design Compiler experiments; the new sweep flow above supersedes them but they remain as references for manual bring-up.

### Additional Utilities

- `rs_codec/py_scripts/vhd_generator_for_rs_constants.py` regenerates `rs_constants.vhd` tables using the helper functions in `rs_codec/py_scripts/rs_helper_functions.py`.
- The `generic_components/formal/check_synthesis_*.tcl` scripts perform unit-level elaboration checks for reusable blocks (shift registers, FIFOs, buffers, etc.).
- FPGA-oriented ModelSim automation for supporting components lives under `generic_components/sim/`.

### Streaming Throughput and Latency

Let `N` be the codeword length, `K` the message symbols, `m` the Galois-field width (bits/symbol), `t = (N-K)/2`, and `f_clk = 1/CLK_NS`. The RTL keeps the encoder and syndrome paths fully streaming (one symbol each cycle) while the half-parallel decoder reuses finite-field resources and therefore emits one symbol every two clocks, matching the energy/throughput model derived from Silva et al. (2021).【F:rs_codec/rtl/rs_encoder.vhd†L198-L339】【F:rs_codec/rtl/rs_encoder.vhd†L400-L448】【F:rs_codec/rtl/rs_syndrome.vhd†L262-L305】【F:scripts/add_pj_per_bit_to_summary.py†L3-L40】【F:rs_codec/rtl/rs_chien_forney.vhd†L200-L318】 The resulting steady-state metrics are:

| Block | Cycles per symbol | Symbol throughput | Information-bit throughput | Latency highlights |
| ----- | ----------------- | ----------------- | ------------------------- | ----------------- |
| Encoder | 1 | `f_clk` | `(K/N) · m · f_clk` | Message symbols propagate combinationally; parity generation keeps `o_valid` high for `N-K` additional cycles before asserting `o_end_codeword`.【F:rs_codec/rtl/rs_encoder.vhd†L198-L339】【F:rs_codec/rtl/rs_encoder.vhd†L400-L448】 |
| Syndrome | 1 | `f_clk` | `(K/N) · m · f_clk` (when forwarding toward the decoder) | The controller asserts `o_wr_symbol` every accepted input cycle and only raises `o_valid` after the final codeword symbol, i.e., after `N` accumulation cycles plus one register stage.【F:rs_codec/rtl/rs_syndrome.vhd†L262-L305】 |
| Decoder (half) | 2 | `f_clk / 2` | `(K/N) · m · f_clk / 2` | Formal timing constraints show the first corrected symbol appears after `N + 2(N-K) + 7` clocks and the full codeword drains by cycle `2N + 2(N-K) + 6`.【F:rs_codec/formal/rs_decoder/procs.itcl†L174-L200】 |

For reference, the decoder timing bounds above are the ones used to size JasperGold proofs and capture the Berlekamp–Massey plus Chien/Forney pipeline depth.【F:rs_codec/formal/rs_decoder/procs.itcl†L174-L200】 Because the decoder exports a ready/valid interface, keeping `i_consume = 1` sustains the quoted per-symbol cadence.【F:rs_codec/rtl/rs_chien_forney.vhd†L200-L318】

#### Example: RS(544,512) over GF(2⁸)

The ASAP7 sweeps include `CLK_NS = 1.55` ns for `N = 544`, `K = 512`, `m = 8`, which maps to `f_clk ≈ 645 MHz`.【F:newdata/asap7_opt_sweep/summary.csv†L12-L23】 Plugging these numbers into the expressions above gives:

- Encoder (and syndrome) symbol throughput ≈ 0.645 Gsym/s, information throughput ≈ 4.86 Gb/s, with a parity flush latency of `(N-K)·CLK_NS = 32·1.55 ns ≈ 49.6 ns`.
- Decoder symbol throughput ≈ 0.323 Gsym/s, information throughput ≈ 2.43 Gb/s, first corrected symbol after `(544 + 2·32 + 7)·1.55 ns ≈ 0.95 µs`, and the entire codeword drained by `(2·544 + 2·32 + 6)·1.55 ns ≈ 1.79 µs`.

These concrete values match the cycle budgeting used in the Silva et al. study and the repository’s energy post-processing scripts.【4c2353†L1-L23】【F:scripts/add_pj_per_bit_to_summary.py†L3-L40】

### Example Plot Workflow

1. Generate or reuse a selection CSV (`python scripts/rsfec_select_and_cfg.py`).
2. Run an ASIC sweep and collect `<OUT_ROOT>/summary.csv`.
3. Plot energy/rate curves:
   ```bash
   python scripts/plot_rs_codec_vs_ber.py \
     --selection rsfec_selection_m8_halfdec.csv \
     --summary data/asap7_sweep_512/summary.csv \
     --gated --syndrome-cycles-per-symbol 1 --decoder-cycles-per-symbol 2
   ```
   The script writes PNG/PDF figures and companion CSVs under `plots/`.

### Publication & Contact

There is a paper that explains the nuances of this project: https://ietresearch.onlinelibrary.wiley.com/doi/10.1049/cdt2.12009

This project started at Universidade Federal de Minas Gerais (UFMG) and is open for the community under the "MIT" license. Contact matgonsil@gmail.com (Mateus Silva) for any questions.
