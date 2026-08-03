# Stage 11 design: the parameter sequencer

A design document, not an implementation. Written 2026-07-31, to be reviewed before any
Verilog is touched. Based on section III.B of Herkenhoff *et al.*, Rev. Sci. Instrum.
**92**, 103201 (2021), and on this project's measured numbers.

---

## Why it is needed, with the measurement that proves it

The paper's precision technique (their Fig. 11) is a *timed sequence*: detune the
resonator to decouple the ion → fire an excitation pulse that imprints a starting
phase → let the ion evolve freely for an exact duration → re-couple → read the phase.
The steps need microsecond-accurate, jitter-free timing.

Stage 9 Step 5 measured what software can do on this system: a **45 ms** control
interval, dominated by sensing and settling — five orders of magnitude too slow, with
jitter to match. The fabric clock is 8 ns. Timed feedback-state switching therefore
belongs in the fabric, and that is all the sequencer is: **a small state machine that
rewrites the phase shifter's two coefficients (and a few friends) at exact times or on
a trigger edge.**

## What the paper's sequencer does (the requirements)

| Paper feature | Requirement here |
|---|---|
| 8 software-configurable parameter sets | 8 × {phase-shifter ci, cq} minimum; add per-set flags (below) |
| Step on a programmed time delay | 32-bit down-counter at 125 MHz → 8 ns resolution, 34 s max per step |
| Step on external trigger edge (rising/falling) | One digital input pin, synchroniser, programmable edge |
| Trigger jitter elimination via 10 MHz reference | Out of scope for now: no reference-clock input is wired on this build. Accept ±1 clock (8 ns) jitter; note it as a known limit |
| Sequencer controls the feedback input source mux | Add per-set flag bits instead (simpler, same effect) |

Per-set contents (one 128-bit record, or four 32-bit registers per set):

- `CI`, `CQ` — the phase shifter coefficients for this step (Q2.14, as now)
- `DURATION` — clocks to hold, 0 = wait for trigger
- `FLAGS` — [0] fire ASG burst at step entry (the excitation pulse — the stock
  generator already has burst mode, `set_a_ncyc`, unused so far); [1] arm the
  acquisition at step entry (phase-coherent capture start); [2] end of sequence:
  hold final set / loop

## Where it lives

A new module `red_pitaya_sequencer.v` on the spare bus slot `sys[7]` (0x40700000),
which is currently a stub. It *drives* the phase shifter's coefficient inputs through
a two-input mux: software register values (as now — power-on default) or sequencer
values. One mux, two 16-bit signals, no timing risk: coefficients are quasi-static
control values, not datapath.

Register sketch (all RW unless stated):

```
0x00  CTRL      [0] arm  [1] soft abort  [2] source: 0 = software coeffs (default)
0x04  STATUS    RO: [3:0] current set, [4] running, [5] done, [6] trigger seen
0x08  TRIG_CFG  [0] edge select, [1] enable external trigger
0x10..0x8C      8 sets x {CI, CQ, DURATION, FLAGS}
```

## What it must NOT touch

- The feedback datapath itself: the phase shifter's arithmetic is unchanged; only the
  *source* of its two coefficient registers gains a mux.
- The acquisition system, other than an `arm` pulse wire (same signal software writes).
- Anything on the guarded ADC → phase-shifter path.
- Power-on behaviour: source defaults to software, sequencer idle — the board is
  bit-for-bit as before until armed. Same discipline as the resonator and the noise.

## Verification plan (Test Stage 11, against the emulated coil)

1. **Timing truth.** Program a two-set sequence (decouple / recouple) with a known
   duration; capture to memory across the transition; the switch must land at the
   programmed sample index ± 1 sample. The memory-writer-as-stopwatch method from
   Stage 9 Step 5, reused.
2. **The paper's Fig. 11, emulated.** Decouple (shift feedback) → ASG burst at the
   "electron" frequency (FLAGS[0]) → free evolution for t_evol → recouple → coherent
   capture (FLAGS[1]). Repeat N times: the read-back phase must advance by
   360°·f·t_evol per programmed step of t_evol, and its scatter is the phase-readout
   precision — the emulated version of the paper's phase-sensitive frequency
   measurement.
3. **Trigger path.** Drive the trigger from a GPIO loop-back; verify edge selection,
   and measure jitter (expect ±1 clock).
4. **Regression.** Stages 1–10 re-run unchanged with the sequencer idle: nothing may
   move.

## Cost estimate

Small: a handful of registers, one counter, one 4-bit state pointer, two muxes. No
DSP, no memory beyond the 32 registers, no new clock domains, nothing recursive. The
build risk is the usual one — a rebuild — not the logic.

## Open questions for review before implementation

1. Which physical pin for the external trigger (the daisy-chain SATA pins are free
   since that module was removed; expansion-header DIO is the alternative)?
2. Is 8 sets enough for the intended measurement cycles, or should it be 16 while the
   address map is being laid out anyway?
3. Should FLAGS also gate the resonator's noise sources (useful for emulated
   cold/hot switching experiments)?
