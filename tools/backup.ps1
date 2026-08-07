<#
================================================================================
  BACK UP THE PROJECT  -  sources only, so it can be rebuilt from scratch
================================================================================

  Locally, which is the usual case:

      .\tools\backup.ps1

  One dated zip in C:\rp\prj\backups, about 2 MB, in seconds. Run it whenever
  something works.

  Somewhere else, such as a USB stick:

      .\tools\backup.ps1 -To E:\

  ONCE THIS PROJECT IS IN GIT, THIS SCRIPT HAS A NARROWER JOB
  -----------------------------------------------------------
  Git keeps the sources, with their full history and a copy on GitHub. It does
  it far better than a dated zip: it records WHY each change was made, lets you
  see exactly what changed, and lets you go back to any point.

  What git deliberately does NOT keep is the built bitstream - a 2 MB binary
  that changes completely on every build, cannot be diffed, and would make the
  repository grow without limit.

  So after `git init`:

      git          the sources, the history, the reasoning, the offsite copy
      this script  the built bitstream, and a belt-and-braces copy of everything

  It now checks the repository as well, and tells you if there are changes the
  zip has captured but git has not - because a zip is a snapshot nobody will
  ever read, and a commit is a snapshot with an explanation attached.

  See GIT.md.

  WHAT GOES IN, AND WHY IT IS SO SMALL
  ------------------------------------
  Everything needed to open the project in Vivado and rebuild it, and nothing
  that Vivado can produce for itself:

      Test_Project.xpr                  the project
      Test_Project.srcs/                the Verilog, the constraints, and the
                                        block design - but see below
      jupyter_notebooks/                every notebook, its docs and its off-board tests
      acquisition_custom/               the acquisition modules, generators and docs
      phaseshift_custom/                the feedback path
      tools/                            these scripts
      *.md, build_project.tcl, ...      documentation and the build

      the last bitstream and its fingerprint  - 2 MB, and it means a working
                                        board can be restored without waiting
                                        25 minutes for a rebuild

  Left out, because Vivado regenerates all of it:

      Test_Project.runs/                36 MB of synthesis and implementation
      Test_Project.cache/               the IP cache
      .../bd/system/ip/                 13 MB of generated IP
      .../bd/system/ipshared/           21 MB of Xilinx library HDL
      results/, __pycache__/, .Xil/     test output and scratch

  That last pair is worth being sure about, because excluding a real source
  would produce a backup that cannot be restored. They are safe: `system.bd`
  carries all 303 processor parameters itself - HP ports, widths, clocks - and
  the project file lists only `system.bd` and `system_wrapper.v`. Everything
  under ip/ and ipshared/ is an OUTPUT of the block design, and
  `build_project.tcl` regenerates it if it is missing.

  Result: 78 MB becomes about 2 MB zipped.

  -Full includes everything, exactly as before, if you want a copy that opens
  without regenerating anything.

  IT CHECKS ITSELF
  ----------------
  A backup you cannot restore is worse than no backup, because you stop
  worrying. After writing the archive this reads it back and confirms every
  file on a required list is present. If one is missing it says so and leaves
  the archive for inspection rather than pretending.

  OPTIONS
      -To           where to put it   (default C:\rp\prj\backups)
      -Full         everything, including the regenerable 76 MB
      -NoBitstream  leave the built bitstream out as well
      -Keep <n>     keep the newest n backups (default 10)

  IF WINDOWS REFUSES TO RUN IT
      powershell -ExecutionPolicy Bypass -File .\tools\backup.ps1
================================================================================
#>

param(
    [string]$To = "",
    [switch]$Full,
    [switch]$NoBitstream,
    [int]$Keep = 10
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
if (-not $To) {
    $To = Join-Path (Split-Path -Parent (Split-Path -Parent $root)) "backups"
}

$stamp = Get-Date -Format "yyyy-MM-dd_HHmm"
$kind  = if ($Full) { "full" } else { "src" }
$name  = "Test_Project_${kind}_$stamp"

Write-Host ""
Write-Host "===============================================================" -ForegroundColor Cyan
Write-Host " Backing up $root" -ForegroundColor Cyan
Write-Host " to          $To" -ForegroundColor Cyan
Write-Host " mode        $(if ($Full) {'everything'} else {'sources only - rebuildable'})" -ForegroundColor Cyan
Write-Host "===============================================================" -ForegroundColor Cyan

# --- refuse to write into the project ---------------------------------------
$rootFull = [IO.Path]::GetFullPath($root).TrimEnd('\') + '\'
$toFull   = [IO.Path]::GetFullPath($To).TrimEnd('\') + '\'
if ($toFull.StartsWith($rootFull, [StringComparison]::OrdinalIgnoreCase)) {
    Write-Host ""
    Write-Host " That destination is inside the project." -ForegroundColor Red
    Write-Host " Every backup would then contain the last one. Pick somewhere else." -ForegroundColor Yellow
    exit 1
}
if (-not (Test-Path $To)) { New-Item -ItemType Directory -Force -Path $To | Out-Null }

# --- is Vivado running? -----------------------------------------------------
if (Get-Process -Name "vivado*" -ErrorAction SilentlyContinue) {
    Write-Host ""
    Write-Host " Vivado is running. If a build is in progress the copy may catch a" -ForegroundColor Yellow
    Write-Host " checkpoint half-written. Close it first if you can." -ForegroundColor Yellow
    Write-Host ""
    if ((Read-Host " Carry on anyway? (y/N)") -ne "y") { exit 1 }
}

# --- where does git think we are? -------------------------------------------
$gitCommit = ""
$gitDirty  = 0
$gitKnown  = $false
if (Get-Command git -ErrorAction SilentlyContinue) {
    $null = git -C $root rev-parse --git-dir 2>$null
    if ($LASTEXITCODE -eq 0) {
        $gitKnown  = $true
        $gitCommit = (git -C $root rev-parse --short HEAD 2>$null)
        $st = git -C $root status --porcelain 2>$null
        if ($st) { $gitDirty = @($st -split "`n" | Where-Object { $_ -ne "" }).Count }
    }
}

# --- copy -------------------------------------------------------------------
Write-Host ""
Write-Host "[1/4] Copying..."
$stage = Join-Path $env:TEMP $name
$rc = @($root, $stage, "/E", "/R:1", "/W:1", "/NFL", "/NDL", "/NJH", "/NJS", "/NP")

if (-not $Full) {
    #  Directories Vivado rebuilds for itself. Named by full path where the name
    #  alone would be ambiguous.
    foreach ($d in @("Test_Project.runs", "Test_Project.cache", "Test_Project.hbs",
                     "Test_Project.hw", "Test_Project.sim", "Test_Project.ip_user_files",
                     "results")) {
        $rc += @("/XD", (Join-Path $root $d))
    }
    $bd = Join-Path $root "Test_Project.srcs\sources_1\bd\system"
    $rc += @("/XD", (Join-Path $bd "ip"), "/XD", (Join-Path $bd "ipshared"))
    #  Scratch, anywhere it appears
    $rc += @("/XD", "__pycache__", "/XD", ".Xil")
}

robocopy @rc | Out-Null
if ($LASTEXITCODE -ge 8) {
    Write-Host "      robocopy reported errors (code $LASTEXITCODE)." -ForegroundColor Red
    exit 1
}

# --- the built bitstream, which is an output but a very useful one ----------
if (-not $Full -and -not $NoBitstream) {
    $impl = Join-Path $root "Test_Project.runs\impl_1"
    $dest = Join-Path $stage "Test_Project.runs\impl_1"
    $any = $false
    foreach ($f in @("red_pitaya_top.bit", "bitstream_id.txt")) {
        $src = Join-Path $impl $f
        if (Test-Path $src) {
            New-Item -ItemType Directory -Force -Path $dest | Out-Null
            Copy-Item $src $dest
            $any = $true
        }
    }
    if ($any) { Write-Host "      included the built bitstream, so a working board can be" }
    if ($any) { Write-Host "      restored without a rebuild" }
}

# A note inside the archive saying what this is a copy OF. Without it, a zip
# found in six months is a pile of files with no provenance.
$info = @()
$info += "Backup of the Red Pitaya acquisition project"
$info += "taken   : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
$info += "mode    : $(if ($Full) {'everything'} else {'sources only, rebuildable'})"
if ($gitKnown) {
    $info += "commit  : $gitCommit"
    if ($gitDirty -gt 0) {
        $info += "WARNING : $gitDirty file(s) were edited but not committed when this"
        $info += "          was taken, so this zip does NOT correspond to that commit."
    } else {
        $info += "restore : git checkout $gitCommit"
    }
} else {
    $info += "commit  : not a git repository - see GIT.md"
}
$info | Set-Content (Join-Path $stage "BACKUP_INFO.txt")

$mb = [math]::Round((Get-ChildItem $stage -Recurse -File |
                     Measure-Object Length -Sum).Sum / 1MB, 1)
Write-Host "      $mb MB staged."

# --- zip --------------------------------------------------------------------
Write-Host ""
Write-Host "[2/4] Zipping..."
$zip = Join-Path $To "$name.zip"
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip -Force
$zmb = [math]::Round((Get-Item $zip).Length / 1MB, 2)
Write-Host "      $zip"
Write-Host "      $zmb MB"

# --- check it can actually be restored --------------------------------------
Write-Host ""
Write-Host "[3/4] Checking the archive contains what a rebuild needs..."
$required = @(
    "Test_Project.xpr",
    "Test_Project.srcs/sources_1/bd/system/system.bd",
    "Test_Project.srcs/sources_1/bd/system/hdl/system_wrapper.v",
    "Test_Project.srcs/sources_1/imports/rp/prj/v0.94/rtl/red_pitaya_top.sv",
    "Test_Project.srcs/sources_1/imports/rp/prj/v0.94/rtl/red_pitaya_ps.sv",
    "Test_Project.srcs/sources_1/imports/rp/rtl/classic/red_pitaya_acq.v",
    "Test_Project.srcs/sources_1/imports/rp/rtl/classic/red_pitaya_resonator.v",
    "Test_Project.srcs/sources_1/imports/rp/rtl/classic/red_pitaya_phaseshift.v",
    "Test_Project.srcs/sources_1/imports/rp/rtl/classic/fir_coeffs.vh",
    "build_project.tcl",
    "acquisition_custom/add_acquisition_sources.tcl",
    "acquisition_custom/gen_fir_coeffs.py",
    "HANDOVER.md"
)
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::OpenRead($zip)
$names = @{}
foreach ($e in $archive.Entries) { $names[$e.FullName.Replace('\','/')] = $true }
$archive.Dispose()

$missing = @()
foreach ($r in $required) { if (-not $names.ContainsKey($r)) { $missing += $r } }

if ($missing.Count -gt 0) {
    Write-Host ""
    Write-Host "      *** THIS ARCHIVE IS NOT RESTORABLE ***" -ForegroundColor Red
    foreach ($m in $missing) { Write-Host "      missing: $m" -ForegroundColor Red }
    Write-Host "      Left in place for inspection. Do not rely on it." -ForegroundColor Yellow
    Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
    exit 1
}
Write-Host "      All $($required.Count) required files present, $($names.Count) files in total."
Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue

# --- prune ------------------------------------------------------------------
Write-Host ""
Write-Host "[4/4] Backups now held:"
$all = Get-ChildItem $To -Filter "Test_Project_*.zip" | Sort-Object LastWriteTime -Descending
$i = 0
foreach ($f in $all) {
    $i++
    if ($i -le $Keep) {
        Write-Host ("      {0,-38} {1,7:N2} MB   {2}" -f $f.Name, ($f.Length / 1MB),
                    $f.LastWriteTime.ToString("yyyy-MM-dd HH:mm"))
    } else {
        Remove-Item $f.FullName -Force
        Write-Host ("      {0,-38} deleted (keeping the newest {1})" -f $f.Name, $Keep)
    }
}

Write-Host ""
Write-Host "===============================================================" -ForegroundColor Green
Write-Host " Done." -ForegroundColor Green
Write-Host "===============================================================" -ForegroundColor Green
Write-Host ""
Write-Host " TO RESTORE: extract the zip, open Test_Project.xpr in Vivado 2020.1," -ForegroundColor Cyan
Write-Host " then run   source .../build_project.tcl   which regenerates the block" -ForegroundColor Cyan
Write-Host " design's output products before building. See BACKUP.md." -ForegroundColor Cyan
Write-Host ""
if ($gitKnown -and $gitDirty -gt 0) {
    Write-Host " $gitDirty file(s) are in this zip but NOT in git." -ForegroundColor Yellow
    Write-Host " A zip is a snapshot nobody will read. A commit is a snapshot with an" -ForegroundColor Yellow
    Write-Host " explanation attached, and it goes offsite. Worth two lines:" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "     git add -A" -ForegroundColor Cyan
    Write-Host "     git commit -m \"what changed and why\"" -ForegroundColor Cyan
    Write-Host "     git push" -ForegroundColor Cyan
    Write-Host ""
} elseif ($gitKnown) {
    Write-Host " Sources are committed at $gitCommit and nothing is outstanding." -ForegroundColor Green
    Write-Host " This zip is really for the bitstream; git has the rest." -ForegroundColor Green
    Write-Host ""
} else {
    Write-Host " This project is not in git. Ten minutes of setup would give you the" -ForegroundColor Yellow
    Write-Host " full history of every change, an offsite copy, and the ability to go" -ForegroundColor Yellow
    Write-Host " back to any point. See GIT.md." -ForegroundColor Yellow
    Write-Host ""
}
