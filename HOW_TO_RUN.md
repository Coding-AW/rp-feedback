# How to run the two commands

Step by step, assuming nothing. If you have never used a command line, start here.

There are exactly two commands you need for normal work:

| Command | Where you type it | Takes | What it's for |
|---|---|---|---|
| `check_system.py` | On the **board** | 10 seconds | "Is it working?" |
| `build_project.tcl` | On your **PC**, in Vivado | 15–25 min | "I changed something, rebuild it" |

They run on **different computers**. Getting that wrong is the most common mistake here, so
each section below starts by telling you which window you should be in.

---

# Part 1 — `check_system.py`

## What it actually does

Think of it as a check-up. It asks the board five questions and prints the answers in plain
English:

1. **Is the right design loaded?** The chip is blank until you load a file into it. Loading an
   old file looks *exactly* like success — lights blink, everything responds, measurements
   look sensible — while the chip runs last month's design. This catches it.
2. **Is the measuring system responding?** Writes a number into the chip and reads it back. If
   it comes back different, something is wrong with the build.
3. **Is anything flagged?** The hardware sets three warning lights by itself. The important one
   is *samples were lost* — if that's lit, any data you took is wrong, because time jumped
   without the record showing it.
4. **What is it set to?** Which frequency it's listening at, how much averaging, and so on.
5. **Is it actually producing data?** Counts samples for a third of a second and checks the
   rate is right.

**It changes nothing.** You can run it whenever you like, as often as you like.

## Step 1 — Get the file onto the board (first time only)

The script lives on your PC. The board can't see your PC's files, so you have to copy it
across. **This is done from your PC.**

Open **PowerShell** on Windows: press the Windows key, type `powershell`, press Enter.

You should see a prompt like `PS C:\Users\yourname>`. Type this, all on one line, then Enter:

```powershell
scp C:\rp\prj\v0.94\Test_Project\check_system.py root@rp-f007f7.local:/root/
```

It will ask for the board's password. Type it (nothing appears as you type — that's normal)
and press Enter.

> **If it says "Could not resolve hostname":** the board isn't reachable. Check it's powered on,
> plugged into the network, and that the blinking light is going.

## Step 2 — Connect to the board

Same PowerShell window:

```powershell
ssh root@rp-f007f7.local
```

Password again. **Your prompt will change** from `PS C:\Users\yourname>` to
`root@rp-f007f7:~#`. That change is the signal that everything you now type runs on the board,
not your PC.

## Step 3 — Run it

```
python3 check_system.py
```

That's it. Ten seconds later you get the report.

> **If it says "Permission denied" or "Operation not permitted":** put `sudo ` in front:
> `sudo python3 check_system.py`

## Step 4 — Read the answer

Every line starts with `OK`, `WARNING` or `PROBLEM`, and the last few lines summarise:

```
   5 OK      1 warnings      0 problems

   Nothing is broken. Check the warnings are things you intended.
```

- **All OK** — go ahead.
- **Warnings** — nothing broken, but check they're deliberate. "Test pattern mode is ON" is a
  warning because the numbers coming out are fake, which is fine during a test and disastrous
  if you didn't mean it.
- **Problems** — stop. Every problem is followed by `->` lines telling you what to do.

## Step 5 — When you're done

```
exit
```

Your prompt goes back to `PS C:\Users\yourname>`, meaning you're on your PC again.

## Running it again later

Steps 1 is only needed once. After that it's just:

```powershell
ssh root@rp-f007f7.local
```
```
python3 check_system.py
```

**Do repeat step 1 if the script has been updated** — the board keeps its own copy and won't
notice changes on your PC.

---

# Part 2 — `build_project.tcl`

## What it actually does

The design is written as text files describing a circuit. The chip can't read text — it needs
a **bitstream**, a 2 MB file that tells it what circuit to become. Building is the process of
turning one into the other. It's slow because the software has to work out how to fit the
circuit onto the chip and route every connection.

The script does five things in order, and the order matters:

1. **Checks the filter numbers are up to date.** Some of the design is produced by a Python
   script. If someone edited that script and forgot to run it, the chip would be built with the
   old numbers and *nothing would complain*. This stops the build and tells you.
2. **Adds any new files** to the project. Vivado doesn't notice new files by itself.
3. **Builds.** The slow part.
4. **Checks the result** and explains it in words rather than leaving you to interpret a report.
5. **Tells you where the file is** and what to do next.

**You only need this if you changed the design.** If you're just taking measurements, skip it.

## Step 1 — Open Vivado

Windows key → type `Vivado` → Enter. It takes a minute to start.

## Step 2 — Open the project

If `Test_Project` appears under **Recent Projects** on the welcome screen, click it.

Otherwise: **File → Project → Open**, then navigate to

```
C:\rp\prj\v0.94\Test_Project\Test_Project.xpr
```

and click Open. (The `.xpr` file *is* the project.)

## Step 3 — Find the Tcl Console

Look at the **bottom** of the Vivado window for a row of tabs: *Tcl Console*, *Messages*,
*Log*, *Reports*, *Design Runs*. Click **Tcl Console**.

You'll see a small text box with a prompt. That's where you type.

> **If you can't see it:** menu **Window → Tcl Console**.

## Step 4 — Type the command

Click into the Tcl Console box, type this exactly, then Enter:

```tcl
source C:/rp/prj/v0.94/Test_Project/build_project.tcl
```

**Note the forward slashes `/`, not backslashes `\`.** This is the one place in Windows that
insists on them. Backslashes will give an error.

## Step 5 — Wait

15 to 25 minutes. It prints progress as it goes. You can watch the *Design Runs* tab if you
like, or go and do something else — you can't break it by leaving it alone.

Don't close Vivado. Don't start another build.

## Step 6 — Read the summary

At the end it prints a summary. The part that matters:

```
  TIMING
    Time to spare on the slowest calculation : 0.133 ns
    Calculations that are too slow           : 0

    PASS - every calculation finishes in time.
```

**"Time to spare" must be positive and "too slow" must be zero.**

The chip works in steps of 8 billionths of a second. If a calculation needs longer than one
step, it gets interrupted halfway and stores a half-finished answer. A build that fails this
does **not** fail cleanly — it may work fine on a cool day and produce corrupted numbers on a
warm one. If it says FAIL, don't use the bitstream; the script lists which calculations were
too slow.

Then:

```
  Bitstream: C:/rp/.../Test_Project.runs/impl_1/red_pitaya_top.bit

  NEXT STEPS
    1. Copy it to the board...
```

## Step 7 — Get it onto the board

**See `BITSTREAM_WORKFLOW.md`.** Don't improvise this — there is a trap that costs people
an hour, and the guide exists because it already cost one here.

The short version, typed on your **PC**:

```powershell
scp C:\rp\prj\v0.94\Test_Project\Test_Project.runs\impl_1\red_pitaya_top.bit root@rp-f007f7.local:/root/new.bit
```

then on the **board**:

```
cat /root/new.bit > /dev/xdevcfg
```

then check it worked:

```
python3 check_system.py
```

---

# Which window am I in?

The single most useful habit. Look at the start of the line before you type:

| What you see | Where you are | What runs here |
|---|---|---|
| `PS C:\Users\yourname>` | Your PC | `scp`, `ssh`, Vivado |
| `root@rp-f007f7:~#` | The board | `python3`, `cat`, `ls` |
| A box at the bottom of Vivado | Vivado's console | `source`, and other `tcl` commands |

If a command doesn't work, check this first. It's usually the answer.

---

# If something goes wrong

| It says | What it means | Do this |
|---|---|---|
| `Could not resolve hostname` | The board can't be found | Check power, network, and that the light is blinking |
| `Permission denied` | You're not administrator | Put `sudo ` in front of the command |
| `No such file or directory` | The file isn't where you said | You're probably on the wrong machine, or need to copy the file across first |
| `couldn't read file` (Vivado) | Wrong path or backslashes | Use forward slashes `/` |
| `command not found` | Typo, or wrong machine | Check the prompt |
| Build says FAIL on timing | Some calculations are too slow | Don't use the bitstream. See `CHANGELOG.md` for how similar cases were fixed |
| Everything looks fine but results are wrong | Very likely an old bitstream | Run `check_system.py` — its first check is exactly this |
