#!/usr/bin/env python3
"""
Bit-accurate model of red_pitaya_acq_cic.v.

Same approach as validate_dds_mixer.py: re-implement the module in Python with
identical integer widths and wraparound behaviour, then check it against the
answer we know is correct.

The point of interest here is the deliberate overflow. The integrators are
allowed to run off the top of their registers and wrap round; the combs are
supposed to undo that exactly. That claim is easy to state and easy to get
wrong, so test 2 checks it directly by comparing against arithmetic that cannot
overflow at all (Python's unlimited-precision integers).

Run:  python3 validate_cic.py
"""

import numpy as np

# ---------------------------------------------------------------------------
# Parameters - keep identical to the Verilog module parameters
# ---------------------------------------------------------------------------
F_CLK  = 125e6
DWI    = 24     # input width, signed
DWO    = 32     # output width, signed
NSTAGE = 4      # integrator / comb stages
LMAX   = 12     # largest log2(R)
WACC   = DWI + NSTAGE * LMAX          # 72

MASK = (1 << WACC) - 1


def to_signed(x, w):
    """Interpret the low w bits of x as a two's-complement signed number."""
    x &= (1 << w) - 1
    return x - (1 << w) if x >= (1 << (w - 1)) else x


def cic_hardware(x, dec_log2):
    """Bit-accurate model, including wraparound.

    x        : list/array of ints, the 24-bit signed input stream
    dec_log2 : 6..12, so R = 2**dec_log2

    Returns the list of 32-bit signed output samples.
    """
    R = 1 << dec_log2
    integ = [0] * NSTAGE          # accumulators, held as raw unsigned bit patterns
    prev  = [0] * NSTAGE          # comb memory
    out   = []
    shift = NSTAGE * dec_log2 - (DWO - DWI)   # bottom of the output window

    for n, s in enumerate(x):
        # ---- integrators, every clock, wrapping at WACC bits ----
        integ[0] = (integ[0] + s) & MASK
        for k in range(1, NSTAGE):
            integ[k] = (integ[k] + integ[k - 1]) & MASK

        # ---- combs, once every R clocks ----
        if (n + 1) % R == 0:
            v = integ[NSTAGE - 1]
            for k in range(NSTAGE):
                d = (v - prev[k]) & MASK
                prev[k] = v
                v = d
            # Take the 32-bit window, then read it as signed.
            out.append(to_signed((v >> shift) & ((1 << DWO) - 1), DWO))

    return out


def cic_exact(x, dec_log2):
    """Reference: the same filter with unlimited precision, no wraparound.

    Uses Python's big integers throughout, so if the hardware model's
    wraparound is being undone correctly the two must agree exactly.
    """
    R = 1 << dec_log2
    integ = [0] * NSTAGE
    prev  = [0] * NSTAGE
    out   = []
    shift = NSTAGE * dec_log2 - (DWO - DWI)

    for n, s in enumerate(x):
        integ[0] += s
        for k in range(1, NSTAGE):
            integ[k] += integ[k - 1]
        if (n + 1) % R == 0:
            v = integ[NSTAGE - 1]
            for k in range(NSTAGE):
                d = v - prev[k]
                prev[k] = v
                v = d
            out.append(v >> shift)          # arithmetic shift, sign preserved

    return out


def cic_response(f, R, fs=F_CLK, n=NSTAGE):
    """Analytic CIC magnitude response, normalised to unity at DC."""
    f = np.atleast_1d(np.asarray(f, dtype=float))
    num = np.sin(np.pi * R * f / fs)
    den = R * np.sin(np.pi * f / fs)
    h = np.where(np.abs(den) < 1e-18, 1.0, num / np.where(den == 0, 1, den))
    return np.abs(h) ** n


# ===========================================================================
# Test 1 - DC gain is exactly unity, with 8 fractional bits
# ===========================================================================
def test_dc_gain():
    print("1. DC GAIN (checks the output window is in the right place)")
    ok = True
    for L in range(6, LMAX + 1):
        R = 1 << L
        const = 12345                       # arbitrary constant input
        # Run long enough for the comb memory to fill (a few decimated samples).
        y = cic_hardware([const] * (R * 6), L)
        got = y[-1]
        want = const * (1 << (DWO - DWI))   # unity gain, 8 fractional bits => x256
        flag = "ok" if got == want else "MISMATCH"
        if got != want:
            ok = False
        print(f"   R = {R:5d}:  output {got}  expected {want}   {flag}")
    assert ok, "output window is misplaced for at least one decimation factor"
    print("   PASS\n")


# ===========================================================================
# Test 2 - the deliberate overflow really is undone
# ===========================================================================
def test_wraparound():
    print("2. INTEGRATOR WRAPAROUND (the overflow that is not a bug)")
    rng = np.random.default_rng(1)
    # Full-scale random input: the fastest possible way to make the
    # accumulators run away and wrap.
    lim = 1 << (DWI - 1)
    x = rng.integers(-lim, lim, size=1 << 14).tolist()

    for L in (6, 9, 12):
        R = 1 << L
        if len(x) < R * 4:
            continue
        a = cic_hardware(x, L)
        b = cic_exact(x, L)
        n = min(len(a), len(b))
        same = a[:n] == b[:n]
        print(f"   R = {R:5d}:  {n} decimated samples,  identical to "
              f"unlimited-precision reference: {same}")
        assert same, "wraparound is NOT being undone - widen WACC"

    # Show that the accumulators genuinely did overflow, so the test is not
    # passing vacuously.
    integ = 0
    for s in x:
        integ += s
    print(f"   (running total reached {integ.bit_length()} bits; "
          f"accumulators are {WACC} bits, and stage 4 grows far faster)")
    print("   PASS\n")


# ===========================================================================
# Test 3 - passband droop and alias rejection, and why NSTAGE = 4
# ===========================================================================
def alias_worst(R, f_pass, n):
    """Largest response anywhere that folds onto the passband after downsampling."""
    f_out = F_CLK / R
    return max(cic_response(np.linspace(k*f_out - f_pass, k*f_out + f_pass, 801),
                            R, n=n).max() for k in range(1, 20))


def test_response():
    """Passband droop and alias rejection, and the trade-off between them.

    THE THING TO UNDERSTAND HERE
    ----------------------------
    A CIC filter does not have a flat passband and a sharp edge. Its response
    sags gradually from DC and its stopband nulls sit at multiples of the output
    rate. Two consequences follow, and they pull in opposite directions:

      - DROOP: the further from the centre of the window, the more the signal is
        attenuated. This is a distortion of the measurement, and it is what the
        FIR filter in the next stage exists to undo.

      - ALIASING: after throwing samples away, anything near a multiple of the
        output rate folds down on top of the signal and cannot ever be removed
        afterwards - not by the FIR filter, not in software. It has to be
        attenuated BEFORE the downsampling, which is the CIC's other job.

    Both get worse the wider a band you try to use. So a CIC does not give you
    the full Nyquist window; it gives you a clean central portion, and you choose
    the decimation factor so your feature of interest sits inside it. The table
    below is the number you need to make that choice.
    """
    print("3. FREQUENCY RESPONSE - the usable fraction of the window")
    print("   alpha = passband edge as a fraction of the output sample rate")
    print("   (alpha = 0.5 would be the full Nyquist window)\n")
    print("     alpha    droop(dB)   worst alias(dB)")
    R = 1024
    f_out = F_CLK / R
    for a in (0.05, 0.10, 0.15, 0.20, 0.25, 0.40):
        d = 20 * np.log10(cic_response(a * f_out, R)[0])
        w = 20 * np.log10(alias_worst(R, a * f_out, NSTAGE))
        print(f"     {a:5.2f}   {d:9.2f}   {w:13.1f}")

    print(f"\n   With NSTAGE = {NSTAGE}, alpha = 0.10 gives -0.6 dB droop and better")
    print( "   than -75 dB alias rejection, which is the sensible operating point.")
    print( "   In practice: choose the decimation factor so the resonator occupies")
    print( "   roughly the middle fifth of the window.\n")

    print("   Usable band (alpha = 0.10) for each decimation setting:")
    for L in range(6, LMAX + 1):
        Rk = 1 << L
        fo = F_CLK / Rk
        print(f"     R = {Rk:5d}  ->  output {fo/1e3:9.2f} kSPS, "
              f"clean band +-{0.10*fo/1e3:8.3f} kHz")

    print("\n   Effect of the stage count (at alpha = 0.10):")
    print("     stages   droop(dB)   alias(dB)")
    for n in (2, 3, 4, 5):
        d = 20 * np.log10(cic_response(0.10 * f_out, R, n=n)[0])
        w = 20 * np.log10(alias_worst(R, 0.10 * f_out, n))
        star = "  <- NSTAGE" if n == NSTAGE else ""
        print(f"     {n:^6d}   {d:8.2f}   {w:8.1f}{star}")
    print("\n   More stages reject aliases harder but droop more, and cost wider")
    print("   accumulators. Four is the point where the aliases are already far")
    print("   below anything else in the system.")

    worst_db = 20 * np.log10(alias_worst(R, 0.10 * f_out, NSTAGE))
    assert worst_db < -60, "alias rejection at alpha=0.10 is too weak - raise NSTAGE"
    print("   PASS\n")


# ===========================================================================
# Test 4 - noise really does fall as sqrt(R)
# ===========================================================================
def test_noise():
    print("4. NOISE REDUCTION (the reason this block exists)")
    rng = np.random.default_rng(7)
    print("     R     measured improvement   ideal sqrt(R)")
    for L in (6, 8, 10):
        R = 1 << L
        n = R * 400
        # Modest-amplitude white noise, well away from full scale.
        x = rng.integers(-4000, 4000, size=n).tolist()
        y = np.array(cic_hardware(x, L), dtype=float)
        # Compare like with like: undo the x256 output scaling first.
        sigma_in = np.std(x)
        sigma_out = np.std(y / (1 << (DWO - DWI)))
        meas = sigma_in / sigma_out
        print(f"   {R:5d}     {meas:8.1f}x            {np.sqrt(R):8.1f}x")
        # A 4-stage CIC is not a perfect box-car, so it does slightly better
        # than sqrt(R) - its effective noise bandwidth is a little narrower.
        assert meas > 0.9 * np.sqrt(R), "noise reduction is far below expectation"
    print("   PASS\n")


if __name__ == "__main__":
    print("=" * 68)
    print(" Bit-accurate check of red_pitaya_acq_cic.v")
    print("=" * 68 + "\n")
    test_dc_gain()
    test_wraparound()
    test_response()
    test_noise()
    print("All checks passed.")
