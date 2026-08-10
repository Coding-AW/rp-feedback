# Build, deploy, and recover

Run all commands from the repository root in Windows PowerShell.

## First setup

```powershell
.\project.ps1 setup
```

This downloads one pinned RedPitaya-FPGA archive, verifies its checksum, extracts
it into `.cache/upstream`, and overlays the files in `fpga/`. Delete `.cache/`
only when you intentionally want to repeat the download.

## Test and build

```powershell
.\project.ps1 test
.\project.ps1 build
```

`build` runs the quick checks first, creates a clean v0.94 Vivado project, forces
synthesis and implementation, and checks timing. Register `0x48` remains the
fixed qualified ID `FE76AE09`; source provenance is written beside the image.
The bitstream and `bitstream_id.txt` are written below:

```text
.cache/upstream/prj/v0.94/project/redpitaya.runs/impl_1/
```

Do not build with Vivado's Generate Bitstream button: it can reuse a stale
netlist and bypass the fingerprint checks.

## Deploy and verify

```powershell
.\project.ps1 deploy -Board <board-hostname>
.\project.ps1 check  -Board <board-hostname>
```

Set `RP_BOARD` if you do not want to pass `-Board` each time. Deployment copies
the bitstream, fingerprint, and health-check script to `/root`, then programs
`/dev/xdevcfg`. The check is read-only.

Deployment reads `bitstream_id.txt` first and refuses any image whose timing
status is missing or is not `PASS`. Register `0x48` is the fixed qualified
hardware ID `FE76AE09`; commit and source provenance are stored only in that
manifest so they cannot perturb FPGA placement.

## External spectrum-analyser Q check

Open `notebooks/acquisition/resonator_coil_characterisation.ipynb` and run it in
order through Step 8d. Wire OUT1 to the resonator drive/feedback path, the
resonator response to IN1, and OUT2 to the spectrum-analyser input.

For each fraction `-0.70`, `0`, `+0.70`, and `+0.90`:

1. Run `external_q_prepare(frac)` and copy its centre, span, and RBW settings.
2. Select logarithmic power and max hold on the analyser, then clear its trace.
3. Run `external_q_replay(frac)` and wait for every repetition.
4. Export frequency and level as CSV.
5. Open `notebooks/acquisition/external_spectrum_analysis.ipynb` and analyse the
   exported CSV there.

External replay uses four max-hold repetitions by default. If separate analysis
reports too few impulses, inconsistent coverage, or inadequate span, discard
the trace and repeat with a larger explicit value such as
`external_q_replay(frac, repeats=8)`.

The coil-characterisation notebook intentionally performs acquisition only;
CSV peak extraction, Lorentzian fitting, Q calculation, and plotting are kept
in the separate analysis notebook. The replay checks the hardware ID, generator
B, sequencer source, phase/gain, delay, bypass, OUT2 routing, IN1 level, and
OUT2 clipping. Its `finally` path always turns off the drive, feedback, and OUT2
monitor. A clipped trace must be discarded.

### Phase/gain resonance shifts

Step 8e-ext uses the same one-trace workflow as the external Q measurement. For
each chosen gain and phase:

1. Run `external_shift_prepare(phase_deg, gain_frac)` and copy its centre, span,
   and RBW settings.
2. Select logarithmic power and max hold on the analyser, then clear its trace.
3. Run `external_shift_replay(phase_deg, gain_frac)` and wait for every repetition.
4. Export the trace using the printed filename.

The same four-repetition default applies here. If coverage validation rejects
the CSV, reacquire it with `external_shift_replay(phase_deg, gain_frac,
repeats=8)` or another larger value.

Gain is a fraction of the measured safe ceiling and is limited to `0...0.95`;
`0.90` and `0.95` are useful high-gain choices. Phase is freely selectable in
degrees and is normalised modulo 360. There is no hardware campaign generator:
the user chooses and acquires each point explicitly, while exported CSV analysis
remains in `external_spectrum_analysis.ipynb`. In that analysis notebook,
`print_maximum_shifts()` selects the phase giving the largest fitted reduction
at the original resonance frequency, while also reporting the signed centre
shift in units of the zero-feedback linewidth. `plot_phase_shift_scan()` shows
both quantities versus phase, and `recommend_phase_refinement()` produces a
5-degree follow-up grid around each coarse maximum.

These two objectives must not be confused. Maximising `abs(delta_f)/LW0` finds
the largest pure centre displacement. Maximising the dB reduction at the old
centre also depends on the new linewidth, because feedback can narrow or broaden
the resonance. The external campaign records both and uses the requested dB
reduction as its selection criterion.

The narrow lines in max hold are expected. OUT1's DDS holds one fixed frequency
until software writes the next frequency, so the analyser records a comb of
settled tones. A stored chirp could look continuous, but the resonator would no
longer be measured in steady state and its apparent peak would depend on chirp
rate, ring-down time, RBW, and sweep direction. Quantitative Q and shift results
therefore continue to use the stepped-tone envelope.

## Golden-source guard

`setup`, `test`, and `build` run `tools/verify_golden.py`. It hashes every FPGA
source after removing comments and whitespace, and stops if executable HDL or
constraints differ from the timing-qualified 7 August 2026 source set. Comment
edits are allowed; functional changes require an explicitly qualified successor
design and a deliberately replaced golden manifest.

## Recovery

Rebooting restores the board's configured startup FPGA image. To discard only
generated Vivado output while retaining the downloaded baseline:

```powershell
.\project.ps1 clean
```

If setup reports a checksum mismatch, remove only the named archive in `.cache/`
and run setup again. Never change `upstream.lock` merely to accept an unexpected
download.
