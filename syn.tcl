########################################
#  Date : 080625
#  Generated : jooyeon37@ucla.edu
########################################
set build_name rs_codec 

set RTL /w/ee.00/puneet/aaronyen/rs_codec

set vhd_filelist_1 [ list \
    $RTL/generic_components/rtl/generic_types.vhd \
    $RTL/generic_components/rtl/generic_functions.vhd \
    $RTL/rs_codec/rtl/rs_full_multiplier_core.vhd \
    $RTL/generic_components/rtl/async_dff.vhd \
    $RTL/generic_components/rtl/d_sync_flop.vhd \
    $RTL/generic_components/rtl/no_rst_dff.vhd \
    $RTL/generic_components/rtl/config_dff_array.vhd \
    $RTL/generic_components/rtl/sync_dff_array.vhd \
    $RTL/generic_components/rtl/reg_fifo_array.vhd \
    $RTL/generic_components/rtl/reg_fifo.vhd \
    $RTL/generic_components/rtl/generic_components.vhd \
    $RTL/rs_codec/rtl/rs_types.vhd \
    $RTL/rs_codec/rtl/rs_constants.vhd \
    $RTL/rs_codec/rtl/rs_functions.vhd \
    $RTL/rs_codec/rtl/rs_components.vhd \
    $RTL/rs_codec/rtl/rs_decoder.vhd \
    $RTL/rs_codec/rtl/rs_encoder.vhd \
    $RTL/rs_codec/rtl/rs_adder.vhd \
    $RTL/rs_codec/rtl/rs_multiplier_lut.vhd \
    $RTL/rs_codec/rtl/rs_multiplier.vhd \
    $RTL/rs_codec/rtl/rs_inverse.vhd \
    $RTL/rs_codec/rtl/rs_full_multiplier.vhd \
    $RTL/rs_codec/rtl/rs_remainder_unit.vhd \
    $RTL/rs_codec/rtl/rs_reduce_adder.vhd \
    $RTL/rs_codec/rtl/rs_syndrome_subunit.vhd \
    $RTL/rs_codec/rtl/rs_syndrome.vhd \
    $RTL/rs_codec/rtl/rs_berlekamp_massey.vhd \
    $RTL/rs_codec/rtl/rs_chien.vhd \
    $RTL/rs_codec/rtl/rs_forney.vhd \
    $RTL/rs_codec/rtl/rs_chien_forney.vhd \
    $RTL/rs_codec/rtl/rs_codec.vhd \
]

puts "VHD FILES ARE: "
puts $vhd_filelist_1

sh rm -rf .WORK
sh mkdir .WORK
define_design_lib WORK -path .WORK
set outDir ./data/01_syn_s
sh mkdir -p $outDir

set topModule $build_name
set hdlin_vhdl_std 2008
# Set up link libraries - use only generic technology library for RTL synthesis
set link_library "* gtech.db"
set target_library "gtech.db"
analyze -f vhd -library WORK $vhd_filelist_1

elaborate $topModule -parameters "N=15,K=11"
# current_design is automatically set after elaboration
link
write -f ddc -o $outDir/elab.ddc -hierarchy

