# Backing up

> **If this project is in git, read `GIT.md` first.** Git keeps the sources, their history, the
> reasoning behind each change, and a copy on GitHub. This file then covers the one thing git
> deliberately does not keep — the built bitstream — plus the SD card.


Two separate things live in two separate places. Back up **both**, but they are not equally
important.

| | Where | Size | If you lost it |
|---|---|---|---|
| **The project** | `C:\rp\prj\v0.94\Test_Project` on your PC | 78 MB (35 MB zipped) | Weeks of work. Irreplaceable |
| **The board's SD card** | in the Red Pitaya | 4–32 GB | Annoying. Mostly a stock Red Pitaya OS you can download again, plus a bitstream you can rebuild |

Do the PC one first. It is the one that matters, and it takes a minute.

---

## 1. The project — one command

From PowerShell, in the project folder:

```powershell
.\tools\backup.ps1
```

One dated zip in `C:\rp\prj\backups`, **about 2 MB**, in seconds. Run it whenever something
works.

To a USB stick or another drive:

```powershell
.\tools\backup.ps1 -To E:\
```

### What goes in

Everything needed to open the project in Vivado and rebuild it, and nothing Vivado can produce
for itself.

| In | |
|---|---|
| `Test_Project.xpr` | the project |
| `Test_Project.srcs/` | the Verilog, the constraints, and the block design |
| `jupyter_notebooks/` | every notebook, its docs and its off-board tests |
| `acquisition_custom/`, `phaseshift_custom/`, `tools/` | modules, generators, scripts |
| `*.md`, `build_project.tcl` | documentation and the build |
| the last bitstream and its fingerprint | 2 MB, and it means a working board can be restored without waiting 25 minutes |

| Left out | Size | Why |
|---|---|---|
| `Test_Project.runs/` | 36 MB | synthesis and implementation output |
| `Test_Project.cache/` | 2.7 MB | the IP cache |
| `.../bd/system/ip/` | 13 MB | generated IP |
| `.../bd/system/ipshared/` | 21 MB | Xilinx library HDL |
| `results/`, `__pycache__/`, `.Xil/` | | test output and scratch |

**78 MB becomes about 2 MB.**

### Being sure the exclusions are safe

Excluding a real source would produce a backup that cannot be restored, which is worse than no
backup at all — so this was checked rather than assumed:

- `system.bd` carries **all 303 processor parameters itself**, including the HP ports and their
  64-bit widths. It is the source; the `.xci` files under `ip/` are outputs of it.
- The project file lists only two block-design files: `system.bd` and `system_wrapper.v`. Both
  are included.
- `build_project.tcl` **regenerates the block design's output products if they are missing**, so
  a restored copy simply builds. That takes about two minutes, once.

### It checks itself

After writing the archive, the script reads it back and confirms thirteen named files are
present — the project, the block design, the top level, the custom modules, the generated
coefficients, the build script. If any is missing it says so plainly and tells you not to rely
on the archive.

A backup you cannot restore is worse than none, because you stop worrying about it.

### Options

| | |
|---|---|
| `-Full` | everything, including the regenerable 76 MB. For a copy that opens without regenerating anything |
| `-NoBitstream` | leave the built bitstream out as well |
| `-Keep 25` | more history than the default ten |

### Doing it by hand instead

There is no short version of this one worth writing out — the exclusion list is the point, and
getting it wrong is the failure mode. Use `-Full` and accept 35 MB if you would rather not
depend on the script.

### What a local backup does and does not protect against

| | |
|---|---|
| A bad edit, a broken build, a change that made things worse | **Yes.** The common case |
| Deleting the wrong thing | **Yes** |
| The disk failing, the laptop being lost or stolen | **No** |

At 2 MB, copying one onto a stick or a network drive occasionally costs nothing. Do that.

---

## 2. The SD card — from the board itself

Do this **before the first armed capture in Test Stage 6**, since that is the only part of this
project that can write outside its own sandbox.

Plug the USB stick into the **Red Pitaya's** USB socket, not the PC.

### Find the stick

```
lsblk
```

Look for something the size of your stick — typically `sda` with one partition `sda1`. The SD
card is `mmcblk0`; do not confuse them.

### Mount it and check the sizes

```
mkdir -p /mnt/usb
mount /dev/sda1 /mnt/usb
df -h /mnt/usb
lsblk -b /dev/mmcblk0 | head -2
```

The last command gives the card's size in bytes. Compressed it will usually come to well under
half of that, but the stick needs headroom.

### Make the image

```
dd if=/dev/mmcblk0 bs=4M | gzip -1 > /mnt/usb/rp_sd_$(date +%F).img.gz
sync
```

It takes several minutes and prints nothing until it finishes. That is normal.

**If the stick is FAT32** — which it is unless you formatted it otherwise — files cannot exceed
4 GB. If the card is large, split as you go:

```
dd if=/dev/mmcblk0 bs=4M | gzip -1 | split -b 3000M - /mnt/usb/rp_sd.img.gz.
```

which produces `rp_sd.img.gz.aa`, `.ab` and so on. Rejoin later with
`cat rp_sd.img.gz.* > rp_sd.img.gz`.

### Finish

```
umount /mnt/usb
```

Do not pull the stick out before this.

### Why the image is trustworthy

The root filesystem is mounted **read-only** on this board — you can see `ro` on the kernel
command line that Test Stage 6 prints. So nothing is changing underneath while `dd` reads, and
the image is consistent. Imaging a live read-write filesystem this way is normally a bad idea;
here it is fine.

---

## 3. Putting it back

**The project:** two ways round, depending on what went wrong.

*Something is broken and you want the whole thing back:* rename `Test_Project` to
`Test_Project_broken`, extract the zip in its place, and open `Test_Project.xpr`.

*You only want one file back:* open the zip in Explorer, find the file, drag it out. Zips open
like folders in Windows, so you can look inside without extracting anything.

**The SD card:** take it out of the board, put it in your PC, and write the image with
[balenaEtcher](https://etcher.balena.io/) or Win32DiskImager. Etcher reads `.img.gz` directly
without unzipping.

If you only need to undo a boot-settings change, you do not need the image at all — the boot
partition is FAT and Windows can read it. Put the card in your PC and restore whatever you
replaced.

**Note for this board:** its boot partition has no `uEnv.txt`. It holds `u-boot.scr` and
`devicetree.dtb`, both compiled, and is mounted read-only. Nothing in this project needs it
changed — see the "if Step 1 found no free memory" section of Test Stage 6 before touching it.

---

## What is actually at risk

Worth being proportionate about this. Nothing in Test Stages 1 to 5 can damage anything: they
read registers and read memory. The only operation in this project that writes outside its own
hardware is the memory writer in Test Stage 6, and it is now behind three guards — a check that
Linux leaves a gap, a probe that the gap is genuinely unused, and a 4 kB trial capture before
the full one.

The realistic worst case is a corrupted few kilobytes and a reboot. The SD image exists so that
even that is a non-event.
