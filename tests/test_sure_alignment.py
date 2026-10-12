import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from pysd.py_backend.statefuls import DelayFixed, Smooth

from scripts.sure_v4.synchronous_delays import install
from scripts.sure_v4.allocation_probe import make_cases, priority_mdl, compare_native
from scripts.sure_v4.align_delays import migrate
from scripts.julia_repro.common import dump, digest


class SynchronousDelayTests(unittest.TestCase):
    def trajectory(self, reverse, staged, years):
        smooth = Smooth(lambda: 10., lambda: 2., lambda: 0., lambda: 1, "s")
        delay = DelayFixed(smooth, lambda: years, lambda: -1., lambda: 1., "d")
        objects = [smooth, delay] if reverse else [delay, smooth]
        model = SimpleNamespace(_dynamicstateful_elements=objects)

        def step(dt):
            next_states = [o.state + o.ddt() * dt for o in objects]
            for obj, state in zip(objects, next_states):
                obj.update(state)
        model._euler_step = step
        if staged:
            install(model)
        runs = []
        for _ in range(2):
            smooth.initialize()
            delay.initialize()
            values = [float(delay())]
            for _ in range(8):
                model._euler_step(1.)
                values.append(float(delay()))
            runs.append(values)
        np.testing.assert_array_equal(*runs)
        return runs[0]

    def test_real_nested_state_order_and_reinitialization(self):
        for delay in (.01, .1, 1., 2., 4.):
            with self.subTest(delay=delay):
                old_before = self.trajectory(False, False, delay)
                old_after = self.trajectory(True, False, delay)
                self.assertNotEqual(old_before, old_after)
                np.testing.assert_array_equal(self.trajectory(False, True, delay), old_before)
                np.testing.assert_array_equal(self.trajectory(True, True, delay), old_before)

    def test_snapshot_copies_arrays_and_restores_callbacks_after_error(self):
        value = np.array([1., 2.])
        callback = lambda: value
        delay = DelayFixed(callback, lambda: 1, lambda: 0, lambda: 1, "d")
        model = SimpleNamespace(_dynamicstateful_elements=[delay])
        def step(dt):
            value[:] = 99
            np.testing.assert_array_equal(delay.input_func(), [1., 2.])
            raise RuntimeError("deliberate failure")
        model._euler_step = step
        install(model)
        with self.assertRaisesRegex(RuntimeError, "deliberate"):
            model._euler_step(1.)
        self.assertIs(delay.input_func, callback)
        with self.assertRaisesRegex(ValueError, "already installed"):
            install(model)


class NativeProbeTests(unittest.TestCase):
    def test_native_float32_comparison_rejects_material_error_and_identity_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = make_cases()[:1]
            dump(root / "cases.json", cases)
            native = {"case_sha256": digest(root / "cases.json"), "series": {}}
            for kind in ("Available allocation", "Priority allocation"):
                for i, value in enumerate(cases[0]["expected"]):
                    native["series"][f"{kind}[C000,S{i}]"] = {"times": [0.], "values": [float(np.float32(value))]}
            dump(root / "native.json", native)
            self.assertTrue(all(r["pass"] for r in compare_native(root, root)["functions"].values()))
            native["series"]["Available allocation[C000,S0]"]["values"][0] = .5
            dump(root / "native.json", native)
            self.assertFalse(compare_native(root, root)["functions"]["Available allocation"]["pass"])
            native["case_sha256"] = "different"
            dump(root / "native.json", native)
            with self.assertRaisesRegex(ValueError, "identity"):
                compare_native(root, root)

    def test_priority_shift_invariance_and_conservation(self):
        cases = make_cases()
        for a, b in zip(cases[:21], cases[21:42]):
            np.testing.assert_allclose(a["expected"], b["expected"], rtol=0, atol=1e-14)
        for c in cases:
            self.assertAlmostEqual(sum(c["expected"]), min(sum(c["request"]), c["supply"]), places=13)
            self.assertTrue(np.all(np.array(c["expected"]) >= 0))
            self.assertTrue(np.all(np.array(c["expected"]) <= np.array(c["request"])))

    def test_rejects_unverified_model_layout_and_allocation_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.jl"
            source.write_text("different model")
            with self.assertRaisesRegex(ValueError, "Reaudit"):
                migrate(source, Path(tmp) / "candidate.jl")
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            priority_mdl("Supplier priority type=2 ~~|")


if __name__ == "__main__":
    unittest.main()
