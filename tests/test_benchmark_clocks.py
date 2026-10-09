"""Standalone timing audit checks; deliberately outside frozen test_julia* files."""
import math
import unittest

from scripts.verify_julia_benchmark_timing import audit_interval, validate_timings


def sample(awake, offset=100_000_000_000, width=1000):
    return {"absolute_before_ns": awake, "continuous_ns": awake + offset + width // 2,
            "absolute_after_ns": awake + width}


def timing(**changes):
    return {"load_seconds": 2., "initialize_seconds": 1., "solve_seconds": 2.,
            "extraction_seconds": 3., "simulation_and_capture_seconds": 6.,
            "serialization_seconds": 1., "max_rss_bytes": 1000, **changes}


class BenchmarkClockTests(unittest.TestCase):
    def test_no_sleep_is_certified_by_overlapping_offset_brackets(self):
        report = audit_interval(sample(0), sample(10_000_000_000))
        self.assertTrue(report["pass"])
        self.assertEqual(report["awake_seconds"], 10.)
        self.assertLess(report["suspend_lower_seconds"], 0.)
        self.assertGreater(report["suspend_upper_seconds"], 0.)

    def test_system_suspend_is_not_accepted_as_compute_time(self):
        report = audit_interval(sample(0), sample(10_000_000_000, offset=103_000_000_000))
        self.assertFalse(report["pass"])
        self.assertAlmostEqual(report["suspend_lower_seconds"], 3., places=5)

    def test_exact_ten_millisecond_limit_is_rejected(self):
        report = audit_interval(sample(0, width=0), sample(10_000_000_000, offset=100_010_000_000, width=0))
        self.assertFalse(report["pass"])

    def test_excessive_bracket_uncertainty_is_rejected(self):
        self.assertFalse(audit_interval(sample(0, width=20_000_000), sample(1_000_000_000))["pass"])

    def test_clock_reset_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "backwards"):
            audit_interval(sample(2_000_000_000), sample(1_000_000_000))
        self.assertFalse(audit_interval(sample(0), sample(1_000_000_000, offset=99_000_000_000))["pass"])

    def test_bad_clock_sample_is_rejected(self):
        bad = sample(0)
        bad["continuous_ns"] = math.nan
        with self.assertRaisesRegex(ValueError, "Invalid clock"):
            audit_interval(bad, sample(1_000_000_000))

    def test_nested_timers_are_not_double_counted(self):
        row = timing(load_compilation_seconds=1.8, initial_u0_construction_seconds=1.,
                     load_excluding_initialization_seconds=1., solve_compilation_seconds=1.9)
        report = validate_timings([row], 9., serialization=True)
        self.assertEqual(report["disjoint_phase_seconds"], 9.)

    def test_all_six_warm_iterations_are_bounded_together(self):
        rows = [timing()] + [timing(load_seconds=0.) for _ in range(5)]
        self.assertEqual(validate_timings(rows, 38.)["disjoint_phase_seconds"], 38.)

    def test_oversized_phase_total_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "exceeds outer"):
            validate_timings([timing()], 7.)

    def test_invalid_timer_values_are_rejected(self):
        for value in (-1., math.nan, math.inf, -math.inf, True):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "Invalid timer"):
                validate_timings([timing(solve_seconds=value)], 100.)

    def test_inconsistent_simulation_total_and_missing_phase_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "disagrees"):
            validate_timings([timing(simulation_and_capture_seconds=1.)], 100.)
        row = timing()
        del row["solve_seconds"]
        with self.assertRaisesRegex(ValueError, "Missing Julia"):
            validate_timings([row], 100.)


if __name__ == "__main__":
    unittest.main()
