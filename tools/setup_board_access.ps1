<#
================================================================================
  SET UP PASSWORD-FREE ACCESS TO THE BOARD  -  run this ONCE
================================================================================

      .\tools\setup_board_access.ps1

  You will type the board's password two or three times during this, and then
  never again.

  WHAT IT DOES
  ------------
  1. Makes an SSH key on this PC, if there isn't one already. A key is a pair of
     files: a private half that stays here and a public half that is safe to
     give away. The board is told to trust anyone holding the private half, and
     from then on it stops asking who you are.

  2. Copies the public half to the board.

  3. Fixes two small annoyances on the board while it is connected:

       - Its own name is missing from its hosts file, so every 'sudo' waits for
         a name lookup that can never succeed. That is the
         "sudo: unable to resolve host rp-f007f7" message, and the delay before
         anything appears. Harmless, but it wastes seconds on every run.

       - Its clock is not set and it has no battery, so log timestamps come out
         months wrong. This sets it from your PC.

  4. Checks that it worked, by connecting once with passwords disabled.

  OPTIONS
      -Board   hostname or IP    (default rp-f007f7.local)
      -User    login name        (default root)

  IF WINDOWS REFUSES TO RUN IT
      powershell -ExecutionPolicy Bypass -File .\tools\setup_board_access.ps1
================================================================================
#>

param(
    [string]$Board = "rp-f007f7.local",
    [string]$User  = "root"
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "===============================================================" -ForegroundColor Cyan
Write-Host " Password-free access to $User@$Board" -ForegroundColor Cyan
Write-Host "===============================================================" -ForegroundColor Cyan

# ---------------------------------------------------------------- 0. tools ---
if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
    Write-Host ""
    Write-Host "OpenSSH is not installed on this PC." -ForegroundColor Red
    Write-Host "Settings > System > Optional features > Add > OpenSSH Client" -ForegroundColor Yellow
    exit 1
}

# ------------------------------------------------------------- 1. the key ----
$sshDir  = Join-Path $env:USERPROFILE ".ssh"
$keyFile = Join-Path $sshDir "id_ed25519"
$pubFile = "$keyFile.pub"

Write-Host ""
Write-Host "[1/4] Key on this PC..."
if (Test-Path $pubFile) {
    Write-Host "      Already have one: $pubFile"
} else {
    if (-not (Test-Path $sshDir)) { New-Item -ItemType Directory -Path $sshDir | Out-Null }
    Write-Host "      Making one (no passphrase, so nothing to remember)..."
    ssh-keygen -t ed25519 -f $keyFile -N '""' -C "redpitaya-$env:USERNAME" | Out-Null
    if (-not (Test-Path $pubFile)) {
        Write-Host "      ssh-keygen did not produce a key." -ForegroundColor Red
        exit 1
    }
    Write-Host "      Made $pubFile"
}
$pub = (Get-Content $pubFile -Raw).Trim()

# --------------------------------------------------------- 2. trust the key --
Write-Host ""
Write-Host "[2/4] Telling the board to trust it (password needed here)..."
$remoteCmd = "mkdir -p ~/.ssh && chmod 700 ~/.ssh && " +
             "touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && " +
             "grep -qxF '$pub' ~/.ssh/authorized_keys || echo '$pub' >> ~/.ssh/authorized_keys"
ssh "$User@$Board" $remoteCmd
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Could not reach the board, or the password was wrong." -ForegroundColor Red
    Write-Host "Check it is powered up:   ping $Board" -ForegroundColor Yellow
    exit 1
}
Write-Host "      Done."

# ------------------------------------------------- 3. tidy up the board ------
Write-Host ""
Write-Host "[3/4] Fixing the sudo delay and the clock..."
$now  = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
$host_ = $Board -replace '\.local$', ''
$tidy = "grep -q '$host_' /etc/hosts || echo '127.0.1.1 $host_' >> /etc/hosts; " +
        "date -s '$now' > /dev/null; " +
        "echo '   hosts: '`$(grep '$host_' /etc/hosts | head -1); " +
        "echo '   clock: '`$(date)"
ssh "$User@$Board" $tidy

# --------------------------------------------------------------- 4. verify ---
Write-Host ""
Write-Host "[4/4] Checking it works without a password..."
$out = ssh -o BatchMode=yes -o ConnectTimeout=10 "$User@$Board" "echo OK" 2>&1
if ($out -match "OK") {
    Write-Host ""
    Write-Host "===============================================================" -ForegroundColor Green
    Write-Host " Done. No more passwords." -ForegroundColor Green
    Write-Host "===============================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host " Now try:" -ForegroundColor Cyan
    Write-Host '   .\tools\run_on_board.ps1 "Test Stage 5 - Droop Correction.ipynb"'
    Write-Host ""
} else {
    Write-Host ""
    Write-Host "Still asking for a password." -ForegroundColor Yellow
    Write-Host "The usual cause is permissions on the board. Try, as root there:" -ForegroundColor Yellow
    Write-Host "    chmod 700 ~/.ssh; chmod 600 ~/.ssh/authorized_keys" -ForegroundColor Yellow
    Write-Host "Answer was: $out"
}
