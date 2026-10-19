"""Main notebook, cells 1-12: configuration, helpers, registers and shutdown."""
import ast
import contextlib
import io
import json
import re
import unittest

import numpy as np

from tests.notebook import (HIGH_K, LIBRARY, MAIN, ROOT, MemoryTransport,
                            QualifiedMemoryTransport, code_cells, mock_hardware, run_cells)


class NotebookStructureTests(unittest.TestCase):
    def test_cells_are_numbered_documented_and_clean(self):
        book = json.loads(MAIN.read_text(encoding='utf-8'))
        cells = book['cells']
        numbers = [c['metadata']['code_cell_number'] for c in cells if c['cell_type'] == 'code']
        self.assertEqual(numbers, list(range(1, len(numbers) + 1)))
        for index, cell in enumerate(cells):
            if cell['cell_type'] != 'code':
                continue
            heading = ''.join(cells[index - 1]['source'])
            self.assertTrue(heading.startswith('## %d —' % cell['metadata']['code_cell_number']),
                            'code cell %d lacks its numbered heading' % index)

    def test_cells_parse_for_board_python_and_carry_no_outputs(self):
        for path in (MAIN, HIGH_K):
            for number, source in code_cells(path).items():
                ast.parse(source, feature_version=(3, 5))   # Python on the board
            for cell in json.loads(path.read_text(encoding='utf-8'))['cells']:
                if cell['cell_type'] == 'code':
                    self.assertIsNone(cell['execution_count'])
                    self.assertEqual(cell['outputs'], [])

    def test_board_numpy_compatibility(self):
        # The NumPy on the Red Pitaya requires a numeric rcond for lstsq.
        for path in (MAIN, HIGH_K):
            source = '\n'.join(code_cells(path).values())
            self.assertNotIn('rcond=None', source)

    def test_notebook_build_id_matches_fpga_header(self):
        header = (ROOT / 'fpga' / 'build_id.vh').read_text(encoding='utf-8')
        self.assertIn("32'hFE76AE09", header)
        self.assertEqual(run_cells(LIBRARY)['BUILD_ID_EXPECTED'], '0xFE76AE09')

    def test_embedded_fir_table_equals_qualified_rtl_coefficients(self):
        header = (ROOT / 'fpga' / 'fir_coeffs.vh').read_text(encoding='utf-8')
        rtl = [int(sign + value) for _, sign, value in
               re.findall(r"coef\[\s*(\d+)\]\s*=\s*(-?)18'sd(\d+);", header)]
        ns = run_cells(LIBRARY + (12,))
        self.assertEqual(rtl, ns['QUALIFIED_FIR_HALF_COUNTS'])
        profile = ns['acquisition_fir_profile']()
        self.assertEqual(len(profile['taps']), 309)
        self.assertEqual(np.sum(profile['taps']), 1)


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.ns = run_cells(LIBRARY)

    def test_official_red_pitaya_limits(self):
        limits = self.ns['RP_LIMITS']
        self.assertEqual(limits['adc_bits'], 14)
        self.assertEqual(limits['sample_rate_hz'], 125e6)
        self.assertEqual(limits['input_impedance_ohm'], 1e6)
        self.assertEqual(limits['input_lv_full_scale_vpk'], 1.0)
        self.assertEqual(limits['input_lv_absolute_max_vpk'], 6.0)
        self.assertEqual(limits['output_full_scale_vpk_into_50ohm'], 1.0)

    def test_quantized_vector_reports_actual_words_and_phase(self):
        row = self.ns['quantized_feedback_vector'](64, 0.0, 40.9e6)
        self.assertEqual(row['ci_word'], row['ci_signed'] & 0xFFFF)
        self.assertEqual(row['cq_word'], row['cq_signed'] & 0xFFFF)
        self.assertLess(abs(row['phase_error_deg']), 1.0)

    def test_configuration_review_plans_the_discovery_capture(self):
        ns = run_cells((4,), self.ns)
        plan = ns['INITIAL_ACQUISITION_PLAN']
        self.assertGreaterEqual(plan['usable_span_hz'], 1.56e6)
        self.assertEqual(plan['decimation_log2'], 6)
        self.assertEqual(plan['fir_expected_state'], 'bypassed')

    def test_acquisition_plan_adapts_from_q100_to_high_q_and_shift(self):
        plan = self.ns['plan_passive_acquisition']
        broad = plan(40e6, 100, linewidths_each_side=1.5)
        narrow = plan(40e6, 10000, linewidths_each_side=1.5)
        shifted = plan(40e6, 50000, 120e3, linewidths_each_side=1.5,
                       centre_on_expected_shift=True)
        with self.assertRaisesRegex(self.ns['CalibrationError'], 'qualified FPGA register range'):
            plan(40.9e6, 150, min_decimation_log2=4)
        self.assertGreaterEqual(broad['usable_span_hz'], 3 * 400e3)
        self.assertGreaterEqual(narrow['bins_per_linewidth'], 20)
        self.assertLess(narrow['sample_rate_hz'], broad['sample_rate_hz'])
        self.assertLess(narrow['bin_hz'], broad['bin_hz'])
        self.assertEqual(shifted['centre_hz'], 40.12e6)
        self.assertGreaterEqual(shifted['bins_per_linewidth'], 20)

    def test_planner_refuses_rather_than_truncates(self):
        for q_value in (50, 100, 150, 1000, 10000, 50000, 100000):
            for shift_hz in (-1e6, 0.0, 1e6):
                try:
                    result = self.ns['plan_passive_acquisition'](
                        40.9e6, q_value, shift_hz, centre_on_expected_shift=True)
                except self.ns['CalibrationError'] as error:
                    # A broad resonance plus a 1 MHz shift is wider than the
                    # largest qualified capture: refusing is the safe answer.
                    self.assertIn('largest qualified capture', str(error))
                    continue
                self.assertGreaterEqual(result['bins_per_linewidth'], 20)
                self.assertAlmostEqual(result['centre_hz'], 40.9e6 + shift_hz)

    def test_cic_dome_is_corrected_and_limited_to_trustworthy_band(self):
        ns = run_cells((12,), self.ns)
        plan = ns['plan_passive_acquisition'](40.9e6, 150, min_decimation_log2=6)
        frequency = np.linspace(40.9e6 - 0.9e6, 40.9e6 + 0.9e6, 2001)
        raw = ns['cic_power_response'](frequency, plan)
        corrected = ns['correct_acquisition_response'](
            {'frequency_hz': frequency, 'psd_v2_per_hz': raw}, plan)
        valid = (np.abs(frequency - 40.9e6) <= 0.5e6) & corrected['response_correction_valid']
        self.assertGreater(np.count_nonzero(valid), 1000)
        self.assertAlmostEqual(float(np.nanmedian(corrected['psd_v2_per_hz'][valid])), 1.0, places=10)
        self.assertLess(raw[0], raw[len(raw) // 2])
        self.assertEqual(corrected['response_source'], 'modelled exact CIC; FIR bypassed')


class RegisterAndShutdownTests(unittest.TestCase):
    def test_capture_backend_and_memory_registers(self):
        ns = mock_hardware()
        phase = ns['PhaseShift']()
        phase.w(0x00, 123)
        self.assertEqual(phase.readback()['ci'], 123)
        phase.off()
        self.assertEqual((phase.readback()['ci'], phase.readback()['cq']), (0, 0))
        ns['CAPTURE_BACKEND'] = lambda lo, dec, n, settle: np.arange(n) + 0j
        self.assertEqual(len(ns['capture'](123, 8, 32, settle=0)), 32)

    def test_identity_cell_shuts_down_and_requires_qualified_build(self):
        ns = mock_hardware(QualifiedMemoryTransport)
        run_cells((11,), ns)
        self.assertEqual(ns['CURRENT_BUILD_ID'], '0xFE76AE09')
        with self.assertRaisesRegex(RuntimeError, 'wrong FPGA identity'):
            run_cells((11,), mock_hardware(MemoryTransport))

    def test_full_shutdown_clears_out2_monitor(self):
        ns = run_cells((11,), mock_hardware(QualifiedMemoryTransport))
        ns['ps'].monitor('input', shift=0)
        self.assertEqual(ns['ps'].readback()['monitor'], 1)
        with contextlib.redirect_stdout(io.StringIO()):
            ns['full_shutdown']()
        self.assertEqual(ns['ps'].readback()['monitor'], 0)

    def test_full_shutdown_attempts_every_device_after_a_failure(self):
        ns = run_cells((11,), mock_hardware(QualifiedMemoryTransport))
        ns['ps'].w(0x00, 77)
        ns['acq'].w(0x00, 1)

        class FailingGenerator(object):
            def off(self):
                raise IOError('injected')

            def assert_b_zero(self):
                return True

        ns['gen'] = FailingGenerator()
        with self.assertRaisesRegex(RuntimeError, 'FULL SHUTDOWN COULD NOT BE VERIFIED'):
            ns['full_shutdown']()
        self.assertEqual(ns['ps'].readback()['ci'], 0)    # feedback still cleared
        self.assertEqual(ns['acq'].r(0x00), 0)            # acquisition still stopped

    def test_out2_monitor_rejects_illegal_shift_and_generator_b_must_be_zero(self):
        ns = mock_hardware()
        phase = ns['PhaseShift']()
        with self.assertRaises(ValueError):
            phase.monitor('input', shift=8)
        generator = ns['Generator']()
        generator.off()
        generator.w(0x24, 1)  # injected channel-B amplitude contamination
        with self.assertRaises(RuntimeError):
            generator.assert_b_zero()


if __name__ == '__main__':
    unittest.main()
