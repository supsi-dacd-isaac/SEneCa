import tempfile
import unittest
from pathlib import Path

import numpy as np

from scripts.julia_repro.common import YEARS, digest, dump
from scripts.sure_v4.validate import exact_replay, warning_review


class V4ValidationTests(unittest.TestCase):
    def snapshot(self, path, value):
        np.savez(path.with_suffix(".npz"), v=np.full((40, 1), value, dtype=np.float64))
        dump(path.with_suffix(".json"), {"years": YEARS, "sha256": digest(path.with_suffix(".npz")),
             "variables": {"x": {"key": "v", "dims": [], "coords": {}, "columns": ["x"]}}})

    def test_replay_requires_bitwise_identity_even_for_signed_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.snapshot(root / "a", 0.)
            self.snapshot(root / "b", -0.)
            self.assertFalse(exact_replay(root / "a", root / "b")["pass"])
            self.snapshot(root / "b", 0.)
            self.assertTrue(exact_replay(root / "a", root / "b")["pass"])

    def test_unknown_or_unsupported_warnings_block_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for mode in ("app", "diagnostic", "fresh"):
                dump(root / "reference" / mode / "warnings.json", [])
            dump(root / "model/warnings.json", [])
            manifest = {"variables": {"Known": {"python_name": "known"}}}
            self.assertTrue(warning_review(root, manifest)["pass"])
            for text in ("Unsupported equation replaced by zero", "_ext_data_unknown\nextrapolating data above the maximum value of the time"):
                dump(root / "reference/app/warnings.json", [{"category": "UserWarning", "message": text}])
                self.assertFalse(warning_review(root, manifest)["pass"])
            dump(root / "reference/app/warnings.json", [])
            dump(root / "model/warnings.json", [{"category": "UserWarning", "message": "Unsupported function ignored"}])
            self.assertFalse(warning_review(root, manifest)["pass"])


if __name__ == "__main__":
    unittest.main()
