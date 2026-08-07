<#
================================================================================
  RUN A TEST NOTEBOOK ON THE BOARD AND BRING THE RESULTS BACK
================================================================================

  ONE COMMAND. From PowerShell on your PC, in the Test_Project folder:

      .\tools\run_on_board.ps1 "Test Stage 5 - Droop Correction.ipynb"

  It will:
     1. flatten the notebook into a plain Python script
     2. copy that script, plus the files it needs, to the board
     3. run it there as administrator, with no browser involved
     4. copy everything it printed - and any plots - back into results\

  The log lands in  results\<notebook name>.log  on your PC. That folder is
  inside the project, so anyone helping you can read it directly. No screenshots,
  no retyping, no copying numbers out of a browser.

  WHY BOTHER
  ----------
  The notebooks have to RUN on the Red Pitaya, because they read the chip's
  registers through /dev/mem, which only exists there. They do NOT have to be
  operated from the board's web page. Doing it this way means the results are a
  file on your PC rather than text in a browser tab, which makes them far easier
  to keep, compare and share.

  OPTIONS
      -Board    hostname or IP        (default rp-f007f7.local)
      -User     login name            (default root)
      -Keep     leave the generated .py in place for inspection

  IF WINDOWS REFUSES TO RUN IT
  ----------------------------
  "running scripts is disabled on this system" is Windows' default policy, not a
  fault in this file. Either allow scripts for yourself, once:

      Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

  or run this one without changing anything:

      powershell -ExecutionPolicy Bypass -File .\tools\run_on_board.ps1 "Test Stage 5 - Droop Correction.ipynb"

  THE PASSWORD PROMPTS
  --------------------
  Run this ONCE and they stop for good:

      .\tools\setup_board_access.ps1

  It sets up a key, and while it is connected also fixes the board's missing
  hostname (the cause of the "sudo: unable to resolve host" delay) and sets its
  clock.

================================================================================
#>

param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Notebook,
    [string]$Board = "rp-f007f7.local",
    [string]$User  = "root",
    [switch]$Keep
)

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
#  This script targets Windows PowerShell 5.1, which is what Windows ships with
#  and what you get by typing "powershell" or right-clicking a .ps1 file.
#
#  Nothing here uses syntax added in PowerShell 7 - no ?? , no ?: , no
#  ForEach-Object -Parallel. Those are PARSE errors on 5.1, not runtime errors,
#  which means the script fails to load at all and the error points at a line
#  that has nothing to do with what you were doing. If you edit this file, keep
#  to 5.1 syntax and test with:  powershell -File tools\run_on_board.ps1 -?
# ---------------------------------------------------------------------------
if ($PSVersionTable.PSVersion.Major -lt 5) {
    Write-Host "This needs Windows PowerShell 5.1 or newer. You have $($PSVersionTable.PSVersion)." -ForegroundColor Red
    exit 1
}

$root     = Split-Path -Parent $PSScriptRoot
$acqDir   = Join-Path $root "acquisition_custom"          # fir_coeffs.txt lives here
$nbDirs   = @((Join-Path $root "jupyter_notebooks\acquisition"),
              (Join-Path $root "jupyter_notebooks\phaseshift"))
$results  = Join-Path $root "results"
$remote   = "/root/acq_run"

# ---------------------------------------------------------------- locate it --
$nbPath = $Notebook
foreach ($d in $nbDirs) {
    if (-not (Test-Path $nbPath)) { $nbPath = Join-Path $d $Notebook }
}
if (-not (Test-Path $nbPath)) { $nbPath = Join-Path $root $Notebook }
if (-not (Test-Path $nbPath)) {
    Write-Host "Cannot find '$Notebook'." -ForegroundColor Red
    Write-Host "Notebooks available:"
    foreach ($d in $nbDirs) {
        Get-ChildItem $d -Filter *.ipynb -ErrorAction SilentlyContinue |
            ForEach-Object { Write-Host "   $($_.Name)" }
    }
    exit 1
}
$nbPath = (Resolve-Path $nbPath).Path
$base   = [IO.Path]::GetFileNameWithoutExtension($nbPath)
$safe   = ($base -replace '[^A-Za-z0-9]+', '_').Trim('_')

New-Item -ItemType Directory -Force -Path $results | Out-Null

Write-Host ""
Write-Host "===============================================================" -ForegroundColor Cyan
Write-Host " $base" -ForegroundColor Cyan
Write-Host " board: $User@$Board" -ForegroundColor Cyan
Write-Host "===============================================================" -ForegroundColor Cyan

# Tired of typing the password? Say so, once, rather than every run.
$keyOk = $false
try {
    $probe = ssh -o BatchMode=yes -o ConnectTimeout=5 "$User@$Board" "echo OK" 2>&1
    $keyOk = ($probe -match "OK")
} catch { }
if (-not $keyOk) {
    Write-Host ""
    Write-Host " This will ask for the board password a few times." -ForegroundColor Yellow
    Write-Host " To stop that for good, run once:  .\tools\setup_board_access.ps1" -ForegroundColor Yellow
}

# ------------------------------------------------------- 1. flatten it --------
Write-Host ""
Write-Host "[1/4] Flattening the notebook into a script..."
$script = Join-Path $env:TEMP "$safe.py"

# Find Python. Written the long way on purpose: the short form for this is
#     $py = (Get-Command python) ?? (Get-Command python3)
# and ?? does not exist before PowerShell 7. Windows ships 5.1 by default, where
# that line is not a runtime error but a PARSE error - so the whole script fails
# to load and the message points at a line that has nothing to do with the
# problem. Everything here sticks to 5.1 syntax.
$py = $null
foreach ($name in @("python", "python3", "py")) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) { $py = $cmd.Source; break }
}
if (-not $py) {
    Write-Host "Python was not found on this PC." -ForegroundColor Red
    Write-Host "Install it from python.org and tick 'Add Python to PATH'." -ForegroundColor Yellow
    exit 1
}
& $py (Join-Path $PSScriptRoot "nb_to_script.py") $nbPath -o $script
if ($LASTEXITCODE -ne 0) { exit 1 }

# ------------------------------------------------------- 2. copy across -------
Write-Host ""
Write-Host "[2/4] Copying to the board..."
ssh "$User@$Board" "mkdir -p $remote"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Could not reach the board. Is it powered up and on the network?" -ForegroundColor Red
    Write-Host "Try:  ping $Board" -ForegroundColor Yellow
    exit 1
}
# One scp for everything, because each connection is another password prompt
# until you have set up a key. Supporting files that are missing are skipped.
$send = @($script)
foreach ($f in @(
    (Join-Path $acqDir "fir_coeffs.txt"),
    (Join-Path $root   "Test_Project.runs\impl_1\bitstream_id.txt"),
    (Join-Path $root   "check_system.py")
)) {
    if (Test-Path $f) { $send += $f }
}
scp @send "${User}@${Board}:$remote/" | Out-Null

# ------------------------------------------------------- 3. run it ------------
Write-Host ""
Write-Host "[3/4] Running on the board (this takes a few minutes)..."
Write-Host "      Output appears below as it happens."
Write-Host ""
$logRemote = "$remote/$safe.log"
ssh "$User@$Board" "cd $remote && sudo python3 -u $safe.py 2>&1 | tee $logRemote"
$runCode = $LASTEXITCODE

# ------------------------------------------------------- 4. bring it back -----
Write-Host ""
Write-Host "[4/4] Copying results back..."
scp "${User}@${Board}:$logRemote" (Join-Path $results "$safe.log") | Out-Null

# Any figures the run produced. There may be none - a notebook with no plots, or
# one that stopped early - and scp complains when its pattern matches nothing.
# That is not a failure, so the complaint is swallowed rather than allowed to
# stop the script one line before it reports where everything was saved.
$prev = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try   { scp "${User}@${Board}:$remote/${safe}_fig*.png" $results 2>&1 | Out-Null }
catch { }
$ErrorActionPreference = $prev

if (-not $Keep) { Remove-Item $script -ErrorAction SilentlyContinue }

Write-Host ""
Write-Host "===============================================================" -ForegroundColor Cyan
Write-Host " Saved to results\" -ForegroundColor Green
Get-ChildItem $results -Filter "$safe*" | ForEach-Object {
    Write-Host ("   {0,-45} {1,8:N0} bytes" -f $_.Name, $_.Length)
}
Write-Host "===============================================================" -ForegroundColor Cyan
Write-Host ""
if ($runCode -ne 0) {
    Write-Host "The run reported a non-zero exit code ($runCode)." -ForegroundColor Yellow
    Write-Host "That is normal if a test stopped deliberately - read the log." -ForegroundColor Yellow
}
