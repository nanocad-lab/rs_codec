########################################
#  Date : 080725
#  Generated : jooyeon37@ucla.edu
########################################
set CLK_PIN clk
set RST_PIN rst
set CLK_TARGET 0.5
# CLK_TARGET: [ns]
set outDir ./data/01_syn_s_0p5nsclk
sh mkdir -p $outDir
set build_name rs_encoder_wrapper
set topModule $build_name

create_clock -name "clk" -period $CLK_TARGET $CLK_PIN

set_dont_touch ${RST_PIN}
set_ideal_network ${RST_PIN}
set_false_path -from [get_ports ${RST_PIN}]

set_max_fanout 20 [current_design]

if { [file exists "constraints.tcl"] } {
    source constraints.tcl
}

uniquify
compile_ultra -no_autoungroup -no_boundary_optimization

write -f ddc -o $outDir/compile.ddc -hierarchy

current_design $topModule
set reportDir $outDir/reports
sh mkdir $reportDir

report_qor > $reportDir/${topModule}_qor.rep
report_timing -significant_digits 6 > $reportDir/${topModule}_timing.rep
report_clock > $reportDir/${topModule}_clock.rep
report_power -significant_digits 6 > $reportDir/${topModule}_power.rep
report_area -hierarchy  > $reportDir/${topModule}_area.rep
report_path_group   > $reportDir/${topModule}_pathgroup.rep
report_timing -capacitance -significant_digits 6

set verilogout_no_tri true
remove_ideal_network [all_clocks]
set_propagated_clock [all_clocks]
write_sdc -version 1.9 ${topModule}.sdc
write -hierarchy -format verilog -output ${topModule}.netlist.v
date
