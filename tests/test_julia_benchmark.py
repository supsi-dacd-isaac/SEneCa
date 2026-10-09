"""Benchmark acceptance and timings use the same completed artifact boundary."""
from contextlib import ExitStack, contextmanager
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.julia_repro import execution, reporting
from scripts.julia_repro.common import digest, dump, read


class BenchmarkTests(unittest.TestCase):
    @contextmanager
    def harness(self, directory):
        experiment = {"revision": "current"}
        dump(directory / "validation.json", {"pass": True, "full_suite": True, "experiment": experiment})
        dump(directory / "benchmark.json", {"pass": True, "status": "complete", "old_result": True})
        clock = [0.]

        def python_worker(command, log):
            start = command.index("--scenarios") + 1
            end = command.index("--label")
            cases, label = command[start:end], command[end+1]
            clock[0] += 4. + 14. * len(cases)
            for i, case in enumerate(cases):
                dump(directory / "reference/app" / f"{label}_{i:02d}_{case}.timing.json", {
                    "load_seconds": 4. if i == 0 else 0.,
                    "initialization_and_configuration_seconds": 1., "integration_seconds": 3.,
                    "extraction_seconds": 6., "simulation_and_capture_seconds": 10.,
                    "serialization_seconds": 4., "max_rss_bytes": 100., "scenario": case, "mode": "app"})

        def julia_worker(run_directory, case, raw, iterations=1, **kwargs):
            clock[0] += 7. + 6. * iterations
            for i in range(1, iterations+1):
                target = raw if iterations == 1 else raw / str(i)
                dump(target / "timing.json", {"load_seconds": 7. if i == 1 else 0.,
                    "initialize_seconds": 1., "solve_seconds": 2., "extraction_seconds": 3.,
                    "simulation_and_capture_seconds": 6., "max_rss_bytes": 200., "iteration": i})

        def convert(*args, **kwargs):
            clock[0] += 4.  # Canonical compressed snapshot conversion is deliberately material.

        with ExitStack() as stack:
            gate = stack.enter_context(patch.object(execution, "check_benchmark_gate"))
            stack.enter_context(patch.object(execution, "experiment_hashes", return_value=experiment))
            stack.enter_context(patch.object(execution.time, "perf_counter", side_effect=lambda: clock[0]))
            stack.enter_context(patch.object(execution, "run_logged", side_effect=python_worker))
            julia = stack.enter_context(patch.object(execution, "run_julia", side_effect=julia_worker))
            stack.enter_context(patch.object(execution, "convert", side_effect=convert))
            compare = stack.enter_context(patch.object(execution, "compare", return_value={"pass": True, "rows": []}))
            yield gate, julia, compare

    def test_failed_repeat_revokes_previous_accepted_timings(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            with self.harness(directory) as (_, _, compare):
                compare.return_value = {"pass": False, "rows": [{"pass": False, "reason": "changed result"}]}
                with self.assertRaisesRegex(RuntimeError, "timed execution changed"):
                    execution.benchmark(directory)
            result = read(directory / "benchmark.json")
            self.assertFalse(result["pass"])
            self.assertNotIn("old_result", result)

    def test_same_serialized_boundary_and_required_repeat_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            with self.harness(directory) as (gate, _, compare):
                execution.benchmark(directory)
                self.assertEqual(compare.call_count, 54)  # Includes every unreported warm-up.
                self.assertEqual(gate.call_count, 2)
            result = read(directory / "benchmark.json")
            self.assertTrue(result["pass"])
            self.assertEqual(result["validation_sha256"], digest(directory / "validation.json"))
            self.assertEqual(len(result["measurements"]), 48)
            self.assertEqual(len(result["summary"]), 12)
            for row in result["measurements"]:
                self.assertEqual(row["serialization_seconds"], 4.)
                self.assertEqual(row["simulation_and_serialization_seconds"],
                                 row["simulation_and_capture_seconds"] + 4.)
                if row["kind"] == "fresh_process":
                    self.assertEqual(row["wall_seconds"], 18. if row["engine"] == "python" else 17.)
                else:
                    self.assertEqual(row["load_seconds"], 0.)
            for group in result["summary"]:
                count = 3 if group["kind"] == "fresh_process" else 5
                self.assertEqual(len(group["metrics"]["simulation_and_capture_seconds"]["values"]), count)

    def test_final_gate_failure_cannot_publish_new_timings(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            with self.harness(directory) as (gate, _, _):
                gate.side_effect = [None, RuntimeError("evidence changed during benchmark")]
                with self.assertRaisesRegex(RuntimeError, "evidence changed"):
                    execution.benchmark(directory)
            self.assertFalse(read(directory / "benchmark.json")["pass"])

    def test_validation_replacement_during_benchmark_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            with self.harness(directory) as (_, julia, _):
                original = julia.side_effect
                def replaced_validation(*args, **kwargs):
                    original(*args, **kwargs)
                    dump(directory / "validation.json", {"pass": True, "different_validation": True})
                julia.side_effect = replaced_validation
                with self.assertRaisesRegex(RuntimeError, "Validation changed during benchmarking"):
                    execution.benchmark(directory)
            self.assertFalse(read(directory / "benchmark.json")["pass"])

    def test_report_omits_stale_or_incomplete_benchmark(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            current = {"revision": "current"}
            dump(directory / "manifest.json", {"pins": {"base_commit": "base", "data_release": "data-v1.0.0",
                 "pysd_reference": "3.14.3", "julia": "1.10.12"}, "scenarios": {"base": {}},
                 "variables": {}, "outputs": [], "diagnostics": [], "six_dimensional": [], "ignored_ui_levers": []})
            dump(directory / "validation.json", {"pass": True, "full_suite": True, "experiment": current})
            valid = {"pass": True, "experiment": current, "validation_sha256": digest(directory / "validation.json"),
                     "summary": [{"engine": "OLD_SPEED_SENTINEL", "scenario": "base", "kind": "fresh_process", "metrics": {}}]}
            with patch.object(reporting, "experiment_hashes", return_value=current), \
                 patch.object(execution, "check_benchmark_gate"):
                for change in ({"pass": False}, {"experiment": {"revision": "old"}}, {"validation_sha256": "old"}):
                    with self.subTest(change=change):
                        dump(directory / "benchmark.json", {**valid, **change})
                        summary = reporting.write_report(directory)
                        self.assertTrue(summary["accepted"])
                        self.assertIsNone(summary["benchmark"])
                        self.assertNotIn("OLD_SPEED_SENTINEL", (directory / "REPORT.md").read_text())


if __name__ == "__main__":
    unittest.main()
