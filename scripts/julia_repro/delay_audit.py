"""Observe the pinned Python state-update order without changing equations.

DELAY FIXED executes input_func during sequential state assignment. A direct
read of an already-updated nested SMOOTH can therefore use the new state even
though ordinary step-cached auxiliaries still hold their old-state values.
This audit records actual reads, and requires bitwise equality to the frozen
oracle before its observations can be used by the experimental translator.
"""
from __future__ import annotations

from functools import wraps
import importlib.metadata
import os
from pathlib import Path

import numpy as np

from .common import PINS, YEARS, RUNTIME, check_sources, digest, dump, read, run_logged
from .results import compare, save_frame


def run(directory, mode="diagnostic", case="base"):
    if os.environ.get("PYTHONHASHSEED") != "0":
        raise RuntimeError("State-order audit requires PYTHONHASHSEED=0 at process startup")
    if importlib.metadata.version("pysd") != PINS["pysd_reference"]:
        raise RuntimeError("State-order audit requires the frozen Python reference")
    import sure_paths
    sure_paths.set_variant("v3")
    import sure_pysd as sp
    from pysd.py_backend.statefuls import DelayFixed

    directory = Path(directory).resolve()
    manifest = read(directory / "manifest.json")
    check_sources(manifest)
    installed = {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()}
    if any(installed.get(name) != version for name, version in manifest["packages"].items()
           if name not in {"pip", "setuptools"}):
        raise RuntimeError("State-order audit environment differs from the frozen reference")
    outputs = manifest["outputs"] if mode == "app" else manifest["diagnostics"]
    sp.OUTPUTS = outputs
    model = sp.load_model(prune=True)
    constants = sp.build_constant_params(model)
    objects = model._dynamicstateful_elements
    order = [item.py_name for item in objects]
    delays = [item for item in objects if isinstance(item, DelayFixed)]
    target = directory / "debug/delay-audit" / mode / case
    target.parent.mkdir(parents=True, exist_ok=True)
    records = {item.py_name: [] for item in delays}
    arrays = {item.py_name: [] for item in delays}
    updated, active, current_reads = set(), [], []
    in_step = False
    initial = {}
    originals = []

    # Special methods must be patched on the class. Capture every original
    # first, so inherited methods are never wrapped twice.
    methods = [(cls, cls.__call__, "__call__" in cls.__dict__) for cls in {type(obj) for obj in objects}]
    for cls, original, local in methods:
        @wraps(original)
        def called(obj, *args, _original=original, **kwargs):
            if active:
                current_reads.append((obj.py_name, obj.py_name in updated))
            return _original(obj, *args, **kwargs)
        cls.__call__ = called
        originals.append((cls, "__call__", original, local))

    for obj in objects:
        original = obj.update
        @wraps(original)
        def update(value, _object=obj, _original=original):
            result = _original(value)
            if in_step:
                updated.add(_object.py_name)
            return result
        obj.update = update
        originals.append((obj, "update", original, False))

    for obj in delays:
        original = obj.input_func
        @wraps(original)
        def input_value(_object=obj, _original=original):
            if not in_step:
                return _original()
            active.append(_object.py_name)
            current_reads.clear()
            cached_before = sorted(model.cache.data)
            try:
                value = _original()
                arrays[_object.py_name].append(np.asarray(value, dtype=np.float64).copy())
                records[_object.py_name].append({
                    "time": float(model.time()),
                    "state_reads": [{"name": name, "updated": changed}
                                    for name, changed in dict.fromkeys(current_reads)],
                    "cached_before": cached_before,
                })
                return value
            finally:
                active.pop()
        obj.input_func = input_value
        originals.append((obj, "input_func", original, True))

    original_step = model._euler_step
    def step(dt):
        nonlocal in_step
        updated.clear()
        if not initial:
            for obj in objects:
                if "hourly_imported_electricity" in obj.py_name:
                    initial[obj.py_name] = np.asarray(obj.state, dtype=np.float64).tolist()
        in_step = True
        try:
            return original_step(dt)
        finally:
            in_step = False
    model._euler_step = step
    originals.append((model, "_euler_step", original_step, False))
    try:
        frame = sp.run_scenario(model, scenario_inputs=manifest["scenarios"][case],
                                const_params=constants, timestamps=YEARS,
                                flatten=mode == "app", return_columns=outputs)
    finally:
        for owner, name, original, local in reversed(originals):
            if local:
                setattr(owner, name, original)
            else:
                delattr(owner, name)

    save_frame(target, frame, outputs, manifest, flattened=mode == "app")
    comparison = compare(directory / "reference" / mode / case, target, exact=True)
    dump(target.with_suffix(".comparison.json"), comparison)
    np.savez_compressed(target.with_suffix(".inputs.npz"), **{k: np.asarray(v) for k, v in arrays.items()})
    audit = {"pass": comparison["pass"], "mode": mode, "case": case,
             "hash_seed": os.environ["PYTHONHASHSEED"], "order": order,
             "implementation": digest(Path(__file__)), "pins": manifest["pins"],
             "packages": manifest["packages"],
             "reference": {suffix: digest((directory / "reference" / mode / case).with_suffix(suffix))
                           for suffix in (".json", ".npz", ".params.json", ".provenance.json")},
             "results": {suffix: digest(target.with_suffix(suffix)) for suffix in (".json", ".npz")},
             "sources": manifest["sources"], "initial_import_states": initial,
             "inputs_sha256": digest(target.with_suffix(".inputs.npz")),
             "delays": {name: {"update_index": order.index(name),
                 "reads_updated_states": sorted({read["name"] for record in values
                     for read in record["state_reads"] if read["updated"]}),
                 "records": values} for name, values in records.items()}}
    dump(target.with_suffix(".audit.json"), audit)
    if not comparison["pass"]:
        raise RuntimeError("State-order instrumentation changed the frozen reference output")
    print({"pass": True, "mode": mode, "updated_reads": {
        name: item["reads_updated_states"] for name, item in audit["delays"].items()
        if item["reads_updated_states"]}}, flush=True)
    return audit


def ensure_policy(directory):
    """Derive the SURE policy only from two verified, unchanged Python audits."""
    directory = Path(directory).resolve()
    manifest = read(directory / "manifest.json")
    check_sources(manifest)
    audits = {}
    evidence = {}
    for mode in ("app", "diagnostic"):
        target = directory / "debug/delay-audit" / mode / "base"
        path = target.with_suffix(".audit.json")
        reference = directory / "reference" / mode / "base"
        def valid(audit):
            return (audit["pass"] and audit["hash_seed"] == "0"
                    and audit["sources"] == manifest["sources"] and audit["pins"] == manifest["pins"]
                    and audit["packages"] == manifest["packages"] and audit["implementation"] == digest(Path(__file__))
                    and audit["reference"] == {s: digest(reference.with_suffix(s)) for s in audit["reference"]}
                    and audit["results"] == {s: digest(target.with_suffix(s)) for s in audit["results"]}
                    and audit["inputs_sha256"] == digest(target.with_suffix(".inputs.npz")))
        try:
            audit = read(path)
            ready = valid(audit)
        except (KeyError, OSError, ValueError):
            ready = False
        if not ready:
            command = ("from scripts.julia_repro.delay_audit import run; run("
                       + repr(str(directory)) + ", mode=" + repr(mode) + ")")
            run_logged([RUNTIME / "python-reference/bin/python", "-B", "-c", command],
                       directory / "logs" / f"delay-audit-{mode}.log")
            audit = read(path)
            if not valid(audit):
                raise RuntimeError(f"Unverified state-order audit: {mode}")
        audits[mode] = audit
        evidence[str(path.relative_to(directory))] = digest(path)
    policies = {mode: {name: item["reads_updated_states"] for name, item in audit["delays"].items()
                       if item["reads_updated_states"]} for mode, audit in audits.items()}
    if audits["app"]["order"] != audits["diagnostic"]["order"] or policies["app"] != policies["diagnostic"]:
        raise RuntimeError("Python app and diagnostic use different sequential state-update semantics")
    return {"updated_reads": policies["app"], "order": audits["app"]["order"], "evidence": evidence}
