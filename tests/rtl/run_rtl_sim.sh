#!/bin/bash
# ===========================================================================
#  run_rtl_sim.sh - simulate the real Verilog, before and after 2026-08-07.
#
#  Yosys elaborates each source file into a cycle-accurate C++ model (CXXRTL);
#  tb_out_stage.cc instantiates the pre-edit and post-edit versions side by
#  side and drives them with identical stimulus. Nothing is compared against a
#  hand-written model - the design is compared against itself.
#
#  Needs:  pip install yowasp-yosys      (a WebAssembly build of Yosys - no
#                                         system packages, no root)
#          g++                            (any C++17 compiler)
#
#  Usage:  ./run_rtl_sim.sh [path-to-pre-edit-copies]
#
#  The pre-edit copies default to whatever git has in HEAD, so this works from
#  a clean checkout without keeping stale files around.
# ===========================================================================
set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
RTL="$ROOT/fpga"
WORK="${TMPDIR:-/tmp}/rtl_sim_work"
export PATH="$HOME/.local/bin:$PATH"

YOSYS_PKG=$(python3 -c "import yowasp_yosys,os;print(os.path.dirname(yowasp_yosys.__file__))")
CXXRTL_INC="$YOSYS_PKG/share/include/backends/cxxrtl/runtime"

rm -rf "$WORK"; mkdir -p "$WORK"; cd "$WORK"

echo "--- fetching the pre-edit sources from git HEAD ---"
for f in red_pitaya_resonator.v red_pitaya_phaseshift.v; do
    git -C "$ROOT" show "HEAD:fpga/$f" > "old_$f"
done

#  Rename so both versions can live in one program.
sed 's/\bred_pitaya_resonator\b/reso_old/g'  old_red_pitaya_resonator.v  > reso_old.v
sed 's/\bred_pitaya_resonator\b/reso_new/g'  "$RTL/red_pitaya_resonator.v"  > reso_new.v
sed 's/\bred_pitaya_phaseshift\b/ps_old/g'   old_red_pitaya_phaseshift.v > ps_old.v
sed 's/\bred_pitaya_phaseshift\b/ps_new/g'   "$RTL/red_pitaya_phaseshift.v" > ps_new.v

echo "--- elaborating (this is also the lint pass) ---"
for m in reso_old reso_new ps_old ps_new; do
    yowasp-yosys -q -p "
        read_verilog -sv $m.v
        hierarchy -check -top $m
        proc
        opt -fast
        check -assert
        write_cxxrtl -header ${m}_rtl.cc
    " 2>&1 | grep -iE "warning|error" || true
    #  Every CXXRTL header uses the same include guard, so including four of
    #  them in one program silently keeps only the first. Give each its own.
    sed -i "s/CXXRTL_DESIGN_HEADER/CXXRTL_DESIGN_HEADER_$(echo "$m" | tr 'a-z' 'A-Z')/g" \
        "${m}_rtl.h"
    #  Same for the C-API entry point, which each file defines under one name.
    #  Nothing here uses the C API; this just lets all four link together.
    sed -i "s/cxxrtl_design_create/cxxrtl_design_create_${m}/g" "${m}_rtl.cc" "${m}_rtl.h"
done

#  The top level's DAC summation leg, which CH B has never exercised.
cp "$HERE/tb_dac_sum.sv" .
yowasp-yosys -q -p "
    read_verilog -sv tb_dac_sum.sv
    hierarchy -check -top tb_dac_sum
    proc
    opt -fast
    check -assert
    write_cxxrtl -header tb_dac_sum_rtl.cc
" 2>&1 | grep -iE "warning|error" || true

echo "--- compiling ---"
g++ -std=c++17 -O2 -I. -I"$CXXRTL_INC" \
    "$HERE/tb_out_stage.cc" reso_old_rtl.cc reso_new_rtl.cc ps_old_rtl.cc ps_new_rtl.cc \
    -o tb_out_stage
g++ -std=c++17 -O2 -I. -I"$CXXRTL_INC" \
    "$HERE/tb_dac_sum.cc" tb_dac_sum_rtl.cc -o tb_dac_sum

echo "--- running ---"
rc=0
./tb_out_stage || rc=1
./tb_dac_sum   || rc=1
exit $rc
