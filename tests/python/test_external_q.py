# -*- coding: utf-8 -*-
"""Acquisition-safety and separate analyser-envelope tests."""
import contextlib
import io
import json
import os

import numpy as np

import run_notebook_mocks


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
ANALYSIS_NB = os.path.join(ROOT, 'notebooks', 'acquisition',
                           'external_spectrum_analysis.ipynb')


def must_fail(fn, expected):
    try:
        fn()
    except (ValueError, RuntimeError) as exc:
        assert any(word in str(exc).lower() for word in expected), str(exc)
        return
    raise AssertionError('invalid analyser trace unexpectedly passed')


def analysis_namespace():
    namespace = {'__name__': '__test__'}
    with io.open(ANALYSIS_NB, encoding='utf-8') as handle:
        notebook = json.load(handle)
    for index, cell in enumerate(notebook['cells']):
        if cell['cell_type'] == 'code':
            exec(compile(''.join(cell['source']), '<analysis cell %d>' % index,
                         'exec'), namespace)
    return namespace


def write_siglent(path, f0, q, spacing=None, missing=(), attenuation_db=18.0,
                  noise_db=0.03, seed=12514):
    """Create a max-hold impulse comb with a Lorentzian power envelope."""
    rng = np.random.RandomState(seed)
    linewidth = f0/q
    spacing = linewidth/8.0 if spacing is None else float(spacing)
    f = np.linspace(f0-4.5*linewidth, f0+4.5*linewidth, 751)
    floor_dbm = -82.0-attenuation_db
    power = np.full(len(f), 10**(floor_dbm/10.0))
    tones = np.arange(f0-4*linewidth, f0+4.01*linewidth, spacing)
    for number, tone in enumerate(tones):
        if number in missing:
            continue
        envelope_dbm = -25.0-attenuation_db - 10*np.log10(
            1+(2*(tone-f0)/linewidth)**2)
        centre = int(np.argmin(abs(f-tone)))
        # A narrow three-bin analyser response approximates finite RBW.
        for delta, weight in ((-1, 0.12), (0, 1.0), (1, 0.12)):
            point = centre+delta
            if 0 <= point < len(f):
                power[point] += weight*10**(envelope_dbm/10.0)
    dbm = 10*np.log10(power)+rng.normal(0, noise_db, len(f))
    header = ['Machine Module,SVA1015X,test', 'Y Axis Scale,LOG',
              'Y Axis Unit,dBm', 'Number of Points,%d' % len(f),
              'RBW,1000.000000,Manual', 'Trace Type,Max Hold', 'Trace Data']
    with io.open(path, 'w', encoding='utf-8', newline='') as handle:
        handle.write('\n'.join(header)+'\n')
        for frequency, level in zip(f, dbm):
            handle.write('%.6f,%.6f\n' % (frequency, level))


def test_analysis(a, scratch, created):
    # Exercise analyser-bin quantisation: a 6.944 kHz tone step lands on a
    # 2.667 kHz grid as alternating two- and three-bin gaps. Remove one tone to
    # verify that the integer-multiple handling also tolerates a missing impulse.
    analyser_f = np.linspace(38.94e6, 40.94e6, 751)
    tone_f = np.arange(38.95e6, 40.93e6, 6944.0)
    peak_indices = np.unique([int(np.argmin(abs(analyser_f-tone))) for tone in tone_f])
    peak_indices = np.delete(peak_indices, 80)
    recovered_spacing = a['_grid_spacing'](
        analyser_f[peak_indices], np.median(np.diff(analyser_f)))
    assert abs(recovered_spacing-6944.0) < 250.0, recovered_spacing

    cases = [(39.94e6, 180.0, (11,)), (39.93e6, 750.0, (8, 31))]
    for number, (f0, q, missing) in enumerate(cases):
        path = os.path.join(scratch, 'synthetic_envelope_%d.csv' % number)
        created.append(path)
        write_siglent(path, f0, q, missing=missing, attenuation_db=12+number*9,
                      seed=12514+number)
        result = a['fit_impulse_envelope'](path)
        assert abs(result['Q']/q-1) < 0.10, result
        assert abs(result['f0']-f0) < 0.05*(f0/q), result
        assert result['n_peaks'] >= 10

    # A shifted resonance is valid and must be recovered at its actual position.
    path = os.path.join(scratch, 'frequency_offset.csv'); created.append(path)
    write_siglent(path, 40.015e6, 420.0, noise_db=0.01)
    shifted = a['fit_impulse_envelope'](path)
    assert abs(shifted['f0']-40.015e6) < 2000

    # Too few impulses and an unresolved linewidth are explicit failures.
    path = os.path.join(scratch, 'too_sparse.csv'); created.append(path)
    write_siglent(path, 40e6, 500.0, spacing=120e3)
    must_fail(lambda: a['fit_impulse_envelope'](path), ('fewer', 'unresolved'))

    shift_specs = [(0.0, 0.0, 0.0, True), (90.0, 0.3, 18e3, False),
                   (90.0, 0.6, 41e3, False), (270.0, 0.6, -36e3, False)]
    entries = []
    for number, (phase, gain, shift, reference) in enumerate(shift_specs):
        path = os.path.join(scratch, 'shift_campaign_%d.csv' % number)
        created.append(path)
        write_siglent(path, 39.94e6+shift, 350.0+80*gain,
                      missing=(10+number,), seed=12700+number)
        entries.append({'phase_deg': phase, 'gain_frac': gain, 'path': path,
                        'reference': reference})
    campaign = a['fit_shift_campaign'](entries)
    for row, spec in zip(campaign, shift_specs):
        assert abs(row['delta_f']-spec[2]) < 0.05*row['linewidth'], row
    must_fail(lambda: a['fit_shift_campaign'](
        [dict(entries[0], reference=False), entries[1]]), ('exactly one',))
    must_fail(lambda: a['fit_shift_campaign'](
        [entries[0], dict(entries[1], reference=True)]), ('exactly one',))
    must_fail(lambda: a['fit_shift_campaign'](
        [entries[0], dict(entries[0], reference=False)]), ('duplicate',))
    must_fail(lambda: a['fit_shift_campaign'](
        [entries[0], dict(entries[1], clipped=True)]), ('clipped',))

    phase_entries = [entries[0]]
    for phase in range(0, 360, 30):
        shift = 60e3*np.sin(np.radians(phase))
        path = os.path.join(scratch, 'phase_scan_%03d.csv' % phase)
        created.append(path)
        write_siglent(path, 39.94e6+shift, 420.0, missing=(12,),
                      seed=13000+phase)
        phase_entries.append({'phase_deg': phase, 'gain_frac': 0.6,
                              'path': path})
    phase_results = a['fit_shift_campaign'](phase_entries)
    best = a['select_maximum_shifts'](phase_results)[0]
    assert best['phase_deg'] in (90.0, 270.0), best
    assert best['drop_at_original_db'] > 3.0, best
    assert abs(best['shift_original_linewidths']) > 0.45, best
    refinement = a['recommend_phase_refinement'](phase_results)
    assert any(abs(row['phase_deg']-best['phase_deg']) < 1e-9 for row in refinement)
    must_fail(lambda: a['select_maximum_shifts'](
        [row for row in phase_results if row['reference'] or row['phase_deg'] < 120]),
        ('complete phase', 'fewer'))

    # When the supplied bench files are present, pin their established results.
    real = [(r'D:\f 0.0 v2.csv', 39.93972193060446e6, 179.8724597506354),
            (r'D:\f 0.9 v2.csv', 39.92891076062464e6, 746.7647785643243),
            (r'D:\s 0.9 52.1.csv', 39.8435346e6, 243.1348)]
    for path, f0, q in real:
        if os.path.exists(path):
            result = a['fit_impulse_envelope'](path)
            assert abs(result['f0']-f0) < 1000, result
            assert abs(result['Q']-q) < 2.0, result

    shift_path = r'D:\s 0.9 52.1.csv'
    if os.path.exists(shift_path):
        shift = a['fit_single_shift'](shift_path)
        assert abs(shift['delta_f']-(-96.1874e3)) < 1000, shift
        assert abs(shift['shift_original_linewidths']-(-0.43319)) < 0.01, shift
        assert abs(shift['drop_at_original_db']-3.758) < 0.10, shift
        q_enhanced = a['fit_impulse_envelope'](r'D:\f 0.9 v2.csv')
        assert abs((shift['f0']-q_enhanced['f0'])-(-85.3762e3)) < 1000
        assert callable(a['plot_two_envelopes_measured'])
        new_q_path = r'D:\q 0.9.csv'
        if os.path.exists(new_q_path):
            new_q = a['fit_impulse_envelope'](new_q_path)
            assert abs(new_q['f0']-39.9292497112e6) < 1000, new_q
            assert abs(new_q['linewidth']-53.6547784e3) < 1000, new_q
            assert abs(new_q['Q']-744.1881) < 2.0, new_q
            import matplotlib.pyplot as plt
            figure, axis = plt.subplots()
            comparison = a['plot_same_frequency_comparison'](
                new_q, shift, (17907, -5024), (7255, 17126), ax=axis)
            plt.close(figure)
            assert abs((shift['f0']-new_q['f0'])-(-85.71499e3)) < 1000
            assert abs(comparison['difference_db']-13.10339) < 0.10
            assert abs(comparison['coefficient_magnitude_difference_db']) < 0.01
            open_path = r'D:\q 0.0.csv'
            if os.path.exists(open_path):
                open_fit = a['fit_impulse_envelope'](open_path)
                assert abs(open_fit['f0']-39.9403980438e6) < 1000, open_fit
                assert abs(open_fit['linewidth']-221.2724662e3) < 1000, open_fit
                assert abs(open_fit['Q']-180.5032) < 2.0, open_fit
                figure, axis = plt.subplots()
                calibrated = a['plot_calibrated_three_way'](
                    open_fit, new_q, shift, ax=axis)
                plt.close(figure)
                assert abs(calibrated['q_enhanced']['delta_f']-(-11.14833e3)) < 1000
                assert abs(calibrated['shifted']['delta_f']-(-96.86332e3)) < 1000
                assert abs(calibrated['q_enhanced']['q_ratio']-4.123) < 0.02
                assert abs(calibrated['shifted']['q_ratio']-1.347) < 0.02
                assert abs(calibrated['q_minus_shifted_at_q_f0_db']-13.10339) < 0.10


def test_acquisition(g):
    for name in ('external_q_prepare', 'external_q_replay',
                 'external_shift_prepare', 'external_shift_replay'):
        assert callable(g[name]), name
    for removed in ('external_q_load', 'external_q_plot', 'external_q_summary',
                    'external_shift_campaign', 'external_shift_phase_campaign'):
        assert removed not in g, removed
    assert g['FB_EXT_REPEATS'] == 4

    state = g['external_q_prepare'](0.0)
    state['freqs'] = np.linspace(state['freqs'].min(), state['freqs'].max(), 121)
    prepare = g['external_q_prepare']
    g['external_q_prepare'] = lambda frac, monitor_shift=0: state
    g['external_q_replay'](0.0, repeats=2, dwell=1e-9)
    g['external_q_prepare'] = prepare
    board = run_notebook_mocks.fakehw._BOARD

    shift_state = g['external_shift_prepare'](90, 0.6)
    assert shift_state['step_hz'] <= g['LW']/32.0*(1+1e-12)
    assert shift_state['half_span_hz'] >= 4*g['LW']
    assert shift_state['A'] == 0.6*g['FB_GAIN_CEIL']
    g['all_off']()
    must_fail(lambda: g['external_shift_replay'](90, 0.6, repeats=0),
              ('repeats',))
    must_fail(lambda: g['external_shift_prepare'](90, 0.951), ('gain_frac',))
    g['external_shift_replay'](270, 0.4, repeats=1, dwell=1e-9,
                               half_span_hz=4*g['LW'], step_hz=g['LW']/32)

    real_freq = g['gen'].freq; calls = [0]
    def corrupt_after_three(frequency):
        result = real_freq(frequency); calls[0] += 1
        if calls[0] == 3:
            g['ps'].w(0x00, g['ps'].r(0x00) ^ 1)
        return result
    g['gen'].freq = corrupt_after_three
    must_fail(lambda: g['external_q_replay'](0.70, repeats=1, dwell=1e-9),
              ('changed',))
    g['gen'].freq = real_freq
    real_clip = g['ps'].monitor_clipped
    g['ps'].monitor_clipped = lambda: True
    must_fail(lambda: g['external_q_replay'](0.0, repeats=1, dwell=1e-9),
              ('clipped',))
    g['ps'].monitor_clipped = real_clip
    assert board._r(board.GEN, 0x04) == 0
    assert board._r(board.PS, 0x00) == board._r(board.PS, 0x04) == 0
    assert (board._r(board.PS, 0x18) & 0x3F) == 0
    assert (board._r(board.SEQ, 0x00) & 4) == 0
    assert board._r(board.ACQ, 0x00) == 0
    assert (board._r(board.EMU, 0x00) & 1) == 0


def main():
    with contextlib.redirect_stdout(io.StringIO()):
        errors, _, hardware = run_notebook_mocks.run(
            'baseline', stop_on_error=True, savefigs=False, return_globals=True)
    assert not errors, errors
    analysis = analysis_namespace()
    scratch = os.path.join(ROOT, 'build'); os.makedirs(scratch, exist_ok=True)
    created = []
    try:
        test_analysis(analysis, scratch, created)
        test_acquisition(hardware)
    finally:
        for path in created:
            if os.path.exists(path):
                os.remove(path)
    print('PASS: separate analyser fitting and safe acquisition tests')


if __name__ == '__main__':
    main()
