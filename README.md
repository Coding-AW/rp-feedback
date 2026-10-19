# Red Pitaya feedback for a Penning-trap resonator

This repository contains a digital feedback system for the single-electron Penning trap,
built on a Red Pitaya STEMlab 125-14 board. The board reads the signal from the trap's
resonator, feeds a copy back to a trap electrode with a chosen gain and phase, and records the
same signal so its spectrum can be measured. Depending on the phase, the feedback either
narrows the resonance (raising its quality factor Q) or shifts its frequency.

**Status.** Both effects have been measured on the trap. Controlling a trapped electron
directly — as a self-excited oscillator, or with proportional-integral-derivative control —
has only been rehearsed against the board's built-in digital resonator, not yet on a real
electron.

## How it works

```text
trap pickup -> amplifier -> IN1 -+- delay + gain/phase -> OUT1 -> high-pass filter -> trap electrode   (feedback)
                                 |
                                 +- mixer -> decimating filters -> board memory -> notebook             (measurement)
```

- **Feedback.** Custom field-programmable gate array (FPGA) logic delays the input by a
  quarter of a period to obtain a second, 90°-shifted copy, and adds the two in the
  proportions set by the gain and phase. This runs continuously at 125 million samples per
  second.
- **Measurement.** Separately, the logic mixes the band around the resonance down to zero
  frequency, reduces the sample rate with decimating filters, and writes the result into the
  board's memory. Jupyter notebooks running on the board read it, compute the spectrum and
  fit it; they also set the gain, phase and filters through the board's registers.

## What is in the repository

| Path | Contents |
|---|---|
| `fpga/` | The custom gateware: the field-programmable gate array sources, constraints, filter coefficients, the record of which upstream Red Pitaya design to build on, and the manifest that guards the qualified sources. See [`fpga/README.md`](fpga/README.md). |
| `bitstream/` | The qualified bitstream (built 7 August 2026, hardware identifier `FE76AE09`) and its identity record. It can be loaded directly; Vivado is not needed. |
| `notebooks/` | The two notebooks that run on the board. See [`notebooks/README.md`](notebooks/README.md). |
| `board/check_system.py` | A health check that runs on the board: is the right bitstream loaded, and is the acquisition system working? It briefly writes and restores two registers, so run it with feedback off. |
| `project.ps1` | One script for everything done from the computer: tests, building, loading the bitstream, copying the notebooks and running the health check. |
| `tools/` | The offline checks run by `project.ps1 test`, and the Vivado build script. |
| `tests/` | Tests that run the notebook code against simulated registers, so no board is needed. |

## Getting started on a new computer

**You need:** Windows PowerShell, Git, Python 3 with NumPy, SciPy and Matplotlib, and OpenSSH
(`ssh` and `scp`). The board needs the standard Red Pitaya operating system with root access
and its Jupyter application. Vivado is only needed to rebuild the bitstream.

```powershell
git clone https://github.com/Coding-AW/rp-feedback.git
cd rp-feedback
$env:RP_BOARD = 'root@rp-f007f7.local'   # the board's address
.\project.ps1 test      # 1. run the offline checks and tests
.\project.ps1 deploy    # 2. load the qualified bitstream onto the board
.\project.ps1 check     # 3. confirm the board reports FE76AE09
.\project.ps1 sync      # 4. copy both notebooks to /root/jupyter_notebooks
```

Then open `http://rp-f007f7.local/` in a browser, choose Development → Python programming to
reach Jupyter, open `/root/jupyter_notebooks/test_noise_passive_feedback.ipynb`, and run its
cells in order. Rebooting the board brings back its stock bitstream, so run `deploy` again after
every reboot.

Loading the bitstream by hand does the same as `deploy`:

```text
scp bitstream/red_pitaya_top.bit root@rp-f007f7.local:/root/
ssh root@rp-f007f7.local "cat /root/red_pitaya_top.bit > /dev/xdevcfg"
```

## Rebuilding the bitstream (optional)

Install Vivado 2020.1 (other versions are refused), then:

```powershell
.\project.ps1 build              # takes 15–25 minutes
.\project.ps1 deploy -UseBuild   # load your build instead of the qualified copy
```

`build` downloads the upstream Red Pitaya v0.94 design at the exact commit recorded in
`fpga/upstream.lock`, checks the download against its checksum, replaces the upstream files
with the ones in `fpga/`, runs the tests, then synthesises and implements the design from
scratch. The result is refused unless it meets timing and uses exactly the qualified design's
resources. `deploy` refuses any bitstream whose `bitstream_id.txt` does not record `FE76AE09`
and a timing pass.

The scripted rebuild has not yet been seen to finish: its only full attempt, on 31 August 2026,
stopped right after Vivado started. The qualified bitstream was built from the same sources in
the project's earlier Vivado layout, and `tools/verify_golden.py` confirms the sources have not
changed since.

Notebook settings (phase, gain, bandwidth, record length, averaging) never need a rebuild.
Changes to the gateware's behaviour do, and are refused until the new design has been
re-qualified; see [`fpga/README.md`](fpga/README.md).

## Checks and tests

`.\project.ps1 test` runs four checks in turn:

1. `tools/verify_golden.py` — the qualified gateware sources match the manifest, ignoring comments.
2. `tools/verify_rtl.py` — every module connection in the gateware names a port that exists.
3. `tools/verify_notebooks.py` — every function call in the notebooks matches its definition,
   and every name exists before it is used.
4. The tests in `tests/` (`python -m unittest discover -s tests -t .`).

## Known issues

- **Feedback phases are offset by a constant.** The notebooks assume the phase shifter delays
  the signal by 3 samples; simulation of the gateware in October 2026 showed 4. Every commanded
  phase therefore arrives about 118° late at 40.9 MHz. Because working phases are found by
  measurement, results stay consistent, but the phase values in degrees are offset.
- **Shutdown leaves the bypass bit alone.** `full_shutdown()` and `disable_held_feedback()` do
  not clear the phase shifter's bypass register (0x40300010), which passes IN1 straight to OUT1.
  Only `config_delay()` clears it.

## History

The cleanup removed the old development log, notebooks and documents from the working tree,
but they remain in git history. For example:

```text
git show d0a264a:docs/development-history.md            # the dated notes cited in code comments
git show 8279c5b:notebooks/feedback_gain_phase_map.py   # the archived gain–phase map
```

The gateware builds on the Red Pitaya v0.94 design from the
[Red Pitaya gateware repository](https://github.com/RedPitaya/RedPitaya-FPGA); the files in `fpga/`
that come from it are modified versions.
