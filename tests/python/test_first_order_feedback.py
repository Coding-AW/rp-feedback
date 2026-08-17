#!/usr/bin/env python3
"""Known-answer and static tests for the standalone first-order notebook."""

import ast
import json
import os
import unittest

import numpy as np


ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..'))
NOTEBOOK = os.path.join(
    ROOT, 'notebooks', 'acquisition', 'resonator_coil_characterisation.ipynb')


class FirstOrderNotebookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(NOTEBOOK, encoding='utf-8') as handle:
            cls.notebook = json.load(handle)
        cls.source = '\n'.join(
            ''.join(cell.get('source', [])) for cell in cls.notebook['cells'])

    def test_every_code_cell_parses_and_outputs_are_clear(self):
        for index, cell in enumerate(self.notebook['cells']):
            if cell['cell_type'] == 'code':
                ast.parse(''.join(cell.get('source', [])), filename='cell-%d' % index)
                self.assertIsNone(cell.get('execution_count'))
                self.assertEqual(cell.get('outputs'), [])

    def test_notebook_is_standalone_with_optional_external_monitor(self):
        self.assertNotIn('first_order_feedback', self.source)
        self.assertNotIn('sys.path.insert', self.source)
        self.assertNotIn('STEP 8d-ext', self.source)
        self.assertNotIn('STEP 8e-ext', self.source)
        self.assertIn('OUT2_MONITOR_INPUT = True', self.source)
        self.assertIn("ps.monitor('input', shift=0)", self.source)
        self.assertIn('OUT2 input monitor clipped', self.source)

    def test_verification_fails_closed_and_brackets_every_point(self):
        self.assertIn("before = _reference_trace(dec_log2=dec_log2)", self.source)
        self.assertIn("after = _reference_trace(dec_log2=dec_log2)", self.source)
        self.assertIn("under-resolved fit", self.source)
        self.assertIn("drive-off oscillation detected", self.source)
        self.assertIn("feedback coefficient readback changed", self.source)
        self.assertIn("finally:\n        gen.off()\n        ps.off()", self.source)

    def test_first_order_known_q(self):
        q0, measured_k = 179.1, 0.777
        predicted_q = q0 / (1.0 - measured_k)
        self.assertAlmostEqual(predicted_q, 803.14, places=2)
        self.assertLess(abs(predicted_q - 801.8) / 801.8, 0.002)

    def test_shift_ceiling_and_phase_error_model(self):
        b0 = 222_975.0
        self.assertAlmostEqual(0.5 * b0, 111_487.5)
        self.assertLess(abs(112_970.0 / b0 - 0.5), 0.01)

        q0, k, delta = 179.1, 0.90, np.deg2rad(3.0)
        exact = q0 / (1.0 - k * np.cos(delta))
        small_error = q0 / ((1.0 - k) + 0.5 * k * delta ** 2)
        self.assertLess(abs(exact / small_error - 1.0), 1e-5)

    def test_vector_model_recovers_gain_dependent_phase(self):
        gains = np.array([0.4, 0.8, 1.1])
        k = 0.72 * gains
        theta = np.deg2rad(np.array([0.0, 7.0, 19.0]))
        damping = k * np.cos(theta)
        shift_term = k * np.sin(theta)
        recovered_k = np.hypot(damping, shift_term)
        recovered_phase = np.arctan2(shift_term, damping)
        np.testing.assert_allclose(recovered_k, k, rtol=1e-12)
        np.testing.assert_allclose(recovered_phase, theta, atol=1e-12)

    def test_vector_model_exposes_gain_compression(self):
        gain = np.linspace(0.1, 1.5, 20)
        linear = 0.75 * gain
        compressed = linear / (1.0 + (gain / 1.0) ** 4) ** 0.25
        low_slope = compressed[2] / gain[2]
        self.assertLess(compressed[-1], 0.85 * low_slope * gain[-1])

    def test_two_amplifier_gain_and_safety_models_are_separate(self):
        self.assertIn('EXT_GAIN_DB    = 27.0', self.source)
        self.assertIn('INTERSTAGE_PAD_DB = 15.0', self.source)
        self.assertIn('EXT_GAIN_SAFETY_DB = 40.2', self.source)
        self.assertIn('measured EXT_GAIN_DB', self.source)
        self.assertIn('Safety limits retain', self.source)

    def test_closed_loop_output_is_not_inferred_from_raw_adc_peak(self):
        self.assertNotIn('adc_peak / G_PASSIVE', self.source)
        self.assertNotIn("'final_output_dbm'", self.source)
        self.assertIn('adc_peak > FB_LEVEL_GUARD', self.source)

    def test_high_gain_diagnostics_do_not_depend_on_preliminary_recommendation(self):
        self.assertIn('_diag_candidates', self.source)
        self.assertIn('_diag_seed', self.source)
        self.assertNotIn("BOUNDARY_STOP_REASON = 'Step 8f produced no verified Q point.'",
                         self.source)
        self.assertIn('DIAG_TARGET_K = (0.30, 0.50, 0.70, 0.85)', self.source)
        self.assertIn("round(min(FB_GAIN_MAX, k/_diag_slope), 4)", self.source)

    def test_reduced_drive_compression_signature(self):
        k_full, k_reduced = 0.72, 0.79
        self.assertTrue(k_reduced > 1.03 * k_full)
        k_full, k_reduced = 0.72, 0.725
        self.assertFalse(k_reduced > 1.03 * k_full)

    def test_v2_known_high_gain_result(self):
        kq, kp, kv = 0.875, 0.890, 0.876
        self.assertLess(max(kq, kp, kv) - min(kq, kp, kv), 0.02)
        self.assertAlmostEqual(1.0 / (1.0 - kq), 8.0)

    def test_adaptive_receiver_is_used_for_closed_loop_linewidth(self):
        self.assertIn('use_dec = choose_dec(lw_hint)', self.source)
        self.assertIn("d_primary = choose_dec(phase_best['measured']['fit']['lw'])",
                      self.source)
        self.assertIn('np.all(dv[:, 4] <= 0.25)',
                      self.source)
        fs, linewidth = 125e6, 28e3
        baseline_window = 0.10 * fs / (2 ** 10)
        adaptive_window = 0.10 * fs / (2 ** 12)
        self.assertGreater(baseline_window / linewidth, 0.25)
        self.assertLess(adaptive_window / linewidth, 0.25)

    def test_small_signal_plateau_replaces_cross_drive_equality(self):
        self.assertIn('DIAG_DRIVE_LEVELS', self.source)
        self.assertIn('_diag_drive_lo = float(DRIVE_WINDOW[0])', self.source)
        self.assertIn('def _amplitude_controlled_drive', self.source)
        self.assertIn("row['small_signal_plateau_ok']", self.source)
        self.assertIn('DIAG_MIN_EXCITATION_COUNTS', self.source)
        self.assertIn('DIAG_PLATEAU_ABS_K', self.source)
        self.assertIn("row['k_small_signal']", self.source)
        compressed_to_small_signal = np.array([0.75, 0.84, 0.891, 0.895, 0.896])
        low_three = compressed_to_small_signal[-3:]
        spread = np.ptp(low_three) / np.mean(low_three)
        self.assertLess(spread, 0.03)

    def test_low_gain_phase_is_not_refined_from_a_flat_q_maximum(self):
        self.assertIn('DIAG_PHASE_REFINE_MIN_K', self.source)
        self.assertIn('using the full-circle narrowing phase', self.source)
        self.assertIn('predicted_k < DIAG_PHASE_REFINE_MIN_K', self.source)

    def test_compression_requires_a_consistent_drive_trend(self):
        self.assertIn("_compression_corr <= -0.70", self.source)
        self.assertIn("row['compression_recovery_k']", self.source)

    def test_drive_cause_isolation_is_interleaved_and_paired(self):
        self.assertIn('DIAG_FIXED_NAVG = 768', self.source)
        self.assertIn('_diag_rng.permutation(_levels)', self.source)
        self.assertIn("variant_records[(repeat, float(drive_scale), 'minus')]", self.source)
        self.assertIn("drow['k_paired']", self.source)
        self.assertIn("drive_dependence_diagnosis", self.source)
        self.assertIn('fit_residual_max', self.source)
        self.assertIn('reference_move_max_lw', self.source)

    def test_low_gain_ambiguity_does_not_block_higher_signal_tests(self):
        self.assertIn('DIAG_GATE_MIN_K', self.source)
        self.assertIn('retained as low-gain diagnostic and continuing', self.source)
        self.assertIn('_gated_rows', self.source)

    def test_origin_fit_is_not_promoted_across_compressed_points(self):
        self.assertIn('origin-constrained descriptive fit', self.source)
        self.assertIn('K/A is not constant', self.source)
        self.assertIn('small-signal K0(A)', self.source)
        self.assertIn("'small_signal_fit'", self.source)

    def test_phase_search_recentres_and_rejects_an_edge_maximum(self):
        self.assertIn('def _adaptive_phase', self.source)
        self.assertIn("'phase maximum remained on the grid edge'", self.source)
        self.assertIn("(-0.5, 0.0, 0.5)", self.source)

    def test_shift_vector_above_unit_is_reported_conditionally(self):
        shift_over_b0 = 0.596
        self.assertAlmostEqual(2.0 * shift_over_b0, 1.192)
        self.assertIn('only a ceiling if vector K < 1', self.source)
        self.assertIn("SHIFT_RECOMMENDATION['k_vector']", self.source)

    def test_exports_are_json_safe_atomic_and_independent(self):
        self.assertIn('def _json_safe', self.source)
        self.assertIn("if isinstance(value, np.ndarray)", self.source)
        self.assertIn("_plain_diagnostic", self.source)
        self.assertIn("os.replace(_json_tmp, RESULTS_JSON)", self.source)
        self.assertIn("os.replace(_npz_tmp, _npz_target)", self.source)
        self.assertIn("_save_errors.append('JSON:", self.source)
        self.assertIn('diagnostic_frequency_hz', self.source)

    def test_linear_reference_interpolation_removes_drift(self):
        before_t, after_t, measured_t = 0.0, 10.0, 5.0
        before_f, after_f = 40e6, 40e6 + 5000.0
        measured_f = 40e6 + 2500.0 + 500.0
        alpha = (measured_t - before_t) / (after_t - before_t)
        baseline = (1.0 - alpha) * before_f + alpha * after_f
        self.assertAlmostEqual(measured_f - baseline, 500.0)

    def test_drift_record_is_mandatory_for_boundary_campaign(self):
        self.assertIn('DRIFT_MINUTES  = 20.0', self.source)
        self.assertIn('DRIFT_VALID = False', self.source)
        self.assertIn("if not globals().get('DRIFT_VALID', False)", self.source)
        self.assertIn("'drift_ok': bool(globals().get('DRIFT_VALID', False))", self.source)
        self.assertIn('DIAG_DRIFT_COVERAGE_MIN', self.source)
        self.assertIn('DIAG_TEMPORAL_OK', self.source)
        self.assertIn('detrended feedback-off linewidth uncertainty exceeds', self.source)

    def test_uncertainty_aware_agreement_avoids_low_k_percentage_cliff(self):
        self.assertIn('DIAG_K_AGREEMENT_ABS = 0.015', self.source)
        self.assertIn("row['agreement_ci95_k']", self.source)
        self.assertIn("row['agreement_limit_k']", self.source)
        self.assertIn("r.get('agreement_ok', False)", self.source)
        k_pair, k_vector = 0.036, 0.038
        self.assertLess(abs(k_vector - k_pair), 0.015)
        self.assertGreater(abs(k_vector-k_pair) / np.mean([k_pair, k_vector]), 0.05)

    def test_joint_pair_and_independent_width_diagnostics_are_saved(self):
        self.assertIn('def _joint_paired_metrics', self.source)
        self.assertIn("'k_joint'", self.source)
        self.assertIn('def trace_fit_diagnostics', self.source)
        self.assertIn("'half_power_lw': hp", self.source)
        self.assertIn('def fit_complex_resonator', self.source)
        self.assertIn("'complex_fit': cfit", self.source)
        self.assertIn('diagnostic_fit_residual', self.source)
        self.assertIn('diagnostic_complex_real', self.source)
        self.assertIn('diagnostic_complex_imag', self.source)
        self.assertIn('diagnostic_timestamp_s', self.source)

    def test_complex_fit_recovers_pole_with_linear_background(self):
        nodes = []
        for cell in self.notebook['cells']:
            if cell.get('cell_type') != 'code':
                continue
            tree = ast.parse(''.join(cell.get('source', [])))
            nodes.extend(n for n in tree.body if isinstance(n, ast.FunctionDef)
                         and n.name == 'fit_complex_resonator')
        namespace = {'np': np}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), '<complex-fit>', 'exec'),
             namespace)
        f0, lw = 39.92e6, 90e3
        f = f0 + np.linspace(-4, 4, 161)*lw
        x = (f-f0)/np.ptp(f)
        z = ((0.03+0.02j) + (0.01-0.005j)*x +
             (1.2-0.4j)/(1+2j*(f-f0)/lw))
        got = namespace['fit_complex_resonator'](
            f, z, {'f0': f0+0.03*lw, 'lw': 1.08*lw})
        self.assertLess(abs(got['f0']-f0), 0.02*lw)
        self.assertLess(abs(got['lw']/lw-1), 0.03)

    def test_fit_quality_and_adaptive_drive_are_fail_closed(self):
        for text in ('FIT_MAX_RESIDUAL = 0.005', 'FIT_MAX_FLOOR_PEAK = 0.05',
                     'FIT_MAX_WIDTH_DISAGREEMENT = 0.05',
                     'FIT_MAX_REFERENCE_K_MOVE = 0.01'):
            self.assertIn(text, self.source)
        self.assertIn("drive_frac < drive_lo", self.source)
        self.assertIn('COHERENT_PEAK_HIGH', self.source)
        self.assertIn('np.clip(requested, _diag_drive_lo, DIAG_BASE_DRIVE)', self.source)

    def test_measured_k_campaign_and_seo_confirmation_protocol(self):
        self.assertIn('CALIBRATION_TARGET_K = (0.10, 0.20, 0.30, 0.40, 0.50)', self.source)
        self.assertIn('FULL_PHASE_TARGET_K = (0.20, 0.40, 0.60, 0.75)', self.source)
        self.assertIn("K_CALIBRATION = {'valid': False}", self.source)
        self.assertIn("0.005 if row['k_small_signal'] > 0.97", self.source)
        self.assertIn('SEO_CONFIRM_CAPTURES = 3', self.source)
        self.assertIn('SEO_MIN_DB_ABOVE_NOISE = 10.0', self.source)
        self.assertIn('red_pitaya_carrier_confirmed', self.source)
        self.assertIn('external_carrier_confirmed', self.source)
        self.assertIn('rp_seen and SEO_EXTERNAL_CARRIER_CONFIRMED', self.source)

    def test_external_chain_confirmation_uses_measured_values(self):
        for text in ('MEASURED_GAIN_INCREASE_DB', 'MEASURED_SECOND_INPUT_DBM',
                     'MEASURED_FINAL_OUTPUT_DBM', 'MEASURED_WORST_HARMONIC_DBC',
                     'MEASURED_BROADBAND_RISE_DB'):
            self.assertIn(text, self.source)
        self.assertIn('7.0 <= MEASURED_GAIN_INCREASE_DB <= 11.0', self.source)
        self.assertIn('MEASURED_WORST_HARMONIC_DBC <= -40.0', self.source)

    def test_insufficient_plateau_is_explicit_not_infinite(self):
        self.assertIn('insufficient eligible points (%d/%d)', self.source)
        self.assertNotIn("_plateau_abs = plateau_spread = float('inf')", self.source)

    def test_synthetic_bias_and_receiver_scenarios_are_distinguishable(self):
        true_k = 0.35
        paired = np.full(5, true_k)
        vector_baseline_bias = true_k + np.linspace(0.0, 0.03, 5)
        self.assertLess(np.ptp(paired), 1e-12)
        self.assertGreater(np.ptp(vector_baseline_bias), 0.015)
        receiver_a = true_k + np.array([-.002, .001, 0, .002, -.001])
        receiver_b = receiver_a + 0.025
        self.assertGreater(abs(receiver_b.mean()-receiver_a.mean()), 0.015)

    def test_exports_and_labelling_are_present(self):
        for name in ('bench_coil_results.json', 'bench_coil_traces.npz',
                     'bench_coil_report.md'):
            self.assertIn(name, self.source)
        self.assertIn('(measured once / mapped)', self.source)
        self.assertIn('(extrapolated; not approached)', self.source)

    def test_boundary_search_is_doubly_gated_and_fails_closed(self):
        self.assertIn('OSC_PROTECTION_CONFIRMED = False', self.source)
        self.assertIn('ONSET_SEARCH_ARMED = False', self.source)
        self.assertIn('protection_margin_db >= 0.0', self.source)
        self.assertIn('SCOPE_NO_CLIPPING_CONFIRMED = False', self.source)
        self.assertIn('SA_LEVELS_CONFIRMED = bool(', self.source)
        self.assertIn('SA_HARMONICS_CONFIRMED = bool(', self.source)
        self.assertIn('HIGH_GAIN_CHAIN_CONFIRMED', self.source)
        self.assertIn('_full_phase_k_max / max(k_slope, 1e-9)', self.source)
        self.assertIn("highest.get('k_small_signal', highest['k_vector']) < 0.98",
                      self.source)
        self.assertIn("while measured_k_per_a * (high_a - low_a) >= 0.01", self.source)
        self.assertIn("if row['k_small_signal'] >= 0.80", self.source)
        self.assertIn("0.02 if row['k_small_signal'] > 0.85", self.source)
        self.assertIn("finally:\n        gen.off(); ps.off()", self.source)


if __name__ == '__main__':
    unittest.main()
