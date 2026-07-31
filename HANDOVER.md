# Handover — where this project stands

Written 2026-07-30. Read this first if you are picking the project up, or starting a fresh
conversation about it. `START_HERE.md` explains the project; this explains the *situation*.

---

## Working, verified on hardware

| | |
|---|---|
| **Feedback path** | Phase shifter, loop delay measured at 119.87 ns. Untouched by any of the acquisition work and must stay that way |
| **Test Stages 1–5** | Reference tone, frequency shift, decimation, noise scaling, droop correction. All pass |
| **Test Stage 5b** | All four known-answer filter tests pass |

The signal path is proven end to end from the input, through mixer, decimator and droop
corrector, to the `PEEK` registers. That is most of the instrument.

---

## The one open problem — SOLVED 2026-07-30

**Test Stage 6 — the path into memory. Memory refused every write, on both ports.**

**There were two faults, both in the processor's boot-time configuration, neither in
any design file. Stage 6 now passes end to end on axi0.**

**Fault 1 — TrustZone.** The memory-permission register (`TZ_DDR_RAM`, 0xF8000430)
defaults at power-on to "refuse all untrusted writers", the boot software never opens
it, and the write engine presented the untrusted badge. Every write on every port was
accepted, then refused, while the processor's own (trusted) writes worked. Opened at
runtime by `diagnose_hp_ports.py --open-tz` — **reverts at every reboot** until the
pending rebuild (see below).

**Fault 2 — axi1 drops half of every sample.** With TrustZone open, axi1 stored the
I half of each 64-bit sample and silently discarded Q: its processor-side port (HP1)
is left with a channel in 32-bit mode by the boot software, and that register refuses
correction from Linux (`Bus error`). axi0's port is configured correctly and runs the
whole of Stage 6 clean. **Use axi0. axi1 is diagnostics-only** — documented in the
register map, defaulted in the notebook, and `check_system.py` warns if axi1 is armed.

**Pending rebuild (in source, NOT yet built): the resonator's noise sources**
(`NOISE_TANK`/`NOISE_OUT` registers, needed by Test Stage 9 — its Step 0 probes for
them and refuses an older bitstream). The earlier pending items — trusted badge, axi0
default, the resonator itself — went into the Stage 8 rebuild and are live.

**After any rebuild:** check the timing report (the resonator's multiply-add must close
in one clock), and re-measure the feedback loop delay to confirm 119.87 ns is unchanged.

### What has been ruled out, with evidence

| Ruled out | How |
|---|---|
| The writer inventing progress | `stat_cur_addr_o` is `next_address`, which advances only on `axi_wrdy_i && axi_wvalid_o` — an accepted write. Both trial captures wrapped exactly as arithmetic demands: 24591 mod 512 = 15 with the counter at sample 15; 24568 mod 512 = 504 with the counter at sample 504 |
| Byte enables masking the data | `axi_wsel_o <= {SW{1'b1}}` |
| Wiring in `red_pitaya_ps.sv` | `axi_master_0_1[1:0]`: index 1 is axi1 on the system side **and** hp1 on the AXI side. Symmetric |
| Clock or reset | `hp1_saxi_clk_i = axi1_clk_i`, 125 MHz from the acquisition; reset released |
| Cache coherency | Tried `0x1E000000`, which the kernel was never told exists and therefore has no cached view of. Identical behaviour |
| The region being in use | Probed before every run: a pattern written from Linux survives untouched |
| The processor being unable to reach the region | The fill pattern is written and read back successfully at both addresses |

### What is left

The fault is **between `axi_master` and the memory** — inside the Zynq block design, which is the
one part not expressed in any file in this repository.

Worth knowing: **there is no evidence DDR writes on this board have ever worked.** The Red Pitaya
oscilloscope's normal mode uses its own 16 kSample block memories, which is what every diagnostic
here has used. The `axi0`/`axi1` paths belong to its *deep-memory* capture, which nothing in this
project has exercised.

---

## How it was found — 2026-07-30, kept for the method

The rebuild with `STATUS2[3]` (write-error flag) and `CTRL[8]` (port select) ran on
hardware, with a one-character fix so the flag catches *both* refusal codes. Result:
**flag SET, identically on axi0 and axi1** — memory answering every write with a
refusal. That exonerated all the logic in one stroke.

The block design — the predicted last resort — turned out to (a) exist in the
repository after all (`Test_Project.srcs/sources_1/bd/system/system.bd`) and (b) be
completely clean: all HP ports enabled, 64-bit, memory fully mapped. With every file
in the repository exonerated, the only place left was the processor's *runtime*
configuration, set by boot software. Two candidates fit the symptom; a ten-second
register read (`diagnose_hp_ports.py`) confirmed TrustZone and cleared the other.

The lesson for the traps list: **the bitstream is not the whole configuration.** A
register the boot software never touches can veto what a perfect design does, and its
power-on default can be "refuse silently".

### If it stays blocked

Stage 6's *purpose* is to prove packing, ordering and integrity. Most of that is reachable
without memory at all: the `PEEK` registers carry the test pattern, so `I + Q = 0xFFFFFFFF` and
the counting sequence can be checked over thousands of reads. `SAMPLE_CNT` proves nothing is lost
in the chain. That would let **Stage 7 proceed** with register-based capture at low decimation,
recording the memory path as unproven — which unblocks the physics rather than parking it.

---

## Before changing anything

```powershell
.\tools\backup.ps1          # 35 MB zip, under a minute
python3 tools\verify_rtl.py            # after any Verilog edit
python3 tools\verify_notebooks.py acquisition_custom\*.ipynb
```

`build_project.tcl` runs both checks itself and refuses to build if either finds a real problem.

---

## Things that have cost this project a day each

Every one of these produced a *plausible wrong answer* rather than an obvious failure. They are
listed in full, with evidence, in `CHANGELOG.md`.

| | The trap |
|---|---|
| **A fresh bitstream can contain old logic** | Editing a source while Vivado has the project open leaves synthesis marked done, so only the later steps re-run. File dates say "fresh". Register `0x48` carries a hash of the source it was actually built from |
| **The board's notebooks and this project's notebooks are separate files** | The browser edits the board's copy. They drift, and the board runs old code while you read new code |
| **A concatenation in Verilog is unsigned** | `pair <= is_centre ? {rd_a[31], rd_a} : (rd_a + rd_b);` — the braces reached across the colon and made the addition unsigned. Correct at the centre of the band, catastrophic at the edges. This was the only real hardware bug found in the whole acquisition system |
| **A test can measure its own artefact** | `\|I + jQ\|` needs two register reads; at higher offsets they land on different samples, and the resulting sag towards the band edges is the same shape as the droop being measured |
| **A tolerance tighter than the measurement** | A 0.1% threshold on a reading worth 0.58%. It could only ever pass by luck |
| **A diagnostic that leaves a mark** | The memory probe's own pattern was read back and reported as 57 000 corrupt samples |
| **"Reserved" is not "not mapped"** | A reserved-memory block inside the kernel's map still has a cacheable view |
| **`MEM_STOP` is the last address, not one past the end** | Set it to `first + size - 8` |
| **A text replacement that does not match fails silently** | A port was "added" to a module and was not. `verify_rtl.py` exists because of this |
| **Vivado's Python is 2.7 and broken** | `exec python` from a Tcl script is not the Python you think it is |

---

## Where everything is

| | |
|---|---|
| `START_HERE.md` | The project, for someone who knows nothing about it |
| `CHANGELOG.md` | Every change and every diagnosis, newest first. Long, and the record of *why* rather than *what* |
| `BACKUP.md` | Backing up the project and the SD card |
| `acquisition_custom/README.md` | Register map, limits, status |
| `acquisition_custom/EXPLAINER.md` | How the acquisition system works, in plain English |
| `tools/` | Optional conveniences, plus the two checkers, which are not optional in spirit |
