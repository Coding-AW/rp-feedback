# Notebooks

Interactive operation and hardware verification are grouped by purpose:

- `acquisition/`: numbered measurement stages, filter design, and coil
  characterisation;
- `feedback/`: phase-shifter control and internal phase measurement.

Run acquisition stages in numeric order. Each notebook states whether it runs
on the Red Pitaya or on the PC and which earlier stages it assumes have passed.
The flagship physical-coil and first-order feedback workflow is
`acquisition/resonator_coil_characterisation.ipynb`. It is standalone, runs in
the Red Pitaya's browser-hosted Jupyter server, and uses only Red Pitaya
measurements. It characterises the coil, verifies maximum Q and maximum shift as
separate operating points, and writes the summary, raw traces, and report.

The off-board acquisition-chain investigation remains in
`acquisition/parameter_constraint_optimisation.ipynb`; it audits configurable
analogue constraints before screening CIC, FIR, FFT, and transport settings.
It does not optimise coil feedback or configure hardware. PI tuning remains
disabled until the physical amplitude plant is measurable.
`acquisition/external_spectrum_analysis.ipynb` remains available only for older
spectrum-analyser CSV data; it is not part of the first-order workflow.

Before using hardware, load a current build and verify its fingerprint:

```powershell
.\project.ps1 deploy
.\project.ps1 check
```

Notebook filenames are stable, lowercase, and sortable. Keep notebook outputs
cleared before committing; `project.ps1 test` audits all acquisition notebooks.
The off-board mock and its scenarios live under `tests/`.
