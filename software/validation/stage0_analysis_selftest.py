#!/usr/bin/env python3
"""
Test Stage 0 - does the analysis give the right answer?

    python3 stage0_analysis_selftest.py            # run every check
    python3 stage0_analysis_selftest.py -v         # show every row

WHY THIS EXISTS
---------------
Everything from Stage 8 upward rests on a chain of fitting and sweeping code,
and that code has repeatedly returned confident, plausible, wrong numbers:

  * a width correction silently capped at its own search limit, inflating Q
  * a noise floor absorbed into the resonance fit, inflating the linewidth by
    up to 168% on broad lines
  * a tone detector too noisy to carry the decision that rested on it
  * a stability test compared against a floor that is exactly zero on a
    digital plant, which marked all 408 points of an atlas unstable

Every one was found by feeding the real functions made-up data whose answer was
known in advance. Nothing in the repository did that on purpose - so the next
one would have been found the same way, by accident, on the board, in the
middle of a run.

verify_notebooks.py and verify_rtl.py check that the code is CONSISTENT.
This checks that it is CORRECT.

HOW IT WORKS
------------
It does not copy the analysis functions - it reads them out of the notebooks and
runs the real ones. If a notebook changes, this tests the change. If a function
is renamed or deleted, this fails loudly rather than testing a stale copy.

The plant is made of arithmetic: a resonance of known centre, width and area,
seen through the receiver's own smearing, on a noise floor you choose, with
seeded random noise so a run repeats exactly. Nothing here touches hardware, so
it runs on any machine in a couple of seconds.

WHAT PASSING MEANS
------------------
That the analysis recovers known answers across the whole range the notebooks
meet in practice - from four times too broad to forty times too narrow, and
from a negligible noise floor to one worth a third of the peak. Tolerances are
written down as numbers below, so a regression appears as a number moving
rather than as somebody's judgement.
"""

import io
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
#  This script lives in software/validation; notebooks are two levels up.
NB_DIR = os.path.normpath(os.path.join(HERE, '..', '..', 'notebooks',
                                       'acquisition'))
VERBOSE = '-v' in sys.argv or '--verbose' in sys.argv

FS_CLK = 125e6
F0     = 40.0e6
Q0     = 180.0
LW0    = F0 / Q0            # 222 kHz, the open-loop linewidth these stages use


# ===========================================================================
#  Getting the real functions out of the notebooks
# ===========================================================================
def load_from_notebook(name, wanted):
    """Execute just the named function definitions from a notebook.

    Reads the .ipynb, finds each `def <name>` and takes it to the start of the
    next top-level statement, then executes those definitions in a namespace
    holding numpy. Deliberately not an import: the functions live in notebooks,
    and copying them here would mean testing the copy.
    """
    path = os.path.join(NB_DIR, name)
    if not os.path.isfile(path):
        raise SystemExit('cannot find %s in %s - the notebooks live in '
                         'notebooks/acquisition/' % (name, NB_DIR))
    nb = json.load(io.open(path, encoding='utf-8'))
    source = '\n'.join(''.join(c['source'])
                       for c in nb['cells'] if c['cell_type'] == 'code')
    ns = {'np': np, 'FS_CLK': FS_CLK}
    lines = source.split('\n')
    for fn in wanted:
        start = None
        for i, line in enumerate(lines):
            if line.startswith('def %s(' % fn):
                start = i
                break
        if start is None:
            raise SystemExit('FAIL: %s does not define %s()' % (name, fn))
        end = start + 1
        while end < len(lines) and (lines[end].startswith((' ', '\t'))
                                    or not lines[end].strip()):
            end += 1
        exec(compile('\n'.join(lines[start:end]), '%s:%s' % (name, fn), 'exec'), ns)
    missing = [f for f in wanted if f not in ns]
    if missing:
        raise SystemExit('FAIL: could not load %s from %s' % (missing, name))
    return ns


STAGE10 = 'stage_10_feedback_atlas.ipynb'
A = load_from_notebook(STAGE10, ['_lorentz_core', 'fit_lorentz3', 'coherence',
                                 'tone_fraction', '_win_half', '_dec_for',
                                 '_model', '_deconv_lw'])


# ===========================================================================
#  The synthetic plant
# ===========================================================================
def spectrum(fs, dec, f0, lw, area, floor, rng=None, rel=0.0):
    """The power a sweep would measure: a resonance of known area, seen through
    the receiver window at this decimation, on a flat floor.

    `area` is the quantity Stage 10 turns into an effective temperature, so
    driving it directly is what makes the temperature check meaningful.
    """
    peak = area / ((np.pi / 2.0) * lw)
    p = peak * A['_model'](fs, dec, f0, lw) + floor
    if rel and rng is not None:
        p = p * (1.0 + rel * rng.standard_normal(len(fs)))
    return p


def sweep(lw_true, area_true, floor, pts=15, span_lw=2.5, rng=None, rel=0.0):
    """Reproduce the adaptive sweep's grid choice, then fit it.

    Mirrors noise_sweep's widen / zoom / accept logic so the fit is judged on
    the grid it would really be given, not a convenient one. Returns the
    deconvolved linewidth and the fitted area, or nans if the sweep would have
    refused the point.
    """
    centre, span = F0, span_lw * LW0
    for _ in range(5):
        fs = centre + np.linspace(-span, span, pts)
        spacing = fs[1] - fs[0]
        dec = A['_dec_for'](spacing)
        p = spectrum(fs, dec, F0, lw_true, area_true, floor, rng, rel)
        base = float(np.min(p))
        share = (p.max() - base) / max(float(np.sum(p - base)), 1e-300)
        contrast = p.max() / max(float(np.median(p)), 1e-300)
        if contrast < 2.0:
            span = min(span * 3.0, 8.0 * LW0)
            continue
        if share > 0.6:
            centre = float(fs[int(np.argmax(p))])
            span = max(span / 5.0, 5e2)
            continue
        try:
            fc, lw, p0, pbase = A['fit_lorentz3'](fs, p)
        except ValueError:
            centre = float(fs[int(np.argmax(p))])
            span = max(span / 5.0, 5e2)
            continue
        inside = bool(fs[0] < fc < fs[-1])
        fitc = p0 / (1.0 + (2.0 * (fs - fc) / lw) ** 2) + pbase
        resid = float(np.sqrt(np.mean(((p - fitc) / p.max()) ** 2)))
        if inside and 1.5 * spacing <= lw <= (fs[-1] - fs[0]) and resid < 0.15:
            lw_t, bracketed = A['_deconv_lw'](lw, fc, fs, dec)
            if bracketed:
                return np.nan, np.nan
            return lw_t, (np.pi / 2.0) * p0 * lw
        if inside and spacing / 5.0 < lw < 1.5 * spacing:
            centre, span = fc, max(2.0 * lw, 5e2)
        else:
            centre = float(fs[int(np.argmax(p))])
            span = max(span / 5.0, 5e2)
    return np.nan, np.nan


# ===========================================================================
#  Checks
# ===========================================================================
RESULTS = []


def record(name, ok, detail):
    RESULTS.append((name, ok, detail))
    print('  %-46s %s   %s' % (name, 'ok  ' if ok else 'FAIL', detail))


def check_width_and_area():
    """Q and effective temperature, across the range the atlas really covers.

    Q ratios from 0.25 (four times too broad) to 40 (forty times too narrow),
    with a floor worth 2% of the open-loop peak. The broad end is where an
    unsubtracted floor does its damage, because peak power falls as the square
    of the Q ratio.
    """
    print('\n1. Width and area against truth, floor = 2% of the open-loop peak')
    print('   %8s %10s %10s %10s' % ('Q/Q0', 'Q err %', 'T err %', 'verdict'))
    area_ol = (np.pi / 2.0) * LW0            # the reference area, peak 1.0
    floor = 0.02
    worst_q = worst_t = 0.0
    for qr in (0.25, 0.3, 0.5, 0.7, 1.0, 1.5, 2.0, 4.0, 8.0, 20.0, 40.0):
        lw = LW0 / qr
        lwm, area = sweep(lw, area_ol * qr, floor)
        if not np.isfinite(lwm):
            record('Q/Q0 = %.2f resolved' % qr, False, 'sweep returned nan')
            continue
        q_err = 100.0 * ((F0 / lwm) / (F0 / lw) - 1.0)
        t_err = 100.0 * ((area / area_ol) / qr - 1.0)
        worst_q = max(worst_q, abs(q_err))
        worst_t = max(worst_t, abs(t_err))
        if VERBOSE:
            print('   %8.2f %10.1f %10.1f' % (qr, q_err, t_err))
    record('worst Q error over the full range', worst_q < 12.0, '%.1f%% (limit 12%%)' % worst_q)
    record('worst area error over the full range', worst_t < 12.0, '%.1f%% (limit 12%%)' % worst_t)


def check_floor_removal():
    """The floor must be taken out, not absorbed.

    A floor worth a third of the peak is what a four-times-broadened resonance
    actually sees, because the peak falls as the square of the Q ratio. Fitting
    without removing it inflated the linewidth by 153% here.
    """
    print('\n2. A large noise floor must not inflate the width')
    worst = 0.0
    for qr, floor in ((0.25, 0.02), (0.3, 0.02), (0.5, 0.02), (1.0, 0.05)):
        lw = LW0 / qr
        lwm, _ = sweep(lw, (np.pi / 2.0) * LW0 * qr, floor)
        if not np.isfinite(lwm):
            record('floor removed at Q/Q0 = %.2f' % qr, False, 'unresolved')
            continue
        err = abs(100.0 * (lwm / lw - 1.0))
        worst = max(worst, err)
        if VERBOSE:
            print('   Q/Q0 %.2f  floor %.0f%% of peak  width err %+.1f%%'
                  % (qr, 100 * floor / (((np.pi / 2) * LW0 * qr) / ((np.pi / 2) * lw)), err))
    record('worst width error with a large floor', worst < 12.0,
           '%.1f%% (limit 12%%; was 153%% before the fix)' % worst)


def check_deconvolution_is_honest():
    """A width correction that hits its own search limit must say so.

    The correction searches between a quarter of the measured width and the
    measured width. If the true answer lies below that, the search converges on
    its own floor and returns a confidently wrong, much narrower width - which
    reads as a spectacular Q. It must report that instead.
    """
    print('\n3. The width correction refuses to guess past its own limits')
    # A well-matched geometry: the receiver window is narrower than the line,
    # so the correction is small and must NOT be flagged.
    fs = F0 + np.linspace(-2.5 * LW0, 2.5 * LW0, 15)
    dec = A['_dec_for'](fs[1] - fs[0])
    lw_t, bracketed = A['_deconv_lw'](LW0, F0, fs, dec)
    record('a well-matched case is not flagged', not bracketed,
           'width %.0f -> %.0f Hz' % (LW0, lw_t))

    # A badly-matched geometry: a wide receiver window on a narrow line. The
    # correction now wants to be far more than the 4x the search allows, so it
    # converges on its own floor. Returning that silently reads as a
    # spectacular Q; it MUST come back flagged.
    caught = []
    for bad_dec in (8, 9, 10, 11):
        lw_narrow = LW0 / 20.0
        fsn = F0 + np.linspace(-2.5 * lw_narrow, 2.5 * lw_narrow, 15)
        got, flag = A['_deconv_lw'](lw_narrow, F0, fsn, bad_dec)
        caught.append(flag)
        if VERBOSE:
            print('   window/line = %5.1f -> flagged %s'
                  % (A['_win_half'](bad_dec) / lw_narrow, flag))
    record('a saturated correction is reported, not returned', all(caught),
           '%d of %d over-smeared geometries flagged' % (sum(caught), len(caught)))
    record('the correction never exceeds its 4x limit', lw_t >= LW0 / 4.0 - 1.0,
           'floor is %.0f Hz' % (LW0 / 4.0))


def check_tone_detector():
    """How tone-like a record is: 1 for noise, 0 for a pure tone.

    Stage 12 replaces the emulator-only stability test with this, so the
    relationship it relies on has to hold: the measure equals 1 - f^2, where f
    is the fraction of the power carried by the tone.
    """
    print('\n4. The tone detector follows 1 - f^2')
    rng = np.random.default_rng(7)
    worst = 0.0
    for f in (0.0, 0.3, 0.5, 0.7, 0.9, 0.99):
        vals = []
        for _ in range(40):
            n = 2048
            noise = np.sqrt((1 - f) / 2) * (rng.standard_normal(n)
                                            + 1j * rng.standard_normal(n))
            tone = np.sqrt(f) * np.exp(2j * np.pi * 0.03 * np.arange(n))
            vals.append(A['coherence'](noise + tone))
        got = float(np.mean(vals))
        want = 1.0 - f ** 2
        worst = max(worst, abs(got - want))
        if VERBOSE:
            print('   tone fraction %.2f -> measured %.3f, expected %.3f' % (f, got, want))
    record('tone detector matches 1 - f^2', worst < 0.05,
           'worst deviation %.3f (limit 0.05)' % worst)
    back = A['tone_fraction'](A['coherence'](
        np.exp(2j * np.pi * 0.03 * np.arange(2048))))
    record('a pure tone reads as fraction 1', back > 0.99, 'read %.3f' % back)


def check_silent_plant():
    """A plant whose undriven output is exactly zero must not break anything.

    Both noise sources off means the resonator's input is exactly zero and its
    output decays to exactly zero. Any analysis that divides by a measured
    floor, or compares against one, has to survive that - it is what marked a
    whole atlas unstable.
    """
    print('\n5. An exactly-zero signal is handled, not crashed on')
    z = np.zeros(512, dtype=complex)
    try:
        c = A['coherence'](z)
        ok = np.isfinite(c)
        record('tone detector on an all-zero record', ok, 'returned %.3g' % c)
    except Exception as exc:
        record('tone detector on an all-zero record', False,
               '%s: %s' % (type(exc).__name__, exc))
    try:
        A['fit_lorentz3'](F0 + np.linspace(-LW0, LW0, 15), np.zeros(15))
        record('fitting a flat record raises rather than inventing', False,
               'returned a fit for flat data')
    except (ValueError, ZeroDivisionError, FloatingPointError):
        record('fitting a flat record raises rather than inventing', True,
               'raised, as it should')
    except Exception as exc:
        record('fitting a flat record raises rather than inventing', False,
               'raised the wrong thing: %s' % type(exc).__name__)


def check_repeatability_under_noise():
    """The same measurement, many times, must land in the same place.

    Real sweeps carry a few percent of noise per point. The scatter this
    produces in Q is what every tolerance elsewhere is really competing with.
    """
    print('\n6. Scatter under realistic measurement noise')
    for qr in (0.5, 1.0, 4.0):
        rng = np.random.default_rng(11)
        got = []
        for _ in range(30):
            lw = LW0 / qr
            lwm, _ = sweep(lw, (np.pi / 2.0) * LW0 * qr, 0.02, rng=rng, rel=0.03)
            if np.isfinite(lwm):
                got.append(F0 / lwm)
        if len(got) < 25:
            record('Q/Q0 = %.1f resolved under noise' % qr, False,
                   'only %d of 30 resolved' % len(got))
            continue
        rel = float(np.std(got) / np.mean(got))
        record('Q scatter at Q/Q0 = %.1f' % qr, rel < 0.10,
               '%.1f%% over 30 runs (limit 10%%)' % (100 * rel))


def main():
    print('=' * 72)
    print(' Test Stage 0 - does the analysis give the right answer?')
    print('=' * 72)
    print(' analysis loaded from: %s' % STAGE10)
    print(' numpy %s' % np.__version__)
    check_width_and_area()
    check_floor_removal()
    check_deconvolution_is_honest()
    check_tone_detector()
    check_silent_plant()
    check_repeatability_under_noise()
    bad = [n for n, ok, _ in RESULTS if not ok]
    print()
    print('=' * 72)
    print(' %d checks, %d failed' % (len(RESULTS), len(bad)))
    for n in bad:
        print('   FAILED: %s' % n)
    print(' STAGE 0:', 'PASS' if not bad else 'FAIL')
    print('=' * 72)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
