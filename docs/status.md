# Project status

The target is a Red Pitaya STEMlab 125-14 using Vivado 2020.1 and the pinned
v0.94 baseline recorded in `fpga/upstream.lock`.

## Verified on hardware

- Feedback phase shifter and gain path; measured loop delay: 119.87 ns.
- Acquisition mixer, DDS, CIC decimator, FIR correction, and diagnostic taps.
- Known-answer filter tests and end-to-end DDR capture through AXI port 0.
- Digital resonator and parameter sequencer test paths.
- Notebook stages 1-10 and subsequent hardware-characterisation workflows.

## Timing-qualified build

- Fixed hardware ID: `FE76AE09` at register `0x48`.
- Clean Vivado 2020.1 rebuild verified on 9 August 2026.
- Timing: WNS `+0.010 ns`, TNS `0`, zero setup, hold, or pulse-width failures.
- Golden synthesis resources: 8,234 LUTs, 7,679 registers, 36.5 BRAM tiles,
  and 26 DSPs.
- The comment-insensitive source guard covers all 18 project-owned HDL and XDC
  files. Changing an executable token stops setup, testing, and building.

## Known limits

- AXI port 1 is diagnostic-only because the board's processor-side HP1 setup
  drops the Q half of 64-bit samples. Use AXI port 0.
- TrustZone memory permissions may need opening after reboot for DDR captures;
  the board utilities diagnose this condition.
- Hardware notebooks require hardware ID `FE76AE09` and a timing-pass build
  manifest, and should not be treated as offline unit tests.
- A produced bitstream is usable only when the build reports timing PASS.

The detailed investigation record remains available in Git history and the
focused documents under `docs/`; `CHANGELOG.md` is reserved for concise releases.
