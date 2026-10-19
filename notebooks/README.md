# Notebooks

Both notebooks are standalone: they import no project file, so they run on the
Red Pitaya after `.\project.ps1 sync` copies them to `/root/jupyter_notebooks`. Each
code cell follows a heading that says what it does, whether it touches hardware, and
whether it is safe to rerun. Every cell that drives OUT1 is commented out until you
uncomment it. **Emergency stop:** `full_shutdown()` (main notebook) or `all_off()`
(high-K notebook); keep a physical way to disconnect OUT1, since a crashed kernel
cannot run either.

## `test_noise_passive_feedback.ipynb` — main trap workflow

Measures the resonator's passive noise spectrum at IN1 with feedback off, then
measures how a chosen feedback gain and phase change its Q and centre frequency.

| Cells | What they do |
|---|---|
| 1–4 | Configuration and limits, imports, shared helpers, review of the first capture plan. No hardware. |
| 5–10 | Register classes for the acquisition system, signal generator, phase shifter and raw scope, plus `capture()` for bounded direct-memory-access records. Definitions only. |
| 11 | Opens the registers, runs `full_shutdown()`, and refuses to continue unless the hardware identifier is `FE76AE09`. |
| 12 | Local-oscillator word, the qualified finite impulse response (FIR) coefficient table and its readback, the cascaded integrator-comb (CIC) plus finite impulse response model, and the bounded spectrum correction. |
| 13–18 | Acquisition-filter check: predict the usable window (14), check fast Fourier transform scaling (15), measure the filter response with OUT1 looped straight to IN1 and the trap disconnected (16–17), then choose model or measured corrections (18). |
| 19–21 | `measure_manual_feedback()`: take one broad feedback-off baseline (20), then repeat only the feedback measurement with its own window, resolution and gain (21). Feedback is always switched off afterwards. |
| 22–23 | `enable_held_feedback()` / `disable_held_feedback()`: hold one setting (at most 1024 counts) for an external measurement such as a spectrum analyser. No timeout. |

Notes:
- `coefficient_counts` sets the digital gain as count / 16384; it is not the loop
  gain K.
- Rewire only after `full_shutdown()`, and take a new baseline after any change to
  pads, amplifiers, cables or electrodes.

## `resonator_coil_manual_high_k.ipynb` — bench-coil diagnostic

Driven-response characterisation of the coil on the bench (OUT1 → 8 dB pad →
ZFL-500LN+ → coil → IN1, with OUT2 to a spectrum analyser). Each step states whether
the cryocooler pump may stay on.

| Step | What it does |
|---|---|
| Configuration, definitions | Seeds, limits and embedded hardware/analysis code; all outputs forced safe. |
| 0 | Known-answer check against the digital resonator. |
| 1 | Input headroom with drive off and at the starting drive. |
| 2 | Fresh resonance and open-loop Q from a bounded, background-subtracted sweep. |
| 3 | Three drive levels; the highest clean linear level is adopted. |
| 4 | Physical OUT2 check: the resonance grid is replayed to the analyser. |
| 5 | Local refinement of the narrowing phase (pump off). |
| 6 | Two gain pairs calibrate K per unit gain for the session (pump off). |
| 7 | Replays manually chosen K values to the analyser (pump off). |
| Final | Emergency shutdown and summary. |
