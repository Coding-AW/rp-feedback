# rtl_sim — simulating the real Verilog before building it

A 25-minute Vivado build is an expensive way to find out that a register was
put in the wrong place. This directory runs the actual RTL on a PC in about
ten seconds.

## Vivado/XSim timing-fix regression

Run `run_timing_fixes_sim.ps1` from PowerShell. It elaborates the actual phase
shifter RTL and checks the two changes made after the latest routed timing
report:

- physical ADC mode is unchanged while diagnostic digital loopback gains
  exactly one 125 MHz sample register;
- generator-only, monitor-only, combined and saturated OUT2 arithmetic;
- OUT2 converter inversion and the monitor-off reset state;
- identical writes and independent reads in both delay-memory copies.

This is a functional pre-build test. Only Vivado implementation can confirm
that the arrays map to BRAM and that routed timing closes.

## Run it

```
./run_rtl_sim.sh
```

Needs `pip install yowasp-yosys` (a WebAssembly build of Yosys — no root, no
system packages) and any C++17 compiler. Nothing else. Exit status is 0 only if
every check passes.

## How it works

Yosys elaborates each source file into a cycle-accurate C++ model (CXXRTL). The
script pulls the **pre-edit** version of each file straight out of `git HEAD`,
renames the modules so both can live in one program, and the testbenches
instantiate old and new **side by side, driven by identical stimulus**.

That is the point. `software/validation/validate_out_stage.py` models the same
logic in Python, but that model is a hand translation — it can share a
misreading with the source it was written from, and agreeing with itself proves
nothing. Here, nothing is compared against a model. The design is compared
against itself, before and after.

## What is checked

`tb_out_stage.cc` — 18 checks

| | |
|---|---|
| T1, T2 | the resonator's output-stage register is a **pure one-clock delay**, and `DELAY = 12` reproduces the old `DELAY = 13` bit for bit. 4 resonances × 5 stimuli × 3 output shifts, plus every `DELAY` from 1 to 255 including the buffer wrap |
| T3 | the emulated resonance is unchanged — same ring frequency, same decay energy |
| T4, T5 | with the monitor off, `dat_a_o` is bit-identical to the pre-edit file and `dat_b_o` is zero on every cycle. The feedback path is untouched |
| T6 | the monitor: both sources verbatim, shifts that saturate rather than wrap, `MON_CLIP` latching and clearing and re-arming, readback of all 24 field combinations |
| T7 | bypass, the sequencer coefficient path, and registers `0x00`–`0x14` all unchanged |

`tb_dac_sum.cc` — 6 checks, on the top level's DAC summation leg, which channel
B had never exercised: all 16384 monitor values, ~78k monitor-plus-generator
combinations, all four corners.

`tb_sequencer.sv`, run by `run_sequencer_sim.ps1`, checks the real sequencer RTL
with the installed Vivado simulator after its bus input was registered to close
the processor-to-`mem_dur` timing path. It verifies the one-clock-delayed,
one-clock-wide acknowledgement; captured address and data; every word of all
eight parameter sets; control, trigger and version registers; consecutive
transactions; and the unchanged clock-by-clock sequence engine.

## Read the header of `tb_dac_sum.sv` before trusting it

**Yosys 0.68 loses the signedness of an element select on a packed array of a
signed type.** A verbatim copy of the top level therefore reported that a
monitor sample of −1 reaches the converter as +8191 — a catastrophic-looking
result that was entirely the simulator. Slang, which implements the full
language and is what Vivado follows, gets it right; and channel A uses the
identical construct on a loop that works on real hardware.

The file explains this at length, deliberately. A test that fails loudly for a
reason unrelated to the design is an invitation to "fix" a correct one.

## What this cannot tell you

**Whether the design meets timing.** That is a question about placement and
routing on a specific device, and only Vivado can answer it. This proves
*equivalence and behaviour* — that the thing about to be built is the thing
intended. Read the slack in `bitstream_id.txt` afterwards as usual.
