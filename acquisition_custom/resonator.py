#!/usr/bin/env python3
"""
The digital resonator: coefficients, predictions, and a bit-exact model.

    python3 resonator.py            # design table and self-check

Imported by the Test Stage 8 notebook. Everything here is arithmetic - it never
touches the hardware, so it can be run on any machine.

WHAT THE RESONATOR IS FOR
-------------------------
The trap's detection coil is a high-Q tuned circuit, and the active feedback
system works by adding a phase-shifted copy of its own signal back into it. That
narrows the resonance at one phase and broadens it at the opposite one.

Testing that against the real coil means the cryostat, the trap, and a resonator
whose centre frequency and Q are themselves unknowns you are trying to measure.
So `red_pitaya_resonator.v` IS a resonator, built in logic, whose centre
frequency and Q you set exactly.

That gives every measurement a known answer. You ask for Q = 300; the sweep must
return 300. You double the feedback gain; the linewidth must change by twice as
much. Anything else is the instrument, not the physics - and telling those two
apart is the whole difficulty, as the rest of this project has demonstrated
repeatedly.
"""

import numpy as np

FS = 125e6          # processing clock
CW = 18             # coefficient width, signed, Q1.17
SW = 25             # state width, signed
SHIFT = CW - 1
ROUND = 1 << (SHIFT - 1)
LIM = (1 << (SW - 1)) - 1


# ---------------------------------------------------------------------------
#  Design
# ---------------------------------------------------------------------------
def design(f0, Q):
    """Coefficients for a resonator at f0 with quality factor Q.

    A pole at radius r and angle w0 has a half-power width of about (1-r)
    radians per sample, so

        Q = f0 / FWHM = pi.(f0/FS) / (1 - r)

    Returns the two integers to write, and what they will actually give -
    which is not quite what you asked for, because they are integers.
    """
    w0 = 2 * np.pi * f0 / FS
    r = 1.0 - np.pi * (f0 / FS) / Q
    if r <= 0:
        raise ValueError('Q = %g is too low for f0 = %g Hz' % (Q, f0))
    c = int(round(r * np.cos(w0) * (1 << SHIFT)))
    s = int(round(r * np.sin(w0) * (1 << SHIFT)))

    r_act = np.hypot(c, s) / (1 << SHIFT)
    w_act = np.arctan2(s, c)
    return {
        'c': c, 's': s,
        'f0_actual': w_act * FS / (2 * np.pi),
        'Q_actual': np.pi * (w_act / (2 * np.pi)) / (1 - r_act) if r_act < 1 else np.inf,
        'r_actual': r_act,
        'unstable': r_act >= 1.0,
    }


def out_shift(Q):
    """A sensible right shift from the 25-bit state to the 14-bit output.

    The resonator amplifies by about Q at its own frequency, so the state runs
    about Q times larger than the drive. Shifting by log2(Q) brings the output
    back to roughly the drive's own scale.
    """
    return int(max(0, min(15, round(np.log2(max(Q, 1))))))


def max_drive(Q, f0=40e6):
    """Largest input amplitude, in counts, before the state saturates.

    A resonator AMPLIFIES by about Q. Drive it at full scale with Q = 1000 and
    it wants to swing a thousand times full scale; the state is 25 bits and the
    input is 14, so there are 11 bits of headroom and no more. Exceed this and
    the resonance is replaced by a distorted shape that still looks vaguely
    resonant - which is why the hardware has a sticky clip flag.
    """
    gain = Q / (np.pi * f0 / FS)
    return (1 << (SW - 1)) / gain


# ---------------------------------------------------------------------------
#  Bit-exact model - the same arithmetic the logic does
# ---------------------------------------------------------------------------
def _sat(x):
    return LIM if x > LIM else (-LIM - 1 if x < -LIM - 1 else x)


def simulate(c, s, x, fb_gain=0.0, fb_phase=0.0):
    """Run the resonator over an input, exactly as the hardware would.

    Integer throughout, rounding rather than truncating - truncation biases
    every sample towards minus infinity, and in a loop with a gain approaching
    one that bias accumulates into a drift or a small self-sustaining
    oscillation that looks uncomfortably like a real resonance.

    fb_gain and fb_phase apply feedback using the resonator's OWN quadrature
    pair, which is exactly the analytic signal and needs no approximation. The
    real system synthesises the quadrature with the phase shifter instead, whose
    accuracy is a separate and already characterised matter.

    Returns (output, clipped).
    """
    u = v = 0
    out = np.empty(len(x), dtype=np.int64)
    clipped = False
    gc = int(round(fb_gain * np.cos(fb_phase) * (1 << SHIFT)))
    gs = int(round(fb_gain * np.sin(fb_phase) * (1 << SHIFT)))

    for n in range(len(x)):
        fb = ((gc * u - gs * v + ROUND) >> SHIFT) if fb_gain else 0
        nu = ((c * u - s * v + ROUND) >> SHIFT) + int(x[n]) + fb
        nv = ((s * u + c * v + ROUND) >> SHIFT)
        if not (-LIM - 1 <= nu <= LIM and -LIM - 1 <= nv <= LIM):
            clipped = True
        u, v = _sat(nu), _sat(nv)
        out[n] = u
    return out, clipped


def response(c, s, freqs, amp=200, settle=20000, measure=20000, **fb):
    """Steady-state amplitude at each frequency. Slow, but exact."""
    out = []
    for f in freqs:
        n = np.arange(settle + measure)
        x = np.round(amp * np.cos(2 * np.pi * f / FS * n)).astype(np.int64)
        y, _ = simulate(c, s, x, **fb)
        tail = y[settle:].astype(float)
        out.append(np.sqrt(2 * np.mean(tail ** 2)))
    return np.array(out)


def linewidth(freqs, amps):
    """FWHM and centre, by interpolating the half-power crossings.

    Interpolating matters. Counting grid points instead makes the width come out
    short by up to a whole grid step, which on a 41-point sweep looked like a
    consistent 11% error in Q and was briefly mistaken for one.
    """
    amps = np.asarray(amps, dtype=float)
    i = int(np.argmax(amps))
    half = amps[i] / np.sqrt(2)

    def crossing(step):
        j = i
        while 0 <= j + step < len(amps):
            if (amps[j] - half) * (amps[j + step] - half) < 0:
                t = (half - amps[j]) / (amps[j + step] - amps[j])
                return freqs[j] + t * (freqs[j + step] - freqs[j])
            j += step
        return None

    lo, hi = crossing(-1), crossing(+1)
    if lo is None or hi is None:
        return float('nan'), freqs[i], amps[i]
    return hi - lo, freqs[i], amps[i]


# ---------------------------------------------------------------------------
if __name__ == '__main__':
    F0 = 40e6
    print('=' * 72)
    print(' Digital resonator - design table at %.1f MHz on a %.0f MHz clock'
          % (F0 / 1e6, FS / 1e6))
    print('=' * 72)
    print('')
    print(' %-8s %-10s %-10s %-12s %-14s %s'
          % ('Q asked', 'c', 's', 'Q actual', 'error', 'largest drive'))
    for Q in (30, 100, 300, 1000, 3000, 10000):
        d = design(F0, Q)
        md = max_drive(Q, F0)
        note = '%.0f counts' % md + ('' if md >= 8192 else
                                     '  (%.0f%% of full scale)' % (100 * md / 8192))
        print(' %-8d %-10d %-10d %-12.1f %-14s %s'
              % (Q, d['c'], d['s'], d['Q_actual'],
                 '%+.2f%%' % (100 * (d['Q_actual'] - Q) / Q), note))

    print('')
    print(' Output shift: about log2(Q) - %s'
          % ', '.join('Q=%d->%d' % (q, out_shift(q)) for q in (30, 100, 300, 1000)))

    print('')
    print('=' * 72)
    print(' Self-check: does the bit-exact model return the Q it was given?')
    print('=' * 72)
    print(' %-10s %-14s %-12s %s' % ('Q asked', 'FWHM Hz', 'Q measured', 'error'))
    for Q in (30, 100, 300):
        d = design(F0, Q)
        span = 4 * F0 / Q
        fr = np.linspace(F0 - span, F0 + span, 121)
        a = response(d['c'], d['s'], fr, amp=2000 if Q < 300 else 200,
                     settle=int(60 * Q) + 8000, measure=8000)
        w, f0m, _ = linewidth(fr, a)
        print(' %-10d %-14.0f %-12.1f %+.2f%%'
              % (Q, w, f0m / w, 100 * (f0m / w - Q) / Q))
    print('')
    print(' Under 2% across the range. The hardware must match this, not the')
    print(' ideal formula - the model has the same rounding the logic has.')
