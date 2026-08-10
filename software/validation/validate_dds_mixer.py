#!/usr/bin/env python3
"""
Bit-accurate model of red_pitaya_acq_dds.v + red_pitaya_acq_mixer.v.

WHY THIS EXISTS
---------------
There is no Verilog simulator in the toolchain used to develop this, so
correctness is established the same way it was for the phase shifter (see
software/validation/validate_phaseshift.py): by re-implementing the module in
Python using EXACTLY the same integer arithmetic - same widths, same
truncations, same shifts - and checking the result against the ideal
floating-point answer.

If this model and the Verilog ever disagree, one of them has a bug, and the
model is short enough to audit line by line.

WHAT IT CHECKS
--------------
  1. The sine lookup table's amplitude accuracy.
  2. The spurious-tone level caused by phase truncation, against the
     -(6.02*LUTW - 3.9) dBc rule of thumb quoted in the module header.
  3. That a tone at (f_lo + df) really does come out as a complex tone at
     +df - i.e. that the sign convention is right and the spectrum is not
     mirrored.
  4. That the mixer cannot overflow its 24-bit output with a full-scale input.

Run:  python3 validate_dds_mixer.py
"""

import numpy as np

# ---------------------------------------------------------------------------
# Parameters - keep these identical to the Verilog module parameters
# ---------------------------------------------------------------------------
F_CLK = 125e6      # Red Pitaya processing clock
PACCW = 32         # phase accumulator width
LUTW  = 12         # sine table address width
DWL   = 16         # local oscillator word width, signed
DWI   = 14         # ADC word width, signed
DWO   = 24         # mixer output width, signed
SHIFT = 6          # right shift applied to the raw product

LUT_DEPTH = 1 << LUTW
QUARTER   = LUT_DEPTH >> 2
AMPL      = (1 << (DWL - 1)) - 1          # 32767


# ---------------------------------------------------------------------------
# The sine table, built exactly as the Verilog initial block builds it
# ---------------------------------------------------------------------------
def build_sine_rom():
    """Mirror of the `initial` block: round-to-nearest, then truncate to int."""
    rom = np.zeros(LUT_DEPTH, dtype=np.int64)
    for k in range(LUT_DEPTH):
        s = np.sin(2.0 * np.pi * k / LUT_DEPTH)
        rom[k] = int(AMPL * s + (0.5 if s >= 0 else -0.5))
    return rom


SINE_ROM = build_sine_rom()


def freq_word(f_out):
    """set_finc for a requested output frequency (module header, step 2)."""
    return int(round(f_out / F_CLK * (1 << PACCW)))


def dds(n_samples, finc, phase0=0):
    """Bit-accurate local oscillator. Returns (cos, sin) as int arrays."""
    mask = (1 << PACCW) - 1
    acc = np.zeros(n_samples, dtype=np.int64)
    p = phase0 & mask
    for n in range(n_samples):
        acc[n] = p
        p = (p + finc) & mask                     # wraps naturally, as in hardware
    addr_sin = (acc >> (PACCW - LUTW)).astype(np.int64)      # phase truncation
    addr_cos = (addr_sin + QUARTER) % LUT_DEPTH
    return SINE_ROM[addr_cos], SINE_ROM[addr_sin]


def arshift(x, s):
    """Arithmetic right shift, matching Verilog's >>> on a signed value.

    Python's >> on a negative int already rounds towards minus infinity, which
    is exactly what an arithmetic shift does in hardware, so this is a direct
    equivalent. It is wrapped in a named function purely so the intent is
    obvious at the call site.
    """
    return x >> s


def mixer(adc, lo_cos, lo_sin):
    """Bit-accurate mixer. adc/lo are int arrays; returns (I, Q) int arrays."""
    prod_i = adc * lo_cos
    prod_q = -(adc * lo_sin)                      # note the minus: sign convention
    return arshift(prod_i, SHIFT), arshift(prod_q, SHIFT)


def blackman_harris(n):
    """4-term Blackman-Harris window (sidelobes about -92 dB).

    WHY NOT numpy's np.hanning: measuring a -70 dBc spur needs a window whose
    OWN spectral leakage is well below that. A Hann window leaks at roughly
    -60 dB a few bins from the carrier, so it manufactures a fake "spur" at
    about -56 dBc and the test fails for no reason. (This exact trap was hit
    during development - the design was fine, the measurement was not.)
    """
    a = [0.35875, 0.48829, 0.14128, 0.01168]
    k = np.arange(n)
    return sum((-1) ** i * a[i] * np.cos(2 * np.pi * i * k / n) for i in range(4))


def quantise_adc(x_float):
    """Full-scale float in [-1, 1] -> 14-bit signed integer, saturating."""
    q = np.round(x_float * ((1 << (DWI - 1)) - 1)).astype(np.int64)
    return np.clip(q, -(1 << (DWI - 1)), (1 << (DWI - 1)) - 1)


# ===========================================================================
# Test 1 - sine table amplitude accuracy
# ===========================================================================
def test_table_accuracy():
    ideal = AMPL * np.sin(2.0 * np.pi * np.arange(LUT_DEPTH) / LUT_DEPTH)
    err = SINE_ROM - ideal
    print("1. SINE TABLE")
    print(f"   entries              : {LUT_DEPTH}")
    print(f"   peak amplitude       : {SINE_ROM.max()} / {SINE_ROM.min()}"
          f"   (symmetric: {SINE_ROM.max() == -SINE_ROM.min()})")
    print(f"   worst rounding error : {np.abs(err).max():.3f} LSB  (expect <= 0.5)")
    assert np.abs(err).max() <= 0.5 + 1e-9, "table rounding is worse than half an LSB"
    assert SINE_ROM.max() == -SINE_ROM.min(), "table is not symmetric"
    print("   PASS\n")


# ===========================================================================
# Test 2 - spurious tone level from phase truncation
# ===========================================================================
def test_spur_level():
    # A frequency deliberately NOT commensurate with the table, which is the
    # worst case for phase truncation. 40 MHz-ish but with an awkward offset.
    f_lo = 40e6 + 1234.567
    n = 1 << 16
    cos_i, sin_i = dds(n, freq_word(f_lo))

    z = cos_i + 1j * sin_i
    spec = np.abs(np.fft.fft(z * blackman_harris(n))) ** 2
    carrier_bin = int(round(f_lo / F_CLK * n)) % n

    # Blank the carrier and its window skirts, then find the largest survivor.
    mask = np.ones(n, dtype=bool)
    for b in range(carrier_bin - 12, carrier_bin + 13):
        mask[b % n] = False
    worst = 10 * np.log10(spec[mask].max() / spec[carrier_bin])
    predicted = -(6.02 * LUTW - 3.9)

    print("2. PHASE-TRUNCATION SPURS")
    print(f"   LUTW                 : {LUTW}")
    print(f"   rule-of-thumb worst  : {predicted:.1f} dBc")
    print(f"   measured worst spur  : {worst:.1f} dBc")
    # The rule of thumb is a pessimistic worst case, so the real design should
    # come in AT or BELOW it. A couple of dB of slack allows for the finite FFT.
    assert worst < predicted + 2, "spurs are worse than the rule of thumb predicts"
    print("   PASS\n")


# ===========================================================================
# Test 3 - downconversion, including the sign convention
# ===========================================================================
def test_downconversion():
    f_lo = 40e6
    n = 1 << 16
    t = np.arange(n) / F_CLK

    print("3. DOWNCONVERSION AND SIGN CONVENTION")
    for df in (+3e3, -3e3):
        # Input tone at f_lo + df, at -6 dB of full scale (leaves headroom).
        adc = quantise_adc(0.5 * np.cos(2 * np.pi * (f_lo + df) * t))
        cos_i, sin_i = dds(n, freq_word(f_lo))
        I, Q = mixer(adc, cos_i, sin_i)

        z = I + 1j * Q
        spec = np.abs(np.fft.fft(z * blackman_harris(n)))
        # Frequency axis in Hz, with negative frequencies in the upper half.
        freqs = np.fft.fftfreq(n, d=1 / F_CLK)

        # IMPORTANT: the raw mixer output contains TWO components of comparable
        # size - the wanted difference term near 0 Hz, and the unwanted sum term
        # at f_sig + f_lo = 80 MHz, which at a 125 MSPS sample rate folds back to
        # 125 - 80 = 45 MHz. Removing that image is the job of the CIC filter in
        # the NEXT stage, so at this point in the chain we must look only at
        # baseband. (Searching the whole spectrum finds the 45 MHz image instead,
        # which is correct behaviour and not a bug.)
        baseband = np.abs(freqs) < 1e6
        idx = np.where(baseband)[0]
        peak = freqs[idx[np.argmax(spec[idx])]]

        # Report how big the image is, purely so the number is on record.
        image = spec[~baseband].max() / spec[idx[np.argmax(spec[idx])]]

        print(f"   input at f_lo {df:+.0f} Hz  ->  baseband peak at {peak:+.1f} Hz"
              f"   (45 MHz image: {20*np.log10(image):+.1f} dB, removed by the CIC)")
        assert np.sign(peak) == np.sign(df), (
            "SPECTRUM IS MIRRORED - the minus sign on the Q product is wrong")
        assert abs(abs(peak) - abs(df)) < 2 * F_CLK / n, "peak is at the wrong frequency"
    print("   PASS (positive offset -> positive frequency, as intended)\n")


# ===========================================================================
# Test 4 - overflow headroom at full scale
# ===========================================================================
def test_headroom():
    n = 1 << 14
    t = np.arange(n) / F_CLK
    # Worst case: full-scale input exactly in phase with the reference.
    adc = quantise_adc(np.cos(2 * np.pi * 40e6 * t))
    cos_i, sin_i = dds(n, freq_word(40e6))
    I, Q = mixer(adc, cos_i, sin_i)

    limit = 1 << (DWO - 1)
    worst = max(np.abs(I).max(), np.abs(Q).max())
    print("4. OVERFLOW HEADROOM")
    print(f"   24-bit signed limit  : +-{limit}")
    print(f"   worst sample seen    : {worst}")
    print(f"   margin               : {20*np.log10(limit/worst):.2f} dB")
    assert worst < limit, "MIXER OVERFLOWS - increase DWO or SHIFT"
    print("   PASS\n")


if __name__ == "__main__":
    print("=" * 68)
    print(" Bit-accurate check of red_pitaya_acq_dds.v + red_pitaya_acq_mixer.v")
    print("=" * 68 + "\n")
    test_table_accuracy()
    test_spur_level()
    test_downconversion()
    test_headroom()
    print("All checks passed.")
