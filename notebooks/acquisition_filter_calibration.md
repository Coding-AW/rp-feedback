# Acquisition-filter workflow — code cells 13–18

Follow **predict → check FFT → measure filters → choose correction → measure the resonator**.
The test calls are commented out: rerunning definitions does not start measurements.

The measurement path is IN1 → mixer → four-stage CIC → optional FIR → FFT.
Software divides averaged spectral power by the selected CIC × FIR power response
before fitting Q and frequency. This does not change the separate OUT1 feedback path.
A model is not a measured calibration. Neither can recover filter nulls, aliases,
clipping or lost signal-to-noise.

---

## 13 — Load the filter-test functions

Run this definition after acquisition helpers (cell 12). It creates the model, FFT check and live
calibration functions. It does not touch hardware; no wiring change or plots are
expected. It is safe to rerun. Missing names mean the imports or acquisition-helper
definitions need to run first.

---

## 14 — Predict the usable window

Uncomment the model calls below; no board is needed and they are safe to repeat.
Compare exponent 6 (broad baseline) with exponent 8 (narrow feedback).
Plots separate CIC sag, FIR compensation, their product and first-image alias leakage.

At exponent 6 or 7 the FIR is automatically bypassed; at 8–12 it is enabled.
The qualified FIR's designed flat full span is approximately
`0.4 × output sample rate`, about 195 kHz at exponent 8, not the full FFT span.
Choose a window away from the steep cutoff.
Changing `passband_fraction` changes the inspected window, not the FIR taps.
Printed ripple is a prediction, not a hardware pass certificate.

---

## 15 — Check FFT normalization without hardware

The synthetic check below needs no wiring. It compares integrated raw PSD with
the same demeaned, Hann-weighted time-record power.
Pass means their fractional difference is below numerical tolerance.
It is safe to rerun; failure is a software/scaling issue, not a trap issue.

Integrate PSD using FFT bin width. Hann equivalent noise bandwidth (ENBW)
describes the resolution filter; do not multiply every PSD bin by ENBW.
Do not submit a corrected or cropped spectrum to this check.

This does not calibrate ADC volts/count. The notebook uses a complex-envelope
convention: a sinusoid's envelope mean-square is twice its real RF mean-square.
The live test checks that factor separately. dB relative to 1 V²/Hz is not dBm.

---

## Before cell 16 — Connect the Red Pitaya loopback

**Hardware change required. Never inject the calibration tone into the trap.**

1. Run `full_shutdown()`. Disconnect the trap/electrode return cable at OUT1
   and isolate it. OUT2 stays disconnected/off. Close other Red Pitaya apps.
2. Disconnect the detection chain from IN1. Follow its power/load requirements;
   never leave an amplifier open if its operating instructions prohibit that.
3. Connect **OUT1 → short coax → IN1**, preferably with a 50 Ω feedthrough
   directly at IN1. A small rated pad is optional; the normal large feedback
   attenuation is not required for this isolated low-level electronics test.
4. No amplifier, trap, resonator, splitter or external source belongs in this loop.
   A native high-impedance IN1 connection is supported for relative testing, but
   matching is less predictable. Treat open-load voltage as potentially twice
   the nominal loaded voltage. Never connect two outputs together.
5. Leave generator control to the test cell. It starts at half of the selected
   low drive and then reaches that drive, with raw-input checks at each level.

There is no new physical feedback loop: phase-shifter coefficients stay zero;
only generator A makes the sine. The call is the command to enable OUT1, without
an extra dialog. Software cannot prove the trap was disconnected.
On a kernel hang, disconnect the loopback and power down the board before rewiring.

---

## 16 — Measure the broad-setting response

Uncomment the loopback scan you need. It starts and ends with Red Pitaya outputs off.
Rerunning definitions or model checks does not erase earlier scan results.
Generator A makes a fixed approximately 40 MHz tone (default 40.9 MHz, or choose
`tone_hz=40e6`). Only the acquisition LO moves the tone through the band.
Randomized offsets and paired bypass/auto captures separate CIC loss from FIR
compensation. Raw ADC checks monitor overload and input drift.

Before scanning, generator-off noise, two-level power proportionality, sine
purity and input peak/DC are checked. Actual quantized generator frequency is
used. Table, amplitude/DC, tuning and channel-B readback are checked.
`drive_fraction=.02` is 2% of digital full scale, not 20 mV measured at IN1.
The test refuses above 5% or the existing lower drive/operating limit.

The broad scan covers ±0.30 of output rate; cell 17 covers ±0.20.
Expect measured/model curves, residuals, repeat scatter and an acceptance record.
Defaults require tone SNR ≥20 dB, power scatter ≤3%, model error ≤0.30 dB and
enabled-FIR ripple ≤0.15 dB. A bypassed CIC need not be flat.
FFT and RF/envelope scaling, register state and FIR readback are checked too.

If rejected, inspect the reasons: poor SNR, compression, source drift, incorrect
coefficients or a too-wide passband can fail. Never force acceptance.
Hardware exceptions attempt shutdown and preserve partial rows in
`LAST_FILTER_CALIBRATION`. Review failures before repeating with safe test wiring.

---

## 18 — Choose the correction before manual measurements

Run `full_shutdown()`, remove the loopback cable, and restore the commissioned
passive detection and feedback wiring. If using the optional external source,
switch it off yourself. Never start trap measurements with either test source connected.

The selection cell starts with explicitly labelled model correction.
To use measured responses, uncomment its two assignments after those scans pass.
The broad baseline and narrow feedback measurement have separate corrections.

Measured records must match decimation, FIR state, clock and coefficient fingerprint;
there is no extrapolation beyond measured LO-relative offsets.
The manual function checks these before enabling feedback. For a new setting,
measure that setting or deliberately choose the labelled model.

This calibrates relative digital response, not absolute electrode voltage or the
whole analogue chain. Repeat at another RF tone for large centre-frequency changes.
After changing a correction or physical setup, reacquire the baseline once.
Subsequent feedback-window changes do not refit the saved baseline.

---

## Reference — What can be configured?

| Setting | Effect and limit |
|---|---|
| LO | Moves the RF measurement window, not OUT1 phase. |
| CIC exponent 6–12 | Changes sample rate, null spacing and latency. Four stages and differential delay one stay fixed. |
| FIR auto/bypass | Auto bypasses at exponents 6–7; enabled FIR compensates only its central band. |
| FIR coefficients | Read back and checked, never rewritten by this workflow. |
| FFT samples | More samples give finer bins and longer records, not a wider passband. |
| Averages | Reduce random scatter, not systematic roll-off or drift. |
| Software correction | Measured or model response; cannot recover nulls or aliases. |

Reconfiguration stops/resets acquisition and allows filter history to settle.
None of these settings changes the physical feedback phase/gain.

---

## Limits — What this self-test does not prove

OUT1, the mixer and ADC share the same clock. A good relative CIC/FIR result
does not independently calibrate clock accuracy, absolute ADC/DAC voltage,
RF bandwidth or the electrode path. This is a fixed-RF, amplitude-response test,
not an independently measured phase/group-delay calibration. Source harmonics
and coherent crosstalk can bias it; raw sine purity and measured/model residuals
help detect problems but cannot rule out every correlated error.

For optional cross-checking, set `source='external'`: disconnect OUT1 and connect
a separate stable, safely attenuated source directly to IN1. Keep its RF frequency
and amplitude fixed. The notebook does not control or turn off an external source.
No external generator is required for the normal loopback workflow.

---

## Optional — Absolute voltage and alias checks

For ADC scaling, independently measure at least three small input RMS levels
under the actual termination, then pass voltage/count pairs to `calibrate_adc_scale`.
It reports a candidate factor and scatter; it changes neither EEPROM nor notebook
scaling. Repeated increasing/decreasing levels help identify compression.

For alias rejection, keep the disconnected electronics wiring and a fixed LO.
Compare equal independently measured source levels at the wanted frequency and at
that frequency ± one output sample rate. Inspect the folded tone and repeat relevant
image bands. A below-floor result is a bound, not proof of zero aliasing.
The model plots only first images; a post-CIC FIR cannot undo already folded aliases.

Background: [CIC compensation](https://www.mathworks.com/help/dsp/ref/dsp.ciccompensationdecimator-system-object.html)
and [PSD normalization](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.periodogram.html).

Hardware reference: [official STEMlab 125-14 specifications](https://redpitaya.readthedocs.io/en/latest/developerGuide/hardware/ORIG_GEN/125-14/top.html)
specify a ±1 V LV input range, high input impedance and 50 Ω output load.
Absolute damage limits are not operating targets; this workflow keeps the existing
lower notebook guards and makes no EEPROM, RTL or FIR-coefficient changes.
