if {![info exists CONFIG_FILE]} {
  set CONFIG_FILE "config/sweep_code_n86_nangate45.txt"
}
if {![info exists OUT_ROOT]} {
  set OUT_ROOT "data/nangate45_code_sweep"
}
source scripts/run_sweep.tcl
