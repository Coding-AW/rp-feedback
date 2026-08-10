# Changelog

Notable user-facing changes are recorded here. Detailed development notes from
bring-up are preserved in [`docs/development-history.md`](docs/development-history.md).

## Unreleased

- Reorganized the repository as a compact STEMlab 125-14 customization layer.
- Replaced the committed Vivado project and stock v0.94 sources with a checked,
  pinned upstream download.
- Added one `project.ps1` interface for setup, test, build, deployment, and board
  checks.
- Consolidated FPGA sources, software, notebooks, tests, and documentation into
  stable top-level areas.
- Preserved the latest feedback, resonator, sequencer, notebook, and RTL-test
  work while moving it into the new layout.
- Restored and locked the timing-qualified 7 August design at hardware ID
  `FE76AE09`; clean builds reproduce WNS `+0.010 ns` and the golden synthesis
  utilization.
- Added a comment-insensitive HDL/XDC guard, external build provenance,
  timing-gated deployment, privacy cleanup, and Red Pitaya attribution.

## 2026-08-07

- Verified acquisition, feedback, digital resonator, parameter sequencer, and
  staged notebook workflows on the Red Pitaya STEMlab 125-14.
