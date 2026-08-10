#!/usr/bin/env python3
"""
Can the resonator's recursion be pipelined without changing what it emulates?

THE PROBLEM, FROM THE 2026-08-07 ROUTED REPORT
----------------------------------------------
    Slack (VIOLATED) : -3.482ns
    Source           : i_reso/v_reg[2]/C     Destination: i_reso/v_reg[15]/R
    Data Path Delay  : 10.865ns   Logic Levels: 11 (CARRY4=7 DSP48E1=2 LUT1=1 LUT5=1)

        FDRE C->Q                       0.518
        route to DSP A                  0.692
        DSP48E1  A[2] -> PCOUT[47]      4.036     <-- multiply + ALU
        cascade net                     0.002
        DSP48E1  PCIN[47] -> P[16]      1.518     <-- second ALU
        route                           0.961
        LUT1                            0.124     <-- carry-in from P[16]
        CARRY4 x 7                      1.234     <-- ROUND propagating to bit 42
        route + setup                  ~1.780
                                      -------
                                       10.865   against 7.907 available

Two separate things are wrong, and only one of them is fixable by rearranging
logic:

  1. The `+ ROUND` for v is done in FABRIC after the DSP cascade, as a +1 at bit
     16 whose carry then propagates through 26 bits - the seven CARRY4 levels.
     Worth about 1.4 ns.

  2. Two cascaded DSP48E1s in one clock cost 4.036 + 1.518 = 5.554 ns on their
     own. Add the flip-flop's 0.518, the 0.692 route into the first DSP, and the
     route and setup at the far end, and the floor is about 8.3 ns against 7.9 ns
     available. A rotation needs two products summed, so two DSP stages is the
     minimum depth. THE SINGLE-CLOCK RECURSION CANNOT CLOSE ON THIS DEVICE,
     however the fabric around it is arranged.

THE FIX: TWO-WAY LOOK-AHEAD (polyphase decomposition)
-----------------------------------------------------
You cannot put a register inside a recursive loop - but you can compute two
samples per update and absorb the extra clock into the coefficients.

    x[n+1] = M x[n] + b[n]          M = (1/2^S) [[c, -s], [s, c]] = r Rot(w0)
    x[n+2] = M^2 x[n] + M b[n] + b[n+1]

and because M is a scaled rotation, M^2 = r^2 Rot(2 w0) - so the squared
coefficients are computed in software exactly the way c and s already are:

    c2 = r^2 cos(2 w0) 2^S          s2 = r^2 sin(2 w0) 2^S

Hold two interleaved state banks, even and odd, each updated on alternate
clocks. Each update then has TWO clocks - 16 ns - for the same ~8.3 ns of logic.

    u[n+2] = (c2 u[n] - s2 v[n] + c d[n] + (d[n+1] << S) + ROUND) >> S
    v[n+2] = (s2 u[n] + c2 v[n] + s d[n]                + ROUND) >> S

Every term after the two products depends only on REGISTERED INPUTS, so it is
outside the loop and can be pipelined freely - presented to the adder as one
vector, exactly the way drive_round already is. The loop keeps its two DSPs and
gains 8 ns.

WHAT THIS SCRIPT CHECKS
-----------------------
The pipelined form is NOT bit-identical to the single-clock one - c2 and s2 are
quantised separately, and the rounding happens once per two samples instead of
twice. So bit-equality is the wrong test. What has to be true instead:

  * it is still a clean resonance, at the frequency and Q that were asked for
  * the f0 and Q recovered from (c2, s2) - which is what Emulator.config()
    would report and what the Step 1 self-test compares against - match what
    the hardware would actually produce, inside the self-test's own tolerances
    (0.20 linewidths on centre, 5% on Q)
  * it behaves the same under drive and under saturation

    python3 validate_resonator_pipelined.py

Nothing here talks to hardware. It is arithmetic and a Fourier transform.
"""
from __future__ import print_function
import math
import sys

import numpy as np

# ---- the widths in the RTL -------------------------------------------------
SW    = 25
CW    = 18
SHIFT = CW - 1          # 17
FS    = 125e6
SAT_HI = (1 << (SW - 1)) - 1
SAT_LO = -(1 << (SW - 1))

# self-test tolerances, from the notebook's configuration cell
TOL_F_LINEWIDTHS = 0.20
TOL_Q_FRACTION   = 0.05


def sgn(value, bits):
    value &= (1 << bits) - 1
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def sat(nxt):
    """Top-two-bits overflow test and clamp, as in the RTL."""
    over = ((nxt >> SW) & 1) ^ ((nxt >> (SW - 1)) & 1)
    if over:
        return (SAT_LO if (nxt >> SW) & 1 else SAT_HI), True
    return sgn(nxt, SW), False


def coeffs(f0, q):
    """c and s exactly as Emulator.config() computes them."""
    w0 = 2.0 * math.pi * f0 / FS
    r = 1.0 - math.pi * (f0 / FS) / q
    return (int(round(r * math.cos(w0) * (1 << SHIFT))),
            int(round(r * math.sin(w0) * (1 << SHIFT))))


def coeffs2(f0, q):
    """c2 and s2 for the pipelined form: M^2 = r^2 Rot(2 w0)."""
    w0 = 2.0 * math.pi * f0 / FS
    r = 1.0 - math.pi * (f0 / FS) / q
    r2 = r * r
    return (int(round(r2 * math.cos(2.0 * w0) * (1 << SHIFT))),
            int(round(r2 * math.sin(2.0 * w0) * (1 << SHIFT))))


def pole_from_c2s2(c2, s2, f0_hint):
    """What Emulator.config() would report from the SQUARED coefficients.

    atan2 recovers 2*w0 modulo 2*pi, and 2*w0 exceeds pi for anything above
    31.25 MHz, so the branch is resolved with the frequency software asked for -
    which software always knows, because it computed the coefficients."""
    r2 = math.hypot(c2, s2) / float(1 << SHIFT)
    two_w0 = math.atan2(s2, c2)
    w0_hint = 2.0 * math.pi * f0_hint / FS
    # lift atan2's principal value onto the branch nearest 2*w0_hint
    k = round((2.0 * w0_hint - two_w0) / (2.0 * math.pi))
    two_w0 += 2.0 * math.pi * k
    w0 = two_w0 / 2.0
    r = math.sqrt(r2)
    f0 = w0 / (2.0 * math.pi) * FS
    q = math.pi * (f0 / FS) / (1.0 - r)
    return f0, q


# ===========================================================================
#  Model A - the single-clock recursion, as built today
# ===========================================================================
def run_single(c, s, drive, nsamp):
    u = v = 0
    clipped = False
    out = np.empty(nsamp, dtype=np.float64)
    for n in range(nsamp):
        d = drive[n]
        drive_round = (d << SHIFT) + (1 << (SHIFT - 1))
        u_acc = sgn(c * u - s * v + drive_round, SW + CW + 1)
        v_acc = sgn(s * u + c * v + (1 << (SHIFT - 1)), SW + CW)
        un = sgn(u_acc >> SHIFT, SW + 1)
        vn = sgn(v_acc >> SHIFT, SW + 1)
        u, cu = sat(un)
        v, cv = sat(vn)
        clipped = clipped or cu or cv
        out[n] = u
    return out, clipped


# ===========================================================================
#  Model B - a CYCLE-EXACT model of the RTL as written
# ===========================================================================
#  This mirrors red_pitaya_resonator.v register for register and clock for
#  clock, including the drive pipeline and the bank schedule. The point is to
#  test the SCHEDULE, not just the algebra: a bank alignment or drive pairing
#  that is one clock out still produces a resonance, just not the right one,
#  and it would show here as a shifted centre or a large image.
#
#      drive_r <- dat_i                          (already in the module)
#      cd_r    <- c*drive_r ;  sd_r <- s*drive_r
#      add_u   <- cd_r + {drive_r, 1'b1, 0...} ; add_v <- sd_r + ROUND
#      ph==0:  accA <- c2*uA - s2*vA  (stage 1, bank A)
#      ph==1:  accB <- c2*uB - s2*vB  (stage 1, bank B)
#      ph==1:  uA   <- clamp((accA + add_u) >>> SHIFT)   (stage 2, bank A)
#      ph==0:  uB   <- clamp((accB + add_u) >>> SHIFT)   (stage 2, bank B)
#      u       <- ph ? uA : uB                            (whichever wrote last)
def run_rtl(c, s_, c2, s2, drive, nsamp):
    rnd = 1 << (SHIFT - 1)
    drive_r = cd_r = sd_r = 0
    add_u = add_v = 0
    accA_u = accA_v = accB_u = accB_v = 0
    ph = 0
    uA = vA = uB = vB = 0
    u = v = 0
    clipped = False
    out = np.empty(nsamp, dtype=np.float64)

    for n in range(nsamp):
        #  ---- combinational, from the CURRENT register values ----
        sumA_u = accA_u + add_u
        sumA_v = accA_v + add_v
        sumB_u = accB_u + add_u
        sumB_v = accB_v + add_v
        uA_nxt = sgn(sumA_u >> SHIFT, SW + 1)
        vA_nxt = sgn(sumA_v >> SHIFT, SW + 1)
        uB_nxt = sgn(sumB_u >> SHIFT, SW + 1)
        vB_nxt = sgn(sumB_v >> SHIFT, SW + 1)

        #  ---- everything below is a non-blocking assignment ----
        n_drive_r = int(drive[n])
        n_cd_r    = c  * drive_r
        n_sd_r    = s_ * drive_r
        n_add_u   = sgn(cd_r + (drive_r << SHIFT) + rnd, SW + CW + 1)
        n_add_v   = sgn(sd_r + rnd, SW + CW + 1)

        n_accA_u, n_accA_v = accA_u, accA_v
        n_accB_u, n_accB_v = accB_u, accB_v
        if ph == 0:
            n_accA_u = sgn(c2 * uA - s2 * vA, SW + CW + 1)
            n_accA_v = sgn(s2 * uA + c2 * vA, SW + CW + 1)
        else:
            n_accB_u = sgn(c2 * uB - s2 * vB, SW + CW + 1)
            n_accB_v = sgn(s2 * uB + c2 * vB, SW + CW + 1)

        n_u = uA if ph else uB
        n_v = vA if ph else vB
        n_uA, n_vA, n_uB, n_vB = uA, vA, uB, vB
        if ph == 1:
            n_uA, ca = sat(uA_nxt)
            n_vA, cb = sat(vA_nxt)
            clipped = clipped or ca or cb
        else:
            n_uB, ca = sat(uB_nxt)
            n_vB, cb = sat(vB_nxt)
            clipped = clipped or ca or cb

        drive_r, cd_r, sd_r = n_drive_r, n_cd_r, n_sd_r
        add_u, add_v = n_add_u, n_add_v
        accA_u, accA_v, accB_u, accB_v = n_accA_u, n_accA_v, n_accB_u, n_accB_v
        uA, vA, uB, vB = n_uA, n_vA, n_uB, n_vB
        u, v = n_u, n_v
        ph = 1 - ph
        out[n] = u
    return out, clipped


run_pipelined_ideal = None      # the idealised model is gone; the RTL model is
                                # the only one worth testing against


def run_pipelined(c, s_, c2, s2, drive, nsamp):
    return run_rtl(c, s_, c2, s2, drive, nsamp)


# ===========================================================================
#  Measure what a model actually is: f0 and Q from its impulse response
# ===========================================================================
def measure(out, discard=8, order=2):
    """f0 and Q from the impulse response, by linear prediction.

    NOT by Fourier transform. A resonator of Q = 250 at 37 MHz decays in
    Q/(pi f0) = 2.15 us - 269 samples - so a 65536-point transform measures the
    WINDOW's width, not the resonator's, and reports Q ~ 4900 for every case.
    That is a real trap and it cost this script one revision.

    The impulse response of a two-pole section satisfies exactly

        y[n] = a1 y[n-1] + a2 y[n-2]

    so a least-squares fit of (a1, a2) over the part of the record that is still
    well above the quantisation floor gives the poles directly, and with them r
    and w0. Exact for a linear model, and immune to windowing.

    `order` above 2 is a check rather than a measurement: if the interleaved
    form had introduced a spurious extra pole, an order-4 fit would find one
    with non-negligible residue."""
    x = np.asarray(out, dtype=np.float64)[discard:]
    #  use the span where the ringing is still resolved: everything above a
    #  thousandth of the peak, and at least a few hundred samples
    #  2e-2 is about four decay constants - long enough to pin the pole, short
    #  enough that every sample still has hundreds of counts in it.
    peak = np.max(np.abs(x)) if len(x) else 0.0
    if peak <= 0:
        return float('nan'), float('nan')
    above = np.where(np.abs(x) > peak * 2e-2)[0]
    end = int(above[-1]) + 1 if len(above) else len(x)
    end = max(order * 8, min(end, len(x)))
    x = x[:end]
    if len(x) < order * 8:
        return float('nan'), float('nan')

    #  y[n] = sum_k a_k y[n-k]
    rows = len(x) - order
    A = np.empty((rows, order))
    for k in range(order):
        A[:, k] = x[order - 1 - k: order - 1 - k + rows]
    b = x[order:order + rows]
    a, _, _, _ = np.linalg.lstsq(A, b, rcond=None)

    roots = np.roots(np.concatenate(([1.0], -a)))
    roots = roots[np.abs(np.imag(roots)) > 1e-12]      # complex pair only
    if len(roots) == 0:
        return float('nan'), float('nan')
    z = roots[np.argmax(np.abs(roots))]                # the dominant pole
    r = float(np.abs(z))
    w0 = float(abs(np.angle(z)))
    f0 = w0 / (2.0 * math.pi) * FS
    q = math.pi * (f0 / FS) / (1.0 - r) if r < 1.0 else float('inf')
    return f0, q


def image_db(out, f0, discard=8):
    """How far below the peak is the polyphase image at fs/2 - f0?

    Two interleaved banks are the two polyphase components of one sequence. If
    their relative phase is not exactly w0 - and quantisation guarantees it is
    not - the residue appears as a mirror line at fs/2 - f0. It is inherent to
    the architecture, so the question is not whether it exists but how far down
    it is."""
    x = np.asarray(out, dtype=np.float64)[discard:]
    peak = np.max(np.abs(x))
    if peak <= 0:
        return float('nan')
    keep = np.where(np.abs(x) > peak * 2e-2)[0]
    x = x[:int(keep[-1]) + 1]
    if len(x) < 256:
        return float('nan')
    X = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    f = np.fft.rfftfreq(len(x), 1.0 / FS)
    k_main = int(np.argmin(np.abs(f - f0)))
    k_img = int(np.argmin(np.abs(f - (FS / 2.0 - f0))))
    w = max(2, len(f) // 400)
    main = np.max(X[max(0, k_main - w):k_main + w + 1])
    img = np.max(X[max(0, k_img - w):k_img + w + 1])
    return 20.0 * math.log10(main / max(img, 1e-30))


#  The emulator is only ever measured through the receiver's +-12 kHz window,
#  and the image sits many megahertz away, so it can never enter a fit. 40 dB is
#  a generous floor: it means the image carries under 0.01% of the power.
IMAGE_MIN_DB = 40.0


def impulse(nsamp, amp=6000):
    d = np.zeros(nsamp, dtype=np.int64)
    d[0] = amp
    return d


def tone(nsamp, f, amp=6000):
    n = np.arange(nsamp)
    return np.round(amp * np.sin(2.0 * math.pi * f * n / FS)).astype(np.int64)


# ===========================================================================
#  The checks
# ===========================================================================
CASES = [
    ('Step 1 self-test point', 37.0e6, 250.0),
    ('the coil',               39.94e6, 180.0),
    ('a cold, narrow line',    40.0e6, 2000.0),
    ('low in the band',        22.0e6, 300.0),
]


def check_resonance():
    print('1. is it one clean resonance, at the frequency asked for?')
    #  Q is reported here for information; whether it is RIGHT is decided in
    #  check 2, against the value software would report for it.
    print('   %-24s %10s %10s %10s %8s %8s %7s'
          % ('case', 'f0 asked', 'f0 single', 'f0 pipe', 'Q single', 'Q pipe', 'img dB'))
    bad = 0
    n = 1 << 14
    for name, f0, q in CASES:
        c, s = coeffs(f0, q)
        c2, s2 = coeffs2(f0, q)
        a, _ = run_single(c, s, impulse(n), n)
        b, _ = run_pipelined(c, s, c2, s2, impulse(n), n)
        fa, qa = measure(a)
        fb, qb = measure(b)
        lw = fb / qb if qb else float('inf')
        df = abs(fb - f0) / lw                 # against what was ASKED for
        img = image_db(b, f0)
        ok = (df < TOL_F_LINEWIDTHS) and (img > IMAGE_MIN_DB)
        bad += 0 if ok else 1
        print('   %-24s %9.3fM %9.3fM %9.3fM %8.1f %8.1f %7.1f   %s'
              % (name, f0 / 1e6, fa / 1e6, fb / 1e6, qa, qb, img,
                 'ok' if ok else ('*** image only %.1f dB down ***' % img
                                  if img <= IMAGE_MIN_DB
                                  else '*** centre off by %.3f lw ***' % df)))
    return bad


def check_reported_pole():
    """The Step 1 self-test compares against the QUANTISED pole that
    Emulator.config() reports. With the pipelined form that has to be recovered
    from c2 and s2 - so it must agree with what the model actually produces."""
    print('')
    print('2. does the pole recovered from (c2, s2) match what it produces?')
    print('   %-24s %11s %11s %9s %9s'
          % ('case', 'f0 reported', 'f0 measured', 'Q rep', 'Q meas'))
    bad = 0
    n = 1 << 14
    for name, f0, q in CASES:
        c, s = coeffs(f0, q)
        c2, s2 = coeffs2(f0, q)
        f_rep, q_rep = pole_from_c2s2(c2, s2, f0)
        b, _ = run_pipelined(c, s, c2, s2, impulse(n), n)
        f_meas, q_meas = measure(b)
        lw = f_meas / q_meas
        df = abs(f_rep - f_meas) / lw
        dq = abs(q_rep / q_meas - 1.0)
        ok = (df < TOL_F_LINEWIDTHS) and (dq < TOL_Q_FRACTION)
        bad += 0 if ok else 1
        print('   %-24s %10.4fM %10.4fM %9.1f %9.1f   %s'
              % (name, f_rep / 1e6, f_meas / 1e6, q_rep, q_meas,
                 'ok' if ok else '*** %.3f lw, %.1f%% Q ***' % (df, 100 * dq)))
    return bad


def check_driven_and_clipping():
    print('')
    print('3. driven response and saturation')
    bad = 0
    n = 1 << 15
    for name, f0, q in CASES[:2]:
        c, s = coeffs(f0, q)
        c2, s2 = coeffs2(f0, q)
        for amp, label in ((6000, 'normal drive'), (8191, 'hard drive')):
            d = tone(n, f0, amp)
            a, ca = run_single(c, s, d, n)
            b, cb = run_pipelined(c, s, c2, s2, d, n)
            #  steady-state amplitude, the quantity Step 4d's threshold uses
            aa = np.max(np.abs(a[n // 2:]))
            ab = np.max(np.abs(b[n // 2:]))
            rel = abs(ab / aa - 1.0) if aa else float('inf')
            ok = rel < 0.05 and (ca == cb)
            bad += 0 if ok else 1
            print('   %-24s %-13s amp %9.0f vs %9.0f (%+.2f%%)  clip %s/%s  %s'
                  % (name, label, aa, ab, 100 * (ab / aa - 1.0),
                     'y' if ca else 'n', 'y' if cb else 'n',
                     'ok' if ok else '*** differs ***'))
    return bad


def check_timing_budget():
    print('')
    print('4. the timing budget, from the 2026-08-07 routed report')
    terms = [('FDRE C->Q', 0.518), ('route into DSP', 0.692),
             ('DSP A->PCOUT', 4.036), ('cascade net', 0.002),
             ('DSP PCIN->P', 1.518)]
    core = sum(t[1] for t in terms)
    fabric = 0.961 + 0.124 + 1.234          # route + LUT1 + 7 CARRY4 (the ROUND)
    tail = 10.865 - core - fabric
    print('   irreducible core (flip-flop, routing, two DSP stages) : %6.3f ns'
          % core)
    print('   fabric ROUND increment, removable                     : %6.3f ns'
          % fabric)
    print('   remaining route and setup                             : %6.3f ns'
          % tail)
    print('   ' + '-' * 62)
    print('   single clock, ROUND removed : %6.3f ns against %6.3f  -> %+6.3f'
          % (core + tail, 7.907, 7.907 - (core + tail)))
    print('   two clocks                  : %6.3f ns against %6.3f  -> %+6.3f'
          % (10.865, 15.907, 15.907 - 10.865))
    print('   even with every removable gate gone, one clock does not close.')
    return 0


if __name__ == '__main__':
    print('=' * 78)
    print('  resonator: can the recursion be pipelined without changing the physics?')
    print('=' * 78)
    bad = check_resonance() + check_reported_pole() + check_driven_and_clipping()
    check_timing_budget()
    print('')
    print('=' * 78)
    if bad:
        print('  FAIL - %d check(s) outside the self-test tolerances' % bad)
    else:
        print('  PASS - the pipelined form is the same resonator, and the pole it')
        print('  reports is the pole it produces, inside the Step 1 tolerances')
        print('  (%.2f linewidths on centre, %.0f%% on Q).'
              % (TOL_F_LINEWIDTHS, 100 * TOL_Q_FRACTION))
    print('=' * 78)
    sys.exit(1 if bad else 0)
