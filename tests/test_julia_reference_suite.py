"""Reference orchestration must preserve failures and verify resumed evidence."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from scripts.julia_repro import reference
from scripts.julia_repro.common import YEARS, digest, dump, read


class ReferenceSuiteTests(unittest.TestCase):
    def test_reference_hash_ignores_only_experiment_bookkeeping(self):
        original = (reference.ROOT / "scripts/julia_repro/common.py").read_text()
        before = reference.reference_implementation()
        bookkeeping = original.replace("def experiment_hashes():", "def experiment_hashes():\n    additional_test_files = []")
        with patch.object(Path, "read_text", return_value=bookkeeping):
            self.assertEqual(before, reference.reference_implementation())
        numerical_environment = original.replace('"PYTHONHASHSEED": "0"', '"PYTHONHASHSEED": "1"')
        self.assertNotEqual(original, numerical_environment)
        with patch.object(Path, "read_text", return_value=numerical_environment):
            self.assertNotEqual(before, reference.reference_implementation())

    def manifest(self):
        return {"sources": {}, "pins": {}, "packages": {}, "dimensions": {},
                "variables": {"x": {"subscripts": []}}, "outputs": ["x"], "diagnostics": ["x"],
                "scenarios": {"base": {"a": 1.}, "bad": {"a": 2.}, "high": {"a": 3.}}}

    def artifact(self, directory, manifest, *, finite=True):
        target = directory / "reference/app/base"
        target.parent.mkdir(parents=True)
        values = np.ones((len(YEARS), 1))
        if not finite:
            values[-1, 0] = np.nan
        np.savez_compressed(target.with_suffix(".npz"), v0000=values)
        dump(target.with_suffix(".json"), {"years": YEARS, "sha256": digest(target.with_suffix(".npz")),
             "variables": {"x": {"key": "v0000", "dims": [], "coords": {}, "columns": ["x"]}}})
        dump(target.with_suffix(".inputs.json"), {"requested": manifest["scenarios"]["base"]})
        for ext in (".params.json", ".warnings.json", ".timing.json"):
            dump(target.with_suffix(ext), {})
        dump(target.with_suffix(".provenance.json"), {
            "context": reference.reference_provenance(manifest, ["base"], "app", None, 0),
            "artifacts": {ext: digest(target.with_suffix(ext)) for ext in
                          (".json", ".npz", ".params.json", ".inputs.json", ".timing.json", ".warnings.json")}})
        return target

    def test_resume_rejects_changed_parameters_or_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory, manifest = Path(tmp), self.manifest()
            target = self.artifact(directory, manifest)
            self.assertTrue(reference.reference_ready(directory, manifest, ["base"]))
            self.assertFalse(reference.reference_ready(directory, manifest, ["base"], label="sequence"))
            dump(target.with_suffix(".params.json"), {"changed": 1.})
            self.assertFalse(reference.reference_ready(directory, manifest, ["base"]))

    def test_resume_rejects_nonfinite_even_with_matching_checksums(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory, manifest = Path(tmp), self.manifest()
            self.artifact(directory, manifest, finite=False)
            self.assertFalse(reference.reference_ready(directory, manifest, ["base"]))

    def test_failed_case_does_not_prevent_later_cases_or_pass_full_suite(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory, manifest, attempted = Path(tmp), self.manifest(), []
            dump(directory / "manifest.json", manifest)
            def worker(command, log):
                attempted.append(str(log))
                if str(log).endswith("reference_app_bad.log"):
                    raise RuntimeError("intentional Python failure")
            with patch.object(reference, "check_sources"), patch.object(reference, "run_logged", worker), \
                 patch.object(reference, "reference_ready", return_value=True), \
                 patch.object(reference, "compare", return_value={"pass": True, "rows": []}), \
                 patch("scripts.julia_repro.packing.validate_real_snapshot", return_value={"pass": True}):
                with self.assertRaisesRegex(RuntimeError, "Python reference failed"):
                    reference.run_reference_suite(directory, list(manifest["scenarios"]))
            report = read(directory / "reference-suite.json")
            self.assertFalse(report["pass"])
            self.assertTrue(report["full_suite"])
            self.assertFalse(report["cases"]["bad"]["pass"])
            self.assertTrue(report["cases"]["high"]["pass"])
            self.assertTrue(any(path.endswith("reference_diagnostic_high.log") for path in attempted))
            self.assertFalse(read(directory / "checks/reference_bad.json")["pass"])


if __name__ == "__main__":
    unittest.main()
