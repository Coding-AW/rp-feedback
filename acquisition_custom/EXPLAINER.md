# How the acquisition system works — plain-English guide

Assumes no prior knowledge of programmable logic. Every term is explained the first time it
appears. For the register map, build steps and test plan, see `README.md`.

---

## 1. The problem

The trap's detection electronics produce a small, fast electrical signal. Somewhere inside it
is the feature we care about: a dip or peak only a **few kilohertz wide**, and in some
experiments only a few **hertz** wide.

The board measures the incoming voltage **125 million times per second**, each measurement a
whole number between −8192 and +8191.

Three things go wrong if we simply record everything:

1. **Storage.** 125 million numbers a second fills any memory almost instantly.
2. **Speed.** The small computer on the board cannot analyse data that fast.
3. **Noise.** Every measurement carries random noise. Looking at raw measurements means
   looking at all the noise from the entire 62 MHz-wide range the board can see, when the
   signal occupies a few kilohertz of it. The signal drowns.

**The solution, in one sentence:** slide the interesting part of the signal down to zero
frequency, then average away everything else.

---

## 2. Background

### What the chip is

The Red Pitaya's main chip has two halves side by side.

- One is an ordinary small computer running Linux. Your Jupyter notebook talks to this. It is
  flexible but far too slow to look at every measurement.
- The other is the **FPGA** — a region of blank digital circuitry that can be wired into
  whatever shape you describe. You do not write a program for it; you describe a *circuit*,
  and the chip physically becomes that circuit.

That distinction is the key. A program does one thing at a time. A circuit does **everything
at once, on every tick of the clock, forever**. That is how it keeps up with 125 million
measurements a second: not by rushing, but by being wide.

### The clock

Everything marches in step with a clock ticking every **8 nanoseconds**. On each tick, every
storage element grabs whatever is on its input. Between ticks, signals travel through wires
and arithmetic and settle.

If a calculation cannot finish within 8 ns, the storage element grabs a value that has not
settled — it captures nonsense. This is a **timing violation**, and it is the single most
important thing to watch when adding logic. Worse, it does not fail cleanly: a path 4 ns too
slow may work at room temperature on one board and corrupt data on another.

### Words used throughout

| Term | Plain meaning |
|---|---|
| Sample | One measurement of the incoming voltage |
| Register | A storage box the computer can read or write — how the notebook controls the hardware |
| Decibel (dB) | A ratio on a logarithmic scale. −6 dB is half the amplitude, −20 dB a tenth, −40 dB a hundredth |

---

## 3. The chain, block by block

```
            the existing feedback path (untouched, must stay fast)
  input --> [ADC] ------> [phase shifter] ------> [DAC] --> back to trap
              |
              | a tap: one extra wire, adds no delay to the loop above
              v
  [0 reference] -> [1 mixer] -> [2 averager] -> [3 corrector] -> [4 memory] -> Python
```

**Nothing in the lower row can slow the upper row down.** The tap is a wire that reads a
value, and reading does not delay anything. This matters: the feedback loop's timing is
critical — measured at exactly 119.87 ns — while the acquisition path's timing is irrelevant,
because nothing it produces goes back into the trap.

---

### Block 0 — The reference tone

**Job:** produce a perfect sine wave inside the chip, at a frequency the notebook sets.

Imagine a clock face with a hand that jumps forward by a fixed angle on every tick. Jump by a
big angle and the hand goes round quickly — a high frequency. That is literally the mechanism:

- A counter holds the current angle. Its full range represents one complete turn, and because
  it is a binary counter it wraps back to zero on its own — exactly what an angle should do.
- Every tick, add a constant. That constant **is** the frequency setting.
- The top 12 bits index a stored table of 4096 sine values.

Smallest step: **0.029 Hz**. Nothing is hard-wired — if your signal arrives mixed down to
1 MHz, you type `1e6`.

We need *two* references a quarter-turn apart. Rather than store two tables, the same table is
read twice at once at two addresses separated by a quarter of its length. Memory blocks have
two independent read ports, so this costs one memory and no extra logic.

---

### Block 1 — The mixer

**Job:** move the interesting part of the signal down to zero frequency. Two multiplications,
and that is the entire block.

From school trigonometry:

```
cos(A) × cos(B)  =  ½cos(A − B)  +  ½cos(A + B)
```

Multiply a signal at frequency *f* by a reference at *f_ref* and you get two new components:
one at the **difference** and one at the **sum**. Put the reference on your signal and the
difference lands at 0 Hz, where a modest sample rate can represent it comfortably.

**The sum term is still there**, at twice the frequency and *the same size*. It is removed by
the next block. This surprises people looking at the mixer output directly — it is a solid
band, not a flat line, and that is correct.

**Why two multiplications, not one.** With a single reference you cannot tell "3 kHz above"
from "3 kHz below" — both give a 3 kHz difference. Since the ion dip sits on one particular
side of the resonator, that ambiguity would destroy the measurement.

Multiplying by **both** references and keeping both results solves it. The pair is written
*I* and *Q*. Think of them as the *x* and *y* coordinates of a rotating arrow: one number
tells you its length, but you need both to know which way it turns. This is why everything
downstream is duplicated.

---

### Block 2 — The averager

**Job:** reduce 125 million numbers a second to something manageable, and suppress noise.

Take *R* consecutive samples, average them, keep one number, discard the rest. The data rate
drops by *R*. Random noise partly cancels when samples are added; a steady signal does not.
Averaging *R* samples improves the signal-to-noise ratio by roughly **√R** — averaging 4096
samples improves it 64 times.

**The trick that makes it cheap.** Adding 4096 stored numbers every tick would be impossible.
Instead:

> The sum of the last 4096 samples equals
> **(the total of everything so far) − (the total up to 4096 samples ago)**.

Both come from a single running total read at two moments. So the whole job is **one addition
per tick** plus one subtraction per output — whatever *R* is. No multiplication at all, which
matters because the chip has only 80 multipliers and the next block needs them.

**The overflow that is deliberate.** The running total grows forever and eventually overflows,
wrapping like a car odometer. This is intentional and provably safe: the subtraction undoes
the wrap exactly, because the wrap cancels in the difference. It only works if the storage is
wide enough — 72 bits here, which is why the registers look oversized.

---

### Interlude — Aliasing, and why the averager must also filter

**If you only look at something occasionally, fast things can masquerade as slow things.**
This is the wagon-wheel effect in old films: wheels appear to spin backwards, because the
camera looks 24 times a second and the spokes move further between looks than you assume.

Concretely: sample a 90 Hz wave 100 times a second and you get *exactly* the same numbers as
sampling a 10 Hz wave. Not similar — identical. No technique can tell them apart, because the
distinguishing information was never captured.

**The rule:** if you sample at rate R, a signal at frequency f is indistinguishable from
signals at f ± R, f ± 2R, … These false copies are **aliases**.

When the averager discards samples it reduces the effective sample rate, so something
previously far away — amplifier noise, a switching-supply harmonic, a stray drive tone — can
fold down onto the ion signal, looking exactly like real physics. **It cannot be fixed
afterwards.** Once two frequencies fold together they are the same numbers.

The only defence is to remove those frequencies *before* discarding samples, which is the
averager's second job. **Alias rejection** measures how well: −77 dB here, meaning anything
dangerous is squashed to a seven-thousandth before it can fold.

**The catch:** you don't get the whole window cleanly.

| Fraction of the window used | Distortion | Alias rejection |
|---|---|---|
| middle 20% | −0.6 dB | −77 dB |
| middle 40% | −2.3 dB | −51 dB |
| middle 80% | −9.7 dB | −24 dB |

**Distortion** is much less serious: the filter is slightly quieter near the window's edge —
like a microphone that under-reports high notes. Nothing is lost; the signal is scaled by a
known amount, so it can be multiplied back out. That is Block 3.

**The asymmetry is the point:** distortion is recoverable, aliasing is not. So the design
accepts a few dB of the first to buy 77 dB of protection against the second.

---

### Block 3 — The corrector

**Job:** undo that distortion, so the window is flat.

The averager's response sags towards the edges by a known, fixed shape. This block applies
the exact opposite shape, so the two cancel.

| Position in the window | Uncorrected | Corrected |
|---|---|---|
| centre | 0 dB | 0 dB |
| halfway out | −0.573 dB | −0.001 dB |
| band edge | **−2.317 dB** | **−0.043 dB** |

It works by multiplying the recent history by a list of **309 fixed numbers** (coefficients)
and adding the results. Those numbers completely define what the filter does; they are
generated by a script and stored in a readable file rather than buried in a tool's settings.

**How 309 multiplications fit in one multiplier.** Two things rescue it:

1. **There is time.** This filter runs at the *decimated* rate, so between output samples
   there are at least 256 clock ticks. One multiplier used 155 times is far cheaper than 155
   multipliers used once.
2. **The filter is symmetric** — the first coefficient equals the last, and so on inward. So
   each coefficient serves two taps, and instead of two multiplications we *add the two
   samples first* and multiply once. That halves the work to 155.

The consequence is a floor on the decimation: 155 multiplications need about 160 ticks, so
below R = 256 the filter cannot keep up and switches itself out of the path automatically.

---

### Block 4 — Getting the data to the computer

**Job:** carry the finished numbers from the FPGA half into the memory the Linux half reads.

1. **Packing.** *I* and *Q* (32 bits each) are glued into one 64-bit number — the natural size
   for the memory system, and it makes it impossible for the pair to become separated.
2. **Buffer.** A queue. The FPGA produces samples at a perfectly steady rate; memory accepts
   them in irregular bursts, because the processor competes for the same path. The queue
   absorbs the mismatch.
3. **Transfer engine.** Copies the queue into memory without the processor fetching each
   number. Python then reads that memory directly.

Red Pitaya's own code already contains a working transfer engine — it is what the stock
oscilloscope uses — so this reuses proven hardware rather than new.

**Overflow is reported, not ignored.** If memory cannot keep up the queue fills and samples
are lost. Lost samples are more damaging than they sound: the record still looks continuous,
but time has silently jumped, so every frequency derived from it is wrong. A sticky flag
catches it.

---

## 4. Two limits worth knowing before you design a measurement

### Frequency resolution is acquisition time

$$\text{bin spacing} = \frac{1}{\text{total acquisition time}}$$

It depends only on **how long you watch**, never on how fast you sample. To distinguish two
frequencies 10 Hz apart you must observe for at least 0.1 s, whatever hardware you use.
Sampling faster buys bandwidth; only observing longer buys resolution.

This is the second reason the averager matters. The scope buffer holds 16384 samples: at the
full rate that is 131 µs and 7629 Hz bins. Decimated by 1024 the same 16384 samples cover
134 ms and give **7.45 Hz** bins. An ion dip a few hertz wide is not merely hard to see at
full rate — it is impossible, regardless of signal-to-noise ratio.

### There is a noise floor averaging cannot remove

Measured at about **72 counts (−41 dBFS)**. Averaging reduces noise by *narrowing the
bandwidth* — it removes what lies outside the final band and passes what is already inside
untouched. As R grows the band shrinks and broadband noise falls as √R, but a component
inside the band is unaffected however narrow the band becomes.

Since the whole chain is a bandpass centred on the reference tone, that floor must be
something arriving within a few kilohertz of it. If your signal is below it, the answer is not
a longer acquisition — it is finding what is sitting in the band.
