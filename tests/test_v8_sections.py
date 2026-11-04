"""The release comparison rejects changed keys and separates numerical drift."""
import unittest
import pandas as pd

from scripts.audit_v8_sections import compare_tables


class SectionComparisonTests(unittest.TestCase):
    def test_coordinates_are_exact_but_order_is_irrelevant(self):
        a = pd.DataFrame({"policy": [0., 0.], "year": [2049, 2050], "value": [1., 2.]})
        self.assertEqual(compare_tables(a, a.iloc[::-1], ["policy", "year"], ["policy"], ["value"])["failures"], 0)
        b = a.copy()
        b.loc[1, "year"] = 2051
        with self.assertRaises(ValueError):
            compare_tables(a, b, ["policy", "year"], ["policy"], ["value"])

    def test_numerical_changes_are_counted_and_nonfinite_data_rejected(self):
        a = pd.DataFrame({"policy": [0., 0.], "year": [2049, 2050], "value": [0., 100.]})
        b = a.copy()
        b["value"] += [1e-9, .001]
        result = compare_tables(a, b, ["policy", "year"], ["policy"], ["value"])
        self.assertEqual(result["failures"], 1)
        b.loc[0, "value"] = float("nan")
        with self.assertRaises(ValueError):
            compare_tables(a, b, ["policy", "year"], ["policy"], ["value"])
