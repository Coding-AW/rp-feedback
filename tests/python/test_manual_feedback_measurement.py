"""Run the notebook's one-setting function with synthetic IQ and mock registers."""
import ast
import contextlib
import copy
import io
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
NOTEBOOK = ROOT/'notebooks/test_noise_passive_feedback.ipynb'


def namespace():
    cells = json.loads(NOTEBOOK.read_text(encoding='utf-8'))['cells']
    ns = {}
    for cell in cells:
        if cell['cell_type'] != 'code':
            continue
        source = ''.join(cell['source'])
        role = cell['metadata'].get('electrode_feedback_role')
        if role in ('configuration', 'pure_library') or any(marker in source for marker in
                ('Standalone numerical dependencies loaded', 'def cic_power_response(',
                 'def measure_manual_feedback(')):
            with contextlib.redirect_stdout(io.StringIO()):
                exec(compile(source, str(NOTEBOOK), 'exec'), ns)
    # No Step 4 results, baseline, saved map, topology digest or accepted campaign.
    for key in ('CALIBRATION', 'LIVE_INPUT_SAFETY', 'PRE_FEEDBACK_DIAGNOSTICS'):
        ns.pop(key, None)
    return ns


def mock_system(seed=42, q0=150, noise_only=False):
    ns = namespace()
    state = dict(ci=0, cq=0, delay=0, delta=0, bypass=0, monitor=0)
    active = dict(count=0, phase=0, reference=40.9e6)
    ns['acq'] = Mock(spec=['build_id', 'r', 'w'])
    ns['acq'].build_id.return_value = int(ns['BUILD_ID_EXPECTED'], 16)
    coef_address = [0]
    ns['acq'].w.side_effect = lambda off, val: coef_address.__setitem__(0, val) if off == 0x40 else None
    ns['acq'].r.side_effect = lambda off: (coef_address[0] if off == 0x40 else
                                          ns['QUALIFIED_FIR_HALF_COUNTS'][coef_address[0]])
    ns['gen'] = Mock(spec=['r', 'assert_b_zero'])
    ns['gen'].r.side_effect = lambda off: 0xC0 if off == 0 else 0
    ns['ps'] = Mock(spec=['readback', 'assert_held', 'config_delay', 'set'])
    ns['ps'].readback.side_effect = lambda: dict(state)
    def held(expected):
        if expected != state:
            raise RuntimeError('coefficient readback mismatch')
    ns['ps'].assert_held.side_effect = held
    ns['ps'].config_delay.side_effect = lambda ref: active.update(reference=ref)
    def apply(gain, phase):
        active.update(count=int(round(gain*16384)), phase=phase)
        quant = ns['quantized_feedback_vector'](active['count'], phase, active['reference'])
        state.update(ci=quant['ci_word'], cq=quant['cq_word'])
    ns['ps'].set.side_effect = apply
    def shutdown():
        active['count'] = 0
        state.update(ci=0, cq=0, monitor=0)
    ns['full_shutdown'] = Mock(side_effect=shutdown)
    ns['sc'] = Mock(spec=['acquire', 'r'])
    ns['sc'].acquire.return_value = (30*np.sin(np.arange(4096))-10, 125e6)
    ns['sc'].r.return_value = 0
    rng = np.random.RandomState(seed)
    def capture(lo_word, decimation, n, settle, fir_mode='auto'):
        sample_rate = ns['FS_CLK']/(1 << decimation)
        centre = lo_word/2.0**32*ns['FS_CLK']
        f = centre+np.fft.fftshift(np.fft.fftfreq(n, 1/sample_rate))
        k = .20*active['count']/32*np.cos(np.deg2rad(active['phase']))
        shift = 10000*active['count']/32*np.sin(np.deg2rad(active['phase']))
        width = 40.9e6/q0*(1-k)
        power = 1e-12*np.exp(.2*(f-40.9e6)/1e6)
        if not noise_only:
            power += 1e-11/(1-k)**2/(1+4*((f-40.9e6-shift)/width)**2)
        plan = dict(centre_hz=centre, sample_rate_hz=sample_rate, decimation_log2=decimation, fir_mode=fir_mode)
        response, _ = ns['acquisition_response_power'](f, plan)
        bins = np.sqrt(power*response*sample_rate*n/2)*(rng.normal(size=n)+1j*rng.normal(size=n))
        return np.fft.ifft(np.fft.ifftshift(bins))/ns['CIC_VOLTS_PER_COUNT']
    ns['capture'] = Mock(side_effect=capture)
    return ns, active, state


class ManualFeedbackTests(unittest.TestCase):
    def tearDown(self):
        plt.close('all')

    def call(self, ns, **kwargs):
        # Legacy bracketed mode remains available, but notebook examples now
        # use explicit baseline / feedback calls with independent settings.
        kwargs.setdefault('mode', 'bracketed')
        with contextlib.redirect_stdout(io.StringIO()), patch.object(plt, 'show'):
            return ns['measure_manual_feedback'](**kwargs)

    def test_independent_windows_cache_unchanged_and_no_recapture(self):
        ns, active, state = mock_system(seed=71, q0=150)
        base = self.call(ns, mode='baseline', averages=64, samples_per_record=4096,
                         phase_reference_hz=40.9e6)
        self.assertEqual(base['status'], 'complete')
        original = copy.deepcopy(base)
        self.assertEqual(ns['capture'].call_count, 64)
        # Switch the synthetic active response to Q~10000, keeping the same
        # instrument. This isolates reuse/windows from any real loop-gain claim.
        narrow_ns, _, _ = mock_system(seed=72, q0=10000)
        ns['capture'].side_effect = narrow_ns['capture'].side_effect
        for lo in (40.9e6, 40.905e6):
            result = self.call(ns, mode='feedback', baseline_measurement=base,
                               coefficient_counts=32, averages=64, decimation_log2=10,
                               samples_per_record=4096, frequency_range_hz=(40.88e6, 40.92e6),
                               q_guess=10000, lo_hz=lo)
            self.assertEqual(result['status'], 'complete', result['warnings'])
            self.assertAlmostEqual(result['fits']['on']['q'], 10000, delta=1000)
            self.assertEqual(result['fits']['before']['q'], base['fits']['before']['q'])
            self.assertFalse(result['recovery_measured'])
            self.assertFalse(result['comparison']['unmeasured_drift_included'])
            self.assertEqual(result['controls']['phase_reference_hz'], 40.9e6)
            self.assertEqual(result['runs'][0]['fits'].keys(), {'on'})
            self.assertIn('fresh_off_health', result['runs'][0])
            self.assertEqual(active['count'], 0)
        self.assertEqual(ns['capture'].call_count, 64*3)  # one baseline + two active only
        np.testing.assert_array_equal(base['spectra']['before']['psd_v2_per_hz'],
                                      original['spectra']['before']['psd_v2_per_hz'])
        np.testing.assert_array_equal(base['fits']['before']['model'], original['fits']['before']['model'])
        self.assertEqual(base['controls'], original['controls'])

    def test_reused_multirepeat_baseline_is_not_refitted(self):
        ns, _, _ = mock_system(seed=73)
        base = self.call(ns, mode='baseline', averages=64, repeats=2, samples_per_record=4096)
        self.assertEqual(base['status'], 'complete')
        result = self.call(ns, mode='feedback', baseline_measurement=base, averages=64,
                           coefficient_counts=32, samples_per_record=4096,
                           fit_range_hz=(40.55e6, 41.25e6))
        self.assertEqual(result['fits']['before']['q'], base['fits']['before']['q'])
        np.testing.assert_array_equal(result['fits']['before']['frequency_hz'],
                                      base['fits']['before']['frequency_hz'])
        self.assertEqual(ns['capture'].call_count, 64*3)

    def test_bad_cached_baseline_and_mode_refuse(self):
        ns, _, _ = mock_system()
        base = self.call(ns, mode='baseline', averages=64, samples_per_record=4096)
        ns['ps'].set.reset_mock()
        for bad in (None, {}, dict(base, mode='feedback'), dict(base, status='review_required'),
                    dict(base, input_context=()), dict(base, filter_model_version=1)):
            with self.assertRaises(ValueError):
                self.call(ns, mode='feedback', baseline_measurement=bad, coefficient_counts=32)
        with self.assertRaises(ValueError):
            self.call(ns, mode='baseline', coefficient_counts=32)
        ns['ps'].set.assert_not_called()

    def test_cached_mode_live_guard_and_active_failure_shutdown(self):
        for fault in ('fresh_dc', 'power', 'dma', 'interrupt'):
            ns, active, _ = mock_system()
            base = self.call(ns, mode='baseline', averages=64, samples_per_record=4096)
            normal_capture = ns['capture'].side_effect
            if fault == 'fresh_dc':
                ns['sc'].acquire.return_value = (np.ones(4096)*-1500, 125e6)
            elif fault == 'power':
                ns['sc'].acquire.side_effect = lambda **kw: (
                    (400 if active['count'] else 30)*np.sin(np.arange(4096))-10, 125e6)
            else:
                def failing(*args, **kwargs):
                    if active['count']:
                        if fault == 'interrupt':
                            raise KeyboardInterrupt()
                        raise RuntimeError('DMA failure')
                    return normal_capture(*args, **kwargs)
                ns['capture'].side_effect = failing
            with self.assertRaises(KeyboardInterrupt if fault == 'interrupt' else RuntimeError):
                self.call(ns, mode='feedback', baseline_measurement=base,
                          coefficient_counts=32, averages=4)
            self.assertEqual(active['count'], 0)
            self.assertTrue(ns['LAST_MANUAL_FEEDBACK_MEASUREMENT']['shutdown_verified'])
            self.assertTrue(base['fits']['before']['accepted'])

    def test_single_public_function_and_no_file_dependencies(self):
        book = json.loads(NOTEBOOK.read_text(encoding='utf-8'))
        cell = next(c for c in book['cells'] if 'def measure_manual_feedback(' in ''.join(c['source']))
        code = ''.join(cell['source'])
        self.assertEqual(code, (ROOT/'notebooks/manual_feedback_measurement.py').read_text(encoding='utf-8'))
        tree = ast.parse(code, feature_version=(3, 5))
        self.assertEqual(len([n for n in tree.body if isinstance(n, ast.FunctionDef)]), 1)
        for bad in ('json.load', 'json.dump', 'open(', 'read_text', '_map_', 'TOPOLOGY_RECORD', 'baseline['):
            self.assertNotIn(bad, code)
        self.assertIsNone(cell['execution_count'])
        self.assertEqual(cell['outputs'], [])

    def test_full_off_on_off_fits_and_shutdown(self):
        ns, active, state = mock_system()
        result = self.call(ns, coefficient_counts=32, phase_deg=0,
                           averages=64, samples_per_record=4096)
        self.assertEqual(result['status'], 'complete', result['warnings'])
        self.assertEqual(list(result['spectra']), ['before', 'on', 'after'])
        self.assertAlmostEqual(result['fits']['before']['q'], 150, delta=12)
        self.assertAlmostEqual(result['fits']['on']['q'], 187.5, delta=15)
        self.assertAlmostEqual(result['fits']['after']['q'], 150, delta=12)
        self.assertAlmostEqual(result['runs'][0]['k_damping'], .2, delta=.05)
        self.assertTrue(result['shutdown_verified'])
        self.assertEqual(active['count'], 0)
        self.assertEqual(ns['capture'].call_count, 3*64)
        self.assertNotIn('records', result)

    def test_signed_gain_and_phase_are_explicit(self):
        ns, active, state = mock_system(seed=17)
        result = self.call(ns, gain=-32/16384, phase_deg=270,
                           averages=64, samples_per_record=4096)
        self.assertEqual(result['controls']['applied_phase_deg'], 90)
        self.assertAlmostEqual(result['runs'][0]['shift_hz'], 10000, delta=4000)
        self.assertEqual(active['count'], 0)

    def test_repeats_do_not_store_raw_records(self):
        ns, active, state = mock_system(seed=22)
        result = self.call(ns, coefficient_counts=0, averages=32, repeats=2, samples_per_record=4096)
        self.assertEqual(len(result['runs']), 2)
        self.assertEqual(result['spectra']['on']['completed_repeats'], 2)
        self.assertLess(sum(v.nbytes for r in result['spectra'].values()
                            for v in r.values() if isinstance(v, np.ndarray)), 200000)
        ns['ps'].set.assert_not_called()

    def test_noise_only_never_enables_feedback_and_still_plots(self):
        ns, active, state = mock_system(noise_only=True)
        result = self.call(ns, coefficient_counts=32, averages=32, samples_per_record=4096)
        self.assertEqual(result['status'], 'review_required')
        self.assertFalse(result['fits']['before']['accepted'])
        ns['ps'].set.assert_not_called()
        self.assertTrue(result['shutdown_verified'])
        self.assertEqual(len(plt.get_fignums()), 2)

    def test_db_plots_match_linear_psd_and_cached_native_grids(self):
        ns, _, _ = mock_system(seed=81)
        base = self.call(ns, mode='baseline', averages=32, samples_per_record=4096)
        axis = plt.gcf().axes[0]
        np.testing.assert_allclose(axis.lines[0].get_ydata(),
                                   10*np.log10(base['spectra']['before']['psd_v2_per_hz']))
        self.assertIn('dB re 1', axis.get_ylabel())
        self.assertEqual(len(plt.gcf().axes), 1)
        result = self.call(ns, mode='feedback', baseline_measurement=base,
                           coefficient_counts=16, averages=32, samples_per_record=8192)
        self.assertEqual(ns['capture'].call_count, 64)  # plots never acquire
        self.assertEqual(len(plt.gcf().axes), 2)
        overview, zoom = plt.gcf().axes
        for ax in (overview, zoom):
            np.testing.assert_array_equal(ax.lines[0].get_xdata(),
                                          base['spectra']['before']['frequency_hz']/1e6)
            np.testing.assert_allclose(ax.lines[2].get_ydata(),
                                       10*np.log10(result['spectra']['on']['psd_v2_per_hz']))
            np.testing.assert_allclose(ax.lines[3].get_ydata(),
                                       10*np.log10(result['fits']['on']['model']))

    def test_copyable_db_plot_handles_invalid_bins_without_warnings(self):
        import textwrap
        import warnings
        source = (ROOT/'notebooks/manual_feedback_measurement.py').read_text(encoding='utf-8')
        block = textwrap.dedent(source.split('# BEGIN COPYABLE DB PLOT\n')[1].split('        # END COPYABLE DB PLOT')[0])
        data = {'label': 'known PSD', 'spectra': {'before': {
            'frequency_hz': np.arange(6)+40.9e6,
            'psd_v2_per_hz': np.array([1e-12, 1e-9, 0, -1, np.nan, np.inf])}}}
        with warnings.catch_warnings(), patch.object(plt, 'show'):
            warnings.simplefilter('error')
            exec(block, {'np': np, 'plt': plt, 'result': data})
        y = plt.gcf().axes[0].lines[0].get_ydata()
        np.testing.assert_allclose(y[:2], [-120, -90])
        self.assertTrue(np.all(np.isnan(y[2:])))

    def test_high_q_narrow_band_decimation_and_shift(self):
        ns, active, state = mock_system(seed=51, q0=10000)
        result = self.call(ns, coefficient_counts=32, phase_deg=90, averages=64,
                           frequency_range_hz=(40.875e6, 40.925e6),
                           decimation_log2=10, samples_per_record=4096, q_guess=10000)
        self.assertEqual(result['status'], 'complete', result['warnings'])
        self.assertAlmostEqual(result['fits']['on']['f0_hz'], 40.91e6, delta=500)
        self.assertAlmostEqual(result['fits']['before']['q'], 10000, delta=1000)
        self.assertEqual(active['count'], 0)
        for row in result['fits'].values():
            self.assertTrue(np.all(np.abs(row['frequency_hz']-40.9e6) >
                                    2*result['controls']['bin_hz']))

    def test_bad_parameters_refuse_before_activation(self):
        for params in (dict(gain=.1, coefficient_counts=32), dict(gain=2),
                       dict(coefficient_counts=1.5), dict(gain=1e-10),
                       dict(decimation_log2=8), dict(samples_per_record=1234),
                       dict(fit_range_hz=(39e6, 40e6)), dict(max_input_vpk=2),
                       dict(averages=1024, max_active_seconds=1), dict(phase_deg=float('nan')),
                       dict(minimum_edge_coverage_linewidths=.01),
                       dict(maximum_fit_uncertainty_linewidths=1.1)):
            ns, active, state = mock_system()
            with self.assertRaises(ValueError, msg=str(params)):
                self.call(ns, **params)
            ns['ps'].set.assert_not_called()
            self.assertEqual(active['count'], 0)
            self.assertTrue(ns['LAST_MANUAL_FEEDBACK_MEASUREMENT']['shutdown_verified'])

    def test_capture_and_interruption_shutdown_when_active(self):
        for failure in (RuntimeError('injected DMA fault'), KeyboardInterrupt()):
            ns, active, state = mock_system()
            normal = ns['capture'].side_effect
            def failing_capture(*args, **kwargs):
                if active['count']:
                    raise failure
                return normal(*args, **kwargs)
            ns['capture'].side_effect = failing_capture
            with self.assertRaises(type(failure)):
                self.call(ns, coefficient_counts=32, averages=64, samples_per_record=4096)
            self.assertEqual(active['count'], 0)
            self.assertEqual(ns['LAST_MANUAL_FEEDBACK_MEASUREMENT']['status'], 'aborted')
            self.assertIn('before', ns['LAST_MANUAL_FEEDBACK_MEASUREMENT']['spectra'])

    def test_adc_dc_build_generator_and_readback_faults_shutdown(self):
        for fault in ('adc', 'dc', 'timeout', 'build', 'generator', 'readback'):
            ns, active, state = mock_system()
            if fault == 'adc':
                ns['sc'].acquire.return_value = (np.ones(4096)*8000, 125e6)
            elif fault == 'dc':
                ns['sc'].acquire.return_value = (np.ones(4096)*-1500, 125e6)
            elif fault == 'timeout':
                ns['sc'].r.return_value = 1
            elif fault == 'build':
                ns['acq'].build_id.return_value = 0
            elif fault == 'generator':
                ns['gen'].assert_b_zero.side_effect = RuntimeError('generator contamination')
            else:
                ns['ps'].assert_held.side_effect = RuntimeError('readback failed')
            with self.assertRaises(RuntimeError, msg=fault):
                self.call(ns, coefficient_counts=32, averages=4)
            self.assertEqual(active['count'], 0)


if __name__ == '__main__':
    unittest.main()
