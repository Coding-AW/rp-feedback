#!/usr/bin/env python3
"""
Generate the droop-correction filter coefficients (block 3).

WHAT THIS FILTER IS FOR
-----------------------
The decimator averages, and averaging is not an even-handed filter: signals at
the centre of the measurement window pass at full strength, signals near the
edge come out weaker. That sag is called passband droop. It is a distortion of
the measurement - the same ion signal would appear smaller simply for sitting
further from the local oscillator.

Nothing is lost, though. The sag is a known, fixed shape, so it can be undone by
a second filter with exactly the opposite shape. That is what this script
designs.

THE SHAPE TO UNDO
-----------------
A CIC filter of NSTAGE stages decimating by R has the response

    |H(v)| = | sin(pi*R*v) / (R*sin(pi*v)) | ** NSTAGE

where v is frequency as a fraction of the INPUT sample rate. Expressed against
the OUTPUT rate - which is what the correction filter runs at - and for large R
this becomes simply

    |H(u)| = | sinc(u) | ** NSTAGE ,        u = f / f_out

That limit is what makes one fixed set of coefficients work for every decimation
factor: written in units of the output rate, the droop shape barely changes.
(The script checks this rather than assuming it - see the verification table.)

So the wanted response is 1/|sinc(u)|**NSTAGE across the passband, rolling off
to zero beyond it.

OUTPUTS
-------
    fir_coeffs.vh    Verilog include file, read by red_pitaya_acq_fir.v
    fir_coeffs.txt   the same numbers as plain text, for inspection

Run:  python3 gen_fir_coeffs.py
"""

import numpy as np
import os

# ---------------------------------------------------------------------------
#  Design parameters - change these and re-run to redesign the filter
# ---------------------------------------------------------------------------
NTAPS    = 309      # matches the paper. Must be ODD so the filter is symmetric
                    # about a whole sample, which keeps the delay exact and lets
                    # the hardware exploit symmetry (155 multiplies, not 309).
NSTAGE   = 4        # CIC stages - must match red_pitaya_acq_cic.v
PASSBAND = 0.20     # correct the droop out to this fraction of the output rate
STOPBAND = 0.28     # fully suppressed beyond here (0.5 = output Nyquist)
COEFW    = 18       # coefficient width in bits, signed. 18 is the widest the
                    # chip's multiplier takes without needing a second one.
COEF_FRAC = COEFW - 1   # coefficients stored as integers scaled by 2**17

NGRID = 8192        # frequency grid used for the design


def cic_droop(u, n=NSTAGE):
    """Droop shape in the large-R limit: |sinc(u)|**n, u in units of f_out."""
    u = np.asarray(u, dtype=float)
    s = np.ones_like(u)
    nz = u != 0
    s[nz] = np.sin(np.pi * u[nz]) / (np.pi * u[nz])
    return np.abs(s) ** n


def design():
    """Design the filter by frequency sampling, then window it.

    1. Write down the response we want on a dense frequency grid.
    2. Inverse Fourier transform it to get the impulse response.
    3. Multiply by a window, which trades a slightly softer band edge for a much
       lower stopband - an unwindowed truncation rings badly (Gibbs).
    4. Keep the middle NTAPS samples.
    """
    # --- 1. wanted response -------------------------------------------------
    u = np.linspace(0.0, 0.5, NGRID // 2 + 1)      # 0 .. Nyquist of the output rate
    D = np.zeros_like(u)

    passband = u <= PASSBAND
    D[passband] = 1.0 / cic_droop(u[passband])     # the inverse of the droop

    # Smooth cosine taper across the transition. A step here would demand an
    # infinitely long filter; a smooth edge is what makes a finite one work.
    trans = (u > PASSBAND) & (u < STOPBAND)
    x = (u[trans] - PASSBAND) / (STOPBAND - PASSBAND)
    D[trans] = (1.0 / cic_droop(np.array([PASSBAND]))[0]) * 0.5 * (1 + np.cos(np.pi * x))
    # beyond STOPBAND, D stays zero

    # --- 2. impulse response ------------------------------------------------
    h_full = np.fft.irfft(D, n=NGRID)              # zero-phase, peak at n=0
    h_full = np.roll(h_full, NGRID // 2)           # move the peak to the middle

    # --- 3 & 4. window and truncate ----------------------------------------
    c = NGRID // 2
    half = NTAPS // 2
    h = h_full[c - half: c + half + 1]
    h = h * np.blackman(NTAPS)

    # Normalise to unity gain at DC, so the filter changes shape without
    # changing the overall scale. sum(h) IS the DC gain of a filter.
    h = h / h.sum()
    return h


def quantise(h):
    """Convert to integers, then correct the DC gain that rounding disturbs."""
    scale = 1 << COEF_FRAC
    q = np.round(h * scale).astype(np.int64)

    # Rounding 309 numbers individually shifts the sum slightly, which would
    # show up as a small gain error. Push the difference into the centre tap,
    # which is the largest and least sensitive.
    err = scale - q.sum()
    q[NTAPS // 2] += err

    lim = (1 << (COEFW - 1)) - 1
    if np.abs(q).max() > lim:
        raise ValueError('coefficient overflows %d bits: %d > %d'
                         % (COEFW, np.abs(q).max(), lim))
    return q


def response(q, u):
    """Frequency response of the quantised filter, at frequencies u (x f_out)."""
    n = np.arange(len(q)) - len(q) // 2
    e = np.exp(-2j * np.pi * np.outer(u, n))
    return np.abs(e @ q) / float(1 << COEF_FRAC)


def min_dec_log2():
    """Smallest log2(decimation) this filter can keep up with.

    One multiply-accumulate per clock, NHALF of them per output sample, plus a
    few cycles for the pipeline to fill and drain. The decimation factor must
    leave at least that many clocks between input samples.
    """
    nhalf = NTAPS // 2 + 1
    need  = nhalf + 8                      # 8 = pipeline fill/drain margin
    L = 0
    while (1 << L) < need:
        L += 1
    return L


def write_params(path):
    """Emit the sizes the Verilog must agree with.

    THIS IS THE POINT OF THIS FILE. NTAPS and the coefficient scaling appear in
    the hardware, in the bypass threshold, and in the validation script. Written
    out by hand in each place they WILL drift apart, and a mismatch does not
    fail loudly - it produces a filter that runs and gives wrong answers.

    Generating them here means there is one place to change and everything else
    follows.
    """
    nhalf = NTAPS // 2 + 1
    with open(path, 'w') as f:
        f.write('// ' + '=' * 74 + '\n')
        f.write('//  Filter sizes - GENERATED FILE, DO NOT EDIT\n')
        f.write('//\n')
        f.write('//  Produced by software/validation/gen_fir_coeffs.py, which is the single\n')
        f.write('//  source of truth for these numbers. Included by red_pitaya_acq_fir.v\n')
        f.write('//  (which builds the filter) and red_pitaya_acq.v (which decides when the\n')
        f.write('//  filter is too slow for the chosen decimation and must be bypassed).\n')
        f.write('// ' + '=' * 74 + '\n\n')
        f.write('localparam integer GEN_NTAPS        = %d;\n' % NTAPS)
        f.write('localparam integer GEN_NHALF        = %d;   // unique coefficients stored\n' % nhalf)
        f.write('localparam integer GEN_COEFW        = %d;\n' % COEFW)
        f.write('localparam integer GEN_COEF_FRAC    = %d;\n' % COEF_FRAC)
        f.write('localparam integer GEN_MIN_DEC_LOG2 = %d;   // R = %d and above\n'
                % (min_dec_log2(), 1 << min_dec_log2()))


def write_verilog(q, path):
    """Emit a Verilog include file holding the unique half of the coefficients.

    Only the first half plus the centre tap are written: the filter is
    symmetric, so the hardware reuses each coefficient for the mirrored tap and
    performs 155 multiplies instead of 309.
    """
    half = NTAPS // 2
    uniq = q[:half + 1]           # taps 0 .. 154 (155 values); 155..308 mirror them

    with open(path, 'w') as f:
        f.write('// ' + '=' * 74 + '\n')
        f.write('//  Droop-correction filter coefficients - GENERATED FILE, DO NOT EDIT\n')
        f.write('//\n')
        f.write('//  Produced by software/validation/gen_fir_coeffs.py\n')
        f.write('//  Re-run that script to change the design; do not hand-edit here.\n')
        f.write('//\n')
        f.write('//  taps          : %d (symmetric, %d unique stored)\n' % (NTAPS, len(uniq)))
        f.write('//  CIC stages    : %d\n' % NSTAGE)
        f.write('//  passband      : 0 .. %.3f of the output sample rate\n' % PASSBAND)
        f.write('//  stopband from : %.3f\n' % STOPBAND)
        f.write('//  coefficients  : %d-bit signed, scaled by 2^%d\n' % (COEFW, COEF_FRAC))
        f.write('//  DC gain       : %d / 2^%d = %.6f\n' % (q.sum(), COEF_FRAC,
                                                            q.sum() / float(1 << COEF_FRAC)))
        f.write('// ' + '=' * 74 + '\n\n')
        for i, v in enumerate(uniq):
            f.write("coef[%3d] = %d'sd%d;\n" % (i, COEFW, v) if v >= 0
                    else "coef[%3d] = -%d'sd%d;\n" % (i, COEFW, -v))


if __name__ == '__main__':
    here = os.path.dirname(os.path.abspath(__file__))

    h = design()
    q = quantise(h)

    print('=' * 68)
    print(' Droop-correction filter for the acquisition system')
    print('=' * 68)
    print('  taps            : %d  (%d unique after symmetry)' % (NTAPS, NTAPS // 2 + 1))
    print('  coefficients    : %d-bit signed, scaled by 2^%d' % (COEFW, COEF_FRAC))
    print('  largest         : %d  (limit %d)' % (np.abs(q).max(), (1 << (COEFW - 1)) - 1))
    print('  DC gain         : %.8f  (want exactly 1)' % (q.sum() / float(1 << COEF_FRAC)))
    print()

    # ---- what the correction actually achieves -----------------------------
    u = np.linspace(0, 0.45, 400)
    droop = cic_droop(u)
    corr  = response(q, u)
    both  = droop * corr

    print('  %8s %12s %12s %12s' % ('u=f/f_out', 'droop [dB]', 'filter [dB]', 'combined [dB]'))
    for uu in (0.00, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30):
        d = 20 * np.log10(cic_droop(np.array([uu]))[0])
        c = 20 * np.log10(max(response(q, np.array([uu]))[0], 1e-12))
        print('  %8.2f %12.3f %12.3f %12.3f' % (uu, d, c, d + c))

    inband = u <= PASSBAND
    ripple = 20 * np.log10(both[inband].max() / both[inband].min())
    stop   = 20 * np.log10(max(corr[u >= STOPBAND].max(), 1e-12))
    print()
    print('  flatness across the corrected band : %.3f dB peak-to-peak' % ripple)
    print('  stopband rejection                 : %.1f dB' % stop)
    print('  peak boost applied                 : %.2f dB (noise is amplified by this at the band edge)'
          % (20 * np.log10(corr[inband].max())))

    # ---- is one coefficient set really good enough for every decimation? ----
    print()
    print('  Checking the large-R approximation against the exact CIC response:')
    print('  %8s %16s' % ('R', 'flatness [dB]'))
    for R in (256, 512, 1024, 2048, 4096):
        f = u * (125e6 / R)                       # real frequency
        num = np.sin(np.pi * R * f / 125e6)
        den = R * np.sin(np.pi * f / 125e6)
        exact = np.abs(np.where(den == 0, 1.0, num / np.where(den == 0, 1, den))) ** NSTAGE
        comb = exact * corr
        r = 20 * np.log10(comb[inband].max() / comb[inband].min())
        print('  %8d %16.3f' % (R, r))

    # The Verilog include file goes NEXT TO THE MODULE that includes it, so
    # Vivado finds it without needing an include-path setting. The plain-text
    # copy stays here for inspection.
    rtl = os.path.normpath(os.path.join(here, '..', '..', 'fpga'))
    vh  = os.path.join(rtl,  'fir_coeffs.vh')
    ph  = os.path.join(rtl,  'fir_params.vh')
    txt = os.path.join(rtl, 'fir_coeffs.txt')
    write_verilog(q, vh)
    write_params(ph)
    np.savetxt(txt, q, fmt='%d',
               header='droop-correction filter, %d taps, %d-bit signed, scaled by 2^%d'
                      % (NTAPS, COEFW, COEF_FRAC))
    # ---- what the hardware must be able to accommodate ---------------------
    nhalf = NTAPS // 2 + 1
    depth = 1
    while depth < NTAPS:
        depth <<= 1
    abw = 0
    while (1 << abw) < depth:
        abw += 1
    print()
    print('  HARDWARE REQUIREMENTS (checked automatically at build time):')
    print('    multiply-accumulates per output sample : %d' % nhalf)
    print('    minimum decimation factor              : %d  (DEC_LOG2 >= %d)'
          % (1 << min_dec_log2(), min_dec_log2()))
    print('    sample history DEPTH must be at least  : %d  (ABW = %d)' % (depth, abw))
    if depth > 512:
        print('    *** DEPTH exceeds the default 512 - raise DEPTH and ABW in')
        print('        red_pitaya_acq_fir.v to %d and %d ***' % (depth, abw))
    print()
    print('  wrote %s' % vh)
    print('  wrote %s' % ph)
    print('  wrote %s' % txt)
