"""Resumable passive gain/phase mapping; Python 3.5 and old SciPy compatible."""


def run_feedback_map(stage, config, coarse_map=None, resume=False,
                     measurement_function=None):
    """Run one explicit coarse/final map stage and checkpoint every spectrum.

    This function can energise OUT1. It never applies more than the configured
    coefficient ceiling and always attempts full_shutdown() on every exit.
    """
    import os, io, csv, json, time, math, hashlib, shutil, gc
    import numpy as np
    from scipy.ndimage import median_filter

    measure = measure_manual_feedback if measurement_function is None else measurement_function
    def call_measurement(**kwargs):
        return measure(**kwargs)
    cfg = {
        'campaign_name': 'current_feedback_map',
        'minimum_coefficient_counts': 128,
        'maximum_coefficient_counts': 1024, 'maximum_k': .85,
        'phase_seed_deg': 225., 'profile': 'fast',
        'coarse_averages': 6, 'final_averages': 16,
        'time_budget_minutes': 55., 'campaign_root': 'feedback_maps',
        'baseline_frequency_range_hz': (40.15e6, 41.65e6),
        'baseline_fit_range_hz': (40.20e6, 41.60e6),
        'locator_frequency_range_hz': (40.15e6, 41.65e6),
        'baseline_decimation_log2': 6, 'baseline_samples_per_record': 8192,
        'baseline_averages': 16, 'feedback_decimation_log2': 8,
        'feedback_minimum_span_hz': 180e3, 'feedback_maximum_span_hz': 1.50e6,
        'feedback_linewidths_full_span': 4.0,
        'feedback_samples_per_record': 8192,
        'map_minimum_edge_coverage_linewidths': .35,
        'coarse_maximum_fit_uncertainty_linewidths': .60,
        'final_maximum_fit_uncertainty_linewidths': .35,
        'feedback_response_calibration': None, 'baseline_response_calibration': None,
        'maximum_background_ratio': 4., 'maximum_carrier_fraction': .35,
        'repeat_fraction': .10, 'seed': 225, 'q_bounds': (20., 1e6)}
    cfg.update(dict(config))
    if stage not in ('coarse', 'final'):
        raise ValueError("stage must be 'coarse' or 'final'. No hardware was accessed.")
    integers = ('minimum_coefficient_counts','maximum_coefficient_counts', 'coarse_averages', 'final_averages',
                'baseline_decimation_log2', 'baseline_samples_per_record',
                'feedback_decimation_log2', 'feedback_samples_per_record')
    for name in integers:
        value = cfg[name]
        if not np.isfinite(value) or value != int(value):
            raise ValueError('%s must be a finite integer; received %r.' % (name, value))
        cfg[name] = int(value)
    if not (1 <= cfg['maximum_coefficient_counts'] <= 1024):
        raise ValueError('maximum_coefficient_counts must be 1..1024. The 1024 ceiling is hard-coded in both planning and application.')
    if not (1 <= cfg['minimum_coefficient_counts'] <= cfg['maximum_coefficient_counts']):
        raise ValueError('minimum_coefficient_counts must be at least 1 and no greater than maximum_coefficient_counts.')
    if not (.05 <= float(cfg['maximum_k']) <= .85):
        raise ValueError('maximum_k must be 0.05..0.85; values closer to one are outside this campaign design.')
    if cfg['profile'] != 'fast' or not 1 <= float(cfg['time_budget_minutes']) <= 55:
        raise ValueError("This implementation supports profile='fast' with time_budget_minutes in 1..55.")
    if not (4 <= cfg['coarse_averages'] <= 64 and 4 <= cfg['final_averages'] <= 128 and
            0 <= float(cfg['repeat_fraction']) <= .25):
        raise ValueError('Averages must be 4..64 coarse and 4..128 final; repeat_fraction must be 0..0.25.')
    for name in ('baseline_frequency_range_hz','baseline_fit_range_hz','locator_frequency_range_hz'):
        if len(cfg[name]) != 2 or not np.all(np.isfinite(cfg[name])) or not 0 < cfg[name][0] < cfg[name][1] < FS_CLK/2:
            raise ValueError('%s must contain two ordered frequencies between zero and Nyquist.' % name)
    if not (cfg['baseline_frequency_range_hz'][0] <= cfg['baseline_fit_range_hz'][0] <
            cfg['baseline_fit_range_hz'][1] <= cfg['baseline_frequency_range_hz'][1]):
        raise ValueError('baseline_fit_range_hz must lie inside baseline_frequency_range_hz.')
    if not (10e3 <= float(cfg['feedback_minimum_span_hz']) <= float(cfg['feedback_maximum_span_hz']) and
            float(cfg['feedback_maximum_span_hz']) <= .8*FS_CLK/(1 << MIN_ACQUISITION_DECIMATION_LOG2)):
        raise ValueError('Feedback spans must be ordered, at least 10 kHz, and no wider than the acquisition path can safely display.')
    if not (1.0 <= float(cfg['feedback_linewidths_full_span']) <= 12.0 and
            .10 <= float(cfg['map_minimum_edge_coverage_linewidths']) <= 1.0 and
            .10 <= float(cfg['coarse_maximum_fit_uncertainty_linewidths']) <= 1.0 and
            .10 <= float(cfg['final_maximum_fit_uncertainty_linewidths']) <= 1.0):
        raise ValueError('Use feedback_linewidths_full_span=1..12, map edge coverage=0.10..1.0, and coarse/final fit-uncertainty limits=0.10..1.0.')

    def scalar(value):
        if isinstance(value, np.generic): return value.item()
        if isinstance(value, np.ndarray): return [scalar(v) for v in value.tolist()]
        if isinstance(value, (list, tuple)): return [scalar(v) for v in value]
        if isinstance(value, dict): return {str(k): scalar(v) for k, v in value.items()}
        return value

    def digest(value):
        raw = json.dumps(scalar(value), sort_keys=True, separators=(',', ':'), allow_nan=False)
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()

    def compact_fit(fit):
        """Keep scalar fit results only; frequency grids and model curves are discarded."""
        names=('accepted','reasons','f0_hz','f0_uncertainty_hz','q','q_uncertainty',
               'linewidth_hz','linewidth_uncertainty_hz','delta_bic','uncertainty_kind')
        return dict((name,scalar(fit[name])) for name in names if name in fit)

    def atomic_json(path, value):
        temporary = path+'.tmp'
        with io.open(temporary, 'w', encoding='utf-8') as handle:
            handle.write(json.dumps(scalar(value), sort_keys=True, indent=2, allow_nan=False))
            handle.flush(); os.fsync(handle.fileno())
        for attempt in range(6):
            try:
                os.replace(temporary, path); break
            except PermissionError:
                if attempt == 5: raise
                time.sleep(.05*(attempt+1))

    def accepted_fit(result, state):
        fit = result.get('fits', {}).get(state, {})
        if result.get('status') not in ('complete', 'review_required') or not fit.get('accepted'):
            raise RuntimeError('%s fit was rejected: %s' %
                               (state, '; '.join(fit.get('reasons', result.get('warnings', ['unknown fit failure'])))))
        return fit

    def baseline_call(label):
        return call_measurement(mode='baseline', averages=cfg['baseline_averages'], repeats=1,
            frequency_range_hz=tuple(cfg['baseline_frequency_range_hz']),
            fit_range_hz=tuple(cfg['baseline_fit_range_hz']),
            decimation_log2=cfg['baseline_decimation_log2'],
            samples_per_record=cfg['baseline_samples_per_record'],
            q_guess=float(cfg.get('baseline_q_guess', 150.)), q_bounds=tuple(cfg['q_bounds']),
            phase_reference_hz=float(cfg.get('phase_reference_hz', CENTRE_HZ)),
            response_calibration=cfg['baseline_response_calibration'],
            fir_mode='auto', show_plots=False, label=label)

    def point_call(count, phase, baseline, prediction, averages, label, force_broad=False):
        if not 1 <= int(count) <= min(1024, cfg['maximum_coefficient_counts']):
            raise RuntimeError('Hardware application refused coefficient count %r outside 1..%d.' %
                               (count, min(1024, cfg['maximum_coefficient_counts'])))
        centre = float(prediction.get('f0_hz', accepted_fit(baseline, 'before')['f0_hz']))
        q = max(21., float(prediction.get('q', accepted_fit(baseline, 'before')['q'])))
        width = centre/q
        if force_broad:
            low,high=map(float,cfg['locator_frequency_range_hz'])
            centre=(low+high)/2.;span=high-low
        else:
            span=min(float(cfg['feedback_maximum_span_hz']),
                     max(float(cfg['feedback_minimum_span_hz']),
                         float(cfg['feedback_linewidths_full_span'])*width))
            low,high=centre-span/2.,centre+span/2.
        dec = cfg['feedback_decimation_log2']
        while dec>0 and .80*FS_CLK/(1 << dec)<span: dec-=1
        rate = FS_CLK/(1 << dec)
        # Increase N, rather than silently narrowing the requested mapped band.
        wanted = int(math.ceil(30.*rate/max(width, 1.)))
        n = cfg['feedback_samples_per_record']
        while n < wanted and n < 65536: n *= 2
        n = min(n, 65536)
        return call_measurement(mode='feedback', baseline_measurement=baseline,
            coefficient_counts=int(count), phase_deg=float(phase), averages=int(averages), repeats=1,
            frequency_range_hz=(low, high), fit_range_hz=(low+span*.05, high-span*.05),
            lo_hz=centre, phase_reference_hz=float(cfg.get('phase_reference_hz', CENTRE_HZ)),
            decimation_log2=dec, samples_per_record=n, q_guess=q, q_bounds=tuple(cfg['q_bounds']),
            response_calibration=cfg['feedback_response_calibration'], fir_mode='auto',
            minimum_edge_coverage_linewidths=float(cfg['map_minimum_edge_coverage_linewidths']),
            maximum_fit_uncertainty_linewidths=float(cfg[stage+'_maximum_fit_uncertainty_linewidths']),
            max_active_seconds=300., show_plots=False, map_safety_mode=True, label=label)

    def vector(count, phase):
        command = quantized_feedback_vector(int(count), float(phase),
                                            float(cfg.get('phase_reference_hz', CENTRE_HZ)))
        return int(command['ci_signed']), int(command['cq_signed']), float(command['actual_phase_deg'])

    def coarse_schedule():
        circles = [v for v in (128, 512, 1024)
                   if cfg['minimum_coefficient_counts'] <= v <= cfg['maximum_coefficient_counts']]
        line = [v for v in (128, 256, 384, 512, 640, 768, 896, 1024)
                if cfg['minimum_coefficient_counts'] <= v <= cfg['maximum_coefficient_counts']]
        if cfg['minimum_coefficient_counts'] not in circles+line:
            line.append(cfg['minimum_coefficient_counts'])
        seeded=[220.,float(cfg['phase_seed_deg'])%360.,230.]
        phases = sorted(dict.fromkeys([float(v) for v in range(0, 360, 30)] + seeded +
                                      [(v+180.)%360. for v in seeded]))
        rows = []
        for count in sorted(dict.fromkeys(circles+line)):
            use = phases if count in circles else [float(cfg['phase_seed_deg']) % 360.,
                                                    (float(cfg['phase_seed_deg'])+180.) % 360.]
            # Deterministic opposite pairs limit drift bias while preserving resume order.
            remaining = list(use); pairs = []
            while remaining:
                phase = remaining.pop(0); pair=[phase]
                opposite = (phase+180.) % 360.
                if opposite in remaining: remaining.remove(opposite); pair.append(opposite)
                pairs.append(pair)
            np.random.RandomState(int(cfg['seed'])+int(count)).shuffle(pairs)
            ordered=[phase for pair in pairs for phase in pair]
            rows.extend([(count, phase, False) for phase in ordered])
        return rows

    def final_counts(coarse):
        rows = [p for p in coarse.get('points', []) if p.get('accepted') and p.get('k') is not None]
        by_count = {}
        for row in rows: by_count[row['count']] = max(row['k'], by_count.get(row['count'], -1e9))
        positive = sorted((k, v) for k, v in by_count.items() if v >= 0)
        if len(positive) < 2:
            raise ValueError('Final mapping needs at least two accepted coarse gains with nonnegative K.')
        counts = np.array([v[0] for v in positive], float)
        kvals = np.maximum.accumulate(np.array([v[1] for v in positive], float))
        keep = np.r_[True, np.diff(kvals) > 1e-5]
        counts, kvals = counts[keep], kvals[keep]
        target = np.linspace(0, min(.80, float(np.max(kvals))), 9)
        result = sorted(dict.fromkeys(int(round(v)) for v in np.interp(target, kvals, counts)))
        return [v for v in result if cfg['minimum_coefficient_counts'] <= v <= cfg['maximum_coefficient_counts']]

    if stage == 'coarse':
        schedule = coarse_schedule(); averages = cfg['coarse_averages']
    else:
        if isinstance(coarse_map, str): coarse_map = _feedback_map_load(coarse_map)
        if not isinstance(coarse_map, dict) or coarse_map.get('stage') != 'coarse':
            raise ValueError('Final mapping requires the accepted/partial coarse map dictionary or its directory.')
        if coarse_map.get('status') != 'complete':
            raise ValueError('Final mapping requires a completed coarse campaign. Review and explicitly resume the stopped coarse campaign first.')
        counts = final_counts(coarse_map)
        base_phases = [float(v) for v in range(0, 360, 15)]
        seed_phase = float(cfg['phase_seed_deg']) % 360.
        schedule=[]
        for count in counts:
            phases=list(base_phases)+[seed_phase]
            if coarse_map.get('phase_axes'):
                nearest=min(coarse_map['phase_axes'],key=lambda row:abs(row['count']-count))
                phases.extend([float(nearest[name])%360. for name in
                               ('regenerative_deg','degenerative_deg','positive_shift_deg','negative_shift_deg')])
            phases=sorted(dict.fromkeys(round(value,6) for value in phases))
            schedule.extend((count,phase,False) for phase in phases)
        rng = np.random.RandomState(int(cfg['seed']))
        repeats = int(math.ceil(len(schedule)*float(cfg['repeat_fraction'])))
        for index in sorted(rng.choice(len(schedule), size=repeats, replace=False), reverse=True):
            count, phase, _ = schedule[index]
            schedule.insert(index+1, (count, phase, True))
        averages = cfg['final_averages']

    estimated_seconds = sum(averages*(SETTLE+cfg['feedback_samples_per_record'] /
                            (FS_CLK/(1 << cfg['feedback_decimation_log2'])))+.5 for _ in schedule)
    estimated_seconds += 2*len(dict.fromkeys(row[0] for row in schedule))*cfg['baseline_averages']*(SETTLE+.01)
    estimated_bytes = max(16384,len(schedule)*1024)
    print('%s map: %d points; estimated %.1f minutes and %.2f MB (fit table only; no spectra or raw records).' %
          (stage.upper(), len(schedule), estimated_seconds/60., estimated_bytes/2**20))
    if estimated_seconds > 60*float(cfg['time_budget_minutes']):
        raise ValueError('Estimated %.1f minutes exceeds the %.1f-minute budget. Reduce averages/grid deliberately; no hardware was accessed.' %
                         (estimated_seconds/60., cfg['time_budget_minutes']))

    campaign_id = str(cfg['campaign_name'])+'_'+stage
    root = os.path.abspath(str(cfg['campaign_root'])); directory = os.path.join(root, campaign_id)
    if not os.path.isdir(directory): os.makedirs(directory)
    if shutil.disk_usage(directory).free < max(100*2**20, estimated_bytes*2):
        raise IOError('Insufficient disk space for atomic compact checkpoints; no hardware was accessed.')
    manifest_path = os.path.join(directory, 'manifest.json')
    config_digest = digest(cfg)
    stored_config=dict(cfg)
    for calibration_name in ('baseline_response_calibration','feedback_response_calibration'):
        calibration=stored_config.get(calibration_name)
        stored_config[calibration_name]=(None if calibration is None else
            {'digest':str(calibration.get('digest',digest(calibration))) if isinstance(calibration,dict) else digest(calibration)})
    hardware_digest=(globals().get('TOPOLOGY_RECORD',{}).get('digest') or
                     digest(globals().get('TOPOLOGY',{'unspecified':True})))
    manifest = {'schema_version': 2, 'stage': stage, 'config': scalar(stored_config),
                'config_digest': config_digest, 'campaign_directory': directory,
                'created_epoch_s': time.time(), 'status': 'planned', 'completed_ids': [],
                'stop_reason': None, 'build_id': str(BUILD_ID_EXPECTED),
                'fir_digest': read_acquisition_fir()['digest'],
                'hardware_digest':hardware_digest,'out2_used': False}
    if os.path.exists(manifest_path):
        with io.open(manifest_path, 'r', encoding='utf-8') as handle: old = json.load(handle)
        if not resume:
            raise IOError('Campaign directory already exists. Choose a new campaign_name, or explicitly pass resume=True.')
        for name in ('schema_version', 'stage', 'config_digest', 'build_id', 'fir_digest','hardware_digest'):
            if old.get(name) != manifest.get(name):
                raise ValueError('Resume refused: %s changed. Start a new campaign rather than mixing incompatible points.' % name)
        terminal_reason=str(old.get('stop_reason') or '').lower()
        if 'k stop' in terminal_reason or 'time-interpolated k' in terminal_reason:
            raise RuntimeError('Resume refused: this campaign reached its K safety boundary. Review the partial map; a resume must never advance to a higher gain after a regenerative stop.')
        manifest = old
    elif resume:
        raise IOError('resume=True was requested but no manifest exists at %s.' % manifest_path)
    atomic_json(manifest_path, manifest)

    completed = dict((int(v), True) for v in manifest.get('completed_ids', []))
    points = []
    summary_path = os.path.join(directory, 'summary.csv')

    def save_summary():
        fields = ('point_id','stage','count','phase_deg','actual_phase_deg','ci','cq','repeat',
                  'timestamp_epoch_s','accepted','q','q_uncertainty','q_ratio','f0_hz',
                  'f0_uncertainty_hz','linewidth_hz','linewidth_uncertainty_hz','shift_hz',
                  'shift_uncertainty_hz','k','k_uncertainty','delta_bic','background_ratio',
                  'carrier_fraction','reason')
        temporary = summary_path+'.tmp'
        with io.open(temporary, 'w', newline='', encoding='utf-8') as handle:
            writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
            for row in sorted(points, key=lambda value: value['point_id']):
                writer.writerow({name: scalar(row.get(name, '')) for name in fields})
            handle.flush(); os.fsync(handle.fileno())
        for attempt in range(6):
            try:
                os.replace(temporary, summary_path); break
            except PermissionError:
                if attempt == 5: raise
                time.sleep(.05*(attempt+1))

    if os.path.exists(summary_path):
        with io.open(summary_path, 'r', newline='', encoding='utf-8') as handle:
            for row in csv.DictReader(handle):
                for name in ('point_id','count','ci','cq'): row[name] = int(row[name])
                for name in ('phase_deg','actual_phase_deg','timestamp_epoch_s','q','q_uncertainty',
                             'q_ratio','f0_hz','f0_uncertainty_hz','linewidth_hz','linewidth_uncertainty_hz',
                             'shift_hz','shift_uncertainty_hz','k','k_uncertainty','delta_bic','background_ratio','carrier_fraction'):
                    row[name] = float(row[name])
                row['accepted'] = row['accepted'].lower() == 'true'; row['repeat'] = row['repeat'].lower() == 'true'
                points.append(row); completed[row['point_id']]=True

    result = {'stage': stage, 'config': stored_config, 'campaign_directory': directory,
              'points': points, 'baselines': [], 'status': 'running',
              'estimated_minutes': estimated_seconds/60., 'out2_used': False}
    baseline_identity_checked=False
    try:
        full_shutdown()
        for count in sorted(dict.fromkeys(row[0] for row in schedule)):
            relevant = [(index, row) for index, row in enumerate(schedule) if row[0] == count]
            pending = [(index, row) for index, row in relevant if index not in completed]
            if not pending: continue
            before = baseline_call('%s count %d before' % (stage, count)); before_fit = accepted_fit(before, 'before')
            before_time=time.time()
            signature={'f0_hz':float(before_fit['f0_hz']),'q':float(before_fit['q']),
                       'linewidth_hz':float(before_fit['linewidth_hz'])}
            if manifest.get('initial_baseline') is None:
                manifest['initial_baseline']=signature; atomic_json(manifest_path,manifest)
            elif resume and not baseline_identity_checked:
                old=manifest['initial_baseline']
                frequency_change=abs(signature['f0_hz']-float(old['f0_hz']))
                q_fraction=abs(signature['q']/max(float(old['q']),1e-30)-1.)
                if frequency_change > max(signature['linewidth_hz'],float(old['linewidth_hz'])) or q_fraction > .30:
                    raise RuntimeError('Resume refused after a fresh feedback-off measurement: the resonance changed by %.3f linewidths and %.1f%% in Q. Start a new campaign so incompatible hardware or resonator states are not mixed.' %
                                       (frequency_change/max(signature['linewidth_hz'],float(old['linewidth_hz'])),100*q_fraction))
                baseline_identity_checked=True
            result['baselines'].append({'position':'before','count':count,'fit':compact_fit(before_fit),'timestamp_epoch_s':before_time})
            rung_points = []
            for point_id, (_, phase, is_repeat) in pending:
                # Use nearest accepted coarse point only to centre/resolve; never as map interpolation.
                prediction = before_fit
                source_points = coarse_map.get('points', []) if isinstance(coarse_map, dict) else points
                candidates = [p for p in source_points if p.get('accepted') and p.get('q')]
                if candidates:
                    near = min(candidates, key=lambda p: abs(p['count']-count)/max(1., count)+
                               abs((p['phase_deg']-phase+180.)%360.-180.)/180.)
                    prediction = {'f0_hz': near['f0_hz'], 'q': near['q']}
                measurement = point_call(count, phase, before, prediction, averages,
                                         '%s point %04d' % (stage, point_id))
                try:
                    on = accepted_fit(measurement, 'on')
                except RuntimeError as first_error:
                    print('Fine window did not produce an accepted fit at count %d phase %.1f deg. Running the one permitted broad bounded locator before retrying the fine measurement.' % (count,phase))
                    locator=point_call(count,phase,before,before_fit,max(4,cfg['coarse_averages']),
                                       '%s point %04d broad retry' % (stage,point_id),force_broad=True)
                    located=accepted_fit(locator,'on')
                    measurement=point_call(count,phase,before,located,averages,
                                           '%s point %04d fine retry' % (stage,point_id))
                    try: on=accepted_fit(measurement,'on')
                    except RuntimeError:
                        raise RuntimeError('Resonance location failed after one broad retry. Initial failure was: %s' % str(first_error))
                ci, cq, actual_phase = vector(count, phase)
                spectrum = measurement['spectra']['on']
                psd = np.asarray(spectrum['psd_v2_per_hz'], float)
                carrier_fraction = float(np.max(psd)/np.sum(psd))
                base_spectrum = before['spectra']['before']
                base_frequency = np.asarray(base_spectrum['frequency_hz'], float)
                base_psd = np.asarray(base_spectrum['psd_v2_per_hz'], float)
                baseline_here = np.interp(np.asarray(spectrum['frequency_hz'], float), base_frequency, base_psd)
                ratio_bins = psd/np.maximum(baseline_here, np.finfo(float).tiny)
                # Median is deliberately insensitive to the central resonance;
                # a broad increase across the acquisition window is not.
                background_ratio = float(np.median(ratio_bins))
                width_ratio = on['linewidth_hz']/before_fit['linewidth_hz']
                k = 1.-width_ratio
                k_unc = float(width_ratio*np.hypot(on['linewidth_uncertainty_hz']/on['linewidth_hz'],
                                                   before_fit['linewidth_uncertainty_hz']/before_fit['linewidth_hz']))
                shift = on['f0_hz']-before_fit['f0_hz']
                shift_unc = float(np.hypot(on['f0_uncertainty_hz'], before_fit['f0_uncertainty_hz']))
                reasons = []
                if carrier_fraction > float(cfg['maximum_carrier_fraction']): reasons.append('narrow carrier fraction exceeded')
                if background_ratio > float(cfg['maximum_background_ratio']): reasons.append('broadband background increased')
                if k >= cfg['maximum_k'] or k+2*k_unc >= cfg['maximum_k']: reasons.append('K stop/uncertainty margin reached')
                if is_repeat:
                    originals=[r for r in points if r.get('accepted') and not r.get('repeat') and
                               r['count']==count and r['phase_deg']==phase]
                    if originals:
                        original=originals[-1]
                        q_limit=3*np.hypot(on['q_uncertainty'],original['q_uncertainty'])
                        f_limit=3*np.hypot(on['f0_uncertainty_hz'],original['f0_uncertainty_hz'])
                        if abs(on['q']-original['q'])>q_limit or abs(on['f0_hz']-original['f0_hz'])>f_limit:
                            reasons.append('repeat disagreed beyond combined 3-sigma fit uncertainty')
                row = {'point_id':point_id,'stage':stage,'count':count,'phase_deg':phase,
                       'actual_phase_deg':actual_phase,'ci':ci,'cq':cq,'repeat':is_repeat,
                       'timestamp_epoch_s':time.time(),'accepted':not reasons,'q':on['q'],
                       'q_uncertainty':on['q_uncertainty'],'q_ratio':on['q']/before_fit['q'],
                       'f0_hz':on['f0_hz'],'f0_uncertainty_hz':on['f0_uncertainty_hz'],
                       'linewidth_hz':on['linewidth_hz'],'linewidth_uncertainty_hz':on['linewidth_uncertainty_hz'],
                       'shift_hz':shift,'shift_uncertainty_hz':shift_unc,'k':k,'k_uncertainty':k_unc,
                       'delta_bic':float(on.get('delta_bic',np.nan)),
                       'background_ratio':background_ratio,'carrier_fraction':carrier_fraction,
                       'reason':'; '.join(reasons)}
                points.append(row); rung_points.append(row); completed[point_id] = True
                manifest['completed_ids'] = sorted(completed); manifest['status'] = 'running'; save_summary(); atomic_json(manifest_path, manifest)
                print('saved %04d: count %d phase %.1f deg, Q %.1f, shift %+.1f Hz, K %.4f [%s]' %
                      (point_id, count, phase, on['q'], shift, k, 'accepted' if row['accepted'] else row['reason']))
                if reasons:
                    manifest['status']='stopped'; manifest['stop_reason']=row['reason']; atomic_json(manifest_path, manifest)
                    raise RuntimeError('MAP STOPPED SAFELY at count %d phase %.1f deg: %s. Partial data were saved; resume is never automatic.' %
                                       (count, phase, row['reason']))
                del measurement,spectrum,psd,on,baseline_here,ratio_bins
                gc.collect()
            after = baseline_call('%s count %d after' % (stage, count)); after_fit = accepted_fit(after, 'before')
            after_time=time.time()
            result['baselines'].append({'position':'after','count':count,'fit':compact_fit(after_fit),'timestamp_epoch_s':after_time})
            # Replace the provisional before-reference comparison with the
            # time-interpolated off baseline. The summary is authoritative;
            # spectra remain unchanged in their per-point NPZ files.
            for row in rung_points:
                weight=np.clip((row['timestamp_epoch_s']-before_time)/max(after_time-before_time,1e-9),0,1)
                base={}
                for name in ('q','f0_hz','linewidth_hz'):
                    base[name]=(1-weight)*before_fit[name]+weight*after_fit[name]
                base_q_unc=np.hypot((1-weight)*before_fit['q_uncertainty'],weight*after_fit['q_uncertainty'])
                base_f_unc=np.hypot((1-weight)*before_fit['f0_uncertainty_hz'],weight*after_fit['f0_uncertainty_hz'])
                base_w_unc=np.hypot((1-weight)*before_fit['linewidth_uncertainty_hz'],weight*after_fit['linewidth_uncertainty_hz'])
                row['q_ratio']=row['q']/base['q']; row['shift_hz']=row['f0_hz']-base['f0_hz']; row['linewidth_hz']=float(row['linewidth_hz'])
                ratio=row['linewidth_hz']/base['linewidth_hz']; row['k']=1-ratio
                row['shift_uncertainty_hz']=float(np.hypot(row['f0_uncertainty_hz'],base_f_unc))
                row['k_uncertainty']=float(ratio*np.hypot(row['linewidth_uncertainty_hz']/row['linewidth_hz'],base_w_unc/base['linewidth_hz']))
                row['baseline_q_uncertainty']=base_q_unc; row['baseline_interpolation_weight']=float(weight)
                if row['k']>=cfg['maximum_k'] or row['k']+2*row['k_uncertainty']>=cfg['maximum_k']:
                    row['accepted']=False; row['reason']=(row['reason']+'; ' if row['reason'] else '')+'time-interpolated K stop reached'
            save_summary()
            if any('time-interpolated K stop reached' in row['reason'] for row in rung_points):
                manifest['status']='stopped';manifest['stop_reason']='time-interpolated K stop reached';atomic_json(manifest_path,manifest)
                raise RuntimeError('MAP STOPPED SAFELY after count %d: time-interpolated K reached its uncertainty-aware limit. Partial data were saved.' % count)
            shift_recovery = abs(after_fit['f0_hz']-before_fit['f0_hz'])
            width_recovery = abs(after_fit['linewidth_hz']-before_fit['linewidth_hz'])
            shift_limit = max(3*np.hypot(after_fit['f0_uncertainty_hz'],before_fit['f0_uncertainty_hz']), before_fit['linewidth_hz'])
            width_limit = max(3*np.hypot(after_fit['linewidth_uncertainty_hz'],before_fit['linewidth_uncertainty_hz']), .3*before_fit['linewidth_hz'])
            if shift_recovery > shift_limit or width_recovery > width_limit:
                for row in rung_points:
                    row['accepted']=False; row['reason']=(row['reason']+'; ' if row['reason'] else '')+'feedback-off recovery failed'
                save_summary()
                manifest['status']='stopped'; manifest['stop_reason']='feedback-off baseline failed recovery'; atomic_json(manifest_path,manifest)
                raise RuntimeError('MAP STOPPED SAFELY: feedback-off baseline failed recovery after count %d. Partial data were saved.' % count)
            del before,after,before_fit,after_fit,rung_points
            gc.collect()
        result['status']='complete'; manifest['status']='complete'; manifest['stop_reason']=None
        result.update(_feedback_map_analyse(result));
        inconsistent=[axis for axis in result['phase_axes'] if not axis['first_harmonic_consistent']]
        if inconsistent:
            manifest['status']='stopped';manifest['stop_reason']='phase response failed first-harmonic consistency'
            atomic_json(manifest_path,manifest);save_summary()
            raise RuntimeError('MAP STOPPED: phase response is not repeatably sinusoidal at count(s) %s. Partial data are saved.' %
                               ', '.join(str(v['count']) for v in inconsistent))
        atomic_json(manifest_path,manifest); save_summary()
        return result
    except BaseException as exc:
        result['status']='stopped'
        manifest['status']='stopped'
        if not manifest.get('stop_reason'):
            manifest['stop_reason']='%s: %s' % (type(exc).__name__,str(exc))
        try: atomic_json(manifest_path,manifest)
        except Exception: pass
        raise
    finally:
        full_shutdown()


def _feedback_map_load(directory):
    """Internal compact loader used by plotting, selection and explicit resume."""
    import os, io, csv, json
    manifest_path = os.path.join(os.path.abspath(str(directory)), 'manifest.json')
    with io.open(manifest_path, 'r', encoding='utf-8') as handle: manifest=json.load(handle)
    points=[]
    with io.open(os.path.join(os.path.dirname(manifest_path),'summary.csv'),'r',newline='',encoding='utf-8') as handle:
        for row in csv.DictReader(handle):
            for n in ('point_id','count','ci','cq'): row[n]=int(row[n])
            for n in ('phase_deg','actual_phase_deg','timestamp_epoch_s','q','q_uncertainty','q_ratio','f0_hz',
                      'f0_uncertainty_hz','linewidth_hz','linewidth_uncertainty_hz','shift_hz','shift_uncertainty_hz',
                      'k','k_uncertainty','delta_bic','background_ratio','carrier_fraction'): row[n]=float(row[n])
            row['accepted']=row['accepted'].lower()=='true'; row['repeat']=row['repeat'].lower()=='true'; points.append(row)
    result={'stage':manifest['stage'],'config':manifest['config'],'campaign_directory':os.path.dirname(manifest_path),
            'points':points,'status':manifest['status'],'out2_used':False}
    result.update(_feedback_map_analyse(result)); return result


def _feedback_map_analyse(mapping):
    """Fit phase axes and quantify repeat/leave-one-out consistency without extrapolation."""
    import numpy as np
    rows=[r for r in mapping.get('points',[]) if r.get('accepted') and not r.get('repeat')]
    axes=[]
    for count in sorted(dict.fromkeys(r['count'] for r in rows)):
        group=[r for r in rows if r['count']==count]
        if len(group)<6: continue
        phase=np.deg2rad([r['actual_phase_deg'] for r in group]); design=np.column_stack((np.ones(len(group)),np.cos(phase),np.sin(phase)))
        wk=1/np.maximum([r['k_uncertainty'] for r in group],1e-9); ws=1/np.maximum([r['shift_uncertainty_hz'] for r in group],1e-9)
        ck=np.linalg.lstsq(design*wk[:,None],np.array([r['k'] for r in group])*wk,rcond=-1)[0]
        cs=np.linalg.lstsq(design*ws[:,None],np.array([r['shift_hz'] for r in group])*ws,rcond=-1)[0]
        kr=np.sqrt(np.mean((design.dot(ck)-np.array([r['k'] for r in group]))**2))
        sr=np.sqrt(np.mean((design.dot(cs)-np.array([r['shift_hz'] for r in group]))**2))
        ktolerance=max(4*np.median([r['k_uncertainty'] for r in group]),.25*np.ptp([r['k'] for r in group]))
        stolerance=max(4*np.median([r['shift_uncertainty_hz'] for r in group]),.25*np.ptp([r['shift_hz'] for r in group]))
        regenerative=float(np.rad2deg(np.arctan2(ck[2],ck[1]))%360.)
        positive=float(np.rad2deg(np.arctan2(cs[2],cs[1]))%360.)
        axes.append({'count':count,'regenerative_deg':regenerative,'degenerative_deg':(regenerative+180)%360,
                     'positive_shift_deg':positive,'negative_shift_deg':(positive+180)%360,
                     'axis_nonorthogonality_deg':abs(abs((positive-regenerative+180)%360-180)-90),
                     'k_first_harmonic_rms':float(kr),'shift_first_harmonic_rms_hz':float(sr),
                     'first_harmonic_consistent':bool(kr<=ktolerance and sr<=stolerance)})
    repeats=[]
    for row in [r for r in mapping.get('points',[]) if r.get('accepted') and r.get('repeat')]:
        candidates=[r for r in rows if r['count']==row['count'] and r['phase_deg']==row['phase_deg']]
        if candidates: repeats.append({'count':row['count'],'phase_deg':row['phase_deg'],
            'q_fractional_difference':abs(row['q']/candidates[0]['q']-1),
            'shift_difference_hz':abs(row['shift_hz']-candidates[0]['shift_hz'])})
    # Leave-one-out local interpolation is an honest check: boundary points for
    # which removal requires extrapolation are reported as untestable.
    validation=[]
    if len(rows)>=10:
        from scipy.interpolate import LinearNDInterpolator
        grouped={}
        for row in rows: grouped.setdefault((row['ci'],row['cq']),[]).append(row)
        groups=list(grouped.values())
        xy=np.array([[g[0]['ci'],g[0]['cq']] for g in groups],float)
        qvalues=np.array([np.mean([r['q_ratio'] for r in g]) for g in groups])
        svalues=np.array([np.mean([r['shift_hz'] for r in g]) for g in groups])
        qrange=max(float(np.ptp(qvalues)),.02); srange=max(float(np.ptp(svalues)),1.)
        for index,group in enumerate(groups):
            row=group[0]; keep=np.arange(len(groups))!=index
            try:
                qp=float(np.asarray(LinearNDInterpolator(xy[keep],qvalues[keep])(xy[index])).reshape(-1)[0])
                sp=float(np.asarray(LinearNDInterpolator(xy[keep],svalues[keep])(xy[index])).reshape(-1)[0])
            except Exception:
                qp=sp=np.nan
            qu=np.mean([r['q_uncertainty']/max(r['q']/r['q_ratio'],1e-30) for r in group])
            su=np.mean([r['shift_uncertainty_hz'] for r in group])
            testable=bool(np.isfinite(qp+sp))
            passed=bool(testable and abs(qp-qvalues[index])<=max(3*qu,.15*qrange) and
                        abs(sp-svalues[index])<=max(3*su,.15*srange))
            validation.append({'point_id':row['point_id'],'testable':bool(np.isfinite(qp+sp)),
                'accepted':passed,
                'q_ratio_error':None if not testable else float(qp-qvalues[index]),
                'shift_error_hz':None if not testable else float(sp-svalues[index])})
    tested=[v for v in validation if v['testable']]
    return {'phase_axes':axes,'repeatability':repeats,'interpolation_validation':validation,
            'interpolation_validation_accepted':bool(tested and all(v['accepted'] for v in tested)),
            'electrode_voltage_directly_measured':False,'interpolation_extrapolation_allowed':False}


def plot_feedback_map(mapping, output_prefix=None):
    """Render the requested heatmaps/phase cuts; rejected and extrapolated areas stay black."""
    import os, numpy as np, matplotlib.pyplot as plt
    import matplotlib.gridspec as gridspec
    from scipy.interpolate import LinearNDInterpolator
    if isinstance(mapping,str): mapping=_feedback_map_load(mapping)
    rows=[r for r in mapping.get('points',[]) if r.get('accepted') and not r.get('repeat')]
    if len(rows)<6: raise ValueError('At least six accepted non-repeat map points are required.')
    grouped={}
    for row in rows: grouped.setdefault((row['ci'],row['cq']),[]).append(row)
    groups=list(grouped.values())
    xy=np.array([[group[0]['ci'],group[0]['cq']] for group in groups],float)
    phase=np.linspace(0,360,181); gains=np.linspace(0,max(r['count'] for r in rows),121)
    pp,gg=np.meshgrid(phase,gains)
    commands=[({'ci_signed':0,'cq_signed':0} if int(round(g))==0 else
              quantized_feedback_vector(int(round(g)),float(p),
              float(mapping['config'].get('phase_reference_hz',CENTRE_HZ))))
              for g,p in zip(gg.ravel(),pp.ravel())]
    query=np.array([[v['ci_signed'],v['cq_signed']] for v in commands],float)
    def grid(name): return np.asarray(LinearNDInterpolator(xy,np.array([np.mean([r[name] for r in group]) for group in groups]))(query)).reshape(gg.shape)
    qgrid,kgrid,sgrid=grid('q_ratio'),grid('k'),grid('shift_hz')
    # Deliberately cut holes around rejected commands. A local interpolator must
    # never bridge across a point at which the hardware or fit guard fired.
    rejected=[r for r in mapping.get('points',[]) if not r.get('accepted')]
    if rejected:
        for row in rejected:
            distance=np.sqrt((query[:,0]-row['ci'])**2+(query[:,1]-row['cq'])**2)
            unsafe=(distance<=max(2.,.02*max(gains))).reshape(gg.shape)
            qgrid[unsafe]=np.nan;kgrid[unsafe]=np.nan;sgrid[unsafe]=np.nan
    try: cmap=CMAP_SEQ
    except NameError:
        try: cmap=plt.get_cmap('viridis')
        except ValueError: cmap=plt.get_cmap('jet')
    cmap.set_bad('black')
    fig=plt.figure(figsize=(12,8)); outer=gridspec.GridSpec(2,2,height_ratios=[2.2,1.0],hspace=.12,wspace=.25)
    axes=[fig.add_subplot(outer[0,0]),fig.add_subplot(outer[0,1]),fig.add_subplot(outer[1,0]),fig.add_subplot(outer[1,1])]
    images=[axes[0].imshow(np.ma.masked_invalid(qgrid),cmap=cmap,origin='lower',aspect='auto',extent=(0,360,0,max(gains))),
            axes[1].imshow(np.ma.masked_invalid(sgrid),cmap=cmap,origin='lower',aspect='auto',extent=(0,360,0,max(gains)))]
    for ax,image,label in ((axes[0],images[0],'Q / Q0'),(axes[1],images[1],'Shift (Hz)')):
        box=ax.get_position(); cax=fig.add_axes([box.x0,box.y1+.012,box.width,.018])
        bar=fig.colorbar(image,cax=cax,orientation='horizontal');bar.set_label(label);cax.xaxis.set_ticks_position('top');cax.xaxis.set_label_position('top')
        ax.axvline(225,color='#ff7f0e',linestyle='--',linewidth=1);ax.set_ylabel('Coefficient count')
    for level,color in ((.5,'white'),(.7,'#ffbb33'),(.85,'#d62728')):
        if np.nanmin(kgrid)<=level<=np.nanmax(kgrid): axes[0].contour(phase,gains,kgrid,levels=[level],colors=[color],linestyles='--',linewidths=1)
    if np.nanmin(sgrid)<=0<=np.nanmax(sgrid): axes[1].contour(phase,gains,sgrid,levels=[0],colors=['white'],linestyles='--',linewidths=1)
    selected=np.unique(np.rint(np.percentile([r['count'] for r in rows],[20,55,100])).astype(int))
    colors=('#4c9be8','#ef6c55','#f5b642')
    for count,color in zip(selected,colors):
        near=[r for r in rows if r['count']==min(dict.fromkeys(v['count'] for v in rows),key=lambda v:abs(v-count))]
        near=sorted(near,key=lambda r:r['actual_phase_deg'])
        x=np.array([r['actual_phase_deg'] for r in near]); q=np.array([r['q_ratio'] for r in near]); shift=np.array([r['shift_hz'] for r in near])
        qu=np.array([r['q_uncertainty']/max(r['q']/r['q_ratio'],1e-30) for r in near]); su=np.array([r['shift_uncertainty_hz'] for r in near])
        axes[2].plot(x,q,'-o',color=color,label='count %d'%near[0]['count']);axes[2].fill_between(x,q-qu,q+qu,color=color,alpha=.15)
        axes[3].plot(x,shift,'-o',color=color,label='count %d'%near[0]['count']);axes[3].fill_between(x,shift-su,shift+su,color=color,alpha=.15)
    for ax in axes[2:]: ax.set_xlabel('Phase (degrees)');ax.set_xlim(0,360);ax.legend(fontsize=8);ax.grid(True,alpha=.25)
    axes[2].set_ylabel('Q / Q0');axes[3].set_ylabel('Shift (Hz)');fig.suptitle('Passive feedback gain-phase map')
    if output_prefix is None: output_prefix=os.path.join(mapping['campaign_directory'],'feedback_map')
    fig.savefig(output_prefix+'.png',dpi=180,bbox_inches='tight');fig.savefig(output_prefix+'.pdf',bbox_inches='tight')
    axis_figure=None;axis_png=None;axis_pdf=None
    phase_axes=mapping.get('phase_axes',[])
    if phase_axes:
        axis_figure,axis_plot=plt.subplots(2,1,figsize=(8,6),sharex=True)
        counts=np.array([r['count'] for r in phase_axes],float)
        for field,label,color in (('regenerative_deg','regenerative','#f5b642'),
                                  ('degenerative_deg','degenerative','#4c9be8'),
                                  ('positive_shift_deg','positive shift','#ef6c55'),
                                  ('negative_shift_deg','negative shift','#54a96b')):
            axis_plot[0].plot(counts,[r[field] for r in phase_axes],'-o',label=label,color=color)
        axis_plot[0].axhline(225,color='#ff7f0e',linestyle='--',label='225 degree seed')
        axis_plot[0].set_ylabel('Empirical phase axis (degrees)');axis_plot[0].set_ylim(0,360)
        axis_plot[0].legend(fontsize=8,ncol=2);axis_plot[0].grid(True,alpha=.25)
        axis_plot[1].plot(counts,[r['axis_nonorthogonality_deg'] for r in phase_axes],'-o',color='#7b5ea7')
        axis_plot[1].axhline(0,color='black',linewidth=.8);axis_plot[1].set_xlabel('Coefficient count')
        axis_plot[1].set_ylabel('Axis non-orthogonality (degrees)');axis_plot[1].grid(True,alpha=.25)
        axis_figure.suptitle('Measured feedback axes versus gain')
        axis_png=output_prefix+'_axes.png';axis_pdf=output_prefix+'_axes.pdf'
        axis_figure.savefig(axis_png,dpi=180,bbox_inches='tight');axis_figure.savefig(axis_pdf,bbox_inches='tight')
    plt.show()
    return {'figure':fig,'png':output_prefix+'.png','pdf':output_prefix+'.pdf',
            'axis_figure':axis_figure,'axis_png':axis_png,'axis_pdf':axis_pdf}


def select_feedback_operating_point(mapping, target_q=None, q_ratio=None,
                                    target_frequency_hz=None, shift_hz=None,
                                    maximum_candidates=5):
    """Return measured-envelope candidates; never apply feedback or extrapolate."""
    import math, numpy as np
    from scipy.interpolate import LinearNDInterpolator
    if isinstance(mapping,str): mapping=_feedback_map_load(mapping)
    if mapping.get('interpolation_validation') and not mapping.get('interpolation_validation_accepted'):
        raise ValueError('Operating-point selection is blocked because withheld measured points were not reproduced within the combined uncertainty. Inspect the map or acquire more local points.')
    if sum(v is not None for v in (target_q,q_ratio))>1 or sum(v is not None for v in (target_frequency_hz,shift_hz))>1:
        raise ValueError('Choose at most one Q target and at most one frequency target.')
    if all(v is None for v in (target_q,q_ratio,target_frequency_hz,shift_hz)):
        raise ValueError('Provide a Q and/or frequency target; this function never chooses the largest gain automatically.')
    rows=[r for r in mapping.get('points',[]) if r.get('accepted') and not r.get('repeat')]
    if len(rows)<6: raise ValueError('Too few accepted points for bounded interpolation.')
    q0=np.median([r['q']/r['q_ratio'] for r in rows]); f0=np.median([r['f0_hz']-r['shift_hz'] for r in rows])
    tq=float(target_q)/q0 if target_q is not None else (float(q_ratio) if q_ratio is not None else 1.)
    ts=float(target_frequency_hz)-f0 if target_frequency_hz is not None else (float(shift_hz) if shift_hz is not None else 0.)
    if (target_q is not None or q_ratio is not None) and not min(r['q_ratio'] for r in rows)<=tq<=max(r['q_ratio'] for r in rows):
        raise ValueError('Requested Q lies outside the measured Q/Q0 range; extrapolation is prohibited.')
    if (target_frequency_hz is not None or shift_hz is not None) and not min(r['shift_hz'] for r in rows)<=ts<=max(r['shift_hz'] for r in rows):
        raise ValueError('Requested frequency shift lies outside the measured shift range; extrapolation is prohibited.')
    grouped={}
    for row in rows: grouped.setdefault((row['ci'],row['cq']),[]).append(row)
    groups=list(grouped.values())
    xy=np.array([[g[0]['ci'],g[0]['cq']] for g in groups],float)
    qv=np.array([np.mean([r['q_ratio'] for r in g]) for g in groups]); sv=np.array([np.mean([r['shift_hz'] for r in g]) for g in groups])
    quv=np.array([np.mean([r['q_uncertainty']/max(r['q']/r['q_ratio'],1e-30) for r in g]) for g in groups])
    suv=np.array([np.mean([r['shift_uncertainty_hz'] for r in g]) for g in groups])
    kv=np.array([np.mean([r['k'] for r in g]) for g in groups]); kuv=np.array([np.mean([r['k_uncertainty'] for r in g]) for g in groups])
    iq,isf=LinearNDInterpolator(xy,qv),LinearNDInterpolator(xy,sv)
    iqu,isu=LinearNDInterpolator(xy,quv),LinearNDInterpolator(xy,suv)
    ik,iku=LinearNDInterpolator(xy,kv),LinearNDInterpolator(xy,kuv)
    limit=max(r['count'] for r in rows); phase=np.linspace(0,360,361)
    count_step=max(1,int(math.ceil(limit/256.)))
    gain=range(0,int(limit)+1,count_step)
    # Evaluate in strips to avoid a large temporary mesh on the Red Pitaya.
    candidates=[]; qscale=max(.02,np.std(qv)); sscale=max(1.,np.std(sv))
    for count in gain:
        commands=[({'ci_signed':0,'cq_signed':0} if int(round(count))==0 else
                  quantized_feedback_vector(int(round(count)),float(p),
                  float(mapping['config'].get('phase_reference_hz',CENTRE_HZ)))) for p in phase]
        query=np.array([[v['ci_signed'],v['cq_signed']] for v in commands],float)
        qp,sp=np.asarray(iq(query)).reshape(-1),np.asarray(isf(query)).reshape(-1)
        qup,sup=np.asarray(iqu(query)).reshape(-1),np.asarray(isu(query)).reshape(-1)
        kp,kup=np.asarray(ik(query)).reshape(-1),np.asarray(iku(query)).reshape(-1)
        valid=np.isfinite(qp)&np.isfinite(sp)&np.isfinite(qup)&np.isfinite(sup)&np.isfinite(kp)&np.isfinite(kup)
        valid &= (kp+2*kup<float(mapping['config']['maximum_k']))
        local=[]
        for index in np.where(valid)[0]:
            distance=float(np.min(np.sqrt(np.sum((xy-query[index])**2,axis=1))))
            margin=max(float(mapping['config']['maximum_k'])-kp[index]-2*kup[index],1e-9)
            score=(((qp[index]-tq)/qscale)**2+((sp[index]-ts)/sscale)**2+
                   .05*(qup[index]/qscale)**2+.05*(sup[index]/sscale)**2+
                   .02*(count/limit)**2+.01*(distance/max(1.,limit))**2+
                   .01*(1.-margin/float(mapping['config']['maximum_k']))**2)
            local.append((score,count,phase[index],qp[index],sp[index],qup[index],sup[index],kp[index],kup[index],distance))
        candidates.extend(sorted(local)[:3])
    candidates.sort(); selected=[]
    # Refine the best coarse neighbourhoods to integer count and quarter-degree
    # resolution without allocating/evaluating a million-point array.
    refined=[]
    for _,coarse_count,coarse_phase,_,_,_,_,_,_,_ in candidates[:20]:
        for count in range(max(0,int(coarse_count)-count_step),min(int(limit),int(coarse_count)+count_step)+1):
            phases=np.arange(coarse_phase-1.,coarse_phase+1.001,.25)%360.
            commands=[({'ci_signed':0,'cq_signed':0} if count==0 else
                      quantized_feedback_vector(count,float(p),float(mapping['config'].get('phase_reference_hz',CENTRE_HZ)))) for p in phases]
            query=np.array([[v['ci_signed'],v['cq_signed']] for v in commands],float)
            qp,sp=np.asarray(iq(query)).reshape(-1),np.asarray(isf(query)).reshape(-1)
            qup,sup=np.asarray(iqu(query)).reshape(-1),np.asarray(isu(query)).reshape(-1)
            kp,kup=np.asarray(ik(query)).reshape(-1),np.asarray(iku(query)).reshape(-1)
            valid=np.isfinite(qp)&np.isfinite(sp)&np.isfinite(qup)&np.isfinite(sup)&np.isfinite(kp)&np.isfinite(kup)
            valid &= (kp+2*kup<float(mapping['config']['maximum_k']))
            for index in np.where(valid)[0]:
                distance=float(np.min(np.sqrt(np.sum((xy-query[index])**2,axis=1))))
                margin=max(float(mapping['config']['maximum_k'])-kp[index]-2*kup[index],1e-9)
                score=(((qp[index]-tq)/qscale)**2+((sp[index]-ts)/sscale)**2+
                       .05*(qup[index]/qscale)**2+.05*(sup[index]/sscale)**2+
                       .02*(count/limit)**2+.01*(distance/max(1.,limit))**2+
                       .01*(1.-margin/float(mapping['config']['maximum_k']))**2)
                refined.append((score,count,float(phases[index]),qp[index],sp[index],qup[index],sup[index],kp[index],kup[index],distance))
    candidates=sorted(candidates+refined)
    for score,count,phase_value,qp,sp,qup,sup,kp,kup,distance in candidates:
        if any(abs(count-r['coefficient_counts'])<2 and abs((phase_value-r['phase_deg']+180)%360-180)<2 for r in selected): continue
        selected.append({'coefficient_counts':int(round(count)),'gain':float(count/16384.),'phase_deg':float(phase_value),
                         'predicted_q':float(qp*q0),'predicted_q_ratio':float(qp),
                         'predicted_q_uncertainty':float(qup*q0),
                         'predicted_frequency_hz':float(f0+sp),'predicted_shift_hz':float(sp),
                         'predicted_shift_uncertainty_hz':float(sup),'predicted_k':float(kp),
                         'predicted_k_uncertainty':float(kup),
                         'k_stability_margin':float(mapping['config']['maximum_k']-kp-2*kup),
                         'distance_to_nearest_measurement_counts':distance,'interpolated_only':True,
                         'extrapolated':False,'automatic_application_allowed':False,
                         'validation_required':'Run one manual feedback measurement and verify shutdown/recovery.'})
        if len(selected)>=int(maximum_candidates): break
    if not selected: raise ValueError('Requested target has no solution inside the accepted measured interpolation envelope.')
    return selected
