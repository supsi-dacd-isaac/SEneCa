"""Relaxed numerical acceptance must preserve the original structural gates."""
from pathlib import Path
import tempfile
import unittest

import numpy as np

from scripts.julia_repro.common import CONFIG, YEARS, digest, dump, read
from scripts.julia_repro.comparison import compare
from scripts.julia_repro.results import compare as strict_compare


class CandidateAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def snapshot(self, name, values, *, discrete=False, coords=None, years=None, include=True):
        path = self.root / name
        np.savez_compressed(path.with_suffix(".npz"), v0000=np.asarray(values, dtype=np.float64))
        variable = {"key": "v0000", "dims": ["Axis"], "coords": {"Axis": ["a", "b"]} if coords is None else coords,
                    "columns": ["Output[a]", "Output[b]"], "discrete": discrete}
        dump(path.with_suffix(".json"), {"years": YEARS if years is None else years,
             "variables": {"Output": variable} if include else {}, "sha256": digest(path.with_suffix(".npz"))})
        return path

    def test_small_roundoff_passes_acceptance_and_retains_failing_strict_diagnostic(self):
        python = np.zeros((len(YEARS), 2))
        python[:, 1] = 1.
        julia = python.copy()
        julia[0, 0], julia[0, 1] = 4e-11, 1. + 5e-9
        reference, candidate = self.snapshot("python", python), self.snapshot("julia", julia)
        result = compare(reference, candidate)
        self.assertTrue(result["pass"])
        self.assertFalse(result["strict"]["pass"])
        self.assertEqual(result["strict"], strict_compare(reference, candidate))
        self.assertEqual(result["acceptance_policy"], read(CONFIG / "acceptance.json"))
        self.assertEqual(result["rows"][0]["failures"], 0)
        self.assertNotIn("year", result["rows"][0])

    def test_large_error_still_fails(self):
        values = np.zeros((len(YEARS), 2))
        julia = values.copy()
        julia[7, 1] = 1e-6
        result = compare(self.snapshot("python", values), self.snapshot("julia", julia))
        self.assertFalse(result["pass"])
        self.assertFalse(result["strict"]["pass"])
        self.assertEqual(result["rows"][0]["year"], YEARS[7])
        self.assertEqual(result["rows"][0]["column"], "Output[b]")

    def test_scale_is_per_elementary_series_over_the_entire_time_axis(self):
        python = np.zeros((len(YEARS), 2))
        python[0, 0] = 1000.
        julia = python.copy()
        julia[-1, :] = 2e-8
        result = compare(self.snapshot("python", python), self.snapshot("julia", julia))
        self.assertFalse(result["pass"])
        self.assertEqual(result["rows"][0]["failures"], 1)
        self.assertEqual(result["rows"][0]["column"], "Output[b]")

    def test_discrete_values_remain_exact(self):
        python = np.ones((len(YEARS), 2))
        julia = python.copy()
        julia[0, 0] = np.nextafter(1., 2.)
        result = compare(self.snapshot("python", python, discrete=True),
                         self.snapshot("julia", julia, discrete=True))
        self.assertFalse(result["pass"])
        self.assertEqual(result["rows"], result["strict"]["rows"])
        self.assertEqual(result["rows"][0]["tolerance"], 0.)

    def test_missing_or_reordered_coordinates_cannot_pass(self):
        values = np.zeros((len(YEARS), 2))
        reference = self.snapshot("python", values)
        for index, coordinates in enumerate(({}, {"Axis": ["a"]}, {"Axis": ["b", "a"]})):
            with self.subTest(coordinates=coordinates):
                result = compare(reference, self.snapshot(f"julia{index}", values, coords=coordinates))
                self.assertFalse(result["pass"])
                self.assertEqual(result["rows"][0]["reason"], "coords mismatch")

    def test_missing_or_shifted_years_cannot_pass(self):
        values = np.zeros((len(YEARS), 2))
        reference = self.snapshot("python", values)
        for index, years in enumerate((YEARS[:-1], [year + 1 for year in YEARS])):
            with self.subTest(years=years):
                result = compare(reference, self.snapshot(f"julia{index}", values, years=years))
                self.assertFalse(result["pass"])
                self.assertEqual(result["rows"][0]["reason"], "timestamps must be exactly 2011..2050")

    def test_nonfinite_reference_or_candidate_cannot_pass(self):
        for side in ("reference", "candidate"):
            for value in (np.nan, np.inf, -np.inf):
                with self.subTest(side=side, value=value):
                    python = np.zeros((len(YEARS), 2))
                    julia = python.copy()
                    (python if side == "reference" else julia)[4, 1] = value
                    result = compare(self.snapshot("python", python), self.snapshot("julia", julia))
                    self.assertFalse(result["pass"])
                    self.assertEqual(result["rows"][0]["reason"], f"nonfinite {side}")

    def test_missing_output_cannot_pass(self):
        values = np.zeros((len(YEARS), 2))
        result = compare(self.snapshot("python", values), self.snapshot("julia", values, include=False))
        self.assertFalse(result["pass"])
        self.assertEqual({row["reason"] for row in result["rows"]}, {"variable set mismatch", "missing variable"})

    def test_exact_mode_returns_the_original_comparator_unchanged(self):
        values = np.ones((len(YEARS), 2))
        reference = self.snapshot("python", values)
        for index, perturbation in enumerate((0., np.spacing(1.))):
            with self.subTest(perturbation=perturbation):
                candidate = self.snapshot(f"julia{index}", values + perturbation)
                actual = compare(reference, candidate, exact=True)
                self.assertEqual(actual, strict_compare(reference, candidate, exact=True))
                self.assertEqual(actual["pass"], perturbation == 0.)
                self.assertNotIn("acceptance_policy", actual)


if __name__ == "__main__":
    unittest.main()
