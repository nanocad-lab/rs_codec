if {![info exists CONFIG_FILE]} {
  set CONFIG_FILE "config/sweep_code_n86_asap7.txt"
}
if {![info exists OUT_ROOT]} {
  set OUT_ROOT "data/asap7_code_sweep"
}
source scripts/run_sweep.tcl
