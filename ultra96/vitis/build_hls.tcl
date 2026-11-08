# Vitis 2025.1: vitis-run --mode hls --tcl build_hls.tcl
# GESTURE_HLS_STAGE: csim, synth, cosim, export (default: export).
set source_dir [file dirname [file normalize [info script]]]
set stage "export"
if {[info exists ::env(GESTURE_HLS_STAGE)]} { set stage $::env(GESTURE_HLS_STAGE) }
if {$stage ni {csim synth cosim export}} { error "Unknown GESTURE_HLS_STAGE: $stage" }
set part "xczu3eg-sbva484-1-i"
if {[info exists ::env(GESTURE_HLS_PART)]} { set part $::env(GESTURE_HLS_PART) }

open_project [file join $source_dir build gesture_cnn]
set_top gesture_cnn_top
add_files [file join $source_dir gesture_cnn.cpp] -cflags "-std=c++14"
add_files [file join $source_dir gesture_cnn.h]
add_files [file join $source_dir weights.h]
add_files -tb [file join $source_dir tb_gesture_cnn.cpp] -cflags "-std=c++14"
add_files -tb [file join $source_dir golden_input.dat]
add_files -tb [file join $source_dir golden_output.dat]
open_solution "solution1" -flow_target vivado
set_part $part
create_clock -period 10 -name default
csim_design
if {$stage ne "csim"} { csynth_design }
if {$stage eq "cosim"} { cosim_design -rtl verilog }
if {$stage eq "export"} {
    # A new IP version lets an existing Vivado block design explicitly upgrade.
    export_design -format ip_catalog -rtl verilog -version "2.0"
}
exit
