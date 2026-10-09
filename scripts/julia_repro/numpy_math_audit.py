"""Capture actual elementary operations without changing the frozen model file."""
from __future__ import annotations

import ast
import importlib.metadata
import inspect
import operator
import os
from pathlib import Path
import sys
import warnings

import numpy as np

from .common import CONFIG, ROOT, RUNTIME, PINS, YEARS, check_sources, digest, dump, read, run_logged
from .numpy_math_patch import platform_contract
from .results import compare, load_snapshot, save_frame


def capture(directory, case="base"):
    directory = Path(directory).resolve()
    manifest = read(directory / "manifest.json")
    check_sources(manifest)
    installed = {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()}
    if (os.environ.get("PYTHONHASHSEED") != "0" or installed.get("pysd") != PINS["pysd_reference"]
            or any(installed.get(name) != version for name, version in manifest["packages"].items()
                   if name not in {"pip", "setuptools"})):
        raise RuntimeError("Elementary math audit requires the frozen Python environment and hash seed")
    target = directory / "debug/numpy-math-audit" / case
    target.mkdir(parents=True, exist_ok=True)
    records, offset = [], 0
    streams = {name: (target / name).open("wb") for name in ("input.bin", "right.bin", "expected.bin")}
    import sure_paths
    sure_paths.set_variant("v3")
    import sure_pysd as sp
    sp.OUTPUTS = manifest["diagnostics"]
    source = ROOT / "Vensim/SURE_pysd_v3.py"

    class Powers(ast.NodeTransformer):
        def visit_BinOp(self, node):
            self.generic_visit(node)
            if isinstance(node.op, ast.Pow):
                return ast.copy_location(ast.Call(func=ast.Name(id="_seneca_capture_power", ctx=ast.Load()),
                    args=[node.left, node.right, ast.Constant(node.lineno)], keywords=[]), node)
            return node

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        model = sp.load_model(prune=True)
        constants = sp.build_constant_params(model)
        module = model.components._components
        original_numpy, patched = module.np, []

        def record(name, x, y, result, parent, line):
            nonlocal offset
            def aligned(value):
                if hasattr(value, "dims"):
                    return np.asarray(value.broadcast_like(result).transpose(*result.dims), dtype=np.float64)
                return np.broadcast_to(np.asarray(value, dtype=np.float64), np.asarray(result).shape)
            left, right, expected = aligned(x), aligned(y), np.asarray(result, dtype=np.float64)
            if not all(np.isfinite(value).all() for value in (left, right, expected)):
                raise ValueError(f"Nonfinite elementary math sample: {parent.f_code.co_name}/{line}")
            for filename, value in (("input.bin", left), ("right.bin", right), ("expected.bin", expected)):
                value.ravel(order="C").astype("<f8").tofile(streams[filename])
            records.append({"name": name, "component": parent.f_code.co_name, "line": line,
                            "shape": list(expected.shape), "offset": offset, "count": expected.size,
                            "time": float(model.time()), "phase": getattr(model.time, "stage", "unknown"),
                            "left_type": type(x).__name__, "right_type": type(y).__name__})
            offset += expected.size
            return result

        class Proxy:
            def __getattr__(self, name):
                operation = getattr(original_numpy, name)
                if name not in {"exp", "log", "sqrt"}:
                    return operation
                def invoke(x, *args, **kwargs):
                    if args or kwargs:
                        raise ValueError("Unsupported elementary math signature")
                    parent = sys._getframe(1)
                    return record(name, x, 0., operation(x), parent, parent.f_lineno)
                return invoke

        def power(x, y, line):
            array = any(hasattr(v, "dims") or isinstance(v, (np.ndarray, np.generic)) for v in (x, y))
            return record("numpy_power" if array else "python_power", x, y, operator.pow(x, y), sys._getframe(1), line)

        module.np = Proxy()
        module._seneca_capture_power = power
        try:
            for node in ast.parse(source.read_text()).body:
                if not isinstance(node, ast.FunctionDef) or not any(
                        isinstance(child, ast.BinOp) and isinstance(child.op, ast.Pow) for child in ast.walk(node)):
                    continue
                if not hasattr(module, node.name):
                    continue
                function = inspect.unwrap(getattr(module, node.name))
                if not inspect.isfunction(function) or function.__globals__ is not module.__dict__:
                    continue
                node.decorator_list = []
                altered = ast.fix_missing_locations(ast.Module(body=[Powers().visit(node)], type_ignores=[]))
                namespace = {}
                exec(compile(altered, str(source), "exec"), namespace)
                patched.append((function, function.__code__))
                function.__code__ = namespace[node.name].__code__
            frame = sp.run_scenario(model, scenario_inputs=manifest["scenarios"][case], const_params=constants,
                                    timestamps=YEARS, flatten=False, return_columns=manifest["diagnostics"])
        finally:
            module.np = original_numpy
            for function, code in patched:
                function.__code__ = code
            del module._seneca_capture_power
            for stream in streams.values():
                stream.close()
    save_frame(target / "snapshot", frame, manifest["diagnostics"], manifest, flattened=False)
    comparison = compare(directory / "reference/diagnostic" / case, target / "snapshot", exact=True)
    _, expected = load_snapshot(directory / "reference/diagnostic" / case)
    _, actual = load_snapshot(target / "snapshot")
    bitwise = all(np.array_equal(expected[name].view(np.uint64), actual[name].view(np.uint64)) for name in expected)
    dump(target / "comparison.json", comparison)
    dump(target / "records.json", records)
    dump(target / "platform.json", platform_contract())
    dump(target / "warnings.json", [str(item.message) for item in caught])
    artifact_names = ("input.bin", "right.bin", "expected.bin", "records.json", "platform.json", "snapshot.json", "snapshot.npz")
    report = {"pass": comparison["pass"] and bitwise, "uint64_bitwise": bitwise, "case": case,
              "calls": len(records), "cells": offset, "instrumented_power_functions": len(patched),
              "sources": manifest["sources"], "pins": manifest["pins"], "packages": manifest["packages"],
              "implementation": digest(Path(__file__)), "platform": platform_contract(),
              "reference": {suffix: digest((directory / "reference/diagnostic" / case).with_suffix(suffix))
                            for suffix in (".json", ".npz", ".params.json", ".provenance.json")},
              "artifacts": {name: digest(target / name) for name in artifact_names}}
    dump(target / "capture.json", report)
    if not report["pass"]:
        raise RuntimeError("Elementary math instrumentation changed the frozen Python outputs")
    return report


def run(directory, case="base"):
    """Capture in the pinned Python interpreter, then test native Julia helpers."""
    from .execution import julia_command
    directory = Path(directory).resolve()
    target = directory / "debug/numpy-math-audit" / case
    command = f"from scripts.julia_repro.numpy_math_audit import capture; capture({str(directory)!r}, case={case!r})"
    run_logged([RUNTIME / "python-reference/bin/python", "-B", "-c", command], target / "capture.log")
    run_logged([*julia_command(), CONFIG / "test_numpy_math.jl", target], target / "julia.log")
    result = read(target / "results.json")
    result.update({"capture_sha256": digest(target / "capture.json"),
                   "kernel_sha256": digest(CONFIG / "numpy_math.jl"),
                   "harness_sha256": digest(CONFIG / "test_numpy_math.jl")})
    dump(target / "results.json", result)
    return result
