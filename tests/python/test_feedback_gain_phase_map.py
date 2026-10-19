"""Synthetic and persistence tests for the standalone gain/phase map."""
import contextlib, io, json, shutil, unittest
from pathlib import Path
from unittest.mock import Mock, patch
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parents[2]
NOTEBOOK=ROOT/'notebooks/test_noise_passive_feedback.ipynb'

@contextlib.contextmanager
def writable_directory(label):
    path=ROOT/'tests/map_test_generated'/label
    if path.exists():shutil.rmtree(str(path))
    path.mkdir(parents=True)
    try:yield str(path)
    finally:shutil.rmtree(str(path),ignore_errors=True)


def map_namespace():
    from tests.python.test_manual_feedback_measurement import namespace
    ns=namespace()
    book=json.loads(NOTEBOOK.read_text(encoding='utf-8'))
    code=next(''.join(c['source']) for c in book['cells'] if 'def run_feedback_map(' in ''.join(c['source']))
    exec(compile(code,str(NOTEBOOK),'exec'),ns)
    ns['read_acquisition_fir']=lambda:{'digest':'synthetic-fir'}
    ns['full_shutdown']=Mock(return_value=True)
    return ns


class SyntheticMeasurement(object):
    def __init__(self, stop_k=.80, interrupt_after=None, q0=150., count_scale=1024.):
        self.stop_k=stop_k;self.interrupt_after=interrupt_after;self.q0=q0
        self.count_scale=count_scale;self.active_calls=0;self.calls=[]
    def __call__(self, **kw):
        self.calls.append(dict(kw));f0=40.9e6;q0=self.q0;width0=f0/q0
        if kw['mode']=='baseline':
            f=np.linspace(40.4e6,41.4e6,1024);p=1e-12+8e-12/(1+4*((f-f0)/width0)**2)
            fit={'accepted':True,'reasons':[],'f0_hz':f0,'q':q0,'linewidth_hz':width0,
                 'f0_uncertainty_hz':30.,'q_uncertainty':.3,'linewidth_uncertainty_hz':300.,
                 'frequency_hz':f,'model':p}
            return {'status':'complete','fits':{'before':fit},'spectra':{'before':{'frequency_hz':f,'psd_v2_per_hz':p}},
                    'controls':{'phase_reference_hz':f0},'label':kw.get('label','baseline'),'filter_model_version':2}
        self.active_calls+=1
        if self.interrupt_after is not None and self.active_calls>self.interrupt_after:raise KeyboardInterrupt()
        count=float(kw['coefficient_counts']);phase=float(kw['phase_deg'])
        k=self.stop_k*(count/self.count_scale)*np.cos(np.deg2rad(phase-225.))
        shift=2e4*(count/self.count_scale)*np.sin(np.deg2rad(phase-225.))
        q=q0/(1-k);width=(f0+shift)/q;centre=kw['lo_hz'];span=kw['frequency_range_hz'][1]-kw['frequency_range_hz'][0]
        f=np.linspace(centre-span/2,centre+span/2,2048);p=1e-12+8e-12/(1+4*((f-f0-shift)/width)**2)
        fit={'accepted':True,'reasons':[],'f0_hz':f0+shift,'q':q,'linewidth_hz':width,
             'f0_uncertainty_hz':10.,'q_uncertainty':max(.2,.003*q),
             'linewidth_uncertainty_hz':max(10.,.003*width),'frequency_hz':f,'model':p}
        return {'status':'complete','fits':{'on':fit},'spectra':{'on':{'frequency_hz':f,'psd_v2_per_hz':p}},
                'controls':{},'comparison':{}}


class GainPhaseMapTests(unittest.TestCase):
    def quiet(self,fn,*a,**kw):
        with contextlib.redirect_stdout(io.StringIO()),patch.object(plt,'show'):return fn(*a,**kw)
    def config(self,root,name='synthetic',**extra):
        value={'campaign_name':name,'campaign_root':root,'maximum_coefficient_counts':1024,
               'maximum_k':.85,'profile':'fast','coarse_averages':6,'final_averages':16,
               'time_budget_minutes':55,'baseline_averages':4}
        value.update(extra);return value
    def test_coarse_recovers_225_axis_and_saves_every_point(self):
        ns=map_namespace();measure=SyntheticMeasurement()
        with writable_directory('coarse') as root:
            result=self.quiet(ns['run_feedback_map'],'coarse',self.config(root),measurement_function=measure)
            self.assertEqual(result['status'],'complete');self.assertFalse(result['out2_used'])
            axis=min(result['phase_axes'],key=lambda r:abs(r['count']-512))
            self.assertLess(abs((axis['regenerative_deg']-225+180)%360-180),3)
            directory=Path(result['campaign_directory'])
            self.assertTrue((directory/'manifest.json').exists());self.assertTrue((directory/'summary.csv').exists())
            self.assertFalse((directory/'points').exists())
            header=(directory/'summary.csv').read_text().splitlines()[0]
            self.assertNotIn('npz',header);self.assertNotIn('psd',header)
            active=[call for call in measure.calls if call['mode']=='feedback']
            self.assertTrue(all(call['minimum_edge_coverage_linewidths']==.35 for call in active))
            self.assertTrue(all(call['maximum_fit_uncertainty_linewidths']==.60 for call in active))
            self.assertTrue(all(call['frequency_range_hz'][1]-call['frequency_range_hz'][0]<=1.50e6 for call in active))
            loaded=ns['_feedback_map_load'](str(directory));self.assertEqual(len(loaded['points']),len(result['points']))
            self.assertIn('delta_bic',loaded['points'][0])
            self.assertGreaterEqual(ns['full_shutdown'].call_count,2)
    def test_k_limit_stops_saves_and_never_exceeds_count_ceiling(self):
        ns=map_namespace();measure=SyntheticMeasurement(stop_k=.90)
        with writable_directory('stop') as root:
            with self.assertRaisesRegex(RuntimeError,'MAP STOPPED'):
                self.quiet(ns['run_feedback_map'],'coarse',self.config(root),measurement_function=measure)
            manifest=json.loads((Path(root)/'synthetic_coarse/manifest.json').read_text())
            self.assertEqual(manifest['status'],'stopped');self.assertTrue(manifest['completed_ids'])
            self.assertTrue(ns['full_shutdown'].called)
            with self.assertRaisesRegex(RuntimeError,'K safety boundary'):
                ns['run_feedback_map']('coarse',self.config(root),resume=True,measurement_function=measure)
        with writable_directory('ceiling') as root:
            with self.assertRaisesRegex(ValueError,'1..1024'):
                ns['run_feedback_map']('coarse',self.config(root,maximum_coefficient_counts=1025),measurement_function=measure)
    def test_interruption_resume_skips_completed_points(self):
        ns=map_namespace();first=SyntheticMeasurement(interrupt_after=12)
        with writable_directory('resume') as root:
            cfg=self.config(root,'resume')
            with self.assertRaises(KeyboardInterrupt):self.quiet(ns['run_feedback_map'],'coarse',cfg,measurement_function=first)
            completed=len(json.loads((Path(root)/'resume_coarse/manifest.json').read_text())['completed_ids'])
            second=SyntheticMeasurement();result=self.quiet(ns['run_feedback_map'],'coarse',cfg,resume=True,measurement_function=second)
            self.assertEqual(result['status'],'complete');self.assertEqual(len(result['points']),completed+second.active_calls)
            self.assertLess(second.active_calls,len(result['points']))
            bad=dict(cfg);bad['maximum_k']=.8
            with self.assertRaisesRegex(ValueError,'config_digest'):
                ns['run_feedback_map']('coarse',bad,resume=True,measurement_function=second)
    def test_high_q_feedback_window_increases_fft_length(self):
        ns=map_namespace();measure=SyntheticMeasurement(stop_k=.75,q0=10000.,count_scale=8.)
        with writable_directory('high_q') as root:
            result=self.quiet(ns['run_feedback_map'],'coarse',self.config(root,'high_q',minimum_coefficient_counts=8,maximum_coefficient_counts=8),measurement_function=measure)
            self.assertEqual(result['status'],'complete')
            active=[call for call in measure.calls if call['mode']=='feedback']
            self.assertTrue(any(call['q_guess']>20000 and call['samples_per_record']>=16384 for call in active))
    def test_final_plot_and_bounded_target_selection(self):
        ns=map_namespace()
        with writable_directory('final') as root:
            coarse=self.quiet(ns['run_feedback_map'],'coarse',self.config(root,'map'),measurement_function=SyntheticMeasurement())
            final=self.quiet(ns['run_feedback_map'],'final',self.config(root,'map'),coarse_map=coarse,measurement_function=SyntheticMeasurement())
            self.assertEqual(final['status'],'complete');self.assertTrue(final['repeatability'])
            figure=self.quiet(ns['plot_feedback_map'],final,output_prefix=str(Path(root)/'figure'))
            self.assertTrue(Path(figure['png']).exists());self.assertTrue(Path(figure['pdf']).exists())
            self.assertTrue(Path(figure['axis_png']).exists());self.assertTrue(Path(figure['axis_pdf']).exists())
            self.assertGreaterEqual(len(figure['figure'].axes),6)
            candidates=ns['select_feedback_operating_point'](final,target_q=300.,shift_hz=0.)
            self.assertTrue(candidates);self.assertTrue(all(not c['extrapolated'] for c in candidates))
            self.assertTrue(all(c['coefficient_counts']<=1024 for c in candidates))
            self.assertTrue(all(c['k_stability_margin']>0 for c in candidates))
            self.assertTrue(all(c['predicted_q_uncertainty']>0 for c in candidates))
            with self.assertRaisesRegex(ValueError,'Provide a Q'):
                ns['select_feedback_operating_point'](final)
    def test_cell_numbers_and_standalone_copy_match(self):
        book=json.loads(NOTEBOOK.read_text(encoding='utf-8'));code=[c for c in book['cells'] if c['cell_type']=='code']
        self.assertEqual([c['metadata']['code_cell_number'] for c in code],list(range(1,29)))
        map_cell=next(''.join(c['source']) for c in book['cells'] if 'def run_feedback_map(' in ''.join(c['source']))
        self.assertEqual(map_cell.replace('\r\n','\n').strip(),
                         (ROOT/'notebooks/feedback_gain_phase_map.py').read_text().replace('\r\n','\n').strip())
        source='\n'.join(''.join(c['source']) for c in book['cells'])
        self.assertNotIn('import feedback_gain_phase_map',source)


if __name__=='__main__':unittest.main()
