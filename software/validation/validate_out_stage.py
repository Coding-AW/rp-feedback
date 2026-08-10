# -*- coding: utf-8 -*-
"""Prove the 2026-08-07 output-stage change is a PURE ONE-CLOCK DELAY.

Two changes went into the bitstream together on 2026-08-07:

  1. red_pitaya_resonator.v   - the saturated output is registered before it is
                                written into the delay-line buffer, to clear the
                                last -0.251 ns of setup slack.
  2. red_pitaya_phaseshift.v  - CH B, previously tied to zero, now carries a
                                monitor of either this module's input or its
                                output, left-shifted 0..7 with saturation, so an
                                external spectrum analyser can see it on OUT2.

Neither touches the recursion, so validate_resonator_pipelined.py still covers
the loop unchanged. What is NOT covered there is the output stage, because that
script's model stops at the state `u`. This script covers it.

WHAT IS CHECKED

  A. The resonator's output stream after the change equals the stream before it,
     sample for sample, shifted by exactly one clock. Checked over random
     states, over states deliberately pinned at the saturation limits, and with
     the delay-line read pointer at several settings - including the wrap.

  B. Setting DELAY one lower recovers the old total latency exactly. This is the
     claim the notebook's `delay=12` default rests on.

  C. The monitor is transparent when off: MON_SRC = 0 drives literal zero, which
     is what CH B carried before the register existed.

  D. The monitor's shift saturates rather than wrapping, and the sticky clip flag
     is set on exactly the samples that saturate. A wrap would turn a large sine
     into a sawtooth, which on a spectrum analyser is not an obviously wrong
     answer - it is a plausible-looking forest of harmonics. That is the failure
     this check exists to make impossible.

Run:  python3 validate_out_stage.py
"""
from __future__ import print_function

import numpy as np

DWI = 14
SW = 25
DLYW = 8
DEPTH = 1 << DLYW
SAT_HI = (1 << (DWI - 1)) - 1        # +8191
SAT_LO = -(1 << (DWI - 1))           # -8192
MON_HW = 7


def sat14(x):
    """The saturating narrow-to-14-bit that both modules use."""
    return SAT_HI if x > SAT_HI else (SAT_LO if x < SAT_LO else int(x))


# ===========================================================================
#  A / B - the resonator output stage, before and after
# ===========================================================================
def out_stage(u_stream, oshift, noise, set_dly, extra_reg):
    """Cycle-exact model of red_pitaya_resonator.v from `u` to `dat_o`.

    `extra_reg` False reproduces the pre-2026-08-07 file; True reproduces the
    file as it now stands. Everything else is identical between the two, which
    is the point - the diff is one flip-flop.
    """
    n = len(u_stream)
    dly_buf = [0] * DEPTH
    dly_wp = 0
    dat_o = 0
    out_sat_r = 0
    out = np.zeros(n, dtype=np.int64)

    for k in range(n):
        # --- combinational, from the current registers ---
        u_scaled = int(u_stream[k]) >> oshift          # arithmetic in Python
        out_pre = u_scaled + int(noise[k])
        out_sat = sat14(out_pre)

        # --- non-blocking assignments ---
        n_dat_o = dly_buf[(dly_wp - set_dly) & (DEPTH - 1)]
        n_buf_val = out_sat_r if extra_reg else out_sat
        n_out_sat_r = out_sat

        dly_buf[dly_wp] = n_buf_val
        dly_wp = (dly_wp + 1) & (DEPTH - 1)
        dat_o = n_dat_o
        out_sat_r = n_out_sat_r
        out[k] = dat_o
    return out


def check_output_stage():
    rng = np.random.RandomState(20260807)
    bad = 0
    ncase = 0

    for trial in range(24):
        n = 4000
        style = trial % 4
        if style == 0:                                   # random states
            u = rng.randint(-(1 << (SW - 1)), 1 << (SW - 1), n)
        elif style == 1:                                 # pinned at the rails
            u = np.where(rng.rand(n) < 0.5,
                         (1 << (SW - 1)) - 1, -(1 << (SW - 1))).astype(np.int64)
        elif style == 2:                                 # a real ring-down
            t = np.arange(n)
            u = np.round((1 << (SW - 2)) * np.exp(-t / 800.0)
                         * np.sin(2 * np.pi * 0.32 * t)).astype(np.int64)
        else:                                            # small, near zero
            u = rng.randint(-64, 65, n).astype(np.int64)

        oshift = int(rng.randint(0, 16))
        noise = (rng.randint(-(1 << 16), 1 << 16, n)
                 if trial % 3 == 0 else np.zeros(n, dtype=np.int64))

        for set_dly in (1, 2, 12, 13, 15, 200, 255):
            ncase += 1
            old = out_stage(u, oshift, noise, set_dly, extra_reg=False)
            new = out_stage(u, oshift, noise, set_dly, extra_reg=True)

            #  A: same stream, one clock later
            if not np.array_equal(old[:-1], new[1:]):
                bad += 1
                print('    MISMATCH (A) trial %d oshift %d dly %d'
                      % (trial, oshift, set_dly))

            #  B: DELAY one lower recovers the old total latency exactly
            if set_dly >= 2:
                comp = out_stage(u, oshift, noise, set_dly - 1, extra_reg=True)
                if not np.array_equal(old, comp):
                    bad += 1
                    print('    MISMATCH (B) trial %d oshift %d dly %d'
                          % (trial, oshift, set_dly))
    return bad, ncase


# ===========================================================================
#  C / D - the OUT2 monitor
# ===========================================================================
def monitor(src_stream, out_stream, mon_src, mon_shf):
    """Cycle-exact model of the new block in red_pitaya_phaseshift.v.

    Returns (dat_b_o stream, sticky clip flag). Two pipeline stages, matching
    the RTL: select, then shift-and-saturate.
    """
    n = len(src_stream)
    mon_sel = 0
    mon_r = 0
    clip = False
    out = np.zeros(n, dtype=np.int64)

    for k in range(n):
        mon_shd = mon_sel << mon_shf              # mon_sel is already signed
        if mon_src != 0 and (mon_shd > SAT_HI or mon_shd < SAT_LO):
            clip = True
        n_mon_r = sat14(mon_shd)
        if mon_src == 1:
            n_mon_sel = int(src_stream[k])
        elif mon_src == 2:
            n_mon_sel = int(out_stream[k])
        else:
            n_mon_sel = 0
        mon_r, mon_sel = n_mon_r, n_mon_sel
        out[k] = mon_r
    return out, clip


def check_monitor():
    rng = np.random.RandomState(11)
    bad = 0
    n = 3000
    a = rng.randint(SAT_LO, SAT_HI + 1, n).astype(np.int64)
    b = rng.randint(SAT_LO, SAT_HI + 1, n).astype(np.int64)

    #  C: off means zero, for every shift setting. This is the check that says
    #     an unwritten register leaves the board exactly as it was.
    for shf in range(8):
        y, clip = monitor(a, b, 0, shf)
        if y.any() or clip:
            bad += 1
            print('    MISMATCH (C) monitor not silent at shift %d' % shf)

    #  C: shift 0 is a straight copy. `out[k]` is the register value AFTER edge
    #     k, the same convention validate_resonator_pipelined.py uses, so the
    #     two pipeline stages show as an offset of one here.
    for src, stream in ((1, a), (2, b)):
        y, clip = monitor(a, b, src, 0)
        if not np.array_equal(y[1:], stream[:-1]):
            bad += 1
            print('    MISMATCH (C) src %d is not a copy at shift 0' % src)
        if clip:
            bad += 1
            print('    MISMATCH (C) src %d clipped at shift 0' % src)

    #  D: saturation, not wrap - and the flag agrees with the samples.
    for shf in range(8):
        y, clip = monitor(a, b, 1, shf)
        want = np.array([sat14(int(v) << shf) for v in a[:-1]])
        if not np.array_equal(y[1:], want):
            bad += 1
            print('    MISMATCH (D) shift %d does not match saturating model' % shf)
        shifted = a.astype(np.int64) << shf
        want_clip = bool(np.any(shifted > SAT_HI) or np.any(shifted < SAT_LO))
        if clip != want_clip:
            bad += 1
            print('    MISMATCH (D) clip flag wrong at shift %d' % shf)

    #  D: a small signal must survive the largest shift untouched. This is the
    #     case the monitor exists for - a ring-down 40 dB down.
    small = rng.randint(-63, 64, n).astype(np.int64)
    y, clip = monitor(small, small, 1, 7)
    if clip or not np.array_equal(y[1:], small[:-1] * 128):
        bad += 1
        print('    MISMATCH (D) a 6-bit signal did not survive shift 7')

    #  D: the shifted word can never overflow the internal width BEFORE the
    #     saturator sees it - that is what MON_HW buys. Signed ranges are not
    #     symmetric, so the two rails are checked separately: the negative rail
    #     shifted by 7 lands on exactly -2^20, the most negative value a signed
    #     21-bit word holds, and one bit fewer would have wrapped it to zero.
    lo = SAT_LO << 7
    hi = SAT_HI << 7
    if lo < -(1 << (DWI + MON_HW - 1)) or hi > (1 << (DWI + MON_HW - 1)) - 1:
        bad += 1
        print('    MISMATCH (D) MON_HW = %d is too small for a shift of 7' % MON_HW)
    return bad


# ===========================================================================
if __name__ == '__main__':
    print('=' * 70)
    print('validate_out_stage.py - the 2026-08-07 output-stage and OUT2 changes')
    print('=' * 70)

    print('\nA/B  resonator output stage: pure one-clock delay, DELAY-1 recovers it')
    bad_a, ncase = check_output_stage()
    print('     %d cases, %d mismatches' % (ncase, bad_a))

    print('\nC/D  OUT2 monitor: silent when off, saturating when loud')
    bad_c = check_monitor()
    print('     %d mismatches' % bad_c)

    total = bad_a + bad_c
    print('\n' + '=' * 70)
    if total:
        print('FAIL - %d mismatches. Do NOT build.' % total)
        raise SystemExit(1)
    print('PASS - the resonator output moves by exactly one clock and nothing')
    print('       else; DELAY = 12 reproduces what DELAY = 13 used to give; the')
    print('       monitor is bit-for-bit silent until it is turned on.')
    raise SystemExit(0)
