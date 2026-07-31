<#
================================================================================
  SAVE TODAY'S WORK TO GIT AND GITHUB  -  training wheels
================================================================================

      .\tools\save.ps1 -m "what changed and why"

  Runs the four commands from GIT.md in order, showing you each one as it goes:

      git status        what have I changed?
      git add -A        stage all of it
      git commit        snapshot it, with your message
      git push          send it to GitHub

  THIS IS TEMPORARY, AND ON PURPOSE
  ---------------------------------
  Those four commands are the same on every project you will ever work on, and
  they are worth knowing. This script exists so that not knowing them yet is not
  a reason to go a week without committing - not so you never learn them.

  It prints each command before running it. After a fortnight you will find you
  are typing them yourself and this script has become pointless, which is the
  intention.

  OPTIONS
      -m <message>   required unless -Amend
      -NoPush        commit locally only, do not send to GitHub
      -Amend         fold these changes into the PREVIOUS commit instead of
                     making a new one. Useful for "I forgot a file". Do NOT use
                     it on anything already pushed - it rewrites that commit,
                     and the copy on GitHub will no longer agree with yours.

  IF WINDOWS REFUSES TO RUN IT
      powershell -ExecutionPolicy Bypass -File .\tools\save.ps1 -m "message"
================================================================================
#>

param(
    [Parameter(Position = 0)]
    [Alias("m")]
    [string]$Message = "",
    [switch]$NoPush,
    [switch]$Amend
)

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot

function Run($label, $argline) {
    Write-Host ""
    Write-Host "  > git $argline" -ForegroundColor Cyan
    $out = & git -C $root @($argline -split ' ') 2>&1
    $out | ForEach-Object { Write-Host "    $_" }
    return $LASTEXITCODE
}

Write-Host ""
Write-Host "===============================================================" -ForegroundColor Cyan
Write-Host " Saving work in $root" -ForegroundColor Cyan
Write-Host "===============================================================" -ForegroundColor Cyan

# --- is git here, and is this a repository? ---------------------------------
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host ""
    Write-Host " Git is not installed. Get it from https://git-scm.com/download/win" -ForegroundColor Red
    Write-Host " and see GIT.md, which walks through the whole setup." -ForegroundColor Yellow
    exit 1
}
$null = git -C $root rev-parse --git-dir 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host " This folder is not a git repository yet." -ForegroundColor Red
    Write-Host ""
    Write-Host " Three commands start one, and GIT.md explains what each does:" -ForegroundColor Yellow
    Write-Host "     git init" -ForegroundColor Cyan
    Write-Host "     git add -A" -ForegroundColor Cyan
    Write-Host '     git commit -m "Working acquisition system: Test Stages 1-7 pass"' -ForegroundColor Cyan
    exit 1
}

# --- 1. what has changed ----------------------------------------------------
Write-Host ""
Write-Host "[1/4] What has changed"
$porcelain = git -C $root status --porcelain 2>$null
$changed = @($porcelain -split "`n" | Where-Object { $_ -ne "" })
if ($changed.Count -eq 0 -and -not $Amend) {
    Write-Host "      Nothing has changed since the last commit. Nothing to do." -ForegroundColor Green
    Write-Host ""
    exit 0
}
foreach ($line in $changed) { Write-Host "      $line" }
Write-Host "      $($changed.Count) file(s)"

if (-not $Message -and -not $Amend) {
    Write-Host ""
    Write-Host " No message given. A commit without one is a snapshot nobody can use." -ForegroundColor Yellow
    Write-Host ' Finish the sentence "applying this commit will..." - for example:' -ForegroundColor Yellow
    Write-Host '     .\tools\save.ps1 -m "Add digital resonator on sys[4] for Stage 8"' -ForegroundColor Cyan
    exit 1
}

# --- 2. stage ---------------------------------------------------------------
Write-Host ""
Write-Host "[2/4] Staging everything"
if ((Run "stage" "add -A") -ne 0) { Write-Host "      git add failed." -ForegroundColor Red; exit 1 }

# --- 3. commit --------------------------------------------------------------
Write-Host ""
Write-Host "[3/4] Committing"
if ($Amend) {
    Write-Host "      (folding into the previous commit)"
    if ($Message) { $rc = & git -C $root commit --amend -m $Message 2>&1 }
    else          { $rc = & git -C $root commit --amend --no-edit 2>&1 }
} else {
    $rc = & git -C $root commit -m $Message 2>&1
}
$rc | ForEach-Object { Write-Host "    $_" }
if ($LASTEXITCODE -ne 0) {
    Write-Host "      Commit failed - nothing was saved." -ForegroundColor Red
    exit 1
}

# --- 4. push ----------------------------------------------------------------
Write-Host ""
Write-Host "[4/4] Sending to GitHub"
$remote = git -C $root remote 2>$null
if (-not $remote) {
    Write-Host "      No remote is set up, so this is saved on this machine only." -ForegroundColor Yellow
    Write-Host "      A commit that has not been pushed dies with the laptop." -ForegroundColor Yellow
    Write-Host "      GIT.md section 3 sets this up in two commands." -ForegroundColor Yellow
} elseif ($NoPush) {
    Write-Host "      Skipped (-NoPush). Remember to push before you finish." -ForegroundColor Yellow
} else {
    $out = & git -C $root push 2>&1
    $out | ForEach-Object { Write-Host "    $_" }
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "      Push failed. The commit IS saved locally - nothing is lost." -ForegroundColor Yellow
        Write-Host "      If this is the first push, it needs a one-off:" -ForegroundColor Yellow
        Write-Host "          git push -u origin main" -ForegroundColor Cyan
        Write-Host "      If it is asking for a password, GitHub no longer accepts them." -ForegroundColor Yellow
        Write-Host "      See GIT.md section 3 - 'Signing in'." -ForegroundColor Yellow
    }
}

# --- where we are now -------------------------------------------------------
Write-Host ""
Write-Host "===============================================================" -ForegroundColor Green
Write-Host " Saved." -ForegroundColor Green
Write-Host "===============================================================" -ForegroundColor Green
Write-Host ""
Write-Host " The last few commits:" -ForegroundColor Cyan
$log = & git -C $root log --oneline -5 2>&1
$log | ForEach-Object { Write-Host "     $_" }
Write-Host ""
Write-Host " Those four commands were:  status  ->  add -A  ->  commit -m  ->  push" -ForegroundColor DarkGray
Write-Host " They are the same on every project. GIT.md explains each one." -ForegroundColor DarkGray
Write-Host ""
