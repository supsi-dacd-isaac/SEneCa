"""Regression checks against the actual v5 source and physical acceptance gate."""
import ast
import unittest

import numpy as np
import xarray as xr

from sure_julia.common import MODEL_PY
from sure_julia.physical import OUTPUTS, check


def source_function(name, environment):
    function = next(n for n in ast.parse(MODEL_PY.read_text()).body
                    if isinstance(n, ast.FunctionDef) and n.name == name)
    function.decorator_list = []
    namespace = {"np": np, "xr": xr, **environment}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(MODEL_PY), "exec"), namespace)
    return namespace[name]


class StockLimitsTests(unittest.TestCase):
    def test_heating_replacement_uses_only_remaining_stock(self):
        stock = xr.DataArray([10., 10., 10.], dims=["HS"])
        function = source_function("consumers_leaving_hs_for_old_age", {
            "heating_solution": lambda: stock,
            "equivalent_lifetime": lambda: xr.DataArray([1., 2., 4.], dims=["HS"]),
            "building_demolition_by_archetype": lambda: xr.DataArray([3., 20., 0.], dims=["HS"]),
            "buildings_hs_renovation_from": lambda: xr.DataArray([2., 0., 0.], dims=["HS"]),
            "consumers_adopting_pv_no": lambda: xr.DataArray([1., 0., 20.], dims=["HS"]),
        })
        np.testing.assert_array_equal(function(), [4., 0., 0.])

    def test_signed_demands_do_not_increase_heating_replacement_budget(self):
        function = source_function("consumers_leaving_hs_for_old_age", {
            "heating_solution": lambda: 10., "equivalent_lifetime": lambda: 1.,
            "building_demolition_by_archetype": lambda: -5.,
            "buildings_hs_renovation_from": lambda: -6.,
            "consumers_adopting_pv_no": lambda: 3.,
        })
        self.assertEqual(function(), 7.)

    def test_demolition_follows_all_eligible_pv_and_battery_cells(self):
        coords = {"District": ["A"], "HS": ["HeatPump", "Oil"],
                  "Performance": ["VeryLow", "Low"], "Type": ["SFH"],
                  "PVpanel": ["PVyes", "PVno"], "Battery": ["Byes", "Bno"]}
        stock = xr.DataArray(np.arange(1., 17.).reshape(1, 2, 2, 1, 2, 2), dims=list(coords), coords=coords)
        shares = stock / stock.sum(dim=["HS", "PVpanel", "Battery"])
        demand = xr.DataArray([[12.]], dims=["District", "Type"],
                              coords={d: coords[d] for d in ["District", "Type"]})
        function = source_function("building_demolition_by_archetype", {
            "_subscript_dict": {**coords, "PerformanceLow": ["VeryLow", "Low"]},
            "res_verylow_demolition": lambda: demand,
            "share_hs_by_archetype": lambda: shares,
        })
        result = function()
        expected = shares * demand
        expected.loc[dict(Performance="Low")] = 0.
        np.testing.assert_allclose(result, expected, rtol=0, atol=1e-15)
        self.assertAlmostEqual(float(result.sum()), 12.)
        self.assertGreater(float(result.sel(PVpanel="PVyes", Battery="Byes").sum()), 0.)


class PhysicalGateTests(unittest.TestCase):
    def arrays(self):
        a = {n: np.zeros((40, 1, 2, 1, 1, 2, 2)) for n in OUTPUTS}
        a["Heating Solution"][:] = 10.
        a["Annual archetypes"] = a["Heating Solution"].sum(axis=6)
        a["Total Res buildings"] = a["Heating Solution"].sum(axis=(2, 5, 6))
        return a

    def test_unchanged_population_and_fixed_input_offset_pass(self):
        a = self.arrays()
        a["Total Res buildings"] += .001
        self.assertTrue(check(a)["pass"])

    def test_missing_nonfinite_and_negative_states_fail(self):
        a = self.arrays()
        del a["Annual archetypes"]
        self.assertFalse(check(a)["pass"])
        for value in (np.nan, -1.):
            a = self.arrays()
            a["Heating Solution"][10, 0, 0, 0, 0, 0, 0] = value
            self.assertFalse(check(a)["pass"])

    def test_unpaired_transfer_and_drifting_population_fail(self):
        for source, gate in [("Consumers leaving HS for old age", "heating_transfer"),
                             ("Buildings HS Renovation From", "renovation_transfer"),
                             ("Consumers adopting PV no", "pv_transfer")]:
            a = self.arrays()
            a[source][10, 0, 0, 0, 0, 0, 0] = 1.
            self.assertFalse(check(a)["checks"][gate]["pass"])
        a = self.arrays()
        a["Total Res buildings"][10:] += 1.
        self.assertFalse(check(a)["checks"]["fine_coarse_changes"]["pass"])


if __name__ == "__main__":
    unittest.main()
