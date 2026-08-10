# Run the parameter-sequencer regression against the actual Verilog with XSim.
# This is separate from run_rtl_sim.sh: that script uses Yosys for before/after
# equivalence, while this test uses the Vivado simulator already installed for
# this FPGA project.

$ErrorActionPreference = 'Stop'

$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$rtl = Join-Path $root 'fpga\red_pitaya_sequencer.v'
$testbench = Join-Path $PSScriptRoot 'tb_sequencer.sv'
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

    & $xelab tb -s sequencer_bus_sim
    if ($LASTEXITCODE -ne 0) { throw "xelab failed with exit code $LASTEXITCODE" }

    & $xsim sequencer_bus_sim -runall
    if ($LASTEXITCODE -ne 0) { throw "xsim failed with exit code $LASTEXITCODE" }
}
finally {
    Pop-Location
}
