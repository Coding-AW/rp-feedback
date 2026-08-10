# Test stage design — the remaining stages, in the order they should be run

A design document. Nothing here is coded yet, and nothing here builds a "master" notebook or
a configuration file — that discussion is kept at the end, for later.

Stages 1–10 prove the instrument and reproduce everything in Herkenhoff *et al.* that can be
reproduced against a resonator built in logic. Stage 11 (the parameter sequencer) is already
designed in `SEQUENCER_PLAN.md`. This document designs the seven that are missing.

**Numbering follows the order they should be run in**, which is not the order they were
thought of. Stage 0 carries a zero because it needs no hardware at all and should exist before
any of the others.

---

## What each new stage does *not* repeat

Every proposal below was checked against what Stages 1–10 already do. Where they touch, the
new stage is scoped to only the part that is genuinely missing.

| New stage | Closest existing work | Already covered | What is actually new |
|---|---|---|---|
| 0 — Analysis self-test | 5b, known-answer filter tests | Same idea, applied to the *filter in the chip* | The same idea applied to the *analysis code*, off the board |
| 12 — Replace emulator-only checks | 10 Step 1, the scan | The scan itself | Two of its decisions cannot run without an emulator |
| 13 — Input health | 4 (noise vs averaging), 7 Step 1 (input level), 7 Step 3 (noise floor) | How the floor scales, and what amplitude to expect | Overload detection, a catalogue of stray signals, and agreement *between* the three measurement paths |
| 14a — Clock, internal | 2 (reference tone and timing) | A 0.3 s sample-rate check against Linux time | The same comparison run long enough to measure stability, plus temperature and warm-up |
| 14b — Clock vs reference | 14a | Stability | Absolute accuracy, which no internal test can reach |
| 15 — Find the resonance | 8 Step 1 (open-loop sweep) | Sweeping and fitting a resonance you have been told about | The two passes *before* that, which find it in the first place |
| 16 — Does anything move | 9 Step 4 (the servo) | Correcting drift, against drift put there on purpose | Measuring how much real drift there is, and whether a scan outruns it |
| 17 — Both electrodes | none | — | All of it |

---

# Phase 0 — No hardware needed

## Stage 0 — Does the analysis give the right answer?

**Proves:** the fitting and sweep code returns known answers on made-up data, and keeps doing
so after every future edit.

**Why it is first.** Everything from Stage 8 upward rests on fitting code that has repeatedly
returned confident, plausible, wrong numbers: a width correction silently capped at its own
limit, inflating Q; a noise floor absorbed into the fit, inflating linewidth by up to 168% on
broad lines; a tone detector too noisy to carry the decision resting on it; a stability test
compared against a floor that is exactly zero on this plant, which marked all 408 points
unstable. Each was found by feeding the real functions made-up data whose answer was known,
and nothing in the repository does that deliberately. The two existing checkers confirm the
code is *consistent*; nothing confirms it is *correct*.

**Method.** A plain Python file, runnable anywhere, feeding the analysis functions a synthetic
signal: a resonance of known centre, width and area, seen through the receiver's own smearing,
on a noise floor you choose, with seeded random noise so runs repeat exactly. Vary the
resonance from four times too broad to forty times too narrow, and the floor from negligible
to a third of the peak. Include one plant that limits softly and one whose undriven output is
exactly zero — the two behaviours that have already caused failures.

**Passes if:** every recovered value lands inside a written-down tolerance across the whole
range, and no error escapes. The tolerances are numbers in the file, so a regression shows up
as a number moving rather than someone's judgement.

**Depends on:** nothing. **Cost:** about a day; seconds to run thereafter.

---

# Phase 1 — While the emulated coil still exists

> This phase exists because of a one-way door. Once the resonator is disabled and a real coil
> is cabled, **there is no longer any way to check an answer against a known one.** Anything
> that needs the emulator to validate it has to be done now.

## Stage 12 — Replace the two checks that only work on an emulator

**Proves:** the atlas can still tell oscillating points from usable ones on a coil whose noise
cannot be switched off or turned down.

**Why here.** Two decisions inside Stage 10's scan are impossible on real hardware, and both
are flagged in the notebook:

- The stability test switches the coil's thermal noise **off** and sees whether the signal
  survives. Real thermal noise has no off switch.
- The linearity check drops that noise by 12 dB and requires the resonance to shrink by 16×.
  Real thermal noise is not adjustable either.

Their replacements can only be trusted if they are checked against the versions that work,
and those only work while the emulator is available. Doing this later means shipping two
unvalidated decisions into the physics.

**Method.** For stability, use how *tone-like* the signal is — a number already computed in
the notebook, 1 for pure noise and 0 for a pure tone. It was set aside for spotting mild
squashing, where it had to resolve a 10% change against 30% scatter; telling an oscillation
from noise is the easy version of the same question. For linearity, inject a tone through the
generator at two amplitudes instead of changing the thermal noise, and require the response to
grow in proportion.

**Passes if:** across a full atlas on the emulated coil, where both old and new methods run,
they agree on the classification of every point. Disagreements are listed individually, not
averaged away.

**Depends on:** Stage 0. **Cost:** two days. No rebuild.

---

# Phase 2 — On the bench, before the coil is connected

## Stage 13 — Is the input healthy?

*(This merges what began as three separate ideas — signal levels, stray signals, and agreement
between measurement paths. They ask the same question, use the same captures, and splitting
them would mean running the same measurement three times.)*

**Proves:** the signal reaching the converter is inside its usable range, nothing else in the
band can be mistaken for the coil, and the three ways of measuring it agree.

**Why here.** This must come *before* Stage 15 goes looking for a resonance. A stray signal
sitting near the coil frequency would be found by that search and fitted as a spectacular
high-Q resonance; an overloaded input produces a distorted shape that still looks vaguely
resonant. Searching first and checking afterwards gets that backwards.

The overload point is the sharpest: **there is no input-overload detection anywhere in this
design.** The output stage limits, and the emulated resonator has a sticky overload flag —
which is what has quietly been doing this job for ten stages. Disable the emulator and that
flag goes with it, exactly when an unknown coil, cryogenic amplifier and gain chain start
presenting unknown levels.

**Method.** Three things from one set of captures.

- *Levels.* Count samples near full scale, and compare the peak-to-average ratio against what
  pure noise gives for that record length — thermal noise has a calculable value, a clipped
  signal does not. Report headroom in decibels and refuse a sweep taken with less than a
  stated margin.
- *Stray signals.* With the input terminated and the emulator off, sweep the whole usable band
  and catalogue every line above the floor, by frequency and size. Repeat with the generator
  running, to catch products of the mixing.
- *Agreement.* Measure one steady tone through all three paths — the register voltmeter, the
  memory capture, the averaged spectrum — convert to the same units and compare. Stage 7
  already checks the memory capture against a known signal, so only the other two comparisons
  are new.

**Passes if:** a deliberately overdriven input trips the check every time and a correctly
levelled one never does; the catalogue exists and nothing sits within a few linewidths of the
intended operating frequency; and the three paths agree inside their combined stated
uncertainty.

**Run it twice.** Once now, which establishes the method and the board's own stray signals.
Again once the coil and amplifier are attached, which is the only way to learn the real
levels. The second run is a repeat of the same notebook, not a new stage.

**Depends on:** nothing new. **Cost:** a day and a half. A hardware overload flag — a
comparator and a sticky bit — would make the levels check exact rather than statistical and is
worth folding into the next rebuild.

## Stage 14a — Does the board's own clock hold still? (no reference needed)

**Proves:** how *stable* the clock is, using only what is already on the board — and decides
whether Stage 14b is needed at all.

**The key fact.** This board carries **two independent crystals**: the 125 MHz oscillator that
drives the fabric and the sample counter, and the processor's own 33.333 MHz crystal, which is
what Linux's clock runs on. Neither is a standard, but they are independent, and comparing
them is a real two-oscillator measurement. Stage 2's `measure_rate()` already does exactly
this — it counts samples against `time.time()` — but for 0.3 s, as a sanity check. Run it for
long enough and it becomes metrology:

| Run length | Samples counted | Resolution |
|---|---|---|
| 0.3 s (today) | 37,000 | 27 ppm |
| 100 s | 1.2 x 10^7 | 0.08 ppm |
| 1000 s | 1.2 x 10^8 | 0.008 ppm |

**Accuracy and stability are different questions, and only one of them needs a standard.**
Accuracy is a fixed offset: if both crystals are 20 ppm low, their ratio is perfect and
everything is still 20 ppm wrong. That part is irreducible. Stability — whether the clock
wanders — is fully measurable here, because independent crystals of different cuts and
frequencies do not drift together. A stable ratio means both are stable; a drifting ratio
means at least one is drifting by that much, and you have bounded it.

**Which measurements actually care.** Most of this project's quantities are ratios or
differences, in which the clock error cancels:

| Quantity | Sensitive to clock *accuracy*? |
|---|---|
| Q = centre / linewidth | No — a ratio of two frequencies from the same clock, so it cancels exactly |
| Linewidth in Hz | Scales with it: 10 ppm of 222 kHz is 2 Hz. Irrelevant |
| Decoupling shift | A difference: 10 ppm of 170 kHz is 1.7 Hz. Irrelevant |
| Oscillation frequency scatter | No — a scatter is a stability measurement |
| Absolute centre frequency | Yes — 10 ppm of 40 MHz is 400 Hz |

Only the last cares, and the paper's 0.75 Hz figure is a scatter, not an absolute. So for
nearly everything measured here, stability is the question — and stability is exactly what
this stage settles without a standard.

**Method.** Three measurements, no extra hardware.

1. **Long two-crystal comparison.** Count acquisition samples against Linux time over runs of
   100 s and 1000 s. Report the fractional difference and how it changes with averaging time.
2. **Temperature.** The Zynq's on-chip sensor is already instantiated in the block design
   (`system_xadc_0`). Log the clock ratio against die temperature through a warm-up and a
   working day. Crystals have a known temperature curve, so movement here is real, correctable,
   and predicts what a cold morning does to a seven-minute scan.
3. **Warm-up.** Start from cold and watch the ratio settle. This says how long to wait before
   trusting a measurement.

**Decision rule — the point of the stage.**

- Combined stability well below 2 x 10^-8 at the averaging times used, and the quantities of
  interest are ratios or differences → **no external reference needed.**
- Drift at the ppm level over a scan duration, or a strong temperature dependence →
  temperature control or a reference is needed.
- Absolute frequency needed to better than about 10 ppm → a reference is needed regardless,
  and no internal test can change that.

**One more free data point.** A bench signal generator has a *specified* timebase, often
±1 ppm. Stage 7 already observed tens of ppm disagreement between generator and board. Read
against the generator's specification, that single existing observation already says which of
the two to suspect.

**Passes if:** the stability curve exists and the decision rule returns a clear answer. Like
Stage 15's bootstrap, this produces numbers rather than a verdict.

**Depends on:** nothing. **Cost:** half a day, most of it waiting. No rebuild.

## Stage 14b — Compare against a real reference (only if 14a says so)

**Proves:** the absolute accuracy of the clock.

**Why conditional.** This is the only thing 14a cannot do, and it needs hardware the lab may
not have. Run it only if 14a shows drift that matters, or if an absolute frequency is required.

Note that Stage 2 already checks the reference tone and the sample rate — but against the
board's own clock. A counter driven by the clock under test cannot detect a clock that is
wrong. The same argument applies to the sequencer's timing check in `SEQUENCER_PLAN.md`.

**Method.** Compare against a rubidium or GPS-locked 10 MHz reference, or at minimum a counter
with a known timebase. Measure the fractional offset with a stated uncertainty.

**Passes if:** the offset is measured, or a correction factor is produced for later stages.

**Depends on:** Stage 14a, and access to a reference. **Cost:** a day.

---

# Phase 3 — With the real coil connected

## Stage 15 — Find the resonance without being told where it is

**Proves:** the system can locate a resonance it knows nothing about, and measure its centre
and width well enough for Stages 8–10 to run on the result.

**Why here.** Every physics stage is currently *handed* the answer, and about forty-six places
downstream read it back — sweep ranges, grid centres, receiver tuning, pass criteria. This is
the largest single piece of work between here and real data. It comes after Stage 13 because
searching a band you have not surveyed is how a stray signal becomes a discovery.

**Method.** Three widening passes, of which only the first two are new — Stage 8's existing
sweep already does the third.

1. **Look around.** Step the receiver across the plausible band, short records, coarse
   averaging, and find where there is more power than elsewhere. No fitting; this only has to
   find the neighbourhood.
2. **Bracket it.** Widen the range around the best candidate until the curve clearly comes back
   down on both sides, so the fit is filling in between points rather than guessing past them.
3. **Refine it.** Hand over to the existing adaptive sweep, which already zooms in, widens out,
   undoes the receiver's smearing, and refuses to return a fit it cannot justify.

**Passes if:** run against the emulated coil at three Q values from 100 to 3000 *without being
told them*, it finds each Q to within 10% and each centre to within a tenth of a linewidth. A
known-answer test of a routine whose whole job is working without one — which means the
validation part belongs in Phase 1, even though the stage is used in Phase 3.

**Depends on:** Stages 0 and 13. **Cost:** two to three days. No rebuild.

## Stage 16 — Does anything move while you are measuring?

*(Merges plant drift and loop-phase stability: both are answered by re-measuring one fixed
point at intervals, so they share a single run.)*

**Proves:** the coil and the feedback loop stay put long enough that one scan describes one
system.

**Why here.** It needs a resonance to watch, so it cannot precede Stage 15. A full atlas takes
about seven minutes; the emulated coil is exactly constant for all of it, while a real
cryogenic coil drifts with temperature and answers to vibration. If the centre moves during a
scan, the map smears in a way that looks like real structure.

The loop's phase is the same question elsewhere. The delay gives a quarter turn at one
frequency only, and the atlas moves the resonance by up to ±170 kHz. The effect is small —
roughly 0.02° per kHz — but the narrowing phase is exactly where the map is most sensitive, so
it is worth measuring rather than assuming.

Stage 9's servo already *corrects* drift, against drift injected on purpose. This stage
measures how much there really is, which is what says whether the servo needs to run during an
atlas at all.

**Method.** Re-measure one fixed operating point at intervals over longer than a full scan,
recording centre, width and achieved phase against time. Then interleave: run an atlas in
which every Nth point is a repeat of that reference, so drift is measured *inside* the scan it
would otherwise corrupt.

**Passes if:** drift over one scan is a stated fraction of a linewidth. If it is not small, the
interleaved reference becomes a correction rather than a diagnostic — which is then this
stage's real deliverable.

**Depends on:** Stage 15. **Cost:** a day, mostly waiting. No rebuild.

---

# Phase 4 — Needs a rebuild

## Stage 11 — Parameter sequencer

Designed in `SEQUENCER_PLAN.md`; that plan stands. One addition: its timing check uses the
memory writer's own sample counter, and a counter driven by the clock under test cannot detect
a clock that is wrong. Pair it with Stage 14a.

## Stage 17 — Driving both electrodes

**Proves:** feedback can be applied to the trap without shifting the trap centre and without
leaking straight into the pickup.

**Why last.** It needs a hardware decision first, and the test only makes sense once that
hardware exists.

**Why it matters.** Driving one electrode makes the trap potential lopsided, which pulls the
very frequency being measured, and couples directly across into the detection electrode — so
the loop partly feeds back on its own leakage rather than on the ion. An equal and opposite
drive on the facing electrode cancels both by symmetry.

**Status.** Not implemented. There is one feedback output driving one converter; the board has
a second, currently used by the generator. The logic is small — invert, route, one trim
register — but the two channels must be matched in both size and timing, and the
fractional-delay mechanism needed for the timing trim already exists.

**Method.** Move the resonance far from the drive frequency so the coil contributes nothing,
drive one electrode, measure what leaks into the pickup, then trim the second channel until it
cancels. Report the depth of the cancellation in decibels.

**Passes if:** leakage is suppressed by a stated amount, and the cancellation holds across the
operating band rather than at a single frequency.

**Depends on:** a rebuild, and the hardware decision. **Cost:** a rebuild plus a day.

---

## Order at a glance

| | Stage | Needs | Blocking? |
|---|---|---|---|
| 1 | **0** — analysis self-test | nothing | yes — protects everything after it |
| 2 | **12** — replace emulator-only checks | the emulator, while it exists | yes — cannot be validated later |
| 3 | **13** — input health | bench, terminated input | yes — before any search |
| 4 | **14a** — clock, internal | nothing | decides whether 14b is needed |
| 4b | **14b** — clock, external | a reference | only if 14a says so |
| 5 | **15** — find the resonance | the coil | yes — everything above 8 needs it |
| 6 | **16** — does anything move | a found resonance | no, but it bounds every scan |
| 7 | **11** — sequencer | rebuild | no |
| 8 | **17** — both electrodes | rebuild + hardware decision | no |

## Deliberately not proposed

- **A bit-exact model versus hardware comparison.** `resonator.py` holds the model and Stage 8
  already checks hardware against a known answer.
- **More emulated-physics stages.** Everything reproducible against a plant whose answer is set
  by software has been reproduced.
- **Re-verifying Stages 2–7 on the real coil.** They never touch the coil. They need re-running
  at the real operating frequency and averaging, which is a parameter change already noted in
  each notebook — not a new stage.

---

# Appendix — notebook organisation (analysis only, not to be built yet)

Kept because the reasoning is still useful, but **nothing below is to be implemented at this
stage.**

The case against a single "master" notebook that configures everything and runs every
measurement: it merges a diagnostic job with a productive one, which want opposite things; it
maximises the damage from hidden notebook state, a trap this project has already recorded; it
chains a dozen automated judgements into one run whose success is the product of all of them;
the pass/fail discipline that makes these stages trustworthy does not survive the move to a
plant with no known answers; and a long run is not resumable, which has already cost twelve
rows of a scan.

What the idea is really reacting to is duplication, and that part is real and measurable:

| Code | Copied into |
|---|---|
| Driver classes (~137 lines) | Stages 8, 9, 10 |
| `capture()` | Stages 7, 9, 10 |
| `_poison()` | Stages 7, 9, 10 |
| `_lorentz_core()` | Stages 8, 9, 10 |
| `welch_psd()` | Stages 9, 10 |

One `capture()` bug recently had to be fixed in two notebooks and one fitting change in three.
When the time comes, the fix is a shared library rather than a master notebook — and the
stages above are written so that each produces a small number of measured values that such a
library would later consume.
