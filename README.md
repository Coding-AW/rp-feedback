# Red Pitaya Penning-trap feedback

This repository is the minimum handover set for the Red Pitaya STEMlab 125-14
(`XC7Z010`) used to measure a resonator and return phase-controlled feedback to
a Penning-trap electrode.

## What the system does

```text
electrode/resonator -> IN1 -> ADC -> phase + gain -> OUT1 -> electrode
                           \-> mixer -> CIC -> FIR -> DDR -> notebook
                                      input/noise monitor -> OUT2 (optional)
```

The FPGA feedback path runs continuously at 125 MHz. It returns a scaled,
phase-shifted copy of IN1 through OUT1. The dissipative feedback quadrature
changes the resonator linewidth and therefore Q; the reactive quadrature moves
the resonant frequency. OUT2 is an optional observation output and is not an
independent measurement because it contains the same ADC data.

The primary measurement no longer relies on a swept injected tone.
`test_noise_passive_feedback.ipynb` measures the passive voltage-noise spectrum
at IN1, removes the independently calibrated acquisition response, and fits the
broad resonator noise peak above the electronics floor. Feedback-on measurements
are bracketed by feedback-off spectra so drift is not mistaken for a Q or
frequency change. A narrow electron feature, when present, must be fitted
separately from the broad resonator envelope.

## Files to hand over

- `fpga/`: complete project-owned, timing-qualified HDL, constraints,
  coefficients, build metadata, and pinned upstream revision.
- `notebooks/test_noise_passive_feedback.ipynb`: primary passive-noise and
  electrode-feedback commissioning workflow.
- `notebooks/resonator_coil_manual_high_k.ipynb`: focused driven-response
  fallback for manually probing the approach to high Q/K.
- `project.ps1`: setup, verification, build, deployment, notebook transfer, and
  board health check.
- `tools/` and `tests/`: offline checks called by `project.ps1 test`.
- `software/check_system.py`: read-only board fingerprint and register check.

The notebooks are deliberately standalone because the Red Pitaya receives only
those files. Analysis and hardware classes are visible in each notebook rather
than hidden behind an installed Python package.

This handover can reproduce and operate the qualified `FE76AE09` design. It is
not a complete FPGA-development laboratory: functional HDL edits are rejected
by the golden-source guard, and the historical behavioural/simulation suite is
not included. Qualifying changed RTL requires restoring or creating appropriate
simulation, timing and hardware tests and deliberately replacing the golden
manifest after they pass.

## Requirements

PC/build machine:

- Windows PowerShell, Git, Python 3 and OpenSSH (`ssh` and `scp`).
- Xilinx Vivado 2020.1. Other Vivado releases are rejected.
- Internet access for the first `setup`, or the already verified pinned archive
  in `.cache/`.

Red Pitaya and instruments:

- STEMlab 125-14 / Zynq-7010 running the classic OS with `/dev/xdevcfg` and
  root access to `/dev/mem`.
- Python with NumPy, SciPy, Matplotlib and Jupyter available on the board.
- A device-tree reserved DMA region (`labuf`) discoverable by the notebooks.
- The documented 39 MHz resonator chain, 30 dB feedback return pad, air gap,
  2.2 pF sensing capacitor, follower and ZFL-500LN+ stage.
- A 50 ohm spectrum analyser for the independent resonance and OUT2 checks.

The notebook configuration cell is the authority for voltage limits, amplifier
ratings, analyser settings and the precise wiring identity. Do not run a
hardware-action cell until those values match the bench.

## End-to-end workflow

Run from this directory in Windows PowerShell. Vivado 2020.1 and OpenSSH (`ssh`
and `scp`) must be available. The first setup also needs internet access.

```powershell
$env:RP_BOARD = 'rp-f007f7.local'
.\project.ps1 setup
.\project.ps1 test
.\project.ps1 build
.\project.ps1 deploy
.\project.ps1 check
.\project.ps1 sync
```

`setup` downloads the exact RedPitaya-FPGA v0.94 source named in
`fpga/upstream.lock`, verifies it, and overlays `fpga/`. `build` repeats the
tests, runs synthesis and implementation, requires timing to pass, and creates:

```text
.cache/upstream/prj/v0.94/project/redpitaya.runs/impl_1/red_pitaya_top.bit
```

`deploy` copies that verified image over SSH and loads it through
`/dev/xdevcfg`. `check` confirms hardware ID `FE76AE09`. `sync` copies the two
standalone notebooks to `/root/jupyter_notebooks` on the board.

The build is reproducible from the tracked files because `upstream.lock` pins
the upstream repository, commit, board, part, Vivado version and archive hash;
`project.ps1` overlays every project-owned HDL file; and the golden manifest
checks the functional HDL and constraints before Vivado starts. A successful
build is usable only when implementation timing reports `PASS`.

Then:

1. Open `http://rp-f007f7.local/` in Chrome.
2. Start or open the Red Pitaya Jupyter application.
3. Browse to `/root/jupyter_notebooks` and open the required notebook.
4. Run cells in order. Read the wiring and safety gate before every hardware
   action; use the notebook's full-shutdown cell after interruption or failure.

## Experiment order

Use `test_noise_passive_feedback.ipynb` as the primary experiment:

1. Review the topology and limits, initialise in the full-safe state, and
   require FPGA build ID `FE76AE09`.
2. Measure IN1 headroom and DC offsets with feedback and generators off.
3. With the feedback gap disconnected, validate ADC/FFT scaling, IQ quality,
   alias rejection and acquisition-filter response using a known signal.
4. Measure the bare-input, powered-amplifier and complete-resonator noise
   baselines. Power down before changing analogue connections.
5. Find the passive resonance at three LO centres. Accept it only if the fitted
   absolute frequency remains fixed as the digital LO moves.
6. Cross-check centre frequency and Q using the independent spectrum analyser.
7. Commission OUT2 as a monitor only; it is not independent evidence because
   it comes from the same ADC stream.
8. Reconnect the attenuated air-gap return, find the smallest observable safe
   feedback coefficient, then measure the full phase circle and paired gain
   ladders with feedback-off brackets.
9. Freeze a calibration, review one requested setting, apply it once, verify
   recovery after switch-off, and export JSON/NPZ evidence.

Use `resonator_coil_manual_high_k.ipynb` only as a driven-response diagnostic
or controlled high-K follow-up. It does not replace the passive-noise baseline,
three-LO invariance test or independent analyser check.

These notebooks cover the current commissioning, passive noise-floor,
resonance, phase-axis, Q-control and frequency-shift experiments. They do not
emulate an electron or prove an absolute electrode voltage: the narrow electron
feature and the air-gap transfer require physical measurements.

After editing locally, rerun `project.ps1 sync`. This is intentionally one-way:
the PC repository is the source of truth. Reload in Chrome only after saving or
closing browser-side edits, otherwise Jupyter can overwrite the uploaded file.

## When a rebuild is required

Notebook configuration, phase, gain, acquisition bandwidth, FFT length, and
averaging do not require a rebuild. Any executable change under `fpga/` does.
The golden-source check rejects such a change until the modified design has
passed timing and hardware validation and `fpga/golden_manifest.json` has been
replaced as a new qualified baseline.

`project.ps1 clean` removes only generated Vivado project output under the
pinned upstream cache. Rebooting the Red Pitaya restores its startup FPGA image,
so deploy again after a reboot.

## Acceptance checklist

- `project.ps1 test` passes the golden-source, RTL-interface, notebook-static
  and 43 fail-closed analysis/safety/interface tests.
- `project.ps1 build` produces a bitstream and `bitstream_id.txt` with timing
  `PASS` and hardware ID `FE76AE09`.
- `project.ps1 deploy` and `check` succeed against the intended board.
- Both notebooks appear under `/root/jupyter_notebooks` after `sync`.
- The passive notebook accepts input safety, analyser calibration, LO
  invariance, independent resonance agreement and feedback-off recovery before
  a feedback recommendation is used.
