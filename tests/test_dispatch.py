"""Translate and execute the actual native equations, including edge cases."""
from pathlib import Path
import tempfile
import unittest
import warnings

import numpy as np
import pysd
import xarray as xr
import fix_allocate_sure

from model_checks.dispatch_validation import cases, write_fixture, physical, DISPATCH, CAPACITY, DEMAND


class DispatchTests(unittest.TestCase):
    def test_recorded_vectors_and_rectangular_edge_cases(self):
        warnings.filterwarnings('ignore', message='Replacing a variable by a constant value.')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'dispatch.mdl'
            expected = write_fixture(path)
            pysd.read_vensim(path)
            py = path.with_suffix('.py')
            py.write_text(py.read_text().replace(fix_allocate_sure.PRIORITY_IMPORT,
                                                 fix_allocate_sure.PRIORITY_WRAPPER))
            model = pysd.load(py)
            df = model.run(return_columns=[DISPATCH, CAPACITY, DEMAND], flatten_output=False)
            dispatched = np.stack([a.values for a in df[DISPATCH]])
            capacity = np.stack([a.values for a in df[CAPACITY]])
            demand = np.stack([a.values for a in df[DEMAND]])
            # PySD rounds embedded WITH LOOKUP coordinates to eight decimals.
            np.testing.assert_allclose(dispatched, np.broadcast_to(expected[:, None, None, :],
                                       dispatched.shape), rtol=0, atol=1e-7)
            self.assertTrue(physical(dispatched, capacity, demand, atol=1e-11)['pass'])
            self.assertEqual(len(df), len(cases()))
            # Replay the unrounded recorded vectors through the same translated
            # equations as well; this checks the solver without lookup rounding.
            coords = model.components.dispatchable_supply_by_supplier().coords
            for i, (name, q, c, d) in enumerate(cases()):
                model.set_components({
                    'Hourly available supply by Supplier': xr.DataArray(
                        np.broadcast_to(q, (2, 1, 9)), coords=coords),
                    'Marginal cost by supplier': xr.DataArray(c, coords={'Supplier': coords['Supplier']}),
                    'Hourly demand and PHS': xr.DataArray(np.full((2, 1), d),
                        coords={k: coords[k] for k in ('Month', 'Hour')}),
                })
                model.clean_caches()
                actual = model.components.electricity_dispatched().values
                with self.subTest(case=name):
                    np.testing.assert_allclose(actual[0, 0], expected[i], rtol=0, atol=1e-11)

    def test_checks_reject_nonfinite_and_broken_balance(self):
        with self.assertRaises(AssertionError):
            physical(np.array([[np.nan]]), np.ones((1, 1)), np.ones(1))
        self.assertFalse(physical(np.zeros((1, 1)), np.ones((1, 1)), np.ones(1))['pass'])


if __name__ == '__main__':
    unittest.main()
