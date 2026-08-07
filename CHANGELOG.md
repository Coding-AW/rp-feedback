# Change log

Every edit made to this project, newest first. Baseline is the stock Red Pitaya
FPGA project v0.94 for the STEMlab 125-14 (XC7Z010), Vivado 2020.1.

Two custom subsystems live here:

- **Feedback path** (`phaseshift_custom/`) — variable phase shifter, working and
  characterised.
- **Acquisition system** (`acquisition_custom/`) — in progress.

Every Jupyter notebook lives in `jupyter_notebooks/` (moved there 2026-08-06), with its
off-board test harness in `jupyter_notebooks/tests/`.

Both reproduce parts of Herkenhoff *et al.*, *A digital feedback system for advanced
ion manipulation techniques in Penning traps*, Rev. Sci. Instrum. **92**, 103201 (2021).

---

## 2026-08-07 — The emulator returns the answer it was given, on hardware

Step 0 and Step 1 pass on bitstream `0xC207CBD8`. The two-way look-ahead resonator works on
silicon: the recursion runs in two clocks across two interleaved banks, `Emulator.config()` writes
four coefficients, the pole is recovered from `COEF_C2`/`COEF_S2`, and the self-test gets back the
centre and Q it asked for.

That closes an arc that started with a bitstream failing timing by 6.9 ns:

| | 08-03 | 08-07 a | 08-07 b | now |
|---|---|---|---|---|
| WNS | -6.907 ns | -3.482 ns | | **-0.251 ns** |
| Failing endpoints | 6224 | 3211 | | **6** |
| Emulator self-test | untrustworthy | untrustworthy | flat, Q = 1.1 | **PASS** |

**This is the first time the Step 1 self-test has been trustworthy.** On every earlier build the
emulator sat behind failing timing paths, so the notebook's one guarantee of instrument integrity
was itself unverified. Every number in `.bak18` was taken under that.

### One false alarm on the way, and the guard it produced

The first attempt reported `f0 = 39.199818 MHz, Q = 1.1, residual 0.0010` - a beautifully fitted
piece of nonsense. Cause: the notebook that ran was the previous one, which writes only `COEF_C`
and `COEF_S`. On the new hardware that leaves `c2 = s2 = 0`, the recursion has no pole, and the
emulator becomes a pass-through. Simulated against the cycle-exact model of the loaded build:

| | old notebook (c2 = s2 = 0) | correct notebook |
|---|---|---|
| Response across +-2.5 linewidths | **1.008 max/min - flat** | 5.10 max/min |
| Position of the peak | index **24 of 25**, an edge | index 12, the centre |

A flat curve with its maximum at the edge forces the Lorentzian fit to extrapolate, which puts the
centre outside the swept band and the width at tens of megahertz - and fits it with a tiny residual,
because a straight line fits very well indeed. Exactly the reported numbers.

This is the board-copy drift `tools/README.md` already warns about: the notebook on the board and
the notebook in the project are separate files.

Two guards added:

- **`Emulator.config()` reads back 0x28/0x2C** and refuses if they did not stick - catching a new
  notebook on an old bitstream, and naming the reverse case in the message.
- **Step 0 probes `COEF_C2`** with a bit pattern. An old bitstream does not decode 0x28 and returns
  zero, so preflight fails loudly instead of letting Step 1 produce a plausible wrong answer.

The reverse mistake - old notebook, new hardware - cannot be caught from inside the old notebook,
which does not know to look. Push the master copy with `run_on_board.ps1`.

### Outstanding

- **WNS -0.251 ns**, six paths, all `set_oshift -> dly_buf`: the output stage's variable barrel
  shifter, the noise add and the saturation feeding the delay line's block RAM. Not the loop. One
  pipeline register fixes it; the output stage is explicitly non-recursive. Costs one clock, so
  `delay` goes 13 -> 12.
- **The OUT2 monitor is still unimplemented** - `red_pitaya_phaseshift.v` line 364 still reads
  `assign dat_b_o = {DWI{1'b0}}`. Design is in `EXTERNAL_VERIFICATION_PLAN.md` section 1.2.
- The working tree carries 85+ uncommitted changes, so `bitstream_id.txt` cannot name a commit and
  the register 0x48 -> commit chain is broken.

---

## 2026-08-07 — An hour on "Initializing Design". The run had already died in its first second

Vivado sat on "Initializing Design" for over an hour. It was not working. `impl_1/exception.log`,
written at 11:59:

```
ERROR: Exception caught trying to open file
       ...\Test_Project.runs\impl_1/runme.log
    Exception name: Error
    Exception error code: 70
    Exception message: Permission denied
```

Vivado launches each run step through a Windows Script Host wrapper (`rundef.js`) whose first act
is to open `runme.log` for writing. The old log from the 11:19 run was still there - 71,826 bytes,
untouched - and locked. The wrapper died on that line, `init_design` never started, the child
never reported back, and `wait_on_run impl_1` blocked for ever while the GUI showed a phase that
had not begun.

`reset_run impl_1` on line 342 is supposed to clear that directory. It **silently failed** to
remove the locked file and returned as if it had worked, which is why nothing looked wrong.

### What it was not

Synthesis ran fine, immediately before: **0 errors, 0 critical warnings**, 4m28s, checkpoint
written. The new two-bank resonator synthesises. DSPs went 17 -> **26 of 80** (the estimate was
about 10 extra; the real figure is 9), block RAM 36.5 of 60.

### Fixed

`build_project.tcl` STEP 3 now proves both run logs are writable *before* launching, and refuses
with the likely causes if not:

```tcl
foreach _run {synth_1 impl_1} {
    set _log "$proj_root/Test_Project.runs/$_run/runme.log"
    if {[file exists $_log] && [catch {file delete -force $_log} _msg]} { ...stop... }
}
```

**The holder turned out to be an orphaned `cmd.exe`** - the run's own batch shell, spawned by
Vivado at 11:59 and never reaped. Windows reports it as *"being used by Command Processor"* when
a delete is refused, and it is also why Vivado printed `[Vivado 12-1017] Problems encountered:
1. PID not specified` on shutdown: the launcher died before recording a PID, so there was nothing
to terminate. `reset_run impl_1` then removed everything in the directory it was allowed to and
left exactly the two files the orphan held - `runme.log` and `job.id.log` - which is what made
the cause visible.

Kill it from an elevated PowerShell:

```powershell
Get-CimInstance Win32_Process -Filter "Name='cmd.exe'" |
  Where-Object { $_.CommandLine -like '*Test_Project*' } | Stop-Process -Force
```

then delete the whole `Test_Project.runs/impl_1` folder; Vivado recreates it. If the command line
filter finds nothing, Resource Monitor -> CPU -> Associated Handles -> search the file name gives
the PID directly. The guard now clears `runme.log`, `job.id.log` and `exception.log` for both
runs, and names all of this if it cannot.

This is the same shape as the `-slack_lessthan` bug and the missing `bitstream_id.txt`: a step
that fails without saying so, and a later step that then reports something untrue - here, a
progress indicator for work that never started.

---

## 2026-08-07 — Two-way look-ahead implemented in Verilog

The design validated earlier today is now written. `red_pitaya_resonator.v` no longer tries to
close a recursive multiply-add in one clock.

### What changed in the module

| | Before | After |
|---|---|---|
| Recursion | one clock, `x[n+1] = M x[n] + b[n]` | two clocks, `x[n+2] = M^2 x[n] + M b[n] + b[n+1]` |
| State | `u, v` | two banks `uA/vA`, `uB/vB` holding even and odd sample indices |
| Coefficients | `COEF_C`, `COEF_S` | plus **`COEF_C2` (0x28)** and **`COEF_S2` (0x2C)** |
| Loop stages | one | `acc <= c2*u - s2*v` then `u <= clamp((acc + add) >>> SHIFT)` |
| Drive | concatenated into the recursion | `c*d` and `s*d` registered outside the loop, summed into one ready-made addend |

The two banks are one clock apart, so one is always in stage 1 while the other is in stage 2:
both stages work every clock and the output still changes every clock. **The path genuinely
crosses two clock edges, so no multicycle constraint is needed** - a clock enable would not have
done, because static timing analysis is edge-based and would still have checked it in one.

`COEF_C` and `COEF_S` are still required. They no longer drive the recursion, but they carry the
`M b[n]` drive term, so **all four coefficients must be written**.

### Verified before it was written, and again after

`acquisition_custom/validate_resonator_pipelined.py` now contains a **cycle-exact model of the
Verilog** - register for register, clock for clock, including the drive pipeline and the bank
schedule. That is the point: a bank alignment or drive pairing one clock out still produces a
resonance, just not the right one.

| Check | Result |
|---|---|
| One clean resonance at the frequency asked for | 37.000, 39.940, 40.000, 22.000 MHz - exact |
| Pole recovered from `(c2, s2)` vs pole produced | within 0.001 linewidths and 2.6% Q, against Step 1 tolerances of 0.20 and 5% |
| Driven steady state, normal and hard drive | 0.03-0.05%; clip flag identical to the single-clock form |
| Polyphase image at `fs/2 - f0` | 45.6 to 58.0 dB down |

Also passing: `verify_rtl.py`, `validate_resonator_loop.py`, `validate_cic.py`,
`validate_dds_mixer.py`, `validate_fir.py`, `stage0_analysis_selftest.py` (13/13),
`verify_notebooks.py`, the notebook name audit, and all nine mock scenarios.

The module was additionally parsed with **pyverilog** as a syntax check, with
`red_pitaya_phaseshift.v` and `red_pitaya_acq_cic.v` as controls. That caught one thing: the
first draft used `function signed [SW-1:0] clamp;`, which is legal Verilog-2001 but which the
parser rejected. Replaced with four wires using the same conditional the single-clock version
used - the rest of the module uses no functions, so this is also more consistent.

### Software, changed to match

- **`Emulator.config()`** writes four coefficients and reports the quantised pole **from c2 and
  s2**, because that is the pole the hardware now realises. `arctan2` gives `2*w0` modulo `2*pi`
  and `2*w0` passes `pi` above 31.25 MHz, so the branch is lifted onto the one nearest the
  frequency asked for - which is known, because it produced the numbers.
- **`delay` default 15 -> 13.** The module's own pipeline is two clocks longer, so 13 + 2 is the
  board's real 15. Both call sites updated.
- **`jupyter_notebooks/tests/fakehw.py`** decodes the pole the same way, so the off-board tests
  exercise the same arithmetic as the board.

### Known artefact, documented in the module header

Two interleaved banks are the two polyphase components of one sequence, and quantisation stops
their relative phase being exactly `w0`. The residue is a mirror line at `fs/2 - f0` - 22.5 MHz
for a 40 MHz pole, 46 to 58 dB down. It cannot enter a measurement, because the receiver's clean
window is +-12 kHz and the image sits megahertz away. It **will** appear in a wide band survey if
the emulator is left enabled during one.

### Still to do

**Rebuild and read the slack.** The predicted stage delays are about 5.8 ns for stage 1 and
3.5 ns for stage 2, both inside 8 ns, but that is an estimate from the routed report's own
numbers and not a timing run. Expect roughly 10 DSP slices where there were 4, against 17 of 80
used. Then re-run Step 1 and Step 4b and compare against `.bak18`: if the recovered Q moves, the
old failing paths had been affecting the emulator and `MIN_AMP_FOR_FIT` needs re-deriving.

And build through `build_project.tcl`, not the Vivado GUI - the 2026-08-07 rebuild left
`bitstream_id.txt` unwritten and `build_id.vh` stale at `0x096CEAD0`.

---

## 2026-08-07 — The single-clock recursion cannot close on this device. The numbers now say so

The rebuild moved WNS from **-6.907 ns to -3.482 ns** and TNS from -6290 to -1403.9, with failing
endpoints down from 6224 to 3211. The drive-before-shift change did what it was meant to. What
it exposed is that the remaining distance is not made of removable logic.

### Where the time goes now

The worst path moved from the u recursion to the **v** recursion, which the last change did not
touch - v has no drive term, so its `+ ROUND` was left alone:

```
Source      i_reso/v_reg[2]/C        Destination  i_reso/v_reg[15]/R
Data Path   10.865 ns                Logic Levels 11 (CARRY4=7 DSP48E1=2 LUT1=1 LUT5=1)

    FDRE C->Q                     0.518
    route into DSP                0.692
    DSP48E1  A[2] -> PCOUT[47]    4.036    <- multiply + ALU
    cascade net                   0.002
    DSP48E1  PCIN[47] -> P[16]    1.518    <- second ALU
    route                         0.961
    LUT1                          0.124    <- carry-in taken from P[16]
    CARRY4 x 7                    1.234    <- ROUND propagating up to bit 42
    route + setup                ~1.780
                                -------
                                 10.865   against 7.907 available
```

Two separate findings, and only one of them is fixable by rearranging logic.

**Vivado is already doing the right thing with the DSPs.** `cv` produces PCOUT and `v_nxt0`
consumes PCIN, so `su + cv` is computed in two cascaded DSP48E1s with no fabric adder between
them. There is nothing left to hand it.

**The `+ ROUND` is in fabric, and it is not an adder.** It is a +1 at bit 16 whose carry then
has to propagate up to bit 42 - a LUT1 generating the carry from `P[16]` and seven CARRY4 levels
carrying it. 1.358 ns to add a single constant bit, because it lands below the shift point and
the DSP has already closed its books.

**And the part that decides it:** the two cascaded DSP stages cost **5.554 ns between them**.
Add the flip-flop's 0.518, the 0.692 route into the first DSP, and the 1.780 of route and setup
at the far end, and the floor is **8.546 ns against 7.907 available - still -0.639 ns with every
removable gate deleted**. A rotation is two products summed, so two DSP stages is the minimum
depth. **The single-clock recursion cannot close at 125 MHz on this part, however the fabric
around it is arranged.** That is now arithmetic from the routed report, not an opinion.

### The fix, and what testing says about it

Two-way look-ahead. A register cannot go inside a recursive loop, but two samples can be
computed per update with the extra clock absorbed into the coefficients:

```
x[n+1] = M x[n] + b[n]                      M = (1/2^S)[[c,-s],[s,c]] = r Rot(w0)
x[n+2] = M^2 x[n] + M b[n] + b[n+1]         M^2 = r^2 Rot(2 w0)
```

so the squared coefficients come out of software exactly the way `c` and `s` already do -
`c2 = r^2 cos(2w0) 2^S`, `s2 = r^2 sin(2w0) 2^S`. Two interleaved state banks, even and odd,
each updated on alternate clocks, gives each update **16 ns for the same 10.865 ns of logic:
+5.042 ns of slack**. Every term after the two products depends only on registered inputs, so it
sits outside the loop and can be pipelined freely.

New: `acquisition_custom/validate_resonator_pipelined.py`. Bit-accurate models of both forms,
including truncation and sign extension at every wire width. Bit-equality is the wrong test here
- `c2, s2` quantise separately and the rounding lands once per two samples instead of twice - so
what it checks is whether the emulator is still the same instrument:

| Check | Result |
|---|---|
| One clean resonance at the frequency asked for | 37.000, 39.940, 40.000, 22.000 MHz - all exact |
| The pole recovered from `(c2, s2)` matches the pole produced - which is what the Step 1 self-test compares against | inside 0.001 linewidths and 2.6% on Q, against tolerances of 0.20 and 5% |
| Driven steady-state amplitude, normal and hard drive | agrees to 0.03-0.05%; clip flag identical |
| Polyphase image at `fs/2 - f0` | 45.9 to 57.0 dB below the peak |

**The image is inherent to the architecture and is worth naming.** Two interleaved banks are the
two polyphase components of one sequence; if their relative phase is not exactly `w0` - and
quantisation guarantees it is not - the residue appears as a mirror line at `fs/2 - f0`. At
40 MHz that is 22.5 MHz, 45.9 dB down. It cannot enter any measurement: the receiver's clean
window is +-12 kHz and the image sits 17.5 MHz away. But it will appear in a Step 2 band survey
if the emulator is ever left enabled during one, and it should be in the module header rather
than discovered later.

### One measurement trap this script walked into first, recorded so it is not repeated

The first version measured f0 and Q by Fourier transform of the impulse response and reported
Q = 4864 for a resonator configured at Q = 250 - in every case, for both forms. A Q = 250
resonator at 37 MHz decays in `Q/(pi f0)` = 2.15 us, which is 269 samples, and the transform was
65536 points long: it was measuring the width of the Hanning window, not the resonator. Replaced
with a least-squares linear-prediction fit of `y[n] = a1 y[n-1] + a2 y[n-2]`, which recovers the
poles directly and is immune to windowing. **A Fourier transform much longer than the ringing
measures the window.**

### Status

The design is validated; the Verilog is not yet written. Also outstanding from the same rebuild:

- **`bitstream_id.txt` was not written and `build_id.vh` was not regenerated** - it still reads
  `GEN_BUILD_ID = 32'h096CEAD0` from 2026-08-03 22:06. So this bitstream reports the **same
  fingerprint as the one it replaces**, and `check_system.py` will report "could NOT be
  verified". That is the Vivado-GUI path the 2026-08-03 entry documents. Rebuild through
  `build_project.tcl` before loading, or there will be two different bitstreams both claiming
  0x096CEAD0.
- The one non-resonator failing path is `ps/system_i/axi_protocol_converter` at **-0.028 ns** on
  `clk_fpga_3`, a single endpoint inside Xilinx IP. Worth a glance, not worth a redesign.

---

## 2026-08-06 — The one-clock recursion had two adders in series. One of them was wiring all along

`bitstream_id.txt` had been carrying its own verdict since 2026-08-03:

```
# timing   : *** FAIL *** worst slack -6.907 ns, 2000 failing path(s)
# WARNING  : this bitstream does not meet timing. Measurements taken
#            from it cannot be trusted, whatever the fingerprint says.
```

The `md5sum` of the bitstream on the board matches `impl_1/red_pitaya_top.bit`, so the board is
running that build. Every published coil number came from it.

### Why the fingerprint could not have told us

`BUILD_ID` is an FNV-1a hash of six **source files** (`build_project.tcl` lines 270-279). Two
different builds of identical source produce an identical fingerprint. So register `0x48`
answers "which source", never "which build" and never "did it meet timing" - and the timing
verdict lives only in a comment line in a text file on the PC, which never reaches the board.
`check_system.py`'s "OK, build fingerprint 0x..." is therefore weaker than it reads. Noted as a
gap; the fix is a separate `BUILD_STAMP` register carrying the build time and a timing-passed
bit, so the board can say *"running the build of 2026-08-03 22:14, which FAILED timing"*.

### The diagnosis

With `SW = 25`, `CW = 18`, `SHIFT = 17`, the recursion was

```
u ──DSP──► c*u ──┐
v ──DSP──► s*v ──┴─► (cu - sv + ROUND) ──► >>> 17 ──► + drive_r ──► sat ──► u
                        43-bit adder                   26-bit adder
                        11 CARRY4                      7 CARRY4
```

11 + 7 = **18 CARRY4**, and the routed report shows exactly `CARRY4=18 DSP48E1=2`, data path
14.131 ns against 8.000 ns. Two adders in series inside a loop that must close in one clock.

The 2026-08-03 saturation change had already removed the overflow comparator's carry chain from
this path. What it left behind were the two *arithmetic* adders, and the note it ended with -
*"this shortens the loop but does not by itself make it close in 8 ns"* - was correct.

### The fix

The second adder need not be in the loop at all. For integers,

```
floor(X / 2**S) + D  ==  floor((X + D*2**S) / 2**S)
```

so the drive can be added **before** the shift. And `ROUND` is a single 1 at bit `SHIFT-1` while
`drive_r << SHIFT` has nothing below bit `SHIFT`, so their sum is a **concatenation** - not an
adder, not even a lookup table:

```verilog
ROUND + (drive_r <<< SHIFT)  ==  {drive_r, 1'b1, {(SHIFT-1){1'b0}}}
```

`red_pitaya_resonator.v` now reads

```verilog
wire signed [SW+CW: 0] drive_round =
    $signed({{(SW+CW+1-18-SHIFT){drive_r[17]}}, drive_r, 1'b1, {(SHIFT-1){1'b0}}});
wire signed [SW+CW: 0] u_acc = cu - sv + drive_round;
wire signed [SW: 0]    u_nxt = (u_acc >>> SHIFT);
```

One 26-bit carry chain leaves the recursion and becomes wiring. Seven of the path's twenty-three
logic levels are gone.

### Verified equivalent, not approximately

New: `acquisition_custom/validate_resonator_loop.py`. It models both forms bit-accurately -
including the Verilog truncation and sign-extension at every wire width - and compares them:

| Check | Result |
|---|---|
| Exhaustive at reduced widths (`SW=6, CW=5`) | 1,464,320 combinations, 0 mismatches |
| Random at the real widths | 400,000 trials including every corner, 0 mismatches |
| Full 20,000-sample runs at 37 MHz/Q=250, 39.94 MHz/Q=180, and 40 MHz/Q=5000 driven into saturation | bit-identical output and clip flag in all three |

The script also predicts the carry-chain count from the widths and prints `11 + 7 = 18`, which is
what made the diagnosis certain rather than plausible: it matches the routed report exactly.

`tools/verify_rtl.py` passes; `stage0_analysis_selftest.py` passes 13 of 13.

### Status - NOT yet closed

**This is an equivalence proof, not a timing result.** Whether the shorter path closes 8 ns is a
question for Vivado. The other large term is the unregistered DSP multiply, which this change
does not touch, and an `A*B -> P` path with no internal pipeline registers is several nanoseconds
on a -1 speed grade part. A single-clock recursive multiply-add at 125 MHz is marginal by
construction.

**Rebuild and read the slack.** If it is still negative, the recursion needs pipelining, and the
design is written up in `EXTERNAL_VERIFICATION_PLAN.md` section 1.1b: two-way look-ahead, where
`x[n+2] = M**2 x[n] + M b[n] + b[n+1]` and `M**2 = r**2 Rot(2w0)`, so the squared coefficients are
computed in software exactly the way `c` and `s` already are. Two interleaved state banks updated
on alternate clocks give each update 16 ns. Costs about 12 DSP slices instead of 4, against 17 of
80 currently used.

### Also still open

The summary report details only its ten worst paths, all in `i_reso`. But 6,224 of 29,573
endpoints fail - twenty-one percent of the design, far more than `i_reso`'s own register count -
so the earlier claim that the failures are "all in the resonator's recursive loop" is **not
established**. Run

```tcl
report_timing -from [get_cells i_ps/*]  -max_paths 50 -slack_lesser_than 0
report_timing -from [get_cells i_acq/*] -max_paths 50 -slack_lesser_than 0
```

If both are clean, the coil measurements stand: `i_reso` is disabled throughout Steps 2-8, its
registers do not toggle, and a quiescent path cannot capture a wrong value. Only the Step 1 and
9a self-tests and the Step 4b fitter calibration are affected - which is bad enough, since the
self-test is the notebook's entire guarantee of instrument integrity. If either returns paths,
the coil numbers are in question too.

---

## 2026-08-06 — The coil notebook now measures its own calibrations; two guardrail bugs found by putting it under test

The bench coil notebook carried a configuration cell full of numbers that had been
measured once and typed back in: the amplifier's gain, the working drive, the
coarse search step, an off-board vector network analyser's answer for `f0` and `Q`.
That is fine on a bench where nothing changes. It is wrong for a resonator that
will go into a trap and then into a cryostat, because **a constant copied from a
previous session is a wrong answer waiting to be believed** — and nothing in the
notebook could tell the difference.

Renamed `Test - Coil wo Amplifier.ipynb` → **`Test - Resonator Coil
Characterisation.ipynb`**, and reworked it so every calibration is measured and
adopted at run time.

### The Step 4 group, reordered so each step runs on the previous one's measurement

Previously: signal budget, then the L/C cross-check, then the amplifier ladder,
then the drive-window scan — with the last two ending in *"set this and re-run
from Step 3"*. Nobody re-runs from Step 3. Every number in Steps 5–8 therefore
belonged to a drive that had been superseded four cells earlier.

| was | is | what it now does |
|---|---|---|
| Step 4c | **Step 4a** | Amplifier gain ladder. Adopts the measured gain and recomputes `DRIVE_LINEAR_MAX` from it |
| Step 4d | **Step 4b** | Drive window. Adopts the top of the window as `DRIVE_FRAC`, then **re-runs the Step 3 refine-and-fit at it** |
| Step 4 | **Step 4c** | Signal budget, re-measured at the adopted drive |
| Step 4b | **Step 4d** | The coil against its known L and C, using the final `f0` and `Q` |

`refine_and_fit()` and `measure_transfer()` were factored out of Step 3 and Step 4
so that the re-measurement is the *same code path*, not a copy of it. `AUTO_CALIBRATE`
turns the adoption off for anyone who wants the old behaviour.

Also removed: the hardcoded `4.46 / 0.21` noise ratio printed by Step 8d, which was
a figure from an earlier run; it now comes from Step 4c's own calculation. And the
Step 7 drift verdict, which compared against a remembered "7-minute scan", now
computes the Step 8c map's cost from `FB_MAP_*` as configured.

### Two bugs the mock found, both in guardrails

**1. The search could report noise as a discovery.** Step 3's coarse pass accepted a
candidate on contrast alone — 6 dB above the band median. But `|z|²` on an empty band
is exponentially distributed, so the largest of 350 points sits about **8 dB above the
median whatever the averaging**: the ratio is scale-free, and more averaging does not
move it. A 6 dB threshold passes pure noise. On a resonator narrow enough that the
100 kHz coarse grid stepped over it, the search reported the biggest noise excursion
in the band, at 54.1 MHz, and the automatic step-halving never fired because the noise
had already "passed".

Fixed by confirming a candidate before committing to it: scan the neighbourhood twice
and **correlate the two scans**. A resonance puts the same shape on the grid both
times; two realisations of noise are independent and correlate at zero give or take
1/√N. Correlation rather than "do the two maxima agree", because the top of a broad
line is flat and its argmax wanders by a good fraction of a linewidth while a narrow
line's does not — one threshold cannot serve both. The contrast figure is now measured
against the *coarse* pass's median, not the zoomed window's: on a line wider than the
window the local median is most of the way up the peak, and a perfectly good resonance
measures 2 dB of contrast against itself.

**2. Adoption could loosen a ceiling on the strength of a noisy measurement.** With an
amplifier declared but not fitted, the gain ladder measured +9.5 dB of nothing in
particular, and the new auto-adopt logic dutifully raised `DRIVE_LINEAR_MAX` from
0.0065 to 0.106 — a 24 dB loosening derived from noise. Adoption may now **tighten** a
ceiling freely but refuses to loosen one: a measured gain more than 3 dB *below* the
declared figure is reported and discarded, and the stricter declared value kept. The
causes — amplifier absent, unpowered, cable off, signal in the noise — are all safe
under the tighter limit and unsafe under the looser one. A measured gain more than
3 dB *above* the declared one still aborts, as before.

### The vector network analyser is gone

`VNA_F0` and `VNA_Q` held a single measurement from a single day. Every reference is
removed — the configuration entries, the Step 4d comparison block, the summary table
row, the JSON keys and the prose. The agreement table now compares the swept fit
against the alternate-decimation fit, both taken this run.

### Step 8d sweeps each setting on its own span

Feedback narrows the line by 1/(1−K), so across the family the linewidth spans more
than an order of magnitude — 28 to 414 kHz on the mock. A span fixed at the unfed
linewidth puts three points across the narrowest curve, and three points do not look
like a Lorentzian. Each setting now gets a span predicted from the Step 8b slope, then
refined by a second pass around what the first pass actually found. The figure has two
panels, both scaled from this run's fits: (a) from the widest fitted line, (b) centred
and scaled on the **unfed** line, which is the curve the whole family is quoted
against. Each curve carries its `Q` and resonant frequency in the legend, with the same
numbers repeated as a table underneath in the thesis's format.

### Plots for every calibration

A calibration with no figure is a calibration nobody checks. Added: the Step 4a gain
ladder against the amplifier's rating, the Step 4b re-measured lineshape, the Step 5
two-receiver overlay, the Step 6 linearity ladder, and a third Step 3 panel showing
the confirmation scan. Thirteen figures per run, every axis limit derived at run time.

### Prose cut by about a third

The markdown went from 35.8k to 27.2k characters while *adding* ~2.5k describing the
new automatic behaviour. Cut: the teaching narrative, a `fit_lorentzian` paragraph that
appeared twice, and the stale references to the coherent-leakage dead end and the
abandoned phase-width method. Kept: every warning, failure mode and physics
justification that changes what the operator would do.

### The off-board test harness, which was in `/tmp` and had been lost once

Now in `jupyter_notebooks/tests/`, and it is what found both bugs above.

| File | What it does |
|---|---|
| `fakehw.py` | A register-level mock. Patches `os.open`, `mmap.mmap` and `open`, so every line of the notebook's own driver code runs unmodified — the `Bus` class, the poison check, the DMA bounds readback, `tone_frac`'s least-squares projection. Only the silicon is fake |
| `audit.py` | Walks the code cells statement by statement and flags any name read at module level before anything binds it. Catches ordering bugs runtime testing misses, because a name left over in a live kernel looks defined when it is not |
| `run_mock.py` | Runs the whole notebook against the mock across a scenario matrix, saving every figure |

Each scenario declares whether the notebook should **finish** or **refuse**, because a
refusal is a pass when refusing is the right answer:

| Scenario | Expected |
|---|---|
| `baseline`, `high_q`, `very_narrow`, `no_amp_declared`, `big_floor`, `noisy_but_averaged` | ok |
| `amp_declared_absent`, `weak_coupling`, `too_noisy` | refuse |

`too_noisy` must refuse *and* say that raising `N_AVG` is the fix; `noisy_but_averaged`
is the same noise with the averaging raised, and proves that it is. 9 of 9 behave as
expected.

---

## 2026-08-06 — Every notebook moved to `jupyter_notebooks/`

Twenty-three notebooks were spread across `acquisition_custom/` and `phaseshift_custom/`,
mixed in with the generators, source lists and validators that the Vivado build reads
from the same folders. Split them apart:

```
jupyter_notebooks/
├── acquisition/    20 notebooks + COIL_NOTEBOOK_HANDOVER.md, STAGE9_PLAN.md,
│                   the Stage 10 atlas plot cell, and the one surviving backup
├── phaseshift/     phase_shift_control.ipynb, scope_phase_check.ipynb
└── tests/          the off-board harness above
```

**What did not move, and why.** `acquisition_custom/README.md` and `EXPLAINER.md` stayed:
they document the register map rather than any notebook, four notebooks cite that exact
path in their own text, and `build_project.tcl` reads other files from the same folder.
`gen_fir_coeffs.py`, `add_acquisition_sources.tcl` and the `validate_*.py` files are part
of the build and stayed with it.

**References updated**, and each one checked to still resolve: `build_project.tcl`'s
pre-build notebook check, `tools/run_on_board.ps1` (now searches both notebook folders by
name, so the command in `START_HERE.md` is unchanged), `tools/verify_notebooks.py`,
`tools/README.md`, `tools/backup.ps1`, `START_HERE.md`, `HANDOVER.md`, `BACKUP.md`, both
folder READMEs, and four in-notebook citations of `phaseshift_custom/scope_phase_check.ipynb`.

**One functional break, caught and fixed.** `acquisition_custom/stage0_analysis_selftest.py`
loads live functions out of the Stage 10 notebook by reading the `.ipynb` from its own
directory. It now resolves `../jupyter_notebooks/acquisition/` and raises a message naming
the new location if the file is not there. It passes: 13 checks, 0 failed.

**A false positive removed from `verify_notebooks.py`.** It reported `get_ipython` as
"used before anything defines it" in any notebook that switches its matplotlib backend
depending on whether it is under Jupyter — which is the correct way to write one. The
name is injected by the IPython kernel, so it exists at run time and in no notebook at
read time. Added to the builtin set. This predates the move; `build_project.tcl` had been
printing a spurious notebook failure on every build, and a checker that cries wolf stops
being read.

### Housekeeping

- **Notebook backups pruned from eighteen to one.** `.bak18` is kept — the version
  immediately before this session's rework. The other seventeen are gone.
- **`BITSTREAM_WORKFLOW.pdf` deleted**, being a second copy of `BITSTREAM_WORKFLOW.md`.
  The five documents and one build script that pointed at the PDF now point at the
  markdown.
- **No other duplicates exist.** A hash sweep of every file outside `.git` and the Vivado
  output directories found no byte-identical pairs.

---

## 2026-08-04 — The atlas was measuring the right thing with the wrong zero on its gain axis

Comparing the measured atlas with Herkenhoff *et al.* Fig. 9 raised two questions:
the self-oscillating region was about half the size, and it needed ~18 dB more
feedback to reach. Neither turned out to be a difference in the physics.

### The arithmetic

With `oshift = 7` the fitted loop gain was **k = 0.73 per unit A**, so onset sat
at A = 1/0.73 = **+2.73 dB**. The actuator ceiling is **+6.02 dB** (signed Q2.14,
A ≤ 1.99994), leaving only **3.3 dB** of usable range above onset. The paper has
5.5 dB above its onset. Since the oscillating region is bounded by
`k·A·cos(φ−φ_N) ≥ 1`, its phase half-width is `arccos(A_onset/A)`:

| | headroom above onset | half-width at the top | area |
|---|---|---|---|
| paper | 5.5 dB | 58° | 1.00 |
| this rig, `oshift=7` | 3.3 dB | 47° | 0.48 |

So the region was not small. **It was cut off by the ceiling.**

The resonator divides its state by 2^`oshift` before the output leaves the
module, so loop gain scales exactly as 2^−`oshift`. Walking that back:

| `oshift` | k | predicted onset |
|---|---|---|
| 7 | 0.73 | +2.73 dB |
| 6 | 1.46 | −3.29 dB |
| **5** | **2.92** | **−9.31 dB** |
| 4 | 5.84 | −15.33 dB (the paper's onset) |

The entire 18 dB is three steps of one internal scaling constant. The two gain
axes never had the same zero — one is referenced to the paper's electronics, the
other to a Q2.14 coefficient magnitude.

In the units that survive the comparison the rig was already doing well: **56×
narrowing against the paper's 25×**, and a frequency pull of 0.72 linewidths
against their ~0.7. The absolute numbers differ because Q₀ is 180 rather than
~4000, and the Hz axis differs by the same factor as the linewidth.

### What changed

**`OSHIFT = 5`**, not 4. It gives a paper-like picture while leaving 15 dB of
actuator margin above onset instead of 21 — and the margin matters, because
lowering `oshift` makes the resonator's output larger and **the output saturator
in `red_pitaya_resonator.v` has no status flag**. Only the *state* overflow sets
`clipped`. Clip the output and nothing says so: the loop gain quietly compresses
and onset drifts upward, which reads as a wrong measurement rather than a fault.
Two existing checks catch it and both must be believed — the open-loop assert
(Q_OL within 10% of `reso.q_q`) and `Q_LIN` in Step 1.

**The gain axis is reframed around onset**, −24.0 to −2.5 dB, coarse at 2 dB
below −14 and fine at 0.5 dB through onset. 29 rows, 696 points, about 12
minutes. Deliberately wider on the low side than the prediction needs, because
the prediction extrapolates a k fitted at `oshift = 7`.

**A bracket guard in Step 0** prints the predicted onset and warns if it falls
outside the axis — before the 12 minutes, not after. A scan that misses the
boundary produces an atlas with no boundary in it, and every stability margin
printed from it is then empty.

**The gain cuts follow the measured onset** (`onset+0.5`, `−2.5`, `−5.5`) instead
of fixed dB values, so they stay useful when `OSHIFT` changes rather than sliding
off the interesting part of the map, or off the grid.

**Two bugs fixed on the way.** `shift_f0()` hard-coded `oshift=7` independently of
`config()`, so retuning the coil mid-scan silently reset the shift and moved the
whole gain axis. And the first attempt made `config()` read a module-level
`OSHIFT` defined two cells later — `verify_notebooks.py` refused it, correctly. It
is a class attribute now, defined before anything can call it and set from the
CONFIG cell.

### Figure formatting

The Δν colourbar was unreadable: the shift runs to ±160 000 Hz, and nine ticks of
six digits collided with each other, with the panel letter and with the title.
Fixed by scaling the data rather than shrinking the text — an automatic Hz/kHz/MHz
choice, `MaxNLocator(5)` on the linear bar and `LogLocator(numticks=4)` on the log
one, a wider gutter between columns, and the panel letters moved clear.

### Caveat

`OSHIFT = 5` changes the plant's output level by 12 dB relative to Stages 8, 9
and 11, which still use 7. Any feedback setting carried between notebooks needs
rescaling by the same 12 dB or re-deriving. Noted in the cell.

---

## 2026-08-04 — Stage 15 searched 20 MHz for a resonator that was switched off

Steps 1, 2 and 3 all failed, and Step 4 then measured the same resonator to 0.3%
at Q = 300 and Q = 1000. Both facts are correct, and together they name the fault.

### Fault 1 — the plant was never enabled

Step 4 configures and **enables** the digital resonator before measuring it:

```python
reso.config(F0, q_true)
reso.noise_tank(TANK_SH); reso.noise_out(None)
reso.enable(); reso.clear()
```

Steps 1 to 3 did not, and nothing else in the notebook does either. In emulation
there is no coil on the bench — the thing to be found *is* the digital resonator,
and the top level only substitutes it for the converter when `reso_ena` is set:

```systemverilog
assign adc_dat_ps[0] = reso_ena ? reso_dat : adc_dat[0];
```

So the search swept 30–50 MHz across a terminated input, 2501 points of it. The
answers were all correct answers to the question actually being asked:

| reported | what it means |
|---|---|
| *"strongest point 0.9 dB above the median"* | the noise floor is flat |
| bracket edges 0.21/0.70, 0.05/1.00, 0.63/0.41 … | random, because there is no peak to bracket |
| *"the line is wider than the search band"* | after 10 doublings, still no line |

The line also has to be **driven**. A resonator with no drive has nothing to
resonate: it is found as a bump in the noise, which is what `noise_sweep()`
downstream measures. So the tank noise has to be on before the search starts, not
only during the Step 4 self-check.

**This is the third instance of this exact fault** — Stage 13 Step 3 was the same
shape two entries ago. A measurement step that assumes a signal source nothing in
the notebook ever turns on.

Fixed: Step 1 now sets the plant up first, gated on `EMULATION`, and prints what it
enabled. With `EMULATION = False` it explicitly disables the resonator instead,
because then the plant really is out on the bench.

### Fault 2 — `capture()` raced the memory writer

The `RuntimeError: unwritten words in the record` is not a transport fault. The
record was read a few hundred microseconds early.

```python
time.sleep(n_samples * (1 << dec_log2) / FS_CLK + 0.005)
acq.w(0x00, 1)                    # disarm
...
got = min(int(acq.r(0x34)), n_samples)
```

Two things wrong, and they compound:

1. **`DMA_COUNT` was not consulted until after the decision to stop had been
   made.** The sleep was a guess with no verification attached to it.
2. **`DMA_COUNT` reports samples handed *to* the memory writer, not samples that
   have landed in DDR.** The writer bursts, so the final burst can still be in
   flight when the count already reads complete.

A fixed 5 ms of margin is also the wrong shape: 30% of a short record, 0.1% of a
long one. That is why this appeared as a rare, load-dependent failure that looked
like hardware — it surfaced here only because Stage 15 fires 2501 short captures
back to back, which is the worst case for it.

Now polls `DMA_COUNT` to completion with a 0.5 s deadline, lets the last burst
land, and — if poison is still found — **retries the read once** before raising. A
word inside the writer's burst buffer is not a lost word; if it is genuinely lost
it will still be poison in 20 ms. The single-shot check could not tell those apart
and reported a transport fault for both.

Verified against a simulated late burst:

| scenario | old | new |
|---|---|---|
| burst 0.5 ms late (the observed race) | RuntimeError | ok |
| burst 10 ms late | RuntimeError | ok |
| genuinely lost | RuntimeError | RuntimeError |

`capture()` was **byte-identical across ten notebooks** (Stages 9 through 17), so
the race was in all of them and the fix is applied to all ten.

### Noted, not changed

`STATUS2` bit 0 — *memory overflow, SAMPLES WERE LOST* — is still not checked;
`capture()` only tests bit 3, the write-error flag. A capture can therefore lose
samples silently. Left alone deliberately: it needs a board to confirm the bit is
not sticky across arm cycles, and a false positive here would block every stage.
Worth doing with hardware to hand.

---

## 2026-08-04 — The atlas gain axis was already at the actuator ceiling

Asked to widen the sweep so more of the self-oscillating region appears. It cannot
be widened, and it is worth writing down why.

### The ceiling

The phase shifter's coefficients are signed **Q2.14** (`DWC = 16`,
`red_pitaya_phaseshift.v`), so the largest representable A is **1.99994 = +6.02 dB**.
`GAINS_DB` already ended at +6.00 dB. Stage 10's own Step 5 knew this —
`A_MAX = 1.99  # A*16384 = 32604, just inside int16` — but two other messages in
the same notebook advised *"Raise the top of GAINS_DB and rerun"* and *"Extend
GAINS_DB upward before operating anywhere"*, which is advice that cannot be
followed. Both corrected to say what to change instead: plant Q, resonator output
shift, or the coefficient format in RTL.

### What was actually wrong with the picture

Onset is near A = 1.4 (+3 dB) and the ceiling is +6 dB, so the unstable band is
about **3 dB wide** — bounded by physics, not by the axis. At the old uniform 2 dB
step that is **two rows**, which is why it drew as a sliver rather than a region.

So the band is not being enlarged. It is being **resolved**, by spending the sample
budget where the behaviour changes:

| range | step | reason |
|---|---|---|
| −26 to 0 dB | 2.0 dB | far from onset, nothing moves quickly |
| 0 to +6 dB | 0.5 dB | through onset and up to the ceiling |

**7 rows inside the unstable band instead of 2.** 26 × 24 = 624 points, about 10
minutes against the previous 7.

### The trap that came with it

A non-uniform axis breaks `imshow`, which the heatmaps used with
`extent=[...]` — that assumes evenly spaced rows. It would have drawn the 0.5 dB
rows stretched to the same height as the 2 dB ones, silently, producing a
completely wrong map that looked entirely reasonable. Switched to `pcolormesh`
with explicit cell edges (`_edges()`), which handles uneven spacing correctly.

Verified by rendering the new axis with synthetic data
(`results/axis_rendering_check_SYNTHETIC.png`): the fine rows above 0 dB draw at
their true spacing and the oscillating lobe resolves into a shape rather than a
line. Synthetic — it checks the axis arithmetic, not the physics.

### The atlas now draws in the paper's format

Laid out as Herkenhoff *et al.* Fig. 9: two columns, `Q` left and `Δν_res` right.
Each is a heatmap over (feedback phase, feedback gain) with a **horizontal
colourbar above it**, and beneath it a panel of line cuts at three gains, drawn in
the same colours as the dashed lines marking those gains on the map. The phase axis
is shared and labelled once, at the bottom, in degrees from −180° to 180°.

Three deliberate departures, all recorded in the cell:

- **Phase is drawn relative to `PHI_N`.** The paper puts the narrowing phase at 0°;
  on this board that phase is `PHI_N`, so the axis is referred to it. Set
  `PHASE_REF = 0.0` for raw phase.
- **The gain axis runs to +6 dB, not −10 dB.** That is this board's actuator
  ceiling, not a choice.
- **White rings are kept**, marking points too loud to be a linear measurement. The
  paper has no equivalent. Dropping a validity warning to match someone else's
  figure would be a poor trade — especially in a session that has spent this much
  time on tests that looked fine and were not.

`T_eff/T0` is not in the paper, so it keeps its own panel rather than being forced
into a layout designed for two quantities.

### Two bugs caught while building it, both by checks rather than by eye

**A forward reference.** `PHASE_REF = PHI_N` looked right and would have crashed
the notebook on a clean top-to-bottom run: `PHI_N` is not assigned until code cell
8, and this is code cell 5. `verify_notebooks.py` reported *"cell 4: 'PHI_N' is
used before anything defines it"* — the same class of fault as the `logic`
declarations in `red_pitaya_top.sv` earlier this week, and caught the same way.
The narrowing phase is now derived from the atlas that has just been measured, so
it cannot go stale or run early.

**A biased derivation.** The first derivation took a median down each phase column
and picked the largest. Tested against synthetic data with a known narrowing phase
of 210°, it returned **165°**. The reason is worth keeping: the columns nearest the
narrowing phase are the ones that oscillate first, so they hold the most missing
entries, and their median is computed over fewer and lower-gain samples — biasing
the answer *away* from the very phase being looked for. Reading the peak off the
highest fully stable gain row has no such bias and returns 210°.

That one would have produced a figure that looked entirely reasonable, with the
phase axis silently offset by 45°.

### One rendering trap

Phase is periodic, so the column at −180° is also the column at +180°. Without
repeating it the map stops at the last sampled point — +165° at 15° steps — and the
unfilled strip beyond draws as **a black stripe up the right-hand edge**, which
reads as a band of self-oscillation that is not there. `_phase_axis()` closes the
axis explicitly. It was caught by looking at the render, not by any check.

`set_title(..., pad=)` is matplotlib ≥ 2.0; the board may be older, and this
notebook already carries shims for that era. The colourbar label with its axis
moved to the top gives identical placement on every version, so that is what is
used.

Verified by executing the notebook's own cell against synthetic arrays of the right
shape — it runs clean and produces both figures
(`results/paper_format_check_SYNTHETIC.png`). Synthetic: it checks the layout and
the axis arithmetic, not the physics.

---

## 2026-08-03 — Stage 13 Step 1: it told us to turn down the gain on a terminated input

```
source: bench: input terminated
  rms                     1.2337e+04 counts
  largest sample          3.9836e+04 counts
  headroom to full scale  -13.7 dB
  samples near full scale 5268 of 8192
  peak/average            3.23   (pure noise gives about 3.00)
  TOO LOUD - reduce the gain ahead of the converter before measuring.
```

Nothing was connected to the input. There was no gain to reduce.

### The record contradicted itself, and that is what gave it away

Two numbers from the *same* 8192 samples:

- **5268 of 8192 samples near full scale** — 64% of the record pinned at the rail
- **peak/average 3.23**, against the 3.00 expected of pure noise

Both cannot be true. A signal with 64% of its samples at full scale has a crest
factor of about 1. A crest factor of 3.23 is healthy, unclipped noise, sitting a
touch above the textbook figure. The clipping metric was wrong; the linearity
metric beside it was fine and was quietly saying so.

### The fault: a full-scale reference from the wrong end of the chain

```python
FULL_SCALE = float(1 << 13)      # 14-bit signed converter
```

That is the **converter's** full scale. But `capture()` reads the **CIC output**,
which is roughly 96 dB further up the chain. The threshold for "near full scale"
came out at 8028 — *below* the record's own rms of 12337 — so most samples tripped
it, and the headroom figure was the ratio of two quantities in different units.

The correct value follows from the RTL headers, which state every step:

| stage | peak | source |
|---|---|---|
| ADC full-scale sine | 2²³ → `2^13` | 14-bit signed |
| local oscillator | `2^15` | `DWL = 16` |
| raw product | `2^28` | |
| mixer, `>> SHIFT = 6` | `2^22` | `red_pitaya_acq_mixer.v` |
| baseband term after the CIC drops the sum term | `2^21` | `cos·cos = ½cos(Δ) + ½cos(Σ)` |
| CIC output — input scale plus 8 bits | **`2^29`** | `red_pitaya_acq_cic.v` |

So `|z|` for a full-scale sine at the converter is **2²⁹**, and it does not move
with decimation — the CIC's output slice tracks R exactly so the scale stays put,
which is the whole reason R is restricted to powers of two.

Checked against the reported numbers: the old reference gives −13.7 dB and 5268
samples, reproducing the failure exactly. The corrected one gives **+82.6 dB of
headroom and 0 samples near full scale** — which is what a terminated input should
look like, and Step 1 passes.

### FIX 13

`FULL_SCALE = float(1 << 29)`, with the derivation written out beside it, and
`ADC_FULL_SCALE` kept separately for when the converter itself is meant. Noted
there: the FIR droop corrector downstream has a DC gain of 1.02 to 1.3, so the true
clip point is up to 2.3 dB below this — comfortably inside the 6 dB
`MIN_HEADROOM_DB` already required.

Step 3's loopback tone was checked against the corrected reference at the same
time: `amp 0.15` gives `|z| = 8.05e7`, **16.5 dB below full scale**. No clipping.

### Two failures, one habit

Both Stage 13 failures this session were the test misjudging a healthy instrument,
and in both the test asserted a diagnosis it had not earned — *"reduce the gain
ahead of the converter"*, *"a scaling error in exactly one of them"*. Neither was
true. A measurement compared against a constant is only as good as the constant,
and a units error between two ends of a signal chain looks exactly like a fault at
whichever end you were already suspicious of.

---

## 2026-08-03 — Stage 13 Step 3: the paths did not disagree. There was nothing for them to agree about

```
memory capture             1.2417e+04     1.000
register voltmeter         1.7146e+03     0.138
averaged spectrum          1.2556e+04     1.011
largest ratio between any two paths: 7.323
```

Read as "one path has a scaling error", which is what the step's own message
says. It was not a scaling error. Two separate faults, neither in the instrument.

### Fault 1 — the tone never reached the converter

The top level builds the converter word like this:

```systemverilog
assign adc_dat[0]    = digital_loop ? dac_a    : <the real converter>;
assign adc_dat_ps[0] = reso_ena     ? reso_dat : adc_dat[0];
```

and the acquisition taps `adc_dat_ps`. Step 3 started the generator and tuned the
acquisition — but with `SOURCE_NOTE = 'bench: input terminated'`, `digital_loop`
off, and the resonator never enabled anywhere in the notebook, **there was no path
from the generator to the acquisition at all.** The tone existed; it had nowhere to
go. All three paths measured the noise floor of a terminated input.

In emulation the resonator is the only other way in — the top level feeds it
`dac_a` and substitutes its output for the ADC — which is how Stages 8 to 11 got
signal. Stage 13 does not enable it. Nothing in the notebook ever did.

### Fault 2 — the three paths were two paths, measuring different things

The register voltmeter returns `|mean(z)|`: a **coherent** average, which cancels
everything not at the tuned frequency. The other two returned
`sqrt(mean(|z|²))`: **total power**, which cancels nothing. On a clean on-tune tone
these agree. On noise they differ by the square root of the number of samples
averaged — which is precisely what was seen.

Simulating pure noise through the actual read timing (software-paced register
reads at roughly 1.3 µs a pair, against a CIC output that updates every 8.192 µs at
`DEC_CHK = 10`, so consecutive reads repeat the same sample) predicts a ratio of
**0.124 to 0.156**. Observed: **0.138**. The number was not evidence of a fault; it
was the correct answer to "what happens if you coherently average noise".

And the third path was never independent. By Parseval the spectrum figure *is* the
record's mean square computed a second way, from the same 8192 samples. It agreed
with the capture to 1.1% because it could hardly do otherwise. Two paths were being
presented as three, and the one genuinely independent comparison — registers
against memory — was being made between incompatible estimators.

### FIX 12 — give it a signal, and compare like with like

Step 3 now enables the internal loopback (house keeping 0x0C bit 0) for the
duration of the test and restores it afterwards. That is the right source for a
scaling cross-check: unity gain, no cable, no resonance, no analogue, nothing to
calibrate.

The comparison is now between matched estimators:

| pair | quantity | what it actually tests |
|---|---|---|
| register voltmeter vs memory capture | coherent `\|mean z\|` | the peek registers against the memory writer — the one comparison that was wanted |
| memory capture vs averaged spectrum | power `sqrt(mean\|z\|²)` | the spectrum normalisation, from one record |

It also reports the **tone fraction** `|mean z| / rms(z)`. Near 1 means a clean
tone; near 0 means there is nothing there, and the step now says *"NO TONE ... the
paths below are being asked to agree about something that is not there"* instead of
blaming a scaling error.

### The lesson

The failure message asserted its own diagnosis — *"That is a scaling error in
exactly one of them, and the ratios above say which"* — and it was wrong on both
counts. There was no scaling error, and the ratios pointed at the path that was
behaving correctly. A test that names the fault it has found is only as good as the
assumption behind the naming; when that assumption fails, a confident wrong answer
is worse than a bare number.

---

## 2026-08-03 — Stage 11 Steps 1 and 2 fail: every parameter set was written one slot too high

With the sequencer finally on the board, Steps 0 and 3 passed and Steps 1 and 2
failed. One line of RTL explains both.

### The fault

```systemverilog
wire [SW-1:0] a_set = sys_addr[SW+3:4];     // bits [6:4]
```

Bits [6:4] of an address are *address ÷ 16*. But the sets **start at 0x10**, not
at 0. So the decode never subtracted the base:

| software asks for | address | decoded as |
|---|---|---|
| set 0 | 0x10 | set 1 |
| set 1 | 0x20 | set 2 |
| … | … | … |
| set 6 | 0x70 | set 7 |
| set 7 | 0x80 | **set 0** |

Every set landed one slot high, and the top one wrapped onto the bottom one. All
eight were wrong.

### Why that produced these two symptoms and not others

The state machine starts at set 0 and reads `mem_dur[0]` — which software had
never actually written, so it was still zero from reset. **A duration of zero
means "wait for a trigger."** With no trigger enabled, the sequence sat at set 0
for ever.

- **Step 2** saw that directly: `set 0, running True, done False` at 200 ms and
  again at 400 ms. It was waiting for a trigger nobody had asked for.
- **Step 1** saw the consequence. The coefficients never left `mem_ci[0]` and
  `mem_cq[0]`, both zero, so nothing ever switched. Its FFT went looking for the
  strongest line in the envelope of a noise-driven resonator and found noise —
  hence 112.8 µs, 70.2 µs, 186.0 µs, 91.4 µs, four numbers with no relation to
  what was programmed or to each other. That scatter was the tell: a wrong
  divisor gives a wrong answer, but a *consistent* one.
- **Step 0 passed**, and could not have failed — see below.
- **Step 3 passed** because it does not depend on which slot a set lands in.

### FIX 11 — subtract the base before decoding

```systemverilog
localparam [19:0] SET_BASE = 20'h10;
wire [19:0]   a_off = sys_addr[19:0] - SET_BASE;
wire [SW-1:0] a_set = a_off[SW+3:4];
```

`a_word` is unchanged and was always correct: 0x10 is a multiple of 16, so the low
bits are unaffected by the offset.

Modelled against the notebook's exact register writes: Step 2a now waits at set 1
as intended, and Step 1's four periods come out at 200.008, 500.016, 1000.016 and
2000.016 µs — errors of 0.004% and below, against a 2% tolerance. The residual two
clocks per cycle are the state machine's load-and-compare overhead, as designed.

### The part worth keeping: why Step 0 could never have caught this

Step 0 writes set 3, reads set 3 back, and checks the values match. It passed
throughout. It would pass no matter how badly the index were decoded, **because
reads use the same decode as writes** — both went to slot 4 and agreed with each
other. The bus was perfectly self-consistent. It had simply relabelled every set.

A read-back test cannot see an error applied identically in both directions. It
proves the memory holds what it was given; it says nothing about whether it was
given the right address.

My first attempt at hardening this was to write a different value to all eight
sets and check for aliasing. Simulated against both decodes, **it passed on the
broken one too** — for exactly the same reason. A relabelling is invisible to any
test that only ever goes through the relabelling.

What breaks the symmetry is the state machine: it reads `mem[cur]` by index and
never touches the bus decode. So Step 0 now **runs a two-set sequence and checks
where it stops** — programmed under software control so it disturbs nothing.
Verified against both decodes:

| decode | result | verdict |
|---|---|---|
| old (buggy) | `set 0, running, not done` | **FAILS** |
| new (fixed) | `set 1, stopped, done` | passes |

The general lesson, and the one that cost the most here: a test that exercises a
translation in both directions cannot detect a fault in that translation. Somewhere
in the loop there has to be a party that did not read the same map.

---

## 2026-08-03 — The zero was a STUB answering. The board was never running the new bitstream

Stage 11 Step 0 read `0x00000000` from slot 7 again, after a rebuild, with Stages 8
and 9 passing and `check_system.py` reporting no issues. Every one of those
reassurances was empty, and the previous entry's explanation was wrong.

### Correcting the previous entry

The entry below blamed the timing failure for the zero reads. **That was wrong.**
Stages 8 and 9 pass on this board, which they could not do if the fabric were
mis-latching. The timing failure is real, is still there, and still has to be
fixed — but it was not what Step 0 was reporting. Diagnosing two faults as one is
how the second one hides.

### What was actually happening

An unused bus slot is filled by `sys_bus_stub`, which is three lines:

```systemverilog
assign bus.ack   = 1'b1;
assign bus.err   = 1'b1;
assign bus.rdata = 'x;      // synthesises to constant zero
```

It **acknowledges the read and returns zero, instantly and without error.** From
software, a stubbed slot and a module whose version register reads zero are
indistinguishable. Before the sequencer existed, slot 7 held exactly this stub.

So `0x00000000` from slot 7 was not a broken sequencer, or a timing casualty. It
was the *old bitstream's stub*, answering correctly. The board was still running a
build from before the sequencer was added — and Stages 8 and 9 passed on it because
neither touches slot 7.

### Why nothing caught it — four silent failures in a row

| # | What happened | Why it was silent |
|---|---|---|
| 1 | `bitstream_id.txt` was never written | The build did not run through `build_project.tcl` to STEP 4. Vivado's GUI *Generate Bitstream* does not write it |
| 2 | `run_on_board.ps1` did not copy it | Line 159 guards with `Test-Path` and skips missing files without a word |
| 3 | `check_system.py` found no file to compare against | `expected` stayed `None`, the comparison was skipped, and control fell through to **"OK, build fingerprint 0x…"** |
| 4 | Stages 8 and 9 passed | Neither reads slot 7 |

Step 3 is the one that did the damage. The script announced success for a check it
had not performed. **"I could not check" and "I checked and it is fine" must never
look the same** — and here they were the same sentence.

That is the second time this file has been the problem: the entry below records
that its fingerprint comparison had never once worked, because it compared the
whole file, comments included, against an 8-character hex string. Fixing that
exposed this deeper hole underneath it.

### FIX 7 — `check_system.py` cannot report OK for a check it did not run

When `bitstream_id.txt` is absent it now says so, in plain terms: the bitstream
could not be verified, this is not an all-clear, here is what to copy across and
why the file may not exist.

### FIX 8 — ask the modules directly, instead of asking a file about them

A fingerprint answers "does the chip match a file on the PC" — useless when the
file is missing, and silent about *which modules the design contains*.
`check_system.py` now reads each custom module's version register and reports it by
name. For the sequencer: slot 7 offset 0x0C must return `0x5E900001`.

A version register is the only honest presence test, because a stub cannot fake
one. Had this existed, the very first run would have said *"The parameter sequencer
is NOT in this bitstream — the slot is still a stub, so this build predates the
module"*, instead of "OK".

### FIX 9 — the fingerprint file is written the moment a bitstream exists

`build_project.tcl` wrote it only in STEP 4, so when STEP 4 did not complete the
file did not exist at all — and its absence was read downstream as consent. It is
now written immediately after implementation, stamped `timing: NOT YET CHECKED`,
and rewritten in STEP 4 with the real verdict. A file that exists and says
"unverified" is worth far more than a missing one.

### FIX 10 — the root cause of all four: one Tcl option that does not exist

Found when the Tcl console finally showed it:

```
ERROR: [Common 17-170] Unknown option '-slack_lessthan',
       please type 'get_timing_paths -help' for usage info.
```

`build_project.tcl` STEP 4 counted failing endpoints with
`get_timing_paths ... -slack_lessthan 0`. **There is no such option.** An ERROR in
a sourced Tcl script aborts it — so STEP 4 has never once run to completion on this
project.

That single wrong word is the origin of everything above:

- no timing verdict was ever printed, which is why a design failing by 7 ns went
  unnoticed through Stages 8, 9 and 10
- STEP 5 never ran, so its "NEXT STEPS" and the fix that made it refuse a bad
  build were both unreachable
- once the fingerprint write was moved into STEP 4, `bitstream_id.txt` stopped
  being written — which is what let a stale bitstream sit on the board while
  `check_system.py` reported no issues

The build still produced a working bitstream every time, which is exactly what made
it invisible: the part that succeeded was loud, and the part that died was silent.

Replaced with options that exist in every Vivado version — fetch the worst paths
and count the negative ones in Tcl. The whole measurement is now wrapped in
`catch`, and a build whose timing **cannot** be measured is treated as failing, not
passing. An unchecked build and a good build must not look the same.

### What to do now

1. Rebuild with `source C:/rp/prj/v0.94/Test_Project/build_project.tcl` — **not**
   the GUI button, which writes no fingerprint. This will print a real timing
   verdict for the first time.
2. Load it following `BITSTREAM_WORKFLOW.pdf` Workflow A. The `md5sum` in step A4
   is the step that proves the file arrived; it is not optional here.
3. Run `sudo python3 check_system.py`. It must now say *"The parameter sequencer is
   present (version 0x5E900001)"*. Anything else, including any "could not be
   verified" warning, means stop.

### Still outstanding, and not to be confused with the above

The build still misses timing: **WNS −7.141 ns, 6845 failing endpoints**, all in
the resonator's recursive loop. FIX 4's saturation change did not move it
materially. Stages 8 and 9 passing is *not* evidence against this — a design that
misses timing can pass tests for a long time and then produce a wrong number on a
warm afternoon. That work is unfinished.

---

## 2026-08-03 — Stage 11 Step 1 reads zero. The sequencer is present; the build fails timing by 6.8 ns

Step 1 stopped with `sequencer version register: 0x00000000` and *"THIS BITSTREAM HAS
NO SEQUENCER"*. The message names the wrong culprit. The sequencer is in the
bitstream. The bitstream is broken.

### The sequencer is there — proved twice

| Evidence | What it shows |
|---|---|
| `synth_1/runme.log:292` | `synthesizing module 'red_pitaya_sequencer'`, with `VERSION bound to: 1586495489` — that is 0x5E900001, the value Step 1 was looking for |
| `synth_1/red_pitaya_top.tcl:122` | the file is in the list Vivado actually compiles |
| `impl_1/..._timing_summary_routed.rpt` | real placed-and-routed cells: `i_seq/mem_dur_reg[1][30]` at `SLICE_X0Y53` |

So the previous two fixes worked. The module was synthesised, placed and routed.

### What is actually wrong

```
CRITICAL WARNING: [Timing 38-282] The design failed to meet the timing requirements.

WNS  -6.799 ns      TNS  -6536.272 ns      Failing endpoints  6224 of 29573
```

**The build misses timing by 6.799 ns on an 8 ns clock** — the slowest path needs
14.7 ns, nearly two clock periods.

> **Superseded — see the entry above (2026-08-03, "The zero was a STUB").** The
> paragraph that followed here argued that the timing failure explained the zero
> reads. It did not. The zero was an old bitstream's `sys_bus_stub` answering
> slot 7, and Stages 8 and 9 pass on this board, which rules out mis-latching
> fabric. The timing failure below is real and still unfixed; it was simply not
> the fault being reported. Two faults, diagnosed as one.

Every one of the ten worst paths is inside `i_reso` — the digital resonator.

### The critical path, and why it is that long

`i_reso/v_reg[17]` → DSP48E1 → LUT1 → **18 CARRY4 levels** → LUT4 → `i_reso/u_reg[15]`

| Stage | Delay |
|---|---|
| Unregistered DSP multiply (`Prop_dsp48e1_A[17]_P[1]`) | 3.841 ns |
| Two carry chains in series — the adder, then the saturation comparison | ~8.6 ns |
| Routing | 4.314 ns |
| **Total data path** | **14.695 ns** |

The resonator is recursive: the whole multiply-add must close in one clock and
cannot be pipelined. `red_pitaya_resonator.v`'s own header says so, and warns
"IF YOU WIDEN THESE, CHECK THE TIMING REPORT — do not assume."

**That check was never done.** The 2026-07-30 entry that added the resonator ends
"*Not yet built. Needs one rebuild, and the timing report needs checking — the
resonator's recursive loop is the one path where that is not a formality.*" The
last clean timing recorded anywhere in this log is **+0.248 ns over 27338
endpoints, on 2026-07-29** — before the resonator existed. Every measurement taken
through the resonator since, Stage 8 and Stage 10 included, was taken through a
design whose timing had never been verified.

### FIX 4 — saturation from two bits instead of two comparisons

Applied, and it is **bit-for-bit behaviour-preserving**: same values into `u` and
`v`, same clip flag, no change to coefficient scaling, physics or software.

The old form asked `u_nxt > SAT_HI` and `u_nxt < SAT_LO`. Each is a 26-bit
magnitude comparison, which Vivado builds as a carry chain — placed *after* the
adder's own carry chain, both inside the recursion.

But `SAT_HI` and `SAT_LO` are exactly the largest and smallest values 25 bits can
hold, so "does it fit" is precisely "are the top two bits equal" — one XOR:

| `u_nxt[25]` | `u_nxt[24]` | meaning |
|---|---|---|
| 0 | 0 | fits, positive |
| 0 | 1 | overflowed positive → `SAT_HI` |
| 1 | 0 | overflowed negative → `SAT_LO` |
| 1 | 1 | fits, negative |

Verified by exhaustive comparison of both forms across the entire signed range at
reduced widths, and boundaries plus 400,000 random values at the real width: zero
mismatches.

**This is necessary but not sufficient.** It removes one of the two carry chains,
perhaps 3–4 ns. The unregistered DSP multiply alone is 3.8 ns, and routing another
4.3 ns. Closing the remaining gap means changing widths or restructuring the
recursion — decisions that change the emulated plant's calibration, so they are
not being made unilaterally here.

### FIX 5 — the build script told us to load a bitstream it had just condemned

This is the process failure, and it is the one that cost the afternoon.

`build_project.tcl` STEP 4 detected the timing failure correctly and printed
*"Do not trust measurements from this build."* Then STEP 5 printed:

```
  NEXT STEPS
    1. Copy it to the board...
```

The FAIL scrolled past; the confident instruction was at the bottom, where the eye
lands. Fixed: when timing fails, STEP 5 now leads with **DO NOT LOAD THIS
BITSTREAM**, explains that the symptom is *not* a clean failure — "registers
reading zero, or values that change when nothing changed, or numbers that look
plausible and are wrong" — and points at the resonator note. The verdict is now the
last thing on screen.

`bitstream_id.txt` was also being written in STEP 3, *before* timing was checked,
so a condemned build still got a clean-looking identity. It is now written after
the verdict and records it.

### FIX 6 — the stale-bitstream check has never once worked

Found while wiring up the above. `check_system.py` read the fingerprint file with:

```python
expected = open(cand).read().strip().upper().replace('0X', '')
```

`.read()` takes the **whole file** — the fingerprint *and* every `#` comment line
under it — then compares that to an 8-character hex string. It can never match.

This is the project's main defence against a stale bitstream, the thing built
after the 2026-07-29 afternoon was lost to exactly that fault, and it has been
reporting "the chip is running DIFFERENT logic from your source" on every run,
including builds that were perfectly current. A check that always cries wolf is
worse than none: it teaches you to scroll past the one message that would have
caught the real thing.

Now reads the first non-comment line, and additionally reports **PROBLEM** when the
fingerprint matches but the build failed timing — because a matching fingerprint
proves the board runs what was built, not that what was built works.

### Where this leaves Stage 11

The sequencer is correct and is in the design. Nothing in Step 1's output is
evidence against it. But no measurement from this bitstream means anything, and
that includes the Stage 10 atlas if it was taken through the resonator on a build
that had never had its timing checked — which, on the evidence above, it was.

---

## 2026-08-03 — Second pass: the same ten errors, because a hand-edited .xpr does not survive Vivado

The identical failure came back, with one telling difference — the line numbers had
moved, from 333/342 to 612/621. That is the signature of a half-applied fix: the
`red_pitaya_top.sv` change (FIX 2 below) had taken, because a text file edited on
disk is a text file Vivado re-reads. The project-file change (FIX 1 below) had not.

### Why the first repair evaporated

`Test_Project.xpr` was edited directly while Vivado had the project open. Vivado does
not re-read that file — it holds the source list in memory and writes it back on
save. Timestamps confirm it: the edit went in, Vivado saved over it minutes later,
and the entry was gone. The generated synthesis script
`Test_Project.runs/synth_1/red_pitaya_top.tcl` listed every custom module except the
sequencer, which is the list Vivado actually compiles from.

This is the same failure mode already recorded on 2026-07-29, when a source file was
edited behind an open Vivado and the build silently used the previous day's netlist.
Same lesson, different file: **while Vivado is open, it owns the project file.**

### FIX 1 (properly, this time) — the sequencer added where the fix is permanent

`acquisition_custom/add_acquisition_sources.tcl` is the script `build_project.tcl`
runs as STEP 2, and it is the project's real source-of-truth for "which custom files
must be in Vivado". `red_pitaya_sequencer.v` was missing from its `acq_files` list —
that is the actual defect, and the hand-edited `.xpr` was only ever a symptom patch.

Added there. It is version-controlled, it re-applies itself on every build, and it
survives the project being deleted and recreated, which a hand-edited `.xpr` does not.

### FIX 3 — a check so this cannot reach synthesis again

The same script now scans `red_pitaya_top.sv` for every module it instantiates and
confirms each one is genuinely declared in a file the project contains. If one is
not, it prints the name, says whether the file exists on disk, names the list to add
it to, and **aborts** — before the 15-to-25-minute build rather than after it.

Nothing already in the project could have caught this:

| Check | What it reads | Why it missed this |
|---|---|---|
| Build fingerprint | files on disk | hashed the sequencer, so the build ID *changed* — it looked included |
| `tools/verify_rtl.py` | the source tree | ports and names all matched, because the file was there |
| **New check** | **the Vivado project** | **asks whether Vivado knows about the file** |

The first two answer "does the file exist". The question that mattered was "does the
toolchain read it".

Two details found while testing it, both fixed:

- Matching module and instance names with `\s*` between them let the pattern split
  `if (` into a module `i` and an instance `f`, then report a missing module called
  `i`. The separator must be `\s+`.
- Checking module names against *filenames* is guesswork — several files here hold
  more than one module. It now reads each project file and looks for the actual
  `module` / `interface` declaration.

Verified both ways: with the sequencer in the project it reports
`all 13 instantiated module(s) found`; with it removed it aborts with the correct
diagnosis and a non-zero error.

### To apply it

In the Vivado Tcl Console, with the project open:

```
source C:/rp/prj/v0.94/Test_Project/build_project.tcl
```

That runs the corrected STEP 2, so the sequencer is added, the new check runs, and
the build proceeds. To add the file without a full rebuild:

```
source C:/rp/prj/v0.94/Test_Project/acquisition_custom/add_acquisition_sources.tcl
reset_run synth_1
launch_runs synth_1 -jobs 4
```

`reset_run` matters — synth_1 is still holding its failed state.

---

## 2026-08-03 — Stage 11 synthesis failure: the module was written but never added to the project

The sequencer build failed at synthesis with ten errors. All ten came from two
causes, and neither was in the sequencer's logic — the module itself is sound.

### What Vivado reported

```
[Synth 8-439]  module 'red_pitaya_sequencer' not found        red_pitaya_top.sv:333
[Synth 8-6038] cannot resolve hierarchical name for 'addr'    red_pitaya_top.sv:342  (+6 more)
[Synth 8-6156] failed synthesizing module 'red_pitaya_top'    red_pitaya_top.sv:52
[Common 17-69] Command failed: Synthesis failed
[Common 17-69] Command failed: Run 'impl_1' has not been launched
```

Only the first is a real fault. The seven `8-6038` errors are the seven `sys[7].*`
connections on an instance whose module could not be found: with no port list to
match against, Vivado cannot resolve `.addr` on the interface and complains once per
port. `8-6156` is the top-level giving up, and the `impl_1` message is implementation
refusing to start after synthesis never produced a netlist. Fix the first error and
the other nine go with it — which is why the count is misleading and the line numbers
are worth reading before the totals.

### FIX 1 — `red_pitaya_sequencer.v` was never added to the Vivado project

The file was written, committed, and added to `build_project.tcl`'s fingerprint list,
so every check that reads the *repository* said it was present. But `Test_Project.xpr`
— the list Vivado actually synthesises from — never gained an entry for it. Writing a
file into `rtl/classic/` does not put it in the project; Vivado only compiles what its
own source set names. `red_pitaya_resonator.v` and the six `red_pitaya_acq*.v` files
each had an entry; this one did not.

Added to the `sources_1` fileset in `Test_Project.xpr`, marked `UsedIn` synthesis,
implementation and simulation, alongside the other custom modules.

> **This fix did not hold — see the entry above for 2026-08-03 (second pass).**
> Editing `Test_Project.xpr` by hand while Vivado has the project open achieves
> nothing: Vivado holds the source list in memory and writes it back over the file.
> The correct place is `add_acquisition_sources.tcl`. The diagnosis below is right;
> the repair was applied in the wrong place.

> Worth noting for next time: the fingerprint in `build_project.tcl` hashes the file,
> so the build ID changed and looked like the new module was in the build. A hash of
> a file on disk proves the file exists, not that the toolchain reads it.

### FIX 2 — two nets were used above their declarations

Latent, and it would have surfaced the moment FIX 1 let elaboration proceed. The
sequencer was instantiated up in the system-bus slot section, next to
`sys_bus_stub_5` — but two of the nets it connects were declared further *down* the
file:

| Net | Declared at | Used at |
|---|---|---|
| `seq_ci`, `seq_cq`, `seq_sel` | with the phase shifter | sequencer instance, ~280 lines earlier |
| `exp_p_in` | House Keeping section | `.trig_i (exp_p_in[0])`, ~100 lines earlier |

SystemVerilog requires a `logic` declaration to precede its first use. Verilog nets
are forgiving about this; `logic` variables are not.

The instantiation moved down to sit immediately above the phase shifter it drives,
where everything it touches already exists. No connection changed — only its position
in the file. The alternative, hoisting the House Keeping declarations to the top,
would have scattered a block that reads cleanly as it stands.

### What was checked and found correct

- All 15 ports on the instance match the module declaration exactly, name for name.
- Bus slots 0–7 each have one owner: 0 housekeeping, 1 scope, 2 signal generator,
  3 phase shifter, 4 resonator, 5 stub, 6 acquisition, 7 sequencer. No slot is
  driven twice, none is left unanswered.
- `sys_bus_stub_7` is correctly removed — slot 7 now has a real module.
- Register map matches the header comment: STATUS packs to 32 bits with `cur` at
  [2:0], running [3], done [4], trigger-seen [5]; the set decode `sys_addr[6:4]`
  gives the documented 16-byte stride across 8 sets.
- The phase shifter's registered coefficient mux is between two flip-flops as
  described, so the guarded ADC → multiplier path is untouched.
- `tools/verify_rtl.py` passes: no name mismatches across 32 modules.

`seq_burst` and `seq_acq_arm` remain deliberately unconnected, as the RTL comment
says — wiring them needs new ports on the signal generator and acquisition system,
which is a separate change.

### Still to do

Synthesis has not been re-run — that needs Vivado on the machine with the board.
Both fixes are structural (a project-file entry and a block move), so the next build
is the real test.

---

## 2026-07-31 — Stage 10 first scan: one wild fit poisoned three verdicts. The sweep is now adaptive

The atlas's first run *proved the resonator works* — K agreed across branches to 2%,
two of three reproducibility points landed within 7% — while STEP 3 failed. The cause
was a single grid point whose fitted Q read **2×10²²**: near the narrowing phase the
feedback squeezes the line ~40×, to 5.6 kHz, and the fixed sweep grid (points 111 kHz
apart, each *listening* only ±16 kHz) could neither sample nor even *hear* it. The fit
of the resulting featureless data diverged, was stored ungated, and one number then
flattened the Q colour scale, dominated the Eq. 8 regression (slope 0.000, scatter 98%
— outlier arithmetic, not physics), and printed a fake "+100%" reproducibility failure.
Three symptoms, one cause: *a resolution coarser than the thing measured, with no gate
between a bad fit and the data it feeds*.

### The fix, iterated three times in simulation before touching the notebook

1. First attempt (gate on implausibly narrow fits) — simulation rejected it: an
   under-resolved line also produces implausibly *wide* fits that pass such a gate.
2. Second attempt (zoom ladder) — simulation exposed the deeper truth: the line hides
   *between the receiver's listening windows*, so no grid refinement alone can find it,
   and a low-contrast gate misreads *broad* lines as absent.
3. Final form, validated 300/300 in all four regimes (40× and 10× narrowed, open loop,
   2.4× broadened; width bias 0.4–2%, centres to tens of Hz):
   - **match the receiver to the grid** — decimation chosen per pass so the listening
     window is ~half the point spacing, rounded *wider*: nothing can hide in a gap;
   - read the data before trusting any fit — low contrast ⇒ widen the span; one point
     owning the power ⇒ zoom on it; then fit with centre/width/residual gates;
   - **deconvolve the known window** from the accepted width by bisecting the exact
     forward model — no calibration constants;
   - unresolved after five passes ⇒ nans, counted and reported, never stored.

Downstream hardening from the same lesson: the Eq. 8 slope is now a *median* of ratios
(a wild point moves a median by one rank, not twenty decades), the temperature map got
a log scale, reproducibility compares on a log scale, the analytic Lorentzian area
replaced span-dependent numerical integration, and the designer refuses to report an
unresolved point. Scan cost: ~20% longer, paid only by the narrowed minority of points.

---

## 2026-07-31 — Stage 9 passes in full. Gap analysis against the paper; Stage 10 built; Stage 11 planned

With Stage 9 passing, the project was audited feature-by-feature against Herkenhoff
*et al.* **Reproduced and proven:** the IQ phase shifter (their Eq. 10), the built-in
acquisition, Q modification (Eqs. 5/7), decoupling by detuning (Eq. 9), and the
software control loop (our measured 45 ms interval vs their reported ~80 ms). **Never
tested until now:** the effective-temperature law (their Eq. 8). **Not implemented:**
the parameter sequencer (their timed/triggered 8-set stepping — the enabler of
pulse-and-phase schemes), the second feedback channel with cancellation, and the SEO.

### New: `Test Stage 10 - Feedback Atlas and Operating Point Designer.ipynb`

The paper's Fig. 8 experiment: a gain × phase scan (default 14 × 24, ~7 min,
configurable) with a stability probe at every point — self-oscillation clips within
microseconds here, so 10 ms of silence proves stability; unstable territory is marked
black and walked around, never measured inside. Three heatmaps: Q, centre shift, and
**T_eff/T0** — the temperature map the paper derives but never images (bump *area* is
the temperature proxy, by equipartition). Cross-checks from the same data: Eq. 8 as a
slope-1 line through every stable point, K linear in gain along both damping phases,
and three settings re-applied cold to prove the maps work as a lookup. Then the
designer: `report()` (measured values + ring-up time, detection bandwidth, stability
margin, and an acquisition plan with bins/record-length/duration), `design_Q()`,
`design_shift()`, and the four canonical operating modes printed with their costs.
Ends with the SEO (their Fig. 12): our resonator grows on microsecond timescales, so
saturation is the fast limiter and the software loop trims the equilibrium onto a
setpoint — same architecture, honestly labelled difference. `EMULATION = False` runs
the identical atlas on the real coil.

One fix during construction, caught on review: a misplaced sign in the broadening-branch
linearity check (computed `1 + Q0/Q` instead of `K`).

### New: `SEQUENCER_PLAN.md` (Stage 11, design only)

The missing fabric feature, specified before any Verilog: 8 parameter sets stepped by
32-bit timers (8 ns resolution) or an external trigger edge; a coefficient-source mux
in front of the phase shifter (control values, not datapath); per-set flags to fire an
ASG burst (the stock generator's unused burst mode is the excitation pulse) and to arm
the acquisition (phase-coherent capture). Power-on behaviour bit-for-bit unchanged.
Includes the Stage 11 verification plan — timing truth by memory-stopwatch, the
paper's Fig. 11 sequence emulated end to end — and three open questions for review.

---

## 2026-07-30 — Stage 9 full run: four faults, four fixes, each one diagnosed from the numbers

| Step | Symptom | Cause | Fix |
|---|---|---|---|
| 1 | Width +42%, centre −16 kHz — but the *data points* traced the correct Lorentzian | `capture()` armed first and settled second, so each record began with the filter pipeline still flushing the previous tuning. The sweep's first point inherited the resonance-peak power of whatever came before it, and one poisoned point at the far end of a quadratic fit has maximal leverage | `capture()` now settles at the new tuning, *then* arms with a fresh writer: sample 0 is already clean. Applies to every capture everywhere |
| 3 | "Electron" *amplified* 1.29× instead of rejected 0.70× | The receiver was never re-pointed: Step 2's sweeps park the LO 2.5 linewidths away, so both tone readings were the averaged residue of a rotating phasor — measured 7.6e4 against a predicted 2.8e7, a factor ~370, which is the ratio that betrayed it | `acq.tune(f0)` before each tone measurement. The decoupling itself (−100 kHz shift, width −12%) had worked all along |
| 4 | Servo improvement 2.0× (gate: 3×) | Not a bug — the *exact* textbook residual of a P-only controller (gain 0.4) chasing a 30-cycle sinusoid; simulation reproduces 2.0× to the digit | PI control, gains from simulation (Kp = Ki = 0.5): 11× nominal, 7.5× with slope calibration 30% off; integrator pauses while the actuator is clamped |
| 5 | Chain latency −0.04 ms (negative), against 2.09 ms analytic | The stimulus was never reset between the five repeats: after the first, the tone was already on, the "edge" landed at the counter read itself, and the result was minus half the read-to-read gap | `step_latency()` takes a prep function restoring the OFF state before every repeat, and settles before arming, same discipline as `capture()` |

Step 2, meanwhile, passed at all three SNRs with K consistent to 0.007 — the sweep
machinery and the noise are sound; every fault above was in this stage's newest code.

---

## 2026-07-30 — Stage 9 Step 1, third method: the power sweep. The first two failed honestly

The spectrum-division fix failed too (+88.7% width): the ratio of two 16-average
spectra carries ~35% noise per bin, and the Lorentzian's entire signature inside the
filter's window is 3 dB of curvature. The bottom panel of the run was fit-proof fog —
the method was statistically starved, not wrong in principle. Rather than patch it
again, replaced it:

**The power sweep.** Point the receiver at a frequency, take the average power of a
short record, step, repeat — loudness against frequency *is* the bump. Three properties
make it decisively better, and simpler to boot: the ~30 kHz receiver window (R = 2048)
is identical at every point, so the chain's shape is a constant that cancels *by
construction* (no reference capture, no division); the sweep spans ±2.5 linewidths, the
whole curve rather than its top; and a 4096-sample variance carries ~2% noise per point
against the ratio method's ~35%. Simulated before adoption: width recovered to 0.7%
(statistical), centre to ±0.7 kHz — versus +15% and +89% from the two spectrum methods.

Step 1 was also given a labelled configuration block (`TANK_SH`, `OUT_SH`, `SWEEP_*`),
and Step 3 now locates the resonance the same way — its Welch-spectrum fits had the
same latent weakness, made worse by the shifted bump sitting against the filter's edge.
The flat floor is switched off during sweeps (a constant offset would bend the
reciprocal-parabola fit) and back on after. The Welch spectrum survives only as
illustration machinery, not as a judge.

For the record, the three-method history in one line each: *raw spectrum* — measured
`Lorentzian × chain`, +15%; *divided spectra* — chain cancelled but statistics starved,
+89%; *power sweep* — chain cancelled by construction and statistics tight, ±0.7%.

---

## 2026-07-30 — Stage 9 Step 1 first run: the chain shaped the spectrum, and the test blamed the noise

```
bump width : 255821 Hz vs known 222262 Hz (+15.1%)     STEP 1: FAIL (gate: 15%)
```

The spectrum plot gave it away: a "flat plateau with cliffs" instead of a bump — but the
y-axis spanned fifteen decades, so the Lorentzian's gentle 3 dB of curvature *was* the
plateau, and the cliffs at ±130 kHz were the correction filter's own band edges. What the
recorder measures is `Lorentzian × chain response`; beyond the ±10% clean band the droop
corrector overshoots, and that rising response stretched the fitted width by +15%. The
centre and the √R law both passed. A tolerance tighter than the measurement, once more —
the reference failed to budget for the instrument in the middle.

### Fixed by self-calibration, not by loosening the gate

`NOISE_OUT` injects **flat** noise *after* the resonator, so its spectrum through the
identical settings **is** the chain's response. Step 1a now captures both, divides, and
fits the ratio — the chain cancels exactly, since both records crossed the same filters.
The plot now shows the two raw spectra and the cleaned ratio with its fit.

Also from the same output: the 40 dB SNR case had hit the generator's 0.95 amplitude
ceiling (the knob quietly delivering ~38 dB). `TANK_SH` moved 2 → 3 (tank noise 6 dB
quieter, bump still enormous), and the calibration cell now warns explicitly if the
ceiling is ever clamped again.

---

## 2026-07-30 — Noise sources in the resonator; Test Stage 9 (noisy measurement, decoupling, servo, latency)

Stage 8 proved the feedback against a *clean* plant; a real measurement is never clean.
The chosen approach (digital, over cabling the real coil now): the real coil offers one
fixed SNR, no electron, and no known answers — the digital plant offers all three, and
the same notebook runs against the real coil afterwards.

### `red_pitaya_resonator.v`: two noise sources, `NOISE_TANK` (0x20) and `NOISE_OUT` (0x24)

Johnson noise injected *into* the loop (comes out as the Lorentzian bump, as the real
tank's noise does) and amplifier noise added *after* it (the flat floor). Two
free-running xorshift64 generators; four signed 14-bit lanes summed per sample for the
Gaussian shape (central-limit, like four dice); amplitude in 6 dB right-shift steps,
enable bits, power-on off, both read back.

**Timing:** the recursive one-clock multiply-add is untouched. Tank noise joins the
*drive*, pre-summed into a register one clock ahead (side effect: the drive leg gains
one clock, ≈8 ns of extra emulated loop delay — irrelevant to the empirically-fitted
phases, documented in the header). Output noise joins the non-recursive output stage.

**A trap caught before it shipped:** the first version of the output addition mixed a
signed value with an unsigned concatenation — *"a concatenation in Verilog is unsigned"*,
the same trap as the corrector's one real hardware bug. It would have zero-extended
negative samples and broken saturation for the negative half of every cycle. Found by
manual review against this changelog's own trap list; all three sum sites now carry
`$signed()` with a load-bearing comment.

**Verified before building:** `verify_rtl.py` passes, and a bit-exact Python model of
the full arithmetic (xorshift, lane sum, registered drive, 18-bit rounded recursion)
reproduces the claimed noise RMS (9452 vs ~9460), credible Gaussianity, and a
noise-driven Lorentzian at the right centre with Q within statistics. **Needs a rebuild.**

### New: `Test Stage 9 - Noisy Measurement Emulation.ipynb`

Step 0 refuses to run unless the *noise* register answers (a Stage 8 bitstream fails the
probe). Step 1 proves the noise honest — bump shape, flat floor, √R law — and calibrates
the SNR knob in dB. Step 2 repeats the Stage 8 phase sweep at 40/20/6 dB: same K and
narrowing phase must come back, with the averaging cost measured in seconds. Step 3:
decoupling — feedback in the shifting quadrature moves the resonance off a fixed
"electron" tone and the tone's amplification must drop by the Lorentzian rejection at
the measured shift. Step 4: a software servo (two-point discriminator, P control through
the shifting quadrature) holds the operating point against a drifting coil at ±25% of a
linewidth. Step 5: the latency budget — register ops, chain group delay (memory writer
as stopwatch: sample counter and record share an index, so Python gets microsecond-class
timing), software sense/act from the servo logs, summed into the measured total control
interval, with the conclusion drawn: software control reaches ~Hz, anything faster is
the fabric's job — the quantified case for the unbuilt trigger synchronisation.

---

## 2026-07-30 — Resonator assessed for the 40 MHz / Q ≈ 180 coil; Test Stage 8 written

### Assessment of `red_pitaya_resonator.v` at the real coil's operating point

| Question | Answer |
|---|---|
| Can it be a 40 MHz, Q = 180 coil? | Yes. 40 MHz is well under the 62.5 MHz limit; Q = 180 sits in the sweet range of the module's own bit-exact table (≤1% Q error, full-scale drive allowed to Q = 1000); headroom at full drive ≈ 6 bits to spare |
| Does it disturb anything when disabled? | No. Power-on disabled, state held at zero, and the input multiplexer passes the ADC bit-for-bit. `sys[4]` was a stub before — no address conflicts. `verify_rtl.py` passes |
| Does it disturb the feedback path when enabled? | The mux is one LUT on the guarded ADC→phase-shifter path: no clock cycle added, but **check the timing report after the rebuild and re-measure the 119.87 ns loop delay** — the file's own warning, honoured |
| Anything found? | One documentation gap: `DELAY = 0` silently means 256 clocks (circular-buffer read-during-write, the same failure shape as the phase shifter's FIX 4). Header now says so; use 1–255 |
| Supporting cast ready? | Phase shifter: yes — its header already works the 40 MHz case (k = 2, D = 7.031, 2-sample latency correction). Generator: register recipe extracted from stock source. `dac_a` is the saturated sum of generator + feedback, and that exact value drives the resonator — the emulated coil hears what the real one would |

### New: `Test Stage 8 - Active Feedback on a Known Resonator.ipynb`

The Herkenhoff phase/gain sweeps, run against the known-answer plant, every cell
explained. Step 0 refuses to run on a bitstream without the resonator (write/read-back
probe — a stub answers zero). Step 1: open-loop network-analyser sweep; the Lorentzian
fit is judged against the frequency and Q implied by the *rounded* 18-bit coefficients,
not the ideals. Step 2: 24-point feedback-phase sweep; linewidth and centre must trace
two sinusoids with the physics-fixed 2:1 modulation ratio; extracts loop gain K and the
narrowing phase (transport delay folded in — the number the real experiment needs).
Step 3: Q-control overlays, judged against `Q0/(1∓K)` using only previously measured
numbers. Step 4: gain sweep, linear approach to the self-oscillation threshold,
extrapolated from a safe distance. Measurement method throughout: acquisition LO tuned
to exactly the drive frequency so the tone lands at DC, where the two-register PEEK
read-skew artefact cannot exist. Clip flag checked after every sweep.

**Needs the pending rebuild** (which also carries the trusted badge and the axi0
default) — the resonator exists in source only until then.

---

## 2026-07-30 — Stage 7 first run: two FAILs, both in the test, neither in the instrument

```
measured peak : +5119.5 Hz   expected +5000.0   error +119.5 Hz    frequency: FAIL
ratio         : 1.9817       (measured / predicted amplitude)      amplitude: FAIL
```

**Frequency — a tolerance tighter than the measurement (again).** Step 1's reference
frequency came from a 131 µs scope glimpse: 7629 Hz bins, so even interpolated it is only
good to ~±100 Hz — before adding tens of ppm of crystal disagreement between generator
and board. Step 2 then demanded a few hertz. The diagnostic observation: **the error was
+119.5 Hz at OFFSET = 3000 *and* 5000** — the instrument moved the peak by exactly the
amount asked, both times; only the reference was off, by a constant.

Fix: Step 1 now refines `F_SIG` with the acquisition system itself (0.13 s capture,
7.5 Hz bins, sub-hertz interpolation), parking the reference 2 kHz below the coarse
estimate and measuring where the tone lands. Not circular: the refinement pins `F_SIG`
at one reference setting, then Step 2 moves the reference thousands of hertz and demands
the peak follow exactly — consistency of the frequency axis, the property Stage 8 relies
on. Absolute frequency is set by the 125 MHz crystal, which no self-test can check
against itself.

**Amplitude — a scale applied twice, as the cell's own error message guessed.** The
spectrum normalisation carried the factor of 2 that belongs to REAL signals (amplitude
split between +f and −f, one-sided display doubles). This data is COMPLEX: one line per
tone, nothing split, nothing to double. Removed — the measured ratio becomes 0.991, a 1%
end-to-end amplitude agreement. The same factor was removed from the noise-floor and
droop cells for consistency (both use ratios, so their verdicts never depended on it).

---

## 2026-07-30 — Stage 7 brought up to the system Stage 6 proved

Stage 7's setup cells predated the whole Stage 6 debugging campaign. They carried, ready
to fire, three of the traps that campaign documented — plus everything it never knew about:

| Old Stage 7 | Now |
|---|---|
| Memory region from a `mem=` kernel argument this board does not use (the cell would stop at an assert) | Same discovery ranking as Stage 6 Step 1: memory above the declared end first (no cached second view), else the largest reserved block |
| `MEM_STOP = start + 8 MB` — one past the end; the hardware treats `MEM_STOP` as the LAST writable address | `start + size − 8`, inclusive, same as Stage 6 |
| No port select — captures ran on whatever `CTRL[8]` held | Explicit `AXI_PORT = 0` with the axi1 warning |
| No write-error check — a refused transfer would have returned stale memory as "data" | `capture()` raises with the TrustZone instruction if `STATUS2[3]` is set |
| No poison — "never written" indistinguishable from a measurement | The range is pre-filled with `0xDEADBEEF`; poison in the read-back raises, and if the poison sits only in Q slots the error names the axi1 signature |
| No TrustZone awareness | The setup cell reads `TZ_DDR_RAM` and prints the one-line fix if the region is closed |

The `capture()` interface is unchanged — `(z, status)` in, same arguments out — so the
measurement cells (frequency, amplitude, noise-versus-R, droop check) are untouched. The
transport can no longer hand them plausible garbage: every failure mode now raises with an
instruction instead of returning numbers.

Also: the Stage 6 driver's `setup()` *default* for `axi_port` was still 1 (axi1); only the
notebook's constant had been flipped. Both notebooks now default to axi0 at every level.

*(Process note, recorded in the spirit of the traps list: the first attempt at two of
these notebook edits wrote a literal `\n` instead of a line break — caught because every
edit is followed by a read-back check, which is the only reason text replacements can be
trusted at all.)*

---

## 2026-07-30 — Stage 6 PASSES END TO END on axi0. axi1 drops half of every sample

With TrustZone open, Stage 6 step 3 on **axi1** produced a new, exact symptom: every I
value landed in the right place, in the right order — and every Q slot still held the
probe pattern. Memory read `[I0][dead][I1][dead]…`: the lower 32 bits of each 64-bit
sample stored, the upper 32 silently discarded, no error flagged anywhere.

That fingerprint means the port itself was executing 64-bit writes as if it were 32 bits
wide. The byte-enable path through the whole design was checked first and is full-width
everywhere (`axi_wr_fifo.v` holds all eight enables permanently high) — and
`diagnose_hp_ports.py` had in fact already shown the culprit and had it explained away:
**HP1 has a channel in 32-bit mode; HP0 is clean 64-bit on both.** Set that way by the
boot software, like the TrustZone register.

The proof took one register write, which is exactly what `CTRL[8]` was built for:
`AXI_PORT = 0` and **the entire Stage 6 notebook passed** — I counting, Q its
complement, `I + Q = 0xFFFFFFFF` throughout. The first fully verified
FPGA-to-memory transport in the project's history.

Two lessons for the traps list:

- **A test can pass on the port that lies.** axi1 reported perfect acceptance while
  discarding half of every sample. Only content verification (step 3) caught it.
- **A dismissed anomaly is a clue on layaway.** The 32-bit setting was in the first
  diagnostic dump, labelled "harmless, we never read". It was the answer.

### Why axi1 stays broken, and why that is acceptable

Correcting HP1's width register from Linux is refused: reads are allowed, the first
write kills the process with `Bus error` (observed; harmless, nothing changed). So the
project standardises on **axi0**, whose boot configuration is correct:

| Change | Where |
|---|---|
| Notebook default `AXI_PORT = 0`, with the reason in a comment | `Test Stage 6` cell 8 |
| Power-on default of `CTRL[8]` flipped to axi0 (**needs the pending rebuild**) | `red_pitaya_acq.v` |
| `check_system.py` prints the selected port and WARNS if axi1 is armed | section 4 |
| Register-map docs updated: axi1 marked diagnostics-only | `red_pitaya_acq.v` header, `README.md` |
| `--set-afi-64` documented as ineffective on this board | `diagnose_hp_ports.py` |

Nothing is lost: the two ports are identical in the design, axi1 remains selectable for
diagnostics, and the port comparison switch has now earned its keep twice.

---

## 2026-07-30 — SOLVED: TrustZone. Memory writes work for the first time

`diagnose_hp_ports.py` read `TZ_DDR_RAM` on the running board: **0x00000000** — every
64 MB slice of memory closed to untrusted writers, the power-on default, never opened by
the boot software. Opened it (`--open-tz`), re-ran Stage 6 step 2, same bitstream:

```
WRITE ERROR flag             : False
STEP 2: PASS                          <- with the honest verdict line
```

456160 bytes landed. **This is the first successful FPGA-to-memory write in the
project's history**, and it closes the mystery that consumed 2026-07-29 and -30: the
write engine (`axi_master.v`) presents the *untrusted* badge (`awprot = 3'b010`), the
processor's own writes are trusted, so the CPU could always write what the FPGA never
could — at any address, on either port, with every visible signal saying "accepted".

### The fix, in three layers

| Layer | What | Why |
|---|---|---|
| **Now (volatile)** | `diagnose_hp_ports.py --open-tz` opens memory until the next reboot | Unblocks Stage 6/7 immediately, no rebuild |
| **Permanent (next rebuild)** | `axi_master.v`: `axi_awprot_o` changed `3'b010` → `3'b000` — the write engine now presents the *trusted* badge, baked into the bitstream | Survives reboots, SD-card swaps and OS updates. Affects only the badge on writes; no data, timing or feedback-path change. The scope's deep path shares the module and merely gains the same immunity. Read channel left untouched (unused; noted in the comment) |
| **Guard** | `check_system.py` now checks `STATUS2[3]` (write-error flag) and reads `TZ_DDR_RAM`, warning if memory is closed | A reboot silently reverts the volatile fix; the ten-second health check now catches it in plain English |

Also: the Stage 6 notebook printed `<- memory REFUSED a write` as a fixed label even
next to `False`; the annotation now matches the value.

**Until the next rebuild:** after every boot, run
`sudo python3 diagnose_hp_ports.py --open-tz` before capturing to memory.
After a rebuild with the badge fix, nothing is needed — and `check_system.py` says which
case you are in via the build fingerprint.

---

## 2026-07-30 — The block design is innocent; the suspect is the boot software

The refusal-on-both-ports result pointed at the Zynq block design. It turns out the
handover was wrong that it "exists in no file" — it is `Test_Project.srcs/sources_1/bd/
system/system.bd`, and it is clean: all four HP ports enabled, 64-bit, with the full
0–512 MB memory range mapped through each. Together with the already-cleared RTL, that
exonerates *everything expressed in this repository*.

What no file here controls is the processor's **runtime** configuration, written by the
boot software on the SD card. Two runtime settings produce exactly the observed symptom
(handshakes fine → refusal; CPU unaffected; both ports identical):

1. **TrustZone** (`TZ_DDR_RAM`, 0xF8000430). One bit per 64 MB of memory; power-on
   default is "refuse all untrusted writers". `axi_master.v` hard-codes the untrusted
   badge (`axi_awprot_o = 3'b010`), so if boot never opens this register, every
   FPGA-side write is refused everywhere, forever, while the CPU sails through.
2. **HP port width** (AFI control registers). A runtime 32/64-bit switch per port;
   ours are 64-bit writes.

### New: `acquisition_custom/diagnose_hp_ports.py`

Runs on the board, reads both settings and explains them; `--open-tz` / `--set-afi-64`
apply the corresponding fix. No rebuild, no bitstream change — settings live in the
processor and reset at reboot, so a confirmed fix then needs making permanent (boot
script, or a one-line `awprot` change in the next rebuild).

---

## 2026-07-30 — Both ports refuse every write, and now the chip says so

The rebuild with `STATUS2[3]`, `CTRL[8]` and the response-code fix ran on hardware.
The result, identical on both ports:

```
address counter advanced : 456584 bytes  (expected about 456584)
memory overflow flag     : False
WRITE ERROR flag         : True   <- memory REFUSED a write     (axi1)
WRITE ERROR flag         : True   <- memory REFUSED a write     (axi0)
```

This is the first *positive* evidence in the whole Stage 6 investigation. Every earlier
signal said "the writes were accepted"; the chip now says **every write is answered with a
refusal**, on both ports alike. That eliminates the acquisition logic, the port choice, and
the address wiring in one stroke — everything expressed in the source files is exonerated.

What remains is the one thing no source file describes: the Zynq block design. The
high-performance (HP) memory ports the writer talks through are configured inside the
processing-system block, and a port that is disabled or has no address route answers
exactly this way — refusing writes with a decode error. Next visit: open the block design
in Vivado, check the HP slave ports are enabled and that the memory address range is
mapped in the Address Editor.

Per `HANDOVER.md`'s fallback, **Stage 7 proceeds without the memory path**, using
register-based capture, with the memory path recorded as unproven.

### Also fixed: the Stage 6 verdict trusted two flags and ignored the third

`Test Stage 6` step 2 printed `PASS` on a run in which memory refused every write:

```python
print('STEP 2:', 'PASS' if (n_written > 1000 and not st['mem_overflow']) else 'FAIL')
```

The verdict predates the write-error flag, so it measured *acceptance*, not *success* —
the same disease the flag was built to cure, one layer up. It now also requires
`write_error` to be clear. Notebook edit only; no rebuild. `verify_notebooks.py` passes.

---

## 2026-07-30 — The write-error flag could not see the most likely error

Found by inspection before the Stage 6 rebuild, in `axi_master.v` — stock Red Pitaya code.

Memory answers every write with a two-bit code: `00` success, `10` "the memory device
failed" (SLVERR), `11` "nothing exists at that address" (DECERR). The line feeding the new
`STATUS2[3]` write-error flag tested for exactly `10`:

```verilog
sys_werr_o <= axi_bvalid_i && (axi_bresp_i == 2'h2) ;
```

Stage 6's suspected fault is a port not routed through to memory inside the Zynq block
design — and an unrouted address answers `11`, not `10`. So the flag built to expose the
fault would have stayed clear while every write was refused: one more plausible wrong
answer, caught this time before it cost a day.

### Fixed

One character, plus a comment explaining the four response codes:

```verilog
sys_werr_o <= axi_bvalid_i && axi_bresp_i[1] ;
```

The top bit is `1` for both failure codes, so every kind of refusal now sets the flag.
Safe to change: this wire only *reports*; it carries no data. The oscilloscope also
instantiates `axi_master`, but its copy of this wire is discarded (`red_pitaya_top.sv`
feeds the scope's `werr` inputs a constant 0). `verify_rtl.py` passes after the edit.

Not yet built — goes into the same rebuild as `STATUS2[3]` and `CTRL[8]`.

---

## 2026-07-30 — Version control: git, GitHub, and the commit stamped into the bitstream

The project goes into git. 78 MB becomes **2.4 MB across 160 files** — the same exclusion list
the source-only backup uses, so there is one rule with two implementations.

### The part that matters most here

This project lost two days to one question: *is the chip running the code I am looking at?* It
was answered by making the bitstream carry a fingerprint of its own source, at register `0x48`.
Git closes that loop completely:

```
register 0x48  ->  bitstream_id.txt  ->  a commit  ->  git checkout
```

`build_project.tcl` now records the commit at build time, writes it into `build_id.vh` and
`bitstream_id.txt`, and **warns loudly when the working tree is dirty**:

> *** THIS BITSTREAM WILL NOT MATCH ANY COMMIT ***
> 3 file(s) are edited but not committed, so there is no commit you could check out later to
> reproduce what is about to be built.

Nothing is blocked. But a build that turns out to be the good one, made from uncommitted edits,
is a result you remember rather than one you can defend.

`git_state` tested against a real repository, clean and dirty: returns the commit and the count
of outstanding files correctly in both.

### New files

| | |
|---|---|
| `GIT.md` | Git and GitHub from nothing, for someone who has used neither. The three-places idea, the daily four commands, how to write a message worth reading, going back, tags, and an honest note that branches are probably not needed yet |
| `.gitignore` | Mirrors the backup's exclusion list, with the reasoning inline. **Verified**: 160 files kept at 2.4 MB, 374 ignored, and the six must-keeps and three must-nots all land correctly |
| `.gitattributes` | Line endings. The PC is Windows and the board is Linux, and without a rule git eventually shows a file as entirely rewritten when only the invisible characters changed. `.py` and `.sh` forced to Linux endings, since they run on the board |
| `tools/save.ps1` | The daily four in one command, printing each as it runs. Deliberately framed as training wheels — those four commands are the same on every project and are worth knowing |

### Bitstreams stay out of git, on purpose

A 2 MB binary that changes completely on every build. Git stores every version in full, cannot
diff two of them, and at this project's build rate would add half a gigabyte a month of files
nobody can read. `tools/backup.ps1` keeps the built bitstream; git keeps the source that makes
it; `0x48` ties them together.

### `backup.ps1` has a narrower job now

It checks the repository, records the commit inside the archive as `BACKUP_INFO.txt`, and says
plainly when there are changes the zip has captured but git has not — because a zip is a
snapshot nobody will read, and a commit is a snapshot with an explanation attached.

---

## 2026-07-30 — The backup keeps only what a rebuild needs: 78 MB becomes 2 MB

`tools/backup.ps1` now archives sources only, by default.

| | Before | After |
|---|---|---|
| Staged | 78 MB | **4.4 MB** (2.3 MB of sources plus the 2.1 MB bitstream) |
| Zipped | 35 MB | **about 2 MB** |
| Files | thousands | 155 |

### What was excluded, and how it was checked

The 36 MB of `Test_Project.srcs` turned out to be **35 MB of block-design output products** —
13 MB of generated IP and 21 MB of Xilinx library HDL, including a single 14 MB VHDL file. Those
are produced from `system.bd`, not written by anyone.

Excluding a real source would give a backup that cannot be restored, so this was verified rather
than assumed:

- `system.bd` carries **all 303 `PCW_*` processor parameters itself** — `PCW_USE_S_AXI_HP0/1 = 1`,
  `PCW_S_AXI_HP_DATA_WIDTH = 64`, the lot. The `.xci` files under `ip/` are its outputs.
- The `.xpr` lists exactly two block-design files: `system.bd` and `hdl/system_wrapper.v`.

Also excluded: `Test_Project.runs` (36 MB), `Test_Project.cache`, `results`, `__pycache__`,
`.Xil`. **The built bitstream and its fingerprint are kept** — 2 MB, and they mean a working
board can be restored without a 25-minute rebuild.

### The companion change, without which this would be a trap

A project restored from a sources-only backup has a block design with **no output products**,
and synthesis fails on it. So `build_project.tcl` now detects that and regenerates them — about
two minutes, once, and it costs nothing when they are already there.

Shrinking the backup without this would have produced an archive that looks complete, restores
cleanly, and then fails to build for a reason nobody would connect to the backup.

### It verifies itself

After writing the zip the script reads it back and confirms thirteen named files are present.
If any is missing it reports which, leaves the archive for inspection, and exits non-zero rather
than claiming success.

A backup you cannot restore is worse than none, because you stop worrying about it.

`-Full` keeps the old behaviour.

---

## 2026-07-30 — Stages 1–7 all pass. A digital resonator, to test the feedback

With the acquisition chain proven end to end, the next question is the feedback system: gain and
phase sweeps against a resonator. Testing that against the real coil means a cryostat and a
resonator whose centre frequency and Q are themselves unknowns. So the plant is now built in
logic, with both set exactly — the same known-answer discipline that found the only real bug in
the corrector.

### `red_pitaya_resonator.v`, on `sys[4]` at `0x40400000`

Enabled, it replaces the digitised CH A signal with a resonator driven by what the board is
sending out, so the loop closes inside the chip:

```
generator ─┐
           ├──▶ DAC value ──▶ [resonator] ──┬──▶ acquisition system
feedback ──┘                                │
    ▲                                       │
    └───────────────────────────────────────┘
```

**Disabled at power-on.** While disabled the muxed net is the ADC exactly.

### Three design decisions, each with a reason

**Coupled form, not the textbook one.** The obvious resonator is
`y[n] = 2r·cos(ω)y[n-1] − r²y[n-2] + x[n]`, and it is a poor choice: the pole radius sets Q and
reaches the arithmetic only through `r²`, so rounding that coefficient moves the pole in exactly
the direction that changes Q. The coupled form keeps two quadrature states, the radius is
`√(c²+s²)`, and rounding trades one coefficient against the other. Measured on a bit-exact model:
**Q within 1% of asked, from 30 to 1000.** It also yields the analytic signal for free.

**25-bit state, 18-bit coefficients — one DSP slice per multiply.** A resonator is recursive, so
the whole multiply-add must finish in one clock and **cannot be pipelined**. This project has
already lost a day to that: the stock scope's `dfilt1` is recursive, could not be pipelined, and
produced 1173 failing endpoints until removed. Anything wider needs cascaded slices whose delay
lands inside the loop. The header says so, and says to narrow rather than widen if timing fails.

**Rounding, not truncation.** Truncation biases every sample towards minus infinity, and in a
loop with a gain approaching one that bias accumulates into a drift or a small self-sustaining
oscillation — which looks uncomfortably like a real resonance.

### A programmable loop delay, because the emulation would otherwise flatter itself

The real loop carries 119.87 ns of converter and cable delay — **43° at 1 MHz, 286° at 40 MHz**.
Inside the chip there is almost none. Without `DELAY` the digital test would remove the very
thing the phase shifter exists to compensate. Set it to 15 clocks to match the board.

### Verified before any of it was written

| | |
|---|---|
| Q from the bit-exact model | within 1.8% at Q=30, 0.4% at Q=300 |
| Headroom | Q up to 1000 at full drive; 10000 needs 21% drive. Sticky clip flag so this is never mistaken for physics |
| The physics | linewidth changes **linearly with feedback gain**, in **opposite directions for opposite phase**, and the peak height tracks Q **exactly** — 1.12 against 1.12 at Q=335/299. That last one is a free known-answer check |

**One measurement error found and fixed while doing this:** counting grid points above half
maximum underestimates the linewidth by up to a grid step, which looked like a consistent 11%
error in Q across every setting. Interpolating the crossings fixes it. `linewidth()` in
`resonator.py` does it correctly and says why.

### Also

`verify_rtl.py` caught a mis-matched anchor during this work, before any build. Five edits to
`red_pitaya_top.sv`, each asserted to have applied. `resonator.py` added; source list and build
fingerprint updated.

**Not yet built.** Needs one rebuild, and the timing report needs checking — the resonator's
recursive loop is the one path where that is not a formality.

---

## 2026-07-30 — The check blocked the build for its own reasons

```
RTL PROBLEMS - synthesis WILL fail. Not starting the build.
  Fatal Python error: Failed to import encodings module
  C:\Xilinx\Vivado\2020.1\tps\win64\python-2.7.16\lib\encodings\__init__.py
```

Two errors, both mine, and the second is the worse one.

**`exec python` from inside Vivado is not the Python you think it is.** Vivado puts its own
2.7.16 at the front of the PATH, and on this installation that copy cannot even start. The
checkers are Python 3.

**A convenience was given the power to stop a build.** That is the real fault. A pre-build check
exists to save time; if it cannot run, the correct behaviour is to say so and get out of the way.
Instead it reported a Python installation problem as "synthesis WILL fail" and refused to
proceed — confidently, and about entirely the wrong thing.

### Fixed

| Change | |
|---|---|
| `find_python3` | Tries `python3`, `py -3`, then `python`, and **asks each one its version** before trusting it. Vivado's 2.7 fails the probe and is skipped |
| `run_checker` | Distinguishes three outcomes by inspecting Tcl's `-errorcode`: the script ran and passed, the script ran and found problems, or the script could not run |
| The build | **Aborts only on `problems`.** `unavailable` prints one line and carries on. No Python 3 on the machine means the checks are skipped, not that the build stops |

Tested against all three cases — a passing script, a script exiting 1, and a missing script — and
each is classified correctly.

### New: `HANDOVER.md`

A single page saying where the project stands: what is verified, what the one open problem is,
what has been ruled out and how, what to do next, and the ten traps that have each cost a day.
Written so a fresh start can pick the work up from the files rather than from a conversation.

---

## 2026-07-30 — A broken build, and the check that should have prevented it

```
[Synth 8-448] named port connection 'axi_sel_o' does not exist for
              instance 'i_acq' of module 'red_pitaya_acq'
```

My fault, and avoidable. The port was added to `red_pitaya_acq.v` by a text replacement that
looked for

```
  output                    axi_wfixed_o   ,
```

while the file actually said

```
  output                    axi_wfixed_o,
```

Different spacing. **The replacement silently did nothing**, the *use* of the port was added
successfully, and the design referred to a port that did not exist. I grepped afterwards, saw
`assign axi_sel_o = set_axi_sel;` in the output, and did not notice the port declaration was
absent from that same output.

### Fixed and audited

The port is declared. Every other edit in that pass was then checked individually rather than
assumed:

| | |
|---|---|
| `red_pitaya_acq_dma.v` | `stat_werr_o` declared as a port, driven in all three branches |
| `red_pitaya_acq.v` | `axi_sel_o` declared and driven; `set_axi_sel` declared, reset, written by CTRL[8], read back at bit 8; `dma_werr` declared, connected, and in STATUS2 bit 3 |
| `red_pitaya_top.sv` | all six `acq_axi_*` nets declared, `wvalid` gated to each port, `wrdy` and `werr` muxed back, scope disconnected from both ports |
| Bit accounting | CTRL readback is exactly 32 bits with `set_axi_sel` at bit 8; STATUS2 is exactly 32 with `dma_werr` at bit 3 |
| Multiple drivers | each of the eight shared axi nets is assigned exactly once |

### New: `tools/verify_rtl.py`

```
python3 tools/verify_rtl.py
```

One second, no Vivado. It checks:

1. every module named in an instantiation exists
2. **every `.foo()` connection names a port the target module actually has** — the one that bit
3. every signal driven by a continuous assignment is declared in that module
4. unconnected ports, reported as information rather than as an error

**Verified against the real failure**: with the port declaration removed it reports both the
missing declaration and the bad connection; with it restored, it passes.

Two false positives were found and fixed while writing it, which is worth recording because a
checker that cries wolf gets ignored:

- `localparam type SBA_T = logic signed [14-1:0];` — a user-defined type introduced by
  `localparam type` rather than `typedef`, so `SBA_T [MNA-1:0] adc_dat;` looked undeclared.
- Alternate top levels for boards this project does not target. It now walks down from
  `red_pitaya_top` and checks only what is reachable — 15 modules of the 30 present.

**It runs inside `build_project.tcl`, before synthesis, and aborts the build if it finds
anything.** A name mismatch now costs a second instead of ninety.

---

## 2026-07-29 (thirty-seventh pass) — Two things that should have existed already

Fair challenge: axi1 is the port the design has always used, so "it is the port" needs better
evidence than "everything else checks out". Two additions make the question answerable rather
than arguable. **Both need one rebuild.**

### `STATUS2[3]` — the write-error flag

`axi_werr_i` reports memory answering a write with an error instead of an acknowledgement. It
has been wired into `red_pitaya_acq_dma.v` since the module was written and **thrown away**.

That is why a transfer could report perfect success and leave memory untouched: every signal
software could see — address counter, overflow flag, sample count — says *the writes were
accepted*. None of them says *the writes succeeded*. This is the one that does. Sticky, cleared
with everything else by `dma_clr`.

### `CTRL[8]` — choose the memory port at run time

Both processor write ports are now wired to the acquisition system, and one register bit selects
between them. Only `wvalid` is gated, so exactly one port ever sees a write and the other sits
idle. The scope gives up its `axi0` deep-memory capture as it already had `axi1`; its ordinary
16384-sample buffers, which the diagnostics use, are untouched.

Comparing the two ports was a 25-minute rebuild per attempt. It is now a register write.

| CTRL[8] | Port |
|---|---|
| 1 | axi1 — as before, the default |
| 0 | axi0 |

### On "it worked before"

Worth stating plainly: **there is no evidence in this project that DDR writes on this board have
ever worked.** The Red Pitaya oscilloscope's normal mode uses its own 16 kSample block memories,
which is what every diagnostic here has used. The `axi0`/`axi1` paths belong to its *deep-memory*
capture, a feature nothing in this project has exercised. So "the port has always been there" is
true, and "the port has been shown to work" is not.

Both flags now print in Step 2, and Step 3's failure message names the other port as the next
thing to try.

---

## 2026-07-29 (thirty-sixth pass) — Not the cache either: the fault is past the logic

The un-declared region behaves identically to the reserved one.

| Region | Counter advanced | Overflow | Memory afterwards |
|---|---|---|---|
| `labuf@a000000` (inside the kernel map) | 457032 = 57129 x 8 | clear | unchanged |
| `0x1E000000` (never declared to the kernel) | 456688 = 57086 x 8 | clear | unchanged |

`0x1E000000` has no cacheable view — the kernel was never told it exists — so a stale-cache
explanation is dead. Both trial captures also wrapped exactly as arithmetic demands
(24591 mod 512 = 15, counter at sample 15; 24568 mod 512 = 504, counter at sample 504).

### Everything in the source has now been checked

| Checked | Result |
|---|---|
| `stat_cur_addr_o` | is `next_address`, advances only on `axi_wrdy_i && axi_wvalid_o` — accepted writes |
| Byte enables | `axi_wsel_o <= {SW{1'b1}}` — all bytes enabled, so writes cannot be silently masked |
| `red_pitaya_ps.sv` array wiring | `axi_master_0_1[1:0]`: index 1 is axi1 on the system side **and** hp1 on the AXI side. Symmetric and correct |
| Clock and reset | `hp1_saxi_clk_i = axi1_clk_i` = 125 MHz from the acquisition; `hp1_saxi_rstn_i = axi1_rstn_i` |
| Top-level | acquisition drives axi1, scope no longer does, scope's axi1 inputs tied off |

The processor can write and read `0x1E000000` — the fill pattern proves it. The logic's writes
are accepted and do not arrive. **The fault is between `axi_master` and the memory, which is
inside the block design rather than in any file that can be read here.**

### Decisive experiment

Move the acquisition from **axi1 to axi0**, the port the stock oscilloscope uses and which is
therefore known to work, and rebuild. The scope's own memory path is not used by anything here,
so it can be disconnected from axi0 as it already was from axi1. If the capture then works, the
difference is the port; if it does not, it is the module.

### Fixed: the hard-coded overflow label

`overflow flag : False <- EXPECTED` was written when the trial used `wrap=False`, where an
overflow genuinely is expected. The trial was later changed to `wrap=True`, where overflow is
**impossible** — a wrapping writer always has somewhere to put the next sample — and the label
became actively misleading.

It is now derived from the settings in use, and a set flag while wrapping stops the test, since
that would be a real fault rather than an expected one.

---

## 2026-07-29 (thirty-fifth pass) — The writes happened; the processor cannot see them

```
address counter advanced : 457032 bytes  (expected about 457032)
overflow flag            : False
```

exactly 57129 samples x 8 bytes, and then

```
first four I : ['0xdeadbeef', '0xdeadbeef', '0xdeadbeef', '0xdeadbeef']
```

### The counter is not a guess

`stat_cur_addr_o` in `axi_wr_fifo.v` is `next_address`, and that only advances on
`axi_wrdy_i && axi_wvalid_o` — an accepted write. It tracked the sample count to the byte, and
the trial capture wrapped exactly 48 times and landed on sample 15 (24591 mod 512 = 15). **The
writes were issued and accepted.** The wiring was checked too: `axi_master_0_1[1]` carries axi1
to `S_AXI_HP1`, the acquisition drives it, the scope no longer does.

So the data went into memory, and the processor read back the fill pattern instead.

### Two views of the same addresses

The logic writes through a port that **bypasses the processor's caches**. `labuf@a000000` sits
inside the memory the kernel was told about, so the processor also holds a **cacheable** view of
those addresses alongside the uncached one `/dev/mem` provides. A write through one view is not
reliably visible through the other, and the symptom is exactly what was seen: everything reports
success, and the memory reads back unchanged.

"Reserved" turned out to be the wrong property to optimise for. **Not allocated is not the same
as not mapped.**

### Ranking changed

Step 1 now prefers **memory the kernel was never told about** over a reserved-memory block
inside the map:

| Rank | On this board | Why |
|---|---|---|
| 1 | `0x1E000000 .. 0x1FFFFFFF`, 32 MB | The device tree declares 480 MB of the 512 MB fitted. The kernel has **no view of this at all**, cached or otherwise, so there is nothing to be stale |
| 2 | `labuf@a000000`, 32 MB | Reserved, but inside the linear map — a cacheable alias exists |
| 3 | `buffer@1000000`, 1.5 MB | Same, and small |

This is also why Red Pitaya's own images shrink the memory node rather than only reserving: the
top of RAM becomes genuinely unreachable rather than merely spoken for.

A new markdown cell records the signature — counter advances, overflow clear, memory unchanged —
so it is recognised on sight rather than re-derived, and gives the two lines needed to force the
region by hand.

---

## 2026-07-29 (thirty-fourth pass) — Step 3 was reading Step 1's probe

```
first four I : [2779096485 2779096487 2779096481 2779096483]
first four Q : ['0xa5a5a5a4', '0xa5a5a5a6', '0xa5a5a5a0', '0xa5a5a5a2']
check 1  I + Q == 0xFFFFFFFF : False  (0 of 57061)
```

2779096485 is **0xA5A5A5A5**. Interleaved, those eight words are

```
a5a5a5a5 a5a5a5a4 a5a5a5a7 a5a5a5a6 a5a5a5a1 a5a5a5a0 a5a5a5a3 a5a5a5a2
```

which is exactly `arange(n) XOR 0xA5A5A5A5` — **the pattern Step 1's probe wrote two cells
earlier.** Step 3 was not reading corrupt acquisition data. It was reading no acquisition data
at all: the memory writer never wrote to `MEM_START`, and the probe's leftovers were still
sitting there being reported as thousands of corrupt samples.

The probe was added last pass as a safety measure. It promptly caused a false diagnosis. That is
worth recording as its own lesson: **a diagnostic that leaves a mark behind becomes a source of
false evidence.**

### Fixes

| Change | Why |
|---|---|
| Step 1 **fills the region with `0xDEADBEEF`** after probing | A value that cannot occur in a counting sequence or a measurement. Any word still reading it is a word the hardware **did not write** — which turns "the data looks wrong" into "the data never arrived", a completely different fault |
| Step 3 recognises both patterns by name | Says "this is the probe pattern" or "nothing was written" and stops, instead of reporting 57 000 corrupt samples |
| Step 3 reports the **high-water mark** | Where the poison begins is where the writer stopped, so a partial capture is measured rather than guessed |
| Step 2 checks the **address counter moved** | `DMA_COUNT` counts samples handed *to* the writer; the address counter only moves when memory *accepts* a write. On this run they disagreed — 57061 against zero — and nothing was checking |
| The trial capture now uses **wrap = True** | With `wrap = False` it stops at the end of its window and latches that it has finished, a state the full capture then has to clear. Wrapping is just as bounded — that is what wrapping means — leaves nothing behind, and additionally exercises the wrap logic |

### Still open

Why the writer counted 57061 samples and moved no addresses. The chain was running and the
samples were produced, so the failure is in the write itself. Step 2 now prints the address
advance, the CTRL value and the region registers when this happens, which is the information
needed to tell apart: arm not set, region not accepted, or the writer left finished by the
previous capture.

---

## 2026-07-29 (thirty-third pass) — Stage 6's trial capture did its job

```
samples written : 26187   (a 4 kB window holds 512)
stopped at      : 0x0A001008   (4104 bytes in)
overflow flag   : True
SystemExit: The writer went OUTSIDE its window
```

**Nothing is broken, and nothing outside the reserved region was touched.** Everything written
lies in `0x0A000000 .. 0x0A001007`, well inside `labuf` (`0x0A000000 .. 0x0BFFFFFF`).

The hardware behaved exactly to its documented contract. Two mistakes were mine, in opposite
directions, which is why the result looked alarming.

### Mistake 1 — MEM_STOP is inclusive

From `red_pitaya_acq_dma.v`:

```verilog
input [AW-1:0] set_stop_i ,  //!< last address of the region
```

**Last address, not one past the end.** So the writer is entitled to write the 8-byte word *at*
MEM_STOP, after which its counter reads MEM_STOP + 8. Step 1 was computing MEM_STOP as
`start + size`, treating it as an exclusive end — which authorised the writer to touch 8 bytes
beyond what was intended.

Now `MEM_STOP = MEM_START + size - 8`, with a check that `MEM_STOP + 7` is still inside the
chosen region.

### Mistake 2 — the bound check was a word too tight

It rejected `cur > MEM_START + 0x1000`, but the legitimate resting place is one word past the
last writable address. Now the window is `[MEM_START, MEM_STOP + 8]`, and the failure message
says plainly that landing outside it is a hardware fault rather than a test artefact.

Verified against four cases: filling the window exactly passes; one word further, and anything
wilder, still fails.

### Mistake 3 — overflow was treated as a fault

The chain produces 122 000 samples a second while the trial runs; the window holds 512. Of
course it overflows, and the flag correctly says so. **Deliberately overflowing a small window
is part of what the trial is for.** The trial now says `EXPECTED` beside the flag and explains
why, and only the address decides pass or fail.

### The convention is now recorded where it cannot be missed

`0x2C` in the RTL header and in the README register table both now say **LAST address —
inclusive, not one past the end**, with the `first + size - 8` formula and a note that `MEM_CUR`
legitimately reads `MEM_STOP + 8`.

### Worth saying plainly

The trial capture was added precisely so that a mistake here would cost 4 kB instead of 8 MB.
It found a real off-by-one on its first outing, in a region that was reserved anyway, and
stopped before the full capture. That is the guard working, not failing.

---

## 2026-07-29 (thirty-second pass) — Test Stage 5 passes

All steps. The droop correction is verified on hardware: the filter is in circuit, the chip
holds the intended coefficients, the measured response matches the designed one, and switching
the correction on and off does not change the scale of the data.

**Stages 1–5 and 5b now all pass.** The signal path is verified end to end from the input
through mixer, decimator and corrector. What remains is the route into memory (Stage 6) and the
whole thing measured against a known signal (Stage 7).

Worth noting how many of this week's failures were the test rather than the hardware:

| Failure | Actually |
|---|---|
| Stage 5 "corrected curve not flat" | the amplitude estimator measuring its own artefact |
| Stage 5 Step 3 "changing the overall scale" | a 0.1% tolerance on a measurement worth 0.58% |
| Stage 5b Test C "taps not 308 apart" | the sign of the generator offset, guessed and doubled |
| Stage 5 "no signal" | `F_SIG` left at 1 MHz against a 10 MHz generator |
| Stage 6 "no reserved memory" | reading the device tree's memory node as RAM fitted |

One was real — the unsigned pre-add — and it was found by the one test built around a known
answer rather than a measured one. That is the lesson worth carrying into Stages 6 and 7, and
it is why Stage 6 leads with a counting sequence rather than a signal.

---

## 2026-07-29 (thirty-first pass) — There was a reserved region all along

`show_memory_map.py` on the board:

```
3. Already reserved for hardware  (device tree)
   buffer@1000000    0x01000000 .. 0x0117FFFF    1.5 MB    (streaming_reserved)
   labuf@a000000     0x0A000000 .. 0x0BFFFFFF   32.0 MB    (logic analyser)
   linux,cma         (dynamically placed)

1. RAM handed to Linux
   0x00000000 .. 0x1DFFFFFF   480 MB
```

**Nothing needs changing.** Two blocks are already declared reserved, and a third region exists
above the declared memory.

### My verdict logic was wrong

It read the device-tree memory node as *"RAM fitted"*. It is not — it is **"RAM handed to
Linux"**. So 480 MB declared against 480 MB claimed looked like no gap, and the verdict ignored
the three reserved regions it had just printed two sections earlier.

Worse, it missed the second answer hiding in the same number. A STEMlab 125-14 has **512 MB**
fitted and the device tree declares **480 MB**. The missing 32 MB is not lost — it is
deliberately withheld, which is the classic Red Pitaya arrangement: shrink the memory node and
the top of RAM becomes unreachable by Linux and therefore available to the logic.

### Both scripts now rank the candidates

| Rank | Region on this board | Why this order |
|---|---|---|
| 1 | `labuf@a000000`, 32 MB | A declared reservation is a **promise**: the kernel knows the block exists and has been told not to allocate it |
| 2 | `0x1E000000`, 32 MB | Genuinely unreachable, but rests on the board really having 512 MB — inferred, not read |
| 3 | `buffer@1000000`, 1.5 MB | Same promise, but only 196 608 samples |

Stage 6 Step 1 picks the best automatically and prints the addresses. On this board:

```
MEM_START = 0x0A000000
MEM_STOP  = 0x0A800000     8 MB, 1 048 576 samples
```

One caveat noted in both places: `labuf` is Red Pitaya's logic-analyser buffer. It is free
unless their logic analyser application is running, so do not run both at once.

### The u-boot.scr curiosity, recorded

```
setenv bootargs ... uio_pdrv_genirq.of_id="generic-uio"
setenv bootargs ${bootargs} mem=256M
```

The second line asks for `mem=256M`, and `/proc/cmdline` does not contain it — the running
kernel matches the device tree's `chosen/bootargs` exactly instead. So that line is not taking
effect on this image. Worth knowing, because someone reading `u-boot.scr` alone would conclude
memory was limited to 256 MB and it is not.

**Also:** sizes now print to one decimal place. `buffer@1000000` is 1.5 MB and was being rounded
to "2 MB", which would have been an unhelpful 33% overstatement of a region that small.

---

## 2026-07-29 (thirtieth pass) — The boot advice did not fit this image

Checking before changing anything turned up that Stage 6's instructions were written for a
different Red Pitaya image:

```
/dev/mmcblk0p1 on /boot type vfat (ro,relatime,...)

ls /boot
bin  boot.bin  devicetree.dtb  dtraw.dts  fpga  include  lib  rp_sdk
sbin  u-boot.scr  uImage  version.txt  www
```

| What I assumed | What is actually there |
|---|---|
| a text file `uEnv.txt` holding the boot arguments | **no `uEnv.txt` at all** |
| an editable file | `u-boot.scr` and `devicetree.dtb`, both **compiled** — they need `mkimage` and `dtc` |
| a writable partition | mounted **`ro`**, read-only |

Following the instruction anyway — remounting the boot partition read-write and editing
compiled files by guesswork — is a good way to end up with a board that does not boot. The
instruction has been replaced.

### New: `acquisition_custom/show_memory_map.py`

```
sudo python3 show_memory_map.py
```

Entirely read-only: mounts nothing, writes nothing, reboots nothing. It prints how much RAM is
fitted (device tree), how much Linux has claimed (`/proc/iomem`), whether anything is already
reserved (`reserved-memory` nodes), what the kernel was told at boot, and **where this
particular image keeps its boot settings** — including reading the text out of `u-boot.scr` and
the `reserved-memory` section out of `dtraw.dts` if either exists.

Then it gives a verdict, and if nothing is free it does **not** tell you to edit a file. It
lists the options in order of preference.

### The revised guidance

1. **Look first.** Many Red Pitaya images already reserve a block, because their own deep-memory
   acquisition needs one. If this one does, nothing needs changing.
2. **Ask whoever set the board up.** A two-minute question that avoids an afternoon of risk.
3. **Use a stock image that reserves memory.** Swapping the SD card is safer than modifying this
   one and is completely reversible — keep the original card.
4. **Rebuild the boot files.** Last resort, image the card first.

And a point worth making plainly in the notebook: **nothing verified so far depends on solving
this.** Stages 1–5 read registers and read memory. They have already established that the whole
signal path works. Stage 6 tests the route into memory; Stage 7 needs Stage 6. That is the only
thing blocked.

---

## 2026-07-29 (twenty-ninth pass) — Backups

New `BACKUP.md` and `tools/backup.ps1`.

The project is **78 MB**, half of it build output, so there is nothing to be selective about:

```powershell
.\tools\backup.ps1
```

writes one dated 35 MB zip into `C:\rp\prj\backups`. `-To E:\` sends it to a stick instead.

**A zip, not a folder, and deliberately so.** A loose folder copy of a Vivado project on the
same machine is a trap: sooner or later you open the backup by mistake, work in it for an hour,
and wonder why your changes keep disappearing. A zip cannot be opened in Vivado by accident.
`-WithFolder` if a browsable copy is genuinely wanted.

The destination defaults to a sibling of the project, and the script **refuses to write inside
it** — each backup would otherwise contain the previous one and they would grow without limit.
It stages a copy first so the zip is a still snapshot, warns if Vivado is open, and keeps the
newest ten. `-SourceOnly` drops the build outputs to 37 MB; keeping them means a restored copy
can be checked against the `0x48` fingerprint without rebuilding first.

`BACKUP.md` is explicit that a local backup covers a bad edit, a broken build or deleting the
wrong thing — the cases that have actually come up — but not a failed disk or a lost laptop.
Copy a zip elsewhere occasionally; the point of the local one is that it is cheap enough to run
several times a day.

The SD card is documented separately and deliberately second, because it matters less — it is
mostly a stock Red Pitaya OS plus a bitstream that can be rebuilt, whereas the project folder is
the only copy of the work. The card image is taken from the board with `dd | gzip` onto a stick
in its own USB socket, with a `split` variant for FAT32's 4 GB file limit.

One thing worth recording: the image is trustworthy because **this board mounts its root
read-only** — `ro` appears on the kernel command line Test Stage 6 prints. Nothing changes
underneath while `dd` reads. Imaging a live read-write filesystem this way would not be safe;
here it is.

`BACKUP.md` ends by putting the risk in proportion. Stages 1 to 5 only read. The single
operation in this project that can write outside its own hardware is Stage 6's memory writer,
now behind three independent guards, and the realistic worst case is a few corrupted kilobytes
and a reboot.

---

## 2026-07-29 (twenty-eighth pass) — Three guards before the writer is ever armed

Asked whether Stage 6 could be made safer. Yes — three independent guards now, none of which
existed before.

| Guard | What it catches | Cost |
|---|---|---|
| **Gap check** (already there) | refuses unless Linux demonstrably stops below the top of RAM | none |
| **Probe** (new) | writes a signature into the region from Linux, waits two seconds, reads it back. If anything is living there the pattern will not survive | 4 s |
| **4 kB trial capture** (new) | the first time the writer is ever armed it gets a window half a page wide, and the step checks it stopped inside that window before letting it near the full region | 0.2 s |

The probe is honest about its limits in the notebook: an intact pattern is strong evidence that
nothing is using the region *now*, not a guarantee that nothing will start. Only the reservation
gives that — it is a seat belt, not a substitute.

The trial capture is the one that bounds the damage. A wrong address costs 4 kB and a reboot
rather than 8 MB through a live filesystem, and the writer's own `MEM_CUR` register is checked
against the window before going further.

**Also:** `mem=496M` is now the suggested value (16 MB free, twice what the test needs) rather
than `mem=480M`, since the smallest change that works is the one least likely to disturb
anything. And a note that a `dd` image of the SD card takes ten minutes and makes the whole
question moot — worth doing once before the first armed capture.

### Why FIFO and DMA at all

Recorded here because it is the obvious question. The chain produces one 64-bit sample per
decimated clock:

| decimation | samples/s | bytes/s |
|---|---|---|
| R = 64 | 1.95 M | 15.6 MB/s |
| R = 1024 | 122 k | 0.98 MB/s |

Python manages about a thousand register reads a second. At R = 1024 that is **122 times too
slow**, and at R = 64 nearly two thousand times. Reading samples out through registers cannot
work for a continuous record, at any decimation this instrument uses — which is why the paper's
Fig. 6a has a FIFO and a memory writer, and why this does too.

The two blocks do different jobs. The **FIFO** absorbs the mismatch between a chain that
produces samples at a perfectly steady rate and a memory bus that accepts them in irregular
bursts, because the processor competes for the same path. The **memory writer** moves the queue
into RAM without the processor fetching each number. Both come from `axi_wr_fifo`, Red Pitaya's
own module — the one the stock oscilloscope uses for its long captures — rather than something
written here, which removes the largest single source of risk in the block.

---

## 2026-07-29 (twenty-seventh pass) — Stage 6 Step 1: a safe place to write

Step 1 stopped with *"NO mem= LIMIT FOUND"*. That was the right call for the wrong reason, and
the step has been rewritten.

### What the step is protecting against

The memory writer puts samples **straight into the board's RAM** through the processor's
high-speed memory port, at whatever physical address software gives it. It has no permissions,
no allocator and no bounds — it writes where it is told. Point it at memory Linux is using and
it overwrites a running program, a disk cache, or the kernel. The result is a crash, or silent
filesystem corruption.

So a region Linux has been told not to touch has to exist before the writer is ever armed.

**It is a boot setting, not an FPGA setting.** Nothing is rebuilt, no bitstream changes, no
Vivado. The addresses are ordinary register writes at run time.

### Why the old check was too narrow

It looked only for `mem=` on the kernel command line. That is one of two normal ways the region
exists; the other is a `reserved-memory` node in the device tree, which some images use instead.
A board set up that way is perfectly safe and would have been refused.

### The new check

It compares what Linux **actually claims** against what the board **actually has**:

| Source | Question it answers |
|---|---|
| `/proc/device-tree/memory/reg` | how much RAM is physically fitted — the device tree describes hardware, so it still reports 512 MB even when the kernel has been told to use less |
| `/proc/iomem`, highest `System RAM` | how far up Linux has claimed |
| `/proc/cmdline` | printed for information, no longer the deciding factor |

Anything between the two is free, however it came to be free. Verified against five board
states: no limit (refuses), `mem=480M` (offers `0x1E100000`–`0x1E900000`), `mem=256M`, a 16 MB
device-tree reservation, and a 4 MB reservation too small to use (refuses).

### And it now says how to fix it

A new markdown cell gives the procedure: find the boot file, **back it up first**, append
`mem=480M`, reboot, re-run. 512 MB fitted, so this leaves the top 32 MB — far more than the 8 MB
the test needs, and Linux will not notice.

It also says what to do if the board does not come back: the boot partition is FAT, so put the
card in a PC, restore the backup, done. That is why the backup step is not optional.

Setting `MEM_START` / `MEM_STOP` by hand is documented as the alternative, with the warning that
a wrong address here does not give a wrong answer — it corrupts whatever is living there — and
the requirement that it be 4 kB aligned, because the writer moves data in bursts from a page
boundary.

---

## 2026-07-29 (twenty-sixth pass) — A tolerance that was nine times tighter than the measurement

Stage 5 Step 3 reported a ratio of **1.005882** against a tolerance of **0.1 %**, and failed.

The tolerance was wrong. It came from the arithmetic — the coefficients sum to exactly 2¹⁷, so
the gain is exactly 1, so a tenth of a percent is surely generous. True of the *filter*, and it
says nothing whatever about the *measurement*.

### How precise is one of these readings, actually

Amplitude is estimated from the spread of ~1500 register reads. Simulated with the board's own
0.6 % per-sample noise and realistic `sleep()` jitter:

| beat frequency | 1σ on a ratio | why |
|---|---|---|
| 145 Hz | **0.06 %** | reads land at evenly spread phases and errors cancel |
| 500 Hz | 5.9 % | half the read rate: every read lands at nearly the same phase |
| 1831 Hz | **0.58 %** | past the read rate, so phases are effectively random |
| 5000 Hz | 0.89 % | as above |

Step 3 measured at u = 0.015, which is **1831 Hz**. So one reading was worth 0.58 %, and the
threshold was 0.1 %. It could only ever have passed by luck.

Both measurements to hand agree with the table exactly:

| | beat | error seen | 1σ from the table | |
|---|---|---|---|---|
| Stage 5b Test B | 145 Hz | 0.017 % | 0.06 % | 0.3σ |
| Stage 5 Step 3 | 1831 Hz | 0.588 % | 0.58 % | **1.02σ** |

A completely ordinary result failing an impossible test.

### Step 3 rewritten

| Change | Why |
|---|---|
| Measures at u = 0.001, about **120 Hz** | the precise column of the table. The designed gain there is 1.0000 to four decimal places, so it is still a gain-at-DC measurement in all but name — taken where measuring is ten times better |
| Repeats the ratio six times | |
| **Sets its own tolerance from the scatter it observes** | three times the standard error of its own readings. If conditions are good the test is strict; if they are poor it says so instead of pretending |
| Prints the spread and the tolerance | so the number can be judged, not just the verdict |

### Step 2's criterion moved to the right column

Its pass/fail was the flatness of the corrected curve — a max minus a min over 21 noisy points.
The range of 21 samples of anything is about 3.7 times its own scatter, so at ~1 % per point that
lands near 0.3 dB **however perfect the filter is**. It was measuring the sample count.

The decision is now the rms of the measured on/off response against the filter actually loaded.
That ratio is taken at one frequency, so droop, generator, cable and estimator bias all cancel;
it is the strict test and the only one that reflects the hardware. Flatness is still printed,
marked informational.

### Worth keeping in mind

**Never put a beat near half the read rate.** At 500 Hz the estimator is a hundred times worse
than at 145 Hz, because every read lands at nearly the same phase. Any future sweep should avoid
the neighbourhood of 500 Hz, 1000 Hz, 1500 Hz at a 1 ms read interval — or read at a different
interval.

---

## 2026-07-29 (twenty-fifth pass) — Checking the notebooks properly

```
NameError: name 'F_SIG' is not defined
```

When I replaced Stage 5b's measurement helpers I wrote over the whole cell — and that cell also
held `F_SIG`, `DEC`, `f_out`, and the block that reads the chip's current coefficients. The
replacement took the setup with it.

That is the third failure of the same kind in two days, and the previous check I added would
never have caught it: it verified that calls matched their functions, and this was a missing
*name*.

### What changed

**The setup block is now its own cell in 5b**, so a helper rewrite cannot take it. `F_SIG` sits
under the same "the one line you must edit" banner as everywhere else.

**`tools/verify_notebooks.py` now checks names as well as calls**, in the order the cells
actually run:

| Check | The real bug it would have caught |
|---|---|
| unknown keyword argument | `measure(..., gap=0)` when `measure` had no `gap` |
| wrong number of arguments | — |
| return unpacked into the wrong count | `a, _, _, _, _, _ = measure(...)` after it went from six values to five |
| **name used before anything defines it** | `F_SIG` |
| **function reaching for a name the notebook never defines** | found `report()` missing the moment the check was written — a fourth instance, before it reached the board |

It distinguishes a genuine forward reference (a function using a global that a later cell
creates, which is fine as long as it is not *called* first) from a name that simply does not
exist. Verified against all four real bugs plus a legitimate forward reference.

**It runs as part of `build_project.tcl`**, so it cannot be forgotten. And on demand:

```
python3 tools/verify_notebooks.py acquisition_custom/*.ipynb
```

All ten notebooks in the project now pass, and all ten flatten and compile.

### Why this kept happening

Every one of these was invisible on the page and certain to fail on the board, several minutes
into a test, at the one moment it mattered. A notebook has no compiler and no import step, so
nothing looks at it until it runs — and the only place it can run is the board. Editing them
from a PC without a checker was the actual problem; the individual mistakes were symptoms.

---

## 2026-07-29 (twenty-fourth pass) — The signal was there all along; the beat test was aliased

```
amplitude : 203 657 475 counts
```

That is the healthy level. **The generator is at 10 MHz, `F_SIG` is right, and the signal is in
the window.** What failed was the test that was supposed to confirm it.

### The beat test was measuring an alias

| | measured | should have been |
|---|---|---|
| reference at nominal | 144.9 Hz | 144.9 Hz ✓ |
| reference 1220.7 Hz lower | 445.9 Hz | 1365.6 Hz |

**The reads are themselves a sampling process, and they are slow.** Python manages roughly a
thousand register reads a second, so the beat measurement could never see anything above about
500 Hz — everything faster folds back and reads as something slower. At a read rate near 900 Hz,
1365.6 Hz folds to **434 Hz**; the measurement said 445.9.

So the two-point trick was doomed by construction: it deliberately moved the reference by
1220.7 Hz, which is more than twice what the method can see. It then compared the alias against
the real thing and correctly concluded they disagreed — about its own limitation.

### Replaced with phase, which cannot alias in the same way

The downconverted signal is a vector going round at the difference frequency, so its **angle**
advances at a constant rate and that rate *is* the difference. `offset_hz()` fits a straight
line to the angle against time and reads off the slope.

| | counting zero crossings | fitting the phase |
|---|---|---|
| Sign of the offset | impossible | free |
| I and Q read microseconds apart | n/a | a fixed lag adds the same constant to every angle and cancels in the slope |
| Is it a tone at all? | inferred, badly | the fit residual says so directly: a tone gives a few hundredths of a radian, noise gives about one |
| Needs a second measurement | yes | no |

The tone test is now that residual, which is both stricter and honest about what it can see. The
result is then confirmed by retuning to the frequency found and checking what is left is near
zero.

### The crash

```
TypeError: measure() got an unexpected keyword argument 'gap'
```

`find_generator()` was added in the same edit that was supposed to give `measure()` a `gap`
parameter. The guard on that edit was `'gap=0.001' not in cell`, and the cell already contained
`def read_I(n=1500, gap=0.001)` — so the guard was satisfied by the wrong line, `measure` was
left alone, and the two halves shipped out of step. My verification afterwards checked
`'gap=0.001)' in source`, which matched `read_I` too. A bad check confirming a bad edit.

### So it cannot happen again: `tools/verify_notebooks.py`

```
python3 tools/verify_notebooks.py acquisition_custom/*.ipynb
```

A notebook has no compiler and no import step, so nothing checks that a call matches the
function it calls — the failure surfaces on the board, minutes into a test. This reads every
code cell in order, collects the functions defined there, and checks every call for too many
positional arguments, unknown keywords, too few arguments, and return values unpacked into the
wrong number of names. It found one more instance the moment it was written
(`measure` unpacked into six names when it returns five). All eight notebooks now pass.

---

## 2026-07-29 (twenty-third pass) — The browser was running an old copy

Run from the browser, and the output contained:

```
WARNING: the two disagree. Generator drifting, or D too small?
```

That line **no longer exists** in this project. It was replaced hours earlier by a hard stop
reading *"These two do not agree, so this is not a tone."* The notebook on the board is an older
copy than the one on the PC.

**The notebooks on the board and the notebooks here are separate files.** The browser edits the
board's; this repository holds the master. Every edit made here since the last copy across is
invisible in the browser, and the board goes on running old code while you read new code. Same
shape of fault as the stale bitstream, in a different place.

`run_on_board.ps1` avoids it by copying the master over on every run — which is why its log
showed `require_signal` running and the browser's did not.

### The measurement itself is unchanged

| | reference at nominal | reference 1220.7 Hz lower | beat moved by |
|---|---|---|---|
| run 1 | 256.8 Hz | 279.5 Hz | +22.7 |
| run 2 | 243.2 Hz | 270.3 Hz | +27.1 |
| run 3 | 225.6 Hz | 180.5 Hz | −45.1 |

Required in every case: **+1220.7 Hz.** These are not drifting or degrading, they are the
zero-crossing rate of broadband noise, which wanders at random. There is no tone in the window.
With the board's copy still carrying `F_SIG = 1.0e6` against a 10 MHz generator, that is exactly
what should be seen.

### New: `acquisition_custom/find_signal.py`

Standalone, no notebook, no arguments:

```
sudo python3 find_signal.py
```

Sweeps the reference tone across 0.2–60 MHz, coarse to fine, and prints the frequency, the
amplitude in counts and in millivolts at the input, and the exact `F_SIG` line to paste. If it
finds nothing anywhere it says so and lists the five physical things to check, cable first.

It exists because a single test can never distinguish "no signal" from "wrong frequency" — both
give an empty window. Only a search can.

### Automation parked

`tools/` gains a README marking it optional and stating plainly that nothing depends on it. The
project is fully usable the plain way: browser for tests, `find_signal.py` and
`check_system.py` on the board, `build_project.tcl` in Vivado.

**`build_project.tcl` is deliberately NOT reverted.** Its fingerprint is what proved the
bitstream matched the source when the corrector fix appeared not to work; without it we were
guessing, twice, for a day. It adds one line of output to a build and takes nothing away.

---

## 2026-07-29 (twenty-second pass) — `F_SIG` was 1 MHz; the generator was at 10 MHz

The new gate stopped the run in seconds instead of two minutes, and it was right: 32 813 counts,
and the beat moved 27 Hz when the reference moved 1220 Hz. No signal.

But the cable was fine. **Stage 5 still carried the default `F_SIG = 1.0e6` while the generator
was at 10 MHz.**

| Notebook | `F_SIG` was | Result on the same cable, the same minute |
|---|---|---|
| Test Stage 5b | `10.0e6` | all four tests pass |
| Test Stage 5 | `1.0e6` | "no signal" |

I updated 5b's copy when I regenerated it and never updated Stage 5's. The measurement window is
±24 kHz out of a 62 MHz input range, so 9 MHz away is roughly 370 windows away: the decimator
removes the signal as thoroughly as unplugging the cable. **"No signal" and "F_SIG is wrong" are
the same symptom**, which is why nothing changed between running it from the browser and from
the command line — same notebook, same wrong number.

### Fixes

| Change | Detail |
|---|---|
| `F_SIG = 10.0e6` in Stages 3, 4, 5, 5b | one value, all four agree |
| A banner above that line | says it is the one line you must edit, and that a wrong value makes the signal vanish rather than weaken |
| **`find_generator()`** | when the gate trips, the reference tone is now swept across 0.2–60 MHz to *find* the signal, coarse to fine, and it prints the frequency to put in `F_SIG`. About ten seconds. A missing signal and a mistyped frequency now give different answers |
| `measure()` gains a `gap` argument | so the search can read flat out instead of at 1 ms a sample |

### Passwords, and the sudo delay

New `tools/setup_board_access.ps1`, run once:

- makes an SSH key on the PC if there is not one, and tells the board to trust it
- adds the board's own name to its `/etc/hosts` — this is the cause of
  `sudo: unable to resolve host rp-f007f7: Connection timed out` and of the pause before any
  output appears. It is only a logging lookup, it never affected a measurement, but it wastes
  seconds on every run
- sets the board's clock from the PC, so log timestamps stop reading June
- verifies with `BatchMode=yes` that passwords really are no longer needed

`run_on_board.ps1` now sends every file in a single `scp` rather than one per file, and checks
at the start whether key access works — if not, it says once where to fix it rather than
silently asking four times.

---

## 2026-07-29 (twenty-first pass) — Two minutes of numbers about nothing

First run through the new PC-side runner. Steps 1 and 1b pass; everything measured fails.

Amplitudes throughout: **~30 000 counts**. With the generator connected earlier the same day it
was **203 732 436**. That is 6800 times smaller — the noise floor. **Nothing was on the input.**

The proof is in the generator search, which had already printed it without stopping:

```
reference on the nominal frequency : beat    256.8 Hz
reference moved down by   1220.7 Hz : beat    279.5 Hz
```

A beat is the *difference* between the generator and the reference tone. Move the reference by
1220.7 Hz and the difference must move by 1220.7 Hz. It moved by **22.7**. A difference that
ignores one of the two things being differenced is not a difference: what was being measured was
broadband noise, whose zero-crossing rate is set by the filter, not by any tone. The consistency
check spotted it, warned, and carried on for another two minutes.

### `require_signal()` — added to Stages 5 and 5b

Two checks, run before anything else and stopping outright rather than warning:

| Check | Catches |
|---|---|
| **Size** — amplitude against a 2 × 10⁵ floor | nothing plugged in |
| **Behaviour** — move the reference by a known amount, the beat must move by the same | a signal outside the window, or a wrong `F_SIG`. Distinguishes "weak signal" from "no signal" without having to define how weak is too weak |

On failure it prints the four things to check, in order: generator output actually switched on,
cable in IN1, `F_SIG` matching the generator, level and input jumper.

Wired into **Step 1** of Stage 5, so a missing signal now costs seconds rather than a full run,
and the frequency it establishes is reused by the sweep. `signed_offset()`'s consistency warning
is now a stop as well.

### Two board-side annoyances seen in the log

| Symptom | Cause | Fix |
|---|---|---|
| `sudo: unable to resolve host rp-f007f7: Connection timed out` | the board's own name is not in its hosts file, so every `sudo` waits for a DNS timeout | on the board: `echo "127.0.0.1 rp-f007f7" >> /etc/hosts` |
| Log timestamps read 2026-06-13 | the board's clock is not set and has no battery | `date -s "2026-07-29 15:30:00"`, or leave it — the ordering is still right |

Neither affects any measurement.

---

## 2026-07-29 (twentieth pass) — Running the tests without a browser

Added `tools/run_on_board.ps1`. One command on the PC:

```powershell
.\tools\run_on_board.ps1 "Test Stage 5 - Droop Correction.ipynb"
```

It flattens the notebook into a plain script, copies it to the board, runs it there over SSH as
administrator, and copies the output back into `results\` as a log plus a PNG per plot.

**Why.** The tests must *run* on the board — they read the chip's registers through `/dev/mem`,
which exists nowhere else — but they do not have to be *operated* from the board's web page.
Every result in this project so far has been read off a browser tab and pasted by hand. As files
in the repository they can be kept, diffed between runs, and read directly by anyone helping.
Editing was never restricted: a notebook is a text file.

| File | Job |
|---|---|
| `tools/run_on_board.ps1` | The one command. Options for board name and user; explains SSH keys if you tire of typing the password |
| `tools/nb_to_script.py` | Notebook to script. Switches matplotlib to a file backend and turns every `plt.show()` into a numbered PNG, so plots survive having no screen |
| `results/` | Where logs and figures land. Purely output; safe to empty |

### PowerShell 5.1, not 7 (fixed same day)

First run failed to start at all:

```
Unexpected token '??' in expression or statement.
```

`??` is PowerShell 7 syntax and Windows ships **5.1**. Worse, it is a *parse* error, not a
runtime one — the script never loads, so the reported line number is where the parser gave up
rather than where anything went wrong.

| Fix | Detail |
|---|---|
| Python lookup rewritten | A plain `foreach` over `python`, `python3`, `py`. The whole script is now 5.1 syntax |
| Version guard at the top | Says so plainly, with a comment telling anyone editing it to keep to 5.1 and why parse errors mislead |
| Figure copy made optional | `scp` complains when its pattern matches nothing, which is normal for a notebook with no plots. Wrapped so it cannot stop the script one line before it reports where results were saved |
| Execution-policy note in the header | "running scripts is disabled on this system" is Windows' default, not a fault. Both ways round it are given |

**One subtlety worth recording.** Stripping notebook magics naively breaks wrapped format
strings, because `%` starts a magic *and* is Python's formatting operator:

```python
print('%d of %d'
      % (a, b))      # <- this line starts with %
```

Blanking that line yields a file that looks right and will not compile. `strip_magics()` tracks
bracket depth and requires a letter after the `%` or `!`, so a continuation is never mistaken
for a magic. All ten notebooks in the project now flatten and compile.

---

## 2026-07-29 (nineteenth pass) — Stage 5 Step 2: the test was measuring itself

All four of Stage 5b's tests pass. Stage 5 Step 2 still failed, with a jagged pair of curves.
The answer was in the column nobody had looked at.

### The `on/off` column already said the filter was correct

It is the two runs divided at the **same** frequency, so the droop, the generator, the cable,
the converter and any bias in the amplitude estimate all cancel. What is left is the correction
filter's own response:

| u | measured on/off | designed | error |
|---|---|---|---|
| −0.240 | 0.704 | 0.653 | +0.051 |
| −0.199 | 1.337 | 1.298 | +0.039 |
| −0.158 | 1.168 | 1.180 | −0.012 |
| −0.117 | 1.132 | 1.095 | +0.037 |
| −0.076 | 1.028 | 1.039 | −0.011 |
| −0.035 | 1.000 | 1.008 | −0.008 |
| 0.015 | 0.999 | 1.001 | −0.002 |
| 0.056 | 0.997 | 1.021 | −0.024 |
| 0.138 | 1.162 | 1.134 | +0.028 |
| 0.179 | 1.219 | 1.237 | −0.018 |
| 0.220 | 1.086 | 1.111 | −0.025 |

**rms 0.027** (one outlier at u = +0.097 excluded, see below). The corrector reproduces its
designed response point by point.

### What corrupted the two curves separately

Stage 5 was still measuring `|I + jQ|`. Stage 5b was moved off that on 2026-07-29; Stage 5 was
not. It needs **two** register reads, microseconds apart, and a new sample arrives every 8 µs —
so the two often come from different samples. Simulated:

| offset u | one sample apart | two samples apart |
|---|---|---|
| 0.015 | −0.005 dB, 3% jitter | −0.019 dB, 7% jitter |
| 0.076 | −0.120 dB, 17% jitter | −0.454 dB, 33% jitter |
| 0.158 | −0.495 dB, 35% jitter | −0.638 dB, 40% jitter |
| 0.240 | −0.896 dB, 48% jitter | |

The measured spread column ran 8.7% to 39.4%, growing with offset. That matches.

**The artefact is a sag of a decibel or so towards the edges of the window, growing with
offset — which is precisely the shape of the thing being measured.** The test was measuring
itself. It cancels in `on/off`, which is why that column was clean, and does not cancel in
either curve alone, which is why both were jagged.

The single outlier at u = +0.097 follows: `off` read −2.133 dB there while u = +0.138 read
−1.721 dB — more droop *nearer* the centre, which droop cannot do. One bad reading, which then
inflated that point's ratio to 1.361.

### Changes to Test Stage 5

| Change | Detail |
|---|---|
| One register, not two | `read_I` + `amplitude()` lifted from Stage 5b. The artefact disappears entirely |
| 1500 reads per point | was 96. Statistical error on a ratio falls from ~2.9% to ~1.3% |
| Finds the generator first | `signed_offset()`, so the sweep frequencies are the ones actually applied |
| New `on/off` and `designed` columns | printed side by side, and an rms quoted against the loaded filter. This is the strict test and is now the one the failure message points at first |
| Tolerance 0.35 dB | honest for this estimator, rather than 0.10 dB which was below its own precision |

The long comment at the top of the measurement cell records the artefact table, so the next
person does not have to rediscover why `|I + jQ|` is not used here.

---

## 2026-07-29 (eighteenth pass) — **The corrector works.** Both remaining failures are the test

Stage 5b run against the fixed bitstream. Tests A and B pass. Test D:

| u | measured | predicted | error |
|---|---|---|---|
| 0.000 | 1.0005 | 1.0000 | +0.0005 |
| 0.050 | 1.0142 | 1.0165 | −0.0023 |
| 0.100 | 1.0566 | 1.0682 | −0.0116 |
| 0.150 | 1.2179 | 1.1608 | +0.0571 |
| 0.200 | 1.2811 | 1.2993 | −0.0182 |

The droop corrector reproduces its designed response. The unsigned pre-add was the whole fault.

### Test C — the shape was right, the frequency axis was not

Measured gains are now all ≤ 1, as two taps of ½ require. And they repeat exactly one comb
period apart:

| u pair, one period (1/308) apart | measured |
|---|---|
| 0.0000 / 0.0033 | 0.7612 / 0.7945 |
| 0.0008 / 0.0041 | 0.9934 / 0.9929 |
| 0.0016 / 0.0049 | 0.6662 / 0.6681 |

Repeatable to 2%, with period exactly 1/308. **The two taps are 308 samples apart and the
pre-add is sound.** Fitting one free frequency offset gives a residual of **0.014** — the comb
matches theory to 1.4%. The offset it needs is **+305.9 Hz**.

The measured beat was 153.6 Hz, and the notebook *subtracted* it: 2 × 153.6 = **307.2 Hz**.

`beat_hz()` counts zero crossings, which gives the **size** of the gap between generator and
reference but never its **sign** — one real channel cannot tell clockwise from anticlockwise.
Subtracting a gap whose sign you guessed wrong does not cancel it, it doubles it. And 307 Hz is
**77% of the two-tap comb's entire period** (397 Hz), so the frequency axis was scrambled.

**Fix — `signed_offset()`.** Measure the beat twice: once with the reference on the nominal
frequency, once with it moved down by a known D larger than any plausible gap. The second beat
is then |δ + D| = δ + D, because δ + D cannot be negative, so **δ = beat₂ − D**, signed. Every
frequency in the notebook is now worked out from the generator's true position, and the offset
is printed in Hz and ppm. Test C also fits the shape as a backstop and says explicitly when the
shape is right and only its position is off.

### Test D — the threshold was tighter than the measurement

Each reading estimates an amplitude from the spread of N asynchronous samples of a sine, so it
carries a statistical error of about 1/(2√(2N)); a ratio of two carries √2 times that.

| reads | 1σ on a ratio | on a gain of 1.2 |
|---|---|---|
| 300 (what was used) | 2.9% | **0.035** |
| 1500 (now) | 1.3% | 0.016 |

The single failing point was 0.0571 out — **1.6σ**. Noise, not a fault. Reads raised to 1500 and
the tolerance now computed from that precision and printed, so the threshold tests the hardware
rather than the sample count.

### Where this leaves the acquisition system

The signal path is verified end to end in hardware: reference tone, frequency shift, decimation,
and now droop correction. Test Stage 5 should follow. Remaining: Stages 6 and 7 (the path into
memory), trigger synchronisation with the feedback sequencer, and the XADC clocking note.

---

## 2026-07-29 (seventeenth pass) — The measured gain *is* the diagnosis

Stage 5b re-run after a fresh build. Same failure. But the numbers name the cause exactly.

Baseline amplitude (correction bypassed): **203 732 436**.

| Quantity | Value |
|---|---|
| 2³¹ ÷ baseline | **10.54** |
| √2 × 2³¹ ÷ baseline (a fully square output) | **14.91** |
| Test C measured gains | 10.34, 2.21, 9.93, **14.63**, 10.17, 2.34, 10.66 |

Four of the seven points sit on 10.54 and the largest sits on 14.91. **The output is not
showing a gain — it is pinned at the 32-bit limit**, with the spread coming from how much of
each cycle is clipped.

Work backwards. To reach `scaled` = 2³¹ with a coefficient of 65536 = 2¹⁶:

```
scaled = pair x coef / 2^17  =  2^31    =>    pair = 2^32
```

2³² is precisely what is left behind when one negative 32-bit sample is zero-extended instead
of sign-extended. **The pre-add is still unsigned in the logic that is running.** The fix of the
fifteenth pass is in the source and is correct; it is not in the chip.

Two taps of gain ½ cannot exceed a gain of 1 under any wiring, coefficient or addressing error.
There is no filter fault that produces these numbers. Only overflow does.

### Hardening

| Change | Detail |
|---|---|
| Stage 5b, new first cell | Reads the build fingerprint at `0x48` and **refuses to run** if it is zero or disagrees with `bitstream_id.txt`. Every wrong answer this notebook has produced was a correct answer about the wrong bitstream |
| Stage 5b, Test C | Recognises this failure by its arithmetic. If the measured gains cluster on 2³¹ ÷ baseline it says so, names the unsigned pre-add, and says the chip is running pre-fix logic |

Recording the signature, because it is worth recognising on sight:

> **A "gain" that equals 2³¹ divided by the input amplitude is not a gain.**
> It is a 32-bit register at its limit.

---

## 2026-07-29 (sixteenth pass) — The fix was never in the bitstream

Stage 5b was re-run after the pre-add fix and failed in exactly the same pattern: **B passed,
C railed, D railed off-centre.** That is the unfixed signature, unchanged.

It was the unfixed signature because the chip was running unfixed logic.

| File | Timestamp |
|---|---|
| `red_pitaya_acq_fir.v` (the fix) | 29 July **13:01** |
| `Test_Project.runs/synth_1/red_pitaya_top.dcp` (the netlist) | 28 July **19:34** |
| `Test_Project.runs/impl_1/red_pitaya_top_routed.dcp` | 28 July **19:40** |
| `Test_Project.runs/impl_1/red_pitaya_top.bit` | 29 July **13:36** |

`impl_1/runme.log` opens the 29 July run with `Command: link_design`, which reads the
**synthesised checkpoint** — the one from the previous evening. Implementation re-ran; synthesis
did not. The bitstream file was newly written, newly dated and byte-different from the old one,
and the logic inside it was a day old.

The cause is that the source was edited outside Vivado while the project was open. Vivado
caches which files it has seen, did not notice, left `synth_1` marked Complete, and
**Generate Bitstream** in the graphical interface built happily from the stale netlist without
warning. `build_project.tcl` has always done `reset_run synth_1` and would not have done this.

**This is the second time this class of fault has cost this project a day**, and the first
(an old bitstream copied to the board) was already called out in `START_HERE.md`. Warnings in
documentation are evidently not enough, so the chip now answers the question itself.

### Build fingerprint — new register `0x48`

`build_project.tcl` hashes every Verilog source in both subsystems, writes the result into
`build_id.vh`, and synthesis bakes it into the bitstream. Software reads it back at `0x48`.

| Situation | What you see |
|---|---|
| Built by `build_project.tcl` | `check_system.py` prints `Build fingerprint 0x…` |
| Built by pressing Generate Bitstream | `0x48` reads **zero** — that path does not regenerate `build_id.vh`, and `check_system.py` says so and tells you to rebuild properly |
| Old bitstream on the board | the fingerprint disagrees with `bitstream_id.txt`, written next to the bitstream at build time |

A file date says when a bitstream was written. The fingerprint says what is inside it. Those
are different questions, and only the second one matters.

### Also

| Change | Detail |
|---|---|
| `build_project.tcl` | `reset_run impl_1` as well as `synth_1`; a comment saying why the decision is taken away from Vivado |
| `build_project.tcl` | Post-build check: if any source file is newer than the netlist, it prints **STALE NETLIST**, lists the files, and refuses to call the build a success |
| `build_project.tcl` | Writes `bitstream_id.txt` beside the bitstream. Copy it to the board with the bitstream |
| `add_acquisition_sources.tcl` | Adds `build_id.vh` as a Verilog Header |
| `check_system.py` | Reads and checks the fingerprint before anything else |
| Stage 5 Step 1b | Its "coefficients do not match" message now names Test Stage 5b as a cause. A single non-zero tap at position 0 is 5b's Test C left resident — which is exactly what it caught this time, correctly |

**The pre-add fix itself is unchanged and still needs a real build.** Nothing in the fifteenth
pass has yet run on hardware.

---

## 2026-07-29 (fifteenth pass) — **ROOT CAUSE FOUND**: the pre-add was unsigned

Test Stage 5b located it in four measurements. **REBUILD REQUIRED.**

| Test | Result | What it means |
|---|---|---|
| A — all zeros | **PASS**, output exactly 0 | accumulator, strobe and output latch are sound |
| B — centre tap only | **worked** (output tracked the input; the pass criterion was broken, not the hardware) | multiply, accumulate, output shift are sound |
| C — first tap only | **railed at ±2147483647** | two taps of gain 1 cannot exceed a gain of 2. This is not a filter shape, it is overflow |
| D — designed filter | railed | same fault |

B and C differ in exactly one thing. The centre tap is the only tap with no partner, so it is
the only one that skips the **pre-add**. B passed without it; C railed with it.

### The fault

`red_pitaya_acq_fir.v`, stage 2, read:

```verilog
pair <= is_centre_1 ? {rd_a[DW-1], rd_a} : (rd_a + rd_b);
```

In Verilog a **concatenation is always unsigned**, and one unsigned part makes an entire
expression unsigned — every operand in it is then zero-extended instead of sign-extended. The
braces on the left of the colon reached across and turned the addition on the right into an
**unsigned** addition.

Zero-extending a negative 32-bit number adds 2³² to its value. So:

| rd_a | rd_b | wanted | got |
|---|---|---|---|
| −1000 | −2000 | −3000 | −3000 — the two extra 2³²s make 2³³ and fall off the top of a 33-bit result |
| +1000 | +2000 | +3000 | +3000 — nothing to extend |
| −1000 | +2000 | +1000 | **−4294966296** — one 2³² left behind |

One tap pair straddling zero contributed an error of 2³² — about a hundred thousand times a
normal sample — and buried the sum.

### Why it looked like a wrong filter for so long

At the centre of the measurement window the signal barely moves, every sample held by the
filter has the same sign, no pair straddles zero, and the filter is **correct**. Move off
centre and the signal changes sign within the window; the further off, the more pairs straddle
zero. The result was a gain that rose smoothly with offset frequency and an output that
fluctuated from sample to sample as the sign pattern shifted — indistinguishable, from the
outside, from a filter with the wrong coefficients.

It also explains every earlier dead end: the coefficient file was right, the readback was
right, the timing was clean, the build was current, and the cycle-accurate model was right —
**because the model was written in Python, whose integers are signed and unlimited.** It
modelled the intent, not the language. That is the whole lesson.

### The fix

```verilog
if (is_centre_1) pair <= rd_a;            // signed -> wider signed: sign-extends
else             pair <= rd_a + rd_b;     // both signed, so the sum is signed
```

`if`/`else` instead of `?:` keeps the braces out of the arithmetic entirely. A plain assignment
from a signed value to a wider signed target sign-extends by itself. A 40-line comment on the
block says why, and says not to tidy it back.

**Audit:** this was the only conditional expression in the acquisition system mixing a
concatenation with signed arithmetic. The manual sign extensions in `red_pitaya_acq_cic.v`
(`dat_ext`) and `red_pitaya_acq.v` are assigned to `wire signed` targets and are correct.

### So it cannot happen again

`validate_fir.py` gains **check 5**, which works in Verilog's rules rather than Python's. It
reproduces both readings of the expression, prints the 2³² divergence on mixed signs, and then
refuses to pass if the RTL contains the broken form. Checks 1–4 all passed throughout the fault
— they had to, since they model the intent.

### Test Stage 5b corrections

| Was | Now |
|---|---|
| Loaded 131072 for "gain 1" | 131072 does **not fit** an 18-bit signed field — it reads back as −131072, which is why Test B reported nonsense. Tests use **65536, gain ½**, and `write_coeffs` now refuses out-of-range values with an explanation |
| Assumed a stationary baseband | The generator and the board are separate crystals, a few parts per million apart — tens of hertz at 10 MHz. The baseline now **measures the residual beat** and reports it in Hz and ppm; every comparison uses amplitude, which does not care |
| Compared means | Compares amplitudes, and reports whether the output is railing — the single most diagnostic fact |
| No signal check | Refuses to proceed if the input is at the noise floor. In the run that found this fault the generator was off for tests B–D, and the tests still gave the right answer, but that was luck |

---

## 2026-07-29 (fourteenth pass) — New Test Stage 5b, known-answer filter tests

The rewritten Stage 5 removed the zero-offset trap and the numbers improved, but the corrected
curve is still wrong, and one reading in the new diagnostic settles what kind of fault it is:

> With the reference tone exactly on the signal, the decimator's output is **constant** —
> measured spread 0.6%. The same constant through the correction filter came out with a spread
> of **74.6%**.

A filter cannot give a varying answer to an unvarying input. So this is not a wrong filter, it
is a filter reading something that changes between passes.

### What was eliminated

| Checked | Result |
|---|---|
| The module, simulated cycle by cycle | Written as a bit-exact model of the Verilog — registers, strobes, pipeline, accumulator clear — and driven with the real coefficients. Constant in → **exactly** that constant out, for ever. Gains at u = 0.06 / 0.12 / 0.20 come out 1.024 / 1.100 / 1.299, the designed inverse droop |
| Implementation timing | WNS **+0.248 ns**, 0 failing endpoints of 27338, hold clean. Not a timing fault |
| Build currency | Sources 19:24–19:25, synthesis 19:34, bitstream 19:42 the same evening. The build is current |
| Synthesis mapping | Sample history replicated into two block RAMs (`dbuf_reg_1`, `dbuf_reg_2`) — the correct way to serve one write and two reads. Coefficients one 155 × 18 dual-port block RAM per channel. The 33 × 18 multiply built as a two-slice cascade |
| Coefficient file | Exactly symmetric, sum exactly 131072 |

### The new notebook

`Test Stage 5b - Known Answer Filter Tests.ipynb` stops measuring the filter through a signal
and instead **loads filters whose answer is known in advance**:

| Test | Loaded | Must produce | A failure means |
|---|---|---|---|
| A | all zeros | exactly zero | the accumulator is not cleared between passes, or the output is latched mid-pass |
| B | centre tap = 131072 | the input unchanged | the multiply, the accumulate or the output shift is wrong |
| C | first tap = 131072 | 2·\|cos(308πu)\| — two taps 308 apart | the sample history is addressed wrongly |
| D | the designed filter, written by software | flat response | the coefficients baked into the bitstream are not the designed ones |

Test C is the one aimed at the leading suspicion. It is the only test that exercises the
circular buffer's addressing against a shape steep enough to see: 308 samples is a long lever,
so the gain swings from 2 to 0 within 0.3% of the output rate.

**Also:** measurements now read `PEEK_I` alone rather than |I + jQ|. The magnitude needs two
register reads microseconds apart, and at high offset they land on different samples — which is
why the old spread column grew in proportion to offset frequency regardless of the filter. A
single register removes that artefact entirely. Amplitude is recovered with
`sqrt(mean² + 2·variance)`, which gives the mean for a standing signal and √2 × spread for a
rotating one, with no special case at zero.

---

## 2026-07-29 (thirteenth pass) — Test Stage 5 rewritten; the zero-offset trap

Stage 5 Step 2 reported the corrected curve at **+22 to +31 dB** where it should be flat to
0.04 dB. Ruled out, with evidence:

| Checked | Result |
|---|---|
| `fir_coeffs.txt` / `fir_coeffs.vh` | 309 taps, exactly symmetric, sum exactly 131072 → gain at DC exactly 1. Response × sinc⁴ droop = **0.043 dB** across the band |
| The filter module's arithmetic | Pipeline traced cycle by cycle: coefficient, sample pair and accumulator all line up; the last tap lands before the output is latched |
| Seven plausible mis-wirings | Centre tap doubled, centre tap dropped, pre-subtract instead of pre-add, address off by one, coefficient lagging the data. **None** produces the measured shape — the closest is 19 dB away from it |
| The synthesis log | Coefficient memory inferred as one 155 × 18 dual-port block RAM per channel, sample history as a true dual-port RAM, the 33 × 18 multiply built as a two-slice cascade. All as intended |

So the filter is arithmetically incapable of the reported error, and the fault lies either in
what the chip's memory contains or in how Step 2 measured. **The test had a real flaw**, and
it was at exactly one sweep point.

### The zero-offset trap

Every mixer leaves a small steady offset on I and Q — its own rounding, converter zero error,
reference-tone leakage. Normally harmless: the wanted signal spins round at the offset
frequency while the artefact sits still, so averaging the magnitude ignores it.

At **exactly zero offset the signal stops spinning.** It becomes a steady value too, added
vectorially to the artefact and inseparable from it. The reading can be anywhere between
|A| − |d| and |A| + |d|, and drifts while you watch. Step 2 measured there, then **divided
every other point by that one reading** — turning a fraction of a decibel into thirty.

### What changed

| Change | Detail |
|---|---|
| **New Step 1b** | Reads all 155 coefficients out of the chip and computes their true response. Answers "does the chip hold the intended filter?" directly, depending on no signal and no measurement |
| Sweep skips the centre | Points run from ±0.015 outwards; no reading is taken at zero offset |
| No division by one point | "Variation across the band" is a max minus a min and needs no reference. The plot's zero line comes from a fit through the whole curve |
| Step 3 moved off DC | Gain-at-DC check now uses the two points nearest the centre, where droop and correction are each under 0.002 dB |
| `peek_mag` returns the spread | An unstable reading now shows itself. The diagnostic cell prints it and says what it means |
| Predicted droop computed | From the actual sweep points rather than quoting the band-edge figure |

**Still open:** whether the chip holds the right coefficients. Step 1b answers it. Note that
the FIR Filter Designer writes to the same memory and its changes persist until the bitstream
is reloaded — if it has been used since the last reload, reload before running Stage 5.

---

## 2026-07-28 (twelfth pass) — Readback sign bug in the designer notebook

The first run of the new designer reported **41 of 155 coefficients "did not read back
correctly"**, e.g. *wrote −1, read +4294705151*, and a resulting window gain of 2686813
instead of 1.

**The hardware was right. The notebook was wrong.** Two separate mistakes, both mine:

| Symptom | Cause | Fix |
|---|---|---|
| 41 coefficients fail readback | The notebook undid an **18-bit** sign, but `red_pitaya_acq.v` already sign-extends to 32 bits before returning the value (`sys_rdata <= {{14{coef_rdata[17]}}, coef_rdata};`). A stored −1 therefore arrives as `0xFFFFFFFF`, not `0x3FFFF` | New `s32()` helper tests bit 31 and subtracts 2³², used in both the verify loop and the readback section |
| Several hundred numbers printed after every call | `describe()` returned a tuple, which Jupyter echoes | Split into `curves()` (returns the arrays) and `describe()` (prints, returns `None`) |

The arithmetic that settles it: 4294705151 + 2¹⁸ = 4294967295 = `0xFFFFFFFF` = −1 as a 32-bit
signed number. Every "wrong" value was off by exactly 2¹⁸ — the signature of a sign undone at
the wrong width. And `fir_coeffs.txt` contains **exactly 41 negative coefficients** among the
155 stored. 41 negatives, 41 failures, no other value affected.

**Consequence:** the readback diagnostic is only now trustworthy, so the Test Stage 5 question —
does the chip hold the intended filter? — is still open, but is now answerable in one cell.

**Also:** the notebook is renamed `FIR Filter Designer.ipynb`; `START_HERE.md` and
`acquisition_custom/README.md` point at the new name.

---

## 2026-07-28 (eleventh pass) — Filter coefficients writable at run time

Changing the correction filter used to mean editing a Python script on a PC, running it,
rebuilding for 25 minutes, and reloading the board. For a two-number change to a passband that
is a heavy price, and it makes experimenting with the filter something nobody does.

The coefficients now live in a **writable memory** reachable from software.

| Change | Detail |
|---|---|
| `red_pitaya_acq_fir.v` | Coefficient store is a RAM rather than a ROM, with a second port for software. Initial contents still come from `fir_coeffs.vh`, so the board powers up with the designed filter |
| `red_pitaya_acq.v` | New registers `0x40` (which coefficient) and `0x44` (write / read it). Both filter instances share the write port, so I and Q cannot diverge |
| New `Filter Designer.ipynb` | Set passband and stopband, see the response plotted against what is currently loaded, write it to the chip in about a second, verified coefficient by coefficient |

**Cost:** none in the signal path. Block RAM has two ports and the filter only ever used one,
so the software port is free. No extra logic between input and output.

**What it does not change:** the number of taps. That is built into the wiring — the address
generator, the pipeline, the bypass threshold — not into the numbers. Changing it still needs
a rebuild, and the notebook says so plainly.

### The readback matters more than the writing

`0x44` reads back **what the chip actually holds**, which is a different thing from what it was
supposed to hold. The Test Stage 5 investigation stalled precisely because there was no way to
tell those apart: the RTL was provably correct, the file was in the project, and the measured
response still did not match. Section 1 of the new notebook answers that question directly, by
reading all 155 values out and computing what filter they make.

Any future "the filter is not behaving" question now starts with a definite answer rather than
an inference.

---

## 2026-07-28 (tenth pass) — Made the project handover-ready

The project will pass to people who did not build it and may not have a hardware background.
Three additions, none of which touch the datapath, so performance is unchanged.

### `START_HERE.md` — one entry point

Previously a newcomer faced a folder of files with no obvious way in. This is the way in:
what the thing does in one picture, the two-machines warning up front, a "what do you want to
do?" routing section, a map of the folders, five traps stated plainly, and a glossary of every
term used anywhere in the project.

### `check_system.py` — "is it working?"

```
sudo python3 check_system.py
```

Ten seconds on the board. Answers five questions in plain English — is the right bitstream
loaded, is the acquisition system responding, is anything flagged, what is it set to, is it
producing samples — and every non-OK result is followed by what to do about it.

The first check matters most: loading an old bitstream looks exactly like success, and has
already cost an hour on this project once.

### `build_project.tcl` — one command to build

```tcl
source C:/rp/prj/v0.94/Test_Project/build_project.tcl
```

Replaces a five-step sequence that had to be done in the right order, followed by reading two
reports correctly. It checks the generated filter files are current, adds sources, builds,
interprets the timing result, reports how full the chip is, and says what to do next.

**The staleness check is the valuable part.** If someone edits `gen_fir_coeffs.py` and forgets
to run it, the chip would be built with the old coefficients and nothing would complain. The
script now stops with an explanation.

Most mistakes on this project were a skipped step, not a design error. These three address
that directly.

---

## 2026-07-28 (ninth pass) — Filter sizes made a single source of truth

Prompted by the question "what is the pipeline if the number of coefficients changes?", which
exposed a genuine hazard: **`NTAPS` was written out in four places that had to agree**, with
nothing enforcing it —

| Place | What it controlled |
|---|---|
| `gen_fir_coeffs.py` | the coefficients themselves |
| `red_pitaya_acq_fir.v` | the hardware that uses them |
| `red_pitaya_acq.v` | the decimation below which the filter is bypassed |
| `validate_fir.py` | the check that is supposed to catch mistakes |

A mismatch between any two does not fail loudly. It produces a filter that builds, runs, and
gives wrong answers — the worst category of fault in this project.

### Fix

The generator now also writes **`fir_params.vh`**, and everything reads from it:

```
gen_fir_coeffs.py ──▶ fir_params.vh ──┬──▶ red_pitaya_acq_fir.v
                                      ├──▶ red_pitaya_acq.v
                                      └──▶ validate_fir.py
```

| Change | Detail |
|---|---|
| New generated file `fir_params.vh` | `GEN_NTAPS`, `GEN_NHALF`, `GEN_COEFW`, `GEN_COEF_FRAC`, `GEN_MIN_DEC_LOG2` |
| `red_pitaya_acq_fir.v` | `NTAPS`, `COEFW`, `COEF_FRAC`, `NHALF` are now localparams derived from the include, not module parameters |
| `red_pitaya_acq.v` | Bypass threshold is `GEN_MIN_DEC_LOG2` rather than a hard-coded `4'd8` — raising the tap count now raises the threshold automatically |
| `validate_fir.py` | Parses `fir_params.vh` instead of repeating the numbers |
| `red_pitaya_acq_fir.v` | **Build-time check**: if `DEPTH < NTAPS` the elaboration fails with `ERROR_fir_DEPTH_must_be_at_least_NTAPS_see_gen_fir_coeffs_output`. Previously the circular buffer would have silently wrapped and the oldest taps read the wrong samples |
| `gen_fir_coeffs.py` | Prints the hardware requirements it implies: multiply-accumulates per sample, minimum decimation, required `DEPTH` |
| `add_acquisition_sources.tcl` | Adds `fir_params.vh` as a Verilog Header too |

The only manual step left when changing the tap count is `DEPTH`/`ABW` if the filter grows past
512 taps — and that one now fails the build rather than passing quietly.

Documented in `acquisition_custom/README.md` under "Changing the correction filter", including
what a `.vh` file actually is and why it is never compiled.

---

## 2026-07-28 (eighth pass) — Every build warning characterised

Systematic pass over the synthesis and implementation logs. Each message classified as
**mine**, **stock Red Pitaya**, or **normal tool noise**, and each of mine fixed.

### Fixed — all three were mine

| Message | Cause | Fix |
|---|---|---|
| `[Designutils 20-1307] Command 'if' is not supported in the xdc constraint file` | The guard I added last pass used a Tcl `if`. An XDC file is a **restricted subset of Tcl with no control flow**, so the whole guarded block was discarded — the same silent failure the guard was written to prevent | Moved the constraint to `red_pitaya_impl.xdc`, marked *not used in synthesis*. No conditional needed |
| `[Designutils 20-1567] set_multicycle_path with -hold is not supported by synthesis` | The ADC hold multicycle sat in a file synthesis reads. Hold analysis only happens at implementation, so synthesis rightly ignored it — but said so every build | Moved to the same implementation-only file |
| `[Synth 8-693] zero replication count` ×4 at `red_pitaya_acq.v:476` | Sign extension written as `{{(32-DWC){x[DWC-1]}}, x}`. `DWC` is already 32, so that asks for **zero** copies of the sign bit | Assign to a wider **signed** wire instead, which sign-extends by the language's own rules whatever the widths. Shorter, cannot produce a zero-width replication, and survives any future width change |

The `if`-guard episode is worth recording as a pattern: **three successive attempts at the same
constraint each failed silently in a different way** — wrong clock names, then too many
positional arguments, then unsupported control flow. In every case the file looked correct and
the constraint did nothing. The only reliable check is reading the log for `12-627`, `12-4739`,
`17-165` and `20-1307`.

### New file

`constrs_1/.../sdc/red_pitaya_impl.xdc` — the two constraints that can only be evaluated once
the processing system has been elaborated. `add_acquisition_sources.tcl` adds it and sets
`used_in_synthesis false`.

### Characterised, no action — stock Red Pitaya or normal tool noise

| Message | Why it is expected |
|---|---|
| `[Synth 8-7071]` unconnected port (×52) | Optional ports on the pre-built processor blocks. Normal |
| `[Synth 8-7023]` connections declared vs given | Same thing, differently worded |
| `[Synth 8-689]` `S_AXI_HP2_bid` width 6 vs 4 (×10) | On memory ports **HP2/HP3, which are not connected to anything**. The mismatched signals are transaction ID tags nothing reads |
| `[Vivado 12-584]` No ports matched `''` | A constraint belonging to a block compiled in isolation |
| `[Timing 38-316]` XADC compiled for 10 ns, driven at 5 ns | Genuine, but inside the block design and outside the measurement path. Monitors chip temperature and supply rails only. **Still outstanding** |
| `[Constraints 18-5210]` No constraints selected for write | Informational |
| `[Common 17-576]` `use_project_ipc` deprecated | Cosmetic |

---

## 2026-07-28 (seventh pass) — Blocks 3 and 4 built; Test Stages 5–7

Stages 1–4 passed on hardware, so the remaining two blocks were written and the chain
completed.

### New files

| File | Purpose |
|---|---|
| `rtl/classic/red_pitaya_acq_fir.v` | Block 3, droop corrector |
| `rtl/classic/red_pitaya_acq_dma.v` | Block 4, packing + buffering + memory streaming |
| `rtl/classic/fir_coeffs.vh` | **Generated** coefficients, included by the filter |
| `acquisition_custom/gen_fir_coeffs.py` | Designs the filter and writes the two files above |
| `acquisition_custom/fir_coeffs.txt` | The same coefficients as plain text |
| `acquisition_custom/validate_fir.py` | Bit-accurate check of block 3 |
| `acquisition_custom/EXPLAINER.md` | Plain-English guide, moved out of the README |
| `Test Stage 5 - Droop Correction.ipynb` | Before-and-after sweep of the window |
| `Test Stage 6 - Data Transport to Memory.ipynb` | Counting pattern, every sample checked |
| `Test Stage 7 - End to End Measurement.ipynb` | Known signal, full chain |

### Block 3 — droop corrector

309 taps, matching the paper. Achieved (from the generator's own report):

| | |
|---|---|
| Uncorrected droop at the band edge | −2.317 dB |
| After correction, across the whole band | **0.036 dB** peak-to-peak |
| Stopband rejection | −58 dB |
| DC gain | exactly 1, so switching correction on/off does not change the data's scale |

Identical flatness at every decimation from 256 to 4096, because expressed against the
*output* rate the droop shape barely changes with R — so one coefficient set serves them all.
The generator checks this against the exact response rather than assuming it.

**How 309 taps fit in one multiplier.** The filter runs at the decimated rate, so there are at
least 256 clock ticks between output samples — one multiplier used many times is far cheaper
than many multipliers used once. Symmetry (`h[k] = h[308-k]`) halves the work again: the two
samples sharing a coefficient are added first, then multiplied once. 155 multiplications per
output sample, using two read ports of one memory.

**Consequence:** the filter needs ~160 ticks, so it **bypasses itself automatically below
R = 256** and reports that in `STATUS2[2]`. Software can also force the bypass, which is how
Test Stage 5 measures the droop with correction off and then on.

### Block 4 — memory streaming

Packs I and Q into one 64-bit word (`{Q, I}`, so a little-endian read gives `[I, Q]`), buffers
them, and streams to memory. Buffering and transfer reuse Red Pitaya's own `axi_wr_fifo`,
already proven on this board — much lower risk than a new transfer engine.

Takes **axi1**, the memory port the stock oscilloscope leaves unused. The scope's axi1
connections were disconnected in `red_pitaya_top.sv`; leaving both driving those nets would be
a genuine multiple-driver error. The scope loses its channel-B deep-memory capture, which
nothing here uses; its ordinary 16384-sample buffers are untouched.

Overflow is latched and reported. Lost samples are the most dangerous failure this instrument
can have: the record still looks continuous but time has jumped, so every frequency derived
from it is wrong.

### Register map additions

`CTRL` gains `[4]` arm, `[5]` wrap, `[6]` bypass corrector, `[7]` clear writer.
New registers `0x28`–`0x38`: memory region, current address, sample count, and a status word
carrying overflow, corrector overrun and corrector bypassed.

`TAP_SEL` gains a third source: the corrector's output, so Stage 5 can look at the same signal
before and after correction through the existing scope.

### Verification

`validate_fir.py` passes four checks, of which the second is the important one: the symmetric
hardware structure produces **bit-identical** results to a plain 309-tap sum over 600 random
samples. The centre tap must be counted once, not twice — the one error that structure invites,
and it would have shown up as a small gain error looking like a calibration problem.

### Documentation

`acquisition_custom/README.md` had grown to ~600 lines. Split: the README is now a concise
reference (chain, build, register map, decimation trade-offs, test plan, limits) and the
plain-English explanation moved to `EXPLAINER.md`.

---

## 2026-07-28 (sixth pass) — Test Stage 4 Check 4, noise floor

Check 4 reported FAIL: noise fell from 155 to 75 counts as decimation rose from 64 to 4096,
against an ideal 8× improvement. **The decimator is in fact working exactly as designed.**

Fitting `std(R)² = C² + K/R` — a floor plus broadband noise — gives residuals within ±4 counts
on values of 75–155. Subtracting the floor leaves a broadband component that improves as:

| R | 64 | 256 | 1024 | 4096 |
|---|---|---|---|---|
| broadband improvement | 1.0× | 2.0× | 4.0× | **8.0×** |
| √R | 1.0 | 2.0 | 4.0 | 8.0 |

Exact at every point. What limits the measurement is a **72.4-count (−41 dBFS) floor** that
averaging cannot remove.

**Why averaging cannot remove it.** The decimator reduces noise by *narrowing the bandwidth* —
it removes what lies outside the final band and passes what is already inside untouched. As R
grows the band shrinks and broadband noise falls as √R, but a component inside the band is
unaffected however narrow the band becomes.

**Where it must be coming from.** The whole chain is a bandpass centred on the reference tone:
at R = 4096 the clean band is only ±3 kHz wide. So the floor is something arriving within a few
kilohertz of 1.000054 MHz — most plausibly the generator still emitting with its output nominally
off, or an unterminated IN1 picking it up.

### Changes

| Change | Reason |
|---|---|
| Check 4 now fits the two-component model and tests the **broadband** part against √R | Demanding the raw figure follow √R to R = 4096 assumes a noise-free environment no real front end has. The decimator is only responsible for the broadband part |
| Floor reported explicitly in counts and dBFS | It is a property of the analogue environment worth recording, not a fault |
| Plot shows measured, fit, broadband part and floor separately | Makes the two contributions visible rather than inferred |
| New diagnostic sweeping the reference frequency | Distinguishes a discrete interferer near the signal frequency from broadband noise in the chain — they need different remedies |

---

## 2026-07-28 (fifth pass) — Test Stage 3, frequency resolution

Step 3 reported FAIL on every case, with every measurement reading exactly ±7629 Hz. That is
one FFT bin: 125 MSPS ÷ 16384 samples. The requested offsets of 5 and 10 kHz are **0.66 and
1.31 bins**, so both rounded into bin 1.

**The physics result was actually correct.** +5000 → +7629, −5000 → −7629, +10000 → +7629,
−10000 → −7629: every sign right. The spectrum is not mirrored, which is what Step 3 exists to
prove. Only the magnitudes were meaningless.

The governing relation, worth stating plainly because it constrains the whole instrument:

> **bin spacing = 1 / total acquisition time**

It depends only on how long you observe, never on how fast you sample. Sampling faster buys
bandwidth; only observing longer buys resolution.

This is the **second reason the decimator matters**, alongside noise and data reduction — it is
what makes long acquisitions possible at all. With a 16384-sample buffer:

| Decimation | Span of 16384 samples | Bin spacing |
|---|---|---|
| 1 (raw tap) | 0.13 ms | 7629 Hz |
| 64 | 8.4 ms | 119 Hz |
| 1024 | 134 ms | **7.45 Hz** |
| 4096 | 537 ms | 1.86 Hz |

An ion dip a few hertz wide is not merely hard to see at full rate — it is impossible,
regardless of signal-to-noise ratio.

### Changes

| Change | Reason |
|---|---|
| `DELTA` now derived from the bin spacing (4 bins, ~30 kHz) instead of a hard-coded 5 kHz | The offsets must be several bins wide to be measurable at all |
| Peak refined by parabolic interpolation across three bins | Recovers roughly a tenth of a bin; without it the answer is quantised to 7629 Hz |
| Zero-offset case now tested separately, as "what fraction of the energy sits at 0 Hz" | The DC removal that isolates the rotating component also removes the signal when there is no rotation — which is why the zero case reported a meaningless 7629 Hz |
| Errors also reported **in bins**, and the failure message distinguishes a resolution problem from a sign problem | The original message pointed only at the sign convention, which was not what had gone wrong |
| Two further offsets added (±4Δ) | More points to confirm the relationship is linear |

---

## 2026-07-28 (fourth pass) — Test Stage 3 notebook corrected

First run on hardware showed the mixer tap as a solid band rather than a flat line, and the
I-Q plane as a smear rather than a blob. **The hardware was right; the notebook's expectation
was wrong.**

Multiplying two tones produces a component at the difference of the frequencies *and* one at
their sum, both the same size. With a 10 MHz signal and a 10 MHz reference, the tap therefore
carries the wanted near-DC value plus a **20 MHz** component of equal amplitude. At 125 MSPS
that is 6.25 samples per cycle, which fills the plot in as a band roughly `2 × A × 256 / 2^shift`
counts wide — about 3400 counts for the observed 1716-count input, matching what was seen.

The sum term is removed by the decimator, which is the *next* block and is not in this
measurement. This was already documented in the mixer's header and in `validate_dds_mixer.py`,
and Step 3 of the notebook correctly restricted its FFT search to baseband — but Step 2 looked
at the time-domain trace and asked for flatness, which the raw mixer output can never show.

| Change | Reason |
|---|---|
| Added a `lowpass()` moving average, applied before assessing flatness and before every I-Q plot | Does in software what the decimator does in hardware: averaging over more than one cycle of the sum term cancels it, leaving the baseband value |
| Step 2 now plots raw **and** smoothed side by side | The raw band is correct behaviour and should be shown as such, not hidden |
| Step 1 now always adopts the **measured** signal frequency | It previously kept the typed value unless it was more than 1% out. A generator set to "10 MHz" measured 10,000,036.6 Hz |
| Step 4 measures magnitude on the smoothed data | Measuring the raw data would mostly have measured the sum term |

**The 36.6 Hz generator offset was not the cause.** It makes the I-Q point rotate once every
27 ms, against a capture lasting 0.131 ms — 1.7° of rotation, invisible.

---

## 2026-07-28 (third pass) — Fallout from removing the unused modules

Removing the daisy chain and the PWM outputs produced **4 DRC errors that blocked
bitstream generation**, plus two warnings. All four problems were consequences of tying
off pins that had previously been driven by proper I/O primitives.

| Problem | Cause | Fix |
|---|---|---|
| `[DRC IOSTDTYPE-1]` ×4 — **errors, "Bitgen not run"** | The SATA pins are a differential pair constrained as `DIFF_HSTL_I_18`. Driving `daisy_p_o` and `daisy_n_o` with two separate constants made them two independent single-ended outputs, contradicting that standard | Drive them through `OBUFDS` differential output buffers with a constant input. The pins stay a proper differential pair, sitting at a fixed level. Input pins need nothing — an unused input infers no buffer |
| `[Place 30-722]` ×4 | `set_property IOB TRUE` on `dac_pwm_o` demands the signal come from a flip-flop inside the I/O block. With the PWM module gone the pins are a constant, so there is no flip-flop to place | Removed the `IOB TRUE` property. It only means something for a signal that changes. Adding a dummy register purely to satisfy the tool would be logic that exists for no reason |
| `[Vivado 12-4739]` at synthesis | `get_clocks clk_fpga_*` matches nothing during **synthesis**, because the processing system is still an unresolved black box and its FCLK outputs do not exist yet | Guarded with `if {[llength $ps_clks] > 0}`. Applied at implementation, skipped quietly at synthesis. Any future `12-4739` or `17-165` is now a real problem rather than expected noise |
| `[Timing 38-282]` | Setup timing **passes** (+0.133 ns, 0 failing endpoints — better than the +0.017 ns before, because the PDM was the critical path). The message is now driven by the 28 ADC-pin hold violations | Addressed properly — see below |

### The ADC hold violations, finally diagnosed and fixed

Present in **every** build of this project including the original, always at exactly
−2.162 ns on exactly 28 endpoints — which is 14 data bits × 2 channels, every ADC data pin.
Not caused by any of the custom work.

The path report gives the whole answer:

| | |
|---|---|
| Data arrives | 3.400 (input delay) + 0.805 (input buffer) = **4.205 ns** |
| Capture edge | **6.011 ns** after the same edge at the pin |
| Required | 6.011 + 0.191 (hold) + 0.166 (uncertainty) = 6.367 ns |
| Slack | 4.205 − 6.367 = **−2.162 ns** |

The entire violation is 6.011 ns of **clock insertion delay**: input buffer 0.983 + routing
1.306 + PLL 0.089 + routing 1.754 + global clock buffer 0.101 + routing 1.777. It is not
compensated because `red_pitaya_pll` uses internal feedback (`CLKFBOUT` tied straight to
`CLKFBIN`), which aligns the PLL's output to its input at the PLL's own pins and does nothing
about the buffers either side of it.

**The hardware is fine.** Data settles at 4.205 ns and holds until 12.205 ns; the capture edge
at 6.011 ns sits inside that window, 1.8 ns after the data settles and 6.2 ns before it
changes. What Vivado objects to is the labelling: because the capture clock is delayed by more
than half a period, each register captures the data launched by the *same* numbered pin edge,
not the previous one.

**Fix:** `set_multicycle_path -hold -end 1` between `adc_clk` and `pll_adc_clk`, which states
exactly that. Slack becomes +5.8 ns. This is a declaration, not a suppression — setup is still
checked on all 28 endpoints and still passes.

The capture registers are already in the input logic block (`ILOGIC_X0Y1` in the report), so
the stock comment *"IO block registers should be used here"* is in fact already satisfied.

---

## 2026-07-28 (later) — Constraint syntax fix and removal of unused modules

### A constraint that had never worked

`[Common 17-165] Too many positional options when parsing 'clk_fpga_3'` at
`red_pitaya.xdc:255`. This was **self-inflicted**: the `set_clock_groups` command added
earlier passed four clock names to `get_clocks`, which takes only one positional pattern.
Vivado rejected the whole command, so the declaration that the processor and oscillator
clock families are asynchronous **had never been applied**.

Fixed by using a glob pattern: `[get_clocks clk_fpga_*]`.

Worth noting that this is the same class of failure as the dead clock names it was written
to fix — a constraint that looks present in the file but does nothing. The only reliable
check is to read the build log for `12-627`, `12-4739` and `17-165`.

### Modules removed

| Module | Slot | Why |
|---|---|---|
| `red_pitaya_pdm` | — | Drove the four slow analogue outputs on the E2 connector, unused here. **It was the design's critical path**, passing with 17 ps to spare. A sigma-delta feedback loop that must close in one clock tick, so it cannot be pipelined without changing its behaviour. Output pins tied low |
| `red_pitaya_ams` | `sys[4]` | Supplied the PWM configuration and had no other purpose. Slot now stubbed |
| `red_pitaya_daisy` | `sys[5]` | Multi-board synchronisation over SATA; this is a single-board setup. Source of the `[Synth 8-327]` inferred-latch warning and of timing paths in the 250 MHz serial domain. SATA outputs tied low, slot stubbed |
| `BUFG bufg_ser_clk`, `BUFG bufg_pwm_clk` | — | Buffered clocks that now go nowhere. A global clock buffer is a scarce routing resource, and every clock domain adds rows to the timing report that must be read and dismissed. The PLL still generates both clocks; its outputs are left unconnected, deliberately, since changing the PLL risks disturbing the ADC and DAC clocks |

**Kept, after discussion:** `red_pitaya_asg` (the arbitrary signal generator). Unused today,
but the paper's design includes internal signal generation for ion excitation pulses, so the
capability is likely wanted later.

**Kept:** `red_pitaya_hk` (LEDs including the LED0 heartbeat, GPIO, board identification) and
`red_pitaya_scope` (needed for the acquisition system's scope tap, and its second memory port
`axi1` is reserved for the acquisition system's DMA).

**Project file list left unchanged**, as requested — unreferenced files cost no hardware.

### Modules now instantiated in `red_pitaya_top.sv`

`red_pitaya_pll`, `red_pitaya_ps`, `sys_bus_interconnect`, `red_pitaya_hk` (sys[0]),
`red_pitaya_scope` (sys[1]), `red_pitaya_asg` (sys[2]), `red_pitaya_phaseshift` (sys[3]),
`red_pitaya_acq` (sys[6]), and stubs on sys[4], sys[5], sys[7].

Every bus slot is either a real module or a stub. A stub matters: it acknowledges accesses
and returns zero, so software touching an unused address gets a clean answer rather than
hanging the bus waiting for a reply that never comes.

---

## 2026-07-28 — Timing fixes after the first acquisition build

The first build with the acquisition system included had **7 failing setup endpoints at
−0.260 ns**, from two unrelated causes.

| File | Change | Reason |
|---|---|---|
| `rtl/classic/red_pitaya_phaseshift.v` | **FIX 7** — the delay clamp added by FIX 4 is now registered instead of combinational | 4 of the 7 endpoints. FIX 4 put a 10-bit comparison and a multiplexer directly in front of the delay-line read address. Registering it removes both lookup tables and their routing from the path. Behaviour unchanged, latency still L = 3 |
| `rtl/classic/red_pitaya_scope.v` | The eight equaliser coefficient registers (offsets `0x30`–`0x4C`) removed | The other 3 endpoints. Leftovers from removing the equaliser itself: 186 flip-flops nothing read, plus their bus address decode. The path from the AXI write-address register to their clock enables measured 7.879 ns, of which **83% was wiring** — the placer had put them far from everything because nothing else connected to them. Those offsets now fall through to the decoder's default case: writes acknowledged and ignored, reads return zero |
| `rtl/classic/red_pitaya_scope.v` | Revert instructions corrected | They described restoring only the filter, which would no longer work now the coefficient registers are gone too |

**Note on FIX 7:** FIX 4 solved a correctness bug (a silently broken delay setting above
31.25 MHz) and created a timing one. Both are now fixed, but it is worth recording that a
correctness fix can introduce a timing regression — and that the regression only appeared
once unrelated logic was added and the placement shifted.

**Note on the delay line:** the FIX 3 write-up says the delay line was rebuilt as block RAM.
In practice Vivado implements it as LUT-based **distributed** RAM, because the line needs one
write port and two independent read addresses — three ports, and block RAM offers two. That
is why its read address net has a fan-out of 229 and why routing dominates that path.

### Resource use after the acquisition system was added

| | Before | After | Change |
|---|---|---|---|
| Logic (LUTs) | 5482 | 7137 | +1655, mostly the two 72-bit decimators |
| Registers | 5518 | 7539 | +2021 |
| Block RAM | 30 | 34 | +4, the oscillator's sine table |
| Multipliers | 6 | 8 | +2, one per mixer channel — as predicted |

---

## 2026-07-27 — Acquisition system, first integration

### New files

| File | Purpose |
|---|---|
| `rtl/classic/red_pitaya_acq_dds.v` | Local-oscillator generator (block 0) |
| `rtl/classic/red_pitaya_acq_mixer.v` | IQ mixer / downconverter (block 1) |
| `rtl/classic/red_pitaya_acq_cic.v` | CIC decimating filter (block 2), one channel |
| `rtl/classic/red_pitaya_acq.v` | Acquisition top level, registers, debug features |
| `acquisition_custom/validate_dds_mixer.py` | Bit-accurate check of blocks 0 and 1 |
| `acquisition_custom/validate_cic.py` | Bit-accurate check of block 2 |
| `acquisition_custom/add_acquisition_sources.tcl` | Adds the new sources to the Vivado project |
| `acquisition_custom/README.md` | Plain-English design guide and test plan |
| `BITSTREAM_WORKFLOW.md` / `.pdf` | Command-line guide for loading bitstreams |
| `phaseshift_custom/which_bitstream.py` | Reports which bitstream is running |
| `acquisition_custom/Test Stage 2 - Reference Tone and Timing.ipynb` | Registers, sample rate, reset, oscillator frequency |
| `acquisition_custom/Test Stage 3 - Frequency Shifting and Sign Convention.ipynb` | Mixer, including the mirrored-spectrum check |
| `acquisition_custom/Test Stage 4 - Decimation Rate Scaling and Noise.ipynb` | Decimator: rate, scaling, noise, staircase |

### Edits to existing files

| File | Change | Reason |
|---|---|---|
| `rtl/classic/red_pitaya_scope.v` | Equaliser `red_pitaya_dfilt1` removed from the datapath; original preserved in a comment block | Caused 1173 of 1289 setup timing violations. Structural: recursive filter whose loop must close in one 8 ns tick but takes ~12 ns. Coefficients reset to pass-through and no software writes them, so removing it changes nothing observable and frees ~14 multipliers |
| `rtl/classic/red_pitaya_phaseshift.v` | **FIX 4** — guard against `set_dly = 0`, plus read-only status bit at `0x14` | Above 31.25 MHz the natural setting is 0, which silently reads the sample 1024 clocks old instead of the current one |
| `rtl/classic/red_pitaya_phaseshift.v` | **FIX 5** — interpolation weights pre-computed into registers | Caused 101 timing violations. `16384 − set_delta` was computed in the signal path every clock, though it only changes when software writes it |
| `rtl/classic/red_pitaya_phaseshift.v` | **FIX 6** — output stage split across two clock ticks | Caused the final 16 violations. Latency 2 → 3 samples; `L_PIPE` updated to 3 in the notebook and validation script |
| `prj/v0.94/rtl/red_pitaya_top.sv` | Instantiated `red_pitaya_acq` on `sys[6]` (`0x40600000`) | Acquisition system integration |
| `prj/v0.94/rtl/red_pitaya_top.sv` | Added scope input multiplexer | Lets the existing scope capture acquisition internals |
| `prj/v0.94/rtl/red_pitaya_top.sv` | Bus stub loop now covers only `sys[7]` | `sys[6]` is occupied |
| `constrs_1/.../sdc/red_pitaya.xdc` | Clock names corrected; processor and oscillator clock families declared asynchronous as one group | ~30 constraints named clocks that do not exist (`dac_clk_o` etc. instead of `pll_dac_clk_1x`) and were silently ignored |
| `constrs_1/.../prj/v0.94/sdc/red_pitaya.xdc` | Dead constraints removed, including `LOC` for a cell that no longer exists | Same reason; clock relationships now defined in one file only |
| `phaseshift_custom/validate_bram.py` | Model updated for FIX 6; `L_PIPE` 2 → 3 | Keeps the model matching the hardware |
| `phaseshift_custom/phase_shift_control.ipynb` | `L_PIPE` 2 → 3 | Same |

### Bugs found during the integration review

Caught by checking the modules against each other before wiring anything up.

| Module | Bug | Consequence if shipped |
|---|---|---|
| `red_pitaya_acq_cic.v` | `stb_o` was asserted on the same clock edge that wrote `dat_o`, so the data was not yet readable | Every decimated sample shifted by one — silently, with no visible symptom |
| `red_pitaya_acq_cic.v` | Output bit window was a hard-coded table valid only for the default parameters | Changing any parameter would have selected the wrong bits and produced plausible but wrong data |
| `red_pitaya_acq_mixer.v` | Outputs named `dat_i_o` / `dat_q_o` | Under Red Pitaya's convention `_i` means input, so these read as inputs. Renamed `i_dat_o` / `q_dat_o` |

### Timing progress

| Build | Worst slack | Failing endpoints | Multipliers |
|---|---|---|---|
| Original | −4.339 ns | 1273 | 20 |
| After removing the equaliser | −1.437 ns | 101 | — |
| After FIX 5 + constraint fixes | −0.639 ns | 16 | 6 |
| After FIX 6 | **+0.017 ns** | **0** | 6 |

### Hardware verification (stage 1)

Phase sweep measured on the board at 1, 5 and 10 MHz:

| | Original build | After all fixes |
|---|---|---|
| Fitted loop delay | 119.824 ns | **119.867 ns** |
| In clock cycles | 14.978 | 14.983 |
| Constant offset | +0.531° | +0.580° |
| Residual scatter | 0.164° | 0.113° |

The loop delay is unchanged: FIX 6 added one clock in hardware, and `L_PIPE = 3`
removes one clock of compensation, so the two cancel exactly. Confirmed by an
intermediate measurement with the new notebook against the old bitstream, which
read 111.86 ns — precisely one clock cycle short, as predicted.

### Known outstanding (status as of the third pass, 2026-07-28)

- ~~28 hold-time violations on the ADC data pins~~ — **resolved**, see the third pass above.
- ~~PDM path has only 17 ps of margin~~ — **resolved**, the module was removed.
- ~~Latch inferred in `red_pitaya_daisy.v`~~ — **resolved**, the module was removed.
- **XADC compiled for the wrong clock speed** (`[Timing 38-316]`): built assuming
  100 MHz, driven at 200 MHz. Inside the block design, so fixing it means regenerating
  that block. Monitors chip temperature and supply rails only, so not in the
  measurement path. **Still outstanding.**

---

## 2026-07-24 — Feedback path (earlier work)

Variable phase shifter built and validated. See `phaseshift_custom/README.md` for
FIXES 1–3: the reserved-keyword name clash, the `.sv` → `.v` rename, and the
rebuild of the delay line from a 1024-deep flip-flop shift register into a block-RAM
circular buffer after the placer ran out of room on the XC7Z010.
