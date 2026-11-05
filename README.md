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
| `tools/` | The offline checks (see "Checks and tests") and the Vivado build script that `fpga/build.tcl` hands over to. |
| `tests/` | Tests that run the notebook code against simulated registers, so no board is needed. |

## Getting started on a new computer

**You need:** `ssh` and `scp` (part of Windows 10 and 11, macOS and Linux) and a web browser.
The board needs the standard Red Pitaya operating system with root access and its Jupyter
application. Vivado is only needed to rebuild the bitstream.

Copy the files to the board once, and a notebook again whenever it changes:

```text
scp bitstream/red_pitaya_top.bit bitstream/bitstream_id.txt root@rp-f007f7.local:/root/
scp board/check_system.py root@rp-f007f7.local:/root/
scp notebooks/test_noise_passive_feedback.ipynb root@rp-f007f7.local:/root/jupyter_notebooks/
scp notebooks/resonator_coil_manual_high_k.ipynb root@rp-f007f7.local:/root/jupyter_notebooks/
```

If `/root/jupyter_notebooks` does not exist yet, create it first with
`ssh root@rp-f007f7.local mkdir -p /root/jupyter_notebooks`.

After every power-up or reboot (which brings back the stock bitstream), load the design:

```text
ssh root@rp-f007f7.local
cat /root/red_pitaya_top.bit > /dev/xdevcfg    # load the qualified design
python3 /root/check_system.py                   # optional health check: expect 0xFE76AE09
```

Then open `http://rp-f007f7.local/` in a browser, choose Development → Python programming to
reach Jupyter, open `/root/jupyter_notebooks/test_noise_passive_feedback.ipynb`, and run its
cells in order.

The offline tests (below) all passed when the system was set up and again in November 2026.
They check the code, not the board, so rerun them only after editing code.

## Rebuilding the bitstream (optional)

You need Vivado 2020.1 (other versions are refused), Git and Python 3. From the repository folder:

```text
git clone https://github.com/RedPitaya/RedPitaya-FPGA.git .cache/upstream            # once
git -C .cache/upstream checkout fc268bd47cd029c20ec8a5194f16661902f6d650             # the commit in fpga/upstream.lock
vivado -mode batch -source fpga/build.tcl -tclargs . .cache/upstream                 # 15–25 minutes
```

If Vivado is not on the `PATH`, use its full path, for example
`C:\Xilinx\Vivado\2020.1\bin\vivado.bat`. `fpga/build.tcl` checks that the upstream checkout is at
the pinned commit and that the qualified sources are unchanged apart from comments
(`tools/verify_golden.py`), copies the files in `fpga/` over the upstream design, and builds
from scratch. The result is refused unless it meets timing and uses exactly the qualified
design's resources. The bitstream and its `bitstream_id.txt` are written to
`.cache/upstream/prj/v0.94/project/redpitaya.runs/impl_1/`; copy both to `/root` on the board
and load them as above. To return to the qualified design, copy the two files in `bitstream/`
again.

The scripted rebuild has not yet been seen to finish: its only full attempt, on 31 August 2026,
stopped right after Vivado started. The qualified bitstream was built from the same sources in
the project's earlier Vivado layout, and `tools/verify_golden.py` confirms the sources have not
changed since.

Notebook settings (phase, gain, bandwidth, record length, averaging) never need a rebuild.
Changes to the gateware's behaviour do, and are refused until the new design has been
re-qualified; see [`fpga/README.md`](fpga/README.md).

## Checks and tests

All of these passed when the system was set up and again in November 2026. They need Python 3
with NumPy, SciPy and Matplotlib, no board, and about 20 seconds. Run them from the repository
folder after editing code:

```text
python tools/verify_golden.py        # qualified gateware sources match the manifest, ignoring comments
python tools/verify_rtl.py           # every module connection names a port that exists
python tools/verify_notebooks.py notebooks/test_noise_passive_feedback.ipynb notebooks/resonator_coil_manual_high_k.ipynb
python -m unittest discover -s tests -t .    # the 58 notebook tests against simulated registers
```

`verify_notebooks.py` checks that every function call in the notebooks matches its definition
and that every name exists before it is used.

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
git show 606f76f:notebooks/feedback_gain_phase_map.py   # the archived gain–phase map
```

The gateware builds on the Red Pitaya v0.94 design from the
[Red Pitaya gateware repository](https://github.com/RedPitaya/RedPitaya-FPGA); the files in `fpga/`
that come from it are modified versions.
