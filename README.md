# Red Pitaya feedback for a Penning-trap resonator

Digital feedback system for the single-electron Penning trap, built on a Red Pitaya
STEMlab 125-14. Custom field-programmable gate array (FPGA) logic returns a
gain- and phase-controlled copy of the resonator signal from IN1 to a trap electrode
through OUT1, and records the same signal at narrow bandwidth for spectral analysis.
Jupyter notebooks running on the board control it and fit the results.

**Status.** On the trap, feedback raises the resonator's Q or shifts its frequency,
depending on the chosen phase. Self-excited-oscillator and proportional-integral-derivative
control of a trapped electron have only been rehearsed against the on-chip digital
resonator; they are not yet demonstrated on a real electron.

```text
trap pickup → amplifier → IN1 ─┬─ quarter-period delay + gain/phase rotation → OUT1 → trap electrode
                               └─ mixer → decimating filters → board memory → notebook spectrum and fit
```

## Repository

| Path | Contents |
|---|---|
| `fpga/` | Project-owned field-programmable gate array sources, constraints, filter coefficients, upstream pin and golden manifest. See [`fpga/README.md`](fpga/README.md). |
| `bitstream/` | The qualified bitstream (7 August 2026, hardware identifier `FE76AE09`) and its identity record. Ready to load; no Vivado needed. |
| `notebooks/` | The two standalone notebooks that run on the board. See [`notebooks/README.md`](notebooks/README.md). |
| `board/check_system.py` | Health check run on the board: bitstream identity, acquisition state, memory access. It briefly writes and restores two registers, so run it with feedback off. |
| `project.ps1` | One script for setup, tests, build, deployment, notebook copy and board check. |
| `tools/` | Offline checks (`verify_golden.py`, `verify_rtl.py`, `verify_notebooks.py`) and the Vivado build script `vivado_build.tcl`. |
| `tests/` | Offline tests that run the notebook cells against mock registers; no board needed. |

## Set up on a new computer

You need Windows PowerShell, Git, Python 3 with NumPy, SciPy and Matplotlib, and
OpenSSH (`ssh`, `scp`). The board needs the classic Red Pitaya operating system with root
access and its Jupyter application. Vivado is only needed to rebuild the bitstream.

```powershell
git clone https://github.com/Coding-AW/rp-feedback.git
cd rp-feedback
$env:RP_BOARD = 'root@rp-f007f7.local'   # your board's address
.\project.ps1 test      # offline checks and tests
.\project.ps1 deploy    # load the qualified bitstream
.\project.ps1 check     # confirm hardware identifier FE76AE09 on the board
.\project.ps1 sync      # copy both notebooks to /root/jupyter_notebooks
```

Then open `http://rp-f007f7.local/` in a browser, go to Development → Python
programming (Jupyter), open `/root/jupyter_notebooks/test_noise_passive_feedback.ipynb`
and run its cells in order. Rebooting the board restores its stock image, so run
`deploy` again after every reboot.

Without the script, the same load is:

```text
scp bitstream/red_pitaya_top.bit root@rp-f007f7.local:/root/
ssh root@rp-f007f7.local "cat /root/red_pitaya_top.bit > /dev/xdevcfg"
```

## Rebuild the bitstream (optional)

Install Vivado 2020.1 (other versions are rejected), then:

```powershell
.\project.ps1 build              # downloads the pinned upstream on first use; 15–25 min
.\project.ps1 deploy -UseBuild   # load your build instead of the qualified copy
```

`build` downloads RedPitaya-FPGA v0.94 at the commit and checksum in
`fpga/upstream.lock`, lays `fpga/` over it, reruns the tests, synthesises and
implements from scratch, and refuses the result unless timing passes and the resource
counts match the qualified design. `deploy` refuses any bitstream whose
`bitstream_id.txt` does not record `FE76AE09` and a timing pass.

The scripted rebuild has not yet been seen to finish: its only full attempt, on
31 August 2026, stopped right after Vivado launched. The qualified bitstream was built
from the same sources in the earlier Vivado project layout; `tools/verify_golden.py`
confirms the sources still match it.

Notebook settings (phase, gain, bandwidth, record length, averaging) never need a
rebuild. Any functional change under `fpga/` does, and is rejected by the golden-source
check until the new design is re-qualified (see [`fpga/README.md`](fpga/README.md)).

## Checks

`.\project.ps1 test` runs, in order:

1. `tools/verify_golden.py` — the qualified sources differ from the manifest only in
   comments.
2. `tools/verify_rtl.py` — every port connection in the Verilog names a port that exists.
3. `tools/verify_notebooks.py` — every notebook call matches its function and every
   name exists before it is used.
4. `python -m unittest discover -s tests -t .` — the tests in `tests/`.

## Known issues

- **Phase-shifter latency.** The notebooks correct commanded phases for a 3-sample
  datapath latency (`PhaseShift.LATENCY = 3`). Register-transfer-level simulation in
  October 2026 measured 4 samples, so commanded phases arrive about 118° late at
  40.9 MHz. The offset is constant, and working phases are found by measurement, so
  results within a series are consistent; absolute phase labels are not.
- **Bypass bit not cleared on shutdown.** `full_shutdown()` and `disable_held_feedback()`
  never touch the phase shifter's bypass register (0x40300010); only
  `config_delay()` clears it. Bypass passes IN1 straight to OUT1.

## History

The development log, older notebooks and documentation are in git history; the
cleanup removed them from the working tree. For example:

```text
git show d0a264a:docs/development-history.md   # dated bring-up notes cited in code comments
git show 8279c5b:notebooks/feedback_gain_phase_map.py   # archived gain–phase map
```

## License

Berkeley Software Distribution (BSD) 3-Clause; see `LICENSE` and `THIRD_PARTY_NOTICES.md`.
