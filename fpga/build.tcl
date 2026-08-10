# Vivado entry point. project.ps1 supplies absolute repository and upstream paths.
if {[llength $argv] != 2} {
    error "usage: vivado -source fpga/build.tcl -tclargs <repo-root> <upstream-root>"
}

set repo_root [file normalize [lindex $argv 0]]
set upstream_root [file normalize [lindex $argv 1]]

if {[string first "2020.1" [version -short]] < 0} {
    error "This design requires Vivado 2020.1; found [version -short]"
}
if {![file exists "$upstream_root/prj/v0.94/rtl/red_pitaya_top.sv"]} {
    error "Pinned RedPitaya-FPGA v0.94 source is missing under $upstream_root"
}

cd $upstream_root
set argv [list v0.94 ""]
source "$upstream_root/red_pitaya_vivado_project_Z10.tcl"
source "$repo_root/tools/vivado_build.tcl"
