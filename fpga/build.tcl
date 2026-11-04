# Vivado entry point. From the repository folder:
#
#     vivado -mode batch -source fpga/build.tcl -tclargs . .cache/upstream
#
# where .cache/upstream is a checkout of the upstream Red Pitaya design at the
# commit pinned in fpga/upstream.lock (see README.md, "Rebuilding the bitstream").
# This script checks the qualified sources, lays fpga/ over the upstream design,
# creates the upstream Vivado project and hands over to tools/vivado_build.tcl.
if {[llength $argv] != 2} {
    error "usage: vivado -mode batch -source fpga/build.tcl -tclargs <repo-root> <upstream-root>"
}

set repo_root [file normalize [lindex $argv 0]]
set upstream_root [file normalize [lindex $argv 1]]

if {[string first "2020.1" [version -short]] < 0} {
    error "This design requires Vivado 2020.1; found [version -short]"
}
if {![file exists "$upstream_root/prj/v0.94/rtl/red_pitaya_top.sv"]} {
    error "Pinned RedPitaya-FPGA v0.94 source is missing under $upstream_root"
}

# --- the upstream checkout must be the pinned commit ------------------------
set lock [dict create]
set fh [open "$repo_root/fpga/upstream.lock" r]
foreach line [split [read $fh] \n] {
    if {[regexp {^([^#=]+)=(.*)$} $line -> key value]} { dict set lock [string trim $key] [string trim $value] }
}
close $fh
set pinned [dict get $lock commit]
if {[file isdirectory "$upstream_root/.git"] && [auto_execok git] ne ""} {
    if {![catch {exec git -C $upstream_root rev-parse HEAD} head] && [string trim $head] ne $pinned} {
        error "Upstream checkout is at [string trim $head], not the pinned commit $pinned.\nRun: git -C $upstream_root checkout $pinned"
    }
    puts "Upstream checkout: commit $pinned (pinned)."
} else {
    puts "Upstream folder is not a git checkout; assuming it holds commit $pinned."
}

# --- the qualified sources must be unchanged apart from comments -----------
proc find_python3 {} {
    foreach cand {{python3} {py -3} {python}} {
        set exe [lindex $cand 0]
        if {[auto_execok $exe] eq ""} continue
        set cmd [concat [list [lindex [auto_execok $exe] 0]] [lrange $cand 1 end]]
        if {[catch {exec {*}$cmd -c "import sys;print(sys.version_info\[0\])"} v]} continue
        if {[string trim $v] eq "3"} { return $cmd }
    }
    return {}
}
set py [find_python3]
if {$py eq {}} {
    puts "WARNING: no Python 3 on the PATH, so the golden-source check was skipped."
} elseif {[catch {exec {*}$py "$repo_root/tools/verify_golden.py"} out]} {
    puts $out
    error "Golden-source check failed. Change fpga/golden_manifest.json only as part of requalifying the design."
} else {
    puts $out
}

# --- lay the project's files over the upstream design -----------------------
file copy -force "$repo_root/fpga/red_pitaya_top.sv" "$upstream_root/prj/v0.94/rtl"
file copy -force "$repo_root/fpga/systemZ10.tcl"     "$upstream_root/prj/v0.94/ip"
file copy -force "$repo_root/fpga/red_pitaya.xdc"    "$upstream_root/sdc"
file copy -force "$repo_root/fpga/project.xdc"       "$upstream_root/prj/v0.94/sdc/red_pitaya.xdc"
foreach name {
    axi_master.v build_id.vh fir_coeffs.vh fir_params.vh
    red_pitaya_acq.v red_pitaya_acq_cic.v red_pitaya_acq_dds.v
    red_pitaya_acq_dma.v red_pitaya_acq_fir.v red_pitaya_acq_mixer.v
    red_pitaya_phaseshift.v red_pitaya_resonator.v
    red_pitaya_scope.v red_pitaya_sequencer.v
} {
    file copy -force "$repo_root/fpga/$name" "$upstream_root/rtl/classic"
}
puts "Laid fpga/ over the upstream design."

cd $upstream_root
set argv [list v0.94 ""]
source "$upstream_root/red_pitaya_vivado_project_Z10.tcl"
source "$repo_root/tools/vivado_build.tcl"
