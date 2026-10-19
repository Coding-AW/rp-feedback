# Notebooks

Both notebooks run on the Red Pitaya itself. They import nothing from this repository, so
`.\project.ps1 sync` simply copies them to `/root/jupyter_notebooks` on the board. Every code
cell sits under a heading that says what it does, whether it drives the hardware, and whether it
is safe to run again. Any cell that can drive OUT1 is commented out: uncomment only the call you
mean to run.

**Emergency stop:** `full_shutdown()` in the main notebook, `all_off()` in the high-K notebook.
Neither can run if the kernel has crashed, so keep a physical way to disconnect OUT1.

## `test_noise_passive_feedback.ipynb` — the trap measurement

Records the resonator's natural noise spectrum with feedback off (the baseline), then records it
again with a chosen feedback gain and phase, and fits both to find Q and the centre frequency.

| Cells | What happens |
|---|---|
| 1–4 | Settings and limits, imports, shared helpers, and a plan for the first capture. No hardware. |
| 5–10 | Definitions for reaching the board: the acquisition system, signal generator, phase shifter and raw oscilloscope, plus `capture()`, which records into a fixed region of board memory. |
| 11 | Opens the registers, switches everything off, and stops unless the board reports the qualified identifier `FE76AE09`. |
| 12 | Tools for turning captures into corrected spectra, including the qualified filter coefficients and a model of the filters' response. |
| 13–18 | Filter check. Predict the filters' response (14) and check the spectrum scaling (15) with no hardware; measure the response with OUT1 looped straight back to IN1 and the trap disconnected (16–17); then choose the model or the measured correction (18). |
| 19–21 | `measure_manual_feedback()`. Take one broad baseline with feedback off (20), then repeat the feedback measurement with its own window, resolution and gain as often as needed (21). Feedback is always switched off afterwards. |
| 22–23 | `enable_held_feedback()` and `disable_held_feedback()`: hold one setting, at most 1024 counts, while an external instrument such as a spectrum analyser measures. There is no timeout. |

Two points that are easy to get wrong:
- `coefficient_counts` sets the digital gain as count ÷ 16384. That is not the loop gain K,
  which also depends on the analogue path.
- Rewire only after `full_shutdown()`, and take a new baseline after any change to attenuators,
  amplifiers, cables or electrodes.

## `resonator_coil_manual_high_k.ipynb` — the bench coil

Characterises the coil on the bench by driving it with a stepped tone and measuring the response
(OUT1 → 8 dB attenuator → ZFL-500LN+ amplifier → coil → IN1, with OUT2 to a spectrum analyser).
Each step's banner says whether the cryocooler pump may stay on.

| Step | What happens |
|---|---|
| Setup | Settings, register access and analysis code; every output starts off. |
| 0 | Checks the measurement chain against the on-chip digital resonator, whose Q is known. |
| 1 | Checks the input level with the drive off and on. |
| 2 | Finds the resonance and measures its open-loop Q. |
| 3 | Tries three drive levels and keeps the highest that is still clean and linear. |
| 4 | Confirms that OUT2 shows the whole resonance on the analyser; feedback stays locked until you do. |
| 5 | Finds the feedback phase that narrows the resonance most (pump off). |
| 6 | Calibrates loop gain K per unit of digital gain at two gains (pump off). |
| 7 | Replays loop-gain values K that you choose, for the analyser to record (pump off). |
| Final | Switches everything off and prints a summary. |
