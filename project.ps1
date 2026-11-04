<#
.SYNOPSIS
    Test, load and rebuild the Red Pitaya feedback system from this computer.

.DESCRIPTION
    test    offline checks of the gateware sources and both notebooks (no board needed)
    deploy  load the qualified bitstream onto the board, then run the board health check
            (-UseBuild loads your own build instead of the qualified copy)
    sync    copy both notebooks to /root/jupyter_notebooks on the board
    build   rebuild the bitstream with Vivado 2020.1 (15-25 minutes)

    The board is root@rp-f007f7.local unless -Board or $env:RP_BOARD names another.

.EXAMPLE
    .\project.ps1 deploy
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('test', 'deploy', 'sync', 'build')]
    [string]$Command = 'test',

    [string]$Board = $(if ($env:RP_BOARD) { $env:RP_BOARD } else { 'root@rp-f007f7.local' }),

    [switch]$UseBuild
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$LockPath = Join-Path $Root 'fpga\upstream.lock'
$Cache = Join-Path $Root '.cache'
$Upstream = Join-Path $Cache 'upstream'
$BuildRuns = Join-Path $Upstream 'prj\v0.94\project\redpitaya.runs'
$Notebooks = @(
    (Join-Path $Root 'notebooks\test_noise_passive_feedback.ipynb'),
    (Join-Path $Root 'notebooks\resonator_coil_manual_high_k.ipynb')
)

function Read-Lock {
    $values = @{}
    foreach ($line in Get-Content -LiteralPath $LockPath) {
        if ($line -match '^([^#=]+)=(.*)$') { $values[$matches[1]] = $matches[2] }
    }
    return $values
}

function Invoke-Native([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed with exit code $LASTEXITCODE" }
}

function Invoke-Python([string[]]$Arguments) {
    # Prefer the Windows launcher (py -3); fall back to python on the PATH.
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) { Invoke-Native $launcher.Source (@('-3') + $Arguments) }
    else { Invoke-Native (Get-Command python -ErrorAction Stop).Source $Arguments }
}

function Copy-Overlay {
    # Project-owned files replace their upstream counterparts.
    $classic = Join-Path $Upstream 'rtl\classic'
    Copy-Item -Force (Join-Path $Root 'fpga\red_pitaya_top.sv') (Join-Path $Upstream 'prj\v0.94\rtl')
    Copy-Item -Force (Join-Path $Root 'fpga\systemZ10.tcl') (Join-Path $Upstream 'prj\v0.94\ip')
    Copy-Item -Force (Join-Path $Root 'fpga\red_pitaya.xdc') (Join-Path $Upstream 'sdc')
    Copy-Item -Force (Join-Path $Root 'fpga\project.xdc') (Join-Path $Upstream 'prj\v0.94\sdc\red_pitaya.xdc')

    $classicFiles = @(
        'axi_master.v', 'build_id.vh', 'fir_coeffs.vh', 'fir_params.vh',
        'red_pitaya_acq.v', 'red_pitaya_acq_cic.v', 'red_pitaya_acq_dds.v',
        'red_pitaya_acq_dma.v', 'red_pitaya_acq_fir.v', 'red_pitaya_acq_mixer.v',
        'red_pitaya_phaseshift.v', 'red_pitaya_resonator.v',
        'red_pitaya_scope.v', 'red_pitaya_sequencer.v'
    )
    foreach ($name in $classicFiles) {
        Copy-Item -Force (Join-Path $Root "fpga\$name") $classic
    }
}

function Setup-Upstream {
    $lock = Read-Lock
    foreach ($key in 'repository', 'commit', 'project', 'model', 'part', 'vivado', 'archive_sha256') {
        if (-not $lock[$key]) { throw "Missing '$key' in fpga/upstream.lock" }
    }
    if ($lock.project -ne 'v0.94' -or $lock.model -ne 'Z10' -or $lock.part -ne 'xc7z010clg400-1') {
        throw 'upstream.lock does not describe the supported STEMlab 125-14 target'
    }

    New-Item -ItemType Directory -Force -Path $Cache | Out-Null
    $archive = Join-Path $Cache "redpitaya-fpga-$($lock.commit).zip"
    $stamp = Join-Path $Upstream '.rp-feedback-upstream'
    $ready = (Test-Path $stamp) -and ((Get-Content -Raw $stamp).Trim() -eq $lock.commit)

    if (-not $ready) {
        if (-not (Test-Path $archive)) {
            $url = "$($lock.repository)/archive/$($lock.commit).zip"
            Write-Host "Downloading pinned RedPitaya-FPGA $($lock.commit.Substring(0, 8))..."
            Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $archive
        }
        $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()
        if ($actual -ne $lock.archive_sha256.ToLowerInvariant()) {
            throw "Upstream archive checksum mismatch. Expected $($lock.archive_sha256), got $actual"
        }

        $extract = Join-Path $Cache "extract-$($lock.commit)"
        if (Test-Path $extract) { Remove-Item -LiteralPath $extract -Recurse -Force }
        New-Item -ItemType Directory -Force -Path $extract | Out-Null
        Expand-Archive -LiteralPath $archive -DestinationPath $extract
        $source = Get-ChildItem -LiteralPath $extract -Directory | Select-Object -First 1
        if (-not $source) { throw 'The upstream archive did not contain a source directory' }
        if (Test-Path $Upstream) { Remove-Item -LiteralPath $Upstream -Recurse -Force }
        Move-Item -LiteralPath $source.FullName -Destination $Upstream
        Remove-Item -LiteralPath $extract -Recurse -Force
        Set-Content -NoNewline -Encoding ascii -LiteralPath $stamp -Value $lock.commit
    }

    if (-not (Test-Path (Join-Path $Upstream 'prj\v0.94\rtl\red_pitaya_top.sv'))) {
        throw 'Pinned archive does not contain the required v0.94 project'
    }
    Copy-Overlay
    Write-Host "Ready: RedPitaya-FPGA $($lock.commit.Substring(0, 8)), v0.94, STEMlab 125-14."
}

function Run-Tests {
    $env:PYTHONDONTWRITEBYTECODE = '1'   # keep the tree free of __pycache__
    Invoke-Python @((Join-Path $Root 'tools\verify_golden.py'))
    Invoke-Python @((Join-Path $Root 'tools\verify_rtl.py'))
    Invoke-Python (@((Join-Path $Root 'tools\verify_notebooks.py')) + $Notebooks)
    Push-Location $Root
    try { Invoke-Python @('-m', 'unittest', 'discover', '-s', 'tests', '-t', '.') }
    finally { Pop-Location }
}

function Get-DeployImage {
    # The qualified copy in bitstream/ unless -UseBuild selects the latest build.
    $folder = if ($UseBuild) { Join-Path $BuildRuns 'impl_1' } else { Join-Path $Root 'bitstream' }
    $bit = Join-Path $folder 'red_pitaya_top.bit'
    $id = Join-Path $folder 'bitstream_id.txt'
    if (-not (Test-Path $bit) -or -not (Test-Path $id)) {
        if ($UseBuild) { throw 'No build found. Run .\project.ps1 build first.' }
        throw "The qualified bitstream is missing from $folder."
    }
    $record = Get-Content -LiteralPath $id -Raw
    if ($record -notmatch '(?m)^FE76AE09\s*$') {
        throw 'Refusing to deploy: bitstream_id.txt does not name the qualified FE76AE09 hardware ID.'
    }
    if ($record -notmatch '(?m)^# timing\s+: PASS\b') {
        throw 'Refusing to deploy: this bitstream has not passed timing.'
    }
    return @($bit, $id)
}

switch ($Command) {
    'test' { Run-Tests }
    'build' {
        Run-Tests
        Setup-Upstream
        $vivado = Get-Command vivado.bat -ErrorAction SilentlyContinue
        if (-not $vivado) { $vivado = Get-Command vivado -ErrorAction SilentlyContinue }
        $vivadoPath = if ($vivado) { $vivado.Source } else { 'C:\Xilinx\Vivado\2020.1\bin\vivado.bat' }
        if (-not (Test-Path $vivadoPath)) {
            throw 'Vivado 2020.1 was not found on PATH or under C:\Xilinx\Vivado\2020.1.'
        }
        Invoke-Native $vivadoPath @('-mode', 'batch', '-source', (Join-Path $Root 'fpga\build.tcl'), '-tclargs', $Root, $Upstream)
    }
    'deploy' {
        # One copy and one command: load the bitstream, then run the health check
        # (it reads the identifier and briefly writes and restores two registers).
        $bit, $id = Get-DeployImage
        Invoke-Native 'scp' @($bit, $id, (Join-Path $Root 'board\check_system.py'), "${Board}:/root/")
        Invoke-Native 'ssh' @($Board, 'cat /root/red_pitaya_top.bit > /dev/xdevcfg && python3 /root/check_system.py')
    }
    'sync' {
        $remote = '/root/jupyter_notebooks'
        Invoke-Native 'ssh' @($Board, "mkdir -p $remote")
        Invoke-Native 'scp' ($Notebooks + @("${Board}:${remote}/"))
        Write-Host "Copied the two notebooks to ${Board}:${remote}."
    }
}
