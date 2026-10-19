# Gateware

Project-owned field-programmable gate array (FPGA) sources for the Red Pitaya
STEMlab 125-14 (Zynq `xc7z010clg400-1`, 125 MHz sample clock). They are laid over the
stock RedPitaya-FPGA v0.94 design, which `project.ps1 setup` downloads at the commit
pinned in `upstream.lock`. Every module's full register map is in its file header.

## Files

| File | Role |
|---|---|
| `red_pitaya_top.sv` | Top level: connects the modules to the processor bus slots and sums the outputs |
| `red_pitaya_phaseshift.v` | Feedback path: quarter-period delay, gain/phase rotation, OUT2 monitor |
| `red_pitaya_acq.v` | Acquisition system: register block that wires the four stages below |
| `red_pitaya_acq_dds.v` | 32-bit local-oscillator generator |
| `red_pitaya_acq_mixer.v` | Mixes IN1 down to complex baseband (I, Q) |
| `red_pitaya_acq_cic.v` | Four-stage cascaded integrator-comb (CIC) decimator, R = 64…4096 |
| `red_pitaya_acq_fir.v` | 309-tap droop-correction finite impulse response (FIR) filter, active for R ≥ 256 |
| `red_pitaya_acq_dma.v` | Writes the I/Q stream into a bounded region of board memory |
| `axi_master.v` | Stock memory-bus master (used by the writer through `axi_wr_fifo`), changed so writes pass the processor's TrustZone check |
| `red_pitaya_resonator.v` | Digital resonator: a known-answer stand-in for the coil, off at power-on |
| `red_pitaya_sequencer.v` | Timed coefficient sequencer: built and present, not used by either notebook |
| `red_pitaya_scope.v` | Stock scope, with its equaliser removed and an acquisition tap added |
| `fir_coeffs.vh`, `fir_params.vh` | Qualified finite impulse response (FIR) coefficients (155 stored, mirrored to 309) and sizes |
| `build_id.vh` | Fixed hardware identifier `FE76AE09`, read back at 0x40600048 |
| `systemZ10.tcl` | Processor block design |
| `red_pitaya.xdc`, `project.xdc`, `red_pitaya_impl.xdc` | Pin, timing and implementation-only constraints |
| `upstream.lock` | Upstream repository, commit, archive checksum, board, part and Vivado version |
| `golden_manifest.json` | Hashes of the qualified sources (comments ignored) |
| `build.tcl` | Vivado entry point; generates the upstream project, then runs `tools/vivado_build.tcl` |

## Register slots

| Base address | Module |
|---|---|
| 0x40000000 | Housekeeping (stock) |
| 0x40100000 | Scope (stock, modified) |
| 0x40200000 | Signal generator (stock) |
| 0x40300000 | Phase shifter (replaces the stock proportional-integral-derivative controller) |
| 0x40400000 | Digital resonator |
| 0x40500000 | Empty |
| 0x40600000 | Acquisition system |
| 0x40700000 | Parameter sequencer |

OUT1 = generator A + phase-shifter output; OUT2 = generator B + OUT2 monitor. Each is
saturated to 14 bits.

## Signal paths

- **Feedback (IN1 → OUT1).** Output = A cos φ · I + A sin φ · Q, where Q is IN1 delayed
  by a quarter period (whole clocks plus an interpolated fraction). Coefficients are
  signed Q2.14; "feedback off" means both coefficients are zero, not the bypass bit.
  The board's loop delay τ of about 120–128 ns sets a delay-limited feedback bandwidth
  of roughly 1/(2τ) ≈ 3.9 MHz.
- **Acquisition (IN1 → memory).** Local oscillator → mixer → cascaded integrator-comb
  (CIC) decimator → FIR filter (bypassed automatically below R = 256, where it cannot
  keep up) → memory writer. The notebooks read the record and compute the spectrum.

## Qualification

The design was qualified on 7 August 2026: timing met with +0.010 ns worst slack and
0 failing endpoints; 8234 look-up tables, 7679 registers, 36.5 block-memory tiles and
26 multiplier blocks. That build is `bitstream/red_pitaya_top.bit`.

`tools/verify_golden.py` compares every listed source, with comments stripped, against
`golden_manifest.json`, and `tools/vivado_build.tcl` checks the same resource counts
after synthesis. A functional change is therefore rejected until it has been
re-qualified (simulation, timing and hardware tests) and the manifest replaced.
Comment-only edits pass.

Comments in these files cite dated entries (for example 2026-07-30) from the
development log, which is kept in git history:
`git show d0a264a:docs/development-history.md`.
