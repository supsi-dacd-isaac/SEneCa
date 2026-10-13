"""Regression checks against the actual v6 source and physical acceptance gate."""
import ast
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import xarray as xr

from sure_julia.common import MODEL_PY, ROOT
from sure_julia.pv_budget import FLOWS, corrected_source
from sure_julia.physical import OUTPUTS, check


def source_function(name, environment):
    function = next(n for n in ast.parse(MODEL_PY.read_text()).body
                    if isinstance(n, ast.FunctionDef) and n.name == name)
    function.decorator_list = []
    namespace = {"np": np, "xr": xr, **environment}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(MODEL_PY), "exec"), namespace)
    return namespace[name]


class StockLimitsTests(unittest.TestCase):
    def test_pv_budget_preserves_ratios_and_empty_sources(self):
        from pysd.py_backend.functions import if_then_else
        coords = {"District": ["A"], "HS": ["A", "B", "C", "D"],
                  "Performance": ["VeryLow"], "Type": ["SFH"],
                  "PVpanel": ["PVyes", "PVno"], "Battery": ["Byes", "Bno"]}
        stock = xr.DataArray(np.full((1, 4, 1, 1, 2, 2), 999.), dims=list(coords), coords=coords)
        stock.loc[dict(PVpanel="PVno", Battery="Bno")] = np.array([2., 0., 10., 10.]).reshape(1, 4, 1, 1)
        demolition, renovation = xr.zeros_like(stock), xr.zeros_like(stock)
        demolition.loc[dict(PVpanel="PVno", Battery="Bno")] = np.array([0., 0., 20., 1.]).reshape(1, 4, 1, 1)
        renovation.loc[dict(PVpanel="PVno", Battery="Bno")] = np.array([0., 0., 0., 1.]).reshape(1, 4, 1, 1)
        env = {"_subscript_dict": coords, "heating_solution": lambda: stock,
               "building_demolition_by_archetype": lambda: demolition,
               "buildings_hs_renovation_from": lambda: renovation,
               "time_step": lambda: .5, "if_then_else": if_then_else}
        available = source_function("available_pv_adoption", env)()
        np.testing.assert_array_equal(available.values.ravel(), [4., 0., 0., 18.])
        env["available_pv_adoption"] = lambda: available
        for demands in ([1., 2., 3., 4., 5., 6.], [0.]*6, [-5., 0., 0., 0., 0., 1.]):
            for name, value in zip(FLOWS, demands):
                env["requested_" + name.lower().replace(" ", "_")] = lambda value=value: xr.full_like(available, value)
            total = source_function("total_pv_request", env)()
            env["total_pv_request"] = lambda: total
            accepted_total = source_function("accepted_pv_adoption", env)()
            env["accepted_pv_adoption"] = lambda: accepted_total
            accepted = [source_function(name.lower().replace(" ", "_"), env)() for name in FLOWS]
            expected = np.minimum(available, sum(max(0., d) for d in demands))
            np.testing.assert_allclose(sum(accepted), expected, rtol=1e-15, atol=1e-15)
            np.testing.assert_array_equal(accepted_total, expected)
            self.assertTrue(all(bool((a >= 0).all()) for a in accepted))
            if sum(demands) > 0:
                for a, demand in zip(accepted, demands):
                    if demand > 0:
                        np.testing.assert_allclose(a, expected * demand / sum(max(0., d) for d in demands))

    def test_source_patch_preserves_sketch_and_all_original_request_clauses(self):
        original = (ROOT / "Vensim/SURE_pysd_v6.mdl").read_bytes().decode("latin-1")
        corrected, clauses = corrected_source(original)
        marker = "\\\\\\---///"
        self.assertEqual(original.partition(marker)[2], corrected.partition(marker)[2])
        self.assertEqual(sum(map(len, clauses.values())), 10)
        for name, bodies in clauses.items():
            for body in bodies:
                self.assertIn("Requested " + name + body, corrected)
        with self.assertRaises(ValueError):
            corrected_source(corrected)

    def test_zero_substitutions_do_not_empty_a_heating_category(self):
        from pysd.py_backend.functions import if_then_else, sum as pysd_sum
        coords = {"District": ["A"], "HS": ["HeatPump", "Oil"],
                  "Performance": ["VeryLow"], "Type": ["SFH"],
                  "PVpanel": ["PVyes", "PVno"], "Battery": ["Byes", "Bno"]}
        stock = xr.DataArray(np.full((1, 2, 1, 1, 2, 2), 5.), dims=list(coords), coords=coords)
        function = source_function("equivalent_lifetime", {
            "_subscript_dict": coords, "heating_solution": lambda: stock,
            "hs_substituted": lambda: xr.DataArray([0., 2.], dims=["HS"], coords={"HS": coords["HS"]}),
            "sum": pysd_sum, "if_then_else": if_then_else,
        })
        np.testing.assert_array_equal(function(), [1e6, 10.])

    def test_equipped_demolition_is_paired_and_cannot_empty_more_than_the_pool(self):
        from pysd.py_backend.functions import if_then_else, sum as pysd_sum
        coords = {"District": ["A"], "HS": ["HeatPump"],
                  "Performance": ["VeryLow"], "Type": ["SFH"],
                  "PVpanel": ["PVyes", "PVno"], "Battery": ["Byes", "Bno"]}
        demolition = xr.DataArray(np.zeros((1, 1, 1, 1, 2, 2)), dims=list(coords), coords=coords)
        demolition.loc[dict(PVpanel="PVyes")] = 50.
        names = [f"{owner}_buildings_with_{kind}" for owner in ["owned", "rented"] for kind in ["pv", "rcp", "rcpv"]]
        pools = {name: float(i+1) for i, name in enumerate(names)}
        total = sum(pools.values())
        environment = {"_subscript_dict": coords, "sum": pysd_sum, "if_then_else": if_then_else,
                       "building_demolition_by_archetype": lambda: demolition,
                       "equipped_buildings": lambda: total,
                       **{name: (lambda value=value: value) for name, value in pools.items()}}
        actual = [source_function(name+"_demolished", environment)().item() for name in names]
        np.testing.assert_array_equal(actual, list(pools.values()))
        self.assertEqual(sum(actual), total)
        environment["equipped_buildings"] = lambda: 0.
        for name in names:
            self.assertEqual(source_function(name+"_demolished", environment)().item(), 0.)

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

    def test_paired_pv_cannot_withdraw_from_an_empty_source(self):
        a = self.arrays()
        a["Heating Solution"][10] = 0.
        a["Consumers adopting PV no"][10] = 1e-6
        a["Consumers adopting PV yes with battery"][10] = 1e-6
        result = check(a)
        self.assertTrue(result["checks"]["pv_transfer"]["pass"])
        self.assertFalse(result["checks"]["pv_source_budget"]["pass"])

    def test_agreeing_engines_cannot_certify_physically_invalid_results(self):
        import json
        from sure_julia import validation
        from sure_julia.physical import PhysicalInvariantError
        a = self.arrays()
        a["Heating Solution"][10, 0, 0, 0, 0, 0, 0] = -1.
        report = check(a)
        def failed_run(parameters):
            raise PhysicalInvariantError(report, a)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "warnings.json").write_text("[]")
            python = SimpleNamespace(backend="python", run_arrays=failed_run,
                                     last_timing={}, warnings=[], variables={})
            julia = SimpleNamespace(backend="julia", run_arrays=failed_run,
                                    last_timing={}, directory=directory,
                                    export=[{"name": n, "dims": [], "coords": {}} for n in a])
            with patch.multiple(validation, create=True, PYTHON=python, JULIA=julia, TARGET=directory), \
                    patch.object(validation, "energy", return_value={"pass": True}):
                self.assertEqual(validation.check(("invalid", {})), ("invalid", False))
            saved = json.loads((directory / "invalid/report.json").read_text())
            self.assertTrue(saved["comparison"]["pass"])
            self.assertFalse(saved["pass"])
            self.assertFalse(saved["python_physical"]["pass"])
            self.assertFalse(saved["julia_physical"]["pass"])
            self.assertTrue((directory / "invalid/python.npz").exists())
            self.assertTrue((directory / "invalid/julia.npz").exists())


if __name__ == "__main__":
    unittest.main()
