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
detect_self_oscillation = _LIB['detect_self_oscillation']
feedback_q_setup = _LIB['feedback_q_setup']
feedback_shift_setup = _LIB['feedback_shift_setup']
fit_passive_resonator = _LIB['fit_passive_resonator']
make_calibration = _LIB['make_calibration']
paired_k = _LIB['paired_k']
passive_iq_spectrum = _LIB['passive_iq_spectrum']
plan_passive_acquisition = _LIB['plan_passive_acquisition']
classify_dc_offset_sources = _LIB['classify_dc_offset_sources']
quantized_feedback_vector = _LIB['quantized_feedback_vector']
simulate_feedback_fixed_point = _LIB['simulate_feedback_fixed_point']
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
                  'acquisition_valid': True,
                  'effective_feedback_valid': True,
                  'created_epoch_s': now},
        safety={'max_k': 0.3, 'topology_digest': 'test-topology-digest',
                'high_pass_filter_in_feedback_path': True},
        build_id='0xFE76AE09')
    values.update(changes)
    return make_calibration(**values)


class ElectrodeFeedbackTests(unittest.TestCase):
    def test_recommendations_explain_missing_calibration_without_resealing(self):
        for missing in (None, {}, {'schema_version': 2}):
            with self.assertRaisesRegex(CalibrationError, 'NO COMPLETED CALIBRATION'):
                feedback_q_setup(missing, q_ratio=1.10)
            with self.assertRaisesRegex(CalibrationError, 'Cell 15'):
                feedback_shift_setup(missing, shift_linewidths=1.0)
        valid = calibration()
        valid['baseline']['q0'] += 1.0
        with self.assertRaisesRegex(CalibrationError, 'changed after it was created'):
            feedback_q_setup(valid)

    def test_acquisition_calibration_is_not_a_sealing_prerequisite(self):
        base = calibration()
        evidence = copy.deepcopy(base['evidence'])
        evidence.pop('acquisition_valid', None)
        rebuilt = make_calibration(
            base['baseline'], base['q_points'], base['shift_points'],
            base['phases'], evidence, base['safety'], base['build_id'])
        self.assertNotIn('acquisition_valid', rebuilt['evidence'])
        with open(NOTEBOOK_PATH, encoding='utf-8') as handle:
            source = handle.read()
        self.assertNotIn('def build_calibration(', source)


    def test_saved_json_workflows_have_been_removed(self):
        with open(NOTEBOOK_PATH, encoding='utf-8') as handle:
            source = handle.read()
        for removed in ('save_feedback_resume_checkpoint', 'load_feedback_resume_checkpoint',
                        'run_gain_phase_map', 'export_campaign', 'RESUME_BASELINE_PLAN'):
            self.assertNotIn(removed, source)
        self.assertIn('def measure_manual_feedback(', source)


    def test_fixed_point_feedback_reproduces_negative_one_count_asymmetry(self):
        import numpy as np
        negative = simulate_feedback_fixed_point(np.array([-191]), 1, 0)
        positive = simulate_feedback_fixed_point(np.array([-191]), -1, 0)
        self.assertEqual(int(negative[0]), -1)
        self.assertEqual(int(positive[0]), 0)

    def test_fixed_point_noise_and_25db_pad_prediction(self):
        import numpy as np
        samples = np.arange(16384, dtype=float)
        input_codes = np.rint(-191.0 + 39.0*np.sqrt(2.0)*np.sin(
            2.0*np.pi*137.0*samples/len(samples))).astype(np.int64)
        output_1 = simulate_feedback_fixed_point(input_codes, 1, 0)
        output_1024 = simulate_feedback_fixed_point(input_codes, 1024, 0)
        self.assertLess(float(np.mean(output_1)), -0.9)
        self.assertAlmostEqual(float(np.std(output_1024)), 39.0*1024.0/16384.0,
                               delta=0.6)
        pad_ratio = 10.0**(-25.0/20.0)
        output_rms_v = float(np.std(output_1024))/8192.0*pad_ratio
        self.assertGreater(output_rms_v, 0.0)
        self.assertLess(output_rms_v, 30e-6)

    def test_quantized_vector_reports_actual_words_and_phase(self):
        row = quantized_feedback_vector(64, 0.0, 40.9e6)
        self.assertEqual(row['ci_word'], row['ci_signed'] & 0xFFFF)
        self.assertEqual(row['cq_word'], row['cq_signed'] & 0xFFFF)
        self.assertLess(abs(row['phase_error_deg']), 1.0)


    def test_default_campaign_keeps_out2_off_and_has_no_analyser_workflow(self):
        with open(NOTEBOOK_PATH, encoding='utf-8') as handle:
            notebook_source = handle.read()
        self.assertIn("out2_monitor_off()", notebook_source)
        self.assertNotIn('OUT2_MONITOR_MODE', notebook_source)
        self.assertNotIn('ANALYSER_FINGERPRINT', notebook_source)
        self.assertNotIn('compare_out2_analyser_trace', notebook_source)

    def test_notebook_build_id_matches_fpga_header(self):
        with open(NOTEBOOK_PATH, encoding='utf-8') as handle:
            notebook_source = json.dumps(json.load(handle))
        header = os.path.join(ROOT, 'fpga', 'build_id.vh')
        with open(header, encoding='utf-8') as handle:
            header_source = handle.read()
        self.assertIn("BUILD_ID_EXPECTED = '0xFE76AE09'", notebook_source)
        self.assertIn("32'hFE76AE09", header_source)

    def test_dedicated_notebook_is_fail_closed_and_streamlined(self):
        path = os.path.join(ROOT, 'notebooks',
                            'test_noise_passive_feedback.ipynb')
        with open(path, encoding='utf-8') as handle:
            notebook = json.load(handle)
        source = '\n'.join(''.join(cell.get('source', []))
                           for cell in notebook['cells'])
        self.assertIn('# Test Noise Passive Feedback', source)
        self.assertNotIn('ELECTRODE_CHARACTERISATION_ARMED', source)
        self.assertIn('OUT1 -> installed high-pass return path -> trap electrode', source)
        self.assertIn("'high_pass_filter_in_feedback_path': True", source)
        self.assertIn('native high-impedance mode', source)
        self.assertIn('passive_iq_spectrum', source)
        self.assertIn('def full_shutdown()', source)
        self.assertIn('def disable_everything()', source)
        self.assertIn('def out2_monitor_off()', source)
        self.assertEqual(source.count('def measure_manual_feedback('), 1)
        self.assertIn('def measure_acquisition_filters(', source)
        self.assertIn('electrode_voltage_directly_measured', source)
        self.assertNotIn('def record_out1_dc_commissioning', source)
        self.assertNotIn('def assess_output_commissioning', source)
        self.assertNotIn('ANALYSER_FINGERPRINT', source)
        self.assertNotIn('resonator_coil_characterisation', source)
        self.assertNotIn('from electrode_feedback', source)
        self.assertNotIn('sys.path', source)
        # The NumPy supplied on the Red Pitaya requires a numeric rcond.
        # A null value works on newer PCs but fails on the board at runtime.
        self.assertNotIn('rcond=None', source)
        self.assertGreaterEqual(source.count('rcond=-1'), 2)
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
        self.assertFalse(cal['electrode_voltage_directly_measured'])
        self.assertFalse(cal['feedback_path_transfer_directly_measured'])
        self.assertEqual(cal['effective_loop_status'],
                         'closed_loop_inference_only')
        setup = feedback_q_setup(cal, target_k=0.1)
        self.assertFalse(setup['electrode_voltage_directly_measured'])
        self.assertFalse(setup['feedback_path_transfer_directly_measured'])
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

    def test_topology_uses_only_campaign_relevant_facts_and_requires_high_pass(self):
        topology = {
            'campaign_label': 'trap-path-A',
            'resonance_frequency_hz': 40.9e6,
            'high_pass_filter_in_feedback_path': True,
            'input_mode': 'native-high-impedance',
        }
        self.assertIn('digest', validate_topology(topology))
        unsafe = copy.deepcopy(topology)
        unsafe['high_pass_filter_in_feedback_path'] = False
        with self.assertRaises(CalibrationError):
            validate_topology(unsafe)
        changed_campaign = copy.deepcopy(topology)
        changed_campaign['campaign_label'] = 'trap-path-B'
        self.assertNotEqual(validate_topology(topology)['digest'],
                            validate_topology(changed_campaign)['digest'])

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

    def test_paired_k(self):
        self.assertAlmostEqual(paired_k(5000, 3000), 0.25)

    def test_passive_fit_recovers_39mhz_q150_over_sloping_noise(self):
        import numpy as np
        frequency = np.linspace(39.4e6, 42.4e6, 3001)
        linewidth = 40.9e6 / 150.0
        slope = 0.15 * (frequency - 40.9e6) / (frequency[-1] - frequency[0])
        peak = 4.0 / (1.0 + 4.0 * ((frequency - 40.9e6) / linewidth) ** 2)
        rng = np.random.RandomState(31)
        psd = 1.0 + slope + peak + rng.normal(scale=0.01, size=frequency.size)
        fit = fit_passive_resonator(frequency, psd)
        self.assertTrue(fit['accepted'])
        self.assertAlmostEqual(fit['f0_hz'], 40.9e6, delta=3000.0)
        self.assertAlmostEqual(fit['q'], 150.0, delta=5.0)
        self.assertEqual(fit['resonator_state'], 'passive_noise')

    def test_acquisition_plan_adapts_from_q100_to_high_q_and_shift(self):
        discovery = plan_passive_acquisition(
            40.9e6, 150, 0.0, min_decimation_log2=6,
            bins_per_linewidth=20, linewidths_each_side=2.5)
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
            plan_passive_acquisition(40.9e6, 150, min_decimation_log2=4)
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

    def test_official_red_pitaya_limits(self):
        hardware = _standalone_hardware()
        limits = hardware['RP_LIMITS']
        self.assertEqual(limits['adc_bits'], 14)
        self.assertEqual(limits['sample_rate_hz'], 125e6)
        self.assertEqual(limits['input_impedance_ohm'], 1e6)
        self.assertEqual(limits['input_lv_full_scale_vpk'], 1.0)
        self.assertEqual(limits['input_lv_absolute_max_vpk'], 6.0)
        self.assertEqual(limits['output_full_scale_vpk_into_50ohm'], 1.0)

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
        self.assertNotIn('analyser_fingerprint', report)
        self.assertGreaterEqual(plan['usable_span_hz'], 1.56e6)
        self.assertEqual(plan['decimation_log2'], 6)


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
                        40.9e6, q_value, shift_hz,
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
                self.assertAlmostEqual(plan['centre_hz'], 40.9e6 + shift_hz)

        frequency = np.linspace(39.4e6, 42.4e6, 3001)
        linewidth = 40.9e6 / 150.0
        ideal = (1.0 + 0.12 * (frequency - 40.9e6) / 1.5e6 +
                 4.0 / (1.0 + 4.0 * ((frequency - 40.9e6) / linewidth) ** 2))
        for seed in range(20):
            rng = np.random.RandomState(seed)
            # Averaged PSD noise is positive and mildly heteroscedastic.
            psd = ideal * rng.gamma(shape=40.0, scale=1.0 / 40.0,
                                    size=frequency.size)
            result = fit_passive_resonator(frequency, psd)
            self.assertTrue(result['accepted'], 'seed %d rejected: %r' %
                            (seed, result))
            self.assertAlmostEqual(result['f0_hz'], 40.9e6, delta=12000.0)
            self.assertAlmostEqual(result['q'], 150.0, delta=20.0)


    def test_cic_dome_is_corrected_and_limited_to_trustworthy_band(self):
        import numpy as np
        namespace = dict(_LIB)
        with open(NOTEBOOK_PATH, encoding='utf-8') as handle:
            notebook = json.load(handle)
        for marker in ('TOPOLOGY = {', 'Standalone numerical dependencies loaded', 'def cic_power_response('):
            source = next(''.join(cell['source']) for cell in notebook['cells']
                          if cell['cell_type'] == 'code' and marker in ''.join(cell['source']))
            exec(compile(source, NOTEBOOK_PATH, 'exec'), namespace)
        plan = plan_passive_acquisition(40.9e6, 150, min_decimation_log2=6)
        frequency = np.linspace(40.9e6 - 0.9e6, 40.9e6 + 0.9e6, 2001)
        raw = namespace['cic_power_response'](frequency, plan)
        spectrum = {'frequency_hz': frequency, 'psd_v2_per_hz': raw,
                    'bin_hz': frequency[1] - frequency[0], 'averages': 40}
        corrected = namespace['correct_acquisition_response'](spectrum, plan)
        central = np.abs(frequency - 40.9e6) <= 0.5e6
        valid = central & corrected['response_correction_valid']
        self.assertGreater(np.count_nonzero(valid), 1000)
        self.assertAlmostEqual(float(np.nanmedian(corrected['psd_v2_per_hz'][valid])),
                               1.0, places=10)
        self.assertLess(raw[0], raw[len(raw)//2])
        self.assertEqual(corrected['response_source'],
                         'modelled exact CIC; FIR bypassed')


    def test_negative_input_offset_is_classified_by_source_not_as_negative_rf(self):
        with open(NOTEBOOK_PATH, encoding='utf-8') as handle:
            notebook = json.load(handle)
        records = {
            'in1_local_50ohm_reference': {
                'dc_offset_v': -0.0215, 'dc_offset_uncertainty_v': 0.00005,
                'accepted': True},
            'powered_chain_safe_reference': {
                'dc_offset_v': -0.0230, 'dc_offset_uncertainty_v': 0.00005,
                'accepted': True},
            'complete_resonator_feedback_off': {
                'dc_offset_v': -0.0232, 'dc_offset_uncertainty_v': 0.00005,
                'accepted': True},
        }
        report = classify_dc_offset_sources(records)
        self.assertTrue(report['local_offset_resolved'])
        self.assertFalse(report['grounding_proven'])
        self.assertFalse(report['automatic_offset_correction_authorised'])
        self.assertAlmostEqual(report['local_reference_offset_v'], -0.0215)
        self.assertTrue(report['comparisons']['powered_chain_increment']['resolved'])
        self.assertFalse(report['comparisons']['resonator_increment']['resolved'])
        notebook_source = '\n'.join(''.join(c.get('source', []))
                                    for c in notebook['cells'])
        self.assertIn('HEADROOM/DC GUARD', notebook_source)
        self.assertIn('simulate_feedback_fixed_point', notebook_source)

    def test_dc_offset_classifier_separates_amplifier_and_trap_increments(self):
        records = {
            'in1_local_50ohm_reference': {
                'dc_offset_v': -0.0002, 'dc_offset_uncertainty_v': 0.00005},
            'in1_open_high_impedance': {
                'dc_offset_v': -0.0030, 'dc_offset_uncertainty_v': 0.00008},
            'powered_chain_safe_reference': {
                'dc_offset_v': -0.0210, 'dc_offset_uncertainty_v': 0.00010},
            'complete_resonator_feedback_off': {
                'dc_offset_v': -0.0340, 'dc_offset_uncertainty_v': 0.00012},
        }
        report = classify_dc_offset_sources(records)
        self.assertFalse(report['local_offset_resolved'])
        self.assertTrue(report['comparisons']['open_input_increment']['resolved'])
        self.assertTrue(report['comparisons']['powered_chain_increment']['resolved'])
        self.assertTrue(report['comparisons']['resonator_increment']['resolved'])
        self.assertTrue(report['comparisons']['external_total_increment']['resolved'])

    def test_dc_offset_classifier_does_not_overcall_noisy_small_difference(self):
        records = {
            'in1_local_50ohm_reference': {
                'dc_offset_v': -0.0230, 'dc_offset_uncertainty_v': 0.0005},
            'complete_resonator_feedback_off': {
                'dc_offset_v': -0.0233, 'dc_offset_uncertainty_v': 0.0005},
        }
        report = classify_dc_offset_sources(records)
        external = report['comparisons']['external_total_increment']
        self.assertFalse(external['resolved'])
        self.assertGreater(external['resolved_threshold_v'], 0.0035)
        self.assertTrue(report['local_offset_resolved'])

    def test_dc_offset_classifier_requires_local_and_complete_captures(self):
        with self.assertRaisesRegex(CalibrationError, 'local 50 ohm'):
            classify_dc_offset_sources({
                'complete_resonator_feedback_off': {
                    'dc_offset_v': -0.02,
                    'dc_offset_uncertainty_v': 0.0001}})


if __name__ == '__main__':
    unittest.main()

# End of standalone notebook tests.
