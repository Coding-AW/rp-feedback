def measure_manual_feedback(gain=None, phase_deg=0.0, coefficient_counts=None,
                            frequency_range_hz=(40.4e6, 41.4e6),
                            decimation_log2=6, samples_per_record=8192,
                            averages=32, repeats=1, fit_range_hz=None,
                            q_guess=150.0, q_bounds=(20.0, 1e6),
                            lo_hz=None, phase_reference_hz=None, settle_s=0.10,
                            max_input_vpk=None, max_output_vpk=None,
                            max_power_ratio=10.0, max_active_seconds=30.0,
                            response_calibration=None, label='manual measurement',
                            mode='baseline', baseline_measurement=None, fir_mode='auto',
                            show_plots=True, map_safety_mode=False,
                            minimum_edge_coverage_linewidths=1.0,
                            maximum_fit_uncertainty_linewidths=0.25):
    """Measure a baseline once, then independent feedback spectra on later calls.

    Paste this single definition after the notebook's standard hardware and
    passive-acquisition helpers. No campaign, JSON, or Step 9A is used.
    mode='baseline': acquire feedback-off only; keep the returned dictionary.
    mode='feedback': pass that dictionary as baseline_measurement; acquire only
    the selected feedback state, with its own window, resolution and fit.
    mode='bracketed' retains the optional same-window off/on/off experiment.
    fir_mode='auto' enables the installed FIR at R>=256; 'bypass' measures CIC only.
    Set EITHER gain (signed, dimensionless) OR coefficient_counts (nonnegative
    integer, gain = count/16384). Neither argument means a zero-feedback test.
    decimation_log2=6 means divide 125 MHz by 64, NOT decimation by six.
    averages is the number of independent FFT powers averaged per state;
    repeats repeats the selected state (or bracketed triplet). Records are discarded.

    Returns spectra, Lorentzian fits, per-repeat results, controls and warnings.
    Also retains the latest/partial result in LAST_MANUAL_FEEDBACK_MEASUREMENT.
    A call never leaves feedback running. Ctrl-C attempts full shutdown, but
    cannot protect against a hung/crashed kernel: retain a physical disconnect.
    """
    import time
    import copy
    import numpy as np
    import matplotlib.pyplot as plt
    from scipy.optimize import least_squares
    from scipy.ndimage import median_filter

    global LAST_MANUAL_FEEDBACK_MEASUREMENT
    required = ('acq', 'gen', 'ps', 'sc', 'capture', 'full_shutdown',
                'correct_acquisition_response', 'quantized_feedback_vector', 'read_acquisition_fir',
                'FS_CLK', 'RP_LIMITS', 'BUILD_ID_EXPECTED', 'ADC_RANGE',
                'ADC_RAW_VOLTS_PER_COUNT', 'CIC_VOLTS_PER_COUNT',
                'ADC_OPERATING_GUARD_VPK', 'OUT1_OPERATING_GUARD_VPK',
                'IN1_DC_OFFSET_MAX_V', 'MIN_ACQUISITION_DECIMATION_LOG2',
                'MAX_ACQUISITION_DECIMATION_LOG2')
    missing = [name for name in required if name not in globals()]
    if missing:
        raise RuntimeError('Manual measurement needs the standard configuration, '
                           'hardware/identity and cell 12 acquisition helpers. '
                           'Missing: %s. No hardware was accessed.' % ', '.join(missing))
    result = {'label': str(label), 'status': 'initialising', 'spectra': {},
              'fits': {}, 'runs': [], 'warnings': [], 'shutdown_verified': False,
              'created_epoch_s': time.time(),
              'mode': mode, 'recovery_measured': False, 'filter_model_version': 2,
              'electrode_voltage_directly_measured': False,
              'feedback_path_transfer_directly_measured': False}
    LAST_MANUAL_FEEDBACK_MEASUREMENT = result
    try:
        full_shutdown()
        if fir_mode not in ('auto', 'bypass'):
            raise ValueError("fir_mode must be 'auto' or 'bypass'; CIC order is fixed in this FPGA.")
        fir_profile = read_acquisition_fir()
        if ADC_RANGE != 'LV':
            raise ValueError('This helper uses the notebook LV ADC calibration. Restore the '
                             'matching LV jumper/range configuration before using it; do not '
                             'interpret HV input codes with the LV volts-per-count scale.')
        if gain is not None and coefficient_counts is not None:
            raise ValueError('Choose gain OR coefficient_counts, not both. For count 32 '
                             'use coefficient_counts=32 or gain=32/16384.0.')
        signed_gain = 0.0 if gain is None else float(gain)
        if coefficient_counts is not None:
            value = float(coefficient_counts)
            if not np.isfinite(value) or value != int(value) or value < 0:
                raise ValueError('coefficient_counts must be a nonnegative integer; zero is an off-only test.')
            signed_gain = value/16384.0
        if not np.isfinite(signed_gain) or abs(signed_gain) >= 1.99:
            raise ValueError('The existing phase-shifter interface requires |gain| < 1.99. '
                             'This digital range is NOT a safe physical-loop gain range.')
        count = int(round(abs(signed_gain)*16384.0))
        if mode not in ('baseline', 'feedback', 'bracketed'):
            raise ValueError("mode must be 'baseline', 'feedback', or 'bracketed'.")
        if mode == 'baseline' and count:
            raise ValueError("Baseline mode cannot apply gain. First call with mode='baseline' "
                             "and no gain; then use mode='feedback', baseline_measurement=your_result.")
        if mode != 'feedback' and baseline_measurement is not None:
            raise ValueError("baseline_measurement is only used with mode='feedback'.")
        if mode == 'feedback':
            base = baseline_measurement
            if (not isinstance(base, dict) or base.get('mode') != 'baseline' or
                    base.get('status') != 'complete' or not base.get('shutdown_verified') or
                    not base.get('fits', {}).get('before', {}).get('accepted')):
                raise ValueError("A successful mode='baseline' result is required. Measure it once "
                                 "with a broad enough window; do not substitute a failed fit or active result.")
            if base.get('filter_model_version') != 2:
                raise ValueError('This baseline predates the corrected CIC x FIR model. Acquire a new broad baseline '
                                 'once with the updated function, then reuse it for subsequent feedback measurements.')
            expected_context = (str(BUILD_ID_EXPECTED), ADC_RANGE, float(ADC_RAW_VOLTS_PER_COUNT),
                                float(CIC_VOLTS_PER_COUNT), float(FS_CLK))
            if tuple(base.get('input_context', ())) != expected_context:
                raise ValueError('Board identity, range, clock or input scaling differs from the cached baseline. '
                                 'Acquire a new baseline before applying feedback.')
            for key in ('f0_hz', 'q', 'linewidth_hz'):
                if not np.isfinite(base['fits']['before'].get(key, np.nan)) or base['fits']['before'][key] <= 0:
                    raise ValueError('Cached baseline has an invalid %s; acquire a new baseline.' % key)
            # Own copies prevent accumulation/refitting from changing the saved baseline.
            result['spectra']['before'] = copy.deepcopy(base['spectra']['before'])
            result['fits']['before'] = copy.deepcopy(base['fits']['before'])
            result['baseline_age_s'] = max(0.0, time.time()-base['created_epoch_s'])
            result['baseline_label'] = base['label']
            result['baseline_controls'] = copy.deepcopy(base['controls'])
            result['comparison_note'] = ('Historical baseline: drift and spectral recovery are not measured. '
                                         'Reacquire after any physical setup change or suspected drift.')
        result['input_context'] = (str(BUILD_ID_EXPECTED), ADC_RANGE, float(ADC_RAW_VOLTS_PER_COUNT),
                                   float(CIC_VOLTS_PER_COUNT), float(FS_CLK))
        if signed_gain != 0 and count == 0:
            raise ValueError('Requested gain rounds to zero coefficients. Use zero explicitly '
                             'for a control measurement, or at least one coefficient count.')
        if not isinstance(show_plots, (bool, np.bool_)) or not isinstance(map_safety_mode, (bool, np.bool_)):
            raise ValueError('show_plots and map_safety_mode must be Boolean values.')
        if map_safety_mode and mode != 'feedback':
            raise ValueError('map_safety_mode is reserved for feedback points managed by run_feedback_map().')
        if not (0.10 <= float(minimum_edge_coverage_linewidths) <= 2.0):
            raise ValueError('minimum_edge_coverage_linewidths must be 0.10..2.0. Lower values allow a broadened peak near a window edge but do not remove centre, resolution, or uncertainty checks.')
        if not (0.10 <= float(maximum_fit_uncertainty_linewidths) <= 1.0):
            raise ValueError('maximum_fit_uncertainty_linewidths must be 0.10..1.0. It limits both centre and linewidth 1-sigma uncertainty relative to fitted linewidth.')
        if not np.isfinite(phase_deg):
            raise ValueError('phase_deg must be a finite angle in degrees.')
        applied_phase = (float(phase_deg)+(180.0 if signed_gain < 0 else 0.0)) % 360.0
        for name, value, low, high in (
                ('averages', averages, 4, 1024), ('repeats', repeats, 1, 20),
                ('samples_per_record', samples_per_record, 256, 65536),
                ('decimation_log2', decimation_log2,
                 MIN_ACQUISITION_DECIMATION_LOG2, MAX_ACQUISITION_DECIMATION_LOG2)):
            if not np.isfinite(value) or value != int(value) or not low <= value <= high:
                raise ValueError('%s must be an integer in %d..%d; received %r.' % (name, low, high, value))
        n, averages, repeats, decimation_log2 = map(int, (samples_per_record, averages, repeats, decimation_log2))
        if n & (n-1):
            raise ValueError('samples_per_record must be a power of two: 4096, 8192, 16384, etc.')
        low_hz, high_hz = map(float, frequency_range_hz)
        fit_low, fit_high = map(float, frequency_range_hz if fit_range_hz is None else fit_range_hz)
        q_low, q_high = map(float, q_bounds)
        centre = (low_hz+high_hz)/2.0 if lo_hz is None else float(lo_hz)
        reference = (fit_low+fit_high)/2.0 if phase_reference_hz is None else float(phase_reference_hz)
        if mode == 'feedback' and phase_reference_hz is None:
            # Acquisition LO/window changes must not silently rotate the feedback vector.
            reference = float(base['controls']['phase_reference_hz'])
        values = (low_hz, high_hz, fit_low, fit_high, centre, reference,
                  q_low, q_high, q_guess, settle_s, max_active_seconds, max_power_ratio)
        if not np.all(np.isfinite(values)):
            raise ValueError('Frequency ranges, Q values, settling time and guards must all be finite.')
        rf_limit = min(FS_CLK/2, RP_LIMITS['input_bandwidth_hz'], RP_LIMITS['output_bandwidth_hz'])
        if not (0 < low_hz < high_hz < rf_limit and low_hz <= fit_low < fit_high <= high_hz
                and 0 < reference < rf_limit and 0 < q_low < q_guess < q_high):
            raise ValueError('Use an ordered positive frequency range within %.3f MHz, '
                             'a fit range inside it, and q_low < q_guess < q_high.' % (rf_limit/1e6))
        if settle_s < 0.01 or not 1 <= max_active_seconds <= 300 or max_power_ratio < 1:
            raise ValueError('Use settle_s >= 0.01, max_active_seconds in 1..300, '
                             'and max_power_ratio >= 1. These are measurement guards, not interlocks.')
        sample_rate = FS_CLK/(1 << decimation_log2)
        if max(abs(low_hz-centre), abs(high_hz-centre)) > .4*sample_rate:
            raise ValueError('Requested %.3f..%.3f MHz does not fit inside the conservative '
                             '%.3f MHz usable span around LO %.3f MHz at decimation_log2=%d. '
                             'Reduce decimation_log2 or narrow/recentre the requested band.' %
                             (low_hz/1e6, high_hz/1e6, .8*sample_rate/1e6, centre/1e6, decimation_log2))
        if averages*(settle_s+n/sample_rate) >= max_active_seconds:
            raise ValueError('The requested averages already exceed max_active_seconds before '
                             'scope/readout overhead. Reduce averages or choose a deliberate longer limit.')
        input_guard = ADC_OPERATING_GUARD_VPK if max_input_vpk is None else float(max_input_vpk)
        output_guard = OUT1_OPERATING_GUARD_VPK if max_output_vpk is None else float(max_output_vpk)
        if not (np.isfinite(input_guard+output_guard) and
                0 < input_guard <= min(ADC_OPERATING_GUARD_VPK, .98*RP_LIMITS['input_lv_full_scale_vpk']) and
                0 < output_guard <= OUT1_OPERATING_GUARD_VPK):
            raise ValueError('Input/output guards must be positive and no higher than the '
                             'notebook operating guards. They can be reduced for a sensitive setup.')
        plan = {'centre_hz': centre, 'decimation_log2': decimation_log2,
                'sample_rate_hz': sample_rate, 'samples_per_record': n,
                'bin_hz': sample_rate/n, 'full_span_hz': sample_rate,
                'fir_mode': fir_mode, 'fir_half_counts': fir_profile['half_counts'],
                'fir_digest': fir_profile['digest']}
        window = np.hanning(n)
        enbw = sample_rate*np.sum(window**2)/np.sum(window)**2
        frequencies = centre+np.fft.fftshift(np.fft.fftfreq(n, 1.0/sample_rate))
        display = (frequencies >= low_hz) & (frequencies <= high_hz)
        lo_word = int(round(centre/FS_CLK*(1 << 32))) & 0xFFFFFFFF
        command = (quantized_feedback_vector(count, applied_phase, reference) if count else
                   {'ci_word': 0, 'cq_word': 0, 'ci_signed': 0, 'cq_signed': 0, 'actual_gain': 0.0})
        result['controls'] = dict(plan, requested_gain=signed_gain, coefficient_counts=count,
                                  phase_deg=float(phase_deg), applied_phase_deg=applied_phase,
                                  phase_reference_hz=reference, averages=averages, repeats=repeats,
                                  fit_range_hz=(fit_low, fit_high), frequency_range_hz=(low_hz, high_hz),
                                  enbw_hz=float(enbw), actual_coefficients=command,
                                  q_guess=q_guess, q_bounds=(q_low, q_high), settle_s=settle_s,
                                  minimum_edge_coverage_linewidths=float(minimum_edge_coverage_linewidths),
                                  maximum_fit_uncertainty_linewidths=float(maximum_fit_uncertainty_linewidths),
                                  max_input_vpk=input_guard, max_output_vpk=output_guard,
                                  max_power_ratio=max_power_ratio, max_active_seconds=max_active_seconds)

        def _manual_input_check(held, proposed=None):
            """Use raw ADC samples including DC; never mistake mean subtraction for headroom."""
            if ('0x%08X' % acq.build_id()).lower() != str(BUILD_ID_EXPECTED).lower():
                raise RuntimeError('FPGA identity changed. Close other board apps and reload the qualified image.')
            ps.assert_held(held)
            gen.assert_b_zero()
            if gen.r(0x04) != 0 or gen.r(0x00) & 0xFF != 0xC0 or held['monitor']:
                raise RuntimeError('A generator or OUT2 is active; this passive test requires them off.')
            codes, rate = sc.acquire(dec=1, n=4096, chan='A')
            codes = np.asarray(codes, dtype=float)
            if sc.r(0x04) != 0 or codes.shape != (4096,) or not np.all(np.isfinite(codes)):
                raise RuntimeError('Raw ADC safety capture timed out or returned invalid data. Check scope/FPGA state.')
            peak = float(np.max(np.abs(codes)))*ADC_RAW_VOLTS_PER_COUNT
            dc = float(np.mean(codes))*ADC_RAW_VOLTS_PER_COUNT
            rms = float(np.std(codes))*ADC_RAW_VOLTS_PER_COUNT
            state = held if proposed is None else proposed
            words = [int(state[key]) & 0xFFFF for key in ('ci', 'cq')]
            signed = [word-65536 if word & 0x8000 else word for word in words]
            # L1 sum bounds I/Q peaks; factor two allows an unloaded 50-ohm-source
            # output. This bounds the DAC signal, NOT voltage at an unknown electrode.
            bound = (2*peak/RP_LIMITS['input_lv_full_scale_vpk']*sum(abs(v) for v in signed)/16384.0 *
                     RP_LIMITS['output_full_scale_vpk_into_50ohm'])
            if any(signed):
                bound += 4*RP_LIMITS['output_full_scale_vpk_into_50ohm']/8192.0
            if peak >= input_guard or abs(dc) > IN1_DC_OFFSET_MAX_V or bound >= output_guard:
                raise RuntimeError('HEADROOM/DC GUARD: IN1 peak %.6g V (limit %.6g), mean %+.6g V '
                                   '(absolute limit %.6g), unloaded OUT1 bound %.6g Vpk (limit %.6g). '
                                   'Reduce gain/input level or investigate offset; do not subtract it to hide overload.' %
                                   (peak, input_guard, dc, IN1_DC_OFFSET_MAX_V, bound, output_guard))
            return {'adc_peak_v': peak, 'adc_dc_v': dc, 'adc_ac_rms_v': rms, 'out1_bound_vpk': bound}

        def _manual_fit(frequency, psd, expected_q):
            """Lorentzian power peak + smooth positive background, in scaled coordinates."""
            mask = ((frequency >= fit_low) & (frequency <= fit_high) &
                    np.isfinite(psd) & (psd > 0) &
                    (np.abs(frequency-centre) > 2*plan['bin_hz']))
            # Mean removal makes a small artificial notch at the acquisition LO.
            # Exclude it and the adjacent Hann bins; it is not an electron dip.
            f, y_all = frequency[mask], psd[mask]
            if len(f) < 128:
                return {'accepted': False, 'reasons': ['Fewer than 128 usable fit bins; increase samples or widen the fit range.']}
            span, midpoint = float(f[-1]-f[0]), float((f[-1]+f[0])/2)
            x_all = (f-midpoint)/span
            median = median_filter(y_all, size=5, mode='nearest')
            keep = (y_all/median < 5) & (median/y_all < 5)
            x, y = x_all[keep], y_all[keep]
            if len(y) < 128:
                return {'accepted': False, 'reasons': ['Too many narrow spurs/dips; use a clean fit window.']}
            log_y = np.log(y)
            design = np.column_stack((np.ones(len(x)), x))
            bg = np.linalg.lstsq(design, log_y, rcond=-1)[0]  # legacy board NumPy
            minimum_width = max(midpoint/q_high, 4*plan['bin_hz'])/span
            maximum_width = min(midpoint/q_low/span, .95)
            if minimum_width >= maximum_width:
                return {'accepted': False, 'reasons': ['Resolution/window cannot cover the requested Q bounds.']}
            seed_width = np.clip(midpoint/expected_q/span, minimum_width*1.01, maximum_width*.99)
            lower = [bg[0]-8, -20, np.log(np.finfo(float).tiny), -.49, np.log(minimum_width)]
            upper = [bg[0]+5, 20, np.log(max(y)*100), .49, np.log(maximum_width)]
            smooth = median_filter(y, size=max(5, int(seed_width*len(y)/8)) | 1)
            peak_x = float(x[int(np.argmax(smooth))])
            starts = ([bg[0], bg[1], np.log(max(y)), 0.0, np.log(seed_width)],
                      [np.log(np.percentile(y, 10)*.25), 0.0, np.log(max(y)), peak_x, np.log(seed_width)])
            def _manual_model(p, xx):
                return np.exp(p[0]+p[1]*xx)+np.exp(p[2])/(1+4*((xx-p[3])/np.exp(p[4]))**2)
            def _manual_residual(p):
                return np.log(_manual_model(p, x))-log_y
            trials = [least_squares(_manual_residual, np.clip(start, np.asarray(lower)+1e-9,
                       np.asarray(upper)-1e-9), bounds=(lower, upper), loss='soft_l1',
                       f_scale=.15, max_nfev=3000) for start in starts]
            solution = min(trials, key=lambda trial: trial.cost)
            width = float(np.exp(solution.x[4])*span)
            f0 = float(midpoint+solution.x[3]*span)
            rss = max(float(np.sum(_manual_residual(solution.x)**2)), np.finfo(float).tiny)
            rss0 = max(float(np.sum((design.dot(bg)-log_y)**2)), np.finfo(float).tiny)
            delta_bic = len(y)*np.log(rss0/rss)-3*np.log(len(y))
            covariance = np.linalg.pinv(solution.jac.T.dot(solution.jac))*2*rss/max(1, len(y)-5)
            sf = float(span*np.sqrt(max(0, covariance[3, 3])))
            sw = float(width*np.sqrt(max(0, covariance[4, 4])))
            q = f0/width
            # Include centre/width covariance when propagating Q = f0/width.
            gradient = np.array([span/width, -q])
            cov_fw = covariance[np.ix_([3, 4], [3, 4])]
            sq = float(np.sqrt(max(0, gradient.dot(cov_fw).dot(gradient))))
            model = _manual_model(solution.x, x_all)
            reasons = []
            if not solution.success or delta_bic < 10:
                reasons.append('Peak is not convincingly distinguished from background (delta BIC %.2f).' % delta_bic)
            if width <= minimum_width*span*1.02 or width >= maximum_width*span*.98:
                reasons.append('Linewidth reached a fit bound; revise Q bounds/window/resolution.')
            if width/plan['bin_hz'] < 20:
                reasons.append('Only %.1f bins per linewidth; increase samples or decimation.' % (width/plan['bin_hz']))
            edge_coverage=min(f0-f[0],f[-1]-f0)/width
            if edge_coverage < float(minimum_edge_coverage_linewidths):
                reasons.append('Fit window reaches only %.2f linewidths from the centre to its nearer edge; this measurement requires %.2f. Widen/recentre the configured range, or deliberately lower minimum_edge_coverage_linewidths for a coarse Q-reducing diagnostic.' %
                               (edge_coverage,float(minimum_edge_coverage_linewidths)))
            uncertainty_limit=float(maximum_fit_uncertainty_linewidths)*width
            if sf > uncertainty_limit or sw > uncertainty_limit or not np.isfinite(sf+sw+sq):
                reasons.append('Fit uncertainty is too large: centre uncertainty is %.3f and linewidth uncertainty %.3f linewidths; the configured limit is %.3f. Increase averaging or widen/isolate the correct peak.' %
                               (sf/width,sw/width,float(maximum_fit_uncertainty_linewidths)))
            if np.max(y_all/model) > 8:
                reasons.append('Strong narrow residual/spur; inspect for oscillation or another mode.')
            return {'accepted': not reasons, 'reasons': reasons, 'f0_hz': f0, 'q': q,
                    'linewidth_hz': width, 'f0_uncertainty_hz': sf, 'q_uncertainty': sq,
                    'linewidth_uncertainty_hz': sw, 'frequency_hz': f, 'model': model,
                    'delta_bic': float(delta_bic), 'uncertainty_kind': 'approximate correlated-bin fit covariance'}

        # Check the requested frequency window against the actual response mask
        # BEFORE energising anything. Measured correction is optional, never loaded.
        trial = correct_acquisition_response({'frequency_hz': frequencies,
                  'psd_v2_per_hz': np.ones(n)}, plan, calibration=response_calibration)
        if not np.all(np.isfinite(trial['psd_v2_per_hz'][display])):
            raise ValueError('Part of the requested band needs excessive/unknown filter correction. '
                             'The installed FIR is flat only in its central passband (about +/-0.20 of output rate), '
                             'not throughout Nyquist. Narrow/recentre the band, reduce decimation, or deliberately '
                             "select fir_mode='bypass' and assess CIC alias rejection. No feedback has been applied.")
        print('%s: gain %+.7g -> count %d; phase %.2f deg; LO %.6f MHz; '
              'span %.1f kHz; bins %.2f Hz; ENBW %.2f Hz; %d averages x %d repeats.' %
              (label, signed_gain, count, applied_phase, centre/1e6, (high_hz-low_hz)/1e3,
               plan['bin_hz'], enbw, averages, repeats))
        states = ('before',) if mode == 'baseline' else (('on',) if mode == 'feedback' else ('before', 'on', 'after'))
        print('Acquiring %s only. Both generators and OUT2 stay off.' % ' -> '.join(states))
        if mode == 'feedback':
            print('Reusing baseline "%s" (age %.1f minutes), unchanged and without recapture/refit. '
                  'Phase reference stays at %.6f MHz.' %
                  (result['baseline_label'], result['baseline_age_s']/60, reference/1e6))
            print(result['comparison_note'])
        print('The fit excludes +/- %.2f Hz around the LO, where record-mean removal '
              'creates an artificial notch; no DC is subtracted from the FPGA feedback path.' % (2*plan['bin_hz']))
        result['status'] = 'measuring'
        for repetition in range(repeats):
            run = {'repeat': repetition+1, 'fits': {}, 'health': {}}
            result['runs'].append(run)
            for state_name in states:
                result['active_stage'] = (repetition+1, state_name)
                full_shutdown()
                held = ps.readback()
                if mode == 'feedback':
                    # Fresh, short full-band safety sample, NOT a resonance/baseline spectrum.
                    run['fresh_off_health'] = _manual_input_check(held)
                if state_name == 'on' and count:
                    ps.config_delay(reference)
                    held = ps.readback()
                    proposed = dict(held, ci=command['ci_word'], cq=command['cq_word'])
                    _manual_input_check(held, proposed)
                    ps.set(count/16384.0, applied_phase)
                    ps.assert_held(proposed)
                    held = proposed
                total = np.zeros(n)
                rms_values, raw_rms = [], []
                deadline = time.monotonic()+max_active_seconds
                try:
                    for record in range(averages):
                        if time.monotonic() > deadline:
                            raise RuntimeError('Measurement time limit reached during %s. Reduce averages '
                                               'or inspect slow capture; this software limit is not a watchdog.' % state_name)
                        health = _manual_input_check(held)
                        raw_rms.append(health['adc_ac_rms_v'])
                        if state_name == 'on':
                            off_rms = (run['fresh_off_health']['adc_ac_rms_v'] if mode == 'feedback'
                                       else run['health']['before']['mean_adc_ac_rms_v'])
                            reference_power = max(off_rms**2,
                                                  ADC_RAW_VOLTS_PER_COUNT**2)
                            if not map_safety_mode and raw_rms[-1]**2/reference_power > max_power_ratio:
                                raise RuntimeError('Full-band ADC power exceeded %.2fx the feedback-off '
                                                   'reference. Reduce gain; inspect amplifier/pickup/oscillation.' % max_power_ratio)
                        raw = capture(lo_word, decimation_log2, n, settle=settle_s, fir_mode=fir_mode)
                        values = np.asarray(raw)*CIC_VOLTS_PER_COUNT
                        if values.shape != (n,) or not np.all(np.isfinite(values)):
                            raise RuntimeError('DMA sample count/non-finite data failure. Check capture bounds and FPGA identity.')
                        values = values-np.mean(values)  # FFT only; raw DC still counts for headroom above.
                        power = np.abs(np.fft.fftshift(np.fft.fft(values*window)))**2/(sample_rate*np.sum(window**2))
                        if not np.all(np.isfinite(power)) or np.sum(power) <= 0:
                            raise RuntimeError('FFT power is zero/non-finite. Check acquisition and input scaling.')
                        total += power
                        rms_values.append(float(np.sqrt(np.mean(np.abs(values)**2))))
                        ps.assert_held(held)
                        if state_name == 'on' and not map_safety_mode and (record+1) % 8 == 0:
                            running_psd = total/(record+1)
                            running_floor = median_filter(running_psd, size=7, mode='nearest')
                            if np.max(running_psd[display]/np.maximum(running_floor[display], np.finfo(float).tiny)) > 20:
                                raise RuntimeError('A narrow carrier appeared during feedback. Stop and '
                                                   'inspect it before calling it a high-Q resonance.')
                finally:
                    full_shutdown()  # Fit/plot only after feedback has been removed.
                if read_acquisition_fir()['digest'] != fir_profile['digest']:
                    raise RuntimeError('FIR coefficients changed during measurement. Feedback is off; discard this result.')
                spectrum = correct_acquisition_response({'frequency_hz': frequencies,
                               'psd_v2_per_hz': total/averages}, plan, calibration=response_calibration)
                observed = spectrum['psd_v2_per_hz'][display]
                fit = _manual_fit(frequencies[display], observed, q_guess)
                run['fits'][state_name] = {key: value for key, value in fit.items()
                                           if key not in ('model', 'frequency_hz')}
                cv = float(np.std(rms_values, ddof=1)/np.mean(rms_values))
                run['health'][state_name] = dict(health, rms_cv=cv,
                                               mean_adc_ac_rms_v=float(np.mean(raw_rms)))
                if cv > .30:
                    fit['accepted'] = False
                    fit['reasons'].append('Nonstationary record RMS (CV %.3f > 0.30).' % cv)
                    run['fits'][state_name]['accepted'] = False
                result['fits'][state_name] = fit
                if state_name not in result['spectra']:
                    result['spectra'][state_name] = {'frequency_hz': frequencies[display].copy(),
                        'psd_v2_per_hz': observed.copy(), 'completed_repeats': 1,
                        'response_source': spectrum.get('response_source', 'unspecified')}
                else:
                    accumulated = result['spectra'][state_name]
                    completed = accumulated['completed_repeats']
                    accumulated['psd_v2_per_hz'] += (observed-accumulated['psd_v2_per_hz'])/(completed+1)
                    accumulated['completed_repeats'] += 1
                if state_name == 'before' and not fit['accepted']:
                    result['warnings'].append('Feedback was not enabled: the fresh off baseline is unreliable. '
                                               + ' '.join(fit['reasons']))
                    break
            if mode != 'bracketed':
                if not all(row['accepted'] for row in run['fits'].values()):
                    result['warnings'].append('Stopped further repeats because the measured fit is unreliable.')
                    break
                continue
            if len(run['fits']) < 3:
                break
            before, on, after = [run['fits'][key] for key in ('before', 'on', 'after')]
            result['recovery_measured'] = True
            if not all(row['accepted'] for row in (before, on, after)):
                result['warnings'].append('Stopped further repeats because at least one fit is unreliable.')
                break
            off_width = (before['linewidth_hz']+after['linewidth_hz'])/2
            run['k_damping'] = 1-on['linewidth_hz']/off_width
            run['shift_hz'] = on['f0_hz']-(before['f0_hz']+after['f0_hz'])/2
            print('Repeat %d: effective damping K %.4f; centre shift %+.2f Hz.' %
                  (repetition+1, run['k_damping'], run['shift_hz']))
            if (abs(after['f0_hz']-before['f0_hz']) > .25*off_width or
                    abs(after['linewidth_hz']-before['linewidth_hz']) > .25*off_width):
                result['warnings'].append('Off baseline did not recover within 0.25 linewidth '
                                           'in centre/width. Inspect drift/heating before another call.')
                break
        # Overlay the final, averaged spectra. All fitted/plot arrays share the
        # identical frequency mask, avoiding the earlier x/y-length mismatch.
        fig, axes = plt.subplots(3 if mode == 'feedback' else 2, 1,
                                 figsize=(11, 10 if mode == 'feedback' else 7))
        residual_axis = axes[-1]
        for state_name, color in (('before', '#1f77b4'), ('on', '#ff7f0e'), ('after', '#2ca02c')):
            if state_name not in result['spectra']:
                continue
            spectrum = result['spectra'][state_name]
            f, p = spectrum['frequency_hz'], spectrum['psd_v2_per_hz']
            # A single repeat was already fitted after shutdown; reuse that fit.
            # Multiple repeats need a fresh fit to their averaged spectrum.
            cached = mode == 'feedback' and state_name == 'before'
            fit = (result['fits'][state_name] if cached or spectrum['completed_repeats'] == 1
                   else _manual_fit(f, p, q_guess))
            prior = [run['fits'][state_name] for run in result['runs'] if state_name in run['fits']]
            if any(not row['accepted'] for row in prior):
                fit['accepted'] = False
                fit['reasons'].append('At least one individual repeat failed; averaging does not remove that failure.')
            if len(prior) > 1 and all('f0_hz' in row for row in prior):
                spread = float(np.std([row['f0_hz'] for row in prior], ddof=1))
                width_spread = float(np.std([row['linewidth_hz'] for row in prior], ddof=1))
                if max(spread, width_spread) > .1*fit.get('linewidth_hz', 0):
                    fit['accepted'] = False
                    fit['reasons'].append('Centre/linewidth drift distorts the average; inspect per-repeat fits.')
            result['fits'][state_name] = fit
            state_averages = result['baseline_controls']['averages'] if cached else averages
            axes[0].semilogy(f/1e6, p, color=color, alpha=.5, linewidth=.8,
                             label='%s PSD (%d x %d spectra)' %
                             (state_name, spectrum['completed_repeats'], state_averages))
            if mode == 'feedback':
                axes[1].semilogy(f/1e6, p, color=color, alpha=.5, linewidth=.8)
            if 'model' in fit:
                caption = '%s: f0 %.6f MHz, Q %.1f%s' % (state_name, fit['f0_hz']/1e6,
                          fit['q'], '' if fit['accepted'] else ' [UNRELIABLE]')
                axes[0].semilogy(fit['frequency_hz']/1e6, fit['model'], color=color,
                                 linewidth=2, linestyle='-' if fit['accepted'] else '--', label=caption)
                if mode == 'feedback':
                    axes[1].semilogy(fit['frequency_hz']/1e6, fit['model'], color=color,
                                     linewidth=2, linestyle='-' if fit['accepted'] else '--')
                residual_axis.plot(fit['frequency_hz']/1e6,
                             np.interp(fit['frequency_hz'], f, p)/fit['model']-1, color=color, alpha=.7)
                print('%s: f0 %.6f +/- %.6f MHz; Q %.2f +/- %.2f; linewidth %.2f Hz; accepted=%s' %
                      (state_name, fit['f0_hz']/1e6, fit['f0_uncertainty_hz']/1e6,
                       fit['q'], fit['q_uncertainty'], fit['linewidth_hz'], fit['accepted']))
            for reason in fit['reasons']:
                print('  %s: %s' % (state_name, reason))
        axes[0].set_ylabel('Corrected PSD (V²/Hz)')
        axes[0].set_title(str(label)+' — one manually selected feedback setting')
        axes[0].legend(fontsize=8)
        residual_axis.axhline(0, color='black', linewidth=.8)
        residual_axis.set_ylabel('PSD / fitted model − 1')
        residual_axis.set_xlabel('Frequency (MHz)')
        residual_axis.set_xlim(low_hz/1e6, high_hz/1e6)
        if mode == 'feedback':
            axes[0].set_title(str(label)+' — full baseline and feedback windows (native grids)')
            axes[1].set_title('Feedback-window zoom; baseline fit is unchanged')
            axes[1].set_ylabel('Corrected PSD (V²/Hz)')
            axes[1].set_xlim(low_hz/1e6, high_hz/1e6)
            before, on = result['fits']['before'], result['fits'].get('on', {})
            if on.get('accepted'):
                ratio = on['linewidth_hz']/before['linewidth_hz']
                result['comparison'] = {
                    'q_ratio': on['q']/before['q'], 'k_damping': 1-ratio,
                    'shift_hz': on['f0_hz']-before['f0_hz'],
                    'shift_fit_uncertainty_hz': float(np.hypot(on['f0_uncertainty_hz'], before['f0_uncertainty_hz'])),
                    'k_fit_uncertainty': float(ratio*np.hypot(on['linewidth_uncertainty_hz']/on['linewidth_hz'],
                                                            before['linewidth_uncertainty_hz']/before['linewidth_hz'])),
                    'unmeasured_drift_included': False}
                print('Relative to saved baseline: Q/Q0 %.4f, effective damping K %.4f, shift %+.2f Hz. '
                      'These are comparisons, not independently calibrated loop gain; unmeasured drift is excluded.' %
                      (result['comparison']['q_ratio'], result['comparison']['k_damping'], result['comparison']['shift_hz']))
        else:
            axes[0].set_xlim(low_hz/1e6, high_hz/1e6)
        fig.tight_layout()
        if show_plots:
            plt.show()
        else:
            plt.close(fig)
        # Additional dB view: logarithm of the averaged LINEAR PSD, not an
        # average of logarithms. Native high-impedance IN1 has no defined 50-ohm
        # delivered power, so do not label this as dBm or dBm/Hz.
        # BEGIN COPYABLE DB PLOT
        plot_result = result
        db_zoom = plot_result.get('mode') == 'feedback'
        db_fig, db_axes = plt.subplots(2 if db_zoom else 1, 1,
                                      figsize=(11, 8 if db_zoom else 4.5), squeeze=False)
        for state_name, color in (('before', '#1f77b4'), ('on', '#ff7f0e'), ('after', '#2ca02c')):
            spectrum = plot_result.get('spectra', {}).get(state_name)
            if spectrum is None:
                continue
            fit = plot_result.get('fits', {}).get(state_name, {})
            state_label = {'before': 'Feedback off (baseline)', 'on': 'Feedback on',
                           'after': 'Feedback off (after)'}[state_name]
            traces = [(spectrum['frequency_hz'], spectrum['psd_v2_per_hz'],
                       state_label + ' PSD', False)]
            if 'model' in fit:
                caption = '%s fit: Q %.1f, f0 %.6f MHz%s' % (
                    state_label, fit['q'], fit['f0_hz']/1e6,
                    '' if fit.get('accepted') else ' [UNRELIABLE]')
                traces.append((fit['frequency_hz'], fit['model'], caption, True))
            for frequency, power_density, caption, is_fit in traces:
                frequency = np.asarray(frequency, dtype=float)
                power_density = np.asarray(power_density, dtype=float)
                if frequency.ndim != 1 or frequency.shape != power_density.shape:
                    raise ValueError('dB plot: %s frequency/PSD arrays must have matching 1-D shapes.' % caption)
                # Leave invalid/zero bins as gaps; never manufacture a noise floor.
                valid = np.isfinite(frequency) & np.isfinite(power_density) & (power_density > 0)
                density_db = np.full(power_density.shape, np.nan)
                density_db[valid] = 10.0*np.log10(power_density[valid] / 1.0)
                for db_axis in db_axes[:, 0]:
                    db_axis.plot(frequency/1e6, density_db, color=color,
                                 alpha=1.0 if is_fit else .5,
                                 linewidth=2 if is_fit else .8,
                                 linestyle='--' if is_fit and not fit.get('accepted') else '-',
                                 label=caption)
        for db_axis in db_axes[:, 0]:
            db_axis.set_xlabel('Frequency (MHz)')
            db_axis.set_ylabel('PSD (dB re 1 V²/Hz)')
            db_axis.grid(True, alpha=.25)
        db_axes[0, 0].set_title(str(plot_result.get('label', 'Measurement')) + ' — dB spectrum')
        db_axes[0, 0].legend(fontsize=8)
        if db_zoom:
            limits = plot_result['controls']['frequency_range_hz']
            db_axes[1, 0].set_xlim(limits[0]/1e6, limits[1]/1e6)
            db_axes[1, 0].set_title('Feedback-window zoom; original baseline fit retained')
        db_fig.tight_layout()
        if locals().get('show_plots', True):
            plt.show()
        else:
            plt.close(db_fig)
        # END COPYABLE DB PLOT
        for warning in result['warnings']:
            print('WARNING: '+warning)
        expected_fits = 1 if mode == 'baseline' else (2 if mode == 'feedback' else 3)
        result['status'] = ('complete' if len(result['fits']) == expected_fits and not result['warnings'] and
                            all(row['accepted'] for row in result['fits'].values()) else 'review_required')
        return result
    except BaseException as exc:
        result['status'] = 'aborted'
        result['error'] = '%s: %s' % (type(exc).__name__, exc)
        raise
    finally:
        try:
            full_shutdown()
            result['shutdown_verified'] = True
        except BaseException:
            result['status'] = 'shutdown_failed'
            raise RuntimeError('Shutdown could not be verified. Physically disconnect OUT1 '
                               'before troubleshooting; do not start another measurement.')


# Define the function above first; then explicitly run a call in a separate cell.
# First acquire the broad OFF baseline once (retain this variable in memory):
# manual_baseline = measure_manual_feedback(mode='baseline', averages=32,
#     frequency_range_hz=(40.4e6, 41.4e6), q_guess=150, label='current setup baseline')
# Then rerun ONLY this call, choosing its own window/decimation/Q estimate:
# measurement = measure_manual_feedback(mode='feedback', baseline_measurement=manual_baseline,
#     coefficient_counts=32, phase_deg=0,
#     frequency_range_hz=(40.4e6, 41.4e6),
#     fit_range_hz=(40.5e6, 41.3e6),
#     decimation_log2=6, samples_per_record=8192, averages=32, repeats=1,
#     label='current amplifier / attenuator arrangement')
# Emergency software stop: full_shutdown()
