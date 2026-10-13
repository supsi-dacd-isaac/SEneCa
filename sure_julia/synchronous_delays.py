"""Experimental Euler semantics: DELAY FIXED samples the pre-step state.

PySD 3.14.3 evaluates DelayFixed.input_func during sequential state assignment.
A nested uncached SMOOTH can therefore be read before or after its update.
Capture all fixed-delay inputs before the Euler step; leave initialization and
the original stateful update methods intact. Applied only to an explicit model
instance, never to the installed package or application source.
"""
from copy import deepcopy


def install(model):
    import pysd
    from pysd.py_backend.statefuls import DelayFixed
    if pysd.__version__ != "3.14.3":
        raise ValueError("Reaudit the integration contract for this PySD version")
    if getattr(model, "_sure_synchronous_delays", False):
        raise ValueError("Delay policy already installed")
    original_step = model._euler_step

    def step(dt):
        delays = [d for d in model._dynamicstateful_elements if isinstance(d, DelayFixed)]
        original_inputs = [d.input_func for d in delays]
        values = [deepcopy(fn()) for fn in original_inputs]
        try:
            for delay, value in zip(delays, values):
                delay.input_func = lambda value=value: value
            return original_step(dt)
        finally:
            for delay, fn in zip(delays, original_inputs):
                delay.input_func = fn

    model._euler_step = step
    model._sure_synchronous_delays = True
