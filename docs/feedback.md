# Variable Phase Shift + Gain — custom Red Pitaya module

> Archived implementation investigation. Paths and commands below describe the
> former vendored Vivado layout. Use the root `README.md`, `docs/usage.md`, and
> `docs/architecture.md` for the supported workflow.

Custom FPGA module replicating the variable phase shifter of Herkenhoff et al.,
*A digital feedback system for advanced ion manipulation techniques in Penning traps*,
Rev. Sci. Instrum. **92**, 103201 (2021), built on the Red Pitaya v0.94 baseline to test
the workflow.

**Signal path:** signal generator → ADC CH A → phase/gain module → DAC CH A → oscilloscope.

## How it works

The output is `y[n] = A·cos(φ)·I[n] + A·sin(φ)·Q[n]`, where `I` is the input (in-phase) and
`Q` is the input delayed ~90° (quadrature). `Q` is produced by a two-tap fractional delay
line at taps `⌊D⌋` and `⌈D⌉`, with `D = f_clk /(4·f_sig)` clock cycles (`f_clk` = 125 MHz).
The trig/gain products `A·cos φ` and `A·sin φ` are computed on the host and written as two
signed Q2.14 coefficients, so the FPGA contains only the delay line and two multipliers.
The delay line is a **block-RAM circular buffer** (write pointer + two registered reads), not
a flip-flop shift register — see FIX 3 below.

The module has a fixed **3-sample pipeline latency** (block-RAM read + multiplier stages +
the FIX 6 output pipeline register; it was 2 before FIX 6).
That is a pure transport delay, adding a constant phase lag of `360·L·f_sig/f_clk` degrees.
The notebook's `configure()` cancels it automatically (`phi_eff = phi − 360·L·f_sig/f_clk`),
so the scope shows the phase you request.

Validated bit-accurately: the ideal-timing model (`validate_phaseshift.py`) gives < 0.03°
phase / < 0.1% gain error; the cycle-accurate block-RAM model (`validate_bram.py`), **with**
host latency compensation, gives < 0.09° phase / < 0.11% gain error across 0–360°.

### Fixes applied during bring-up
- **FIX 1** — `[Synth 8-2715] syntax error near buf`: the delay array was named `buf`, a
  reserved Verilog keyword. Renamed to `dly_mem`.
- **FIX 2** — file renamed `.sv → .v` (module is plain Verilog-2001; `.sv` was not the error).
- **FIX 7** — `[Timing 38-282]` after the acquisition system was added, 4 failing endpoints at
  −0.260 ns on `set_dly_reg → q_mix`. **FIX 4 caused this**: it computed the delay clamp
  combinationally, putting a 10-bit comparison and a multiplexer directly in front of the
  delay-line read address. The clamp is now **registered**, taking both lookup tables and
  their routing out of the path. Behaviour unchanged; latency still L = 3.
  Worth noting the delay breakdown: only 1.958 ns of the 8.098 ns was logic — the rest was
  wiring, dominated by one net with **fan-out 229**. That is the delay-line read address:
  the line needs one write port and two independent read addresses, which is three ports,
  and block RAM offers only two — so Vivado builds it from LUT-based distributed RAM and the
  address must reach every one of them. (The FIX 3 note below says "block RAM"; in practice
  the tool chose distributed RAM for this reason.)
- **FIX 6** — `[Timing 38-282]` 16 remaining failing endpoints at −0.639 ns on the path
  `mult_i → out_a_reg`. The output stage did multiply → 31-bit add → two clip comparisons →
  store all within one 8 ns tick (8.464 ns measured). Unlike FIX 5 nothing could be hoisted
  out, so the sum is now **registered** and the clipping happens on the following tick. The
  bypass path is delayed to match, so toggling bypass does not change latency.
  **Latency goes from L = 2 to L = 3 samples**, i.e. loop delay ~120 → ~128 ns.
  `L_PIPE` updated to 3 in both `validate_bram.py` and `phase_shift_control.ipynb`; the
  model's independent latency measurement reads exactly 3.000 samples at every frequency,
  and worst phase error after compensation is 0.080° (was 0.083°).
  Cost to the experiment: phase-vs-frequency slope 43.1 → 46.0 °/MHz, and the delay-limited
  feedback bandwidth 4.2 → 3.9 MHz — both far outside this detection system's range.
- **FIX 5** — `[Timing 38-282]` design fails timing, 101 failing endpoints at −1.437 ns, all on
  the path `set_delta_reg → q_mix`. The interpolation weight `(1−δ)` was computed as
  `16384 − set_delta` *combinationally, inside the signal path*, putting a 15-bit
  subtraction in front of the multiplier: register → 4 carry stages → multiply → add →
  register = 7.698 ns against an 8 ns clock. `set_delta` is a configuration value written
  by software, so the subtraction is now done **once into a register** instead of 125
  million times a second. Signal latency is unchanged at L = 2; only a newly written
  `set_delta` takes one extra clock (8 ns) to take effect. Both validation scripts still
  pass, worst phase error 0.083°.
- **FIX 4** — see the high-frequency section below: `set_dly = 0` was silently broken.
- **FIX 3** — `[Place 30-4/30-99] utilization very high` on the XC7Z010: the delay line was a
  1024-deep flip-flop shift register with variable-index taps (~14k FFs + huge F7/F8 muxes),
  which overflowed the small device. Rebuilt as a block-RAM circular buffer (~2 BRAM tiles).

## Files changed / added

| File | Change |
|------|--------|
| `...srcs/sources_1/imports/rp/rtl/classic/red_pitaya_phaseshift.v` | **NEW** custom module (plain Verilog, like `red_pitaya_pid.v`) |
| `...srcs/sources_1/imports/rp/prj/v0.94/rtl/red_pitaya_top.sv` | PID instantiation on `sys[3]` swapped for `red_pitaya_phaseshift i_ps` (original PID kept, commented, for revert) |
| `notebooks/feedback/phase_shift_control.ipynb` | Jupyter control (interactive sliders, latency-compensated) |
| `software/validation/validate_phaseshift.py` | ideal-timing fixed-point model |
| `software/validation/validate_bram.py` | cycle-accurate block-RAM model + latency check |
| `notebooks/feedback/scope_phase_check.ipynb` | internal-scope input/output phase measurement (diagnostic) |

## Phase diagnostic: FPGA vs measurement-rig artifact

`scope_phase_check.ipynb` uses the Red Pitaya's own acquisition block (`sys[1]`,
`0x40100000`, unchanged in this bitstream) to measure input vs output **inside the board**,
removing the external scope, the 50/50 divider, and the BNC cabling from the comparison.

Wiring: add one short loopback cable **OUT1 → IN2**; keep the generator on **IN1**.
The scope then captures CH A = IN1 (FPGA input) and CH B = IN2 (FPGA output). Both go through
identical ADC chains at the same clock and buffer index, so their relative phase is exact and
any common latency cancels.

> **AXI access rule (important):** the FPGA register/buffer space must be read with **single
> 32-bit accesses only**. A bulk `mmap` slice (`m[a:b]`) becomes a wide/burst `memcpy` that the
> GP-AXI → sys-bus bridge cannot acknowledge; this locks the AXI bus and **reboots the board**
> (symptom: "Bad Gateway" + LED0 stops blinking). The notebook reads buffers one word at a
> time for this reason. If the board does reboot, reload the bitstream
> (`cat red_pitaya_top.bit > /dev/xdevcfg`) before retrying.

Run the sweep cell: it steps the FPGA setpoint 0→180° and fits `measured = slope·setpoint +
offset`. Slope ≈ −1 means the module applies exactly the phase you request; the constant
`offset` is fixed board transport delay (DAC/ADC). Whatever your external scope shows *beyond*
that offset is the divider/cable artifact. (Phase extraction verified to <0.02° at 740 kHz in
a synthetic bit-quantized test.)

*Optional stronger variant (needs a rebuild):* route the module output `pid_dat[0]` into the
scope's CH B input (`.adc_b_i` in `red_pitaya_top.sv`) to compare input vs output **digitally**,
removing even the DAC/ADC analog path — an absolute check of the logic alone. Ask if you want
this wired up.

The DAC path is untouched: the module drives the same `pid_dat[]` nets, which are already
summed and saturated into DAC CH A in the top module.

## Register map (base `0x40300000`, was PID)

| Offset | Name | Format | Meaning |
|--------|------|--------|---------|
| 0x00 | CI    | signed Q2.14   | gain·cos(φ) |
| 0x04 | CQ    | signed Q2.14   | gain·sin(φ) |
| 0x08 | DLY   | uint (0..1022) | ⌊D⌋ integer delay |
| 0x0C | DELTA | uint Q0.14     | δ = D − ⌊D⌋ |
| 0x10 | BYP   | bit            | 1 = bypass (pass input through) |
| 0x14 | STAT  | bit (read-only)| 1 = DLY was written as 0 and has been clamped to 1 — the requested delay is invalid, pick a larger equivalent one (see FIX 4 in the module) |

### High signal frequencies (added during acquisition-system work)

`D = f_clk/(4·f_sig)` drops below 1 above 31.25 MHz, so `DLY` would be written as 0 —
which is broken, because a block-RAM read at the address being written returns the
sample from `DEPTH` clocks ago rather than the current one. The module now clamps to 1
and reports it at 0x14, but the correct fix is host-side: a 90° shift equals 90° plus
any whole number of signal periods, so use

```
D = f_clk/(4·f_sig) + k·f_clk/f_sig        (integer k ≥ 1)
```

and choose the `k` whose fractional part lands closest to 0 or 1, where the two-tap
interpolator is most accurate. Measured/modelled at 40 MHz:

| k | D | DLY | δ | gain error | phase error |
|---|---|-----|---|-----------|-------------|
| 0 | 0.781 | 0 | 0.781 | −2.90 dB | +9.15° |
| 1 | 3.906 | 3 | 0.906 | −1.20 dB | +5.21° |
| **2** | **7.031** | **7** | **0.031** | **−0.39 dB** | **−1.90°** |
| 3 | 10.156 | 10 | 0.156 | −2.05 dB | −7.69° |

Both residual errors are constant at a fixed frequency, so `configure()` can calibrate
them out exactly as it already does for the 2-sample pipeline latency. Below ~10 MHz
none of this matters — the errors there are under 0.12 dB and 0.1°.

## Build

1. **Fix the source set: drop the old `.sv`, add the new `.v`.**
   In the Vivado Tcl console (project open):
   ```tcl
   # remove the broken/renamed .sv if the project still lists it
   remove_files {Test_Project.srcs/sources_1/imports/rp/rtl/classic/red_pitaya_phaseshift.sv}
   # add the corrected Verilog module
   add_files -norecurse {Test_Project.srcs/sources_1/imports/rp/rtl/classic/red_pitaya_phaseshift.v}
   update_compile_order -fileset sources_1
   ```
   (or GUI: *Sources* pane → right-click the old `red_pitaya_phaseshift.sv` →
   *Remove File from Project*; then *Add Sources → Add or create design sources
   → Add Files* and select `red_pitaya_phaseshift.v`.) The edited
   `red_pitaya_top.sv` is already in the project.

2. **Generate the bitstream.** *Flow Navigator → Generate Bitstream* (runs synthesis +
   implementation), or:
   ```tcl
   reset_run synth_1
   launch_runs impl_1 -to_step write_bitstream -jobs 4
   wait_on_run impl_1
   ```
   Output: `Test_Project.runs/impl_1/red_pitaya_top.bit`.

## Deploy to the Red Pitaya

3. Copy the bitstream to the board and load it into the FPGA fabric:
   ```bash
   scp Test_Project.runs/impl_1/red_pitaya_top.bit root@<pitaya-ip>:/root/phaseshift.bit
   ssh root@<pitaya-ip>
   cat /root/phaseshift.bit > /dev/xdevcfg     # classic OS image
   # (newer images: use fpgautil / the redpitaya_fpga loader instead)
   ```

4. Run the notebook **as root** (mmap of `/dev/mem`):
   ```bash
   sudo jupyter notebook   # then open phase_shift_control.ipynb
   ```
   Move the sliders — Phase, Gain, and Signal freq (set this to your generator frequency).
   Register writes take effect immediately.

## Notes / limits

- `DEPTH = 1024` covers signals down to ~30 kHz. For lower frequencies increase `DEPTH`
  and `DLYW` in the module (and update the notebook's `DEPTH`).
- CH B output is held at zero (single-channel test). To use both channels, extend the
  module with a second coefficient/delay set and drive `dat_b_o`.
- The ASG sum in the top module is harmless (zero when idle). If you want the DAC to carry
  only the phase-shifted signal with no chance of ASG interference, leave the arbitrary
  signal generator unconfigured.
- To revert to stock: swap the instantiation in `red_pitaya_top.sv` back to `red_pitaya_pid`
  (the original is preserved in a comment block) and rebuild.
