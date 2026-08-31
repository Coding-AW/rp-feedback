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

Then:

1. Open `http://rp-f007f7.local/` in Chrome.
2. Start or open the Red Pitaya Jupyter application.
3. Browse to `/root/jupyter_notebooks` and open the required notebook.
4. Run cells in order. Read the wiring and safety gate before every hardware
   action; use the notebook's full-shutdown cell after interruption or failure.

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
