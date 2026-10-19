"""Main notebook, cells 13-18: acquisition-filter prediction and calibration."""
import ast
import contextlib
import io
import json
import unittest
from unittest.mock import Mock, patch

import numpy as np
from scipy.signal import freqz

from tests.notebook import MAIN, mock_hardware, run_cells
from tests.test_manual_feedback_measurement import mock_system, namespace, plt


def filter_system(seed=1, response_fault=0.0):
    ns, active, state = mock_system(seed=seed)
    run_cells((13,), ns)
    rng = np.random.RandomState(seed)
    input_rms = float(np.std(ns['sc'].acquire.return_value[0]))*ns['ADC_RAW_VOLTS_PER_COUNT']
    def tone_capture(word, dec, n, settle, fir_mode='auto'):
        lo = word/2.0**32*ns['FS_CLK']; rate = ns['FS_CLK']/(1 << dec)
        plan = dict(centre_hz=lo, sample_rate_hz=rate, decimation_log2=dec, fir_mode=fir_mode)
        gain = ns['filter_response_components'](np.array([40.9e6]), plan)['combined'][0]
        fraction = (40.9e6-lo)/rate
        voltage = np.sqrt(2)*input_rms*np.sqrt(gain)*(1+response_fault*(fraction/.2)**2)
        tone = voltage*np.exp(2j*np.pi*fraction*np.arange(n))
        noise = voltage/500*(rng.normal(size=n)+1j*rng.normal(size=n))
        return (tone+noise)/ns['CIC_VOLTS_PER_COUNT']
    ns['capture'].side_effect = tone_capture
    return ns, active, state


def loopback_system(seed=5, amplitude_exponent=1.0, connected=True):
    """Real notebook Generator with memory registers; only analogue signals are simulated."""
    ns, active, state = filter_system(seed)
    generator = mock_hardware()['Generator']()
    read_register = generator.r
    # The actual ASG exposes the fractional step at a different read address.
    generator.r = lambda off: read_register(0x4C if off == 0x14 else off)
    ns['gen'] = generator
    def shutdown():
        state.update(ci=0, cq=0, monitor=0)
        active['count'] = 0
        generator.off()
    ns['full_shutdown'] = Mock(side_effect=shutdown)
    rng = np.random.RandomState(seed)
    def amplitude():
        frac = (generator.r(4) & 0x3FFF)/8192.
        return .7*.02*(frac/.02)**amplitude_exponent if connected and generator.r(0)&255 == 0x11 else 0.
    def source_hz():
        return generator.r(0x10)*ns['FS_CLK']/2**30
    def scope(dec, n, chan):
        t = np.arange(n)/ns['FS_CLK']
        volts = amplitude()*np.cos(2*np.pi*source_hz()*t) + rng.normal(0, .25*ns['ADC_RAW_VOLTS_PER_COUNT'], n)
        return volts/ns['ADC_RAW_VOLTS_PER_COUNT'], ns['FS_CLK']
    ns['sc'].acquire.side_effect = scope
    def capture(word, dec, n, settle, fir_mode='auto'):
        lo = word/2**32*ns['FS_CLK']; rate = ns['FS_CLK']/(1 << dec)
        plan = dict(centre_hz=lo, sample_rate_hz=rate, decimation_log2=dec, fir_mode=fir_mode)
        gain = ns['filter_response_components'](np.array([source_hz()]), plan)['combined'][0]
        wave = amplitude()*np.sqrt(gain)*np.exp(2j*np.pi*(source_hz()-lo)*np.arange(n)/rate)
        return (wave+1e-6*(rng.normal(size=n)+1j*rng.normal(size=n)))/ns['CIC_VOLTS_PER_COUNT']
    ns['capture'].side_effect = capture
    return ns, active, state


class AcquisitionFilterTests(unittest.TestCase):
    def tearDown(self):
        plt.close('all')

    def quiet(self, function, *args, **kwargs):
        # Existing external-tone simulations remain a separate source mode.
        if function.__name__ == 'measure_acquisition_filters':
            kwargs.setdefault('source', 'external')
        with contextlib.redirect_stdout(io.StringIO()), patch.object(plt, 'show'):
            return function(*args, **kwargs)

    def test_workflow_order_and_opt_in_correction_selection(self):
        book = json.loads(MAIN.read_text(encoding='utf-8'))
        cells = book['cells']
        sources = [''.join(c['source']) for c in cells]
        calibration_index = next(i for i, s in enumerate(sources)
                                 if 'def inspect_acquisition_filters(' in s)
        selection_index = next(i for i, s in enumerate(sources)
                               if s.startswith('# Explicit correction selection.'))
        manual_index = next(i for i, s in enumerate(sources)
                            if 'def measure_manual_feedback(' in s)
        self.assertLess(calibration_index, selection_index)
        self.assertLess(selection_index, manual_index)
        # Explicitly running selection uses labelled models unless the operator
        # chooses accepted live results; it cannot start a capture.
        ns = {'CalibrationError': RuntimeError}
        with contextlib.redirect_stdout(io.StringIO()) as output:
            exec(sources[selection_index], ns)
        self.assertIsNone(ns['BASELINE_RESPONSE'])
        self.assertIsNone(ns['FEEDBACK_RESPONSE'])
        self.assertIn('not a measured calibration', output.getvalue())
        measured_selection = sources[selection_index].replace(
            '# BASELINE_RESPONSE = FILTER_BASELINE_CALIBRATION',
            'BASELINE_RESPONSE = FILTER_BASELINE_CALIBRATION').replace(
            '# FEEDBACK_RESPONSE = FILTER_FEEDBACK_CALIBRATION',
            'FEEDBACK_RESPONSE = FILTER_FEEDBACK_CALIBRATION')
        selected = dict(ns, FILTER_BASELINE_CALIBRATION={'responses': {'bypass': {'accepted': True}}},
                        FILTER_FEEDBACK_CALIBRATION={'responses': {'auto': {'accepted': False}}})
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, 'not an accepted'):
            exec(measured_selection, selected)
        selected['FILTER_FEEDBACK_CALIBRATION']['responses']['auto']['accepted'] = True
        with contextlib.redirect_stdout(io.StringIO()):
            exec(measured_selection, selected)
        self.assertIs(selected['BASELINE_RESPONSE'], selected['FILTER_BASELINE_CALIBRATION']['responses']['bypass'])
        self.assertIs(selected['FEEDBACK_RESPONSE'], selected['FILTER_FEEDBACK_CALIBRATION']['responses']['auto'])
        # All newly presented action cells are opt-in, and pass the selection.
        examples = [s for c, s in zip(cells, sources)
                    if c['cell_type'] == 'code' and
                    (s.startswith('# manual_baseline =') or s.startswith('# measurement ='))]
        self.assertEqual(len(examples), 2)
        for s, key in zip(examples, ('BASELINE_RESPONSE', 'FEEDBACK_RESPONSE')):
            self.assertEqual(ast.parse(s).body, [])
            calls = []
            exec('\n'.join(line[2:] for line in s.splitlines()),
                 dict(ns, manual_baseline={}, measure_manual_feedback=lambda **kw: calls.append(kw)))
            self.assertIs(calls[0]['response_calibration'], ns[key])

    def test_broad_and_narrow_calibration_cover_manual_examples(self):
        ns = namespace()
        for dec, fraction, span in ((6, .30, 1e6), (8, .20, 180e3)):
            self.assertLess(span, 2*fraction*ns['FS_CLK']/(1 << dec))

    def test_broad_live_example_with_synthetic_cic_response(self):
        ns, _, state = filter_system()
        result = self.quiet(ns['measure_acquisition_filters'], decimation_log2=6,
                            fractions=np.linspace(-.30, .30, 13),
                            repeats=2, samples_per_record=1024, settle_s=.01)
        self.assertTrue(result['accepted'], result.get('rejection_reasons'))
        self.assertTrue(result['responses']['bypass']['accepted'])

    def test_out1_loopback_uses_actual_generator_and_quantized_frequency(self):
        for dec in (6, 8):
            ns, _, state = loopback_system()
            # Prove stale burst/fractional settings are cleared before starting.
            for register in (0x4C, 0x18, 0x1C, 0x20): ns['gen'].w(register, 123)
            r = self.quiet(ns['measure_acquisition_filters'], source='out1',
                           decimation_log2=dec, fractions=np.linspace(-.2, .2, 9),
                           repeats=2, samples_per_record=1024, settle_s=.01)
            self.assertTrue(r['accepted'], r['rejection_reasons'])
            self.assertEqual(r['tone_hz'], ns['gen'].r(0x10)*ns['FS_CLK']/2**30)
            self.assertAlmostEqual(r['loopback_startup']['power_linearity_ratio'], 1., delta=.01)
            self.assertFalse(r['absolute_voltage_calibrated'])
            self.assertFalse(r['independent_clock_test'])
            self.assertEqual(ns['gen'].r(4), 0)
            self.assertEqual(ns['gen'].r(0)&255, 0xC0)
            self.assertEqual(state['ci'], 0); self.assertEqual(state['monitor'], 0)
            self.assertTrue(r['shutdown_verified'])
            self.assertTrue(all(row['source']=='out1' for row in r['responses'].values()))

    def test_out1_missing_cable_and_compression_refuse_scan(self):
        for kwargs, message in ((dict(connected=False), 'too weak'),
                                (dict(amplitude_exponent=.6), 'linearity')):
            ns, _, _ = loopback_system(**kwargs)
            with self.assertRaisesRegex(RuntimeError, message):
                self.quiet(ns['measure_acquisition_filters'], source='out1', settle_s=.01)
            ns['capture'].assert_not_called()
            self.assertEqual(ns['gen'].r(4), 0)
            self.assertTrue(ns['LAST_FILTER_CALIBRATION']['shutdown_verified'])

    def test_out1_invalid_drive_table_and_interrupt_shutdown(self):
        for drive in (-.1, .1, 0., 1e-7, np.nan):
            ns, _, _ = loopback_system()
            with self.assertRaises(ValueError):
                self.quiet(ns['measure_acquisition_filters'], source='out1', drive_fraction=drive)
            self.assertEqual(ns['gen'].r(4), 0)
            ns['capture'].assert_not_called()
        ns, _, _ = loopback_system()
        ns['gen'].load_sine = lambda: None
        with self.assertRaisesRegex(RuntimeError, 'table readback'):
            self.quiet(ns['measure_acquisition_filters'], source='out1')
        self.assertFalse(any(off == 0 and val&255 == 0x11 for off, val in ns['gen'].transport.write_log))
        for error in (KeyboardInterrupt(), RuntimeError('DMA failed')):
            ns, _, _ = loopback_system(); ns['capture'].side_effect = error
            with self.assertRaises(type(error)):
                self.quiet(ns['measure_acquisition_filters'], source='out1', settle_s=.01)
            self.assertEqual(ns['gen'].r(4), 0)
            self.assertTrue(ns['LAST_FILTER_CALIBRATION']['shutdown_verified'])

    def test_out1_register_changes_during_capture_shutdown(self):
        for register, value in ((4, 999), (0x10, 0), (0x24, 123), (0, 0xC00111)):
            ns, _, _ = loopback_system()
            capture = ns['capture'].side_effect
            def corrupt(*args, **kwargs):
                data = capture(*args, **kwargs)
                ns['gen'].w(register, value)
                return data
            ns['capture'].side_effect = corrupt
            with self.assertRaises(RuntimeError):
                self.quiet(ns['measure_acquisition_filters'], source='out1', settle_s=.01)
            self.assertEqual(ns['gen'].r(4), 0)
            self.assertEqual(ns['gen'].r(0)&255, 0xC0)
            self.assertFalse(ns['LAST_FILTER_CALIBRATION']['accepted'])

    def test_cic_exact_response_matches_independent_boxcar_cascade(self):
        ns = namespace()
        for dec in (6, 8, 12):
            ratio = 1 << dec
            offsets = np.array([0, .05, .2, .4, .9, 1.1])
            _, box = freqz(np.ones(ratio)/ratio, worN=2*np.pi*offsets/ratio)
            plan = dict(centre_hz=0., sample_rate_hz=125e6/ratio, decimation_log2=dec)
            got = ns['cic_power_response'](offsets*plan['sample_rate_hz'], plan)
            np.testing.assert_allclose(got, abs(box)**8, atol=1e-12)

    def test_flat_passband_and_real_stopband_not_unity(self):
        ns = namespace()
        for dec in range(6, 13):
            rate = 125e6/(1 << dec)
            plan = dict(centre_hz=40.9e6, sample_rate_hz=rate, decimation_log2=dec)
            f = 40.9e6+np.linspace(-.2, .2, 801)*rate
            result = ns['filter_response_components'](f, plan)
            self.assertEqual(result['fir_bypassed'], dec < 8)
            if dec >= 8:
                self.assertLess(np.ptp(10*np.log10(result['combined'])), .06)
                g, _ = ns['acquisition_response_power'](np.array([40.9e6+.3*rate]), plan)
                self.assertLess(g[0], 1e-8)
            else:
                np.testing.assert_allclose(result['fir'], 1)
        report = self.quiet(filter_system()[0]['inspect_acquisition_filters'])
        self.assertAlmostEqual(report['enbw_hz'], 89.417, delta=.03)
        self.assertAlmostEqual(report['passband_full_span_hz'], 195312.5)

    def test_bypass_and_bounded_inverse(self):
        ns = namespace(); rate=125e6/256
        plan = dict(centre_hz=40.9e6, sample_rate_hz=rate, decimation_log2=8)
        f = 40.9e6+np.array([0, .1, .2, .3])*rate
        expected = np.array([1., 3., 2., 1.])*1e-12
        gain, _ = ns['acquisition_response_power'](f, plan)
        corrected = ns['correct_acquisition_response'](dict(frequency_hz=f,psd_v2_per_hz=expected*gain), plan)
        np.testing.assert_allclose(corrected['psd_v2_per_hz'][:3], expected[:3])
        self.assertTrue(np.isnan(corrected['psd_v2_per_hz'][-1]))
        bypass = ns['filter_response_components'](f, dict(plan, fir_mode='bypass'))
        np.testing.assert_allclose(bypass['combined'], bypass['cic'])

    def test_window_weighted_parseval_for_stationary_and_burst_records(self):
        ns,_,_=filter_system(); rng=np.random.RandomState(4)
        x=rng.normal(size=(3,4096))+1j*rng.normal(size=(3,4096))
        x[0,:200]*=30  # unweighted vs windowed power would fail incorrectly
        self.assertTrue(ns['validate_fft_parseval'](x)['accepted'])
        self.assertFalse(ns['validate_fft_parseval'](x, {'psd_v2_per_hz': np.ones(4096), 'bin_hz': 1})['accepted'])
        self.assertFalse(ns['validate_fft_parseval'](np.zeros((2,512)))['accepted'])

    def test_tone_amplitude_and_positive_negative_frequency_off_bin(self):
        ns,_,_=filter_system();rate=125e6/256;n=4096;t=np.arange(n)/rate
        for f in (0, 10331.23, -27789.4):
            x=np.array([.03*np.exp(2j*np.pi*f*t+1j*phase) for phase in (0,.2,.8)])
            fit=ns['analyse_filter_tone_records'](x,rate,f)
            self.assertAlmostEqual(fit['amplitude_v'],.03,delta=1e-6)
            self.assertAlmostEqual(fit['observed_offset_hz'],f,delta=.01)
        # FFT mean removal would erase a tone at LO: the tone estimator retains it.

    def test_live_scan_accepts_known_filter_and_reuses_only_matching_calibration(self):
        ns,active,_=filter_system()
        r=self.quiet(ns['measure_acquisition_filters'],repeats=2,samples_per_record=1024,
                     fractions=np.linspace(-.2,.2,9))
        self.assertTrue(r['accepted'],r['rejection_reasons'])
        self.assertTrue(r['shutdown_verified']);self.assertEqual(active['count'],0)
        self.assertEqual(ns['capture'].call_count,36)
        profile=ns['acquisition_fir_profile']()
        plan=dict(centre_hz=41e6,sample_rate_hz=125e6/256,decimation_log2=8,
                  fir_half_counts=profile['half_counts'])
        cal=r['responses']['auto']
        g,_=ns['acquisition_response_power'](np.array([41e6,41e6+2e5]),plan,cal)
        self.assertAlmostEqual(g[0],1,delta=.01); self.assertTrue(np.isnan(g[1]))
        for bad in (dict(cal,accepted=False),dict(cal,decimation_log2=9),dict(cal,fir_digest='bad'),
                    dict(cal,clock_hz=1),dict(cal,fir_bypassed=True)):
            with self.assertRaises(ValueError): ns['acquisition_response_power'](np.array([41e6]),plan,bad)

    def test_live_scan_rejects_wrong_response_and_weak_tone(self):
        ns,_,_=filter_system(response_fault=.2)
        r=self.quiet(ns['measure_acquisition_filters'],repeats=2,samples_per_record=1024,
                     fractions=np.linspace(-.2,.2,9))
        self.assertFalse(r['accepted'])
        self.assertTrue(any('model error' in v for v in r['responses']['auto']['rejection_reasons']))
        ns,_,_=filter_system(); rng=np.random.RandomState(19)
        ns['capture'].side_effect=lambda word,dec,n,settle,fir_mode: (rng.normal(size=n)+1j*rng.normal(size=n))*1e5
        r=self.quiet(ns['measure_acquisition_filters'],repeats=2,samples_per_record=1024,
                     fractions=np.linspace(-.2,.2,9))
        self.assertFalse(r['accepted'])

    def test_live_scan_shutdown_on_fault_and_interrupt(self):
        for failure in (RuntimeError('DMA failed'),KeyboardInterrupt()):
            ns,active,_=filter_system();ns['capture'].side_effect=failure
            with self.assertRaises(type(failure)):
                self.quiet(ns['measure_acquisition_filters'],repeats=2,samples_per_record=1024)
            self.assertEqual(active['count'],0)
            self.assertTrue(ns['LAST_FILTER_CALIBRATION']['shutdown_verified'])

    def test_fir_readback_failure_restores_address_and_does_not_write_table(self):
        ns,_,_=filter_system();ns['acq'].r.side_effect=lambda off: 0
        with self.assertRaisesRegex(RuntimeError,'address readback'):
            ns['read_acquisition_fir']()
        self.assertEqual(ns['acq'].w.call_args.args,(0x40,0))
        self.assertTrue(all(call.args[0] == 0x40 for call in ns['acq'].w.call_args_list))

    def test_real_capture_control_bits_status_failures_and_settling(self):
        for dec, mode, status, failure in ((8,'bypass',4,False), (12,'auto',0,False),
                (6,'auto',6,False), (8,'auto',1,True), (8,'auto',2,True),
                (8,'auto',8,True), (8,'auto',4,True)):
            ns=mock_hardware()
            registers={0x34:32,0x38:status}
            acq=Mock()
            acq.w.side_effect=lambda off,value: registers.__setitem__(off,value)
            acq.r.side_effect=lambda off: registers.get(off,0)
            acq.tune_word.side_effect=lambda value: registers.__setitem__(4,value)
            ns.update(acq=acq, MEM_START=0x1E000000, MEM_STOP=0x1E7FFFF8,
                      CAPTURE_BACKEND=None, _poison=lambda count: None,
                      _read_region=lambda count: np.arange(count//4,dtype='<u4').tobytes())
            with patch.object(ns['time'],'sleep') as sleep:
                if failure:
                    with self.assertRaises(RuntimeError): ns['capture'](123,dec,32,settle=0,fir_mode=mode)
                else:
                    got=ns['capture'](123,dec,32,settle=0,fir_mode=mode)
                    self.assertEqual(got.shape,(32,))
                    if dec==12: self.assertGreaterEqual(sleep.call_args_list[0].args[0],317/(125e6/4096))
            self.assertEqual(registers[0],0)
            running=[c.args[1] for c in acq.w.call_args_list if c.args[0]==0 and c.args[1]&1]
            self.assertTrue(all(bool(value&64)==(mode=='bypass') for value in running))

    def test_live_input_guard_wrong_build_and_adc_scale_validation(self):
        for fault in ('dc','clipping','build'):
            ns,active,_=filter_system()
            if fault=='build': ns['acq'].build_id.return_value=0
            else: ns['sc'].acquire.return_value=(np.ones(4096)*(2000 if fault=='dc' else 8191),125e6)
            with self.assertRaises(RuntimeError):
                self.quiet(ns['measure_acquisition_filters'],repeats=2,samples_per_record=1024)
            self.assertTrue(ns['LAST_FILTER_CALIBRATION']['shutdown_verified'])
            ns['capture'].assert_not_called()
        ns,_,_=filter_system()
        adc=ns['calibrate_adc_scale']([.01,.02,.03],[100,200,300])
        self.assertTrue(adc['accepted']); self.assertAlmostEqual(adc['volts_per_count'],1e-4)
        self.assertFalse(ns['calibrate_adc_scale']([.01,.02,.03],[100,150,180])['accepted'])
        with self.assertRaises(ValueError): ns['calibrate_adc_scale']([.01,.02,np.nan],[100,200,300])


if __name__=='__main__':
    unittest.main()
