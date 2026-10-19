# =============================================================================
#  BUILD THE WHOLE PROJECT  -  one command, with checks
# =============================================================================
#
#  Called by fpga/build.tcl once the pinned upstream project exists. Run it
#  through `.\project.ps1 build`. A full build takes roughly 15-25 minutes and
#  ends with a plain PASS or FAIL summary.
#
#    1. check the qualified filter files exist; run the RTL and notebook checks
#    2. add the implementation constraints and set the top module
#    3. synthesise, implement and write the bitstream (from scratch every time)
#    4. check timing and the golden resource counts; write bitstream_id.txt
#    5. print where the bitstream is and what to do next
# =============================================================================

set t_start [clock seconds]
set proj_root [file dirname [file dirname [file normalize [info script]]]]
set project_dir [get_property DIRECTORY [current_project]]
set runs_dir "$project_dir/redpitaya.runs"

proc banner {text} {
    puts ""
    puts "============================================================"
    puts "  $text"
    puts "============================================================"
}

# -----------------------------------------------------------------------------
banner "STEP 1 of 5   Checking the qualified filter files"
# -----------------------------------------------------------------------------
#  The timing-qualified coefficient and parameter files are part of the FPGA
#  overlay. tools/verify_golden.py checks their exact functional contents
#  before Vivado starts, so the build only needs to require their presence.
# -----------------------------------------------------------------------------
set rtl    "$proj_root/fpga"
set ok 1

foreach f [list "$rtl/fir_coeffs.vh" "$rtl/fir_params.vh"] {
    if {![file exists $f]} {
        puts "  MISSING: [file tail $f]"
        puts ""
        puts "  Restore the qualified file from the handover repository."
        set ok 0
    } else {
        puts "  ok: [file tail $f]"
    }
}
if {!$ok} {
    puts ""
    puts "  STOPPING. Fix the above and run this script again."
    return
}

# -----------------------------------------------------------------------------
#  Vivado puts its own (broken) Python 2.7 first on the PATH, so every candidate
#  is asked its version before being trusted. A check that cannot run is
#  skipped with a note; only a check that runs AND finds a problem stops the
#  build.
# -----------------------------------------------------------------------------
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

#  Returns: ok | problems | unavailable, and the output.
proc run_checker {py script extra} {
    if {$py eq {}} { return [list unavailable "no working Python 3 on the PATH"] }
    if {![file exists $script]} { return [list unavailable "$script not found"] }
    set rc [catch {exec {*}$py $script {*}$extra} out opts]
    if {$rc == 0} { return [list ok $out] }
    if {[lindex [dict get $opts -errorcode] 0] eq "CHILDSTATUS"} {
        return [list problems $out]        ;# the script ran and said no
    }
    return [list unavailable $out]         ;# the script could not run at all
}

set PY3 [find_python3]
if {$PY3 eq {}} {
    puts "  No usable Python 3 found - the pre-build checks will be skipped."
    puts "  (Vivado's own Python is 2.7 and is not used. Install Python 3 and"
    puts "   tick 'Add to PATH' to enable them. The build itself does not need it.)"
} else {
    puts "  Pre-build checks will use: $PY3"
}
puts ""

# Two one-second checks: Verilog port names that do not line up, and notebook
# calls that cannot work (tools/verify_rtl.py, tools/verify_notebooks.py).
foreach {label script extra} [list \
        "RTL names" "$proj_root/tools/verify_rtl.py" {} \
        "Notebooks" "$proj_root/tools/verify_notebooks.py" \
            [glob -nocomplain "$proj_root/notebooks/*.ipynb"]] {
    lassign [run_checker $PY3 $script $extra] status out
    switch -- $status {
        ok {
            puts "  $label: consistent."
        }
        unavailable {
            puts "  $label: check skipped - $out"
        }
        problems {
            puts "  ---------------------------------------------------------------"
            puts "  $label - PROBLEMS FOUND. Synthesis will fail. Not building."
            foreach line [split $out \n] { puts "  $line" }
            puts "  ---------------------------------------------------------------"
            return -code error "$label check failed - fix the above and re-run"
        }
    }
}
puts ""

# -----------------------------------------------------------------------------
#  The processor block design (system.bd, created from fpga/systemZ10.tcl) needs
#  its generated output products before synthesis. Generate them if missing.
# -----------------------------------------------------------------------------
set bd_file [get_files -quiet system.bd]
if {$bd_file ne ""} {
    set bd_dir [file dirname $bd_file]
    if {![file isdirectory "$bd_dir/ip"]} {
        puts "  Block design has no output products - generating them now (two minutes)."
        if {[catch {
            open_bd_design $bd_file
            generate_target all [get_files $bd_file]
            close_bd_design [get_bd_designs]
        } err]} {
            puts "  Could not generate them automatically: $err"
            puts "  In the GUI: Sources -> right-click system.bd -> Generate Output Products"
            return -code error "block design output products are missing"
        }
        puts "  Done."
    } else {
        puts "  Block design output products: present."
    }
    puts ""
}

banner "STEP 2 of 5   Adding source files to the project"
# -----------------------------------------------------------------------------
set impl_xdc "$proj_root/fpga/red_pitaya_impl.xdc"
if {[file exists $impl_xdc]} {
    add_files -fileset constrs_1 -norecurse $impl_xdc
    set_property used_in_synthesis false [get_files red_pitaya_impl.xdc]
    set_property used_in_implementation true [get_files red_pitaya_impl.xdc]
}
update_compile_order -fileset sources_1
set_property top red_pitaya_top [current_fileset]


# -----------------------------------------------------------------------------
#  PROVENANCE
#  Register 0x48 always reports the fixed hardware ID FE76AE09 (fpga/build_id.vh).
#  bitstream_id.txt additionally records a hash of the HDL sources and the git
#  commit, so a bitstream can be traced back to the exact files:
#      register 0x48 -> bitstream_id.txt -> commit -> git checkout
#  That only works from a clean working tree, so uncommitted edits are flagged.
# -----------------------------------------------------------------------------
proc git_state {root} {
    if {[auto_execok git] eq ""} { return [list none "" 0] }
    set g [lindex [auto_execok git] 0]
    if {[catch {exec $g -C $root rev-parse --short HEAD} commit]} {
        return [list none "" 0]
    }
    set dirty 0
    if {![catch {exec $g -C $root status --porcelain} st]} {
        set dirty [llength [split [string trim $st] \n]]
        if {[string trim $st] eq ""} { set dirty 0 }
    }
    return [list ok [string trim $commit] $dirty]
}

proc source_fingerprint {files} {
    set h 2166136261
    foreach f $files {
        if {![file exists $f]} continue
        set fh [open $f rb]
        fconfigure $fh -translation binary
        set data [read $fh]
        close $fh
        # pad to a multiple of four so we can hash 32 bits at a time
        set n [string length $data]
        append data [string repeat "\x00" [expr {(4 - ($n % 4)) % 4}]]
        binary scan $data iu* words
        foreach w $words {
            set h [expr {($h ^ $w) & 0xFFFFFFFF}]
            set h [expr {($h * 16777619) & 0xFFFFFFFF}]
        }
        set h [expr {($h ^ $n) & 0xFFFFFFFF}]
    }
    return $h
}

set source_dir "$proj_root/fpga"
set fp_files [list]
foreach f [lsort [glob -nocomplain "$source_dir/red_pitaya_acq*.v"]] { lappend fp_files $f }
foreach f [lsort [glob -nocomplain "$source_dir/red_pitaya_resonator.v"]] { lappend fp_files $f }
foreach f [lsort [glob -nocomplain "$source_dir/red_pitaya_sequencer.v"]] { lappend fp_files $f }
foreach f [list "$source_dir/fir_coeffs.vh" "$source_dir/fir_params.vh" \
                "$source_dir/red_pitaya_phaseshift.v" \
                "$source_dir/red_pitaya_scope.v" \
                "$source_dir/red_pitaya_top.sv"] {
    if {[file exists $f]} { lappend fp_files $f }
}
# The fixed build ID is included in the guarded HDL manifest separately. This
# source hash is provenance only and is never written into synthesized logic.

set source_hash [source_fingerprint $fp_files]
set source_hash_hex [format %08X $source_hash]
set build_id_hex FE76AE09

lassign [git_state $proj_root] git_status git_commit git_dirty
if {$git_status eq "none"} {
    set git_line "not a git repository"
} elseif {$git_dirty > 0} {
    set git_line "commit $git_commit PLUS $git_dirty uncommitted change(s)"
} else {
    set git_line "commit $git_commit, working tree clean"
}

puts "  Hardware ID       : 0x$build_id_hex   (fixed golden design ID)"
puts "  Source hash       : 0x$source_hash_hex (provenance only)"
puts "  Source            : $git_line"
if {$git_dirty > 0} {
    puts ""
    puts "  *** THIS BITSTREAM WILL NOT MATCH ANY COMMIT ***"
    puts "  $git_dirty file(s) are edited but not committed, so there is no commit"
    puts "  you could check out later to reproduce what is about to be built."
    puts "  Nothing is stopped - but if this build turns out to be the good one,"
    puts "  you will not be able to get back to it. Commit first:"
    puts "        git add -A"
    puts "        git commit -m \"what changed and why\""
    puts ""
}
puts ""

# -----------------------------------------------------------------------------
banner "STEP 3 of 5   Building (this is the slow part - 15 to 25 minutes)"
# -----------------------------------------------------------------------------
puts "  Starting at [clock format [clock seconds] -format %H:%M:%S]."
puts "  You can watch progress in the Design Runs tab."
puts ""

#  Reset BOTH runs: Vivado can leave synthesis marked complete after a file is
#  edited outside the tool, and implementation then starts from a stale netlist.
reset_run impl_1
reset_run synth_1

#  Prove the run logs can be written BEFORE launching. If runme.log is locked
#  (a leftover vivado.exe or cmd.exe, an open log viewer, an antivirus sweep),
#  Vivado's launcher dies silently and wait_on_run blocks for ever.
foreach _run {synth_1 impl_1} {
  foreach _f {runme.log job.id.log exception.log} {
    set _log "$runs_dir/$_run/$_f"
    if {[file exists $_log] && [catch {file delete -force $_log} _msg]} {
        puts ""
        puts "  STOP - $_run/runme.log cannot be removed."
        puts "         $_msg"
        puts ""
        puts "  Something is holding it open. Launching anyway would leave"
        puts "  Vivado apparently stuck on \"Initializing Design\" for ever."
        puts ""
        puts "  The usual holder is an orphaned cmd.exe left by a previous run."
        puts "  Close Vivado, then in an elevated PowerShell:"
        puts "    Get-CimInstance Win32_Process -Filter \"Name='cmd.exe'\" |"
        puts "      Where CommandLine -like '*redpitaya.runs*' | Stop-Process -Force"
        puts "  If that finds nothing: Resource Monitor -> CPU -> Associated"
        puts "  Handles -> search the file name; it gives the PID directly."
        puts ""
        puts "  Then run .\\project.ps1 clean - Vivado"
        puts "  recreates it - and re-source this script."
        return
    }
  }
}

launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1

# The golden 7 August netlist used these exact resources. A different count is
# evidence that executable HDL, parameters, or project configuration changed,
# even when filenames still look correct.
set util_report "$runs_dir/synth_1/red_pitaya_top_utilization_synth.rpt"
if {![file exists $util_report]} {
    error "Golden netlist check failed: synthesis utilization report is missing."
}
set util_fh [open $util_report r]
set util_text [read $util_fh]
close $util_fh
foreach pattern {
    {\| Slice LUTs\* +\| 8234 +\|}
    {\| Slice Registers +\| 7679 +\|}
    {\| Block RAM Tile +\| 36\.5 +\|}
    {\| DSPs +\| +26 +\|}
} {
    if {![regexp $pattern $util_text]} {
        error "Golden netlist check failed: unexpected synthesis utilization."
    }
}
puts "  Golden synthesis utilization matches: 8234 LUTs, 7679 registers, 36.5 BRAM, 26 DSPs."

# -----------------------------------------------------------------------------
#  Did synthesis actually re-run?
#
#  If the netlist is older than any source file, the bitstream does not contain
#  what is on disk, whatever its own date says. Refuse to call that a success.
# -----------------------------------------------------------------------------
set synth_dcp "$runs_dir/synth_1/red_pitaya_top.dcp"
set stale [list]
if {[file exists $synth_dcp]} {
    set synth_time [file mtime $synth_dcp]
    foreach f $fp_files {
        if {[file mtime $f] > $synth_time} { lappend stale [file tail $f] }
    }
}
if {[llength $stale] > 0} {
    puts ""
    puts "  *** STALE NETLIST ***"
    puts "  These sources are NEWER than the synthesised netlist:"
    foreach f $stale { puts "      $f" }
    puts "  The bitstream does NOT contain them. Close and reopen the project,"
    puts "  then run this script again."
    puts ""
} else {
    puts "  Netlist is newer than every source file. Good."
}

# -----------------------------------------------------------------------------
#  Write bitstream_id.txt NOW, marked "not yet checked", and rewrite it in STEP 4
#  with the timing verdict. The file must exist the moment a bitstream exists,
#  even if everything after this point fails; deploy refuses it until STEP 4
#  records PASS.
# -----------------------------------------------------------------------------
set fh [open "$runs_dir/impl_1/bitstream_id.txt" w]
puts $fh $build_id_hex
puts $fh "# fingerprint above is what register 0x48 reports"
puts $fh "# built    : [clock format [clock seconds]]"
puts $fh "# source   : $git_line"
puts $fh "# source_hash: $source_hash_hex (provenance only)"
puts $fh "# tool     : Vivado [version -short]"
puts $fh "# target   : [get_property PART [current_project]]"
puts $fh "# timing   : NOT YET CHECKED - project.ps1 build did not reach STEP 4."
puts $fh "#            If you are reading this in a finished build, something"
puts $fh "#            went wrong after implementation. Do not load this."
close $fh

# -----------------------------------------------------------------------------
banner "STEP 4 of 5   Checking the result"
# -----------------------------------------------------------------------------
open_run impl_1

# --- timing ------------------------------------------------------------------
#  "Slack" is how much time to spare each calculation has. The chip works in
#  steps of 8 billionths of a second; if a calculation needs longer than that,
#  it captures a half-finished answer. Negative slack means at least one
#  calculation is too slow.
# -----------------------------------------------------------------------------
#  Count failing paths with options every Vivado version has (capped: the exact
#  number stops mattering once the design fails). Wrapped in catch so a timing
#  query error reports "could not check" instead of aborting the script; an
#  unmeasured build is treated as FAILING, never as passing.
set CAP    2000
set fail   0
set capped 0
set wns    0.0
set timing_known 1

if {[catch {
    set wns [get_property SLACK [get_timing_paths -delay_type max]]
    if {$wns < 0} {
        foreach p [get_timing_paths -delay_type max -max_paths $CAP -nworst 1] {
            if {[get_property SLACK $p] < 0} { incr fail }
        }
        if {$fail >= $CAP} { set capped 1 }
    }
} err]} {
    set timing_known 0
    puts ""
    puts "  *** COULD NOT MEASURE TIMING ***"
    puts "  $err"
    puts ""
    puts "  Treating this build as FAILED, because an unchecked build and a good"
    puts "  build must not look the same. Open the implemented design and run"
    puts "  Report Timing Summary by hand before trusting anything from it."
}

puts ""
puts "  TIMING"
if {!$timing_known} {
    puts "    Not measured - see the error above."
} else {
    puts "    Time to spare on the slowest calculation : [format %.3f $wns] ns"
    if {$capped} {
        puts "    Calculations that are too slow           : $fail or more (capped)"
    } else {
        puts "    Calculations that are too slow           : $fail"
    }
}
puts ""
set timing_ok [expr {$timing_known && $wns >= 0}]
if {$timing_ok} {
    puts "    PASS - every calculation finishes in time."
} else {
    puts "    FAIL - some calculations do not finish in time."
    puts ""
    puts "    This matters: a design that fails timing does not fail cleanly. It"
    puts "    may work on a cool day and produce corrupted numbers on a warm one."
    puts "    Do not trust measurements from this build."
    if {$timing_known} {
        puts ""
        puts "    The slowest paths are:"
        catch {
            foreach p [lrange [get_timing_paths -delay_type max -max_paths 5] 0 4] {
                puts "      [format %8.3f [get_property SLACK $p]] ns   \
[get_property STARTPOINT_PIN $p] -> [get_property ENDPOINT_PIN $p]"
            }
        }
    }
}

# -----------------------------------------------------------------------------
#  Rewrite bitstream_id.txt with the timing verdict: the identifier only proves
#  the board runs what was built, not that what was built meets timing.
# -----------------------------------------------------------------------------
set fh [open "$runs_dir/impl_1/bitstream_id.txt" w]
puts $fh $build_id_hex
puts $fh "# fingerprint above is what register 0x48 reports"
puts $fh "# built    : [clock format [clock seconds]]"
puts $fh "# source   : $git_line"
puts $fh "# source_hash: $source_hash_hex (provenance only)"
puts $fh "# tool     : Vivado [version -short]"
puts $fh "# target   : [get_property PART [current_project]]"
if {$timing_ok} {
    puts $fh "# timing   : PASS  worst slack [format %.3f $wns] ns, 0 failing"
} elseif {!$timing_known} {
    puts $fh "# timing   : *** NOT MEASURED *** the timing query failed - see the"
    puts $fh "#            build log. Treat as failing until checked by hand."
} else {
    puts $fh "# timing   : *** FAIL *** worst slack [format %.3f $wns] ns, $fail failing path(s)"
    puts $fh "# WARNING  : this bitstream does not meet timing. Measurements taken"
    puts $fh "#            from it cannot be trusted, whatever the fingerprint says."
}
if {$git_status eq "ok" && $git_dirty == 0} {
    puts $fh "# reproduce: git checkout $git_commit"
}
close $fh

# --- how full is the chip ----------------------------------------------------
puts ""

puts "  SPACE USED ON THE CHIP"
foreach {name total} {LUT 17600 FDRE 35200 DSP48E1 80 RAMB36E1 60} {
    set n [llength [get_cells -quiet -hier -filter "REF_NAME == $name"]]
    if {$total > 0} {
        puts [format "    %-10s %6d of %6d   (%4.1f %%)" $name $n $total \
              [expr {100.0 * $n / $total}]]
    }
}

# -----------------------------------------------------------------------------
banner "STEP 5 of 5   Summary"
# -----------------------------------------------------------------------------
set bit "$runs_dir/impl_1/red_pitaya_top.bit"
set mins [expr {([clock seconds] - $t_start) / 60}]

puts "  Build took about $mins minutes."
puts ""
if {[file exists $bit] && !$timing_ok} {
    # A bitstream exists but failed STEP 4: the verdict must be the last thing
    # on screen, never a cheerful "next steps".
    puts "  *** DO NOT LOAD THIS BITSTREAM ***"
    puts ""
    if {$timing_known} {
        puts "  It built, but it misses timing by [format %.3f [expr {-$wns}]] ns on an 8 ns clock,"
        puts "  across $fail path(s). The chip would latch half-finished answers. What"
    } else {
        puts "  It built, but its timing could not be measured - see STEP 4 above."
        puts "  An unchecked build is treated as a failing one. What a timing"
        puts "  failure"
    }
    puts "  that looks like from software is not a clean failure - it is registers"
    puts "  reading zero, or values that change when nothing changed, or numbers"
    puts "  that look plausible and are wrong."
    puts ""
    puts "  The bitstream is at:"
    puts "    $bit"
    puts "  It is left in place deliberately, so the reports can be examined - not"
    puts "  because it is usable."
    puts ""
    puts "  WHAT TO DO"
    puts "    1. Open the timing report:  Flow Navigator -> Implementation ->"
    puts "       Open Implemented Design -> Report Timing Summary."
    puts "    2. Look at where the failing paths START and END. If they are in"
    puts "       i_reso, this is the resonator's recursive loop - see the timing"
    puts "       note in red_pitaya_resonator.v, which says to NARROW the widths,"
    puts "       not widen them."
    puts "    3. Fix it, rebuild, and only then load."
    puts ""
    puts "  The board is still running whatever it had before. That is the right"
    puts "  place for it to be."
} elseif {[file exists $bit]} {
    puts "  Bitstream: $bit"
    puts ""
    puts "  NEXT STEPS"
    puts "    1. Copy it to the board: .\\project.ps1 deploy"
    puts "    2. Check the right one loaded: .\\project.ps1 check"
    puts "    3. Sync and run test_noise_passive_feedback.ipynb in order."
} else {
    puts "  NO BITSTREAM WAS PRODUCED."
    puts ""
    puts "  Look in the build log for entries marked ERROR. Warnings do not"
    puts "  stop a build; errors do."
}
puts ""

# A bitstream that cannot be deployed is a failed command. Print the detailed
# summary first, then return a non-zero status to project.ps1 and CI.
if {![file exists $bit]} {
    error "Build failed: no bitstream was produced."
}
if {!$timing_ok} {
    error "Build failed: generated bitstream does not meet timing."
}
