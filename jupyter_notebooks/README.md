# Notebooks

Every Jupyter notebook in the project, in one place. Moved here on 2026-08-06 from
`acquisition_custom/` and `phaseshift_custom/`, which now hold only the modules, generators and
validators that the Vivado build needs.

```
jupyter_notebooks/
├── acquisition/    the measurement stages, the coil characterisation, the filter designer
├── phaseshift/     the feedback path's own two notebooks
└── tests/          run the coil notebook off the board, against a register-level mock
```

## acquisition/

| Notebook | What it answers |
|---|---|
| `Test Stage 2 - Reference Tone and Timing` | Registers, sample rate, reset, oscillator frequency |
| `Test Stage 3 - Frequency Shifting and Sign Convention` | The mixer, including the mirrored-spectrum check |
| `Test Stage 4 - Decimation Rate Scaling and Noise` | The decimator: rate, scaling, noise, staircase |
| `Test Stage 5 - Droop Correction` | The correction filter against the passband droop |
| `Test Stage 5b - Known Answer Filter Tests` | The filter against answers computed independently |
| `Test Stage 6 - Data Transport to Memory` | The direct-memory-access path, bounds and poison |
| `Test Stage 7 - End to End Measurement` | The whole chain on a known input |
| `Test Stage 8 - Active Feedback on a Known Resonator` | Feedback against the digital emulator |
| `Test Stage 9 - Noisy Measurement Emulation` | A noise-driven measurement, emulated |
| `Test Stage 10 - Feedback Atlas and Operating Point Designer` | The gain/phase atlas and where to sit on it |
| `Test Stage 11 - Parameter Sequencer` | Running a planned sequence of settings |
| `Test Stage 12 - Real Coil Replacements` | The two decisions that only calibrate on an emulator |
| `Test Stage 13 - Input Health` | What is arriving at the input, and whether to trust it |
| `Test Stage 14a - Clock Consistency` | The 125 MHz clock against itself |
| `Test Stage 14b - Clock Against a Reference` | The same clock against an external standard |
| `Test Stage 15 - Find the Resonance` | Locating a resonance with nothing handed over |
| `Test Stage 16 - Drift and Stability` | How much moves, and over what time |
| `Test Stage 17 - Driving Both Electrodes` | Differential and common-mode drive |
| **`Test - Resonator Coil Characterisation`** | **A physical coil on the bench: find it, characterise it, and modify it with feedback.** The flagship |
| `FIR Filter Designer` | Change the correction filter live, no rebuild |

Also here: `COIL_NOTEBOOK_HANDOVER.md` (the coil notebook's own history and open questions),
`STAGE9_PLAN.md` (why Stage 9 is digital), and `Test Stage 10 - atlas plot cell (paste over the
old one).py` (a replacement cell for the Stage 10 atlas figure).

One backup is kept: `Test - Resonator Coil Characterisation.ipynb.bak18`, the version
immediately before the 2026-08-06 rework. The seventeen older ones were deleted.

## phaseshift/

| Notebook | What it does |
|---|---|
| `phase_shift_control.ipynb` | Interactive control of the phase shifter — sliders, live readback |
| `scope_phase_check.ipynb` | Input/output phase measured with the board's own scope |

## tests/

Runs the coil notebook end to end **off the board**, against a mock that patches `os.open`,
`mmap.mmap` and `open` so every line of the notebook's own driver code executes unmodified.
See `tests/README.md`. Two commands:

```
python3 jupyter_notebooks/tests/audit.py       # names used before they exist
python3 jupyter_notebooks/tests/run_mock.py all   # nine scenarios, each with an expected verdict
```

## What did not move, and why

`acquisition_custom/README.md` and `EXPLAINER.md` stayed put: they document the register map and
the acquisition design rather than any notebook, several notebooks cite that path in their own
text, and `build_project.tcl` reads other files from the same folder. The generators
(`gen_fir_coeffs.py`), the source list (`add_acquisition_sources.tcl`) and the validators
(`validate_*.py`) are part of the Vivado build and stayed with it.

`build_project.tcl` runs `tools/verify_notebooks.py` over `jupyter_notebooks/acquisition/*.ipynb`
as a pre-build check, and `tools/run_on_board.ps1` searches both notebook folders by name, so
`.\tools\run_on_board.ps1 "Test Stage 5 - Droop Correction.ipynb"` still works unchanged.
