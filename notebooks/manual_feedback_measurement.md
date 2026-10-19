---
# Manual measurements — code cells 19–21

## What changes

Measure the broad feedback-off resonance **once**, retaining its spectrum and fit
in `manual_baseline`. Then rerun only the feedback call, using a different window,
decimation, FFT length and Q estimate. That call acquires **only the feedback
spectrum** and switches feedback off afterward. It never recaptures or refits the
saved baseline. No JSON, checkpoint, or campaign calibration is needed.

The plots show a broad overview, a zoom of the enhanced measurement window, and
fit residuals. Each spectrum/model keeps its native frequency grid. A narrow
window cannot change the baseline fit or pretend to improve its resolution.
Changing the acquisition LO also leaves the inherited feedback phase reference
unchanged unless you explicitly override `phase_reference_hz`.

An additional figure shows the same averaged spectra and Lorentzian models in
**dB relative to 1 V²/Hz**, with a full overview and (for feedback mode) an
enhanced-window zoom. It uses `10*log10(PSD / (1 V²/Hz))`: for example,
`1e-12 V²/Hz` is `-120 dB`. Negative dB values are normal and do not mean negative
voltage or negative power. The logarithm is applied after averaging linear powers;
fits still use the original data. Zero/non-finite bins appear as gaps.

This is not dBm: native high-impedance IN1 does not measure power delivered into
a known 50-ohm load. There is no new hardware action, recapture or refit for this
additional plot. The baseline and enhanced measurement retain their own grids.

## Preparation and hardware

Run the standard configuration, imports/library, hardware interface, identity and
shutdown cells, then **cell 12's acquisition helpers and cells 13–18's filter workflow**,
including its explicit correction selection, followed by the definition below.
No saved calibration file is needed. Physical commissioning is still necessary:
software cannot establish unknown amplifier/electrode damage limits.

Use the already commissioned detection and return paths. Both generators and
OUT2 stay off. Before changing pads, amplifiers, filters, cables or electrodes,
shut down and follow the hardware's power/connector sequence. **Acquire a new
baseline after a physical setup change**, and start at a conservative gain again.
The function cannot detect such changes automatically.

Defining the function does nothing to hardware. Each call immediately runs the
requested measurement, without another confirmation dialog. Every call attempts
full shutdown on completion, error and Ctrl-C. Keep a physical means to interrupt
the return path: a crashed kernel cannot run shutdown, and the software deadline
is checked between captures, not by an independent watchdog.

## A — Measure the broad baseline once

Run this in its **own cell** after the function definition:

```python
manual_baseline = measure_manual_feedback(
    mode='baseline',                       # No gain is applied.
    frequency_range_hz=(40.4e6, 41.4e6),
    fit_range_hz=(40.5e6, 41.3e6),
    decimation_log2=6, samples_per_record=8192,
    fir_mode='auto', response_calibration=BASELINE_RESPONSE,
    averages=32, repeats=1,
    q_guess=150.0, q_bounds=(20.0, 1e6),
    phase_reference_hz=40.9e6,
    label='current setup — broad off baseline'
)
```

**Expected result:** one averaged off spectrum, an accepted Lorentzian fit with
Q, centre and linewidth, and verified shutdown. Review residuals before accepting
the physical interpretation. Increase averaging for weak random noise; widen the
fit window if the shoulders are missing. A failed baseline cannot be reused.
Rerunning this cell deliberately replaces the baseline.

## B — Adjust and repeat only the enhanced measurement

Run this in a **different cell**. The values below are examples, not a guarantee
that count 32 is safe or that Q=2000 will result. Start at your commissioned low
gain. If the enhanced width/centre is unknown, start with a broad window, then
narrow it once located.

```python
measurement = measure_manual_feedback(
    mode='feedback', baseline_measurement=manual_baseline,
    coefficient_counts=32, phase_deg=0.0,
    frequency_range_hz=(40.81e6, 40.99e6),
    fit_range_hz=(40.82e6, 40.98e6),
    decimation_log2=8, samples_per_record=8192,
    fir_mode='auto', response_calibration=FEEDBACK_RESPONSE,
    averages=32, repeats=1,
    q_guess=2000.0, q_bounds=(20.0, 1e6),
    label='manual Q-enhanced measurement'
)
```

Each call changes only the new measurement. Each repeat averages independent FFT
**powers**, not signed waveforms that would cancel random noise. Raw time records
are discarded as they are processed. The latest/partial result is also retained
in `LAST_MANUAL_FEEDBACK_MEASUREMENT`. No files are loaded or saved; a kernel
restart loses these in-memory results.

## Choosing windows, resolution and gain

| Setting | Purpose |
|---|---|
| `frequency_range_hz` | New acquisition/display window, independent of the baseline. Move it to follow frequency shifts. |
| `fit_range_hz` | Fit only this subset to exclude other resonances. Keep at least one linewidth on each side of the centre. |
| `decimation_log2` | Sample rate is `FS_CLK / 2**decimation_log2`. Larger values narrow the available band and improve resolution. |
| `samples_per_record` | Power-of-two FFT length, 256–65,536. Bin spacing = sample rate / length; at least 20 bins per linewidth are required. |
| `averages`, `repeats` | Spectra per measurement and repetitions of that state. Averaging reduces random noise, not drift. |
| `q_guess`, `q_bounds` | Fit starting estimate and search limits, not a forced Q. |
| `coefficient_counts` **or** `gain` | Choose one. Digital `gain=count/16384` is not physical loop K. Negative gain adds 180 degrees. |
| `phase_deg` | Commanded feedback phase; electrode phase is not independently measured. |
| `lo_hz` | Acquisition LO, separate from the inherited feedback phase reference. |

The printed bin width and Hann-window equivalent noise bandwidth (ENBW) describe
resolution. PSDs are normalised in V²/Hz at the notebook ADC scale and corrected
using its CIC/FIR model, or an optional **in-memory** `response_calibration`.
Narrow peaks can have different apparent heights at different ENBWs; compare
resolved fits, not peak height alone.

Mean removal for the FFT causes a small notch at the LO. The fit excludes that
bin and its neighbours. No DC is subtracted from hardware feedback. A real
electron dip, multiple resonances or self-oscillation cannot be interpreted
reliably by this single Lorentzian plus smooth-background model.

## Checks retained and the baseline-reuse trade-off

Before each feedback repeat, a short raw-ADC off **safety capture** checks current
DC, peak and RMS. It is not a resonance spectrum or a baseline fit. During
acquisition the function checks headroom, readback, generator state, time limits,
large full-band power growth and narrow-carrier evidence.

`max_input_vpk` and `max_output_vpk` may reduce, never raise, notebook operating
guards. `max_power_ratio` compares current raw-ADC power with the fresh short off
capture, not with an old differently decimated spectrum. `max_active_seconds`
bounds each acquisition loop but is not a hardware watchdog.

**A reused baseline does not measure present drift or post-feedback recovery.**
Its age is printed. Zero coefficients prove feedback is off, not that Q/frequency
recovered. Reacquire deliberately after setup changes, suspected heating, or
unexplained drift. There is no automatic age cutoff: the operator must decide
whether the saved baseline remains representative.

`measurement['comparison']` reports Q ratio, shift and effective damping
`1 - linewidth_on / linewidth_baseline` for accepted fits. Fit uncertainties
**exclude unmeasured drift**. This is not an independently calibrated loop K or
permission to approach self-oscillation. `recovery_measured=False` records this
limitation explicitly.

**Pass:** resolved peak, adequate shoulders/resolution, acceptable uncertainty,
and no live-guard failure. `status='complete'` does not certify historical
baseline stability. Failed fits are plotted as unreliable and stop further
repeats; hardware failures raise an error and attempt shutdown.

Optional `mode='bracketed'` retains the old same-window off/on/off measurement
when a recovery check is wanted. It is not needed for this independent-window
workflow.

**Stop:** call `full_shutdown()`. If shutdown cannot be verified, physically
interrupt OUT1 before troubleshooting. Review failures before rerunning; do not
loosen guards to hide instability. The companion Python file is for copying the
definition into an existing notebook, **not** for importing.

Manual calls accept `fir_mode='auto'` or `'bypass'`. Cells 13–18 explain electronics-only
calibration and real passband limits. The code reads the installed FIR coefficients
and models their product with CIC instead of assuming a flat FIR. Existing PSD/dB
units follow the complex-envelope convention detailed in cell 15. Choosing bypass
changes measurement filtering only; it does not bypass or modify OUT1 feedback.

After upgrading from the earlier assumed-flat-FIR implementation, acquire the
broad baseline once again. Old result dictionaries are rejected to avoid mixing
different correction conventions; the new baseline can then be reused normally.
