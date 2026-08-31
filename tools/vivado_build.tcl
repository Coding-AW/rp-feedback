# =============================================================================
#  BUILD THE WHOLE PROJECT  -  one command, with checks
# =============================================================================
#
#  This internal script is called by fpga/build.tcl after the pinned upstream
#  project has been generated. Users should run `.\project.ps1 build`.
#  A full build takes roughly 15-25 minutes. Read the summary at the end: it
#  says PASS or FAIL in plain
#       words and tells you what to do next.
#
#  WHAT IT DOES, IN ORDER
#    - checks the qualified filter files exist
#    - adds any new source files to the project
#    - runs synthesis, implementation and bitstream generation
#    - checks the timing result and explains it
#    - reports how full the chip is
#    - tells you where the bitstream is
#
#  WHY BOTHER
#  Doing this by hand means remembering five steps in the right order and then
#  reading two reports correctly. Most of the mistakes made on this project were
#  a skipped step, not a design error.
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
#  The notebooks are checked here too, because a notebook has no compiler and a
#  broken call or a missing name only shows up on the board, minutes into a
#  test. It costs a second. See tools/verify_notebooks.py.
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
#  FINDING A USABLE PYTHON, AND WHAT TO DO IF THERE IS NOT ONE
#
#  Vivado puts its own Python 2.7 at the front of the PATH, and on this
#  installation that copy cannot even start:
#
#      Fatal Python error: Failed to import encodings module
#      C:\Xilinx\Vivado\2020.1\tps\win64\python-2.7.16\lib\encodings\__init__.py
#
#  So `exec python` from inside Vivado is not the Python you think it is. Every
#  candidate is therefore ASKED its version before being trusted.
#
#  And the more important lesson: THE CHECKS MUST NOT BE ABLE TO STOP A BUILD
#  FOR THEIR OWN REASONS. They are conveniences. If one cannot run, the build
#  carries on with a note. Only a check that runs AND reports a real problem
#  stops anything.
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

# -----------------------------------------------------------------------------
#  Two one-second checks that between them catch the mistakes that have actually
#  cost this project time: a Verilog name that does not line up, and a notebook
#  call that cannot work. Neither replaces the build; both fail faster than it.
# -----------------------------------------------------------------------------
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
# -----------------------------------------------------------------------------
#  THE BLOCK DESIGN'S OUTPUT PRODUCTS
#
#  `system.bd` is a source; everything under bd/system/ip and bd/system/ipshared
#  is generated FROM it - 34 MB of IP and Xilinx library HDL that Vivado can
#  rebuild in a couple of minutes.
#
#  That is why tools/backup.ps1 leaves them out, taking the backup from 78 MB to
#  about 2 MB. The consequence is that a project restored from such a backup has
#  a block design with no output products, and synthesis would fail on it.
#
#  So generate them here if they are missing. It costs nothing when they are
#  already present, and it means a restored copy simply builds.
# -----------------------------------------------------------------------------
set bd_file [get_files -quiet system.bd]
if {$bd_file ne ""} {
    set bd_dir [file dirname $bd_file]
    if {![file isdirectory "$bd_dir/ip"]} {
        puts "  Block design has no output products - generating them now."
        puts "  (Normal after restoring a sources-only backup. Two minutes.)"
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
#  BUILD FINGERPRINT
# -----------------------------------------------------------------------------
#  A hash of every Verilog file in the acquisition system, written into
#  build_id.vh and so baked into the bitstream, where software can read it back
#  at register 0x48.
#
#  WHY. On 2026-07-29 a source file was edited while Vivado had the project
#  open. Vivado did not notice, left synthesis marked complete, and
#  implementation ran from the PREVIOUS DAY'S netlist. The bitstream file was
#  newly written, newly dated and byte-different - and the logic inside it was a
#  day old. A whole afternoon went into re-diagnosing a fault that had already
#  been fixed. File dates cannot catch that. This can.
# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------
#  WHICH COMMIT IS THIS BUILD FROM?
#
#  The fingerprint below proves the bitstream matches the files on this PC. Git
#  proves those files are a particular commit. Recording both closes the loop
#  that cost this project two days:
#
#      register 0x48  ->  bitstream_id.txt  ->  a commit  ->  git checkout
#
#  and you can get back to exactly the logic that is running on the board,
#  months later, with one command.
#
#  That only works if the working tree is CLEAN at build time. Build with
#  uncommitted edits and the bitstream corresponds to no commit that exists -
#  so this warns, loudly, rather than quietly recording a commit that is not
#  what was built.
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
    set git_line "not a git repository (see GIT.md - version control is worth ten minutes)"
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

#  reset_run on BOTH runs, deliberately.
#
#  Vivado decides for itself whether synthesis needs re-running, and it gets
#  that wrong when a file is edited outside the tool while the project is open:
#  it leaves synthesis marked complete and implementation then starts from the
#  stale netlist. Resetting removes the decision. It costs a few minutes and has
#  already saved considerably more than that.
reset_run impl_1
reset_run synth_1

#  Prove the run logs can actually be written, BEFORE launching.
#
#  Vivado launches each run step through a Windows Script Host wrapper
#  (rundef.js) that opens runme.log for writing as its very first act. If that
#  file is locked the wrapper dies immediately with "Permission denied", the
#  child never reports back, wait_on_run blocks for ever, and the GUI sits at
#  "Initializing Design" looking busy. That cost an hour on 2026-08-07.
#
#  reset_run above is supposed to clear these, and it silently does not when
#  the file is held open. So check, and say what is holding it.
#
#  The usual culprits, in order: a leftover vivado.exe from a previous run; the
#  GUI's own Log tab still displaying the last run's log; an editor or tail
#  viewer left open on it; a backup or antivirus sweep over the runs tree.
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
        puts "  Seen 2026-08-07: an ORPHANED cmd.exe - the run's own batch shell,"
        puts "  spawned by Vivado and never reaped - held runme.log and"
        puts "  job.id.log. Windows names it \"Command Processor\" when a delete"
        puts "  is refused. It is also why Vivado said \"PID not specified\" on"
        puts "  shutdown: the launcher died before recording a PID to kill."
        puts ""
        puts "  Close Vivado, then in an elevated PowerShell:"
        puts "    Get-CimInstance Win32_Process -Filter \"Name='cmd.exe'\" |"
        puts "      Where CommandLine -like '*Test_Project*' | Stop-Process -Force"
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
#  Write the fingerprint file NOW, then rewrite it in STEP 4 with the timing
#  verdict once that is known.
#
#  Writing it twice looks redundant. It is not. On 2026-08-03 this write lived
#  only in STEP 4, and STEP 4 did not complete - so bitstream_id.txt did not
#  exist at all. run_on_board.ps1 skips that file silently when it is missing,
#  check_system.py had nothing to compare against, and reported "OK" for a
#  bitstream it had never verified. The board was still running a build from
#  before the sequencer existed.
#
#  So: the file must exist the moment a bitstream exists, even if everything
#  after this point fails. It is marked "not yet checked" until STEP 4 replaces
#  it, and check_system.py treats that as unverified rather than as approval.
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
#  BUG, fixed 2026-08-03. This line used to read:
#
#      set fail [llength [get_timing_paths ... -slack_lessthan 0]]
#
#  There is no such option. Vivado 2020.1 answers:
#
#      ERROR: [Common 17-170] Unknown option '-slack_lessthan'
#
#  and an ERROR in a sourced Tcl script ABORTS IT. So STEP 4 has never once run
#  to completion on this project. No timing verdict was ever printed, STEP 5
#  never ran, and - once the fingerprint write was moved into STEP 4 - that file
#  stopped being written too, which is what let a stale bitstream sit on the
#  board while check_system.py reported no issues.
#
#  One wrong option name, and every check downstream of it silently ceased to
#  exist. The build still produced a bitstream, which is what made it invisible.
#
#  Replaced with options that exist in every Vivado version: ask for the worst
#  paths and count the negative ones here. Capped, because asking for tens of
#  thousands of paths is slow and the exact number stops mattering once it is
#  clear the design fails.
# -----------------------------------------------------------------------------
#  Wrapped in catch, for the same reason. If measuring timing fails again -
#  another renamed option, a Vivado upgrade - the script must carry on and say
#  "I could not check" rather than dying and taking every later step with it.
#  An unmeasured build is treated as a FAILING one, never as a passing one.
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
#  Record the fingerprint next to the bitstream, so it can be copied to the
#  board alongside it and compared with what the chip reports - AND record
#  whether this build met timing, because the fingerprint alone only proves the
#  board is running what was built, not that what was built is trustworthy.
#
#  On 2026-08-03 a build missed timing by 6.799 ns with 6224 failing endpoints.
#  It produced a bitstream, a valid fingerprint, and a confident "NEXT STEPS:
#  copy it to the board". Register reads came back as zeros and an afternoon
#  went into looking for a missing module that was present all along.
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
    # -------------------------------------------------------------------------
    #  A bitstream exists, but STEP 4 just said not to trust it. Saying "copy it
    #  to the board" here as though nothing had happened is how the 2026-08-03
    #  afternoon was lost: the FAIL scrolled past, the cheerful NEXT STEPS were
    #  at the bottom where the eye lands, and the board was loaded with logic
    #  that could not work. The verdict has to be the LAST thing on screen.
    # -------------------------------------------------------------------------
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
    puts "       not widen them, and CHANGELOG.md for 2026-08-03."
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
    puts "    3. Run the test notebooks in order, starting from Test Stage 2."
} else {
    puts "  NO BITSTREAM WAS PRODUCED."
    puts ""
    puts "  Look in the Messages tab for entries marked ERROR (red). Warnings"
    puts "  (yellow) do not stop a build; errors do. CHANGELOG.md lists every"
    puts "  warning this project is known to produce and whether it matters."
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
