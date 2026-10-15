import unittest
from types import SimpleNamespace

import numpy as np
from pysd.py_backend.statefuls import DelayFixed, Smooth

from sure_julia.synchronous_delays import install


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


if __name__ == "__main__":
    unittest.main()
