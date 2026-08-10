# Handover — `resonator_coil_characterisation.ipynb`

> Archived experimental record. Use `docs/usage.md` and the notebooks index for
> current commands and paths.

Paste this into a new chat to pick up where the previous one left off.

> **Superseded, 2026-08-06.** The notebook has been renamed to
> `resonator_coil_characterisation.ipynb` and reworked since this was written. What
> changed: every calibration is now measured and adopted at run time rather than typed into the
> configuration cell (Step 4 is reordered to 4a gain ladder, 4b drive window, 4c signal budget,
> 4d L and C, and 4b re-measures the resonance at the drive it adopts); all VNA references are
> gone; Step 3 confirms a candidate by correlating two scans before committing to it, and halves
> `SEARCH_STEP` until one does; Step 8d sweeps each feedback setting on its own span and plots
> two auto-scaled panels. The off-board test tools that this document said were lost in `/tmp`
> now live in `jupyter_notebooks/tests/`. Section 2's measured values below are from the run
> before all of that, and §7's first two actions are now done automatically.


**File:** `notebooks/acquisition/resonator_coil_characterisation.ipynb` (formerly "Test - Coil wo Amplifier", and before that "Test Stage 18")
**Size:** 61 cells (38 code, 23 markdown). Backups `.bak` … `.bak17`, oldest first.
**Board:** Red Pitaya STEMlab 125-14. Bitstream build id `0x096CEAD0`.
**Reference:** Herkenhoff *et al.*, Rev. Sci. Instrum. **92**, 103201 (2021), and the
Herkenhoff BA thesis (MPG PuRe item_3237563).

The notebook is standalone — no imports from other notebooks, stdlib + numpy + matplotlib only.
It runs end to end on the board and against an off-board mock.

---

## 1. Current hardware

```
OUT1 ──[ZFL-500LN+]──[0.3 pF]──┬── node A (top of coil)
        no pad, no terminator   │
                                │
IN1  ─────[short coax ~4 cm]────┴──[0.3 pF]
                                │
                          coil ∥ 39 pF
                                │
                             casing ── SMA shells ── board ground
```

- Both 0.3 pF coupling capacitors solder to the **same** point on the coil; the 39 pF runs from
  that point to the casing. Two short male-to-male SMA cables. **No separate ground strap** —
  the coax shields are the ground.
- Amplifier: **Mini-Circuits ZFL-500LN+** in the **drive** path (0.1–500 MHz, ~28 dB nominal,
  +5 dBm output rating, +15 V / 60 mA). Currently **unterminated and unpadded**.
- Input jumper: **LV** (±1 V).

### Why the amplifier is in the drive path

The drive port is already fed from OUT1's 50 Ω source, so a 50 Ω amplifier costs nothing there.
The pickup port is high impedance (1 MΩ ‖ ~15 pF ≈ 260 Ω at 40 MHz); a 50 Ω input there throws
away 14 dB before any gain arrives.

### Configuration values currently set

```
EXT_GAIN_DB     = 33.7      AMP_IN_MAX_DBM  = -15.0     (open-load derated)
EXT_PAD_DB      = 0.0       AMP_OUT_MAX_DBM =   0.0
DRIVE_FRAC      = 0.0032    G_PASSIVE       = 0.0158
L_COIL = 423.5e-9 ± 11.8n   C_COIL = 1.59e-12 ± 0.06p   C_PARALLEL = 39e-12
VNA_F0 = 39.976e6           VNA_Q  = 181.0
```

---

## 2. Results as they stand

| quantity | value |
|---|---|
| centre frequency | 39.9417 MHz |
| linewidth | 222.09 kHz |
| Q (swept) | 179.8 |
| Q (alternate decimation) | 179.7 (−0.1%) |
| **Q (VNA, independent)** | **181.0 (+0.6%) — CONSISTENT** |
| drift | +17.8 Hz/min, scatter 207 Hz |
| passive round-trip transfer | 0.0158 |
| with ZFL-500LN+ | 0.767–0.78 (measured gain +33.7 dB) |
| K per unit gain | 0.804 measured, 0.774 predicted (4%) |
| self-oscillation onset | A = 1.24 (register limit 1.99) |
| Q reached under feedback | 1434, from 180 |
| detuning range | ±110 kHz = ±0.5 linewidths |
| shift-setting accuracy | 0.007 linewidths rms (34 ppm of f₀) |

**Physics cross-checks that pass:** Q against the VNA (0.6%), Q against an alternate decimation
(0.1%), K against the loop-gain budget (4%), the quarter-turn relationship between the narrowing
and detuning phases, and `Q = Q₀/(1 − K cos φ)` reproducing the measured cuts to within a few
percent at every phase.

**Without the 39 pF** the coil sits near 165 MHz — above the 62.5 MHz Nyquist limit and
invisible to this board. The added capacitance is what makes the measurement possible.

---

## 3. Key findings and fixes (do not re-derive these)

### Things that were broken and are now fixed

1. **Ring-down removed.** The decay is `Q/(π f₀)` ≈ 1.4 µs; the drive is cut by a register write
   from Python with tens of microseconds of jitter. It could never have worked. All references
   purged.
2. **`PhaseShift.LATENCY` was 2, the RTL says 3** (since FIX 6 in `red_pitaya_phaseshift.v`).
   One sample is 8 ns = **115° at 40 MHz**, so the whole phase axis was rotated.
3. **matplotlib `'C0'`–`'C9'` colours do not exist in 1.x**, which is what the board runs. Every
   figure failed to render with `Invalid rgba arg`. All colours are now explicit hex, and there
   is a single `rcParams` block for figure styling.
4. **The phase between sweep points is not a measurement on this board.** `sweep()` retunes two
   numerically-controlled oscillators with two separate register writes; between them
   `Δφ = 2π(f_new − f_old)·Δt` opens up and accumulates, with jitter. It looks like a transport
   delay of tens of microseconds. **Every fit now uses `|z|²` only.** The old
   `width_from_phase()` is gone.
5. **A complex/Fano fitter I added was reporting its own grid edges as measurements** —
   Q = 672 and Q = 2499 were both `hint × e^±1.3125`. Removed entirely once the VNA confirmed
   the plain symmetric fit was right all along.
6. **`peak_frac()` was being used to measure a transfer.** It returns total excursion including
   DC offset and broadband noise, and over-read the tone by 4×, which over-predicted the loop
   gain by the same factor. Added `tone_frac(f)` — a least-squares projection onto cos/sin at the
   known frequency, mean removed. `peak_frac()` remains, correctly, as the clipping guard.
7. **Step 8a's K estimator was a small-K approximation.** `dq/(2Q₀) = K/(1−K²)`, which over-reads
   33% at K = 0.5 and 178% at K = 0.8. Now taken exactly from opposite-phase pairs as
   `(Q₊−Q₋)/(Q₊+Q₋)`.
8. **Damage and compression limits were conflated.** Damage is set by the amplifier's *input*
   power (`DRIVE_MAX = 0.056`), compression by its *output* (`≤ 0.0065`). They differ by the
   gain — a factor of nine.
9. **Absolute drive lists break when the drive changes.** `drive_frac=0.3` was hardcoded in
   Step 1; `DRIVE_FRACS_LIN` and `FB_GAINS` were absolute. All are now fractions of `DRIVE_FRAC`
   or of the usable ceiling.
10. **Step 6's "non-linearity" was the noise floor**, not the coil. Fitting `p = F + cD²` gave a
    floor equal to 92% of the lowest-rung peak. Compounded by DAC quantisation — `set_amp = 2`
    loses 13% of the fundamental. **Lowering the drive made it worse.**

### A dead end, recorded so it is not re-chased

For several rounds I pursued a **coherent-leakage** hypothesis: that a stray drive-to-pickup path
was interfering with the resonance and inflating the fitted width. It produced a Fano fitter, a
leak-correction budget, and a good deal of cabling advice. **The VNA agreeing with the symmetric
fit's Q to 0.6% killed it.** There is an off-resonance floor, but it adds in power, not
coherently, and `fit_lorentzian`'s additive baseline already handles it. Do not re-open this
without new evidence.

### Still open

- **3.8 pF of capacitance unaccounted.** Measured f₀ and known L imply 37.4 pF across the tank;
  coil (1.59) + capacitor (39) + ports (0.6) = 41.2 pF. Stray can only *add*, so the model is too
  big. **Measure the 39 pF part** — a −10% part closes it exactly.
- **Step 6 linearity inconclusive.** Run **Step 4d** (the drive-window scan) and use the
  `DRIVE_FRAC` it recommends rather than nudging.
- **The self-oscillation region is not safely reachable.** See §5.
- **Thesis Fig. 6.3 (a *noise* spectrum) cannot be reproduced.** The coil's Johnson noise arrives
  at 0.21 nV/√Hz against a 4.46 nV/√Hz converter floor — 21× below. Step 8d builds the **driven**
  equivalent, which carries the same information.

---

## 4. Guardrails already in the notebook

**Drive ceiling**
- `Generator.amp()` refuses anything outside `[0, DRIVE_MAX]` rather than masking. Previously
  `frac = -0.5` silently became ×1.5 and `2.0` became silence.
- `DRIVE_MAX` is *derived* from `EXT_GAIN_DB` and `AMP_IN_MAX_DBM`, so declaring an amplifier
  makes an over-drive unrepresentable rather than merely documented.
- `DRIVE_LINEAR_MAX` is separate and derived from `AMP_OUT_MAX_DBM`; exceeding it warns.
- `EXT_PAD_DB` raises both limits.

**Approach, never jump**
- `preflight_drive()` measures at a tenth of the working drive, extrapolates, and refuses if the
  full value would approach full scale. **This is the guard that works even when `EXT_GAIN_DB` is
  wrong or an amplifier is fitted but undeclared.**
- Step 4c's gain ladder climbs in 4 dB steps and stops when the *next* rung would exceed the
  amplifier's output rating. It infers the amplifier's output level from what arrives at the
  input, so it never needs to know the gain.
- Step 4c **aborts** if the measured gain exceeds the declared value — that is the case where
  `DRIVE_MAX` is too permissive.

**Never leave the hardware live**
- `all_off()` (generator, feedback, emulator) registered with `atexit` and called from a
  `finally` in every step that raises the drive. An exception or Ctrl-C cannot leave the coil
  driven with the loop closed.
- `sweep()` zeroes the drive in a `finally`.

**Converter protection**
- Per-point input level guard (`FB_LEVEL_GUARD`, `GUARD_NSAMP` samples).
- Closed-loop headroom cap solving both constraints together:
  `A ≤ (H−D)/(D·r + G·(H−D))` and `A ≤ (1 − D·r/guard)/G`. The old open-loop version
  under-estimated the converter excursion sevenfold at K = 0.8.
- Step 8c detects self-oscillation by switching the drive **off** and reading the input, then
  opens the loop immediately.
- Step 8c refuses to explore past the boundary when an external amplifier makes it unsafe, and
  computes the pad required.

**Measurement integrity**
- Step 0 preflight: build id, register readback, sample rate, status flags.
- Step 1 / 9a emulator self-test against a known answer, before and after the session.
- Step 4d drive-window scan: calibrates the fitter against the emulator to find the smallest
  amplitude at which a fit is trustworthy, then finds the window on the coil between
  noise-limited and compressed.
- Step 5 repeats the width at a different decimation.
- Step 4b compares f₀ against L and C, and against the VNA.
- Fits reject widths more than 50× from the unfed line, and refuse rather than return a grid edge.

**Testing infrastructure (in `/tmp`, not the repo — recreate if needed)**
- A mock register model (`fakehw.py`) that emulates acquisition, generator, phase shifter,
  emulator, scope and DDR, including self-oscillation past unity loop gain.
- A **static audit** that walks cells in order and flags any name used before it exists. This
  caught three ordering bugs that runtime testing missed.
- A **nine-scenario ablation matrix**: `baseline`, `amp_declared`, `amp_drive_high`, `no_coil`,
  `no_L_est`, `no_vna`, `weak_coupling`, `oscillating`, `osc_amp_unsafe`.

---

## 5. The self-oscillation region — why it is not yet reachable

Two constraints pull against each other. An oscillating loop drives the DAC to full scale, and
`gen.amp()`'s ceiling does **not** bound the feedback path, so the amplifier sees
`10 − EXT_PAD_DB` dBm.

```
pad needed for safety          : 25 dB   (currently 0)
net gain needed to reach K = 1 : 30.5 dB (currently 33.7)
amplifier gain satisfying both : 55.5 dB
```

| configuration | net | G | onset A | |
|---|---|---|---|---|
| LN only, no pad, no terminator | +28.1 dB | 0.40 | 2.48 | **unsafe** |
| LN only, 25 dB pad | +3.1 dB | 0.02 | 44 | safe, unreachable |
| **LN + ZFL-750+, 10 dB pad, 50 Ω terminator** | **+32.0 dB** | **0.63** | **1.59** | **safe and reachable** |

**Terminating the output is what unlocks it** — it removes the 20 dB open-load derating, raising
`AMP_IN_MAX_DBM` from −15 to +5 dBm and cutting the pad requirement from 25 dB to 5. The second
amplifier then covers the pad and the terminator's 6 dB with margin.

Once wired: set `AMP_IN_MAX_DBM = 5.0`, `EXT_PAD_DB = 10.0`, `EXT_GAIN_DB = 48.0`.

---

## 6. Proposed plan — guardrails for the real detection system

**Governing principle:** the maximum power that can ever reach the detection system must be set
by a **passive component**, not by software. Every software guard can be defeated by one wrong
config value, a different notebook, or a reloaded bitstream.

### Layer 1 — hardware (cannot be defeated)

| item | protects | purpose |
|---|---|---|
| **Fixed pad at OUT1** | everything downstream | The absolute ceiling. Size against **full-scale DAC** (+10 dBm), not the intended drive — an unstable loop produces full scale |
| DC blocks on both lines | trap electrodes, cryo amplifier gate | The board's ports are DC-coupled |
| 50 Ω terminations per the ZFL datasheets | the amplifiers | Removes the 20 dB open-load derating |
| Attenuator/limiter before IN1 | the board's input | Its absolute maximum at RF is the input range, not the ±30 V DC figure |
| Power-sequencing interlock | the amplifiers | Bias before RF, RF off before bias |
| Separated drive and pickup runs | the measurement | A stray path competes with 0.3 pF |

### Layer 2 — software: model the chain, not one number

Replace the scalar `EXT_GAIN_DB` with a declared chain:

```python
CHAIN = [
    ('OUT1',           dict(max_out_dbm=+10.0)),
    ('pad 20 dB',      dict(gain_db=-20.0, max_in_dbm=+20.0)),
    ('ZFL-500LN+',     dict(gain_db=+28.2, max_in_dbm=+5.0, max_out_dbm=+5.0)),
    ('pad 10 dB',      dict(gain_db=-10.0, max_in_dbm=+20.0)),
    ('cryostat feed',  dict(gain_db=-3.0)),
    ('trap electrode', dict(max_in_dbm=-30.0)),   # decides everything
]
```

- **`audit_chain()`** — walks it at **full-scale DAC**, prints every node level, raises if any
  rating is exceeded.
- **`max_safe_drive()`** — inverts it, so `DRIVE_MAX` comes from the tightest constraint anywhere.
- **`dry_run()`** — the whole audit with no hardware access.
- **`TRAP_CONNECTED`** flag — hard-caps the drive and *disables* Steps 8c/8d/8e's approach to the
  instability boundary. Walking into self-oscillation is a bench experiment, not a trap one.
- **Register-state check at startup** — the phase shifter can hold coefficients from a previous
  session; refuse to proceed if they are not zero.
- **A separate, lower ceiling for "ion present"** — a drive that is electrically harmless can
  still eject the ion.

**Two numbers are needed before this can be written:** the cryogenic amplifier's maximum safe
input, and the electrode's maximum injection level.

### Layer 3 — measurements that replace assumptions

| measure | replaces the assumption that |
|---|---|
| every attenuator's actual value | it matches its marking |
| the full chain's gain at low level, **into a dummy load** | datasheet gains add |
| OUT1's actual full-scale output | it is +10 dBm |
| DC continuity through both blocks | they are intact |
| the cryo amplifier's max safe input | you know it |
| the resonator's Q warm | it resembles the cold value (it won't — cold Q is far higher, so the same gain gives the same K but much larger consequences) |

### Layer 4 — staged commissioning

- **Stage 0 — bench, dummy load.** Chain audit passes; measured gain within 1 dB of declared;
  `all_off()` verified; emulator self-test passes.
- **Stage 1 — warm trap, no ion.** Lowest usable drive, no feedback. Go/no-go: notebook and VNA
  agree on f₀ and Q.
- **Stage 2 — cold trap, no ion.** Repeat cold, then feedback to K ≈ 0.3 only. Go/no-go: K
  proportional to gain, quarter-turn relationship holds.
- **Stage 3 — cold trap with ion.** `TRAP_CONNECTED = True`, ion-present ceiling, no boundary
  exploration.

### What none of this protects against

A cable falling off; the wrong attenuator fitted (hence measuring them); a different notebook
driving the same registers; a bitstream reload changing register semantics — which is what the
`BUILD_ID` check in Step 0 is for. Hardware guardrails are the answer to all four, which is why
Layer 1 comes first.

---

## 7. Suggested next actions

1. Measure the 39 pF capacitor — closes the 3.8 pF discrepancy.
2. Run **Step 4d** and adopt its recommended `DRIVE_FRAC`; stop nudging.
3. Fit the 50 Ω terminator, the 10 dB pad and the ZFL-750+ to make the self-oscillation region
   safe *and* reachable, then update the three config values in §5.
4. Obtain the cryo amplifier's max input and the electrode's max injection, then implement
   Layer 2.
