# Red Pitaya feedback and acquisition

FPGA instrumentation for a Penning-trap experiment. A Red Pitaya STEMlab
125-14 maintains an adjustable feedback path while an independent acquisition
chain mixes, decimates, filters, and records the measured signal.

```text
trap --> ADC --+--> phase and gain --> DAC --> trap
               +--> mixer --> decimator --> filter --> DDR --> Python
```

## Requirements

- Red Pitaya **STEMlab 125-14** (`XC7Z010`)
- Xilinx Vivado **2020.1** for FPGA builds
- Windows PowerShell and Python 3
- Internet access during the first setup only

The stock Red Pitaya sources are not duplicated here. Setup downloads the exact
v0.94 revision recorded in [`fpga/upstream.lock`](fpga/upstream.lock), checks its
SHA-256 digest, and applies this project's small source overlay in `.cache/`.

## Use it

From PowerShell in the repository root:

```powershell
.\project.ps1 setup
.\project.ps1 test
.\project.ps1 build
.\project.ps1 deploy -Board <board-hostname>
```

After deployment, verify the running build without changing its configuration:

```powershell
.\project.ps1 check -Board <board-hostname>
```

Generated projects, logs, and bitstreams stay under `.cache/` and are ignored by
Git. A second build can use the verified cache without network access.

## Documentation

- [Build, deploy, and recover](docs/usage.md)
- [Architecture](docs/architecture.md)
- [Register map](docs/register-map.md)
- [Verified status and known limits](docs/status.md)
- [Notebooks](notebooks/README.md)
- [Tests](tests/README.md)

Project changes should use the stable scopes `fpga`, `software`, `notebooks`,
`tests`, `docs`, and `build`; keep file moves separate from functional edits so
GitHub can show history across renames.

## Upstream and attribution

This independent project customizes Red Pitaya's v0.94 FPGA design. It is not
an official Red Pitaya product and is not endorsed by Red Pitaya. The exact
upstream repository and revision are pinned in
[`fpga/upstream.lock`](fpga/upstream.lock); see
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for attribution and license
information.
