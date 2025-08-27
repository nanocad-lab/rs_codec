########################################
#  Date : 080625
#  Generated : jooyeon37@ucla.edu
########################################
set build_name rs_encoder_wrapper
# Original external path kept for reference
# set RTL /w/ee.00/puneet/jooyeon/Chiplet_link/rs_codec/
#set DB_DIR /w/ee.00/puneet/jooyeon/Lib/22fdx/FOUNDATION_IP/GPIO/1p8/archive/IN22FDX_GPIO18_9M11S30P_FDK_RELV01R21/model/timing/db/
set DB_DIR /w/ee.00/puneet/jooyeon/Lib/GF_45SG01/45SG01_phase1_logic_IP/45SG01_SC_11T_SG40RVT_2021q2v1/liberty

set link_library [list *]
set target_library [list ]

foreach fileName [glob -d $DB_DIR *.db] {
     set link_library [linsert $link_library end $fileName]
     set target_library [linsert $target_library end $fileName]
}


set RTL /u1/ee/aaronyen/rs_codec

set vhd_filelist_1 [ list \
    $RTL/generic_components/rtl/generic_types.vhd \
    $RTL/generic_components/rtl/generic_functions.vhd \
    $RTL/generic_components/rtl/generic_components.vhd \
    $RTL/rs_codec/rtl/rs_types.vhd \
    $RTL/rs_codec/rtl/rs_constants.vhd \
    $RTL/rs_codec/rtl/rs_functions.vhd \
    $RTL/rs_codec/rtl/rs_components.vhd \
    $RTL/rs_codec/rtl/rs_encoder.vhd \
    $RTL/generic_components/rtl/async_dff.vhd \
    $RTL/rs_codec/rtl/rs_adder.vhd \
    $RTL/rs_codec/rtl/rs_multiplier_lut.vhd \
    $RTL/rs_codec/rtl/rs_multiplier.vhd \
    $RTL/rs_codec/rtl/rs_remainder_unit.vhd \
    $RTL/rs_codec/rtl/rs_syndrome.vhd \
    $RTL/rs_codec/rtl/rs_syndrome_subunit.vhd \
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
##set link_library "* gtech.db"
##set target_library "gtech.db"
# Generate generic_types.vhd based on RS_GF parameter
# Define word width mapping for different Galois Fields
set RS_GF_VALUE 2  ;# RS_GF_16 = 2, change this for different GF sizes

# Map RS_GF enum value to bit width (log2 of GF size)
switch $RS_GF_VALUE {
    0  { set WORD_WIDTH 1 }  ;# RS_GF_4   -> 2 bits  (1 downto 0)
    1  { set WORD_WIDTH 2 }  ;# RS_GF_8   -> 3 bits  (2 downto 0)  
    2  { set WORD_WIDTH 3 }  ;# RS_GF_16  -> 4 bits  (3 downto 0)
    3  { set WORD_WIDTH 4 }  ;# RS_GF_32  -> 5 bits  (4 downto 0)
    4  { set WORD_WIDTH 5 }  ;# RS_GF_64  -> 6 bits  (5 downto 0)
    5  { set WORD_WIDTH 6 }  ;# RS_GF_128 -> 7 bits  (6 downto 0)
    6  { set WORD_WIDTH 7 }  ;# RS_GF_256 -> 8 bits  (7 downto 0)
    7  { set WORD_WIDTH 8 }  ;# RS_GF_512 -> 9 bits  (8 downto 0)
    8  { set WORD_WIDTH 9 }  ;# RS_GF_1024-> 10 bits (9 downto 0)
    9  { set WORD_WIDTH 9 }  ;# RS_GF_NONE-> 10 bits (default max)
    default { set WORD_WIDTH 9 }  ;# Default to maximum width
}

# Map RS_GF enum index to literal name
switch $RS_GF_VALUE {
    0  { set RS_GF_NAME RS_GF_4 }
    1  { set RS_GF_NAME RS_GF_8 }
    2  { set RS_GF_NAME RS_GF_16 }
    3  { set RS_GF_NAME RS_GF_32 }
    4  { set RS_GF_NAME RS_GF_64 }
    5  { set RS_GF_NAME RS_GF_128 }
    6  { set RS_GF_NAME RS_GF_256 }
    7  { set RS_GF_NAME RS_GF_512 }
    8  { set RS_GF_NAME RS_GF_1024 }
    9  { set RS_GF_NAME RS_GF_NONE }
    default { set RS_GF_NAME RS_GF_NONE }
}

# Generate generic_types.vhd from template
exec sed "s/WORD_WIDTH_PLACEHOLDER/$WORD_WIDTH/g" $RTL/generic_components/rtl/generic_types_basic.vhd > $RTL/generic_components/rtl/generic_types.vhd

puts "Generated generic_types.vhd with max_word width: [expr $WORD_WIDTH + 1] bits for RS_GF=$RS_GF_VALUE"

# Generate a wrapper with RS_GF default replaced from RS_GF_NONE to selected RS_GF
set WRAPPER_SRC $RTL/rs_codec/rtl/rs_encoder_wrapper.vhd
set WRAPPER_GEN $outDir/rs_encoder_wrapper_gen.vhd
exec sed "s/RS_GF_NONE/$RS_GF_NAME/g" $WRAPPER_SRC > $WRAPPER_GEN

# Use generated wrapper
set vhd_filelist_1 [linsert $vhd_filelist_1 end $WRAPPER_GEN]

analyze -f vhd -library WORK $vhd_filelist_1

elaborate $topModule -parameters "N=15,K=11"
# current_design is automatically set after elaboration
link
write -f ddc -o $outDir/elab.ddc -hierarchy

