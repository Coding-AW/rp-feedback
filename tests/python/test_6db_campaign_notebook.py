import ast
import json
import math
import numpy as np
from pathlib import Path
import unittest


NOTEBOOK = (Path(__file__).parents[2] / 'notebooks' / 'acquisition' /
            'resonator_coil_characterisation_6db_campaign.ipynb')


class SixDbCampaignNotebookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.notebook = json.loads(NOTEBOOK.read_text(encoding='utf-8'))
        cls.source = '\n'.join(''.join(c.get('source', []))
                               for c in cls.notebook['cells'])
        cls.code_source = '\n'.join(''.join(c.get('source', []))
                                    for c in cls.notebook['cells']
                                    if c.get('cell_type') == 'code')

    def test_all_code_cells_compile(self):
        for index, cell in enumerate(self.notebook['cells']):
            if cell.get('cell_type') == 'code':
                ast.parse(''.join(cell.get('source', [])),
                          filename='cell-%d' % index)

    def test_hardware_description_is_six_db(self):
        self.assertIn("INTERSTAGE_PAD_DB = 6.0", self.source)
        self.assertIn("INTERSTAGE_PAD_LABEL = '6 dB'", self.source)
        self.assertIn("EXT_GAIN_DB    = 36.0", self.source)
        self.assertIn("EXT_GAIN_SAFETY_DB = 49.2", self.source)

    def test_feedback_runs_without_external_validation_but_reports_it(self):
        self.assertIn("if not HIGH_GAIN_CHAIN_CONFIRMED:", self.source)
        self.assertIn("external 6 dB-chain validation is incomplete", self.source)
        self.assertNotIn("raise RuntimeError('6 dB feedback is locked", self.source)
        self.assertIn("MEASURED_SECOND_INPUT_DBM <= SECOND_IN_MAX_DBM", self.source)
        self.assertIn("MEASURED_FINAL_OUTPUT_DBM <= AMP_OUT_MAX_DBM", self.source)

    def test_full_map_is_disabled_for_fast_qualification(self):
        map_cells = [c for c in self.notebook['cells']
                     if 'STEP 8c - GAIN / PHASE MAP' in ''.join(c.get('source', []))]
        self.assertEqual(len(map_cells), 1)
        self.assertEqual(map_cells[0]['cell_type'], 'raw')
        self.assertIn('QUALIFICATION_ONLY = True', self.source)
        self.assertIn('DRIFT_MINUTES  = 5.0', self.source)

    def test_extreme_point_runtime_policy(self):
        self.assertIn('DIAG_TARGET_K = (0.10, 0.30, 0.50, 0.70, 0.75, 0.80, 0.85)', self.source)
        self.assertIn('(0.0017, 0.0024, 0.0031)', self.source)
        self.assertIn('REFERENCE_DRIVE_FRAC = 0.0031', self.source)
        self.assertIn('DIAG_REPEAT_COUNT = 2', self.source)
        self.assertIn('3 if predicted_k >= DIAG_ESCALATE_K', self.source)
        self.assertNotIn('two consecutive gains failed', self.source)

    def test_soft_failures_retry_and_continue(self):
        self.assertIn('for retry_mode in (False, True):', self.source)
        self.assertIn("else 'soft_measurement'", self.source)
        self.assertIn('_characterise_failed_gain', self.source)
        self.assertIn("result['attempts'] = attempts", self.source)

    def test_hard_stops_are_narrow_and_shutdown_is_unconditional(self):
        self.assertIn('class HardSafetyStop(RuntimeError):', self.source)
        self.assertIn("raise HardSafetyStop('ADC clipping risk", self.source)
        self.assertIn("raise HardSafetyStop('drive-off oscillation", self.source)
        self.assertIn("if failure_class == 'hard_safety':", self.source)
        self.assertIn('finally:\n    gen.off()\n    ps.off()', self.source)

    def test_rejected_attempts_and_raw_traces_are_exported(self):
        self.assertIn("out['attempts'] = [_plain_record(attempt)", self.source)
        self.assertIn('def _attempt_records(records):', self.source)
        self.assertIn("for key in ('before', 'measured', 'after') if key in r", self.source)
        self.assertIn("'quality_error': quality_error", self.source)

    def test_bad_run_diagnostic_figures_are_present(self):
        for text in ('Gain/drive accepted fraction',
                     'Phase/gain failures (hollow = rejected)',
                     'Bracket references',
                     'Highest valid and rejected lineshapes'):
            self.assertIn(text, self.source)

    def test_suitable_verdict_requires_nonzero_reliable_gain(self):
        self.assertIn('SAFE_FULL_MAP_GAIN>0.0', self.source)
        self.assertIn("CAMPAIGN_END_STATE = ('hard safety stop'", self.source)

    def test_compression_plots_and_diagnosis_are_present(self):
        for text in ('K/A: compression view', 'coherent response / drive',
                     'opposite-phase widths / B0', 'up/down hysteresis',
                     'external spectral evidence', 'QUALIFICATION_DIAGNOSIS',
                     "'analogue compression'", "'gain-dependent phase rotation'",
                     "'lineshape/fitting failure'", "'feedback-transfer nonlinearity"):
            self.assertIn(text, self.source)

    def test_complex_k_is_not_in_mandatory_agreement_matrix(self):
        self.assertIn('_all_est = np.column_stack([_vector, _paired, _joint])',
                      self.source)
        self.assertNotIn('_all_est = np.column_stack([_vector, _paired, _complex_pair',
                         self.source)

    def test_experimental_complex_fit_does_not_veto_trace(self):
        quality_start = self.source.index('def _fit_quality')
        quality_end = self.source.index('def _reference_trace', quality_start)
        gate = self.source[quality_start:quality_end]
        self.assertNotIn("diag['complex_lw_disagreement'] >", gate)
        self.assertIn("diag['residual_rms']", gate)
        self.assertIn("diag['structured_residual']", gate)

    def test_zero_if_receiver_policy_and_filter_validation(self):
        for text in ('def receiver_policy(', 'tone is\n    always at DC',
                     'def adaptive_settle(', 'FIR_TAPS = 309',
                     'def receiver_metadata(', "'fir_overrun'",
                     'def emulator_high_q_qualification()',
                     'HIGH_Q_TEST_VALUES = (250.0, 1000.0, 5000.0)'):
            self.assertIn(text, self.source)
        self.assertNotIn('receiver window exceeds 25% linewidth', self.source)

    def test_adaptive_high_q_grid_and_settling_formulas(self):
        tree = ast.parse(self.code_source)
        wanted = {'adaptive_frequency_grid', 'adaptive_settle'}
        functions = [n for n in tree.body
                     if isinstance(n, ast.FunctionDef) and n.name in wanted]
        namespace = dict(np=np, FS_CLK=125e6, HIGH_Q_POINTS_PER_LW=25,
                         HIGH_Q_WING_LW=4.0, FIR_SETTLE_GROUP_DELAYS=4.0,
                         FIR_TAPS=309, HIGH_Q_RESONATOR_TAU=7.0, SETTLE=0.02)
        exec(compile(ast.Module(body=functions, type_ignores=[]), '<adaptive>', 'exec'),
             namespace)
        grid = namespace['adaptive_frequency_grid'](40e6, 8e3)
        in_line = np.sum(np.abs(grid-40e6) <= 4e3)
        self.assertGreaterEqual(in_line, 25)
        settle = namespace['adaptive_settle'](8e3, 12)
        self.assertGreaterEqual(settle, 4.0*154.0/(125e6/4096.0))
        self.assertGreaterEqual(settle, 7.0/(math.pi*8e3))

    def test_high_k_pair_is_optional_but_quadrature_is_required(self):
        self.assertIn('HIGH_K_PAIR_OPTIONAL = 0.60', self.source)
        self.assertIn("'broadening SNR insufficient; optional at high K'", self.source)
        self.assertIn("row['quadrature_available']", self.source)
        self.assertIn("row['pair_requirement']", self.source)
        self.assertIn('def _broadening_probe_drive(', self.source)

    def test_wider_map_phase_policy_and_manual_external_comparison(self):
        self.assertIn('FULL_CIRCLE_TARGET_K = (0.20, 0.40, 0.60, 0.70)', self.source)
        self.assertIn('HIGH_K_SELECTED_TARGET_K = (0.75, 0.80, 0.85)', self.source)
        self.assertIn('def phase_schedule_for_k(', self.source)
        self.assertIn("EXTERNAL_MEASUREMENT = {", self.source)
        self.assertIn('MANUAL EXTERNAL COMPARISON', self.source)

    def test_rolloff_tuple_bug_is_fixed(self):
        self.assertIn('for r,d in _valid_rows', self.source)
        self.assertNotIn("[r for r in _valid_rows if r['gain']", self.source)

    def test_outputs_do_not_overwrite_control_run(self):
        self.assertIn("bench_coil_6db_results.json", self.source)
        self.assertIn("bench_coil_6db_traces.npz", self.source)
        self.assertIn("bench_coil_6db_report.md", self.source)


if __name__ == '__main__':
    unittest.main()
