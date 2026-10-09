"""Acceptance must not survive failed reruns or mixed experiment revisions."""
from contextlib import ExitStack, contextmanager
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from scripts.julia_repro import execution
from scripts.julia_repro.common import digest, dump, read


class ValidationProvenanceTests(unittest.TestCase):
    def test_parallel_scenarios_keep_separate_evidence_and_complete_determinism(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            with self.experiment(directory) as (_, runner):
                barrier, lock, started = threading.Barrier(2, timeout=5), threading.Lock(), set()
                def synchronize_first_runs(run_directory, case, raw, *args, **kwargs):
                    with lock:
                        first = case not in started
                        started.add(case)
                    if first:
                        barrier.wait()
                runner.side_effect = synchronize_first_runs
                execution.validate(directory, ["base", "high", "base"], jobs=2)
                result = read(directory / "validation.json")
                self.assertTrue(result["pass"])
                self.assertEqual(result["validation_jobs"], 2)
                self.assertEqual(set(result["determinism"]),
                                 {"fresh_a", "fresh_b", "sequence_0", "sequence_1", "sequence_2"})
                stamps = [read(directory / "checks" / f"julia_{case}.provenance.json")
                          for case in ("base", "high")]
                self.assertNotEqual(stamps[0]["context"]["reference"], stamps[1]["context"]["reference"])

    @contextmanager
    def experiment(self, directory, *, run=None):
        current = {"revision": "original"}
        manifest = {"scenarios": {"base": {}, "high": {}}, "outputs": ["x"]}
        dump(directory / "manifest.json", manifest)
        dump(directory / "fixtures.json", {"pass": True, "experiment": current})
        dump(directory / "reference-suite.json", {"pass": True, "full_suite": True,
             "selected_pass": True, "cases": {case: {"pass": True} for case in manifest["scenarios"]}})
        dump(directory / "checks/reference_determinism.json", {"pass": True})
        for case in manifest["scenarios"]:
            dump(directory / "checks" / f"reference_{case}.json", {"pass": True})
            dump(directory / "checks" / f"packing_{case}.json", {"pass": True, "cells_checked": 1})
            target = directory / "julia" / case
            dump(target / "translation.json", {"pass": True, "model": "model.jl"})
            for folder in ("reference/diagnostic", "candidate"):
                path = directory / folder / case
                dump(path.with_suffix(".json"), {})
                path.with_suffix(".npz").write_bytes(b"test artifact")

        def convert(_, case, raw, destination, **kwargs):
            dump(destination.with_suffix(".json"), {})
            destination.with_suffix(".npz").write_bytes(b"test artifact")

        def logged(command, log):
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text("")

        def verify(_, case):
            target = directory / "julia" / case
            return target, read(target / "translation.json")

        with ExitStack() as stack:
            stack.enter_context(patch("scripts.julia_repro.common.check_sources"))
            stack.enter_context(patch("scripts.julia_repro.reference.reference_ready", return_value=True))
            stack.enter_context(patch("scripts.julia_repro.packing.validate_real_snapshot", return_value={"pass": True, "cells_checked": 1}))
            stack.enter_context(patch("scripts.julia_repro.energy.check_snapshot", return_value={"pass": True, "cells": 1}))
            stack.enter_context(patch("scripts.julia_repro.reduction_samples.run", return_value={"pass": True, "cells": 1}))
            stack.enter_context(patch.object(execution, "experiment_hashes", side_effect=lambda: dict(current)))
            stack.enter_context(patch.object(execution, "evidence_hashes", return_value={"evidence": "fixed"}))
            stack.enter_context(patch.object(execution, "verify_translation", side_effect=verify))
            stack.enter_context(patch.object(execution, "convert", side_effect=convert))
            stack.enter_context(patch.object(execution, "compare", side_effect=lambda *args, **kwargs: {"pass": True, "rows": []}))
            stack.enter_context(patch.object(execution, "run_logged", side_effect=logged))
            runner = stack.enter_context(patch.object(execution, "run_julia", side_effect=run))
            yield current, runner

    def matching_stamp(self, directory, case, current):
        candidate = directory / "candidate" / case
        stamp = directory / "checks" / f"julia_{case}.provenance.json"
        context = {"experiment": current, "translation": digest(directory / "julia" / case / "translation.json"),
                   "reference": {str(p.relative_to(directory)): digest(p) for p in
                                 [directory / "reference/diagnostic" / f"{case}{suffix}"
                                  for suffix in (".json", ".npz")]}}
        dump(stamp, {"context": context, "candidate": {suffix: digest(candidate.with_suffix(suffix))
                                                      for suffix in (".json", ".npz")}})
        return stamp

    def test_forced_failed_rerun_invalidates_old_resume_stamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            with self.experiment(directory, run=RuntimeError("solver failed")) as (current, runner):
                stamp = self.matching_stamp(directory, "base", current)
                with self.assertRaisesRegex(RuntimeError, "solver failed"):
                    execution.validate(directory, ["base", "high"], resume=False)
                self.assertFalse(stamp.exists(), "A failed rerun must revoke previous reusable evidence")
                self.assertFalse(read(directory / "validation.json")["pass"])
                with self.assertRaisesRegex(RuntimeError, "solver failed"):
                    execution.validate(directory, ["base", "high"], resume=True)
                self.assertEqual([call.args[1] for call in runner.call_args_list], ["base", "base"])

    def test_experiment_change_during_integration_cannot_be_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            with self.experiment(directory) as (current, runner):
                runner.side_effect = lambda *args, **kwargs: current.update(revision="changed during solve")
                with self.assertRaisesRegex((RuntimeError, ValueError), "(?i)(experiment|changed|revision)"):
                    execution.validate(directory, ["base", "high"])
                self.assertFalse(read(directory / "validation.json")["pass"])

    def test_earlier_candidate_overwrite_during_later_case_cannot_be_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            with self.experiment(directory) as (_, runner):
                def overwrite_earlier_case(run_directory, case, *args, **kwargs):
                    if case == "high":
                        (directory / "candidate/base.npz").write_bytes(b"changed after comparison")
                runner.side_effect = overwrite_earlier_case
                with self.assertRaisesRegex((RuntimeError, ValueError), "(?i)(evidence|candidate|changed|provenance)"):
                    execution.validate(directory, ["base", "high"])
                self.assertFalse(read(directory / "validation.json")["pass"])

    def test_benchmark_gate_rechecks_original_source_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            with self.experiment(directory) as (current, _):
                dump(directory / "validation.json", {"pass": True, "full_suite": True,
                     "experiment": current, "evidence": {"evidence": "fixed"}})
                with patch("scripts.julia_repro.common.check_sources", side_effect=RuntimeError("original source changed")):
                    with self.assertRaisesRegex(RuntimeError, "original source changed"):
                        execution.check_benchmark_gate(directory)

    def test_sequence_middle_scenario_must_match_independent_high(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            with self.experiment(directory):
                def comparison(reference, candidate, **kwargs):
                    return {"pass": candidate.name != "sequence_1_high", "rows": []}
                with patch.object(execution, "compare", side_effect=comparison):
                    with self.assertRaisesRegex(RuntimeError, "Numerical validation failed"):
                        execution.validate(directory, ["base", "high"])
                result = read(directory / "validation.json")
                self.assertFalse(result["pass"])
                self.assertFalse(result["determinism"]["sequence_1"]["pass"])

    def test_sequence_warning_blocks_acceptance(self):
        for prefix in ("Warning:", "WARNING:"):
            with self.subTest(prefix=prefix), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                with self.experiment(directory):
                    def warning(command, log):
                        log.write_text(f"{prefix} unsupported runtime behavior\n")
                    with patch.object(execution, "run_logged", side_effect=warning):
                        with self.assertRaisesRegex(RuntimeError, "(?i)sequence runtime warning"):
                            execution.validate(directory, ["base", "high"])
                    self.assertFalse(read(directory / "validation.json")["pass"])

    def test_failed_real_packing_blocks_julia_even_with_old_pass_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            with self.experiment(directory) as (_, runner):
                with patch("scripts.julia_repro.packing.validate_real_snapshot", return_value={"pass": False}):
                    with self.assertRaisesRegex(ValueError, "packing failed"):
                        execution.validate(directory, ["base", "high"])
                runner.assert_not_called()
                self.assertFalse(read(directory / "validation.json")["pass"])

    def test_reference_energy_failure_blocks_acceptance_even_with_equal_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            with self.experiment(directory):
                def energy(path):
                    return {"pass": "reference" not in path.parts, "cells": 1}
                with patch("scripts.julia_repro.energy.check_snapshot", side_effect=energy):
                    with self.assertRaisesRegex(RuntimeError, "Numerical validation failed"):
                        execution.validate(directory, ["base", "high"])
                self.assertFalse(read(directory / "validation.json")["pass"])
                check = read(directory / "checks/julia_base.json")
                self.assertFalse(check["conservation"]["python"]["pass"])


if __name__ == "__main__":
    unittest.main()
