# Acquisition system

Red Pitaya (STEMlab 125-14) implementation of the **acquisition system** from Herkenhoff
*et al.*, Rev. Sci. Instrum. **92**, 103201 (2021) — the blue-outlined blocks of their Fig. 6a.

Built on top of the existing feedback path (`phaseshift_custom/`), which it reads but never
disturbs.

> Archived implementation investigation. Paths and commands below describe the
> former vendored Vivado layout. Use the root `README.md`, `docs/usage.md`, and
> `docs/architecture.md` for the supported workflow.

- **What it does and why** → `EXPLAINER.md`
- **Is it working?** → `sudo python3 ../check_system.py` on the board
- **Build everything** → `source .../project.ps1 build` in Vivado
- **Every edit ever made** → `../CHANGELOG.md`
- **Loading bitstreams** → `../docs/usage.md`

---

## The chain

```
   input --> [ADC] --> [phase shifter] --> [DAC] --> back to trap    (existing, latency-critical)
               |
               | read-only tap: adds no delay
               v
        [reference tone] --> [mixer] --> [decimator] --> [corrector] --> [memory] --> Python
```

| Block | File | Job |
|---|---|---|
| Reference tone | `red_pitaya_acq_dds.v` | Sine and cosine at a software-set frequency, 0.029 Hz steps |
| Mixer | `red_pitaya_acq_mixer.v` | Slides the signal down to 0 Hz, keeping which side it came from |
| Decimator | `red_pitaya_acq_cic.v` | Averages by 64–4096. Cuts the data rate and the noise |
| Corrector | `red_pitaya_acq_fir.v` | Flattens the decimator's droop: 2.32 dB → 0.04 dB |
| Memory writer | `red_pitaya_acq_dma.v` | Packs I/Q into 64-bit words and streams them to memory |
| Top level | `red_pitaya_acq.v` | Registers, debug features, glue |

Coefficients can be **rewritten at run time** — see `notebooks/acquisition/fir_filter_designer.ipynb`.

---

## Changing the correction filter

**The easy way: `notebooks/acquisition/fir_filter_designer.ipynb`, on the board.** Change the passband and stopband,
see the response, load it into the chip in about a second. No Vivado, no rebuild, no bitstream.
The coefficient memory is writable at run time through registers `0x40` and `0x44`.

What that notebook *cannot* change is the **number of taps**, which is built into the wiring
rather than the numbers. That still needs a rebuild — read on.

Changes made from the notebook are lost at the next power cycle, because the chip reverts to
the coefficients built into the bitstream. To make one permanent, put the numbers into the
generator below and rebuild.

### The permanent route

The corrector's coefficients are **generated, never hand-written**. `gen_fir_coeffs.py` is the
single source of truth for both the numbers and the sizes that depend on them.

### Running it

From the `acquisition_custom` folder, on any machine with Python and numpy:

```
python3 gen_fir_coeffs.py
```

It writes three files and prints the response it achieved:

| File | Goes to | Read by |
|---|---|---|
| `fir_coeffs.vh` | next to the RTL | `red_pitaya_acq_fir.v`, inside an `initial` block |
| `fir_params.vh` | next to the RTL | `red_pitaya_acq_fir.v` **and** `red_pitaya_acq.v` |
| `fir_coeffs.txt` | here | `validate_fir.py`, and for reading by eye |

### What `.vh` files actually are

They are **not compiled**. A `.vh` file is a fragment of text that Vivado pastes into the
middle of a module at the `` `include `` line, before compiling anything. `fir_coeffs.vh`
contains nothing but 155 assignments:

```verilog
coef[  0] = 18'sd0;
...
coef[154] = 18'sd71142;
```

and the module says:

```verilog
reg signed [17:0] coef [0:154];
initial begin
  `include "fir_coeffs.vh"
end
```

Vivado evaluates that at **elaboration** — on your PC, during synthesis — and bakes the results
into a small read-only memory's power-on contents. **No hardware is built for the `initial`
block.** The chip simply starts up with those numbers already in place.

Both files must be marked **Verilog Header** in the project, or Vivado tries to compile them
as modules of their own and fails. `add_acquisition_sources.tcl` does that.

### To change the coefficients only

Passband, stopband, window, CIC stage count — anything that does not change how many taps
there are:

1. Edit the parameters at the top of `gen_fir_coeffs.py`
2. `python3 gen_fir_coeffs.py` — check the flatness and stopband it reports
3. `python3 validate_fir.py`
4. Rebuild the bitstream. **No Verilog needs editing.**

### To change the *number* of taps

`NTAPS` used to appear in four places that had to agree, with nothing enforcing it — and a
mismatch does not fail loudly, it produces a filter that builds, runs, and gives wrong answers.
It is now generated into `fir_params.vh` and everything reads from there:

```
gen_fir_coeffs.py ──▶ fir_params.vh ──┬──▶ red_pitaya_acq_fir.v   (builds the filter)
                                      ├──▶ red_pitaya_acq.v       (bypass threshold)
                                      └──▶ validate_fir.py        (checks it)
```

So the procedure is the same as above — edit `NTAPS`, re-run, rebuild — with **one thing to
watch**. The generator prints:

```
HARDWARE REQUIREMENTS (checked automatically at build time):
  multiply-accumulates per output sample : 155
  minimum decimation factor              : 256  (DEC_LOG2 >= 8)
  sample history DEPTH must be at least  : 512  (ABW = 9)
```

- **Minimum decimation** is handled for you: the bypass threshold comes from the same file, so
  raising the tap count automatically raises the decimation at which the filter switches
  itself out.
- **DEPTH** is the one manual step. If the required depth exceeds 512, raise `DEPTH` and `ABW`
  in `red_pitaya_acq_fir.v` to the printed values. Forgetting is not silent — the build fails
  with `ERROR_fir_DEPTH_must_be_at_least_NTAPS_see_gen_fir_coeffs_output`.

**Fewer taps buys a lower minimum decimation.** 155 taps would need only 64 clocks per sample,
so the corrector would work at R = 128 as well. The cost is a softer band edge.

---

## Building

```tcl
source C:/rp/prj/v0.94/Test_Project/project.ps1 build
```

One command: checks the generated filter files are current, adds sources, builds, checks
timing, and reports in plain English. 15-25 minutes.

`add_acquisition_sources.tcl` does the source-adding step alone, if that is all you need.

---

## The digital resonator — base `0x40400000`

A stand-in for the trap's detection coil, built in logic, with a centre frequency and Q that
software sets exactly. Enabled, it replaces the digitised CH A signal and is driven by what the
board is sending out, so the feedback loop closes inside the chip with no cables. **Disabled at
power-on**, and while disabled the board behaves exactly as before.

| Offset | Name | R/W | Contents |
|---|---|---|---|
| `0x00` | CTRL | RW | `[0]` enable — replaces the digitised input `[1]` clear the state, self-clearing |
| `0x04` | COEF_C | RW | `c = r·cos(ω₀) × 2¹⁷`, 18-bit signed |
| `0x08` | COEF_S | RW | `s = r·sin(ω₀) × 2¹⁷`, 18-bit signed |
| `0x0C` | DELAY | RW | Extra loop delay, 0–255 clocks. **Set 15** to match the board's real 119.87 ns |
| `0x10` | OUT_SHIFT | RW | Right shift from the 25-bit state to the 14-bit output. About log₂(Q) |
| `0x14` | STATUS | RO | `[0]` **CLIPPED** — the state saturated. Sticky. If set, the sweep is fiction |
| `0x18` / `0x1C` | PEEK_U / PEEK_V | RO | The two state variables, ninety degrees apart |

`resonator.py` computes the coefficients and carries a bit-exact model of the same arithmetic.

**Q you can ask for.** A resonator amplifies by about Q at its own frequency, and the state has
11 bits of headroom over the input:

| Q | Error from rounding | Largest drive |
|---|---|---|
| 30–1000 | under 0.1% | full scale |
| 3000 | +0.5% | 69% of full scale |
| 10000 | +2.6% | 21% of full scale |

---

## Register map — base `0x40600000`

**Read and write one 32-bit word at a time.** A bulk `mmap` slice becomes a burst the bus
bridge cannot acknowledge; it locks the bus and reboots the board. (Ordinary DDR memory is
different — bulk reads there are fine and fast.)

| Offset | Name | R/W | Contents |
|---|---|---|---|
| `0x00` | CTRL | RW | `[0]` enable `[1]` soft reset `[2]` test pattern `[3]` scope tap `[4]` arm `[5]` wrap `[6]` bypass corrector `[7]` clear writer `[8]` memory port: 0 = axi0 (default — **use this**), 1 = axi1 (drops the Q half of every sample on this board; boot software misconfigures its processor port. Diagnostics only. See CHANGELOG 2026-07-30) |
| `0x04` | LO_FINC | RW | `round(f_lo / 125e6 × 2³²)` |
| `0x08` | DEC_LOG2 | RW | log2 of decimation, 6…12 |
| `0x0C` | SRC_SEL | RW | 0 = IN1, 1 = IN2 |
| `0x10` | TAP_SEL | RW | scope tap: 0 = mixer, 1 = decimator, 2 = corrector |
| `0x14` | TAP_SHIFT | RW | which 14-bit window of the tapped value |
| `0x18` / `0x1C` | PEEK_I / PEEK_Q | RO | most recent sample |
| `0x20` | SAMPLE_CNT | RO | samples produced since reset |
| `0x24` | STATUS | RO | `[0]` enabled `[1]` test `[2]` tap |
| `0x28` | MEM_START | RW | first address of the region |
| `0x2C` | MEM_STOP | RW | **LAST** address — inclusive, not one past the end. Set it to `first + size - 8`. `MEM_CUR` legitimately reads `MEM_STOP + 8` once the region is full |
| `0x30` | MEM_CUR | RO | address being written |
| `0x34` | DMA_COUNT | RO | samples written since clear |
| `0x38` | STATUS2 | RO | `[0]` **overflow — samples lost** `[1]` corrector overrun `[2]` corrector bypassed `[3]` **write error — memory refused a write.** Sticky. Separates "the writes were accepted" from "the writes succeeded" |
| `0x40` | COEF_ADDR | RW | Which correction-filter coefficient to access, 0…154 |
| `0x44` | COEF_DATA | RW | Write: store it. Read: what the chip actually holds — use this to verify |
| `0x48` | BUILD_ID | RO | Hash of the Verilog this bitstream was built from. `check_system.py` compares it with `bitstream_id.txt`. **0 means the bitstream was not built by `project.ps1 build`** and may contain stale logic |

**Order matters.** The decimator holds a running total that assumes a fixed decimation, so
always: disable → write settings → reset → enable. The `setup()` helper in the notebooks does
this.

**Memory region:** the writer writes to whatever physical address you give it. It must be a
region Linux has been told not to use, or it will overwrite the operating system. Test Stage 6
finds one from the kernel command line and refuses to run without it.

---

## Choosing the decimation factor

Decimation sets three things at once. There is no setting that is best at everything.

| R | Output rate | Clean band | Bin spacing (16384 samples) | Corrector |
|---|---|---|---|---|
| 64 | 1.95 MHz | ±195 kHz | 119 Hz | bypassed |
| 128 | 977 kHz | ±98 kHz | 60 Hz | bypassed |
| 256 | 488 kHz | ±49 kHz | 30 Hz | active |
| 1024 | 122 kHz | ±12.2 kHz | 7.5 Hz | active |
| 4096 | 30.5 kHz | ±3.05 kHz | 1.9 Hz | active |

- **Clean band** — the portion of the window where unwanted signals are rejected by better
  than 75 dB. Aim to put the resonator in the middle fifth.
- **Bin spacing** — frequency resolution, which is `1 / acquisition time` and nothing else.
  Sampling faster buys bandwidth; only observing longer buys resolution.
- **Corrector** — needs about 160 clock cycles per sample, so it bypasses itself below R = 256.

---

## Debug features

| Feature | Register | Why it exists |
|---|---|---|
| Test pattern | `CTRL[2]` | Replaces data with `I = n`, `Q = ~n`, so `I + Q = 0xFFFFFFFF` always. Checks the transport with no signal at all: gaps mean dropped samples, repeats mean a stall, a broken invariant means swapped halves |
| Peek registers | `0x18`, `0x1C` | The latest sample, readable directly. Made blocks 1–3 testable long before the memory path existed |
| Scope tap | `CTRL[3]`, `TAP_SEL` | Substitutes an internal signal for the scope's input, so the existing scope captures 16384 samples of any point in the chain |

---

## Test plan

Run in order, as root (`sudo jupyter notebook`). Each ends by disabling the system.

| Stage | Notebook | Checks | Generator |
|---|---|---|---|
| 1 | — (rebuild + `phaseshift_custom` sweep) | The feedback path still measures 119.87 ns | — |
| 2 | `Test Stage 2 …` | Registers, sample rate, reset, reference tone | 1–10 kHz on IN1 |
| 3 | `Test Stage 3 …` | Frequency shift **and the sign convention** | sine on IN1 |
| 4 | `Test Stage 4 …` | Decimation rate, scaling, noise | sine, off for noise |
| 5 | `Test Stage 5 …` | Droop correction, before and after | sine on IN1 |
| 6 | `Test Stage 6 …` | Transport: every sample, in order, undamaged | none |
| 7 | `Test Stage 7 …` | End to end against a known signal | sine on IN1 |
| 8 | — | The real detection system | — |

Stage 3 is the one that matters most: a lost sign would mirror every spectrum, putting the ion
dip on the wrong side of the resonator while looking entirely plausible.

---

## Verification

No Verilog simulator is available, so each block is re-implemented in Python with identical
integer arithmetic and checked against the answer we know is right.

```
python3 validate_dds_mixer.py     # reference tone, mixer
python3 validate_cic.py           # decimator, including its deliberate overflow
python3 validate_fir.py           # corrector, including the symmetric structure
python3 gen_fir_coeffs.py         # regenerate coefficients; prints the achieved response
```

Traps these caught, recorded so nobody rediscovers them:

- The decimator's "data ready" fired one clock early — every sample would have been shifted by
  one, silently.
- Its output bit window was hard-coded and correct only for the default parameters.
- Measuring a −70 dBc spur with the wrong analysis window manufactures a fake −56 dBc one.
- The mixer's output legitimately contains a large component at twice the signal frequency.
  Searching the whole spectrum finds that instead of the signal.

---

## Known limits

| | |
|---|---|
| Noise floor | ~72 counts (−41 dBFS) that averaging cannot remove. It is inside the measurement band, so narrowing the band does not help. Below this, a longer acquisition is not the answer |
| Corrector | Unavailable below R = 256 |
| Trigger sync | Not built. The paper starts captures in step with the feedback sequencer |
| XADC | Compiled for 100 MHz, driven at 200 MHz. Inside the block design; monitors chip temperature only |

---

## Status

| | |
|---|---|
| **Passed on hardware** | Stages 1, 2, 3, 4 — reference tone, frequency shift, decimation, noise scaling |
| | **Stage 5 — all steps.** The droop correction works end to end on hardware |
| | Stage 5b — all four known-answer filter tests |
| **Ready, not yet passed** | Stage 6 — unblocked. This board declares `labuf@a000000`, 32 MB, already reserved |
| | Stage 7 — end to end. Needs 6 first |
| **Not built** | Trigger synchronisation with the feedback sequencer |

The signal path itself is verified from the input through to the corrector. What remains
untested is the path into memory, and the whole thing measured end to end.
