"""High-K coil notebook: embedded helpers, fitting and OUT2 replay safety."""
import ast
import json
import time
import unittest

import numpy as np

from tests.notebook import HIGH_K

NOTEBOOK = str(HIGH_K)
NB = json.loads(HIGH_K.read_text(encoding='utf-8'))
# Indexed by position in the notebook (markdown cells included).
CELLS = [''.join(cell.get('source', [])) for cell in NB['cells']]
SOURCE = '\n'.join(CELLS)


def function_from_cell(index, name, namespace):
    tree = ast.parse(CELLS[index])
    node = next(node for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == name)
    module = ast.Module(body=[node], type_ignores=[])
    exec(compile(module, NOTEBOOK, 'exec'), namespace)
    return namespace[name]


class ManualHighKNotebookTests(unittest.TestCase):
    def test_is_standalone_and_has_labelled_lab_sequence(self):
        forbidden = ('from software.', 'import software.', 'sys.path',
                     'json.load', 'read_text(', 'BASELINE_GLOB',
                     'nbformat.read', 'runpy')
        for value in forbidden:
            self.assertNotIn(value, SOURCE)
        for step in range(8):
            self.assertIn('Step %d' % step, SOURCE)
        self.assertGreaterEqual(SOURCE.count('PUMP ON'), 7)
        self.assertGreaterEqual(SOURCE.count('PUMP OFF'), 3)

    def test_proven_helpers_and_out2_replay_invariants_are_embedded(self):
        required = ('class Bus', 'class Acq', 'class Generator',
                    'class PhaseShift', 'class Emulator', 'class Scope',
                    'def sweep(', 'def fit_lorentzian(',
                    'def half_power_width(', 'def refine_and_fit(',
                    "ps.monitor('input',shift=OUT2_MON_SHIFT)",
                    'ps.assert_held(expected)', 'gen.assert_b_zero()',
                    'ps.monitor_clipped()', 'all_off()')
        for value in required:
            self.assertIn(value, SOURCE)

    def test_robust_fit_recovers_known_q(self):
        namespace = {'np': np, 'time': time}
        exec(compile(CELLS[2], NOTEBOOK, 'exec'), namespace)
        exec(compile(CELLS[8], NOTEBOOK, 'exec'), namespace)
        fit = namespace['fit_lorentzian']
        f0, q = 39.9e6, 210.0
        lw = f0/q
        f = f0 + np.linspace(-5, 5, 201)*lw
        p = 0.08 + 2.5/(1.0+(2.0*(f-f0)/lw)**2)
        got = fit(f, p, allow_second=False)
        self.assertLess(abs(got['f0']-f0)/lw, 0.01)
        self.assertLess(abs(got['Q']/q-1.0), 0.01)
        self.assertLess(abs(namespace['half_power_width'](f, p, 0.08)/lw-1.0),
                        0.01)

    def test_pairing_and_manual_setting_math(self):
        q0, kval = 210.0, 0.4
        qp, qm = q0/(1-kval), q0/(1+kval)
        self.assertAlmostEqual((qp-qm)/(qp+qm), kval)
        namespace = {'np': np, 'K_PER_A': 1.0, 'K_REACHABLE': 0.95,
                     'FB_GAIN_MAX': 1.90, 'AMP_OUT_MAX_DBM': 0.0,
                     'AMP_P1DB_DBM': 7.9, 'K_LADDER_MIN_COUNTS': 4,
                     'EXT_PAD_DB': 8.0, 'EXT_GAIN_SAFETY_DB': 33.7}
        function_from_cell(8, 'amp_out_dbm', namespace)
        function_from_cell(8, 'amp_dac_fraction', namespace)
        setting = function_from_cell(24, 'manual_setting', namespace)
        row = setting(0.8)
        self.assertAlmostEqual(row['gain'], 0.8)
        self.assertAlmostEqual(row['amp_dbm'], 0.0, places=8)
        with self.assertRaises(ValueError):
            setting(0.96)

    def test_every_hardware_campaign_has_finally_cleanup(self):
        for index in (10, 12, 18, 24):
            self.assertIn('finally:', CELLS[index])
            self.assertIn('all_off()', CELLS[index])

    def test_mock_out2_replay_and_clip_cleanup(self):
        class Gen(object):
            def __init__(self): self.running = False
            def freq(self, value): self.frequency = value
            def amp(self, value): self.amplitude = value
            def run(self): self.running = True
            def assert_b_zero(self): return True
            def lo_word(self): return 123
        class Acq(object):
            def start(self, value): self.dec = value
            def tune_word(self, value): self.word = value
            def measure(self, value): return 10+0j
        class Ps(object):
            def __init__(self): self.monitoring = False; self.clipped = False
            def config_delay(self, value): self.frequency = value
            def monitor(self, source, shift=0): self.monitoring = source == 'input'
            def set(self, gain, phase): self.coeff = (gain, phase); return self.coeff
            def readback(self): return {'coeff': self.coeff, 'monitor': self.monitoring}
            def assert_held(self, expected):
                if self.readback() != expected: raise RuntimeError('changed')
            def monitor_clipped(self): return self.clipped
        class Scope(object):
            def peak_frac(self, value): return 0.1

        gen, acq, ps, scope = Gen(), Acq(), Ps(), Scope()
        stopped = []
        def all_off():
            gen.running = False; ps.monitoring = False; stopped.append(True)
        namespace = {'np': np, 'F0': 1000.0, 'LW': 100.0, 'Q_SWEEP': 10.0,
                     'K_PER_A': 1.0, 'K_REACHABLE': 0.95, 'FB_GAIN_MAX': 1.9,
                     'AMP_OUT_MAX_DBM': 0.0, 'AMP_P1DB_DBM': 7.9,
                     'K_LADDER_MIN_COUNTS': 4, 'OUT2_REPEATS': 1,
                     'OUT2_DWELL': 0.0, 'OUT2_MON_SHIFT': 0,
                     'LEVEL_GUARD_NSAMP': 64, 'FB_LEVEL_GUARD': 0.8,
                     'FB_NAVG': 2, 'PHI_NARROW': 30.0,
                     'SEARCH_FIT_MAX_RESID': 0.1, 'MANUAL_LOG': [],
                     'gen': gen, 'acq': acq, 'ps': ps, 'sc': scope,
                     'all_off': all_off, 'input': lambda unused: '',
                     'time': type('T', (), {'sleep': staticmethod(lambda unused: None)}),
                     'adaptive_frequency_grid': lambda *args, **kwargs: np.array([900.,1000.,1100.]),
                     'receiver_policy': lambda unused: 10,
                     'adaptive_settle': lambda *unused: 0.0,
                     '_background_on': lambda grid: np.zeros(len(grid)),
                     'fit_lorentzian': lambda *args, **kwargs:
                         {'f0':1000.,'lw':50.,'Q':20.,'resid':0.0},
                     'amp_dac_fraction': lambda unused: 0.01,
                     'amp_out_dbm': lambda unused: 0.0}
        namespace['manual_setting'] = function_from_cell(24, 'manual_setting', namespace)
        replay = function_from_cell(24, 'replay_k', namespace)
        row = replay(0.5)
        self.assertTrue(row['valid'])
        self.assertFalse(gen.running)
        self.assertFalse(ps.monitoring)
        self.assertTrue(stopped)
        ps.clipped = True
        with self.assertRaises(RuntimeError):
            replay(0.5)
        self.assertFalse(gen.running)
        self.assertFalse(ps.monitoring)


if __name__ == '__main__':
    unittest.main()
