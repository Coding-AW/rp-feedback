# Filter-test definitions: no hardware runs until a measurement call is made.
def inspect_acquisition_filters(decimation_log2=8, samples_per_record=8192,
                                centre_hz=40.9e6, half_counts=None, passband_fraction=.20):
    """Plot predicted CIC/FIR/product and alias folding; no hardware access."""
    dec = int(decimation_log2)
    if dec != decimation_log2 or not 6 <= dec <= 12 or not 0 < passband_fraction < .5:
        raise ValueError('Choose integer decimation_log2 6..12 and a passband half-width between 0 and 0.5 of output rate.')
    if int(samples_per_record) != samples_per_record or samples_per_record < 256:
        raise ValueError('FFT comparison requires an integer sample count of at least 256.')
    profile = acquisition_fir_profile(half_counts)
    rate = FS_CLK/(1 << dec)
    plan = dict(centre_hz=centre_hz, sample_rate_hz=rate, decimation_log2=dec,
                fir_half_counts=profile['half_counts'])
    # Include the requested edges exactly: sparse plotting grids must not hide
    # ripple at the steep start of the transition band.
    x = np.unique(np.r_[np.linspace(-.499, .499, 2001), -passband_fraction, passband_fraction])
    response = filter_response_components(centre_hz+x*rate, plan)
    fig, axes = plt.subplots(3, 1, figsize=(11, 10))
    for name in ('cic', 'fir', 'combined'):
        axes[0].plot(x*rate/1e3, 10*np.log10(np.maximum(response[name], 1e-20)), label=name)
    axes[0].set_ylim(-110, 8)
    axes[0].set_title('CIC loss, FIR boost/roll-off, and hardware product (no software correction)')
    axes[0].set_ylabel('Power gain (dB)'); axes[0].legend()
    good = abs(x) <= passband_fraction
    axes[1].plot(x[good]*rate/1e3, 10*np.log10(response['combined'][good]))
    axes[1].set_title('Requested passband detail: not the whole Nyquist band')
    axes[1].set_ylabel('Combined gain (dB)')
    # First adjacent decimation images fold onto the same final frequencies.
    # The post-decimation FIR treats wanted and aliased tones identically.
    alias_plus = cic_power_response(centre_hz+(x+1)*rate, plan)/response['cic']
    alias_minus = cic_power_response(centre_hz+(x-1)*rate, plan)/response['cic']
    axes[2].plot(x*rate/1e3, 10*np.log10(np.maximum(np.maximum(alias_plus, alias_minus), 1e-20)))
    axes[2].set_title('Worst first-image leakage relative to wanted tone: FIR cannot undo folded aliases')
    axes[2].set_ylabel('Relative alias gain (dB)')
    for ax in axes:
        ax.set_xlabel('Offset from LO (kHz)'); ax.grid(True, alpha=.25)
    fig.tight_layout(); plt.show()
    window = np.hanning(int(samples_per_record))
    report = dict(plan, fir_digest=profile['digest'], fir_bypassed=response['fir_bypassed'],
                  bin_hz=rate/samples_per_record,
                  enbw_hz=float(rate*np.sum(window**2)/np.sum(window)**2),
                  record_seconds=samples_per_record/rate,
                  passband_full_span_hz=2*passband_fraction*rate,
                  passband_ripple_db=float(np.ptp(10*np.log10(response['combined'][good]))),
                  group_delay_seconds=4*((1 << dec)-1)/(2*FS_CLK) +
                  (0 if response['fir_bypassed'] else 154/rate),
                  fir_l1_gain_bound=profile['l1_gain_bound'])
    print('R=%d; output %.3f ksample/s; FIR %s; bins %.3f Hz; ENBW %.3f Hz.' %
          (1 << dec, rate/1e3, 'BYPASSED' if response['fir_bypassed'] else 'enabled', report['bin_hz'], report['enbw_hz']))
    print('Requested flat span %.3f kHz; model ripple %.4f dB; nominal filter group delay %.3f ms.' %
          (report['passband_full_span_hz']/1e3, report['passband_ripple_db'], report['group_delay_seconds']*1e3))
    print('This is a model, not evidence that the board/filter or analogue chain has passed calibration.')
    return report


def validate_fft_parseval(records, spectrum=None, maximum_fractional_error=1e-10):
    """Exact Hann-weighted Parseval check; unweighted noise power is NOT identical."""
    data = np.asarray(records, dtype=complex)
    if data.ndim != 2 or min(data.shape) < 2 or not np.all(np.isfinite(data)):
        raise ValueError('FFT check requires finite records shaped [repeat, samples].')
    centred = data-np.mean(data, axis=1, keepdims=True)
    window = np.hanning(data.shape[1]); sumw2 = np.sum(window**2)
    time_power = float(np.mean(np.sum(abs(centred*window)**2, axis=1)/sumw2))
    if spectrum is None:
        # Fout cancels after multiplication by delta_f = Fout/N.
        frequency_power = float(np.mean(np.sum(abs(np.fft.fft(centred*window, axis=1))**2,
                                              axis=1)/(data.shape[1]*sumw2)))
    else:
        # Supply the RAW uncorrected complex-envelope PSD, never an inversely
        # equalized/truncated spectrum; otherwise Parseval compares different signals.
        frequency_power = float(np.sum(spectrum['psd_v2_per_hz'])*spectrum['bin_hz'])
    error = abs(frequency_power/max(time_power, np.finfo(float).tiny)-1)
    return {'accepted': bool(time_power > 0 and error <= maximum_fractional_error),
            'hann_weighted_time_power_v2': time_power, 'integrated_psd_power_v2': frequency_power,
            'fractional_error': error, 'convention': 'complex-envelope mean square, not watts into a load'}


def calibrate_adc_scale(reference_vrms, measured_count_rms):
    """Evaluate an independent raw-ADC volts/count check; never update scaling silently."""
    reference = np.asarray(reference_vrms, dtype=float)
    counts = np.asarray(measured_count_rms, dtype=float)
    if (reference.ndim != 1 or reference.shape != counts.shape or reference.size < 3 or
            not np.all(np.isfinite(reference+counts)) or np.any(reference <= 0) or np.any(counts <= 0)):
        raise ValueError('Supply at least three positive finite pairs: independently measured IN1 RMS volts and raw ADC RMS counts.')
    scale = reference/counts
    scatter = float(np.std(scale, ddof=1)/np.mean(scale))
    return {'accepted': scatter <= .02, 'volts_per_count': float(np.mean(scale)),
            'uncertainty_volts_per_count': float(np.std(scale, ddof=1)), 'relative_scatter': scatter,
            'applied_to_notebook': False}


def analyse_filter_tone_records(records, sample_rate_hz, expected_offset_hz):
    """Measure a known complex tone without confusing FFT bin width with amplitude."""
    from scipy.optimize import minimize_scalar
    data = np.asarray(records, dtype=complex)
    if data.ndim != 2 or data.shape[0] < 2 or data.shape[1] < 256 or not np.all(np.isfinite(data)):
        raise ValueError('Tone analysis needs at least two finite records of at least 256 complex samples.')
    rate = float(sample_rate_hz); n = data.shape[1]
    if not np.isfinite(rate) or rate <= 0 or not np.isfinite(expected_offset_hz):
        raise ValueError('Tone fitting needs a positive finite sample rate and a finite expected frequency offset.')
    if np.mean(abs(data)**2) <= np.finfo(float).tiny:
        raise ValueError('Tone records are all zero. Check the selected source, loopback cable and acquisition; no response can be calibrated.')
    t = np.arange(n)/rate; window = np.hanning(n)
    folded = (expected_offset_hz+rate/2) % rate-rate/2
    amplitudes, offsets, residuals = [], [], []
    for row in data:
        # Search a narrow frequency interval to allow source/ADC clock error.
        # This avoids assuming the generator lands exactly on an FFT bin.
        def objective(offset):
            return -abs(np.sum(row*window*np.exp(-2j*np.pi*(folded+offset)*t))/np.sum(window))**2
        fitted = minimize_scalar(objective, bounds=(-rate/n, rate/n), method='bounded',
                                 options={'xatol': rate/n*1e-6})
        f = folded+fitted.x
        a = np.sum(row*window*np.exp(-2j*np.pi*f*t))/np.sum(window)
        residual = row-a*np.exp(2j*np.pi*f*t)
        amplitudes.append(abs(a)); offsets.append(f)
        residuals.append(float(np.mean(abs(residual)**2)))
    power = np.asarray(amplitudes)**2
    snr = float(10*np.log10(np.mean(power)/max(np.mean(residuals), np.finfo(float).tiny)))
    return {'amplitude_v': float(np.sqrt(np.mean(power))),
            'power_v2': float(np.mean(power)), 'power_relative_scatter': float(np.std(power, ddof=1)/np.mean(power)),
            'observed_offset_hz': float(np.mean(offsets)), 'snr_db': snr,
            'parseval': validate_fft_parseval(data)}


def measure_acquisition_filters(tone_hz=40.9e6, decimation_log2=8,
                                fractions=None, repeats=3, samples_per_record=4096,
                                settle_s=.03, maximum_ripple_db=.15,
                                maximum_model_error_db=.30, seed=7,
                                source='out1', drive_fraction=.02):
    """Fixed RF tone, swept LO, FIR bypass/on pairs; feedback always off.

    DISCONNECT THE TRAP from IN1 and OUT1 first. For source='out1', connect only
    OUT1 -> short coax (optional pad) -> IN1, preferably locally terminated 50 ohm.
    The generator is distinct from feedback, whose coefficients remain zero.
    source='external' retains the independently supplied fixed-tone option.
    Returns compact measurements and optional accepted response dictionaries.
    OUT1 generator A is enabled only for loopback and shut down on every exit.
    No FIR coefficients, feedback coefficients or OUT2 are enabled/rewritten.
    """
    global LAST_FILTER_CALIBRATION
    result = {'accepted': False, 'rows': [], 'responses': {}, 'rejection_reasons': [],
              'timestamp_epoch_s': time.time(), 'shutdown_verified': False,
              'source': source, 'absolute_voltage_calibrated': False,
              'independent_clock_test': False}
    LAST_FILTER_CALIBRATION = result
    try:
        full_shutdown()
        if source not in ('out1', 'external'):
            raise ValueError("source must be 'out1' for the isolated loopback or 'external' for a separate fixed RF source.")
        if source == 'out1' and (not np.isfinite(drive_fraction) or
                not 0 < drive_fraction <= min(.05, DRIVE_MAX) or
                int(round(drive_fraction*8192)) < 2):
            raise ValueError('Loopback drive_fraction must produce at least two generator counts and be <= min(0.05, DRIVE_MAX). '
                             'Start at 0.02; this is a digital fraction, not an independently calibrated voltage.')
        if ADC_RANGE != 'LV':
            raise ValueError('This test uses the notebook LV input scaling. Match the physical range before measuring.')
        dec = int(decimation_log2); n = int(samples_per_record)
        fractions = np.linspace(-.20, .20, 17) if fractions is None else np.asarray(fractions, dtype=float)
        if (dec != decimation_log2 or not 6 <= dec <= 12 or n != samples_per_record or
                n < 1024 or n > 32768 or n & (n-1) or repeats < 2 or repeats != int(repeats) or repeats > 10 or
                fractions.ndim != 1 or not 9 <= fractions.size <= 65 or not np.all(np.isfinite(fractions)) or
                np.any(abs(fractions) > .45) or len(np.unique(fractions)) != len(fractions) or
                not np.any(fractions == 0) or min(fractions) >= 0 or max(fractions) <= 0):
            raise ValueError('Use decimation 6..12, power-of-two samples 1024..32768, repeats 2..10, '
                             'and 9..65 unique offset fractions within +/-0.45 including zero and both signs.')
        if not np.isfinite(tone_hz) or not 0 < tone_hz < 50e6 or not np.isfinite(settle_s) or settle_s < .01:
            raise ValueError('Use a finite RF tone within 0..50 MHz and settle_s >= 0.01.')
        if not (0 < maximum_ripple_db <= 1 and 0 < maximum_model_error_db <= 1):
            raise ValueError('Ripple/model tolerances must be positive and <=1 dB; investigate larger errors.')
        profile = read_acquisition_fir()
        held = ps.readback()
        if held['ci'] or held['cq'] or held['monitor']:
            raise RuntimeError('Feedback or OUT2 is not zero after shutdown. Disconnect OUT1 and resolve register readback before any tone test.')
        # These local checks are shared by startup, the scan and shutdown.
        # A changing generator must not be mistaken for a changing filter.
        expected_generator = {0x04: 0}
        expected_control = [0xC0]

        def check_source():
            if ('0x%08X' % acq.build_id()).lower() != str(BUILD_ID_EXPECTED).lower():
                raise RuntimeError('FPGA changed during calibration; close other Red Pitaya applications before retrying.')
            ps.assert_held(held)
            gen.assert_b_zero()
            if gen.r(0x00) & 0x1FF != expected_control[0]:
                raise RuntimeError('Generator A control changed during the filter test. Stop competing apps; no correction is accepted.')
            for address, expected in expected_generator.items():
                actual = gen.r(address)
                if actual != expected:
                    raise RuntimeError('Generator readback mismatch at 0x%02X: expected 0x%08X, got 0x%08X. '
                                       'Amplitude, DC offset or tuning changed; disconnect loopback and investigate.' %
                                       (address, expected, actual))

        def raw_input():
            check_source()
            codes, adc_rate = sc.acquire(dec=1, n=4096, chan='A')
            codes = np.asarray(codes, dtype=float)
            if (codes.shape != (4096,) or sc.r(0x04) or not np.all(np.isfinite(codes)) or
                    not np.isfinite(adc_rate) or abs(adc_rate/FS_CLK-1) > 1e-9):
                raise RuntimeError('Raw ADC capture/clock invalid or timed out; no response calibration accepted.')
            voltage = codes*ADC_RAW_VOLTS_PER_COUNT
            if np.max(abs(voltage)) >= ADC_OPERATING_GUARD_VPK or abs(np.mean(voltage)) > IN1_DC_OFFSET_MAX_V:
                raise RuntimeError('ADC peak/DC operating guard exceeded. Stop the source, check cabling/offsets and reduce level before retrying.')
            check_source()
            return voltage

        if source == 'out1':
            # Bound even an unterminated output conservatively; never rely on a
            # matched-pad loss to make an excessive command safe.
            count = int(round(drive_fraction*8192))
            bound = 2*(count/8192.0)*RP_LIMITS['output_full_scale_vpk_into_50ohm']
            if bound >= min(ADC_OPERATING_GUARD_VPK, OUT1_OPERATING_GUARD_VPK):
                raise ValueError('Loopback nominal high-impedance output bound exceeds an operating guard; reduce drive_fraction.')
            off = raw_input()
            off_power = float(np.var(off))
            gen.load_sine()
            # The existing ASG has asymmetric low-frequency write/read addresses:
            # write fractional step at 0x4C, read it at 0x14. Clear stale burst
            # state as well; generator apps may have left these non-default.
            for address in (0x4C, 0x18, 0x1C, 0x20, 0x44):
                gen.w(address, 0)
            expected_generator.update({0x14: 0, 0x18: 0, 0x1C: 0, 0x20: 0, 0x44: 0})
            # Verify all waveform words while A is held off, not just control.
            for address in range(16384):
                expected = int(round(8191*np.sin(2*np.pi*address/16384.0))) & 0x3FFF
                if gen.r(0x10000+4*address) & 0x3FFF != expected:
                    raise RuntimeError('Generator sine table readback failed at sample %d. No tone was enabled.' % address)
            tone_hz = gen.freq(float(tone_hz))  # use actual quantized DDS frequency
            expected_generator.update({0x08: (16384 << 16)-1, 0x0C: 0,
                                       0x10: gen.freq_word(tone_hz)})
            check_source()
            result['loopback_startup'] = {'off_power_v2': off_power, 'levels': [],
                                          'nominal_high_z_bound_vpk': bound}
            print('LOOPBACK ONLY: ramping generator A at %.6f MHz; feedback and OUT2 remain zero.' % (tone_hz/1e6))
            for rung in (count//2, count):  # count >= 2: distinct, ascending levels
                gen.amp(rung/8192.0)
                expected_generator[0x04] = rung  # upper DC-offset field must stay zero
                check_source()
                gen.run()
                expected_control[0] = 0x11
                time.sleep(settle_s)
                voltage = raw_input()
                power = float(np.var(voltage))
                if power < (4*ADC_RAW_VOLTS_PER_COUNT)**2 or power < 10*max(off_power, 1e-30):
                    raise RuntimeError('Loopback tone is too weak or does not rise at least 10x above generator-off ADC power. '
                                       'Check OUT1-to-IN1 cabling, termination and excessive pads. No automatic amplitude increase is made.')
                # A fixed frequency permits an independent raw-ADC sine/DC fit.
                # Reject strong other tones or generator distortion before using RMS.
                t = np.arange(voltage.size)/FS_CLK
                design = np.column_stack((np.cos(2*np.pi*tone_hz*t),
                                          np.sin(2*np.pi*tone_hz*t), np.ones(t.size)))
                coefficients = np.linalg.lstsq(design, voltage, rcond=-1)[0]
                residual_power = float(np.mean((voltage-design.dot(coefficients))**2))
                if residual_power/power > .03:
                    raise RuntimeError('Loopback raw input is not a clean sine: >3% residual power. '
                                       'Check distortion, noise, competing signals and range; do not calibrate from this trace.')
                result['loopback_startup']['levels'].append(dict(
                    generator_counts=rung, rms_v=float(np.sqrt(power)), peak_v=float(np.max(abs(voltage))),
                    dc_v=float(np.mean(voltage)), excess_power_v2=power-off_power,
                    residual_fraction=residual_power/power))
                print('  generator count %d: input RMS %.3f mV, peak %.3f mV, DC %.3f mV' %
                      (rung, 1e3*np.sqrt(power), 1e3*np.max(abs(voltage)), 1e3*np.mean(voltage)))
            levels = result['loopback_startup']['levels']
            linearity = ((levels[1]['excess_power_v2']/levels[0]['excess_power_v2']) /
                         (float(levels[1]['generator_counts'])/levels[0]['generator_counts'])**2)
            result['loopback_startup']['power_linearity_ratio'] = linearity
            if not .90 <= linearity <= 1.10:
                raise RuntimeError('Loopback two-level power linearity ratio %.3f is outside 0.90..1.10. '
                                   'Check DAC/ADC compression, source state or noise before accepting a response.' % linearity)
        result['tone_hz'] = float(tone_hz)
        rate = FS_CLK/(1 << dec)
        if min(tone_hz-fractions*rate) <= 0 or max(tone_hz-fractions*rate) >= 50e6:
            raise ValueError('Swept LO leaves the 0..50 MHz supported RF range; reduce offsets.')
        plan = dict(centre_hz=float(tone_hz), sample_rate_hz=rate, decimation_log2=dec,
                    fir_half_counts=profile['half_counts'])
        modes = ('bypass', 'auto') if dec >= 8 else ('bypass',)
        rng = np.random.RandomState(seed)
        # Fixed RF avoids importing analogue gain-versus-frequency ripple into
        # the digital response, even when source and ADC share the board clock.
        for fraction in rng.permutation(fractions):
            lo_word = _lo_word(tone_hz-fraction*rate)
            lo_actual = lo_word*FS_CLK/float(1 << 32)
            offset = tone_hz-lo_actual
            for mode in rng.permutation(modes):
                records, input_powers = [], []
                for repeat in range(int(repeats)):
                    voltage = raw_input()
                    if np.std(voltage) < 4*ADC_RAW_VOLTS_PER_COUNT:
                        raise RuntimeError('Raw input RMS is below four ADC counts: insufficient level for a reliable tone calibration. '
                                           'Check source/cabling and independently verify a small input level before retrying.')
                    input_powers.append(float(np.var(voltage)))
                    raw = capture(lo_word, dec, n, settle=settle_s, fir_mode=str(mode))
                    raw = np.asarray(raw)
                    if raw.shape != (n,) or not np.all(np.isfinite(raw)) or max(np.max(abs(raw.real)), np.max(abs(raw.imag))) >= .98*(1 << 31):
                        raise RuntimeError('DMA shape/nonfinite/32-bit clipping failure; reject this filter measurement.')
                    records.append(raw*CIC_VOLTS_PER_COUNT)
                    check_source()
                stats = analyse_filter_tone_records(records, rate, offset)
                row = dict(stats, fraction=float(fraction), offset_hz=float(offset), fir_mode=str(mode),
                           input_power_v2=float(np.mean(input_powers)),
                           input_power_scatter=float(np.std(input_powers, ddof=1)/max(np.mean(input_powers), 1e-30)))
                # The 2^29 scale makes |I+jQ| the RF sine PEAK amplitude.
                # Therefore half its mean square is the equivalent real RF power.
                row['absolute_gain_check'] = row['power_v2']/max(2*row['input_power_v2'], 1e-30)
                result['rows'].append(row)
                print('offset %+8.2f kHz, FIR %-6s: SNR %.1f dB, repeat scatter %.2f%%' %
                      (offset/1e3, mode, stats['snr_db'], 100*stats['power_relative_scatter']))
        if read_acquisition_fir()['digest'] != profile['digest']:
            raise RuntimeError('FIR coefficients changed during the scan. Discard results; no correction was accepted.')
        full_shutdown()  # Analysis/plotting occurs with the writer and outputs off.
        zero = next(r for r in result['rows'] if r['fraction'] == 0 and r['fir_mode'] == 'bypass')
        reference = zero['absolute_gain_check']
        if not .9 <= reference <= 1.1:
            result['rejection_reasons'].append('CIC-to-raw-ADC sine scaling differs by >10%% (power ratio %.4g).' % reference)
        fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
        for mode in modes:
            rows = sorted([r for r in result['rows'] if r['fir_mode'] == mode], key=lambda r: r['offset_hz'])
            x = np.array([r['offset_hz'] for r in rows])
            measured = np.array([r['absolute_gain_check']/reference for r in rows])
            mode_plan = dict(plan, fir_mode=mode)
            predicted = filter_response_components(tone_hz+x, mode_plan)['combined']
            residual = 10*np.log10(measured/predicted)
            ripple = float(np.ptp(10*np.log10(measured)))
            max_error = float(np.max(abs(residual)))
            reasons = []
            if any(r['snr_db'] < 20 or r['power_relative_scatter'] > .03 or
                   r['input_power_scatter'] > .03 or not r['parseval']['accepted'] for r in rows):
                reasons.append('%s: inadequate tone SNR (<20 dB), >3%% repeat/input scatter, or FFT failure' % mode)
            if max_error > maximum_model_error_db:
                reasons.append('%s: measured/model error %.3f dB exceeds %.3f dB' % (mode, max_error, maximum_model_error_db))
            if mode == 'auto' and ripple > maximum_ripple_db:
                reasons.append('FIR hardware product ripple %.3f dB exceeds %.3f dB: narrow passband, inspect coefficients, or use qualified software correction' %
                               (ripple, maximum_ripple_db))
            response = {'accepted': not reasons and not result['rejection_reasons'],
                        'offset_hz': x, 'power_gain': measured, 'decimation_log2': dec,
                        'fir_bypassed': mode == 'bypass' or dec < 8, 'fir_digest': profile['digest'],
                        'clock_hz': float(FS_CLK), 'timestamp_epoch_s': time.time(),
                        'passband_ripple_db': ripple, 'maximum_model_error_db': max_error,
                        'rejection_reasons': reasons, 'relative_digital_response_only': True,
                        'source': source, 'tone_hz': float(tone_hz),
                        'absolute_voltage_calibrated': False, 'independent_clock_test': False}
            # Conservative propagation; common-reference covariance is not removed.
            # Independent source/ADC calibration errors are not measured by this scan.
            response['power_gain_uncertainty'] = measured*np.sqrt(np.array([
                r['power_relative_scatter']**2+r['input_power_scatter']**2+
                zero['power_relative_scatter']**2+zero['input_power_scatter']**2
                for r in rows])/float(repeats))
            response['uncertainty_description'] = 'repeat-based standard uncertainty; excludes absolute source/ADC calibration'
            result['responses'][mode] = response
            axes[0].plot(x/1e3, 10*np.log10(measured), 'o-', label=mode+' measured')
            axes[0].plot(x/1e3, 10*np.log10(predicted), '--', label=mode+' model')
            axes[1].plot(x/1e3, residual, 'o-', label=mode)
            print('%s: ripple %.4f dB; maximum model residual %.4f dB; accepted=%s' %
                  (mode, ripple, max_error, response['accepted']))
        axes[0].set_ylabel('Gain relative to bypass centre (dB)'); axes[0].legend()
        axes[1].set_ylabel('Measured / predicted (dB)'); axes[1].set_xlabel('Offset from LO (kHz)')
        for ax in axes: ax.grid(True, alpha=.25)
        fig.tight_layout(); plt.show()
        result['accepted'] = all(r['accepted'] for r in result['responses'].values())
        for r in result['responses'].values():
            for reason in r['rejection_reasons']: print('REJECTED: '+reason)
        for reason in result['rejection_reasons']: print('REJECTED: '+reason)
        return result
    except BaseException as exc:
        result['accepted'] = False
        for response in result['responses'].values(): response['accepted'] = False
        result['error'] = '%s: %s' % (type(exc).__name__, exc)
        raise
    finally:
        try:
            full_shutdown()
            if gen.r(0x04) or gen.r(0x00) & 0xFF != 0xC0:
                raise RuntimeError('Generator A amplitude/DC or control is nonzero after shutdown.')
            gen.assert_b_zero()
            result['shutdown_verified'] = True
        except BaseException:
            result['accepted'] = False
            for response in result['responses'].values(): response['accepted'] = False
            raise RuntimeError('Full shutdown could not be verified. Keep OUT1/trap disconnected, turn off the external '
                               'generator manually, and investigate the register connection before retrying.')
