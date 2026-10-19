"""Mock-hardware tests for the explicit continuously held feedback pair."""
import contextlib
import io
import json
from pathlib import Path
import unittest
import numpy as np

from tests.python.test_manual_feedback_measurement import mock_system

ROOT=Path(__file__).resolve().parents[2]
NOTEBOOK=ROOT/'notebooks/test_noise_passive_feedback.ipynb'
SOURCE=ROOT/'notebooks/continuous_feedback_hold.py'


def hold_namespace():
    ns,active,state=mock_system(seed=91)
    code=SOURCE.read_text(encoding='utf-8')
    exec(compile(code,str(SOURCE),'exec'),ns)
    return ns,active,state


class ContinuousFeedbackHoldTests(unittest.TestCase):
    def quiet(self,function,*args,**kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return function(*args,**kwargs)

    def test_enable_holds_exact_coefficients_then_disable_clears_all(self):
        ns,active,state=hold_namespace()
        held=self.quiet(ns['enable_held_feedback'],128,225.,40.9e6,512)
        self.assertTrue(held['enabled']);self.assertEqual(active['count'],128)
        self.assertEqual(state['ci'],held['ci_signed'] & 0xffff)
        self.assertEqual(state['cq'],held['cq_signed'] & 0xffff)
        self.assertFalse(held['automatic_timeout']);self.assertFalse(held['out2_enabled'])
        stopped=self.quiet(ns['disable_held_feedback'])
        self.assertFalse(stopped['enabled']);self.assertEqual(active['count'],0)
        self.assertEqual(state['ci'],0);self.assertEqual(state['cq'],0)

    def test_ceiling_bad_build_dc_and_readback_fail_closed(self):
        cases=('ceiling','build','dc','readback')
        for case in cases:
            ns,active,state=hold_namespace()
            if case=='build': ns['acq'].build_id.return_value=0
            if case=='dc': ns['sc'].acquire.return_value=(np.ones(4096)*1000,125e6)
            if case=='readback': ns['ps'].set.side_effect=lambda gain,phase:None
            with self.assertRaises((ValueError,RuntimeError)):
                self.quiet(ns['enable_held_feedback'],128,225.,40.9e6,
                           2048 if case=='ceiling' else 512)
            self.assertEqual(active['count'],0);self.assertEqual(state['ci'],0);self.assertEqual(state['cq'],0)
            self.assertFalse(ns['HELD_FEEDBACK_STATE']['enabled'])

    def test_notebook_copy_matches_and_map_execution_remains_commented(self):
        book=json.loads(NOTEBOOK.read_text(encoding='utf-8'))
        cell=next(c for c in book['cells'] if 'def enable_held_feedback(' in ''.join(c.get('source',[])))
        self.assertEqual(''.join(cell['source']).strip(),SOURCE.read_text(encoding='utf-8').strip())
        for number in (24,25):
            source=''.join(next(c for c in book['cells'] if c.get('metadata',{}).get('code_cell_number')==number)['source'])
            active=[line for line in source.splitlines() if line.strip() and not line.lstrip().startswith('#')]
            self.assertEqual(active,[])


if __name__=='__main__': unittest.main()
