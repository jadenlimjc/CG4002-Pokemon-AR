# Run after vitis/build_hls.tcl exports the temporal HLS IP.
# vivado -mode batch -source ultra96/vivado/build_vivado.tcl
set source_dir [file dirname [file normalize [info script]]]
set vitis_dir [file normalize [file join $source_dir .. vitis]]
set fpga_dir [file normalize [file join $source_dir .. fpga]]
set build_dir [file join $source_dir build temporal_overlay]
set bundle [file join $source_dir build board_bundle]
set ip_dir [file join $vitis_dir build gesture_cnn solution1 impl ip]
if {![file exists [file join $ip_dir component.xml]]} {
    error "Export the temporal HLS IP before building Vivado"
}
if {[file exists [file join $build_dir temporal_overlay.xpr]]} {
    error "Vivado build already exists at $build_dir; move it aside before a fresh build"
}
create_project temporal_overlay $build_dir -part xczu3eg-sbva484-1-i
set_property ip_repo_paths [list $ip_dir] [current_project]
update_ip_catalog
import_files -norecurse [file join $source_dir design design_1 design_1.bd]
set bd_file [get_files design_1.bd]
open_bd_design $bd_file
upgrade_bd_cells [get_bd_cells g_cnn]
validate_bd_design
save_bd_design
generate_target all $bd_file
set wrapper_files [make_wrapper -files $bd_file -top]
add_files -norecurse $wrapper_files
set_property top design_1_wrapper [current_fileset]
update_compile_order -fileset sources_1

launch_runs synth_1 -jobs 4
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] ne "100%"} {
    error "Vivado synthesis failed: [get_property STATUS [get_runs synth_1]]"
}
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} {
    error "Vivado implementation failed: [get_property STATUS [get_runs impl_1]]"
}
open_run impl_1
report_timing_summary -file [file join $build_dir timing_summary.rpt]
report_utilization -file [file join $build_dir utilization.rpt]
foreach delay_type {max min} {
    set paths [get_timing_paths -delay_type $delay_type -max_paths 1]
    if {[llength $paths] == 0 || [get_property SLACK [lindex $paths 0]] < 0} {
        error "Missing or failing $delay_type timing; inspect timing_summary.rpt"
    }
}
set bit_file [file join [get_property DIRECTORY [get_runs impl_1]] design_1_wrapper.bit]
set hwh_file [file join $build_dir temporal_overlay.gen sources_1 bd design_1 hw_handoff design_1.hwh]
file mkdir $bundle
file copy -force $bit_file [file join $bundle gesture_cnn.bit]
file copy -force $hwh_file [file join $bundle gesture_cnn.hwh]
foreach name {golden_input.dat golden_output.dat model_manifest.json} {
    file copy -force [file join $vitis_dir $name] [file join $bundle $name]
}
file copy -force [file join $fpga_dir deployment cnn_pynq_ultra96.py] $bundle
foreach name {evaluate_fpga.py evaluation_data.py} {
    file copy -force [file join $fpga_dir utility $name] $bundle
}
file copy -force [file join $source_dir .. real_data processed_50hz_128 real_gestures_test.npz] $bundle
puts "Temporal overlay and board bundle ready: $bundle"
close_project
exit
