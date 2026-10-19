[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('setup', 'test', 'build', 'deploy', 'sync', 'check', 'clean')]
    [string]$Command = 'test',

    [string]$Board = $(if ($env:RP_BOARD) { $env:RP_BOARD } else { '<board-hostname>' })
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$LockPath = Join-Path $Root 'fpga\upstream.lock'
$Cache = Join-Path $Root '.cache'
$Upstream = Join-Path $Cache 'upstream'
$BuildRuns = Join-Path $Upstream 'prj\v0.94\project\redpitaya.runs'

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

function Invoke-GoldenCheck {
    $python = Get-Command py -ErrorAction SilentlyContinue
    if ($python) { Invoke-Native $python.Source @('-3', (Join-Path $Root 'tools\verify_golden.py')); return }
    $python = Get-Command python -ErrorAction Stop
    Invoke-Native $python.Source @((Join-Path $Root 'tools\verify_golden.py'))
}

function Copy-Overlay([hashtable]$Lock) {
    $classic = Join-Path $Upstream 'rtl\classic'
    $projectRtl = Join-Path $Upstream 'prj\v0.94\rtl'
    $projectIp = Join-Path $Upstream 'prj\v0.94\ip'
    $commonSdc = Join-Path $Upstream 'sdc'
    $projectSdc = Join-Path $Upstream 'prj\v0.94\sdc'

    Copy-Item -Force (Join-Path $Root 'fpga\red_pitaya_top.sv') $projectRtl
    Copy-Item -Force (Join-Path $Root 'fpga\systemZ10.tcl') $projectIp
    Copy-Item -Force (Join-Path $Root 'fpga\red_pitaya.xdc') $commonSdc
    Copy-Item -Force (Join-Path $Root 'fpga\project.xdc') (Join-Path $projectSdc 'red_pitaya.xdc')

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
    Invoke-GoldenCheck
    $lock = Read-Lock
    foreach ($key in 'repository', 'commit', 'project', 'model', 'part', 'vivado', 'archive_sha256') {
        if (-not $lock[$key]) { throw "Missing '$key' in fpga/upstream.lock" }
    }
    if ($lock.project -ne 'v0.94' -or $lock.model -ne 'Z10' -or $lock.part -ne 'xc7z010clg400-1') {
        throw 'upstream.lock does not describe the supported STEMlab 125-14 target'
    }
    if ($lock.archive_sha256 -eq 'TO_BE_FILLED') { throw 'fpga/upstream.lock has no archive checksum' }

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
    Copy-Overlay $lock
    Write-Host "Ready: RedPitaya-FPGA $($lock.commit.Substring(0, 8)), v0.94, STEMlab 125-14."
}

function Run-Tests {
    # Keep the handover tree clean when Python imports the notebook tests.
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $python = Get-Command py -ErrorAction SilentlyContinue
    if ($python) { $exe = $python.Source; $prefix = @('-3') }
    else { $python = Get-Command python -ErrorAction Stop; $exe = $python.Source; $prefix = @() }

    Invoke-Native $exe ($prefix + @((Join-Path $Root 'tools\verify_golden.py')))
    Invoke-Native $exe ($prefix + @((Join-Path $Root 'tools\verify_rtl.py')))
    $notebooks = @(
        (Join-Path $Root 'notebooks\test_noise_passive_feedback.ipynb'),
        (Join-Path $Root 'notebooks\resonator_coil_manual_high_k.ipynb')
    )
    Invoke-Native $exe ($prefix + @((Join-Path $Root 'tools\verify_notebooks.py')) + $notebooks)
    Invoke-Native $exe ($prefix + @('-m', 'unittest',
        'tests.python.test_noise_passive_feedback',
        'tests.python.test_manual_feedback_measurement',
        'tests.python.test_acquisition_filter_calibration',
        'tests.python.test_feedback_gain_phase_map',
        'tests.python.test_continuous_feedback_hold',
        'tests.python.test_manual_high_k'))
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
        if ($Board -eq '<board-hostname>') { throw 'Specify -Board <hostname> or set RP_BOARD before deployment.' }
        $bit = Join-Path $BuildRuns 'impl_1\red_pitaya_top.bit'
        $id = Join-Path $BuildRuns 'impl_1\bitstream_id.txt'
        if (-not (Test-Path $bit) -or -not (Test-Path $id)) { throw 'No verified build found. Run .\project.ps1 build first.' }
        $buildRecord = Get-Content -LiteralPath $id -Raw
        if ($buildRecord -notmatch '(?m)^FE76AE09\s*$') {
            throw 'Refusing to deploy: register 0x48 is not the qualified FE76AE09 hardware ID.'
        }
        if ($buildRecord -notmatch '(?m)^# timing\s+: PASS\b') {
            throw 'Refusing to deploy: the latest bitstream has not passed timing. Run .\project.ps1 build and inspect its result.'
        }
        Invoke-Native 'scp' @($bit, $id, (Join-Path $Root 'software\check_system.py'), "${Board}:/root/")
        Invoke-Native 'ssh' @($Board, 'cat /root/red_pitaya_top.bit > /dev/xdevcfg')
        Write-Host "Loaded the bitstream on $Board."
    }
    'sync' {
        if ($Board -eq '<board-hostname>') { throw 'Specify -Board <hostname> or set RP_BOARD before syncing.' }
        $remote = '/root/jupyter_notebooks'
        Invoke-Native 'ssh' @($Board, "mkdir -p $remote")
        Invoke-Native 'scp' @(
            (Join-Path $Root 'notebooks\test_noise_passive_feedback.ipynb'),
            (Join-Path $Root 'notebooks\resonator_coil_manual_high_k.ipynb'),
            "${Board}:${remote}/"
        )
        Write-Host "Copied the two handover notebooks to ${Board}:${remote}."
    }
    'check' {
        if ($Board -eq '<board-hostname>') { throw 'Specify -Board <hostname> or set RP_BOARD before checking the board.' }
        Invoke-Native 'scp' @((Join-Path $Root 'software\check_system.py'), "${Board}:/root/check_system.py")
        Invoke-Native 'ssh' @($Board, 'sudo python3 /root/check_system.py')
    }
    'clean' {
        $project = Join-Path $Upstream 'prj\v0.94\project'
        if (Test-Path $project) { Remove-Item -LiteralPath $project -Recurse -Force }
        Write-Host 'Removed generated Vivado project output; the upstream cache remains available offline.'
    }
}
