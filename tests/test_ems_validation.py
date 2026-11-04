"""EMS acceptance rejects missing evidence and substantive numerical changes."""
import json
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from pathlib import Path

import numpy as np

from sure_julia.ems_store_validation import compare_values, verify_sources
from sure_julia.validation import cases


class EMSValidationTests(unittest.TestCase):
    def test_regeneration_rejects_disagreement_before_writing_data(self):
        from sure_julia import python_batch
        original = {"signal": np.ones(40)}
        changed = {"signal": np.ones(40) * 2}
        oracle = SimpleNamespace(run_arrays=lambda *args: original)
        julia = SimpleNamespace(run_arrays=lambda *args: changed,
                                export=[{"name": "signal", "dims": [], "coords": {}}])
        with TemporaryDirectory() as directory, patch.multiple(python_batch, create=True,
                ENGINE=oracle, JULIA=julia, TARGET=Path(directory)):
            with self.assertRaisesRegex(ValueError, "Julia differs"):
                python_batch._execute({"id": "test", "parameters": {}, "outputs": ["signal"]})
            self.assertFalse((Path(directory) / "parts").exists())
            self.assertFalse(json.loads((Path(directory) / "comparisons/test.json").read_text())["pass"])

    def test_live_suite_covers_rebates_communities_and_continuous_inputs(self):
        values = cases()
        crosses = [v for n, v in values.items() if n.startswith("ems_")]
        self.assertEqual(len(crosses), 18)
        self.assertEqual({v["EMS rebate"] for v in crosses}, {0., .4, .8})
        for rebate in (0., .4, .8):
            self.assertEqual({(v["Energy Community scenario"], v["Buildings PVno connected to RCPv"])
                              for v in crosses if v["EMS rebate"] == rebate},
                             {(c, b) for c in (0., 1.) for b in (1., 1.5, 2.)})
        self.assertEqual(values["live_intermediate"]["EMS rebate"], .35)

    def test_comparison_distinguishes_roundoff_from_changed_results(self):
        reference = np.array([[0., 1., 1e6], [0., 2., 2e6]])
        self.assertTrue(compare_values(reference, reference.copy())["exact"])
        self.assertTrue(compare_values(reference, np.nextafter(reference, np.inf))["pass"])
        for candidate in (reference + 1., reference[:-1], np.full_like(reference, np.nan)):
            self.assertFalse(compare_values(reference, candidate)["pass"])
        changed = reference.copy()
        changed[0, 0] = 1e-7
        failure = compare_values(reference, changed)
        self.assertFalse(failure["pass"])
        self.assertEqual(json.loads(json.dumps(failure))["first_index"], [0, 0])

    def test_incomplete_source_manifest_cannot_certify_the_data(self):
        from sure_julia.common import MODEL_REVISION
        partial = {"backend": "python", "model_variant": "ems1",
                   "model_revision": MODEL_REVISION, "sources": {}}
        with patch("sure_julia.ems_store_validation.read", return_value=partial):
            with self.assertRaisesRegex(ValueError, "Incomplete"):
                verify_sources()
