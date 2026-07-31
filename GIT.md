# Git and GitHub, from nothing

Written for someone who has never used either. Twenty minutes to set up, four commands a day
afterwards.

---

## 1. What the two things are

**Git** is a program on your computer. It takes a **snapshot** of your project whenever you ask,
and keeps every snapshot for ever, each with a note from you saying what changed and why. That
is the whole idea. Everything else is detail.

**GitHub** is a website that keeps a copy of those snapshots somewhere that is not your laptop.

They are separate. Git works perfectly well with no internet at all; GitHub is where you push a
copy so that a dead hard drive is an inconvenience rather than a disaster.

### Why it is better than the zip you already have

`tools/backup.ps1` gives you a dated zip. That is a real backup, and it has genuinely saved
projects. But:

| A zip | A commit |
|---|---|
| "Test_Project_src_2026-07-30_1620.zip" | "Fix the unsigned pre-add in the corrector" |
| To find when something broke: extract several and compare by hand | `git log` shows every change, newest first |
| To see what changed: no way | `git diff` shows the exact lines |
| To go back: extract over the top and hope | `git checkout` puts you there exactly |
| Lives on the same disk | Lives on GitHub too |

The difference that matters most for this project is the second column's first row. This
project's `CHANGELOG.md` exists because *why* a change was made turned out to be worth more than
the change itself. Commit messages are that same discipline, attached to the code rather than
kept alongside it.

---

## 2. The one idea people find confusing

Git has **three places**, not two. Almost every early confusion comes from not knowing this.

```
   your folder            the staging area              the history
   (working tree)         (the "index")                 (commits)

   you edit here    ──▶   you choose what      ──▶      permanent, with
                          goes in the next             a message
      git add             snapshot                     git commit
```

**Why the middle one exists.** You have edited five files. Three are one coherent change, two are
something else entirely. Staging lets you commit the three now, with their own message, and the
other two later with theirs. Your history then reads as a sequence of *ideas*, not a sequence of
*times you happened to save*.

If you always want everything, `git add -A` stages the lot and you can ignore the distinction.
That is a perfectly reasonable way to start.

---

## 3. Setting it up, once

### Install git

Download from [git-scm.com](https://git-scm.com/download/win). Accept every default. When it
asks about the default editor, if you do not know what Vim is, choose Notepad or VS Code — this
matters, because git will occasionally open an editor and Vim is famously hard to get out of.

Then tell it who you are. This goes into every commit, for ever:

```powershell
git config --global user.name  "Alex Williams"
git config --global user.email "200155153+Coding-AW@users.noreply.github.com"
```

### Start the repository

From PowerShell, in `C:\rp\prj\v0.94\Test_Project`:

```powershell
git init
git add -A
git commit -m "Working acquisition system: Test Stages 1-7 pass"
```

Three commands and you have a complete, permanent snapshot of everything as it stands today.

`git init` created a hidden folder called `.git`. That folder *is* the repository — every
snapshot, for ever, compressed. Do not delete it and do not put it in the backup exclusion list.

### Check what it decided to keep

```powershell
git status
```

Should say `nothing to commit, working tree clean`. And:

```powershell
git count-objects -vH
```

should show a few megabytes. If it shows hundreds, something in `.gitignore` is not matching —
stop and check before pushing, because a repository is much easier to keep small than to make
small later.

### Put it on GitHub

1. Make an account at [github.com](https://github.com).
2. Click **New repository**. Name it something like `redpitaya-penning-acquisition`. **Do not**
   tick "Add a README" — you already have files, and an empty repository is easier to push into.
3. Choose **Private** unless you have checked with your supervisor. It is easy to make a private
   repository public later and impossible to un-publish something.
4. GitHub then shows you two commands. They will look like:

```powershell
git remote add origin https://github.com/YOURNAME/redpitaya-penning-acquisition.git
git push -u origin main
```

The first tells your local repository where its copy lives; `origin` is just the conventional
name for it. The second sends everything and remembers the choice, which is why every later push
is simply `git push`.

**Signing in.** GitHub stopped accepting passwords over the command line in 2021. The easiest
route is to install [GitHub CLI](https://cli.github.com/) and run `gh auth login` once — it
handles everything through the browser. Otherwise git will prompt for a **personal access
token**, which you create at github.com under Settings → Developer settings → Personal access
tokens. Treat it as a password.

---

## 4. The daily loop — four commands

```powershell
git status                       # what have I changed?
git add -A                       # stage all of it
git commit -m "what and why"     # snapshot it, with a message
git push                         # send it to GitHub
```

That is genuinely all of it, and you can go months without needing anything else.

**When to commit.** Whenever something works, or whenever you are about to try something that
might not. Commits are free. A commit every twenty minutes is not excessive; a commit every three
days is a lost afternoon waiting to happen.

### Writing a message worth reading

The message is the part your future self will actually use. Six months from now `git log` is a
list of these and nothing else.

| Poor | Better |
|---|---|
| "update" | "Fix the unsigned pre-add in the droop corrector" |
| "fixed bug" | "MEM_STOP is the last address, not one past the end" |
| "changes" | "Add digital resonator on sys[4] for feedback testing" |
| "wip" | "WIP: resonator wired in, not yet built or timed" |

The rule of thumb: finish the sentence *"Applying this commit will…"*. And for anything subtle,
add a blank line and a paragraph underneath saying **why** — the same instinct that makes
`CHANGELOG.md` useful.

```powershell
git commit -m "Fix the unsigned pre-add in the droop corrector" -m @"
A concatenation is always unsigned in Verilog, and one unsigned part makes a
whole expression unsigned. The braces on the left of the colon reached across
and made the addition zero-extend, so any tap pair straddling zero contributed
an error of 2^32. Correct at the band centre, catastrophic at the edges.
"@
```

---

## 5. What is deliberately not kept

`.gitignore` lists it, with the reasoning. In short: **everything Vivado can produce for itself.**

| Not kept | Size | Why |
|---|---|---|
| `Test_Project.runs/` | 36 MB | synthesis and implementation output |
| `.../bd/system/ip/`, `ipshared/` | 34 MB | generated from `system.bd` |
| `Test_Project.cache/` | 2.7 MB | Vivado's own cache |
| `results/` | | test output — evidence, not source |
| `*.bit` | 2 MB each | see below |

**78 MB becomes 2.4 MB**, and none of what is left out is irreplaceable.

### Why bitstreams are not in git

A bitstream is a 2 MB binary that changes *completely* on every build. Git stores each version in
full, cannot show you a difference between two, and the repository would grow by 2 MB every time
you build. After a month of this project's build rate that is half a gigabyte of files nobody can
read.

The zip from `tools/backup.ps1` keeps the built bitstream. Git keeps the source that produces it.

---

## 6. The clever part: which commit is on the board?

This project lost two full days to one question — *is the chip running the code I am looking
at?* — and answered it by making the bitstream carry a fingerprint of its own source, readable
at register `0x48`.

Git closes that loop completely:

```
   register 0x48        the bitstream's fingerprint
        │
        ▼
   bitstream_id.txt     the same fingerprint, plus the COMMIT it was built from
        │
        ▼
   git checkout <commit>    the exact sources, months later, in one command
```

`build_project.tcl` now records the commit at build time, and **warns loudly if the working tree
is dirty**:

```
  *** THIS BITSTREAM WILL NOT MATCH ANY COMMIT ***
  3 file(s) are edited but not committed, so there is no commit you could
  check out later to reproduce what is about to be built.
```

Nothing is blocked — but if that build turns out to be the good one, you cannot get back to it.
**Commit before you build.** It costs ten seconds and it is the difference between a result you
can defend and one you merely remember.

---

## 7. Going back, and looking around

```powershell
git log --oneline                  # every commit, newest first
git log --oneline -- path/to/file  # ...that touched one file
git show <commit>                  # everything that commit changed
git diff                           # what I have changed but not staged
git diff HEAD~1                    # what changed since the last commit
```

To undo:

```powershell
git restore <file>            # throw away my changes to one file
git restore .                 # throw away ALL uncommitted changes  <-- careful
git revert <commit>           # a NEW commit that undoes an old one
```

`git revert` is the safe one and the one to prefer. It undoes a change by adding a change, so
the history still shows what happened and why. Rewriting history is possible and is not worth
learning yet.

To look at an old version without changing anything:

```powershell
git checkout <commit>         # look around
git checkout main             # come back
```

### Tags: naming the versions that matter

```powershell
git tag -a v1.0-stages-1-7 -m "All seven test stages pass on hardware"
git push --tags
```

A tag is a permanent, memorable name for one commit. Worth adding whenever something reaches a
state you might want to return to — "all stages passing", "before the resonator went in", "the
version in the thesis".

---

## 8. Branches, briefly and honestly

A branch is a line of work you can develop without disturbing the main one. They are the reason
git is used by large teams.

**You probably do not need one yet.** For a single person on a single machine, committing
straight to `main` is fine and simpler. The moment they become worth it is when you want to try
something substantial that might not work:

```powershell
git checkout -b try-16-bit-coefficients   # a new line of work
#  ... experiment, commit as much as you like ...
git checkout main                          # main is untouched, exactly as it was
```

If the experiment works, `git merge try-16-bit-coefficients`. If it does not, walk away and
delete the branch. Nothing on `main` ever saw it.

---

## 9. Two things people wish they had known

**A commit is not sent anywhere until you push.** `git commit` is local. If the laptop dies
between committing and pushing, the commits die with it. Push at the end of every session — it
takes a second.

**Never commit a password, key or token.** Git keeps everything for ever, so deleting the file
later does not remove it from the history. `.gitignore` already excludes `*.pem`, `*.key` and SSH
keys for this reason. If it happens anyway, treat the secret as compromised and change it — do
not just delete the file.


---

## 11. Two things that happen to everyone on day one

### "LF will be replaced by CRLF" — dozens of warnings

Expected, harmless, and it happens once.

Windows ends a line with two invisible characters, Linux with one. `.gitattributes` tells git to
store the Linux version inside the repository and give you the Windows version in your folder,
so that neither you nor the board ever has to think about it. The warning is git telling you it
noticed the difference and will handle it.

**Nothing is lost and nothing is corrupted.** The warnings stop after the first commit.

There is a small piece of evidence that it is doing the right thing: **no `.py` file appears in
that list.** All seventeen of them are pinned to Linux endings, because they run on the board,
and git leaves them exactly as they are. Everything that *was* warned about — Verilog, Markdown,
Tcl, notebooks — only ever opens on Windows or in a tool that does not care.

If you would rather not see them at all:

```powershell
git config --global core.safecrlf false
```

but they are worth reading once, because they are the only time git will mention this.

### `git init` in the wrong folder

Easily done, and **completely harmless**. Worth understanding why, because the fear is worse than
the fact.

`git init` creates **one hidden folder called `.git`** and changes nothing else. `git add` copies
file contents *into* that folder; it never alters, moves or deletes the originals. So the entire
mistake lives inside `.git`, and deleting that folder undoes all of it.

**To check whether one is still there:**

```powershell
Test-Path C:\Users\yourname\.git
```

**To see what it had captured, if anything:**

```powershell
git -C C:\Users\yourname log --oneline        # commits - probably "does not have any"
git -C C:\Users\yourname status --short | Measure-Object -Line
```

**To remove it.** Safest through File Explorer: go to `C:\Users\yourname`, turn on
View → Hidden items, and delete the folder called `.git` — that folder and nothing else. Or:

```powershell
Remove-Item -Recurse -Force C:\Users\yourname\.git
```

Check the path character by character before pressing enter. `Remove-Item -Recurse -Force` does
not ask twice.

**Was anything exposed?** No. Nothing leaves your machine until you `git push`, and a repository
created by accident has nowhere to push to. Even if `git add` had swept up SSH keys or saved
passwords, they went into `.git` and out again when you delete it.

**Does it affect this project?** No. `C:\rp\prj\v0.94\Test_Project` is not inside your home
folder, so the two repositories never knew about each other.

The one thing to avoid is leaving it there. Git looks *upwards* for a repository, so a stray one
in your home folder means that any `git` command typed in a subfolder that is not itself a
repository would quietly operate on your entire home directory.

---

## 12. The whole thing on one card

```powershell
# once
git init
git add -A
git commit -m "Working acquisition system: Test Stages 1-7 pass"
git remote add origin https://github.com/YOURNAME/REPO.git
git push -u origin main

# every day
git status
git add -A
git commit -m "what changed and why"
git push

# before every build
git status                 # clean? then the bitstream will match a commit

# when something works properly
git tag -a v1.1-resonator -m "Digital resonator, Stage 8 passing"
git push --tags
```

`tools/save.ps1` runs the daily four in one command if you would rather not type them yet — but
they are worth learning, because they are the same four on every project you will ever touch.
