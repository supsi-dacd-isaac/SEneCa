"""Production contracts independent of a Julia installation."""
import itertools
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from sure_julia.catalog import defaults, inventory, outputs, parameters
from sure_julia.common import digest, dump, identity
from sure_julia.runtime import JuliaBackend, frame_from_arrays
from sure_julia.translator.builder_patch import component_cells, _rectangles
from sure_julia.validation import compare


class ProductionTests(unittest.TestCase):
    def test_catalog_covers_every_requested_component(self):
        variables, _ = inventory()
        self.assertFalse(set(outputs()) - set(variables))
        self.assertEqual(len(defaults()), 40)

    def test_parameters_are_complete_strict_and_do_not_round(self):
        a = parameters({"FiT": .123456781})
        b = parameters({"FiT": .123456782})
        self.assertNotEqual(identity(a), identity(b))
        self.assertEqual(len(a), 40)
        for values in [{"unknown": 1}, {"FiT": float("nan")}, {"Provvedimento 1.2": .5}]:
            with self.assertRaises(ValueError):
                parameters(values)

    def test_except_cells_and_rectangles_preserve_every_rank(self):
        for rank in range(1, 7):
            dims = {f"D{i}": [f"a{i}", f"b{i}", f"c{i}"] for i in range(rank)}
            ranges = {**dims, "Tail": list(dims.values())[-1][1:]}
            cells = component_cells(list(dims), [list(dims)[:-1]+["Tail"]], dims, ranges)
            self.assertEqual(set(cells), {x for x in itertools.product(range(1,4), repeat=rank) if x[-1] == 1})
            expanded = [x for r in _rectangles(cells) for x in itertools.product(*r)]
            self.assertEqual(sorted(expanded), cells)

    def test_frame_labels_preserve_six_dimensional_values(self):
        dims = [f"D{i}" for i in range(6)]
        coords = {d: [f"{d}b", f"{d}a"] for d in dims}
        spec = {"name": "X", "dims": dims, "coords": coords}
        array = np.arange(40*64, dtype=float).reshape(40, 2, 2, 2, 2, 2, 2)
        for values in (array, np.asfortranarray(array)):
            frame = frame_from_arrays({"X": values}, [spec])
            self.assertEqual(frame.columns[0], "X[D0b,D1b,D2b,D3b,D4b,D5b]")
            np.testing.assert_array_equal(frame.to_numpy(), array.reshape(40, -1))
            nested = frame_from_arrays({"X": values}, [spec], flatten=False)
            np.testing.assert_array_equal(nested.X.iloc[39].values, array[39])

    def test_comparator_never_discards_invalid_cells_or_years(self):
        spec = [{"name": "X", "dims": [], "coords": {}}]
        a = np.arange(40, dtype=float)
        self.assertTrue(compare({"X": a}, {"X": a+1e-12}, spec)["pass"])
        for b in [a[:-1], np.full(40, np.nan), a+1e-3]:
            self.assertFalse(compare({"X": a}, {"X": b}, spec)["pass"])

    def test_invalid_backend_cannot_fall_back(self):
        from sure_backend import backend_name
        with patch.dict(os.environ, {"SURE_BACKEND": "unknown"}):
            with self.assertRaises(ValueError):
                backend_name()

    def test_model_location_changes_the_live_cache_identity(self):
        from sure_backend import engine_identity
        with tempfile.TemporaryDirectory() as temporary:
            directories = [Path(temporary) / name for name in ("first", "second")]
            for directory in directories:
                directory.mkdir()
                (directory / "build.json").write_text("same manifest")
            with patch.dict(os.environ, {"SURE_BACKEND": "julia", "SURE_JULIA_MODEL": str(directories[0])}):
                first = engine_identity()
            with patch.dict(os.environ, {"SURE_BACKEND": "julia", "SURE_JULIA_MODEL": str(directories[1])}):
                self.assertNotEqual(first, engine_identity())

    def test_unresponsive_worker_is_reaped_after_timeout(self):
        # A real subprocess exercises pipe ownership and timeout cleanup without
        # requiring Julia or an expensive model compilation in unit tests.
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            model = directory / "model.jl"
            model.write_text("")
            dump(directory / "build.json", {"complete": True, "model": model.name,
                                           "artifacts": {model.name: digest(model)}})
            dump(directory / "export.json", [{"name": "X", "dims": [], "coords": {}}])
            worker = directory / "worker"
            worker.write_text(f"#!{sys.executable}\nimport time\nprint('{{\"ready\": true}}', flush=True)\ninput()\ntime.sleep(60)\n")
            worker.chmod(0o700)
            engine = JuliaBackend(directory, timeout=2)
            try:
                with patch.dict(os.environ, {"SURE_JULIA_BIN": str(worker)}):
                    engine._start()
                    process = engine.process
                    engine.timeout = .05
                    with self.assertRaises(TimeoutError):
                        engine.run_arrays()
                    self.assertIsNone(engine.process)
                    self.assertIsNotNone(process.poll())
                    self.assertTrue(process.stdin.closed)
                    self.assertTrue(process.stdout.closed)
            finally:
                engine.close()

    def test_batch_gmd_preserves_labels_and_audits_existing_negative_weight_rule(self):
        from sure_julia.batch import gmd
        dims = [f"D{i}" for i in range(6)]
        coords = {d: ["second", "first"] for d in dims}
        export = {name: {"dims": dims, "coords": coords} for name in ("value", "weight")}
        values = np.arange(64, dtype=float)
        weights = np.arange(1, 65, dtype=float)
        arrays = {"value": np.broadcast_to(values.reshape((2,)*6), (40,)+(2,)*6).copy(),
                  "weight": np.broadcast_to(weights.reshape((2,)*6), (40,)+(2,)*6).copy()}
        spec = {"gmd": {"value": "value", "weight": "weight"}}
        expected = np.sum(weights[:, None]*weights[None, :]*abs(values[:, None]-values[None, :]))/(2*weights.sum()**2)
        self.assertAlmostEqual(gmd(arrays, spec, export)["gmd"], expected, places=12)
        v, w = values[:-1], weights[:-1]
        expected = np.sum(w[:, None]*w[None, :]*abs(v[:, None]-v[None, :]))/(2*w.sum()**2)
        for negative, significant in [(-1., 1), (-1e-15, 0)]:
            arrays["weight"].flat[-1] = negative
            audit = []
            self.assertAlmostEqual(gmd(arrays, spec, export, audit)["gmd"], expected, places=12)
            self.assertEqual(audit[0]["excluded_cells"], 1)
            self.assertEqual(audit[0]["beyond_numerical_zero"], significant)
            self.assertEqual(arrays["weight"].flat[-1], negative)
        arrays["weight"].flat[-1] = np.nan
        with self.assertRaises(ValueError):
            gmd(arrays, spec, export)


if __name__ == "__main__":
    unittest.main()
