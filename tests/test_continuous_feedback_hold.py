"""Main notebook, cells 22-23: one feedback setting held for an external measurement."""
import ast
import contextlib
import io
import unittest
import numpy as np

from tests.notebook import code_cells, run_cells
from tests.test_manual_feedback_measurement import mock_system


def hold_namespace():
    ns,active,state=mock_system(seed=91)
    run_cells((22,),ns)
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

    def test_enable_call_is_commented_out(self):
        # Cell 23 energises OUT1, so running it unedited must do nothing.
        self.assertEqual(ast.parse(code_cells()[23]).body,[])

if __name__=='__main__': unittest.main()
