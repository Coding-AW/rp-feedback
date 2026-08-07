# -*- coding: utf-8 -*-
"""Run the whole notebook against fakehw.py, cell by cell, and save every figure.

Usage:  python3 run_mock.py [scenario]
"""
import json, io, os, re, sys, time as _realtime, traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import fakehw

import os as _os
NB = _os.path.normpath(_os.path.join(
    _os.path.dirname(_os.path.abspath(__file__)), '..',
    'acquisition', 'Test - Resonator Coil Characterisation.ipynb'))
FIGDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'figs')

# Smaller grids and no waiting, so a full pass takes seconds. Every code path is
# still exercised; only the point counts change.
OVERRIDES = [
    (r'^N_AVG\s+= \d+', 'N_AVG          = 16'),
    (r'^GUARD_NSAMP\s+= \d+', 'GUARD_NSAMP    = 64'),
    (r'^SETTLE\s+= [\d.]+', 'SETTLE         = 0.0'),
    (r'^DRIFT_MINUTES\s+= [\d.]+', 'DRIFT_MINUTES  = 0.02'),
    (r'^DRIFT_PERIOD\s+= [\d.]+', 'DRIFT_PERIOD   = 0.1'),
    (r'^FB_NAVG\s+= \d+', 'FB_NAVG        = 16'),
    (r'^FB_MAP_PHASES\s+= \d+', 'FB_MAP_PHASES  = 8'),
    (r'^FB_MAP_GAINS\s+= \d+', 'FB_MAP_GAINS   = 4'),
    (r'^FB_MAP_NPTS\s+= \d+', 'FB_MAP_NPTS    = 11'),
    (r'^FB_MAP_NAVG\s+= \d+', 'FB_MAP_NAVG    = 12'),
    (r'^FB_MAP_SETTLE\s+= [\d.]+', 'FB_MAP_SETTLE  = 0.0'),
    (r'^DRIVE_SCAN_N\s+= \d+', 'DRIVE_SCAN_N   = 5'),
    (r'^FB_SPEC_NPTS\s+= \d+', 'FB_SPEC_NPTS   = 41'),
    (r"^FB_PHASES\s+= .*", 'FB_PHASES      = list(range(0, 360, 30))'),
]

SCENARIOS = {}
CONFIG = {}          # per-scenario edits to the notebook's configuration cell


EXPECT = {}          # 'ok' = must run to the end; 'refuse' = must stop, loudly


def _scen(name, config=(), expect='ok', **kw):
    s = fakehw.Scenario()
    s.name = name
    for k, v in kw.items():
        setattr(s, k, v)
    SCENARIOS[name] = s
    CONFIG[name] = list(config)
    EXPECT[name] = expect


# The chain as actually built
_scen('baseline')
# A cold, narrow resonator - exercises choose_dec at its ceiling
_scen('high_q', Q=1800.0, floor_frac=0.05)
# Narrow enough that a 100 kHz coarse step walks over it: the SEARCH_STEP
# halving is the only thing that finds this one
_scen('very_narrow', Q=9000.0, floor_frac=0.001)
# No amplifier, and the configuration says so - the passive path, with
# G_PASSIVE re-measured rather than remembered
_scen('no_amp_declared', amp_gain_db=0.0,
      config=[(r'^EXT_GAIN_DB\s+= [\d.]+', 'EXT_GAIN_DB    = 0.0'),
              (r'^DRIVE_FRAC\s+= [\d.]+', 'DRIVE_FRAC     = 0.30')])
# An amplifier declared but NOT fitted - must refuse, not adopt the loose ceiling
_scen('amp_declared_absent', amp_gain_db=0.0, expect='refuse')
# Coupling far weaker than declared - nothing to measure, must say so
_scen('weak_coupling', g_passive=0.0005, amp_gain_db=0.0, expect='refuse')
# A floor comparable with the peak - the fit's additive baseline must cope
_scen('big_floor', floor_frac=0.45)
# Receiver noise at the level of the signal - must refuse rather than fit noise
_scen('too_noisy', noise_counts=1.2e6, expect='refuse')
# The same noise, with the averaging raised to match: must recover
_scen('noisy_but_averaged', noise_counts=1.2e6,
      config=[(r'^N_AVG\s+= \d+', 'N_AVG          = 512'),
              (r'^FB_NAVG\s+= \d+', 'FB_NAVG        = 512')])


class FakeTime(object):
    """Real clock, no waiting."""
    time = staticmethod(_realtime.time)
    strftime = staticmethod(_realtime.strftime)
    gmtime = staticmethod(_realtime.gmtime)
    localtime = staticmethod(_realtime.localtime)

    @staticmethod
    def sleep(x):
        return None


def run(scenario='baseline', stop_on_error=True, savefigs=True):
    scen = SCENARIOS[scenario]
    nb = json.load(io.open(NB, encoding='utf-8'))
    cells = [(i, ''.join(c['source'])) for i, c in enumerate(nb['cells'])
             if c['cell_type'] == 'code']

    figdir = os.path.join(FIGDIR, scenario)
    if savefigs and not os.path.isdir(figdir):
        os.makedirs(figdir)

    g = {'__name__': '__main__'}
    installed = False
    errors = []
    nfig = 0

    for idx, text in cells:
        if 'CONFIGURATION' in text:
            for pat, rep in OVERRIDES + CONFIG.get(scenario, []):
                text = re.sub(pat, rep, text, flags=re.M)
        try:
            exec(compile(text, '<cell %d>' % idx, 'exec'), g)
        except SystemExit as exc:
            print('\n### cell %d raised SystemExit: %s' % (idx, exc))
            errors.append((idx, 'SystemExit: %s' % exc))
            break
        except Exception:
            print('\n### cell %d FAILED' % idx)
            traceback.print_exc()
            errors.append((idx, traceback.format_exc().strip().splitlines()[-1]))
            if stop_on_error:
                break
        if savefigs:
            for num in plt.get_fignums():
                nfig += 1
                plt.figure(num).savefig(
                    os.path.join(figdir, 'cell%02d_%02d.png' % (idx, nfig)),
                    dpi=90, bbox_inches='tight')
        plt.close('all')
        if not installed and 'import os, mmap' in text:
            fakehw.install(scen, g)
            g['time'] = FakeTime
            installed = True
    return errors, nfig


if __name__ == '__main__':
    which = sys.argv[1] if len(sys.argv) > 1 else 'baseline'
    if which == 'all':
        summary = []
        for name in SCENARIOS:
            print('\n' + '#' * 72)
            print('# SCENARIO: %s' % name)
            print('#' * 72)
            errs, nf = run(name, stop_on_error=True, savefigs=False)
            summary.append((name, errs))
        print('\n' + '=' * 72)
        bad = 0
        for name, errs in summary:
            want = EXPECT[name]
            got = 'refuse' if errs else 'ok'
            mark = 'PASS' if got == want else 'FAIL'
            bad += (mark == 'FAIL')
            print('%-4s %-20s expected %-6s got %-6s %s'
                  % (mark, name, want, got, errs[0][1][:90] if errs else ''))
        print('=' * 72)
        print('%d of %d scenarios behaved as expected'
              % (len(summary) - bad, len(summary)))
        sys.exit(1 if bad else 0)
    else:
        errs, nf = run(which)
        print('\n%s: %d figures saved, %s'
              % (which, nf, 'no errors' if not errs else errs))
