# Stage 9 — Emulating the real measurement, with noise — PLAN

Written 2026-07-30. This is a plan, not an implementation. Nothing below exists yet
except where marked. Read alongside `HANDOVER.md` and the Stage 8 notebook.

---

## 1. What a "real measurement" actually is, and why Stage 8 didn't do it

Every test so far drove the system with a **clean tone** and asked where and how big it
came out. The real experiment has no tone. The detection coil is driven by its own
**thermal (Johnson) noise** — the random jostling of electrons in its resistance — and
the measurement is the **spectrum of that noise**: a Lorentzian bump at the coil's
resonance. The electron, when present, appears as a narrow *dip* in that bump (it
shorts the coil's noise at its own oscillation frequency). Feedback then reshapes the
bump: narrower, broader, or **moved off the electron's frequency to decouple from it**.

So "emulate a real measurement" means: drive the emulated coil with noise of chosen
strength, measure *spectra* rather than swept amplitudes, and do every Stage 8 task —
phase/gain sweep, peak shifting, active feedback — from those noisy spectra. That
exercises what Stage 8 never touched: long memory captures, spectral averaging, fitting
noisy data, and knowing how measurement precision depends on signal-to-noise ratio
(SNR) and integration time.

---

## 2. Digital or real coil? — DIGITAL, for three reasons

| | Digital resonator + digital noise | Real coil |
|---|---|---|
| Known answer? | **Yes** — f0, Q, noise level all set exactly; every result checkable | No — f0, Q, noise temperature are the unknowns being measured |
| Configurable SNR? | **Yes** — two registers, −20 dB to +60 dB | No — Johnson noise is set by temperature; SNR changes need attenuators and soldering |
| Separates instrument faults from physics? | **Yes** — the discipline that caught every bug so far | No — a wrong Q could be the coil or the code |

The real coil is not skipped — it is the step *after*: disable the resonator (one
register write), connect the coil, and run the **same notebook**. Its calibrations
(narrowing phase, latency budget) are exactly what the real run needs first anyway.

---

## 3. Where the noise comes from (the one hardware addition)

Noise must enter **where Johnson noise physically arises: at the resonator's input**,
so the resonator filters it into the correct Lorentzian bump by itself. Options
considered:

- **Replay noise from the signal generator's table** — rejected. The table repeats
  every 131 µs, so its "noise" is really 16384 spectral lines 7.6 kHz apart:
  periodic, correlated, and wrong inside our 122 kHz analysis band.
- **A pseudo-random generator inside the resonator module** — chosen. A handful of
  linear-feedback shift registers (LFSRs — small circuits that step through a
  pseudo-random sequence with an astronomically long period) summed together; the sum
  of several uniform random values is close to Gaussian (the central-limit theorem),
  which is what thermal noise is. One new amplitude register scales it, and the scaled
  noise is added to the resonator's input.

**Design constraints already identified:**
- The addition lands in the resonator's input path, which — unlike its recursive core —
  **can be safely pipelined**: register the (input + noise) sum one clock before it
  enters the recursion, so the critical multiply-add path is untouched. Timing report
  must confirm, as always.
- New registers go on the resonator's own bus slot (spare offsets from 0x20) — no new
  bus slot, no new module, minimal surface area.
- **Needs one rebuild.** Bundle with anything else pending so it stays one rebuild.

**SNR is then a calibration, not a guess:** measure noise power in the band with the
tone off, tone power with the noise off, and set the two amplitudes for the target
ratio. Step 0 of the notebook does this and prints the dial.

---

## 4. The Stage 9 notebook, step by step

**Step 0 — Presence, calibration of the SNR dial.** Probe the noise register exists
(refuse to run on an old bitstream, as Stage 8 does). Measure noise floor vs the
amplitude register (must be linear), and the tone scale (known from Stage 7's ×65536).
Result: "SNR = X dB" means something exact from here on.

**Step 1 — The measurement itself: a noise spectrum.** No tone at all. Noise on,
capture long records to memory (this is Stage 6's transport doing its real job for the
first time), average many spectra (Welch averaging: split the record, transform each
segment with a fast Fourier transform (FFT), average the powers — trades resolution for
steadiness), fit the Lorentzian bump. **Pass:** recovered f0 and Q match the known
answer; bump height matches the calibrated noise level.

**Step 2 — Phase and gain sweep, measured from noise.** Repeat Stage 8's sweeps, but
each point is now a fitted noise spectrum instead of a driven amplitude — exactly how
the real experiment does it. Run at three SNRs (e.g. +20 dB, 0 dB, −10 dB) and report
how the precision of K and the narrowing phase degrades — the first quantitative answer
to "how much averaging will the real coil need?"

**Step 3 — Decoupling: move the peak off the electron.** Mark an "electron frequency"
f_e (a designated line near f0 — no electron emulation needed to test the *shift*).
Apply the quarter-phase feedback from Stage 8; verify the bump's centre moves by the
predicted amount and measure how much noise power remains at f_e versus shift — the
decoupling curve. **Pass:** power at f_e falls as the Lorentzian predicts.

**Step 4 — Active feedback under noise.** Close the loop at the narrowing phase with
noise running: verify Q_eff still follows Q0/(1−K), that the loop stays stable below
the Stage 8 threshold with noise present, and that the clip flag stays clear (noise
peaks are larger than sine peaks of the same power — headroom check matters here).

**Step 5 — The latency budget and the control interval.** See section 5.

**Summary — what transfers to the real coil unchanged.**

*Optional extension (decision needed):* a true **electron emulation** — a second, very
high-Q digital resonator coupled to the first, producing the real observable (the dip).
More hardware work (a second instance plus coupling arithmetic, timing to re-check);
not needed for anything above, but it would let the full detection analysis be
rehearsed on a known answer. Could be Stage 10.

---

## 5. Latency: what gets measured, and how

Two different clocks matter and must not be confused: **hardware latency** (nanoseconds
to milliseconds, fixed by the chip) and the **control interval** (how often software
can measure → decide → act, milliseconds and up, dominated by Python and by physics).

| Stage | Predicted | How it will be measured |
|---|---|---|
| Resonator input register + recursion | 2 clocks (16 ns) | design inspection (fixed) |
| Emulated converter/cable delay | 15 clocks (120 ns), set by register | already exact by construction |
| Phase shifter | 2 samples (16 ns) | its header (measured previously) |
| DAC summation | ~2 clocks | design inspection |
| **Feedback loop total** | **~150 ns emulated (vs 119.87 ns real)** | **narrowing-phase-vs-frequency method:** repeat the phase sweep at several resonator frequencies; transport delay makes the narrowing phase advance linearly with frequency, and the slope IS the loop latency. Uses only Stage 8 machinery, no new hardware |
| Mixer | ~3 clocks | design inspection |
| Decimator | ~R clocks (8 µs at R=1024) | step-response, see below |
| Correction filter | ~half the taps at the output rate (~2 ms at R=1024) | step-response, see below |
| **Acquisition chain total** | **~2 ms at R=1024** | **two-decimation step method:** switch the tone on, find the step edge in a captured record, at two different R values; fitting latency = a + b·R separates the fixed part from the part that scales with averaging |
| Memory writer | ≤ 16-sample burst buffer (~130 µs at R=1024) | bounded by design; visible in the step method |
| Python: one register read | ~0.1–1 ms | `time.time()` around it |
| Python: capture + FFT + fit | ~10–100 ms | timed in Step 5 |
| **Control interval** | **~30–300 ms, software-dominated** | a toy closed loop — measure, fit, write the phase — timed over many cycles with the breakdown printed |

One physics point the notebook will make explicit: the control interval has a floor no
software can beat. Frequency resolution is 1/(observation time), so *seeing* a feature
of width Δf takes at least 1/Δf of data — about 4.5 µs for the open-loop line here, but
proportionally longer for narrowed lines and for precision much finer than the width.
The budget table says which part is physics, which is silicon, and which is Python —
so nobody later optimises the wrong one.

---

## 6. Order of work once approved

1. RTL: noise generator inside `red_pitaya_resonator.v` (new registers ≥0x20, input
   pipelined), `verify_rtl.py`, documentation in header + CHANGELOG.
2. **One rebuild**, fingerprint check, timing report check (resonator path + noise).
3. Stage 9 notebook, written and verified like Stage 8 (every cell explained,
   compile-checked, PASS/FAIL gates against known answers).
4. Run on hardware; record results in CHANGELOG; update HANDOVER.
5. Then: the real coil, same notebook, resonator off.
