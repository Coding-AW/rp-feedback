# Run focused regressions for the timing fixes without launching synthesis or
# implementation. The test uses the actual phase-shifter RTL and a literal lift
# of the top-level OUT2/digital-loopback arithmetic.

$ErrorActionPreference = 'Stop'

$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$rtl = Join-Path $root 'fpga\red_pitaya_phaseshift.v'
$testbench = Join-Path $PSScriptRoot 'tb_timing_fixes.sv'
$vivadoBin = 'C:\Xilinx\Vivado\2020.1\bin'
$xvlog = Join-Path $vivadoBin 'xvlog.bat'
$xelab = Join-Path $vivadoBin 'xelab.bat'
$xsim = Join-Path $vivadoBin 'xsim.bat'

foreach ($tool in @($xvlog, $xelab, $xsim)) {
    if (-not (Test-Path -LiteralPath $tool -PathType Leaf)) {
        throw "Vivado simulator tool not found: $tool"
    }
}

Push-Location $root
try {
    & $xvlog --sv $testbench $rtl
    if ($LASTEXITCODE -ne 0) { throw "xvlog failed with exit code $LASTEXITCODE" }
    & $xelab tb_timing_fixes -s timing_fixes_sim
    if ($LASTEXITCODE -ne 0) { throw "xelab failed with exit code $LASTEXITCODE" }
    & $xsim timing_fixes_sim -runall
    if ($LASTEXITCODE -ne 0) { throw "xsim failed with exit code $LASTEXITCODE" }
}
finally {
    Pop-Location
}
