from __future__ import annotations

import importlib.metadata
from contextlib import contextmanager
import resource
import sys
import time
import warnings

import numpy as np

from .common import ROOT, PINS, YEARS, read, dump, check_sources
from .results import save_frame


@contextmanager
def phase_timers(model):
    """Observe existing calls, without changing equations, output or caching."""
    from pysd.py_backend.output import ModelOutput
    metrics, originals = {}, []
    def wrap(owner, name, metric):
        original = getattr(owner, name)
        local = name in vars(owner)
        def measured(*args, **kwargs):
            started = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                metrics[metric] = metrics.get(metric, 0.) + time.perf_counter() - started
        originals.append((owner, name, original, local))
        setattr(owner, name, measured)
    wrap(model, "_config_simulation", "initialization_and_configuration_seconds")
    wrap(model, "_integrate_step", "integration_seconds")
    for name in ("initialize", "update", "add_run_elements", "postprocess"):
        wrap(ModelOutput, name, "extraction_seconds")
    try:
        yield metrics
    finally:
        for owner, name, original, local in reversed(originals):
            if local:
                setattr(owner, name, original)
            else:
                delattr(owner, name)


def run_reference(directory, cases, mode="app", label=None):
    manifest = read(directory / "manifest.json")
    check_sources(manifest)
    if importlib.metadata.version("pysd") != PINS["pysd_reference"]:
        raise RuntimeError("Reference requires PySD 3.14.3")
    expected = manifest["packages"]
    current = {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()}
    differences = {k: (v, current.get(k)) for k, v in expected.items()
                   if k not in {"pip", "setuptools"} and current.get(k) != v}
    if differences:
        raise RuntimeError(f"Reference environment drift: {differences}")
    sys.path.insert(0, str(ROOT))
    import sure_paths
    sure_paths.set_variant("v3")
    import sure_pysd as sp
    outputs = manifest["outputs"] if mode == "app" else manifest["diagnostics"]
    if mode == "diagnostic":
        sp.OUTPUTS = outputs  # process-local, expands dependency closure without editing the app
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        started = time.perf_counter()
        model = sp.load_model(prune=True)
        constants = sp.build_constant_params(model)
        load_seconds = time.perf_counter() - started
        for index, case in enumerate(cases):
            scenario = manifest["scenarios"][case]
            ignored = [name for name in scenario if not sp._in_ns(model, name)]
            applied = sp.build_params(model, const_params=constants, scenario_inputs=scenario)
            params = {}
            for name, value in applied.items():
                if hasattr(value, "dims"):
                    params[name] = {"dims": list(value.dims), "coords": {d: list(value.coords[d].values)
                                    for d in value.dims}, "values": value.values.tolist()}
                else:
                    params[name] = {"dims": [], "coords": {}, "values": float(value)}
            suffix = f"{label}_{index:02d}_{case}" if label else case
            target = directory / "reference" / mode / suffix
            target.parent.mkdir(parents=True, exist_ok=True)
            dump(target.with_suffix(".params.json"), params)
            dump(target.with_suffix(".inputs.json"), {"requested": scenario, "ignored_by_webapp": ignored})
            started = time.perf_counter()
            print(f"Running {mode}/{case}", flush=True)
            with phase_timers(model) as metrics:
                frame = sp.run_scenario(model, scenario_inputs=scenario, const_params=constants,
                                        timestamps=YEARS, flatten=mode == "app", return_columns=outputs)
            simulation_seconds = time.perf_counter() - started
            started = time.perf_counter()
            print(f"Serializing {mode}/{case}", flush=True)
            save_frame(target, frame, outputs, manifest, flattened=mode == "app")
            dump(target.with_suffix(".timing.json"), {
                "load_seconds": load_seconds if index == 0 else 0.,
                "simulation_and_capture_seconds": simulation_seconds,
                **metrics,
                "serialization_seconds": time.perf_counter() - started,
                "max_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "scenario": case, "mode": mode,
            })
            dump(target.with_suffix(".warnings.json"), [str(w.message) for w in caught])
            print(f"Saved {mode}/{suffix}: {simulation_seconds:.2f}s", flush=True)
