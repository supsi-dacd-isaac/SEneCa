import unittest

import numpy as np

from scripts.report_vensim import annual_series


class NativeAnnualReportTests(unittest.TestCase):
    def test_suppliers_stay_separate_and_coordinate_order_is_used(self):
        meta = {"dims": ["Supplier", "Hour", "Month"],
                "coords": {"Supplier": ["Import", "PHS"], "Hour": ["H2", "H1"], "Month": ["M1"]}}
        a = np.tile([10., 20., 1., 2.], (40, 1))
        labels, values = annual_series(meta, a)
        self.assertEqual(labels, ["Import", "PHS"])
        np.testing.assert_array_equal(values[:, 0], np.full(40, 30.*365/12))
        np.testing.assert_array_equal(values[:, 1], np.full(40, 3.*365/12))

    def test_zero_series_and_non_hourly_output(self):
        meta = {"dims": ["Month", "Hour"], "coords": {"Month": ["M1"], "Hour": ["H1"]}}
        labels, values = annual_series(meta, np.zeros((40, 1)))
        self.assertEqual(labels, ["total"])
        self.assertEqual(values.shape, (40, 1))
        self.assertTrue((values == 0).all())
        self.assertIsNone(annual_series({"dims": [], "coords": {}}, np.ones((40, 1))))


if __name__ == "__main__":
    unittest.main()
