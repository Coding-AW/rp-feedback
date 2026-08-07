# External verification of Q and ν_res — design plan

A design document, not an implementation. Written 2026-08-06, to be reviewed before any Verilog
is touched or any notebook cell is added. Same status as `SEQUENCER_PLAN.md`.

**Goal.** Hold the feedback at chosen gains and phases, taken from the scans that already
measured them, and confirm the resulting quality factor and resonant frequency on an external
spectrum analyser fed from OUT2.

---

## 0. Read this first: the current bitstream fails timing

`Test_Project.runs/impl_1/bitstream_id.txt`:

```
096CEAD0
# timing   : *** FAIL *** worst slack -6.907 ns, 2000 failing path(s)
# WARNING  : this bitstream does not meet timing. Measurements taken
#            from it cannot be trusted, whatever the fingerprint says.
```

`0x096CEAD0` is the fingerprint the coil notebook prints and passes in Step 0. Every published
number — 39.9417 MHz, Q = 179.8, the feedback map, Q → 1434 — came from this build.

**Where it fails.** The ten worst paths are all inside `i_reso`, the digital resonator emulator:

| | |
|---|---|
| Source | `i_reso/v_reg[21]/C` |
| Destination | `i_reso/u_reg[*]/R` (the flip-flop **reset** pins) |
| Data path delay | 14.131 ns against an 8.000 ns requirement |
| Logic levels | 23 — 18 × CARRY4, 2 × DSP48E1, 3 × LUT |

A wide carry chain driving a synchronous reset. That is a saturation or clip detector on the
accumulator, which is what `emu.clipped()` reads and what the Step 1 self-test's
`if emu.clipped(): raise` depends on.

**Confirmed 2026-08-06:** the `md5sum` of the bitstream on the board matches
`impl_1/red_pitaya_top.bit`. The board is running this build. `BUILD_ID` could not have told you
that — it is a hash of six *source files* (`build_project.tcl` lines 270–279), so every build of
the same source shares a fingerprint. It answers "which source", never "which build" and never
"did it meet timing".

**What is still not known.** The timing summary details only its ten worst paths, and 6,224 of
29,573 endpoints fail (TNS −6290 ns, about −1.0 ns average). Twenty-one percent of the design's
endpoints is far more than `i_reso`'s own register count, so the CHANGELOG's claim that the
failures are "all in the resonator's recursive loop" is **not established** by the summary
report. Settle it before trusting any published number:

```tcl
report_timing -from [get_cells i_ps/*]  -max_paths 50 -slack_lesser_than 0
report_timing -from [get_cells i_acq/*] -max_paths 50 -slack_lesser_than 0
```

If both come back clean, the coil measurements stand: `i_reso` is disabled throughout Steps 2–8,
its registers do not toggle, and a quiescent path cannot capture a wrong value. Only the Step 1
and 9a self-tests and the Step 4b fitter calibration — the three places the emulator is switched
in — are affected. If either returns paths, the coil measurements are in question too, and this
plan waits.

---

## 1. Bitstream changes

### 1.1 The emulator's recursion — diagnosis and fix

**What the path actually is.** With `SW = 25`, `CW = 18`, `SHIFT = 17`, the one-clock recursion
was:

```
u ──DSP──► c·u ──┐
v ──DSP──► s·v ──┴─► (cu − sv + ROUND) ──► >>> 17 ──► + drive_r ──► sat ──► u
                        43-bit adder                   26-bit adder
                        11 CARRY4                      7 CARRY4
```

11 + 7 = **18 CARRY4**, which is exactly what the routed report shows on the failing path
(`CARRY4=18 DSP48E1=2`, data path 14.131 ns). Two adders in series inside a loop that has 8 ns.

**The second adder does not have to be there.** For integers,
`floor(X/2ˢ) + D ≡ floor((X + D·2ˢ)/2ˢ)`, so the drive can be added *before* the shift. And
`ROUND` is a single 1 at bit `SHIFT−1` while `drive_r << SHIFT` has nothing below bit `SHIFT`, so
their sum is a **concatenation** — not an adder, not even a lookup table:

```verilog
ROUND + (drive_r <<< SHIFT)  ==  {drive_r, 1'b1, {(SHIFT-1){1'b0}}}
```

**Applied 2026-08-06**, and proved bit-for-bit identical by
`acquisition_custom/validate_resonator_loop.py`: exhaustive at reduced widths (1,464,320
combinations), 400,000 random cases at the real widths, and three full 20,000-sample resonator
runs including one driven into saturation. Zero mismatches. One 26-bit carry chain leaves the
recursion and becomes wiring.

**This is necessary but may not be sufficient.** It removes about 7 of the 23 logic levels. The
other large term is the unregistered DSP multiply, which this does not touch — an
`A×B → P` path with no internal pipeline registers is several nanoseconds on a −1 speed grade
part, so a single-clock recursive multiply-add at 125 MHz is marginal by construction. Rebuild
and read the slack before assuming anything.

### 1.1b Required, and validated 2026-08-07: pipeline by two-way look-ahead

> The 2026-08-07 rebuild reached WNS -3.482 ns. The two cascaded DSP stages cost
> 5.554 ns by themselves and the irreducible core is 8.546 ns against 7.907
> available, so **one clock cannot close whatever the fabric does**. Validated by
> `acquisition_custom/validate_resonator_pipelined.py`; see the CHANGELOG entry of
> 2026-08-07 for the measured numbers, including the -46 dB polyphase image.

You cannot simply add a register to a recursive loop — but you can compute two samples per
update and absorb the extra clock into the coefficients. With
`x[n] = (u[n], v[n])ᵀ` and `x[n+1] = M·x[n] + b[n]`:

```
x[n+2] = M²·x[n] + M·b[n] + b[n+1]
```

and because `M = r·Rot(ω₀)`, the squared matrix is simply `M² = r²·Rot(2ω₀)`. So the new
coefficients are

```
c2 = r²·cos(2ω₀)·2^SHIFT        s2 = r²·sin(2ω₀)·2^SHIFT
```

computed in software exactly the way `c` and `s` already are — one extra line in
`Emulator.config()`, two extra coefficient registers.

Hold **two interleaved state banks**, even and odd, each updated on alternate clocks. Each update
then has **two clocks (16 ns)** to settle, which closes with room to spare. The output multiplexes
between the banks, outside the loop.

```
u[n+2] = (c2·u[n] − s2·v[n] + c·d[n] + d[n+1]·2^SHIFT) / 2^SHIFT
v[n+2] = (s2·u[n] + c2·v[n] + s·d[n])                  / 2^SHIFT
```

Cost: about 12 DSP slices instead of 4, against 17 of 80 currently used. Software impact: two
more coefficient registers in `Emulator.config()`, and the same change in
`jupyter_notebooks/tests/fakehw.py`'s `_emu_pole()`. Treat it as its own piece of work with its
own validation script — `validate_resonator_loop.py` is the template.

**Consequence to expect either way.** The emulator's saturation behaviour has been unreliable, so
the Step 1 self-test's clipping guard may not have been working. Once timing closes, re-run
Step 1 and Step 4b and compare against `.bak18`. If the recovered Q moves, the failing paths were
affecting it and `MIN_AMP_FOR_FIT` needs re-deriving.

### 1.2 The OUT2 monitor

Only one line stops OUT2 from carrying anything. `red_pitaya_phaseshift.v` line 364:

```verilog
assign dat_b_o = {DWI{1'b0}};       // single-channel: CH B held at zero
```

`pid_dat[1]` is already wired to `dac_b_sum` in the top level, so nothing outside this module
needs touching.

**New register, phase shifter base `0x40300000`, offset `0x18`** (free: `0x00`–`0x10` are
coefficients/delay/bypass, `0x14` is a read-only delay readback):

| Bits | Field | Meaning |
|---|---|---|
| `[1:0]` | `MON_SRC` | `0` = off (channel B held at zero, exactly as now) · `1` = phase-shifter **input** `dat_a_i` · `2` = phase-shifter **output** `out_a` · `3` = reserved |
| `[5:3]` | `MON_SHF` | left shift 0–7 applied before saturation |

**Defaults to `0`.** The bitstream behaves identically to today until software enables it — the
same discipline `i_acq` and `i_reso` already follow.

```verilog
// ---- monitor: drives the otherwise-unused channel B output to OUT2 --------
//  A read-only observation point. dat_a_i is a fan-out, out_a is already
//  registered; nothing is inserted into the channel A datapath, so the
//  119.87 ns loop delay is untouched.
reg  [1:0] set_mon_src;
reg  [2:0] set_mon_shf;
// (bus write block)
//   if (sys_addr[19:0]==20'h18) begin
//       set_mon_src <= sys_wdata[1:0];
//       set_mon_shf <= sys_wdata[5:3];
//   end
wire signed [DWI-1:0]   mon_sel = (set_mon_src==2'd1) ? dat_a_i :
                                  (set_mon_src==2'd2) ? out_a   : {DWI{1'b0}};
wire signed [DWI+7-1:0] mon_shf = $signed(mon_sel) <<< set_mon_shf;
reg  signed [DWI-1:0]   mon_reg;
always @(posedge clk_i)
  if (!rstn_i) mon_reg <= {DWI{1'b0}};
  else         mon_reg <= mon_saturate(mon_shf);   // same style as the CH A saturation
assign dat_b_o = mon_reg;
```

Plus a readback case at `0x18` so software can prove the register exists.

**Why `dat_a_i` is the right input tap.** It is `adc_dat_ps[0]`, which is post-emulator: the
monitor automatically follows whatever the notebook is measuring — the coil, or the digital
resonator when it is switched in.

**Resource cost.** ~14 flip-flops, a two-way mux and a saturating shifter: on the order of 50
lookup tables. Current utilisation is 8691/17600 lookup tables (49%) and 8108/35200 flip-flops
(23%). Immaterial.

---

## 2. Does this affect the feedback loop, now or in future?

### 2.1 Logic and timing — no expected effect

| Concern | Assessment |
|---|---|
| **Channel A datapath** | Untouched. Nothing is inserted; `dat_a_i` is fanned out and `out_a` is read after it is already registered. The 119.87 ns loop delay is unchanged by construction |
| **Fan-out loading** | `dat_a_i` gains one destination. Tens of picoseconds of extra routing delay at worst, against an 8 ns period. Not zero, so **re-measure the loop delay** with `jupyter_notebooks/phaseshift/scope_phase_check.ipynb` after the rebuild rather than assuming |
| **New clock domain crossings** | None. `dat_b_o → pid_dat[1] → dac_b_sum → dac_dat_b` is the identical structure channel A already uses. That path currently shows +0.646 ns slack over 45 endpoints |
| **Resources** | Negligible, as above |
| **Default state** | Off. A future feedback experiment that does not want the monitor simply never writes `0x18` |

### 2.2 Analogue — two real risks, both measurable

**Risk 1: OUT2 coupling back into the tank.** OUT2 would carry a copy of the tank's signal, at
the tank's frequency, on a connector block inches from OUT1 and the coil. Approaching K = 1 the
loop is extremely sensitive to any additional path, and this one has unknown phase and delay.
Enough of it returning to the tank creates a second, uncontrolled feedback loop.

*Mitigation:* a 10–20 dB pad and a terminated cable running straight into the analyser, routed
away from the coil. *Verification:* cell 10.3 below measures Q with the monitor off and on, and
refuses to continue if it moves.

**Risk 2: converter switching noise.** DAC B is currently static. Making it active adds
switching current in an output stage that shares its supply and ground with DAC A, which drives
the loop. This is a genuine mechanism for raising the drive's noise floor.

*Mitigation:* the shift field. Do not run the monitor at full scale if −40 dBm at the analyser is
enough. *Verification:* cell 10.3 also compares the Step 2 band-survey floor with the monitor off
and on.

### 2.3 A trap worth naming

`red_pitaya_top.sv` line 373: `assign adc_dat[1] = digital_loop ? dac_b : adc_dat_raw[1]`.

The housekeeping block's digital-loop bit routes DAC B into ADC B **internally**. If it is set,
the OUT2 → IN2 loopback self-test in cell 10.2 passes **with no cable connected**, and you would
conclude the monitor works when nothing reaches the SMA. Cell 10.1 must read that bit and refuse
if it is set.

### 2.4 What to check after the rebuild

1. `WNS > 0` — `build_project.tcl` already gates on this, and it is now the pass criterion.
2. `report_timing -from [get_cells i_ps/*] -max_paths 50` clean.
3. Loop delay re-measured and still 119.87 ns.
4. Coil notebook re-run end to end, compared against `.bak18` — the "did fixing the emulator's
   timing move anything" check.

---

## 3. Notebook additions — Step 10

Appended to `Test - Resonator Coil Characterisation.ipynb`, after Step 9. It needs `PHI_NARROW`,
`PHI_BROAD`, `PHI_SHIFT`, `k_slope`, `FB_GAIN_CEIL`, `spec_fit`, `_slope`, `SHIFT_MAX`, `F0`,
`LW`, `Q_SWEEP` and `TONE_PEAK` — all in memory once Steps 8a–8e have run. Every code cell is
preceded by a markdown cell, as with the rest of the notebook.

### Configuration additions

```python
MONITOR_SRC        = 1      # 0 off, 1 phase-shifter input, 2 phase-shifter output
MONITOR_SHIFT      = None   # None = cell 10.2 measures and chooses it
EXT_PAD_DB_ANALYSER = 10.0  # pad + cable loss between OUT2 and the analyser
EXT_PERTURB_TOL    = 0.02   # refuse if enabling the monitor moves Q by more than this
EXT_HOLD_TIMEOUT_S = 300.0  # a held point drops out on its own after this
EXT_HOLD_POLL_S    = 0.2    # watchdog interval while holding
```

### The cells

| # | Type | Content |
|---|---|---|
| **10.0** | md | **What this verifies and how to wire it.** `OUT2 → 10 dB pad → DC block → analyser`. What the monitor does check (mixer, decimator, corrector, transport, fitter) and what it does not (the analogue-to-digital converter, the clock, the front end). Points at the passive tank tap as the complementary check that covers those |
| **10.1** | md | **Preflight, and why.** Three things make the whole step meaningless: an old bitstream with no `0x18`, the housekeeping digital-loop bit set, or the monitor left enabled from a previous session |
| **10.1** | code | A small `Monitor` driver class on `0x18`. Probe-and-readback to prove the register exists — an old bitstream fails to hold the pattern and raises with "rebuild needed, see EXTERNAL_VERIFICATION_PLAN.md". Reads the housekeeping digital-loop bit and refuses if set. Restores `0x18 = 0` after probing. Prints the build id and states that timing must have passed |
| **10.2** | md | **The loopback self-test.** Before trusting anything on the analyser, prove OUT2 carries the signal — using a cable you already have and no external instrument |
| **10.2** | code | `OUT2 → IN2`. Drive at `F0`, enable the monitor, capture both channels with the scope block (`sc.tone_frac(F0)` on `chan='A'` and `'B'`). Reports the **measured monitor gain**, which is what converts the analyser's dBm back to a tank voltage. Sweeps `MON_SHF` and picks the largest shift that does not saturate at the **largest input level in the hold list**, not at the unfed level — under feedback the input rises by 1/(1−K) |
| **10.3** | md | **Does the monitor disturb what it monitors?** The two mechanisms from §2.2, and why this is measured rather than argued |
| **10.3** | code | `refine_and_fit` with the monitor off → on → off. Reports Δf₀ and ΔQ, and re-runs the Step 2 survey both ways to compare noise floors. Raises if ΔQ exceeds `EXT_PERTURB_TOL`, naming which mechanism to chase and suggesting a larger pad first |
| **10.4** | md | **Building the operating points from the scans.** Nothing here is typed by hand. Explains each predicted column so a disagreement can be attributed to one thing |
| **10.4** | code | `build_hold_list()` → a table of `label, A, φ, K_pred, Q_pred, f_res_pred, lw_pred, level_dBm_pred`. Three families: **unfed reference** (A = 0); **Q family** at `PHI_NARROW`/`PHI_BROAD` over `FB_SPEC_FRACS × FB_GAIN_CEIL`, with `K = k_slope·A` and `Q = Q₀/(1−K)`; **shift family** at `PHI_SHIFT`/`PHI_SHIFT+180` over `FB_SHIFT_FRACS × FB_GAIN_CEIL`, with `Δf = _slope·A` |
| **10.5** | md | **Holding safely — the watchdog.** This is the first time the notebook parks the loop at high gain indefinitely. Sweeps have a per-point level guard; a hold has none |
| **10.5** | code | `hold(A, phi, mode, seconds)`. Two modes: **`sweep`** repeatedly sweeps the drive across the line so the analyser in max-hold traces a lineshape (needed for Q); **`park`** fixes the drive at the predicted centre (verifies f_res and level only). While holding, poll `sc.peak_frac()` every `EXT_HOLD_POLL_S`, and drop everything on exceeding `FB_LEVEL_GUARD`, on the drive-off oscillation test, or on `EXT_HOLD_TIMEOUT_S`. `try/finally → ps.off(); gen.off()` on every exit path including Ctrl-C |
| **10.6** | md | **Taking the readings.** The analyser settings are computed per point, not chosen: span from `lw_pred`, resolution bandwidth ≤ `lw_pred/8`, reference level from `level_dBm_pred`. Names the trap: a sweep that dwells less than a few times the ring-up time `Q_eff/(π·f₀)` measures a **broader** line than exists, so Q reads low. At Q = 1400 that is 11 µs per resolution cell |
| **10.6** | code | Guided run. For each point: print the settings to dial in, call `hold()`, then `input()` the measured centre and −3 dB width. Appends to `EXT_ROWS`. Skippable per point, resumable, and Ctrl-C safe |
| **10.7** | md | **What agreement and disagreement mean.** Tolerances, and the attribution rules |
| **10.7** | code | Board versus analyser for Q and for centre shift, with a y = x line and residuals in linewidths. Verdict per family: centre to 0.1%, Q to 10% |
| **10.8** | code | Append an `external_check` block to `bench_coil_results.json`, and leave the monitor **off** |
| **10.9** | md | Troubleshooting decision table (below) |

### Troubleshooting table (cell 10.9)

| Symptom | Likely cause | What tells you |
|---|---|---|
| `0x18` does not read back | Old bitstream | 10.1 compares the build id against `bitstream_id.txt` |
| IN2 sees nothing in loopback | Monitor off, cable, or IN2 jumper | 10.2 reports which of the three |
| IN2 sees signal with the **cable removed** | Housekeeping digital-loop bit set | 10.1 refuses before you get here |
| Analyser shows the tone, but Q reads low | Sweep too fast against the ring-up time, or resolution bandwidth too wide | 10.6 prints both limits for that point |
| Q changes when the analyser cable is connected | OUT2 coupling into the tank | 10.3 quantifies it; fit a larger pad |
| Analyser centre offset by a constant across every point | Analyser frequency reference | Feed signal generator channel 2 in as an exact marker — its word is 0.116 Hz exact on the same 125 MHz clock |
| Held point drifts out over minutes | Real coil drift | Compare against `DRIFT_HZ_PER_MIN` from Step 7 |
| Level far below prediction | Shift field, pad value, or `EXT_PAD_DB_ANALYSER` | 10.2 measures the real monitor gain |
| Q agrees unfed but not under feedback | The monitor is perturbing the loop only near instability | Re-run 10.3 at the highest gain in the list, not at A = 0 |

### Expected levels

`TONE_PEAK` was 0.0049 of full scale at IN1. With the monitor at shift `s`, OUT2 delivers
`0.0049 × 2^s` of the converter's ±1 V:

| shift | OUT2 peak | into 50 Ω | after a 10 dB pad |
|---|---|---|---|
| 0 | 4.9 mV | −36 dBm | −46 dBm |
| 3 | 39 mV | −18 dBm | −28 dBm |
| 5 | 157 mV | −6 dBm | −16 dBm |

Comfortable at any of these. The constraint on `s` is the **largest** level in the hold list: at
K = 0.83 the input rises about sixfold, so a shift chosen at A = 0 will saturate under feedback.
Cell 10.2 picks `s` from the maximum predicted level, which is why it must run after 10.4 —
**or** 10.4 must run first and 10.2 take its table as an argument. The latter is cleaner; order
the cells 10.1, 10.4, 10.2, 10.3, 10.5 … and renumber.

---

## 4. Order of work

1. Confirm no failing paths in `i_ps` or `i_acq` (§0). If there are, stop and fix those first.
2. Fix `i_reso`'s comparator, rebuild, confirm `WNS > 0`.
3. Re-run the coil notebook on the clean bitstream; diff against `.bak18`.
4. Add the monitor register, rebuild, confirm `WNS > 0` again and the loop delay unchanged.
5. Add Step 10 and run the loopback self-test with no analyser attached.
6. Attach the analyser and work through the hold list.

Steps 2 and 4 are separate rebuilds on purpose: if the second one breaks timing you know it was
the monitor, and if the coil numbers move at step 3 you know it was the emulator.
