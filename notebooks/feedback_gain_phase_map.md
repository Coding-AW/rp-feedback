# Gain–phase campaign — code cells 22–26

This section maps how feedback changes Q and resonant frequency. It does not
assume that 225° is regenerative: the coarse sweep samples it deliberately and
fits the physical axes from all accepted points.

The map reuses the one-point measurement’s fitted spectra, CIC/FIR correction,
raw-input checks, exact coefficient readback and shutdown. OUT2 remains off.
Only the compact CSV fit table and campaign manifest are retained. Per-point
spectra, fitted curves and raw time records are discarded.

---

## 22 — Load the resumable map functions

Run the definition cell once. It defines the campaign, plotting and target-selection
interfaces without accessing hardware or creating files. It is safe to rerun.

The private helpers load saved summaries and calculate phase axes, repeatability
and leave-one-out interpolation checks. They are kept in this cell so the notebook
remains standalone.

---

## 23 — Configure the campaign

Run the configuration cell and edit the campaign name before a new physical setup.
The hard maximum is 1024 counts and the uncertainty-aware stop is K=0.85.
The default first active rung is 128 counts because lower commands were not
measurable in the present setup. Change `minimum_coefficient_counts` only after
the physical loop changes.
The configuration describes software measurement choices, not unknown electrode
voltage or analogue gain.

`baseline_frequency_range_hz` and `locator_frequency_range_hz` are explicit
absolute bounds. The active window is centred on the predicted resonance and
bounded by `feedback_minimum_span_hz`, `feedback_maximum_span_hz`, and
`feedback_linewidths_full_span`. Coarse broadened resonances may use 0.35
linewidth of clean data at the nearer edge; centre, resolution, uncertainty,
spur and hardware checks remain active.

The printed estimate is repeated before hardware starts. Existing campaign
directories are never overwritten. Use a new name after changing attenuation,
amplification, cabling, filter correction or trap conditions.

---

## 24 — Run or resume the coarse diagnostic map

Before uncommenting the call, restore the passive trap wiring, remove the OUT1–IN1
filter-calibration loopback, and verify the external physical stop for OUT1.
Run the broad manual baseline successfully first if you want a visual check.

The coarse sweep starts at low counts, advances in ascending rungs, measures
opposite phases closely in time and brackets every rung with feedback-off baselines.
It uses full phase circles at selected gains and extra points around 225°.

Every point returns to full shutdown before fitting and is written atomically.
Any K limit, carrier, broadband, fit, repeatability or recovery failure stops the
whole campaign with partial data preserved. A stopped campaign never resumes by
itself. Use `resume=True` only after investigating the printed reason.

---

## 25 — Run the final map and produce the figure

Only run this after reviewing the coarse axes and accepted points. The final grid
chooses about nine gain rungs distributed through measured K, uses 15° phase steps,
and repeats ten percent of points. Each active spectrum is centred and resolved
from the nearest accepted coarse result.

The plotting call creates PNG and PDF output beside the campaign data. Its upper
panels are Q/Q0 and frequency-shift heatmaps; lower panels show measured phase
cuts at representative gains. Rejected and extrapolated areas stay black.
Contours show K=0.5, 0.7 and 0.85, and the orange vertical line marks the original
225° expectation. Interpolation uses actual quantized CI/CQ coordinates.

---

## 26 — Select a future operating point

Call `select_feedback_operating_point` with a Q target, frequency target, or both.
It searches only inside the accepted triangulated map and returns several candidates.
It never applies feedback. If Q alone is supplied it favours low residual shift;
if shift alone is supplied it favours little Q change.

Each candidate reports the predicted Q/frequency, quantized count and phase,
distance to measured data, and the requirement for a fresh manual validation.
Do not treat interpolation as permission to approach K=1. If no accepted local
solution exists, take additional measurements rather than enabling extrapolation.
