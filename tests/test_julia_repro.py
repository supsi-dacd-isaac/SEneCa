"""Exact representation and fail-closed comparator regression tests."""
import itertools
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from scripts.julia_repro.builder_patch import component_cells, _rectangles
from scripts.julia_repro.common import YEARS, digest, dump
from scripts.julia_repro.inventory import model_inventory, scenarios
from scripts.julia_repro.packing import DIMENSIONS, mapping, pack, unpack
from scripts.julia_repro.results import compare


class RepresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.coords, _ = model_inventory()

    def test_5280_distinct_cells_are_preserved_with_both_memory_orders(self):
        shape = tuple(len(self.coords[d]) for d in DIMENSIONS)
        for order in ("C", "F"):
            values = np.arange(5280, dtype=np.float64).reshape(shape, order=order)
            converted = pack(values, self.coords)
            self.assertEqual(converted.shape, (120, 11, 4))
            np.testing.assert_array_equal(values, unpack(converted, self.coords))
            self.assertEqual(len(set(converted.ravel())), 5280)

    def test_selection_reduction_normalization_and_category_transition(self):
        shape = tuple(len(self.coords[d]) for d in DIMENSIONS)
        values = np.arange(1, 5281, dtype=np.float64).reshape(shape)
        packed = pack(values, self.coords)
        # HS aggregation, normalized shares and a transfer between two HS categories.
        np.testing.assert_array_equal(values.sum(axis=1).reshape(120, 4), packed.sum(axis=1))
        normalized = values / values.sum(axis=1, keepdims=True)
        np.testing.assert_array_equal(pack(normalized, self.coords), packed / packed.sum(axis=1, keepdims=True))
        moved, moved_packed = values.copy(), packed.copy()
        transfer = values[:, 0, ...] / 2
        moved[:, 0, ...] -= transfer
        moved[:, 1, ...] += transfer
        moved_packed[:, 1, :] += moved_packed[:, 0, :] / 2
        moved_packed[:, 0, :] /= 2
        np.testing.assert_array_equal(pack(moved, self.coords), moved_packed)
        mask = np.zeros(shape, dtype=bool)
        mask[:, :, 0, :, 0, 1] = True
        np.testing.assert_array_equal(pack(np.where(mask, 0., values), self.coords),
                                      np.where(pack(mask, self.coords), 0., packed))

    def test_label_mapping_works_with_reordered_coordinates(self):
        coords = {k: list(reversed(v)) for k, v in self.coords.items()}
        pairs = list(mapping(coords))
        self.assertEqual(len(set(x for x, _ in pairs)), 5280)
        self.assertEqual(len(set(x for _, x in pairs)), 5280)

    def test_exact_exclusions_for_all_ranks_and_partial_last_axis(self):
        for rank in range(1, 7):
            dims = {f"D{i}": [f"a{i}", f"b{i}", f"c{i}"] for i in range(rank)}
            ranges = {**dims, "Tail": list(dims.values())[-1][1:]}
            clause = list(dims)[:-1] + ["Tail"]
            cells = component_cells(list(dims), [clause], dims, ranges)
            self.assertEqual(set(cells), {x for x in itertools.product(range(1,4), repeat=rank) if x[-1] == 1})
            rectangles = _rectangles(cells)
            expanded = [p for box in rectangles for p in itertools.product(*box)]
            self.assertEqual(set(expanded), set(cells))
            self.assertEqual(len(expanded), len(cells))

    def test_nonrectangular_exclusion_union_is_not_a_bounding_box(self):
        dims = {"A": ["a1", "a2"], "B": ["b1", "b2"], "C": ["c1", "c2"]}
        cells = component_cells(list(dims), [["a1", "b2", "C"], ["a2", "B", "c1"]], dims, dims)
        self.assertEqual(set(cells), {(1,1,1), (1,1,2), (2,1,2), (2,2,2)})
        result = [x for box in _rectangles(cells) for x in itertools.product(*box)]
        self.assertEqual(set(result), set(cells))
        self.assertEqual(len(result), len(cells))

    def test_unknown_labels_cannot_be_silently_dropped(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            component_cells(["Broken"], [], {"D": ["a", "b"]}, {"Broken": ["a", "missing"]})


class ComparatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def snapshot(self, name, values, years=YEARS, coordinates=None):
        path = self.root / name
        np.savez_compressed(path.with_suffix(".npz"), v0000=values)
        dump(path.with_suffix(".json"), {"years": years, "sha256": digest(path.with_suffix(".npz")),
             "variables": {"X": {"key": "v0000", "columns": ["X[a]", "X[b]"],
                                  "dims": ["D"], "coords": {"D": coordinates or ["a", "b"]}}}})
        return path

    def test_equal_arrays_pass(self):
        data = np.ones((40, 2))
        self.assertTrue(compare(self.snapshot("a", data), self.snapshot("b", data))["pass"])

    def test_per_series_scale_does_not_hide_small_cell_error(self):
        data = np.tile([1e12, 1e-9], (40, 1))
        changed = data.copy()
        changed[20,1] += 1e-5
        result = compare(self.snapshot("a", data), self.snapshot("b", changed))
        self.assertFalse(result["pass"])
        self.assertEqual(result["rows"][0]["year"], 2031)
        self.assertEqual(result["rows"][0]["column"], "X[b]")

    def test_nonfinite_cannot_pass_even_when_equal(self):
        for value in (float("nan"), float("inf")):
            data = np.ones((40,2)); data[0,0] = value
            self.assertFalse(compare(self.snapshot("a", data), self.snapshot("b", data))["pass"])

    def test_truncation_and_coordinate_permutation_fail(self):
        reference = self.snapshot("a", np.ones((40,2)))
        self.assertFalse(compare(reference, self.snapshot("b", np.ones((39,2)), YEARS[:-1]))["pass"])
        self.assertFalse(compare(reference, self.snapshot("b", np.ones((40,2)), coordinates=["b", "a"]))["pass"])

    def test_changed_snapshot_checksum_fails(self):
        path = self.snapshot("a", np.ones((40,2)))
        path.with_suffix(".npz").write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "Corrupt"):
            compare(path, path)

    def test_discrete_values_require_exact_equality(self):
        from scripts.julia_repro.common import read
        data = np.ones((40, 2))
        a = self.snapshot("a", data)
        b = self.snapshot("b", data + 1e-12)
        for path in (a, b):
            metadata = read(path.with_suffix(".json"))
            metadata["variables"]["X"]["discrete"] = True
            dump(path.with_suffix(".json"), metadata)
        self.assertFalse(compare(a, b)["pass"])

    def test_scenario_suite_is_deterministic_and_deduplicated(self):
        import pysd_explore_config as cfg
        first = scenarios(cfg.ALL_INPUTS)
        self.assertEqual(first, scenarios(cfg.ALL_INPUTS))
        values = list(first[0].values())
        self.assertEqual(len(values), len({tuple(sorted(v.items())) for v in values}))


class GateTests(unittest.TestCase):
    def test_only_matching_existing_python_data_notices_are_classified(self):
        from scripts.julia_repro.translation import classify_warnings
        notice = "foo\nData value missing or non-valid\nFile name: '/original/input.csv'\nReference cell: 'B2'\nfilled with the interpolation method"
        messages = [{"message": "_ext_data_" + notice.replace("/original/", "/copy/")},
                    {"message": notice.replace("B2", "B3")},
                    {"message": "Unsupported SmoothStructure: emitting placeholder 0.0"}]
        result = classify_warnings(messages, [notice])
        self.assertEqual([r["classification"] for r in result],
                         ["existing_python_input_interpolation", "blocking", "blocking"])

    def test_partial_stale_or_modified_evidence_never_unlocks_benchmark(self):
        from scripts.julia_repro.execution import check_benchmark_gate
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            dump(directory / "manifest.json", {})
            dump(directory / "reference-suite.json", {"pass": True, "full_suite": True})
            dump(directory / "checks/reference_determinism.json", {"pass": True})
            valid = {"pass": True, "full_suite": True, "experiment": {"version": "a"}, "evidence": {"data": "a"}}
            with patch("scripts.julia_repro.execution.experiment_hashes", return_value={"version": "a"}), \
                 patch("scripts.julia_repro.execution.evidence_hashes", return_value={"data": "a"}), \
                 patch("scripts.julia_repro.common.check_sources"):
                for changes in ({"pass": False}, {"full_suite": False}, {"experiment": {}}, {"evidence": {}}):
                    dump(directory / "validation.json", {**valid, **changes})
                    with self.assertRaises(RuntimeError):
                        check_benchmark_gate(directory)
                dump(directory / "validation.json", valid)
                check_benchmark_gate(directory)

    def test_timing_summary_keeps_raw_values_and_separates_engines(self):
        from scripts.julia_repro.execution import summarize_timings
        rows = [{"engine": "python", "scenario": "base", "kind": "fresh_process", "wall_seconds": value}
                for value in (1., 8., 3.)]
        summary = summarize_timings(rows)[0]["metrics"]["wall_seconds"]
        self.assertEqual(summary, {"values": [1., 8., 3.], "median": 3., "min": 1., "max": 8.})


if __name__ == "__main__":
    unittest.main()
