# Off-board tests for `Test - Resonator Coil Characterisation.ipynb`

These existed only in `/tmp` and were lost between sessions. They live here now, next to
the notebooks they test.

| File | What it does |
|---|---|
| `fakehw.py` | A register-level mock of the board. It patches `os.open`, `mmap.mmap` and `open`, so every line of the notebook's own driver code runs unmodified — the `Bus` class, the poison check, the DMA bounds readback, `tone_frac`'s least-squares projection. Only the silicon is fake. |
| `audit.py` | Static audit: walks the code cells in order, statement by statement, and flags any name read at module level before anything binds it. Catches ordering bugs that runtime testing misses, because a name left over in a live kernel looks defined when it is not. |
| `run_mock.py` | Runs the whole notebook against the mock, cell by cell, across a scenario matrix. Saves every figure. |

## Running

```
python3 audit.py                 # must print PASS
python3 run_mock.py all          # must print "9 of 9 scenarios behaved as expected"
python3 run_mock.py baseline     # one scenario, with figures written to figs/
```

`run_mock.py` shrinks the grids and removes the settling waits so a full pass
takes seconds. Every code path is still exercised; only the point counts change.

## The scenario matrix

Each scenario declares whether the notebook should **finish** or **refuse**. A
refusal is a pass when refusing is the right answer — that is most of what the
guardrails are for.

| Scenario | Models | Expected |
|---|---|---|
| `baseline` | the chain as actually built | ok |
| `high_q` | a cold, narrow resonator — exercises `choose_dec` at its ceiling | ok |
| `very_narrow` | narrow enough that the coarse step walks over it; only the automatic `SEARCH_STEP` halving finds it | ok |
| `no_amp_declared` | no amplifier, and the configuration says so — `G_PASSIVE` is re-measured | ok |
| `amp_declared_absent` | an amplifier declared but not fitted | refuse |
| `weak_coupling` | coupling far weaker than declared | refuse |
| `big_floor` | an off-resonance floor comparable with the peak | ok |
| `too_noisy` | receiver noise at the level of the signal | refuse |
| `noisy_but_averaged` | the same noise with `N_AVG` raised to match | ok |

The last pair matters: `too_noisy` must refuse *and* say that raising `N_AVG`
is the fix, and `noisy_but_averaged` proves that it is.

## Physics the mock reproduces

A parallel resonator with a chosen f0 and Q plus an additive-in-power floor; a
capacitive round trip with an amplifier that has a gain and a compression knee;
the feedback loop as `Q_eff = Q0/(1 − K cos φ)` with the centre shifted by
`K sin φ` and an **arbitrary loop phase**, so the narrowing phase has to be
found rather than assumed; self-oscillation once `K cos φ ≥ 1`, showing up as
full-scale input with the drive off; the digital resonator emulator decoded from
its own 18-bit coefficients; and receiver noise, so fits degrade at low drive as
they do on the board.
