# Working with the Red Pitaya from the command line

A practical guide to powering up the board, getting a newly built bitstream onto it,
loading it, checking which one is running, and going back to the factory one.

Written assuming no prior command-line experience. Every command is copy-and-paste ready.

**Board name used throughout:** `rp-f007f7.local` — change this if you use a different board.

---

## Part 1 — The single most important idea: there are TWO computers

This causes more lost hours than anything else, so it comes first.

| | **Your PC** | **The Red Pitaya** |
|---|---|---|
| Runs | Windows | Linux |
| Has | Vivado, and the bitstream files it builds | The FPGA chip that runs the bitstream |
| You reach it via | PowerShell / Command Prompt | `ssh` from your PC |

They have **completely separate sets of files**. A file sitting on your PC does not exist on
the board until you copy it across. This is the whole reason the `scp` command exists.

### How to tell which computer your window is talking to

Look at the **prompt** — the text before where you type:

```
PS C:\Users\yourname>            <-- your PC (Windows PowerShell)
C:\Users\yourname>               <-- your PC (Command Prompt)
root@rp-f007f7:~#             <-- the Red Pitaya
```

**Check this before every command.** A command typed on the wrong machine either fails
confusingly or, worse, quietly does something harmless-looking and wrong.

> **Real example from this project.** This was typed while already logged into the board:
>
> ```
> root@rp-f007f7:~#  scp red_pitaya_top.bit root@rp-f007f7.local:/root
> ```
>
> It asked for a password, reported "100%, 2035KB" and looked completely successful. But
> `rp-f007f7.local` **is the board** — so it copied a stale file in `/root` onto itself.
> The new bitstream never left the PC. The board then ran week-old logic while appearing
> perfectly healthy: LED blinking, registers responding, sensible-looking measurements.
> It cost an hour to find. Part 5 shows how to make that impossible.

---

## Part 2 — Powering up and connecting

1. **Plug in power** — the micro-USB marked `PWR`. Use a supply rated at least 2 A; an
   underpowered supply causes random reboots that look like faults in your design.
2. **Plug in the network cable** (or confirm Wi-Fi if you use it).
3. **Wait about 30 seconds** for Linux to boot.
4. **Check LED0 is blinking.** That is the board's heartbeat: it means the operating system
   is alive and running. If it is dark or frozen, the board has not booted or has crashed.
5. **Connect from your PC.** Open PowerShell and type:

```powershell
ssh root@rp-f007f7.local
```

Enter the password when asked. Your prompt changes to `root@rp-f007f7:~#`, which means
**everything you now type runs on the board, not on your PC**.

To go back to your PC, type `exit` and press Enter. The prompt returns to `PS C:\...>`.

**A useful habit: keep two windows open.** One left permanently on your PC, one logged into
the board. Then you never have to remember which is which — you just click the right window.

---

## Part 3 — Knowing where you are, and what is there

Linux organises files in folders, called **directories**, exactly like Windows. The only
difference is that Linux writes them with forward slashes: `/root/projects` rather than
`C:\root\projects`.

Four commands cover almost everything:

| Command | What it does | Plain meaning |
|---|---|---|
| `pwd` | print working directory | "Which folder am I in right now?" |
| `ls` | list | "What's in this folder?" |
| `ls -l` | list, long format | Same, but with sizes and dates — usually what you want |
| `cd <folder>` | change directory | "Move into that folder" |

Useful shorthands:

- `cd /root` — go to the `root` folder, starting from the very top of the disk
- `cd ..` — go up one level
- `cd` on its own — go back to your home folder (`/root`)
- `~` means "my home folder", so `~/stage1.bit` and `/root/stage1.bit` are the same file

Try this on the board to get oriented:

```bash
pwd
ls -l
```

---

## Part 4 — Moving, renaming and deleting files

On the board:

| Task | Command |
|---|---|
| Rename a file | `mv oldname.bit newname.bit` |
| Move a file into a folder | `mv myfile.bit /root/archive/` |
| Copy a file (keeping the original) | `cp myfile.bit backup.bit` |
| Make a folder | `mkdir /root/archive` |
| Delete a file | `rm myfile.bit` |
| See a file's size and date | `ls -l myfile.bit` |

`mv` does both moving and renaming, because to Linux they are the same operation: you are
changing the file's full path.

> **`rm` deletes immediately and permanently.** There is no recycle bin. Prefer renaming
> things to `OLD_...` over deleting them, at least until you are sure.

---

## Part 5 — Copy-paste workflows

### Workflow A — Load a freshly built bitstream

This is the main routine. Do the steps in order and it cannot go wrong.

**Step A1 — On the BOARD: move the old file out of the way**

Prompt must read `root@rp-f007f7:~#`.

```bash
mkdir -p /root/archive
mv /root/*.bit /root/archive/ 2>/dev/null
ls -l /root/*.bit
```

The last line should say **"No such file or directory"**. That is what you want: it proves
`/root` now contains no bitstream at all, so anything you find there next came from this
transfer and nothing else.

**Step A2 — On your PC: check you are sending the right file**

Prompt must read `PS C:\...>`. If it says `root@rp-f007f7`, type `exit` first.

```powershell
certutil -hashfile C:\rp\prj\v0.94\Test_Project\Test_Project.runs\impl_1\red_pitaya_top.bit MD5
```

This prints a **checksum** — a short fingerprint calculated from the file's contents. Two
files with the same checksum are identical; change one bit and the checksum changes
completely. Write the value down.

**Step A3 — On your PC: send the file**

```powershell
scp C:\rp\prj\v0.94\Test_Project\Test_Project.runs\impl_1\red_pitaya_top.bit root@rp-f007f7.local:/root/stage1.bit
```

Reading that command: `scp` means "secure copy". The first path is **where the file is now**
(on your PC). The second is **where it should end up** — `root@rp-f007f7.local` names the
board, and everything after the colon is the destination path on it.

Note the file is deliberately given a **new name** on arrival, `stage1.bit`. Never reuse the
name of a file that was already there; if the transfer silently fails you cannot tell the
difference between the new file and the old one.

**Step A4 — On the BOARD: check it actually arrived**

```bash
ls -l /root/stage1.bit
md5sum /root/stage1.bit
```

The checksum must match what Step A2 printed. **If it matches, the correct file is on the
board and there is no room for doubt.** If it does not, the transfer went somewhere else —
go back to Step A3 and check your prompt was on the PC.

**Step A5 — On the BOARD: load it into the chip**

```bash
cat /root/stage1.bit > /dev/xdevcfg
```

This pushes the file into the FPGA's configuration port, which physically rewires the chip.
It takes under a second. LED0 should keep blinking.

> **LED0 blinking does NOT mean the right bitstream loaded.** It only means *a* valid
> bitstream loaded. It looks identical whether you loaded today's build or last month's.
> The checksum in Step A4 is what actually proves it.

**Step A6 — Confirm the new logic is really running**

Run `phaseshift_custom/which_bitstream.py`, or paste its contents into a notebook cell
started with `sudo jupyter notebook`. It writes an invalid delay setting and reads back a
status register that only exists in the newer builds:

- prints **1** → new bitstream is running
- prints **0** → old bitstream; something in Steps A1–A5 did not take effect

---

### Workflow B — Which bitstream is running right now?

```bash
sudo python3 /root/which_bitstream.py
```

(Copy that script across the same way as in Workflow A if it is not already on the board.)

Also worth knowing:

```bash
ls -l /root/*.bit
```

shows every bitstream on the board with its date — handy for spotting a stale file you had
forgotten about.

---

### Workflow C — Going back to the factory bitstream ("unloading")

There is no way to *unload* a bitstream. The FPGA always holds one; the only thing you can
do is load a different one over the top. To get back to Red Pitaya's own version:

**Easiest: restart the board.** It always boots with the factory bitstream.

```bash
reboot
```

Wait about 30 seconds, then `ssh` back in.

**Or load it directly, without rebooting.** First find where it lives on your image:

```bash
ls /opt/redpitaya/fpga/
```

That lists the bitstreams that came with the board. Then load whichever one you need, for
example:

```bash
cat /opt/redpitaya/fpga/fpga_0.94.bit > /dev/xdevcfg
```

Use the exact filename that `ls` showed you — it varies between operating system versions.

---

### Workflow D — Keeping the board tidy

Bitstreams all look alike and are all about 2 MB, so unlabelled ones are worse than useless.

```bash
mkdir -p /root/archive
mv /root/stage1.bit /root/archive/2026-07-27_stage1_timing_fixed.bit
ls -l /root/archive/
```

A naming pattern that works well: **date, then what changed**.

```
2026-07-24_baseline_phaseshift_only.bit
2026-07-27_stage1_timing_fixed.bit
2026-08-03_acquisition_dds_mixer.bit
```

Keep the matching checksum in your lab notebook next to each one. Then "which build was I
running when I took this data?" is always answerable.

---

## Part 6 — Things that will catch you out

| Symptom | Cause | Fix |
|---|---|---|
| Transfer says 100% but nothing changes | `scp` was typed on the board, so it copied a file onto itself | Check the prompt. `scp` runs on the **PC** |
| Board behaves as though your changes never happened | Old bitstream still loaded | Checksum (Step A4), then `which_bitstream.py` |
| Your bitstream works, then stops working | Opening the Red Pitaya **web interface**, or launching any of its apps, reloads the factory bitstream over yours | Load yours **last**, and stay out of the web interface |
| `cat ... > /dev/xdevcfg` gives "No such file or directory" | Newer operating system image; that device does not exist | Check with `ls /sys/class/fpga_manager`. If present, use `fpgautil -b <file>` instead |
| Board reboots, LED0 stops blinking | Usually a bulk memory read from Python. The bus bridge cannot handle burst transfers and locks up | Read registers **one 32-bit word at a time**. Reload the bitstream afterwards |
| `Permission denied` when running a Python script | Reading `/dev/mem` needs administrator rights | Put `sudo` in front, or start Jupyter with `sudo jupyter notebook` |
| Random reboots during use | Underpowered USB supply | Use a supply rated 2 A or more |

---

## Part 7 — Quick reference

**On your PC (PowerShell)**

```powershell
ssh root@rp-f007f7.local                                    # connect to the board
certutil -hashfile <full\path\to\file.bit> MD5              # fingerprint a file
scp <full\path\to\file.bit> root@rp-f007f7.local:/root/<newname>.bit   # send it
```

**On the board**

```bash
pwd                                  # where am I
ls -l                                # what is here
cd /root                             # go somewhere
mv old.bit new.bit                   # rename or move
rm file.bit                          # delete (permanent)
md5sum file.bit                      # fingerprint, to compare with the PC
cat file.bit > /dev/xdevcfg          # load into the FPGA
reboot                               # restart, returns to the factory bitstream
exit                                 # back to your PC
```

---

## Part 8 — The short version

Whenever you build something new:

1. **Board:** clear out old bitstreams → `mv /root/*.bit /root/archive/`
2. **PC:** fingerprint the new one → `certutil -hashfile ... MD5`
3. **PC:** send it under a **new name** → `scp ... root@rp-f007f7.local:/root/stage1.bit`
4. **Board:** check the fingerprint matches → `md5sum /root/stage1.bit`
5. **Board:** load it → `cat /root/stage1.bit > /dev/xdevcfg`
6. **Board:** confirm the new logic is live → `which_bitstream.py` should print 1

Steps 2, 4 and 6 are the ones people skip, and they are the ones that catch the failure where
everything looks fine and nothing is.
