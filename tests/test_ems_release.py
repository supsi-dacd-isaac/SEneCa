"""EMS previews bind runtime, data and independent validation to one model."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.verify_julia_release import normalized_warnings, verify_ems


class EMSReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "provenance").mkdir()
        (self.root / "sure_julia/generated").mkdir(parents=True)
        self.warnings = [{"category": "UserWarning", "message": "File name: '/app/generated/input.csv'\nReference cell: 'B4'"}]
        (self.root / "sure_julia/generated/warnings.json").write_text(json.dumps(self.warnings))
        (self.root / "provenance/sections.parquet").write_bytes(b"test-only")
        self.actual = {k: {} for k in ("sources", "defaults", "parameters", "years", "float", "delay_policy")}
        self.actual.update(model_revision="sure-v8-ems-2", artifacts={"SURE.jl": "numerical", "warnings.json": "local"},
            implementation={p: "locked" for p in ("sure_julia/julia/Manifest.toml", "sure_julia/julia/Project.toml", "sure_julia/python.lock")})
        expected = deepcopy(self.actual)
        expected["artifacts"]["warnings.json"] = "other-checkout"
        self.provenance = {"backend": "python", "model": expected, "model_metadata_sha256": "build",
            "translation_warnings": normalized_warnings(self.warnings),
            "live_certificate": {"pass": True, "complete_suite": True, "cases": {str(i): True for i in range(55)}, "build": "build"},
            "data_audit": {"pass": True, "scenarios": 871, "configurations": 1197,
                           "model_revision": "sure-v8-ems-2", "generation_manifest_sha256": "generation", "sections": {}}}
        from scripts.data_release import EMS_DATA_PATHS
        for name in EMS_DATA_PATHS:
            if name.startswith("precomputed/"):
                path = self.root / name
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(b"verified-data")
                self.provenance["data_audit"]["sections"][path.stem.removesuffix("_scenarios")] = {
                    "new_sha256": hashlib.sha256(b"verified-data").hexdigest()}
        self.sections = {"backend": "python", "model_revision": "sure-v8-ems-2", "sources": {},
            "julia_validation": {"pass": True, "scenarios": 871, "build_sha256": "build"},
            "generation_manifest_sha256": "generation",
            "scenarios_sha256": hashlib.sha256(b"test-only").hexdigest()}
        (self.root / "provenance/sections.json").write_text(json.dumps(self.sections))

    def test_complete_evidence_accepts_only_warning_path_variation(self):
        verify_ems(self.root, self.provenance, self.actual)
        moved = [{**self.warnings[0], "message": self.warnings[0]["message"].replace('/app/generated/', '/different/build/')}]
        self.assertEqual(normalized_warnings(moved), normalized_warnings(self.warnings))

    def test_changed_equations_and_missing_scenarios_fail(self):
        changed = deepcopy(self.actual)
        changed["artifacts"]["SURE.jl"] = "different"
        with self.assertRaisesRegex(ValueError, "numerical artifacts"):
            verify_ems(self.root, self.provenance, changed)
        self.provenance["live_certificate"]["cases"].pop("0")
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            verify_ems(self.root, self.provenance, self.actual)

    def test_warning_cell_change_is_not_ignored(self):
        self.provenance["translation_warnings"][0]["message"] = "File name: 'input.csv'\nReference cell: 'B5'"
        with self.assertRaisesRegex(ValueError, "warnings differ"):
            verify_ems(self.root, self.provenance, self.actual)
