"""Conservation is an additional gate, including when both engines agree."""
import unittest
from unittest.mock import patch

import numpy as np

from scripts.julia_repro.energy import check_snapshot


class EnergyTests(unittest.TestCase):
    def snapshot(self, request, allocated, available):
        coords = {"Month": ["M1"], "Hour": ["H1"], "Supplier": ["A", "B"]}
        names = ("Hourly available supply by Supplier", "Electricity dispatched", "Hourly demand and PHS")
        meta = {"years": [2011, 2012], "variables": {
            name: {"dims": list(coords) if i < 2 else list(coords)[:-1],
                   "coords": coords if i < 2 else {k: v for k, v in coords.items() if k != "Supplier"}}
            for i, name in enumerate(names)}}
        arrays = dict(zip(names, map(lambda x: np.asarray(x, dtype=float), (request, allocated, available))))
        return patch("scripts.julia_repro.energy.load_snapshot", return_value=(meta, arrays))

    def test_negative_requests_and_insufficient_supply(self):
        with self.snapshot([[-1, 3], [2, 3]], [[0, 2], [2, 3]], [[2], [10]]):
            result = check_snapshot("unused")
        self.assertTrue(result["pass"])
        self.assertEqual(result["cells"], 2)

    def test_equal_engine_outputs_do_not_excuse_energy_loss(self):
        with self.snapshot([[2, 3], [2, 3]], [[1, 1], [2, 3]], [[3], [10]]):
            result = check_snapshot("unused")
        self.assertFalse(result["pass"])
        self.assertEqual(result["first_failure"]["year"], 2011)

    def test_conserving_sum_does_not_excuse_negative_allocation(self):
        with self.snapshot([[2, 3], [2, 3]], [[-1, 3], [2, 3]], [[2], [10]]):
            result = check_snapshot("unused")
        self.assertFalse(result["pass"])
        self.assertEqual(result["bound_failures"], 1)

    def test_nonfinite_is_never_ignored(self):
        with self.snapshot([[2, 3], [2, 3]], [[float("nan"), 2], [2, 3]], [[2], [10]]):
            self.assertFalse(check_snapshot("unused")["pass"])


if __name__ == "__main__":
    unittest.main()
