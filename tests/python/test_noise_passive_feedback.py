#!/usr/bin/env python3
"""Known-answer and fail-closed tests for manual electrode-feedback setup."""
import copy
import ast
import json
import os
import sys
import time
import unittest

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..'))
NOTEBOOK_PATH = os.path.join(
    ROOT, 'notebooks',
    'test_noise_passive_feedback.ipynb')


def _standalone_library():
    """Execute the notebook's own pure library, never a project module."""
    with open(NOTEBOOK_PATH, encoding='utf-8') as handle:
        notebook = json.load(handle)
    cells = [cell for cell in notebook['cells']
             if cell.get('metadata', {}).get('electrode_feedback_role') ==
             'pure_library']
    if len(cells) != 1:
        raise AssertionError('expected one standalone pure_library cell')
    namespace = {'__name__': 'standalone_electrode_feedback_test'}
    exec(compile(''.join(cells[0]['source']), NOTEBOOK_PATH, 'exec'), namespace)
    return namespace


def _standalone_hardware():
    """Execute configuration/import/definition cells with no real hardware."""
    with open(NOTEBOOK_PATH, encoding='utf-8') as handle:
        notebook = json.load(handle)
    namespace = {'__name__': 'standalone_electrode_feedback_hardware_test'}
    wanted = ('configuration', 'hardware_definition')
    for cell in notebook['cells']:
        if cell.get('cell_type') != 'code':
            continue
        role = cell.get('metadata', {}).get('electrode_feedback_role')
        source = ''.join(cell['source'])
        if role in wanted or (role == 'pure_analysis' and
                              'Standalone numerical dependencies loaded' in source):
            exec(compile(source, NOTEBOOK_PATH, 'exec'), namespace)
    return namespace


_LIB = _standalone_library()
CalibrationError = _LIB['CalibrationError']
SetupError = _LIB['SetupError']
analyser_configuration_fingerprint = _LIB['analyser_configuration_fingerprint']
detect_self_oscillation = _LIB['detect_self_oscillation']
feedback_q_setup = _LIB['feedback_q_setup']
feedback_shift_setup = _LIB['feedback_shift_setup']
fit_passive_resonator = _LIB['fit_passive_resonator']
make_calibration = _LIB['make_calibration']
paired_k = _LIB['paired_k']
passive_iq_spectrum = _LIB['passive_iq_spectrum']
plan_passive_acquisition = _LIB['plan_passive_acquisition']
validate_setup = _LIB['validate_setup']
validate_topology = _LIB['validate_topology']


def calibration(**changes):
    now = time.time()
    values = dict(
        baseline={'f0_hz': 740000.0, 'q0': 4000.0, 'linewidth_hz': 185.0},
        q_points=[
            {'gain': 0.0, 'k': 0.0, 'q': 4000.0, 'linewidth_hz': 185.0,
             'residual_shift_hz': 0.0, 'uncertainty_q': 20.0},
            {'gain': 0.2, 'k': 0.1, 'q': 4444.4, 'linewidth_hz': 166.5,
             'residual_shift_hz': 0.4, 'uncertainty_q': 30.0},
            {'gain': 0.4, 'k': 0.2, 'q': 5000.0, 'linewidth_hz': 148.0,
             'residual_shift_hz': 0.8, 'uncertainty_q': 45.0}],
        shift_points=[
            {'signed_gain': -0.4, 'signed_k': -0.2, 'shift_hz': -80.0,
             'q': 4002.0, 'residual_q_change': 2.0, 'uncertainty_hz': 3.0},
            {'signed_gain': -0.2, 'signed_k': -0.1, 'shift_hz': -40.0,
             'q': 4001.0, 'residual_q_change': 1.0, 'uncertainty_hz': 2.0},
            {'signed_gain': 0.0, 'signed_k': 0.0, 'shift_hz': 0.0,
             'q': 4000.0, 'residual_q_change': 0.0, 'uncertainty_hz': 1.0},
            {'signed_gain': 0.2, 'signed_k': 0.1, 'shift_hz': 41.0,
             'q': 4001.0, 'residual_q_change': 1.0, 'uncertainty_hz': 2.0},
            {'signed_gain': 0.4, 'signed_k': 0.2, 'shift_hz': 83.0,
             'q': 4002.0, 'residual_q_change': 2.0, 'uncertainty_hz': 3.0}],
        phases={'regenerative_deg': 330.0, 'degenerative_deg': 150.0,
                'positive_shift_deg': 60.0, 'negative_shift_deg': 240.0,
                'uncertainty_deg': 0.4},
        evidence={'noise_floor_valid': True, 'baseline_valid': True,
                  'linearity_valid': True, 'phase_valid': True,
                  'gain_linearity_valid': True, 'drift_valid': True,
                  'acquisition_valid': True, 'analyser_valid': True,
                  'output_commissioning_valid': True,
                  'effective_feedback_valid': True,
                  'out1_dc_offset_valid': True,
                  'out2_monitor_valid': True,
                  'created_epoch_s': now},
        safety={'max_k': 0.3, 'topology_digest': 'test-topology-digest',
                'return_attenuation_db_nominal': 30.0,
                'input_attenuation_db': 0.0,
                'sense_capacitance_f': 2.2e-12,
                'in1_termination_ohm': 1.0e6,
                'analyser_impedance_ohm': 50.0,
                'airgap_geometry_id': 'gap-test-A'},
        build_id='0xFE76AE09')
    values.update(changes)
    return make_calibration(**values)


class ElectrodeFeedbackTests(unittest.TestCase):
    def test_notebook_build_id_matches_fpga_header(self):
        with open(NOTEBOOK_PATH, encoding='utf-8') as handle:
            notebook_source = json.dumps(json.load(handle))
        header = os.path.join(ROOT, 'fpga', 'build_id.vh')
        with open(header, encoding='utf-8') as handle:
            header_source = handle.read()
        self.assertIn("BUILD_ID_EXPECTED = '0xFE76AE09'", notebook_source)
        self.assertIn("32'hFE76AE09", header_source)

    def test_dedicated_notebook_is_fail_closed_and_keeps_out2_as_monitor(self):
        path = os.path.join(ROOT, 'notebooks',
                            'test_noise_passive_feedback.ipynb')
        with open(path, encoding='utf-8') as handle:
            notebook = json.load(handle)
        source = '\n'.join(''.join(cell.get('source', []))
                           for cell in notebook['cells'])
        self.assertIn('# Test Noise Passive Feedback', source)
        self.assertNotIn('ELECTRODE_CHARACTERISATION_ARMED', source)
        self.assertIn('ELECTRODE_MAX_K = 0.30', source)
        self.assertIn('OUT1 -> 30 dB pad -> air-gap pin', source)
        self.assertIn("in1_termination_ohm': 1.0e6", source)
        self.assertIn('no external 50 ohm termination', source)
        self.assertIn('passive_iq_spectrum', source)
        self.assertIn("ps.monitor('input', shift=0)", source)
        self.assertIn('def full_shutdown()', source)
        self.assertIn('def disable_everything()', source)
        self.assertIn('def out2_monitor_off()', source)
        self.assertLess(source.index('def _measure_feedback_point'),
                        source.index('def calibrate_safe_probe_gain'))
        self.assertEqual(source.count('def _measure_feedback_point'), 1)
        self.assertIn('coil_voltage_directly_measured', source)
        self.assertNotIn('resonator_coil_characterisation', source)
        self.assertNotIn('from electrode_feedback', source)
        self.assertNotIn('sys.path', source)
        # The NumPy supplied on the Red Pitaya requires a numeric rcond.
        # A null value works on newer PCs but fails on the board at runtime.
        self.assertNotIn('rcond=None', source)
        self.assertGreaterEqual(source.count('rcond=-1'), 5)
        self.assertTrue(notebook['metadata']['electrode_feedback']['standalone'])
        for index, cell in enumerate(notebook['cells']):
            self.assertIn('electrode_feedback_role', cell.get('metadata', {}),
                          'cell %d has no role metadata' % index)
            if cell.get('cell_type') == 'code':
                self.assertGreater(index, 0)
                self.assertEqual(notebook['cells'][index - 1]['cell_type'],
                                 'markdown',
                                 'code cell %d lacks preceding instructions' % index)
        self.assertNotIn('second-electrode mode', source)
        for index, cell in enumerate(notebook['cells']):
            if cell.get('cell_type') == 'code':
                ast.parse(''.join(cell.get('source', [])), filename='cell-%d' % index)
                self.assertIsNone(cell.get('execution_count'))
                self.assertEqual(cell.get('outputs'), [])

    def test_q_requests_resolve_to_same_interpolation(self):
        cal = calibration()
        by_q = feedback_q_setup(cal, target_q=4444.4)
        by_ratio = feedback_q_setup(cal, q_ratio=4444.4/4000.0)
        by_k = feedback_q_setup(cal, target_k=0.1)
        by_gain = feedback_q_setup(cal, gain=0.2)
        self.assertEqual({round(x['resolved']['gain'], 6)
                          for x in (by_q, by_ratio, by_k, by_gain)}, {0.2})
        self.assertEqual(feedback_q_setup(cal)['resolved']['gain'], 0.2)

    def test_q_rejects_conflicts_and_extrapolation(self):
        cal = calibration()
        with self.assertRaises(SetupError):
            feedback_q_setup(cal, target_q=4500, gain=0.2)
        with self.assertRaises(SetupError):
            feedback_q_setup(cal, target_k=0.25)

    def test_shift_supports_all_forms_and_both_defaults(self):
        cal = calibration()
        self.assertAlmostEqual(feedback_shift_setup(cal, shift_hz=41)['resolved']['signed_gain'], 0.2)
        self.assertAlmostEqual(feedback_shift_setup(cal, shift_linewidths=-40/185.0)['resolved']['signed_gain'], -0.2)
        self.assertAlmostEqual(feedback_shift_setup(cal, signed_gain=0.3)['resolved']['shift_hz'], 62.0)
        self.assertAlmostEqual(feedback_shift_setup(cal, target_k=0.1, direction=1)['resolved']['shift_hz'], 41.0)
        defaults = feedback_shift_setup(cal)
        self.assertEqual(defaults['negative']['resolved']['signed_gain'], -0.2)
        self.assertEqual(defaults['positive']['resolved']['signed_gain'], 0.2)

    def test_shift_rejects_bad_direction_and_extrapolation(self):
        cal = calibration()
        with self.assertRaises(SetupError):
            feedback_shift_setup(cal, target_k=0.1)
        with self.assertRaises(SetupError):
            feedback_shift_setup(cal, shift_hz=1000)

    def test_shift_k_limit_is_enforced_at_calibration(self):
        base = calibration()
        points = copy.deepcopy(base['shift_points'])
        points[-1]['signed_k'] = 0.31
        with self.assertRaises(CalibrationError):
            make_calibration(base['baseline'], base['q_points'], points,
                             base['phases'], base['evidence'], base['safety'],
                             base['build_id'])

    def test_missing_noise_linearity_or_safety_evidence_fails_closed(self):
        for section, key in (('evidence', 'noise_floor_valid'),
                             ('evidence', 'linearity_valid')):
            kwargs = {}
            base = calibration()
            # Rebuild from known inputs rather than attempting to reseal a record.
            evidence = copy.deepcopy(base['evidence']); evidence.pop('created_epoch_s', None)
            evidence['created_epoch_s'] = time.time()
            safety = copy.deepcopy(base['safety'])
            (evidence if section == 'evidence' else safety)[key] = False
            with self.assertRaises(CalibrationError):
                make_calibration(base['baseline'], base['q_points'], base['shift_points'],
                                 base['phases'], evidence, safety, base['build_id'])

    def test_tampering_staleness_and_wrong_build_are_rejected(self):
        cal = calibration()
        self.assertFalse(cal['coil_voltage_directly_measured'])
        self.assertFalse(cal['airgap_transfer_directly_measured'])
        self.assertEqual(cal['effective_loop_status'],
                         'closed_loop_inference_only')
        setup = feedback_q_setup(cal, target_k=0.1)
        self.assertFalse(setup['coil_voltage_directly_measured'])
        self.assertFalse(setup['airgap_transfer_directly_measured'])
        changed = copy.deepcopy(setup); changed['resolved']['gain'] = 1.9
        with self.assertRaises(SetupError):
            validate_setup(changed, cal)
        with self.assertRaises(SetupError):
            validate_setup(setup, cal, current_build_id='wrong')
        with self.assertRaises(SetupError):
            validate_setup(setup, cal, max_age_s=60,
                           now_s=cal['evidence']['created_epoch_s'] + 61)

    def test_rejected_points_cannot_expand_envelope(self):
        cal = calibration()
        q = copy.deepcopy(cal['q_points'])
        q.append({'gain': 1.0, 'k': 0.29, 'q': 5600, 'linewidth_hz': 130,
                  'residual_shift_hz': 1, 'uncertainty_q': 90,
                  'accepted': False})
        rebuilt = make_calibration(cal['baseline'], q, cal['shift_points'],
                                   cal['phases'], cal['evidence'], cal['safety'],
                                   cal['build_id'])
        with self.assertRaises(SetupError):
            feedback_q_setup(rebuilt, gain=0.8)

    def test_topology_rejects_wrong_airgap_or_fixed_components(self):
        topology = {
            'resonance_frequency_hz': 39e6,
            'return_attenuation_db_nominal': 30.0,
            'input_attenuation_db': 0.0,
            'sense_capacitance_f': 2.2e-12,
            'voltage_follower_gain_db_nominal': -1.0,
            'zfl_model': 'ZFL-500LN+',
            'zfl_supply_v': 12.0,
            'in1_termination_ohm': 1.0e6,
            'in1_termination_location': 'NONE-NATIVE-HIGH-IMPEDANCE-IN1',
            'airgap_geometry_id': 'gap-2026-08-28-A',
            'input_cable_id': 'input-A',
            'feedback_cable_id': 'feedback-A',
        }
        self.assertIn('digest', validate_topology(topology))
        unsafe = copy.deepcopy(topology)
        unsafe['in1_termination_ohm'] = 50.0
        with self.assertRaises(CalibrationError):
            validate_topology(unsafe)
        unsafe = copy.deepcopy(topology)
        unsafe['return_attenuation_db_nominal'] = 15.0
        with self.assertRaises(CalibrationError):
            validate_topology(unsafe)

    def test_passive_fft_normalisation_and_instability_detection(self):
        import numpy as np
        rng = np.random.RandomState(4)
        records = rng.normal(size=(40, 1024)) + 1j * rng.normal(size=(40, 1024))
        spectrum = passive_iq_spectrum(records, 10000.0, 30e6)
        self.assertAlmostEqual(spectrum['bin_hz'], 10000.0 / 1024)
        self.assertEqual(spectrum['averages'], 40)
        current = spectrum['psd_v2_per_hz'].copy()
        current[100] *= 100.0
        result = detect_self_oscillation(spectrum['frequency_hz'], current,
                                         spectrum['psd_v2_per_hz'])
        self.assertTrue(result['unsafe'])

    def test_analyser_fingerprint_and_paired_k(self):
        analyser = {'model': 'SA', 'input_impedance_ohm': 50,
                    'maximum_safe_input_dbm': 20, 'reference_level_dbm': 10,
                    'attenuation_db': 10, 'preamp_state': 'off',
                    'detector': 'RMS', 'rbw_hz': 3.5, 'vbw_hz': 3.5,
                    'averages': 40, 'cable_id': 'A', 'cable_loss_db': 0.5}
        first = analyser_configuration_fingerprint(analyser)
        analyser['attenuation_db'] = 20
        self.assertNotEqual(first, analyser_configuration_fingerprint(analyser))
        self.assertAlmostEqual(paired_k(5000, 3000), 0.25)

    def test_passive_fit_recovers_39mhz_q150_over_sloping_noise(self):
        import numpy as np
        frequency = np.linspace(37.5e6, 40.5e6, 3001)
        linewidth = 39e6 / 150.0
        slope = 0.15 * (frequency - 39e6) / (frequency[-1] - frequency[0])
        peak = 4.0 / (1.0 + 4.0 * ((frequency - 39e6) / linewidth) ** 2)
        rng = np.random.RandomState(31)
        psd = 1.0 + slope + peak + rng.normal(scale=0.01, size=frequency.size)
        fit = fit_passive_resonator(frequency, psd)
        self.assertTrue(fit['accepted'])
        self.assertAlmostEqual(fit['f0_hz'], 39e6, delta=3000.0)
        self.assertAlmostEqual(fit['q'], 150.0, delta=5.0)
        self.assertEqual(fit['resonator_state'], 'passive_noise')

    def test_acquisition_plan_adapts_from_q100_to_high_q_and_shift(self):
        discovery = plan_passive_acquisition(
            39e6, 150, 0.0, min_decimation_log2=6,
            bins_per_linewidth=20, linewidths_each_side=3.0)
        broad = plan_passive_acquisition(40e6, 100,
                                         linewidths_each_side=1.5)
        narrow = plan_passive_acquisition(40e6, 10000,
                                          linewidths_each_side=1.5)
        shifted = plan_passive_acquisition(
            40e6, 50000, 120e3, linewidths_each_side=1.5,
            centre_on_expected_shift=True)
        self.assertGreaterEqual(discovery['usable_span_hz'], 1.56e6)
        self.assertEqual(discovery['decimation_log2'], 6)
        self.assertEqual(discovery['fir_expected_state'], 'bypassed')
        with self.assertRaisesRegex(CalibrationError,
                                    'qualified FPGA register range'):
            plan_passive_acquisition(39e6, 150, min_decimation_log2=4)
        self.assertGreaterEqual(broad['usable_span_hz'], 3 * 400e3)
        self.assertGreaterEqual(narrow['bins_per_linewidth'], 20)
        self.assertLess(narrow['sample_rate_hz'], broad['sample_rate_hz'])
        self.assertLess(narrow['bin_hz'], broad['bin_hz'])
        self.assertEqual(shifted['centre_hz'], 40.12e6)
        self.assertGreaterEqual(shifted['bins_per_linewidth'], 20)

    def test_mock_register_transport_and_capture_use_notebook_definitions(self):
        import numpy as np
        hardware = _standalone_hardware()
        hardware['TRANSPORT_FACTORY'] = hardware['MemoryTransport']
        acquisition = hardware['Acq']()
        generator = hardware['Generator']()
        phase = hardware['PhaseShift']()
        self.assertTrue(hardware['shutdown_devices'](generator, phase,
                                                     acquisition))
        self.assertEqual((phase.readback()['ci'], phase.readback()['cq']),
                         (0, 0))
        hardware['CAPTURE_BACKEND'] = lambda lo, dec, n, settle: np.arange(n) + 0j
        captured = hardware['capture'](123, 8, 32, settle=0)
        self.assertEqual(len(captured), 32)

    def test_official_red_pitaya_limits_and_low_to_high_probe_order(self):
        hardware = _standalone_hardware()
        limits = hardware['RP_LIMITS']
        self.assertEqual(limits['adc_bits'], 14)
        self.assertEqual(limits['sample_rate_hz'], 125e6)
        self.assertEqual(limits['input_impedance_ohm'], 1e6)
        self.assertEqual(limits['input_lv_full_scale_vpk'], 1.0)
        self.assertEqual(limits['input_lv_absolute_max_vpk'], 6.0)
        self.assertEqual(limits['output_full_scale_vpk_into_50ohm'], 1.0)
        counts = hardware['OUT1_INITIAL_COEFFICIENT_COUNTS']
        self.assertEqual(counts, tuple(sorted(counts)))
        self.assertEqual(counts[0], 1)
        self.assertLessEqual(counts[-1] / 16384.0,
                             hardware['OUT1_MAX_INITIAL_GAIN'])

    def test_bench_review_runs_without_manual_confirmations(self):
        namespace = dict(_LIB)
        with open(NOTEBOOK_PATH, encoding='utf-8') as handle:
            notebook = json.load(handle)
        for cell in notebook['cells']:
            if cell.get('cell_type') != 'code':
                continue
            role = cell.get('metadata', {}).get('electrode_feedback_role')
            source = ''.join(cell.get('source', []))
            if role == 'configuration' or 'def configuration_report()' in source:
                exec(compile(source, NOTEBOOK_PATH, 'exec'), namespace)
        report = namespace['CONFIGURATION_REPORT']
        plan = namespace['INITIAL_ACQUISITION_PLAN']
        self.assertEqual(report['passive_measurement_mode'],
                         'ready_for_live_safety_tests')
        self.assertIn('topology_digest', report)
        self.assertIn('analyser_fingerprint', report)
        self.assertGreaterEqual(plan['usable_span_hz'], 1.56e6)
        self.assertEqual(plan['decimation_log2'], 6)

    def test_synthetic_phase_axes_and_live_guards(self):
        import numpy as np
        with open(NOTEBOOK_PATH, encoding='utf-8') as handle:
            notebook = json.load(handle)
        namespace = dict(_LIB)
        namespace['np'] = np
        namespace['json'] = json
        for cell in notebook['cells']:
            source = ''.join(cell.get('source', []))
            if 'def calibrate_phase_axes' in source:
                exec(compile(source, NOTEBOOK_PATH, 'exec'), namespace)
        phases = np.arange(0.0, 360.0, 15.0)
        rows = [{'phase_deg': phase,
                 'fit': {'q': 8000.0 + 400.0 * np.cos(np.deg2rad(phase - 25.0)),
                         'f0_hz': 40e6 + 200.0 * np.cos(np.deg2rad(phase - 115.0))}}
                for phase in phases]
        axes = namespace['calibrate_phase_axes'](rows)
        self.assertAlmostEqual(axes['regenerative_deg'], 25.0, delta=0.1)
        self.assertAlmostEqual(axes['positive_shift_deg'], 115.0, delta=0.1)
        self.assertLess(axes['orthogonality_error_deg'], 0.1)
        source = '\n'.join(''.join(cell.get('source', []))
                           for cell in notebook['cells'])
        self.assertGreaterEqual(source.count('sc.peak_frac(4096)'), 4)
        self.assertIn('run calibrate_safe_probe_gain() before the phase sweep', source)
        self.assertIn('OUT1_OPERATING_GUARD_VPK', source)

    def test_shutdown_attempts_every_device_after_failure(self):
        hardware = _standalone_hardware()
        calls = []

        class GeneratorFailure(object):
            def off(self):
                calls.append('generator')
                raise IOError('injected')

        class Phase(object):
            def off(self):
                calls.append('phase')
            def readback(self):
                calls.append('readback')
                return (0, 0)

        class Acquisition(object):
            def stop(self):
                calls.append('acquisition')

        with self.assertRaises(RuntimeError):
            hardware['shutdown_devices'](GeneratorFailure(), Phase(),
                                         Acquisition())
        self.assertEqual(calls, ['generator', 'phase', 'acquisition', 'readback'])

    def test_campaign_monitor_survives_feedback_off_and_full_shutdown_clears_it(self):
        hardware = _standalone_hardware()
        memory_transport = hardware['MemoryTransport']

        class QualifiedMemoryTransport(memory_transport):
            def __init__(self, base, span):
                memory_transport.__init__(self, base, span)
                if base == 0x40600000:  # acquisition BUILD_ID register 0x48
                    self.m[0x48:0x4C] = (0xFE76AE09).to_bytes(4, 'little')

        hardware['TRANSPORT_FACTORY'] = QualifiedMemoryTransport
        with open(NOTEBOOK_PATH, encoding='utf-8') as handle:
            notebook = json.load(handle)
        for cell in notebook['cells']:
            source = ''.join(cell.get('source', []))
            if source.startswith('acq = Acq()'):
                exec(compile(source, NOTEBOOK_PATH, 'exec'), hardware)
                break
        phase = hardware['ps']
        phase.monitor('input', shift=0)
        hardware['feedback_off']()
        self.assertEqual(phase.readback()['monitor'], 1)
        hardware['full_shutdown']()
        self.assertEqual(phase.readback()['monitor'], 0)

    def test_out2_monitor_rejects_illegal_shift_and_detects_fault_state(self):
        hardware = _standalone_hardware()
        hardware['TRANSPORT_FACTORY'] = hardware['MemoryTransport']
        phase = hardware['PhaseShift']()
        with self.assertRaises(ValueError):
            phase.monitor('input', shift=8)
        phase.monitor('input', shift=0)
        phase.w(0x18, 0x101)  # injected sticky clipping bit plus input source
        self.assertTrue(phase.monitor_clipped())
        generator = hardware['Generator']()
        generator.off()
        generator.w(0x24, 1)  # injected channel-B amplitude contamination
        with self.assertRaises(RuntimeError):
            generator.assert_b_zero()

    def test_out2_analyser_psd_conversion_and_configuration_fingerprint(self):
        import numpy as np
        namespace = dict(_LIB)
        namespace.update(_standalone_hardware())
        with open(NOTEBOOK_PATH, encoding='utf-8') as handle:
            notebook = json.load(handle)
        for cell in notebook['cells']:
            source = ''.join(cell.get('source', []))
            if 'def compare_out2_analyser_trace' in source:
                exec(compile(source, NOTEBOOK_PATH, 'exec'), namespace)
                break
        analyser = {'model': 'mock-SA', 'input_impedance_ohm': 50.0,
                    'maximum_safe_input_dbm': 20.0, 'reference_level_dbm': 10.0,
                    'attenuation_db': 10.0, 'preamp_state': 'off', 'detector': 'RMS',
                    'rbw_hz': 1000.0, 'vbw_hz': 1000.0, 'averages': 40,
                    'cable_id': 'out2-A', 'cable_loss_db': 1.5}
        namespace['ANALYSER'] = analyser
        namespace['ANALYSER_FINGERPRINT'] = analyser_configuration_fingerprint(analyser)
        frequency = np.linspace(38.5e6, 39.5e6, 101)
        psd = 2e-9 * np.ones_like(frequency)
        power_dbm = 10 * np.log10(psd * analyser['rbw_hz'] / 50.0) + 30
        power_dbm -= analyser['cable_loss_db']
        result = namespace['compare_out2_analyser_trace'](
            frequency, power_dbm,
            {'frequency_hz': frequency, 'psd_v2_per_hz': psd})
        self.assertTrue(result['accepted'])
        self.assertAlmostEqual(result['median_error_db'], 0.0, places=9)
        analyser['rbw_hz'] = 2000.0
        with self.assertRaises(RuntimeError):
            namespace['compare_out2_analyser_trace'](
                frequency, power_dbm,
                {'frequency_hz': frequency, 'psd_v2_per_hz': psd})

    def test_out1_dc_record_rejects_offset_and_invokes_full_shutdown(self):
        namespace = dict(_LIB)
        namespace.update(_standalone_hardware())
        with open(NOTEBOOK_PATH, encoding='utf-8') as handle:
            notebook = json.load(handle)
        for cell in notebook['cells']:
            source = ''.join(cell.get('source', []))
            if 'def record_out1_dc_commissioning' in source:
                exec(compile(source, NOTEBOOK_PATH, 'exec'), namespace)
                break
        good = namespace['record_out1_dc_commissioning'](
            0.001, 0.002, 0.010, 'mock scope', 0.0001, True)
        self.assertTrue(good['accepted'])
        shutdowns = []
        namespace['full_shutdown'] = lambda: shutdowns.append(True)
        with self.assertRaises(RuntimeError):
            namespace['record_out1_dc_commissioning'](
                0.020, 0.020, 0.080, 'mock scope', 0.0001, True)
        self.assertEqual(shutdowns, [True])

    def test_effective_loop_acceptance_helpers(self):
        # Load the later pure-analysis helper cell without running hardware cells.
        with open(NOTEBOOK_PATH, encoding='utf-8') as handle:
            notebook = json.load(handle)
        namespace = {'np': __import__('numpy')}
        for cell in notebook['cells']:
            source = ''.join(cell.get('source', []))
            if 'def assess_gain_linearity' in source:
                exec(compile(source, NOTEBOOK_PATH, 'exec'), namespace)
        rows = [{'gain': gain, 'response': 2.0 * gain, 'accepted': True}
                for gain in (0.0, 0.1, 0.2, 0.3)]
        linear = namespace['assess_gain_linearity'](rows, 'response')
        self.assertTrue(linear['accepted'])
        commissioning = namespace['assess_output_commissioning']({
            'dac_zero_valid': True, 'out1_scale_valid': True,
            'spectral_purity_valid': True, 'coefficient_linearity_valid': True,
            'phase_valid': True, 'output_noise_valid': True,
            'clipping_absent': True, 'shutdown_valid': True})
        self.assertTrue(commissioning['accepted'])
        self.assertFalse(commissioning['coil_voltage_directly_measured'])
        self.assertFalse(commissioning['airgap_transfer_directly_measured'])

    def test_record_health_stress_cases_and_verbose_errors(self):
        import numpy as np
        namespace = dict(_LIB)
        namespace.update({'np': np,
                          'RP_LIMITS': {'input_lv_full_scale_vpk': 1.0},
                          'ADC_OPERATING_GUARD_VPK': 0.8})
        with open(NOTEBOOK_PATH, encoding='utf-8') as handle:
            notebook = json.load(handle)
        for cell in notebook['cells']:
            source = ''.join(cell.get('source', []))
            if 'def record_health' in source:
                start = source.index('def record_health')
                exec(compile(source[start:], NOTEBOOK_PATH, 'exec'), namespace)
                break
        health = namespace['record_health']
        rng = np.random.RandomState(90210)
        safe = 0.05 * (rng.normal(size=(40, 2048)) +
                       1j * rng.normal(size=(40, 2048)))
        self.assertTrue(health(safe)['accepted'])
        guard = safe.copy(); guard[0, 0] = 0.85
        guarded = health(guard)
        self.assertFalse(guarded['accepted'])
        self.assertIn('operating guard', ' '.join(guarded['rejection_reasons']))
        clipped = safe.copy(); clipped[0, 0] = 0.99
        self.assertTrue(health(clipped)['clipped'])
        drifting = safe * np.linspace(0.2, 3.0, 40)[:, None]
        self.assertFalse(health(drifting)['stationary'])
        with self.assertRaisesRegex(CalibrationError,
                                    'non-finite samples.*Discard the capture'):
            invalid = safe.copy(); invalid[2, 3] = np.nan
            health(invalid)
        with self.assertRaisesRegex(CalibrationError,
                                    'numerically zero.*IN1 cabling'):
            health(np.zeros((4, 64), dtype=complex))

    def test_planner_and_resonance_fit_monte_carlo_stress(self):
        import numpy as np
        for q_value in (50, 100, 150, 1000, 10000, 50000, 100000):
            for shift_hz in (-1e6, 0.0, 1e6):
                try:
                    plan = plan_passive_acquisition(
                        39e6, q_value, shift_hz,
                        min_decimation_log2=6,
                        centre_on_expected_shift=True,
                        bins_per_linewidth=20)
                except CalibrationError as error:
                    # A Q=50 resonance plus a 1 MHz shift guard is wider than
                    # the deliberately bounded acquisition band (even at zero
                    # shift with the default ten-linewidth coverage). Safe
                    # refusal is preferable to silently truncating it.
                    self.assertIn('requested usable span', str(error))
                    self.assertIn('largest qualified capture', str(error))
                    continue
                self.assertGreaterEqual(plan['bins_per_linewidth'], 20)
                self.assertGreater(plan['usable_span_hz'], 0)
                self.assertAlmostEqual(plan['centre_hz'], 39e6 + shift_hz)

        frequency = np.linspace(37.5e6, 40.5e6, 3001)
        linewidth = 39e6 / 150.0
        ideal = (1.0 + 0.12 * (frequency - 39e6) / 1.5e6 +
                 4.0 / (1.0 + 4.0 * ((frequency - 39e6) / linewidth) ** 2))
        for seed in range(20):
            rng = np.random.RandomState(seed)
            # Averaged PSD noise is positive and mildly heteroscedastic.
            psd = ideal * rng.gamma(shape=40.0, scale=1.0 / 40.0,
                                    size=frequency.size)
            result = fit_passive_resonator(frequency, psd)
            self.assertTrue(result['accepted'], 'seed %d rejected: %r' %
                            (seed, result))
            self.assertAlmostEqual(result['f0_hz'], 39e6, delta=12000.0)
            self.assertAlmostEqual(result['q'], 150.0, delta=20.0)

    def test_synthetic_linearity_compression_and_hysteresis(self):
        import numpy as np
        with open(NOTEBOOK_PATH, encoding='utf-8') as handle:
            notebook = json.load(handle)
        namespace = {'np': np}
        for cell in notebook['cells']:
            source = ''.join(cell.get('source', []))
            if 'def assess_gain_linearity' in source:
                exec(compile(source, NOTEBOOK_PATH, 'exec'), namespace)
        gains = np.linspace(0.0, 0.3, 7)
        linear = [{'gain': float(g), 'response': float(5.0 * g)} for g in gains]
        compressed = [{'gain': float(g),
                       'response': float(1.0 - np.exp(-18.0 * g))}
                      for g in gains]
        self.assertTrue(namespace['assess_gain_linearity'](
            linear, 'response')['accepted'])
        self.assertFalse(namespace['assess_gain_linearity'](
            compressed, 'response', minimum_r_squared=0.995)['accepted'])
        down = [{'gain': row['gain'], 'response': row['response'] + 0.3}
                for row in linear]
        hysteresis = namespace['assess_hysteresis'](
            linear, down, 'response', maximum_fraction_of_span=0.05)
        self.assertFalse(hysteresis['accepted'])

    def test_cic_dome_is_corrected_and_limited_to_trustworthy_band(self):
        import numpy as np
        namespace = dict(_LIB)
        with open(NOTEBOOK_PATH, encoding='utf-8') as handle:
            notebook = json.load(handle)
        for index in (2, 4, 28):
            source = ''.join(notebook['cells'][index].get('source', []))
            exec(compile(source, NOTEBOOK_PATH, 'exec'), namespace)
        plan = plan_passive_acquisition(39e6, 150, min_decimation_log2=6)
        frequency = np.linspace(39e6 - 0.9e6, 39e6 + 0.9e6, 2001)
        raw = namespace['cic_power_response'](frequency, plan)
        spectrum = {'frequency_hz': frequency, 'psd_v2_per_hz': raw,
                    'bin_hz': frequency[1] - frequency[0], 'averages': 40}
        corrected = namespace['correct_acquisition_response'](spectrum, plan)
        central = np.abs(frequency - 39e6) <= 0.5e6
        valid = central & corrected['response_correction_valid']
        self.assertGreater(np.count_nonzero(valid), 1000)
        self.assertAlmostEqual(float(np.nanmedian(corrected['psd_v2_per_hz'][valid])),
                               1.0, places=10)
        self.assertLess(raw[0], raw[len(raw)//2])
        self.assertEqual(corrected['response_source'],
                         'modelled CIC response; FIR bypassed')

    def test_lo_invariance_and_edge_fit_guards_reproduce_bad_run(self):
        import numpy as np
        namespace = dict(_LIB)
        with open(NOTEBOOK_PATH, encoding='utf-8') as handle:
            notebook = json.load(handle)
        for index in (2, 4, 28, 34):
            source = ''.join(notebook['cells'][index].get('source', []))
            exec(compile(source, NOTEBOOK_PATH, 'exec'), namespace)
        rows_fixed = []
        rows_moving = []
        for lo in (38.8e6, 39.0e6, 39.2e6):
            plan = {'centre_hz': lo}
            rows_fixed.append({'plan': plan,
                               'fit': {'f0_hz': 39.02e6,
                                       'linewidth_hz': 260e3,
                                       'accepted': True}})
            rows_moving.append({'plan': plan,
                                'fit': {'f0_hz': lo + 20e3,
                                        'linewidth_hz': 260e3,
                                        'accepted': True}})
        self.assertTrue(namespace['assess_lo_invariance'](rows_fixed)['accepted'])
        self.assertFalse(namespace['assess_lo_invariance'](rows_moving)['accepted'])

        # Reproduce the real run: Q~150 at 39.16--39.17 MHz was physically
        # LO-invariant but lay only ~1.3 linewidths below the upper boundary.
        observed = []
        for lo, f0, q in zip((38.8e6, 39.0e6, 39.2e6),
                             (39.171858e6, 39.159565e6, 39.171974e6),
                             (156.5, 151.6, 158.0)):
            observed.append({'plan': {'centre_hz': lo},
                             'fit': {'f0_hz': f0,
                                     'linewidth_hz': f0/q,
                                     'accepted': True}})
        observed_invariance = namespace['assess_lo_invariance'](observed)
        self.assertTrue(observed_invariance['accepted'])
        self.assertLess(observed_invariance['centre_spread_linewidths'], 0.06)

        frequency = np.linspace(38.5e6, 39.5e6, 2001)
        linewidth = 260e3
        edge_peak = 1.0 + 5.0 / (1.0 + 4.0*((frequency-39.45e6)/linewidth)**2)
        edge = namespace['fit_one_spectrum'](
            {'frequency_hz': frequency, 'psd_v2_per_hz': edge_peak},
            discovery=True)
        self.assertTrue(edge['accepted'])
        self.assertIn('recentered fit', edge['edge_margin_warning'])
        self.assertLess(edge['edge_margin_linewidths'], 1.5)

    def test_local_refined_fit_excludes_neighbouring_resonances(self):
        import numpy as np
        namespace = dict(_LIB)
        with open(NOTEBOOK_PATH, encoding='utf-8') as handle:
            notebook = json.load(handle)
        for index in (2, 4, 28, 34):
            source = ''.join(notebook['cells'][index].get('source', []))
            exec(compile(source, NOTEBOOK_PATH, 'exec'), namespace)
        rng = np.random.RandomState(812)
        frequency = np.linspace(38.0e6, 40.1e6, 5001)
        f0 = 39.17e6
        linewidth = f0/150.0
        main = 3.0e-12/(1.0 + 4.0*((frequency-f0)/linewidth)**2)
        # Irrelevant structures resembling those in the supplied run plot.
        neighbour_low = 4.0e-12/(1.0 + 4.0*((frequency-38.45e6)/35e3)**2)
        neighbour_high = 5.0e-12/(1.0 + 4.0*((frequency-39.62e6)/25e3)**2)
        psd = (1.0e-12 + main + neighbour_low + neighbour_high)
        psd *= np.exp(rng.normal(scale=0.08, size=frequency.size))
        fit = namespace['fit_one_spectrum'](
            {'frequency_hz': frequency, 'psd_v2_per_hz': psd},
            discovery=False, q_range=(75.0, 300.0),
            fit_centre_hz=f0,
            fit_half_width_hz=1.25*linewidth)
        self.assertTrue(fit['accepted'], fit['rejection_reasons'])
        self.assertLess(abs(fit['f0_hz']-f0), 0.08*linewidth)
        self.assertLess(abs(fit['q']-150.0), 35.0)
        self.assertEqual(namespace['REFINED_BASELINE_AVERAGES'], 120)
        self.assertEqual(namespace['SAFE_PROBE_AVERAGES'], 120)

    def test_empirical_response_calibration_uses_lo_relative_offsets(self):
        import numpy as np
        namespace = dict(_LIB)
        with open(NOTEBOOK_PATH, encoding='utf-8') as handle:
            notebook = json.load(handle)
        for index in (2, 4, 28, 30):
            source = ''.join(notebook['cells'][index].get('source', []))
            exec(compile(source, NOTEBOOK_PATH, 'exec'), namespace)
        namespace['CLR_GREY'] = '0.5'
        plan = plan_passive_acquisition(39e6, 150, min_decimation_log2=6)
        frequency = np.r_[np.linspace(38.5e6, 39.5e6, 9), 39e6, 38.5e6, 39.5e6]
        predicted = namespace['cic_power_response'](frequency, plan)
        input_rms = np.full(frequency.shape, 1e-3)
        measured_rms = input_rms * np.sqrt(predicted)
        calibration_result = namespace['calibrate_acquisition_response'](
            frequency, input_rms, measured_rms, plan)
        self.assertTrue(calibration_result['accepted'])
        shifted_plan = dict(plan); shifted_plan['centre_hz'] = 39.2e6
        shifted_frequency = calibration_result['offset_hz'] + shifted_plan['centre_hz']
        gain, source = namespace['acquisition_response_power'](
            shifted_frequency, shifted_plan, calibration_result)
        self.assertEqual(source, 'measured swept-tone response')
        self.assertTrue(np.allclose(gain, calibration_result['power_gain']))

    def test_dma_cic_scale_reconstructs_input_volts_without_false_clipping(self):
        import numpy as np
        namespace = dict(_LIB)
        with open(NOTEBOOK_PATH, encoding='utf-8') as handle:
            notebook = json.load(handle)
        for index in (2, 4, 28, 30):
            source = ''.join(notebook['cells'][index].get('source', []))
            exec(compile(source, NOTEBOOK_PATH, 'exec'), namespace)
        self.assertEqual(namespace['CIC_COUNTS_PER_ADC_VPK'], float(1 << 29))
        known_vpk = 0.0125
        raw_peak = known_vpk * (1 << 29)
        scale = namespace['validate_cic_voltage_scale'](raw_peak, known_vpk)
        self.assertTrue(scale['accepted'])
        self.assertAlmostEqual(scale['reconstructed_input_vpk'], known_vpk)
        # The former ADC-count conversion would falsely report 819.2 V here.
        self.assertAlmostEqual(raw_peak * namespace['CIC_VOLTS_PER_COUNT'],
                               known_vpk)

    def test_broad_peak_detector_survives_coloured_noise_and_narrow_spurs(self):
        import numpy as np
        namespace = dict(_LIB)
        with open(NOTEBOOK_PATH, encoding='utf-8') as handle:
            notebook = json.load(handle)
        for index in (2, 4, 28, 34):
            source = ''.join(notebook['cells'][index].get('source', []))
            exec(compile(source, NOTEBOOK_PATH, 'exec'), namespace)
        frequency = np.linspace(38.5e6, 39.5e6, 2049)
        linewidth = 39e6 / 150.0
        x = (frequency - 39e6) / 1e6
        background = np.exp(0.35*x)
        lorentzian = 0.45 / (1.0 + 4.0*((frequency-39.04e6)/linewidth)**2)
        for seed in range(12):
            rng = np.random.RandomState(700 + seed)
            psd = (background + lorentzian) * rng.gamma(
                shape=40.0, scale=1.0/40.0, size=frequency.size)
            # Large one-bin interference must be masked, not fitted as high Q.
            for index in rng.choice(np.arange(50, 1999), size=8, replace=False):
                psd[index] *= 15.0
            result = namespace['fit_one_spectrum'](
                {'frequency_hz': frequency, 'psd_v2_per_hz': psd},
                discovery=True)
            self.assertTrue(result['accepted'],
                            'seed %d rejected: %r' % (seed, result))
            self.assertAlmostEqual(result['f0_hz'], 39.04e6, delta=35e3)
            self.assertAlmostEqual(result['q'], 150.0, delta=45.0)
            self.assertGreaterEqual(result['masked_spur_bins'], 8)

    def test_broad_peak_detector_rejects_noisy_background_without_resonance(self):
        import numpy as np
        namespace = dict(_LIB)
        with open(NOTEBOOK_PATH, encoding='utf-8') as handle:
            notebook = json.load(handle)
        for index in (2, 4, 28, 34):
            source = ''.join(notebook['cells'][index].get('source', []))
            exec(compile(source, NOTEBOOK_PATH, 'exec'), namespace)
        frequency = np.linspace(38.5e6, 39.5e6, 2049)
        x = (frequency - 39e6) / 1e6
        rng = np.random.RandomState(991)
        psd = np.exp(0.4*x) * rng.gamma(shape=40.0, scale=1.0/40.0,
                                        size=frequency.size)
        result = namespace['fit_one_spectrum'](
            {'frequency_hz': frequency, 'psd_v2_per_hz': psd},
            discovery=True)
        self.assertFalse(result['accepted'])
        message = ' '.join(result['rejection_reasons'])
        self.assertTrue('ΔBIC' in message or 'integrated broad-feature SNR' in message)

    def test_plan_relative_fit_tracks_high_q_feedback_state(self):
        import numpy as np
        namespace = dict(_LIB)
        with open(NOTEBOOK_PATH, encoding='utf-8') as handle:
            notebook = json.load(handle)
        for index in (2, 4, 28, 34):
            source = ''.join(notebook['cells'][index].get('source', []))
            exec(compile(source, NOTEBOOK_PATH, 'exec'), namespace)
        frequency = np.linspace(38.97e6, 39.03e6, 4097)
        q_value = 10000.0
        linewidth = 39e6/q_value
        rng = np.random.RandomState(1440)
        ideal = 1.0 + 0.8/(1.0+4.0*((frequency-39.004e6)/linewidth)**2)
        psd = ideal*rng.gamma(shape=80.0, scale=1.0/80.0,
                              size=frequency.size)
        result = namespace['fit_one_spectrum'](
            {'frequency_hz': frequency, 'psd_v2_per_hz': psd},
            discovery=False, q_range=(2000.0, 50000.0))
        self.assertTrue(result['accepted'], result)
        self.assertAlmostEqual(result['f0_hz'], 39.004e6, delta=700.0)
        self.assertAlmostEqual(result['q'], q_value, delta=2500.0)

    def test_negative_input_offset_is_classified_by_source_not_as_negative_rf(self):
        import numpy as np
        namespace = dict(_LIB)
        namespace.update({'np': np, 'json': json})
        with open(NOTEBOOK_PATH, encoding='utf-8') as handle:
            notebook = json.load(handle)
        exec(compile(''.join(notebook['cells'][2]['source']),
                     NOTEBOOK_PATH, 'exec'), namespace)
        source = ''.join(notebook['cells'][24]['source'])
        source = source[:source.index('LIVE_INPUT_SAFETY =')]
        exec(compile(source, NOTEBOOK_PATH, 'exec'), namespace)
        records = {
            'in1_high_impedance_zfl_disconnected': {
                'dc_offset_v': -0.0215, 'accepted': True},
            'powered_detection_chain': {'dc_offset_v': -0.0230, 'accepted': True},
            'complete_resonator_feedback_off': {
                'dc_offset_v': -0.0232, 'accepted': True},
        }
        report = namespace['compare_input_dc_offsets'](records)
        self.assertTrue(report['accepted'])
        self.assertAlmostEqual(report['adc_native_input_offset_v'], -0.0215)
        self.assertAlmostEqual(report['powered_chain_increment_v'], -0.0015)
        self.assertAlmostEqual(report['resonator_connection_increment_v'], -0.0002)
        notebook_source = '\n'.join(''.join(c.get('source', []))
                                    for c in notebook['cells'])
        self.assertIn('predicted_feedback_dc_bound_v', notebook_source)
        self.assertIn('fractional-delay phase shifter passes DC', notebook_source)


if __name__ == '__main__':
    unittest.main()
