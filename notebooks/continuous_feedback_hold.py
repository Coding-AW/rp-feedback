"""Explicit enable/disable pair for externally observed continuous feedback."""

HELD_FEEDBACK_HARD_CEILING_COUNTS = 1024
if 'HELD_FEEDBACK_STATE' not in globals():
    HELD_FEEDBACK_STATE = {'enabled': False, 'last_action': 'definition loaded'}


def enable_held_feedback(coefficient_counts, phase_deg,
                         reference_frequency_hz=40.9e6,
                         maximum_coefficient_counts=1024):
    """Latch one bounded gain/phase setting until explicitly disabled.

    The function returns after writing the registers. The FPGA continues using
    those coefficients until disable_held_feedback(), another program, a new
    bitstream, or a reboot changes them. There is deliberately no software loop
    or automatic timeout, so an external physical disconnect remains essential.
    """
    import time
    import numpy as np
    global HELD_FEEDBACK_STATE
    try:
        full_shutdown()
        count_value=float(coefficient_counts)
        ceiling_value=float(maximum_coefficient_counts)
        if (not np.isfinite(count_value) or count_value != int(count_value) or
                not np.isfinite(ceiling_value) or ceiling_value != int(ceiling_value)):
            raise ValueError('coefficient_counts and maximum_coefficient_counts must be finite integers. No feedback was enabled.')
        count=int(count_value); ceiling=int(ceiling_value)
        if not 1 <= ceiling <= HELD_FEEDBACK_HARD_CEILING_COUNTS:
            raise ValueError('maximum_coefficient_counts must be 1..%d. The hard ceiling cannot be raised by this function.' % HELD_FEEDBACK_HARD_CEILING_COUNTS)
        if not 1 <= count <= ceiling:
            raise ValueError('Requested coefficient_counts=%d is outside the enabled range 1..%d. Use disable_held_feedback() for zero.' % (count,ceiling))
        phase=float(phase_deg); reference=float(reference_frequency_hz)
        rf_limit=min(FS_CLK/2.,RP_LIMITS['input_bandwidth_hz'],RP_LIMITS['output_bandwidth_hz'])
        if not np.isfinite(phase) or not np.isfinite(reference) or not 0 < reference < rf_limit:
            raise ValueError('phase_deg must be finite and reference_frequency_hz must lie between zero and %.3f MHz.' % (rf_limit/1e6))
        actual_build='0x%08X' % acq.build_id()
        if actual_build.lower() != str(BUILD_ID_EXPECTED).lower():
            raise RuntimeError('Feedback was not enabled: FPGA identity %s does not match qualified build %s.' % (actual_build,BUILD_ID_EXPECTED))

        # This fresh raw-ADC capture includes DC and out-of-band pickup. It is a
        # headroom guard, not a measurement of the resonant tone amplitude.
        codes,_=sc.acquire(dec=1,n=4096,chan='A')
        voltage=np.asarray(codes,dtype=float)*float(ADC_RAW_VOLTS_PER_COUNT)
        if voltage.shape != (4096,) or not np.all(np.isfinite(voltage)):
            raise RuntimeError('Feedback was not enabled: the fresh IN1 safety capture was incomplete or non-finite.')
        input_peak_v=float(np.max(np.abs(voltage)))
        input_dc_v=float(np.mean(voltage))
        command=quantized_feedback_vector(count,phase,reference)
        output_bound_vpk=(2.*input_peak_v/RP_LIMITS['input_lv_full_scale_vpk']*
                          (abs(command['ci_signed'])+abs(command['cq_signed']))/16384.*
                          RP_LIMITS['output_full_scale_vpk_into_50ohm'])
        if input_peak_v >= ADC_OPERATING_GUARD_VPK:
            raise RuntimeError('Feedback was not enabled: fresh IN1 peak %.4f V reached the %.4f V operating guard.' % (input_peak_v,ADC_OPERATING_GUARD_VPK))
        if abs(input_dc_v) > IN1_DC_OFFSET_MAX_V:
            raise RuntimeError('Feedback was not enabled: fresh IN1 mean %+.4f V exceeded the +/-%.4f V DC guard.' % (input_dc_v,IN1_DC_OFFSET_MAX_V))
        if output_bound_vpk >= OUT1_OPERATING_GUARD_VPK:
            raise RuntimeError('Feedback was not enabled: conservative OUT1 bound %.4f Vpk reached the %.4f Vpk operating guard.' % (output_bound_vpk,OUT1_OPERATING_GUARD_VPK))

        gen.assert_b_zero()
        ps.config_delay(reference)
        ps.set(count/16384.0,phase)
        readback=ps.readback()
        if (readback['ci'] != command['ci_word'] or readback['cq'] != command['cq_word'] or
                readback['bypass'] != 0 or readback['monitor'] != 0):
            raise RuntimeError('Feedback coefficient verification failed: expected CI/CQ 0x%04X/0x%04X with bypass and OUT2 off, read %r.' %
                               (command['ci_word'],command['cq_word'],readback))
        gen.assert_b_zero()
        HELD_FEEDBACK_STATE={'enabled':True,'coefficient_counts':count,
            'maximum_coefficient_counts':ceiling,'requested_phase_deg':phase%360.,
            'actual_phase_deg':command['actual_phase_deg'],'reference_frequency_hz':reference,
            'ci_signed':command['ci_signed'],'cq_signed':command['cq_signed'],
            'actual_gain':command['actual_gain'],'input_peak_v':input_peak_v,
            'input_dc_v':input_dc_v,'conservative_out1_bound_vpk':output_bound_vpk,
            'enabled_epoch_s':time.time(),'out2_enabled':False,
            'automatic_timeout':False}
        print('HELD FEEDBACK ENABLED: count %d/%d, requested phase %.2f deg, actual phase %.2f deg at %.6f MHz.' %
              (count,ceiling,phase%360.,command['actual_phase_deg'],reference/1e6))
        print('CI=%d, CQ=%d; IN1 peak %.4f V, mean %+.4f V; conservative OUT1 bound %.4f Vpk.' %
              (command['ci_signed'],command['cq_signed'],input_peak_v,input_dc_v,output_bound_vpk))
        print('The coefficients remain active after this cell returns. Run disable_held_feedback() immediately after the external measurement.')
        return dict(HELD_FEEDBACK_STATE)
    except BaseException as exc:
        HELD_FEEDBACK_STATE={'enabled':False,'last_error':'%s: %s' % (type(exc).__name__,str(exc))}
        try: full_shutdown()
        except BaseException as shutdown_error:
            raise RuntimeError('Feedback setup failed and shutdown could not be verified. Disconnect OUT1 physically. Setup error: %s; shutdown error: %s' % (exc,shutdown_error))
        raise


def disable_held_feedback():
    """Clear held feedback, both generators, OUT2 and acquisition, then verify."""
    import time
    global HELD_FEEDBACK_STATE
    full_shutdown()
    readback=ps.readback()
    if readback['ci'] or readback['cq'] or readback['monitor']:
        raise RuntimeError('DISABLE FAILED: feedback/OUT2 readback remains nonzero after full shutdown. Disconnect OUT1 physically: %r' % readback)
    HELD_FEEDBACK_STATE={'enabled':False,'disabled_epoch_s':time.time(),
                         'last_action':'full shutdown verified'}
    print('HELD FEEDBACK DISABLED: CI=CQ=0; generators, OUT2 and acquisition are off.')
    return dict(HELD_FEEDBACK_STATE)
