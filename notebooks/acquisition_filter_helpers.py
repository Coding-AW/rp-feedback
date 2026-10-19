# These definitions are inlined in Step 6; the notebook imports no local file.
# The qualified 309-tap symmetric FIR stores 155 signed Q1.17 coefficients.
QUALIFIED_FIR_HALF_COUNTS = [0]*57 + [
    -1, 0, 1, 0, 0, 0, 0, 0, 1, 0, -1, 0, 1, 1, -1, -1, 0, 1, 1, 0,
    -1, -1, 2, 2, -1, -3, 0, 3, 1, -1, -1, -1, 1, 4, 1, -6, -3, 6,
    4, -4, -4, 1, 2, 3, 2, -5, -8, 6, 14, -4, -16, 0, 13, 3, -4, -4,
    -10, -1, 24, 11, -34, -23, 35, 30, -24, -26, 4, 2, 19, 43, -35,
    -102, 34, 158, -12, -181, -19, 135, 30, 14, 32, -295, -249, 716, 731,
    -1257, -1619, 1860, 3117, -2418, -5566, 2729, 9743, -2247, -18165,
    -1953, 44731, 71142]


def acquisition_fir_profile(half_counts=None):
    """Describe coefficients without writing hardware or trusting build ID alone."""
    values = np.asarray(QUALIFIED_FIR_HALF_COUNTS if half_counts is None else half_counts, dtype=float)
    if (values.shape != (155,) or not np.all(np.isfinite(values)) or
            np.any(values != np.rint(values)) or np.any(values < -131072) or np.any(values > 131071)):
        raise ValueError('FIR profile needs exactly 155 signed 18-bit integer coefficients.')
    counts = values.astype(np.int64)
    taps = np.concatenate((counts, counts[-2::-1])) / float(1 << 17)
    if abs(np.sum(taps)) < .01:
        raise ValueError('FIR DC gain is near zero. Check coefficient readback; no inverse correction is safe.')
    digest = hashlib.sha256(counts.astype('<i4').tobytes()).hexdigest()
    return {'half_counts': counts.tolist(), 'taps': taps, 'digest': digest,
            'dc_gain': float(np.sum(taps)), 'l1_gain_bound': float(np.sum(np.abs(taps)))}


def read_acquisition_fir():
    """Read the live I/shared FIR table; pointer writes do not change coefficients."""
    if ('0x%08X' % acq.build_id()).lower() != str(BUILD_ID_EXPECTED).lower():
        raise RuntimeError('Cannot read FIR: qualified FPGA identity does not match. Close competing board apps.')
    old_address = acq.r(0x40)
    values = []
    try:
        for address in range(155):
            acq.w(0x40, address)
            if acq.r(0x40) != address:
                raise RuntimeError('FIR address readback failed at %d; do not trust this calibration.' % address)
            acq.r(0x44)  # discard first read: coefficient RAM has registered read latency
            word = int(acq.r(0x44)) & 0x3FFFF
            values.append(word - 0x40000 if word & 0x20000 else word)
    finally:
        acq.w(0x40, old_address)
    return acquisition_fir_profile(values)


def cic_power_response(frequency_hz, plan, stages=4):
    """Exact normalized four-stage, differential-delay-one CIC power response."""
    if stages != 4:
        raise ValueError('This FPGA has four CIC stages. Changing order requires an RTL rebuild, not a parameter here.')
    rate = float(plan['sample_rate_hz'])
    ratio = 1 << int(plan['decimation_log2'])
    relative = (np.asarray(frequency_hz, dtype=float)-float(plan['centre_hz']))/rate
    # sin(pi*f*R/Fs)/(R*sin(pi*f/Fs)) = sinc(f/Fout)/sinc(f/Fs).
    return np.abs(np.sinc(relative)/np.sinc(relative/ratio))**8


def filter_response_components(frequency_hz, plan):
    """Predict CIC, FIR and combined gains, using stored or live-read coefficients."""
    from scipy.signal import freqz
    dec = int(plan['decimation_log2'])
    mode = plan.get('fir_mode', 'auto')
    if not 6 <= dec <= 12 or mode not in ('auto', 'bypass'):
        raise ValueError("Use decimation_log2=6..12 and fir_mode='auto' or 'bypass'.")
    frequency = np.asarray(frequency_hz, dtype=float)
    offset = (frequency-float(plan['centre_hz']))/float(plan['sample_rate_hz'])
    profile = acquisition_fir_profile(plan.get('fir_half_counts'))
    _, response = freqz(profile['taps'], worN=2*np.pi*offset)
    cic = cic_power_response(frequency, plan)
    bypass = mode == 'bypass' or dec < FIR_MIN_DECIMATION_LOG2
    fir = np.ones_like(cic) if bypass else np.abs(response)**2
    return {'cic': cic, 'fir': fir, 'combined': cic*fir,
            'fir_bypassed': bypass, 'fir_digest': profile['digest']}


def acquisition_response_power(frequency_hz, plan, calibration=None):
    """Return total power gain; never assume an enabled FIR is flat everywhere."""
    frequency = np.asarray(frequency_hz, dtype=float)
    model = filter_response_components(frequency, plan)
    if calibration is not None:
        checks = (calibration.get('accepted') is True,
                  calibration.get('decimation_log2') == int(plan['decimation_log2']),
                  calibration.get('fir_bypassed') == model['fir_bypassed'],
                  calibration.get('fir_digest') == model['fir_digest'],
                  calibration.get('clock_hz') == float(plan['sample_rate_hz'])*(1 << int(plan['decimation_log2'])))
        if not all(checks):
            raise ValueError('Response calibration is rejected or belongs to different decimation, FIR coefficients/state '
                             'or clock. Select the matching measured response or use the explicitly labelled model.')
        measured_f = np.asarray(calibration['offset_hz'], dtype=float)
        measured_p = np.asarray(calibration['power_gain'], dtype=float)
        if (measured_f.ndim != 1 or measured_f.shape != measured_p.shape or measured_f.size < 3 or
                not np.all(np.isfinite(measured_f+measured_p)) or np.any(np.diff(measured_f) <= 0) or
                np.any(measured_p <= 0)):
            raise ValueError('Measured response must have sorted unique finite offsets and positive power gains.')
        # Calibration moves with LO because a fixed RF tone isolates the digital
        # baseband response. Absolute ADC/RF gain remains a separate calibration.
        gain = np.interp(frequency-float(plan['centre_hz']), measured_f, measured_p, left=np.nan, right=np.nan)
        return gain, 'measured fixed-RF-tone / swept-LO digital response'
    return model['combined'], ('modelled exact CIC; FIR bypassed' if model['fir_bypassed'] else
                               'modelled CIC x actual FIR coefficients; not a physical calibration')


def correct_acquisition_response(spectrum, plan, calibration=None,
                                 maximum_correction_db=MAX_RESPONSE_CORRECTION_DB):
    """Undo measured/modelled gain only where inversion is bounded; never undo aliasing."""
    frequency = np.asarray(spectrum['frequency_hz'], dtype=float)
    raw = np.asarray(spectrum['psd_v2_per_hz'], dtype=float)
    if raw.shape != frequency.shape or not np.isfinite(maximum_correction_db) or maximum_correction_db < 0:
        raise ValueError('Response correction requires matching PSD/frequency arrays and a finite nonnegative correction limit.')
    gain, source = acquisition_response_power(frequency, plan, calibration)
    valid = np.isfinite(gain) & (gain >= 10**(-float(maximum_correction_db)/10))
    corrected = np.full(raw.shape, np.nan)
    corrected[valid] = raw[valid]/gain[valid]
    out = dict(spectrum)
    out.update(raw_psd_v2_per_hz=raw, psd_v2_per_hz=corrected, acquisition_power_gain=gain,
               response_correction_valid=valid, response_source=source,
               maximum_response_correction_db=float(maximum_correction_db))
    return out
