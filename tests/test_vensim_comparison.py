import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pyarrow as pa

from scripts.julia_repro.common import YEARS, digest, dump
from scripts.vensim_comparison.core import comparison, hourly_frame, reconstruct_import, selections


def snapshot(path, values, *, years=YEARS, dims=(), coords=None, columns=("x",)):
    np.savez(path.with_suffix(".npz"), x=np.asarray(values, dtype=np.float64))
    dump(path.with_suffix(".json"), {"years": years, "sha256": digest(path.with_suffix(".npz")),
         "variables": {"x": {"key": "x", "dims": list(dims), "coords": coords or {}, "columns": list(columns)}}})


class NativeComparisonTests(unittest.TestCase):
    def test_full_grid_keeps_named_aliases_and_removes_duplicates(self):
        cfg = SimpleNamespace(INPUT_GRID={"a": [0., 1.], "b": [0., 1., 2.]}, BASE_SCENARIO={"a": 0., "b": 1.})
        cases = selections(cfg, "full")
        self.assertEqual(len(cases), 6)
        base = next(c for c in cases if "base" in c["labels"])
        self.assertEqual(base["inputs"], cfg.BASE_SCENARIO)
        self.assertTrue(any(label.startswith("grid_") for label in base["labels"]))

    def compare(self, a, b, **kwargs):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            snapshot(root / "reference", a, **kwargs)
            snapshot(root / "candidate", b, **kwargs)
            return comparison(root / "reference", root / "candidate")

    def test_explicit_float32_export_quantization_is_accounted_for(self):
        b = np.full((40, 1), 1000.123456)
        a = b.astype(np.float32).astype(np.float64)
        result = self.compare(a, b)
        self.assertTrue(result["pass"])
        self.assertEqual(result["rows"][0]["strict_failures"], 40)

    def test_one_percent_is_diagnostic_not_an_acceptance_tolerance(self):
        result = self.compare(np.full((40, 1), 1000.), np.full((40, 1), 1001.))
        self.assertFalse(result["pass"])
        self.assertEqual(result["rows"][0]["beyond_one_percent"], 0)

    def test_missing_year_nonfinite_and_wrong_shape_cannot_pass(self):
        a = np.ones((40, 1))
        b = a.copy(); b[20, 0] = np.nan
        self.assertFalse(self.compare(a, b)["pass"])
        self.assertFalse(self.compare(a, a, years=YEARS[:-1])["pass"])
        self.assertFalse(self.compare(np.ones((40, 2)), np.ones((40, 2)))["pass"])

    def test_unquantized_archive_is_flagged(self):
        self.assertFalse(self.compare(np.full((40, 1), .1), np.full((40, 1), .1))["pass"])

    def test_aggregate_cancellation_cannot_hide_cell_errors(self):
        a = np.full((40, 2), 100.)
        b = a + np.array([1., -1.])
        result = self.compare(a, b, dims=("Month", "Hour"), coords={"Month": ["M1"], "Hour": ["H1", "H2"]},
                              columns=("x[M1,H1]", "x[M1,H2]"))
        self.assertFalse(result["pass"])
        self.assertEqual(result["rows"][0]["annual_aggregate"]["max_abs"], 0.)

    def test_hourly_annualization_and_small_variable_scale(self):
        a, b = np.full((40, 2), .5), np.full((40, 2), .51)
        result = self.compare(a, b, dims=("Month", "Hour"), coords={"Month": ["M1"], "Hour": ["H1", "H2"]},
                              columns=("x[M1,H1]", "x[M1,H2]"))["rows"][0]
        self.assertAlmostEqual(result["max_fraction_variable_scale"], .02)
        self.assertAlmostEqual(result["annual_aggregate"]["max_abs"], .02 * 365/12)

    def test_sparse_constant_requires_exact_pattern_and_equation(self):
        names = ["Hourly exported electricity[M1,H1,Import]", "Hourly exported electricity[M1,H1,PV]"]
        frame = pd.DataFrame(np.ones((40, 2)), index=YEARS, columns=names)
        frame.iloc[0, 0] = 0
        frame.iloc[1:, 0] = np.nan
        equation = "Hourly exported electricity[Month,Hour,Import]=\n0\n~GWh"
        rebuilt, certificate = reconstruct_import(frame, equation)
        self.assertEqual(certificate["cells"], 39)
        self.assertEqual(rebuilt.iloc[:, 0].tolist(), [0]*40)
        self.assertTrue(frame.iloc[1:, 0].isna().all())
        for bad_equation in ("", equation.replace("=\n0", "=\n1")):
            with self.assertRaises(ValueError):
                reconstruct_import(frame, bad_equation)
        for r, c, v in ((0, 0, 1.), (1, 1, np.nan), (1, 0, 0.), (1, 1, np.inf)):
            invalid = frame.copy(); invalid.iloc[r, c] = v
            with self.assertRaises(ValueError):
                reconstruct_import(invalid, equation)

    def test_hourly_labels_are_ordered_explicitly_and_duplicates_rejected(self):
        frame = pd.DataFrame([{"variable": "x", "month": "M1", "hour": hour, "supplier": "", "year": year,
                               "value": year * 10 + i} for year in YEARS for i, hour in enumerate(("H1", "H2"))])
        ordered = hourly_frame(pa.Table.from_pandas(frame.sample(frac=1, random_state=2)), ["x[M1,H2]", "x[M1,H1]"])
        self.assertEqual(ordered.loc[2011].tolist(), [20111, 20110])
        for invalid in (pd.concat([frame, frame.iloc[:1]]), frame.iloc[:-1]):
            with self.assertRaises(ValueError):
                hourly_frame(pa.Table.from_pandas(invalid), ["x[M1,H1]", "x[M1,H2]"])
        sparse = hourly_frame(pa.Table.from_pandas(frame.iloc[:-1]), ["x[M1,H1]", "x[M1,H2]"], allow_missing=True)
        self.assertTrue(np.isnan(sparse.iloc[-1, -1]))
        with self.assertRaises(ValueError):
            hourly_frame(pa.Table.from_pandas(pd.concat([frame, frame.iloc[:1]])),
                         ["x[M1,H1]", "x[M1,H2]"], allow_missing=True)


if __name__ == "__main__":
    unittest.main()
