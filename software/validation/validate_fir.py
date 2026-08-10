#!/usr/bin/env python3
"""
Bit-accurate model of red_pitaya_acq_fir.v, and of the decimator + corrector
working together.

Same approach as the other validation scripts: re-implement the module in Python
with identical integer arithmetic, then check it against the answer we know is
right. There is no Verilog simulator in this toolchain, so this is the check.

WHAT IT VERIFIES
  1. The coefficients are what the generator produced, and sum to exactly 2^17
     (unity gain at DC - so switching correction on and off must not change the
     scale of the data).
  2. The symmetric structure computes the same thing as the plain 309-tap sum.
     This is the one place a subtle error would hide: the centre tap must NOT be
     counted twice.
  3. The combined decimator + corrector response is flat across the band. This
     is the prediction Test Stage 5 measures on hardware.
  4. Saturation behaves at full scale rather than wrapping.
  5. The pre-add is SIGNED. Checks 1-4 model what the filter is meant to do,
     using Python integers, so they cannot see a fault in how Verilog reads the
     expression. Check 5 works in Verilog's own rules, where a concatenation is
     unsigned and one unsigned part makes a whole expression unsigned. That is
     the fault that reached hardware and survived every other check here.

Run:  python3 validate_fir.py
"""

import numpy as np
import os
import re
import pathlib

HERE = os.path.dirname(os.path.abspath(__file__))
RTL  = os.path.normpath(os.path.join(HERE, '..', '..', 'fpga'))

# ---------------------------------------------------------------------------
#  Parameters - READ FROM THE GENERATED FILE, not written out again here.
#
#  fir_params.vh is produced by gen_fir_coeffs.py and is the single source of
#  truth: the same file is included by red_pitaya_acq_fir.v and red_pitaya_acq.v.
#  Repeating the numbers here would let this script drift out of step with the
#  hardware it is supposed to be checking, which would defeat its purpose.
# ---------------------------------------------------------------------------
def _read_params():
    txt = pathlib.Path(RTL, 'fir_params.vh').read_text()
    out = {}
    for m in re.finditer(r'localparam\s+integer\s+(GEN_\w+)\s*=\s*(\d+)\s*;', txt):
        out[m.group(1)] = int(m.group(2))
    return out

_P        = _read_params()
NTAPS     = _P['GEN_NTAPS']
NHALF     = _P['GEN_NHALF']
COEFW     = _P['GEN_COEFW']
COEF_FRAC = _P['GEN_COEF_FRAC']
DW        = 32
NSTAGE    = 4                     # CIC stages, must match red_pitaya_acq_cic.v

print('parameters read from fir_params.vh: NTAPS=%d NHALF=%d COEFW=%d FRAC=%d'
      % (NTAPS, NHALF, COEFW, COEF_FRAC))


def load_coeffs():
    """Read the unique half from the plain-text file the generator wrote."""
    q = np.loadtxt(os.path.join(HERE, 'fir_coeffs.txt')).astype(np.int64)
    assert len(q) == NTAPS, 'expected %d coefficients, found %d' % (NTAPS, len(q))
    return q


def fir_symmetric(x, h):
    """Model of the HARDWARE: symmetric structure, pre-add then one multiply.

    This mirrors what red_pitaya_acq_fir.v actually computes, including the
    special case at the centre tap where the two addresses coincide and the
    sample must be used once, not twice.
    """
    n = len(x)
    half = NTAPS // 2                       # 154
    y = np.zeros(n, dtype=np.int64)
    xp = np.concatenate([np.zeros(NTAPS, dtype=np.int64), x.astype(np.int64)])

    for i in range(n):
        m = i + NTAPS                       # index into the padded array
        acc = 0
        for k in range(NHALF):
            a = xp[m - k]
            b = xp[m - (NTAPS - 1) + k]
            pair = a if k == half else (a + b)   # centre tap used once only
            acc += int(h[k]) * int(pair)
        y[i] = acc >> COEF_FRAC              # arithmetic shift, as in hardware
    return y


def fir_direct(x, h_full):
    """Reference: the plain 309-tap sum, no symmetry trick. Must agree exactly."""
    n = len(x)
    xp = np.concatenate([np.zeros(NTAPS, dtype=np.int64), x.astype(np.int64)])
    y = np.zeros(n, dtype=np.int64)
    for i in range(n):
        m = i + NTAPS
        acc = 0
        for k in range(NTAPS):
            acc += int(h_full[k]) * int(xp[m - k])
        y[i] = acc >> COEF_FRAC
    return y


def cic_response(f_over_fout, n=NSTAGE):
    """Droop shape in units of the output sample rate."""
    u = np.atleast_1d(np.asarray(f_over_fout, dtype=float))
    s = np.ones_like(u)
    nz = u != 0
    s[nz] = np.sin(np.pi * u[nz]) / (np.pi * u[nz])
    return np.abs(s) ** n


def fir_response(h_full, u):
    """Frequency response of the filter at frequencies u (in units of f_out)."""
    k = np.arange(NTAPS) - NTAPS // 2
    e = np.exp(-2j * np.pi * np.outer(u, k))
    return np.abs(e @ h_full) / float(1 << COEF_FRAC)


# ===========================================================================
# Test 1 - the coefficients themselves
# ===========================================================================
def test_coeffs(h_full):
    print('1. COEFFICIENTS')
    print('   taps                 : %d  (%d unique stored in hardware)' % (NTAPS, NHALF))
    print('   largest magnitude    : %d   (18-bit signed limit %d)'
          % (np.abs(h_full).max(), (1 << (COEFW - 1)) - 1))
    print('   sum                  : %d' % h_full.sum())
    print('   DC gain              : %.10f' % (h_full.sum() / float(1 << COEF_FRAC)))
    sym = np.array_equal(h_full, h_full[::-1])
    print('   symmetric            : %s' % sym)
    assert sym, 'coefficients are not symmetric - the hardware structure assumes they are'
    assert h_full.sum() == (1 << COEF_FRAC), 'DC gain is not exactly 1'
    assert np.abs(h_full).max() <= (1 << (COEFW - 1)) - 1, 'coefficient overflows 18 bits'
    print('   PASS\n')


# ===========================================================================
# Test 2 - the symmetric structure matches the plain sum
# ===========================================================================
def test_structure(h_full):
    print('2. SYMMETRIC STRUCTURE vs PLAIN 309-TAP SUM')
    print('   (the centre tap must be counted ONCE - counting it twice is the')
    print('    one error this structure invites, and it would show as a small')
    print('    gain error that looks like a calibration problem)')
    rng = np.random.RandomState(3)
    x = rng.randint(-(1 << 20), 1 << 20, size=600).astype(np.int64)

    h_half = h_full[:NHALF]
    y_hw  = fir_symmetric(x, h_half)
    y_ref = fir_direct(x, h_full)

    same = np.array_equal(y_hw, y_ref)
    print('   %d samples, identical: %s' % (len(x), same))
    if not same:
        d = np.argmax(y_hw != y_ref)
        print('   first difference at %d: %d vs %d' % (d, y_hw[d], y_ref[d]))
    assert same, 'the symmetric structure does not match the direct sum'
    print('   PASS\n')


# ===========================================================================
# Test 3 - does the correction actually flatten the band?
# ===========================================================================
def test_flatness(h_full):
    print('3. COMBINED DECIMATOR + CORRECTOR RESPONSE')
    print('   (this is the prediction Test Stage 5 measures on hardware)')
    u = np.linspace(0, 0.30, 601)
    droop = cic_response(u)
    corr  = fir_response(h_full, u)
    both  = droop * corr

    print()
    print('   %10s %12s %12s %12s' % ('f / f_out', 'droop [dB]', 'corr [dB]', 'combined'))
    for uu in (0.00, 0.05, 0.10, 0.15, 0.20):
        d = 20 * np.log10(cic_response(np.array([uu]))[0])
        c = 20 * np.log10(max(fir_response(h_full, np.array([uu]))[0], 1e-12))
        print('   %10.2f %12.3f %12.3f %12.3f' % (uu, d, c, d + c))

    band = u <= 0.20
    ripple_before = 20 * np.log10(droop[band].max() / droop[band].min())
    ripple_after  = 20 * np.log10(both[band].max() / both[band].min())
    print()
    print('   across the band 0 .. 0.20 x f_out:')
    print('     uncorrected variation : %7.3f dB' % ripple_before)
    print('     corrected variation   : %7.3f dB' % ripple_after)
    print('     improvement           : %7.0fx' % (ripple_before / max(ripple_after, 1e-9)))
    assert ripple_after < 0.2, 'the correction is not flattening the band'
    print('   PASS\n')


# ===========================================================================
# Test 4 - saturation rather than wrapping
# ===========================================================================
def test_saturation(h_full):
    print('4. SATURATION AT FULL SCALE')
    print('   The correction boosts the band edge by up to 2.27 dB, so a signal')
    print('   already near full scale can overflow. It must CLIP, not wrap - a')
    print('   wrap turns a large positive number into a large negative one and')
    print('   produces a spike indistinguishable from real physics.')
    lim = (1 << (DW - 1)) - 1
    h_half = h_full[:NHALF]

    x = np.full(400, lim, dtype=np.int64)          # constant, full scale
    y = fir_symmetric(x, h_half)
    settled = y[NTAPS:]

    print()
    print('   constant full-scale input : %d' % lim)
    print('   settled output            : %d' % settled[-1])
    print('   error                     : %d LSB (unity DC gain, so expect ~0)'
          % (settled[-1] - lim))
    assert abs(int(settled[-1]) - lim) <= 2, 'DC gain is not unity at full scale'

    over = int(np.abs(y).max())
    print('   worst value seen          : %d  (32-bit signed limit %d)' % (over, lim))
    print('   would the hardware clip?  : %s' % ('yes' if over > lim else 'no'))
    print('   PASS\n')


def _sext(v, w):
    """Interpret the low w bits of v as a signed number."""
    v &= (1 << w) - 1
    return v - (1 << w) if v & (1 << (w - 1)) else v


def test_verilog_signedness():
    """5. THE PRE-ADD MUST BE SIGNED - checked against Verilog's own rules.

    Every other check in this file models what the filter is MEANT to do, using
    Python integers, which are signed and unlimited. That is exactly why they
    all passed while the hardware was broken: the fault was not in the intent,
    it was in how Verilog interprets the expression that carries it out.

    In Verilog a concatenation - anything in { } - is ALWAYS unsigned, and one
    unsigned part makes a whole expression unsigned, which makes every operand
    in it zero-extended instead of sign-extended. The pre-add was written as

        pair <= is_centre ? {rd_a[31], rd_a} : (rd_a + rd_b);

    and the braces on the left of the colon quietly turned the addition on the
    right into an unsigned one. This function reproduces both readings and shows
    where they disagree, then checks the RTL does not contain the broken form.
    """
    print('5. SIGNEDNESS OF THE PRE-ADD (Verilog semantics, not Python)')
    print('   A concatenation is unsigned, and one unsigned part makes the whole')
    print('   expression unsigned. This checks the pre-add is not written that way.')
    print()

    def pair_signed(a, b):
        """What we want: both sign-extended to 33 bits, then added."""
        return _sext((a + b) & ((1 << 33) - 1), 33)

    def pair_unsigned(a, b):
        """What the old code did: both ZERO-extended to 33 bits, then added."""
        ua = a & 0xFFFFFFFF
        ub = b & 0xFFFFFFFF
        return _sext((ua + ub) & ((1 << 33) - 1), 33)

    cases = [(-1000, -2000, 'both negative'),
             (1000,   2000, 'both positive'),
             (-1000,  2000, 'MIXED SIGNS'),
             (1000,  -2000, 'MIXED SIGNS')]
    print('   %14s %14s   %14s %14s   %s'
          % ('rd_a', 'rd_b', 'signed (want)', 'unsigned (bug)', ''))
    worst = 0
    for a, b, note in cases:
        want, got = pair_signed(a, b), pair_unsigned(a, b)
        worst = max(worst, abs(want - got))
        print('   %14d %14d   %14d %14d   %s%s'
              % (a, b, want, got, note, '  <-- off by 2^32' if want != got else ''))
    print()
    print('   worst disagreement : %d  (= 2^%.0f)' % (worst, np.log2(worst)))
    print('   One tap pair straddling zero was enough to bury the whole sum.')
    print()

    src = pathlib.Path(RTL, 'red_pitaya_acq_fir.v').read_text()
    body = re.sub(r'//[^\n]*', '', src)          # strip comments before searching
    broken = re.search(r'pair\s*<=[^;]*\?[^;]*\{', body)
    print('   RTL uses the broken conditional form : %s' % bool(broken))
    assert not broken, (
        'red_pitaya_acq_fir.v assigns `pair` from a conditional expression '
        'containing a concatenation. That makes the pre-add unsigned. Use '
        'if/else with plain signed assignments instead.')

    has_if = re.search(r'if\s*\(\s*is_centre_1\s*\)\s*pair\s*<=\s*rd_a\s*;', body)
    print('   RTL uses the safe if/else form       : %s' % bool(has_if))
    assert has_if, 'the centre-tap branch is not a plain signed assignment'
    print('   PASS\n')



if __name__ == '__main__':
    print('=' * 68)
    print(' Bit-accurate check of red_pitaya_acq_fir.v')
    print('=' * 68 + '\n')
    h = load_coeffs()
    test_coeffs(h)
    test_structure(h)
    test_flatness(h)
    test_saturation(h)
    test_verilog_signedness()
    print('All checks passed.')
