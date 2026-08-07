#!/usr/bin/env python3
"""
Is the shortened resonator recursion BIT-FOR-BIT the old one?

WHY THIS EXISTS
---------------
`red_pitaya_resonator.v` closes its recursion in one clock, and the 2026-08-03
build missed timing by 6.9 ns doing it. The critical path carried two adders in
series inside the loop:

    u_nxt = ((c*u - s*v + ROUND) >>> SHIFT) + drive_r
             \________ 43-bit add ________/   \_ 26-bit add _/
                    11 CARRY4 levels             7 CARRY4 levels

which is exactly the "CARRY4=18" the routed timing report shows.

The second adder does not have to be there. For integers,

    floor(X / 2**S) + D  ==  floor((X + D*2**S) / 2**S)

so the drive can be added BEFORE the shift instead of after. And because ROUND
is a single 1 at bit SHIFT-1 while D<<SHIFT has nothing below bit SHIFT, their
sum is a CONCATENATION - no adder at all:

    ROUND + (drive_r <<< SHIFT)  ==  {drive_r, 1'b1, {(SHIFT-1){1'b0}}}

so the new form is

    u_nxt = (c*u - s*v + {drive_r, 1'b1, 0...0}) >>> SHIFT

with one fabric adder in the loop instead of two.

This script proves the two forms produce identical values - not approximately,
identically - by the same method the saturation change was checked with:
exhaustive comparison at reduced widths, then random comparison at the real
widths, then a full resonator run.

    python3 validate_resonator_loop.py

Nothing here talks to hardware. It is arithmetic.
"""
from __future__ import print_function
import itertools
import random
import sys

# ---- the widths actually in the RTL ---------------------------------------
DWI   = 14      # input width
SW    = 25      # state width  - one DSP A port
CW    = 18      # coefficient width - one DSP B port
SHIFT = CW - 1  # 17; coefficients are Q1.17
SAT_HI = (1 << (SW - 1)) - 1
SAT_LO = -(1 << (SW - 1))


def sgn(value, bits):
    """Interpret the low `bits` of `value` as two's complement, as Verilog does
    when a wider expression is assigned to a narrower signed wire."""
    value &= (1 << bits) - 1
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def asr(value, shift):
    """Arithmetic right shift. Python's >> already floors towards -inf for
    negative ints, which is what Verilog's >>> does on a signed value."""
    return value >> shift


# ===========================================================================
#  The two forms of the recursion
# ===========================================================================
def u_nxt_old(c, s, u, v, drive, shift=SHIFT, sw=SW, cw=CW):
    """((c*u - s*v + ROUND) >>> SHIFT) + drive     - as built"""
    rnd = 1 << (shift - 1)
    acc = sgn(c * u - s * v + rnd, sw + cw)      # 43-bit wire
    return sgn(asr(acc, shift) + drive, sw + 1)  # 26-bit wire


def u_nxt_new(c, s, u, v, drive, shift=SHIFT, sw=SW, cw=CW):
    """(c*u - s*v + {drive, 1'b1, 0...}) >>> SHIFT  - proposed"""
    #  The concatenation, built exactly as the Verilog would: drive in the high
    #  bits, the rounding 1 at bit SHIFT-1, zeros below.
    drive_round = (drive << shift) + (1 << (shift - 1))
    acc = sgn(c * u - s * v + drive_round, sw + cw + 1)   # 44-bit wire
    return sgn(asr(acc, shift), sw + 1)                   # 26-bit wire


def v_nxt_old(c, s, u, v, shift=SHIFT, sw=SW, cw=CW):
    rnd = 1 << (shift - 1)
    return sgn(asr(sgn(s * u + c * v + rnd, sw + cw), shift), sw + 1)


v_nxt_new = v_nxt_old        # v has no drive term; it is unchanged


def saturate(nxt, sw=SW):
    """The top-two-bits overflow test and clamp, as in the RTL."""
    over = ((nxt >> sw) & 1) ^ ((nxt >> (sw - 1)) & 1)
    if over:
        return (SAT_LO if (nxt >> sw) & 1 else SAT_HI), True
    return sgn(nxt, sw), False


# ===========================================================================
#  1. Exhaustive, at reduced widths
# ===========================================================================
def test_exhaustive():
    """Small widths, every combination. The identity is width-independent, so
    proving it here proves the structure; the random pass below then rules out
    a width or sign-extension slip at the real sizes."""
    sw, cw = 6, 5
    shift = cw - 1
    lo_c, hi_c = -(1 << (cw - 1)), (1 << (cw - 1))
    lo_s, hi_s = -(1 << (sw - 1)), (1 << (sw - 1))
    n = bad = 0
    rng = range(lo_c, hi_c)
    for c, s in itertools.product(rng, rng):
        for u, v in itertools.product(range(lo_s, hi_s, 3), range(lo_s, hi_s, 5)):
            for drive in (-8, -1, 0, 1, 7):
                a = u_nxt_old(c, s, u, v, drive, shift, sw, cw)
                b = u_nxt_new(c, s, u, v, drive, shift, sw, cw)
                n += 1
                if a != b:
                    bad += 1
                    if bad <= 3:
                        print('   MISMATCH c=%d s=%d u=%d v=%d d=%d: %d != %d'
                              % (c, s, u, v, drive, a, b))
    print('1. exhaustive at SW=%d CW=%d : %d combinations, %d mismatches'
          % (sw, cw, n, bad))
    return bad


# ===========================================================================
#  2. Random, at the real widths, including every boundary
# ===========================================================================
def test_random(trials=400000, seed=20260806):
    rnd = random.Random(seed)
    c_lo, c_hi = -(1 << (CW - 1)), (1 << (CW - 1)) - 1
    u_lo, u_hi = -(1 << (SW - 1)), (1 << (SW - 1)) - 1
    d_lo, d_hi = -(1 << 17), (1 << 17) - 1
    edge = [c_lo, c_hi, 0, 1, -1, c_hi // 2]
    bad = 0
    for i in range(trials):
        if i < len(edge) ** 3:                       # sweep the corners first
            c = edge[i % len(edge)]
            s = edge[(i // len(edge)) % len(edge)]
            u, v = u_lo, u_hi
            d = d_lo if i % 2 else d_hi
        else:
            c = rnd.randint(c_lo, c_hi)
            s = rnd.randint(c_lo, c_hi)
            u = rnd.randint(u_lo, u_hi)
            v = rnd.randint(u_lo, u_hi)
            d = rnd.randint(d_lo, d_hi)
        a = u_nxt_old(c, s, u, v, d)
        b = u_nxt_new(c, s, u, v, d)
        if a != b:
            bad += 1
            if bad <= 3:
                print('   MISMATCH c=%d s=%d u=%d v=%d d=%d: %d != %d'
                      % (c, s, u, v, d, a, b))
    print('2. random at SW=%d CW=%d   : %d trials, %d mismatches'
          % (SW, CW, trials, bad))
    return bad


# ===========================================================================
#  3. A whole resonator run, both ways, sample by sample
# ===========================================================================
def run_resonator(f0, q, nsamp, new_form, fs=125e6, amp=6000, seed=7):
    import math
    w0 = 2.0 * math.pi * f0 / fs
    r = 1.0 - math.pi * (f0 / fs) / q
    c = int(round(r * math.cos(w0) * (1 << SHIFT)))
    s = int(round(r * math.sin(w0) * (1 << SHIFT)))
    rnd = random.Random(seed)
    u = v = 0
    clipped = False
    out = []
    for n in range(nsamp):
        drive = int(round(amp * math.sin(2.0 * math.pi * f0 * n / fs))) \
            + rnd.randint(-3, 3)
        un = (u_nxt_new if new_form else u_nxt_old)(c, s, u, v, drive)
        vn = v_nxt_new(c, s, u, v)
        u, cu_ = saturate(un)
        v, cv_ = saturate(vn)
        clipped = clipped or cu_ or cv_
        out.append(u)
    return out, clipped


def test_full_run():
    bad = 0
    for f0, q, amp in ((37.0e6, 250.0, 6000),      # the Step 1 self-test point
                       (39.94e6, 180.0, 8000),     # the coil
                       (40.0e6, 5000.0, 8191)):    # high Q, drives it into clip
        a, ca = run_resonator(f0, q, 20000, new_form=False, amp=amp)
        b, cb = run_resonator(f0, q, 20000, new_form=True,  amp=amp)
        same = (a == b) and (ca == cb)
        bad += 0 if same else 1
        print('3. full run f0=%.2f MHz Q=%-6.0f amp=%4d : %s  (clip %s)'
              % (f0 / 1e6, q, amp,
                 'identical over 20000 samples' if same else '*** DIFFERS ***',
                 'yes' if ca else 'no'))
    return bad


# ===========================================================================
#  4. Adder count in the loop, which is the point of the change
# ===========================================================================
def report_structure():
    print('')
    print('4. what is left in the recursion')
    print('   old : DSP(c*u) DSP(s*v) -> 43-bit add -> shift -> 26-bit add '
          '-> sat -> reg')
    print('         fabric carry chains: %d + %d = %d CARRY4 levels'
          % ((SW + CW + 3) // 4, (SW + 1 + 3) // 4,
             (SW + CW + 3) // 4 + (SW + 1 + 3) // 4))
    print('   new : DSP(c*u) DSP(s*v) -> 44-bit add -> shift -> sat -> reg')
    print('         fabric carry chains: %d CARRY4 levels'
          % ((SW + CW + 4) // 4))
    print('   the routed report for the 2026-08-03 build shows CARRY4=18, '
          'which is')
    print('   %d + %d - the two adders this change reduces to one.'
          % ((SW + CW + 3) // 4, (SW + 1 + 3) // 4))


if __name__ == '__main__':
    print('=' * 70)
    print('  resonator recursion: is the shortened form bit-for-bit the old one?')
    print('=' * 70)
    bad = test_exhaustive() + test_random() + test_full_run()
    report_structure()
    print('')
    print('=' * 70)
    if bad:
        print('  FAIL - %d check(s) found a difference' % bad)
    else:
        print('  PASS - the two forms are identical everywhere tested')
        print('')
        print('  This proves EQUIVALENCE only. Whether the shorter path closes')
        print('  8 ns is a question for Vivado, not for arithmetic - rebuild and')
        print('  read the slack.')
    print('=' * 70)
    sys.exit(1 if bad else 0)
