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

## `project.ps1`

`project.ps1` is the project's PowerShell entry point. It keeps setup, testing,
building, programming the board, and checking the board consistent. Run it from
PowerShell in the repository root:

```powershell
.\project.ps1 <command>
```

Running it without a command is the same as `test`.

| Command | What it does |
|---|---|
| `setup` | Checks the project-owned FPGA sources, downloads the exact RedPitaya-FPGA v0.94 source archive named in `fpga/upstream.lock` if it is not already cached, verifies its SHA-256 checksum, extracts it under `.cache/upstream`, and copies this project's FPGA files over that baseline. It does not build or program the board. |
| `test` | Runs the source-integrity check, HDL module/port checks, notebook static checks, the analysis self-test, notebook audit, and Python tests. It does not require Vivado or a connected board. |
| `build` | Runs `setup` and `test`, creates the Vivado project, performs synthesis and implementation with Vivado 2020.1, checks timing, and writes the bitstream and build manifest. A build is usable only if timing passes. |
| `deploy` | Checks that the locally built image has the qualified hardware ID and a timing `PASS`, copies it to the board over SSH, and loads it through `/dev/xdevcfg`. It requires `-Board <hostname-or-IP>`. |
| `check` | Copies the read-only health-check script to the board and runs it. It verifies the loaded FPGA interface without changing its configuration. It requires `-Board <hostname-or-IP>`. |
| `clean` | Removes the generated Vivado project and build output. It retains the downloaded upstream source cache, so a later setup normally does not need another download. |

The normal source-to-board workflow is:

```powershell
.\project.ps1 setup
.\project.ps1 test
.\project.ps1 build
.\project.ps1 deploy -Board <board-hostname-or-IP>
.\project.ps1 check  -Board <board-hostname-or-IP>
```

You can set the board once instead of supplying `-Board` repeatedly:

```powershell
$env:RP_BOARD = "192.168.1.100"
.\project.ps1 deploy
.\project.ps1 check
```

Generated projects, logs, and bitstreams stay under `.cache/` and are ignored by
Git. A second build can use the verified cache without network access. The built
files are placed in:

```text
.cache/upstream/prj/v0.94/project/redpitaya.runs/impl_1/
```

The important files are `red_pitaya_top.bit` and `bitstream_id.txt`.

## Load a pre-generated bitstream

Only load a bitstream built for the **Red Pitaya STEMlab 125-14 / XC7Z010** and
from a source you trust. Loading an image for another Red Pitaya model can give
incorrect pin behaviour. The commands below use the classic Red Pitaya OS
interface expected by this project.

If the bitstream was produced locally by `project.ps1 build`, use `deploy`; it
checks the accompanying manifest before programming the board:

```powershell
.\project.ps1 deploy -Board 192.168.1.100
```

For an arbitrary trusted pre-generated `.bit` file, copy it to the board and
load it manually:

```powershell
$Board = "192.168.1.100"
$Bitstream = "C:\path\to\red_pitaya_top.bit"

scp $Bitstream "root@${Board}:/root/red_pitaya_top.bit"
ssh "root@${Board}" "cat /root/red_pitaya_top.bit > /dev/xdevcfg"
```

This manual route bypasses the timing, fingerprint, and hardware-ID checks made
by `project.ps1 deploy`. If the image is this project's qualified bitstream,
verify it immediately afterward:

```powershell
.\project.ps1 check -Board $Board
```

Programming through `/dev/xdevcfg` is temporary: rebooting restores the FPGA
image configured by the board's operating system. If `/dev/xdevcfg` does not
exist, the board is using a different Red Pitaya OS generation; do not substitute
a loader command blindly. Use that OS image's documented FPGA-loading method.

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
