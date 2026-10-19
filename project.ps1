<#
.SYNOPSIS
    Set up, check, build and deploy the Red Pitaya feedback system.

.DESCRIPTION
    setup   download the pinned RedPitaya-FPGA v0.94 source and lay fpga/ over it
    test    golden-source, RTL-name and notebook checks, then the offline tests
    build   setup + test, then synthesise and implement with Vivado 2020.1
    deploy  copy a bitstream and its bitstream_id.txt to the board and load it
            (the qualified bitstream/ copy by default; -UseBuild for your own build)
    check   run board/check_system.py on the board
    sync    copy both notebooks to /root/jupyter_notebooks on the board
    clean   remove the generated Vivado project (the upstream cache stays)

.EXAMPLE
    $env:RP_BOARD = 'rp-f007f7.local'
    .\project.ps1 deploy
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('setup', 'test', 'build', 'deploy', 'sync', 'check', 'clean')]
    [string]$Command = 'test',

    [string]$Board = $(if ($env:RP_BOARD) { $env:RP_BOARD } else { '<board-hostname>' }),

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

function Assert-Board {
    if ($Board -eq '<board-hostname>') { throw "Specify -Board <hostname> or set RP_BOARD before '$Command'." }
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
    Invoke-Python @((Join-Path $Root 'tools\verify_golden.py'))
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
    'setup' { Setup-Upstream }
    'test' { Run-Tests }
    'build' {
        Setup-Upstream
        Run-Tests
        $vivado = Get-Command vivado.bat -ErrorAction SilentlyContinue
        if (-not $vivado) { $vivado = Get-Command vivado -ErrorAction SilentlyContinue }
        $vivadoPath = if ($vivado) { $vivado.Source } else { 'C:\Xilinx\Vivado\2020.1\bin\vivado.bat' }
        if (-not (Test-Path $vivadoPath)) {
            throw 'Vivado 2020.1 was not found on PATH or under C:\Xilinx\Vivado\2020.1.'
        }
        Invoke-Native $vivadoPath @('-mode', 'batch', '-source', (Join-Path $Root 'fpga\build.tcl'), '-tclargs', $Root, $Upstream)
    }
    'deploy' {
        Assert-Board
        $bit, $id = Get-DeployImage
        Invoke-Native 'scp' @($bit, $id, (Join-Path $Root 'board\check_system.py'), "${Board}:/root/")
        Invoke-Native 'ssh' @($Board, 'cat /root/red_pitaya_top.bit > /dev/xdevcfg')
        Write-Host "Loaded $bit on $Board."
    }
    'sync' {
        Assert-Board
        $remote = '/root/jupyter_notebooks'
        Invoke-Native 'ssh' @($Board, "mkdir -p $remote")
        Invoke-Native 'scp' ($Notebooks + @("${Board}:${remote}/"))
        Write-Host "Copied the two notebooks to ${Board}:${remote}."
    }
    'check' {
        Assert-Board
        Invoke-Native 'scp' @((Join-Path $Root 'board\check_system.py'), "${Board}:/root/check_system.py")
        Invoke-Native 'ssh' @($Board, 'sudo python3 /root/check_system.py')
    }
    'clean' {
        $project = Join-Path $Upstream 'prj\v0.94\project'
        if (Test-Path $project) { Remove-Item -LiteralPath $project -Recurse -Force }
        Write-Host 'Removed the generated Vivado project; the upstream cache remains available offline.'
    }
}
