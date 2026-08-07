# Start here

You have been handed a Red Pitaya set up to measure a signal from a Penning trap. This page
is the way in. **It assumes you know nothing about the project or about programmable logic.**

Fifteen minutes here will save you a day.

---

## 1. What this thing does, in one picture

The trap produces a faint signal at some radio frequency. Buried in it is a feature only a few
kilohertz — sometimes a few hertz — wide. The board's job is to pull that feature out.

```
   trap ──▶ [ FEEDBACK PATH ]  ──▶ back to the trap      (controls the ion)
              │
              │ listens in, changes nothing
              ▼
            [ ACQUISITION SYSTEM ] ──▶ memory ──▶ Python  (measures the ion)
```

Two independent systems on one chip:

| | What it does | Where it lives |
|---|---|---|
| **Feedback path** | Shifts the signal's phase and sends it back to the trap, to control the ion's motion | `phaseshift_custom/` |
| **Acquisition system** | Records the signal so you can look at it | `acquisition_custom/` |

The acquisition system only *listens*. It cannot disturb the feedback path — that separation
is deliberate and is worth preserving.

---

## 2. The two machines — read this before typing anything

**There are two computers, and mixing them up is the most common mistake here.**

| | **Your PC** | **The Red Pitaya** |
|---|---|---|
| Runs | Windows, with Vivado | Linux |
| Holds | The design, and the files Vivado builds | The chip that runs them |
| You see | `PS C:\Users\...>` | `root@rp-f007f7:~#` |

**Look at the prompt before every command.** They have completely separate files. A file on
your PC does not exist on the board until you copy it across.

> The single most expensive mistake made on this project so far: a copy command typed on the
> board instead of the PC. It reported success, transferred 2 MB, and the board ran week-old
> logic for an hour while looking perfectly healthy.

Full guide: **`BITSTREAM_WORKFLOW.md`**

---

## 3. What do you want to do?

### "I just want to check it still works"

On the board:

```
python3 check_system.py
```

Ten seconds. Tells you in plain English whether the right design is loaded, whether anything
is flagged, what it is currently set to, and whether it is producing data. Anything other than
OK comes with what to do about it.

**Never used a command line?** `HOW_TO_RUN.md` walks through it keystroke by keystroke.

### "I want to take a measurement"

1. `sudo python3 check_system.py` — confirm it is healthy
2. Work through the **Test Stage** notebooks in `acquisition_custom/`, in order
3. Stage 7 measures a signal end to end. Stage 8 is your real experiment

Two ways to run them. Both execute on the board — they read the chip's registers, which only
exist there — but only one needs a browser:

| | How | Output |
|---|---|---|
| **In the browser** | `http://rp-f007f7.local/jupyter/` | On screen, in the tab |
| **From your PC** | `.\tools\run_on_board.ps1 "Test Stage 5 - Droop Correction.ipynb"` | A log and PNGs in `results\`, on your PC |

The second is worth knowing about: results become files you keep, compare and share, instead of
text in a tab. **Editing** has no restriction either way — a notebook is a text file, so edit it
wherever you like.

### "I changed something and need to rebuild"

On your PC, in Vivado's Tcl Console:

```tcl
source C:/rp/prj/v0.94/Test_Project/build_project.tcl
```

One command, typed into Vivado's Tcl Console. It checks the generated files are current, adds
any new sources, builds, checks the result, and tells you plainly whether it passed.
15–25 minutes.

**Step-by-step, including where to find the Tcl Console:** `HOW_TO_RUN.md`

Then copy the bitstream across — see `BITSTREAM_WORKFLOW.md` — and run `check_system.py`.

### "Something is wrong and I don't know why"

1. `sudo python3 check_system.py` — start here always
2. `CHANGELOG.md` — every warning this project produces, and whether it matters
3. Re-run the Test Stage notebook for the block you suspect. Each says what a failure means,
   not just that it failed

### "I want to change the correction filter"

Open `jupyter_notebooks/acquisition/FIR Filter Designer.ipynb` on the board. Two numbers, a plot, and it
loads into the chip in about a second — no rebuild. Changing the *number* of taps still needs
one; the notebook says so.

### "I want to put the current notebooks on the board"

The notebooks in this project and the ones the browser shows are **separate copies**. Edits here
are invisible in the browser until you copy them across, and the board will happily run old code
while you read new code.

Once, to find where Jupyter keeps its files — on the board:

```
find / -name "Test Stage 5*.ipynb" 2>/dev/null
```

Then every time, from PowerShell on your PC in the project folder (two lines, and adjust the
path if the `find` said something different):

```powershell
ssh root@rp-f007f7.local "rm -rf /root/jupyter/RedPitaya/acq"
scp -r acquisition_custom root@rp-f007f7.local:/root/jupyter/RedPitaya/acq
```

In the browser they appear under **RedPitaya / acq**. The `rm -rf` first is deliberate: it makes
this folder a copy of the project rather than a merge, so there is never a question of which
version you are looking at. Anything you edited on the board is lost — edit here instead.

The whole folder goes across, not just the notebooks, because several of them need
`fir_coeffs.txt`, and `find_signal.py` and `show_memory_map.py` are useful to have there too.

### "I want to save my work properly"

```powershell
.\tools\save.ps1 -m "what changed and why"
```

Commits it to git and sends it to GitHub. **`GIT.md` explains git and GitHub from nothing** —
twenty minutes to set up, four commands a day afterwards. Worth it: a commit records *why* a
change was made, and `build_project.tcl` stamps the commit into every bitstream, so register
`0x48` traces all the way back to the exact source months later.

### "I want to back up my work"

```powershell
.\tools\backup.ps1
```

One dated 35 MB zip into `C:\rp\prj\backups`, in under a minute. Add `-To E:\` for a USB
stick. Full instructions, including the board's SD card: **`BACKUP.md`**. Worth doing before
the first armed capture in Test Stage 6.

### "I want to understand how it works"

`acquisition_custom/EXPLAINER.md` — written for someone with no background in this.

---

## 4. Where everything is

```
Test_Project/
├── START_HERE.md            ← you are here
├── HOW_TO_RUN.md            the two commands, keystroke by keystroke
├── check_system.py          "is it working?"          run on the BOARD
├── build_project.tcl        "build everything"        run on your PC
├── BITSTREAM_WORKFLOW.md   copying files to the board, and the traps
├── CHANGELOG.md             every change ever made, and why
├── HANDOVER.md              where things stand, and the one open problem
├── GIT.md                   git and GitHub, from nothing
├── BACKUP.md                how to back up the project and the SD card
│
├── tools/                   run a notebook on the board from your PC
│   ├── run_on_board.ps1
│   └── nb_to_script.py
├── results/                 logs and plots come back here
│
├── jupyter_notebooks/       EVERY NOTEBOOK, IN ONE PLACE
│   ├── acquisition/           Test Stage 2..17, the coil characterisation,
│   │                          FIR Filter Designer, and their own docs
│   ├── phaseshift/            phase_shift_control, scope_phase_check
│   └── tests/                 run every notebook off the board, against a mock
│
├── acquisition_custom/      THE MEASURING SYSTEM
│   ├── README.md              reference: registers, settings, limits
│   ├── EXPLAINER.md           how it works, in plain English
│   ├── gen_fir_coeffs.py      makes a filter design permanent
│   └── validate_*.py          software checks of each block
│
├── phaseshift_custom/       THE FEEDBACK PATH
│   ├── README.md
│   └── validate_*.py
│
└── Test_Project.srcs/       the design itself (Verilog). Rarely edited by hand
```

---

## 5. Five things that will catch you out

**1. Loading an old bitstream looks exactly like success.** The light blinks, registers
answer, measurements look plausible. Always check the file fingerprint, and run
`check_system.py` afterwards.

**2. Sampling faster does not improve frequency resolution.** Resolution is
`1 ÷ how long you watched`, and nothing else. To separate two frequencies 10 Hz apart you must
record for at least 0.1 seconds.

**3. Averaging cannot remove everything.** It narrows the band; anything already inside the
band passes untouched. There is a floor of about 72 counts here that no amount of averaging
will get below. If your signal is under it, a longer measurement will not help — something is
sitting in the band and needs finding.

**4. Read registers one at a time.** Reading a block in one go sends a request the chip's
internal bus cannot answer. It locks up and the board reboots. The provided code already does
this correctly; do not "optimise" it.

**5. Opening the Red Pitaya web page reloads the factory design over yours.** Load your
bitstream last, and stay out of the web interface.

**6. A fresh bitstream file can contain old logic.** Editing a source while Vivado has the
project open can leave synthesis marked "done", so only the last steps re-run and the bitstream
is rebuilt from a stale netlist. Never judge this by file dates. The chip carries a fingerprint
of the source it was built from at register `0x48`; `check_system.py` reads it and compares it
with `bitstream_id.txt`. Always build with `build_project.tcl`, which forces a full rebuild.

---

## 6. Words you will meet

| Word | What it means |
|---|---|
| **FPGA** | The reconfigurable half of the main chip. You describe a circuit and the chip becomes it |
| **Bitstream** | The file that tells the FPGA what circuit to be. About 2 MB |
| **Register** | A numbered storage slot the software can read or write — how Python controls the hardware |
| **Sample** | One measurement of the incoming voltage. The board takes 125 million per second |
| **Decimation (R)** | How many samples are averaged into one. Bigger = quieter but slower and narrower |
| **Mixer** | Slides the signal down to zero frequency, so a slow recorder can capture it |
| **I and Q** | A pair of numbers giving the signal's size *and* direction, like x and y coordinates |
| **Droop** | The measurement window sagging at its edges. The correction filter undoes it |
| **Aliasing** | Fast things masquerading as slow ones when you look too rarely. Cannot be undone afterwards |
| **Timing violation** | A calculation that does not finish before the next clock tick. Produces corrupt data unpredictably |
| **Slack** | Spare time on a calculation. Positive is good, negative is a timing violation |
| **dB (decibel)** | A ratio: −6 dB is half, −20 dB a tenth, −40 dB a hundredth |

---

## 7. Where the project stands

**Working and tested on hardware:** the feedback path (loop delay 119.87 ns), and the
acquisition system through reference tone, frequency shift, averaging **and droop correction**.
**Stages 1–5 and 5b all pass.** The signal path is verified from the input to the corrector.

**What to do next, in order:**

1. **Stage 6.** Step 1 finds the reserved region on this board automatically
   (`labuf@a000000`, 32 MB) and proposes `0x0A000000`. Nothing needs changing on the board.
2. **Stage 7** — end to end, the one that says the instrument works.

**Not built:** trigger synchronisation with the feedback sequencer.

**Known outstanding:** listed at the end of `acquisition_custom/README.md`.

Based on Herkenhoff *et al.*, *A digital feedback system for advanced ion manipulation
techniques in Penning traps*, Rev. Sci. Instrum. **92**, 103201 (2021).
