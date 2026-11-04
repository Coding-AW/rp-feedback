# Gateware

These are the project's own field-programmable gate array (FPGA) sources for the Red Pitaya
STEMlab 125-14, whose chip is a Zynq `xc7z010clg400-1` sampling at 125 MHz. They are not a
complete design on their own: `project.ps1 build` downloads the upstream Red Pitaya v0.94 design
at the commit pinned in `upstream.lock`, and these files replace or add to its files. Each
module's register map is written out in full at the top of its source file.

## Files

| File | What it is |
|---|---|
| `red_pitaya_top.sv` | Top level. Connects each module to its slot on the processor's register bus and adds the module outputs together. |
| `red_pitaya_phaseshift.v` | The feedback path: quarter-period delay, gain/phase rotation and the optional OUT2 monitor. |
| `red_pitaya_acq.v` | The acquisition system's register block, which connects the four stages below. |
| `red_pitaya_acq_dds.v` | Local oscillator: a numerically generated sine and cosine at the chosen frequency. |
| `red_pitaya_acq_mixer.v` | Multiplies IN1 by the local oscillator, shifting the band of interest down to zero frequency as an in-phase (I) and quadrature (Q) pair. |
| `red_pitaya_acq_cic.v` | Cascaded integrator-comb (CIC) filter: a four-stage decimator that keeps one sample in R, with R = 64…4096. |
| `red_pitaya_acq_fir.v` | Finite impulse response (FIR) filter, 309 taps, that flattens the droop of the cascaded integrator-comb (CIC) filter. It is active only for R ≥ 256, because it cannot keep up at faster rates. |
| `red_pitaya_acq_dma.v` | Writes the I/Q stream into a fixed, bounded region of board memory. |
| `axi_master.v` | The stock memory-bus master, used by the writer through `axi_wr_fifo`. Changed so its writes pass the processor's TrustZone memory check. |
| `red_pitaya_resonator.v` | Digital resonator: a stand-in for the coil with a known frequency and Q, used to check the measurement chain. Off at power-on. |
| `red_pitaya_sequencer.v` | Sequencer that can switch feedback coefficients at exact times. Built into the bitstream but not used by either notebook. |
| `red_pitaya_scope.v` | The stock oscilloscope, with its equaliser removed and an acquisition tap added. The notebooks use it for raw input checks. |
| `fir_coeffs.vh`, `fir_params.vh` | The qualified finite impulse response (FIR) coefficients (155 stored, mirrored to 309) and the filter sizes. |
| `build_id.vh` | The fixed hardware identifier `FE76AE09`, which software reads back at 0x40600048 to confirm the right bitstream is loaded. |
| `systemZ10.tcl` | The processor block design. |
| `red_pitaya.xdc`, `project.xdc`, `red_pitaya_impl.xdc` | Pin assignments, timing constraints and implementation-only constraints. |
| `upstream.lock` | Which upstream design to download: repository, commit, archive checksum, board, chip and Vivado version. |
| `golden_manifest.json` | Fingerprints of the qualified sources, used to detect changes in behaviour. |
| `build.tcl` | Vivado's entry point: creates the upstream project, then runs `tools/vivado_build.tcl`. |

## Register slots

The processor reaches each module through its own block of addresses:

| Base address | Module |
|---|---|
| 0x40000000 | Housekeeping (stock) |
| 0x40100000 | Oscilloscope (stock, modified) |
| 0x40200000 | Signal generator (stock) |
| 0x40300000 | Phase shifter (in place of the stock proportional-integral-derivative controller) |
| 0x40400000 | Digital resonator |
| 0x40500000 | Empty |
| 0x40600000 | Acquisition system |
| 0x40700000 | Sequencer |

The outputs are sums, each limited to the 14-bit range: OUT1 is signal-generator channel A plus
the phase-shifter output, and OUT2 is channel B plus the OUT2 monitor.

## Signal paths

- **Feedback (IN1 → OUT1).** The phase shifter delays IN1 by a quarter of a period, in whole
  clock cycles plus an interpolated fraction, giving a copy shifted by 90°. It outputs
  A cos φ × (input) + A sin φ × (delayed input), so the two coefficients set gain A and phase φ.
  Each coefficient is a signed 16-bit number in which 16384 means 1.0. Feedback is off when
  both are zero; the bypass bit is a separate test mode that passes IN1 straight through. The
  loop delay τ of about 120–128 ns limits the useful feedback bandwidth to roughly
  1/(2τ) ≈ 3.9 MHz.
- **Acquisition (IN1 → memory).** Local oscillator and mixer, then the CIC filter, then the FIR
  filter (bypassed automatically below R = 256), then the memory writer. The notebooks read the
  record from memory and compute the spectrum.

## Qualification and the golden-source guard

The design was qualified on 7 August 2026. Timing was met with 0.010 ns to spare and no failing
paths, and it used 8234 look-up tables, 7679 registers, 36.5 block-memory tiles and 26 multiplier
blocks. That build is `bitstream/red_pitaya_top.bit`.

Two checks keep the sources tied to that build. `tools/verify_golden.py` compares each listed
source with `golden_manifest.json` after stripping comments, so editing comments is allowed but
any change in behaviour is refused. After synthesis, `tools/vivado_build.tcl` checks that the
resource counts above are reproduced exactly. To change the design on purpose, re-qualify it
with simulation, timing and hardware tests, then replace the manifest.

Some comments cite dated entries (for example 2026-07-30) from the development log, which is
kept in git history: `git show d0a264a:docs/development-history.md`.
