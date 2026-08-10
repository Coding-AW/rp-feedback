# Notebooks

Interactive operation and hardware verification are grouped by purpose:

- `acquisition/`: numbered measurement stages, filter design, and coil
  characterisation;
- `feedback/`: phase-shifter control and internal phase measurement.

Run acquisition stages in numeric order. Each notebook states whether it runs
on the Red Pitaya or on the PC and which earlier stages it assumes have passed.
The flagship physical-coil workflow is
`acquisition/resonator_coil_characterisation.ipynb`.
The off-board parameter investigation is
`acquisition/parameter_constraint_optimisation.ipynb`; it explains the CIC,
FIR, FFT, feedback, and PI trade-offs and never configures hardware.
Spectrum-analyser CSV exports are fitted separately in
`acquisition/external_spectrum_analysis.ipynb`; the hardware notebook does not
mix acquisition state with off-board data analysis.

Before using hardware, load a current build and verify its fingerprint:

```powershell
.\project.ps1 deploy
.\project.ps1 check
```

Notebook filenames are stable, lowercase, and sortable. Keep notebook outputs
cleared before committing; `project.ps1 test` audits all acquisition notebooks.
The off-board mock and its scenarios live under `tests/`.
