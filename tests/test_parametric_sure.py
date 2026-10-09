"""Parameter name and generated source boundaries are explicit and fail closed."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.julia_parametric.model import resolve_name, rewrite_identifiers, replace_once
from scripts.benchmark_julia_parametric import runtime_signature, verify_control_reference
from scripts.julia_repro.common import digest, dump


class ParameterTests(unittest.TestCase):
    def test_quoted_vensim_names_resolve_without_dropping_controls(self):
        self.assertEqual(resolve_name("Provvedimento 1.2", {'"Provvedimento 1.2"': 'provvedimento_12'}), '"Provvedimento 1.2"')
        self.assertEqual(resolve_name("pv rebate", {"PV rebate": "pv_rebate"}), "PV rebate")

    def test_unknown_and_ambiguous_controls_raise(self):
        for namespace in ({}, {"P": "one", '"P"': "two"}):
            with self.assertRaises(ValueError):
                resolve_name("p", namespace)

    def test_exact_name_has_precedence(self):
        self.assertEqual(resolve_name("P", {"P": "one", '"P"': "two"}), "P")

    def test_rewrite_does_not_change_labels_comments_or_longer_identifiers(self):
        source = '"fit" => c -> fit + fit_cost # fit\ntext = "escaped \\" fit"\n'
        expected = '"fit" => c -> c.parameters.fit + fit_cost # fit\ntext = "escaped \\" fit"\n'
        self.assertEqual(rewrite_identifiers(source, {"fit": "c.parameters.fit"}), expected)

    def test_source_contract_must_be_unique(self):
        self.assertEqual(replace_once("abc", "b", "X"), "aXc")
        for source in ("ac", "abbc"):
            with self.assertRaises(ValueError):
                replace_once(source, "b", "X")

    def test_validation_identity_includes_runtime_but_not_orchestration(self):
        signature = {"scripts/julia_parametric/model.py": "model", "benchmarks/julia-parametric/worker.jl": "worker",
                     "scripts/benchmark_julia_parametric.py": "driver", "tests/test_parametric_sure.py": "tests"}
        for path in ("scripts/julia_parametric/model.py", "benchmarks/julia-parametric/worker.jl"):
            self.assertNotEqual(runtime_signature(signature), runtime_signature({**signature, path: "changed"}))
        self.assertEqual(runtime_signature(signature), runtime_signature({**signature,
            "scripts/benchmark_julia_parametric.py": "changed"}))

    def test_controls_gate_rejects_failed_or_changed_reference(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source, artifact = root / "source.py", root / "controls/snapshot.json"
            source.write_text("source")
            dump(artifact, {"value": 1})
            certificate = {"pass": True, "source_context": {str(source): digest(source)},
                           "artifacts": {artifact.name: digest(artifact)}}
            dump(root / "controls/report.json", certificate)
            self.assertEqual(verify_control_reference(root), digest(root / "controls/report.json"))
            dump(root / "controls/report.json", {**certificate, "pass": False})
            with self.assertRaises(ValueError):
                verify_control_reference(root)
            dump(root / "controls/report.json", certificate)
            source.write_text("changed")
            with self.assertRaises(ValueError):
                verify_control_reference(root)
            source.write_text("source")
            dump(artifact, {"value": 2})
            with self.assertRaises(ValueError):
                verify_control_reference(root)


if __name__ == "__main__":
    unittest.main()
