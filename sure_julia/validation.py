"""Full-cell comparison and the production scenario acceptance suite."""
import argparse
import concurrent.futures
import itertools
import multiprocessing
import os
import re
from pathlib import Path
import time
import traceback

import numpy as np
import pandas as pd

from .catalog import defaults, parameters
from .common import ROOT, YEARS, digest, dump, identity, read


def cases():
    from pysd_explore_config import ALL_INPUTS
    from pv_batteries import exploratory_config as exp
    base = defaults()
    result = {"base": base}
    # Worst negative dwelling weight in the original 8,171-scenario batch.
    result["regression_negative_stock"] = parameters({"PV rebate cantonal": 0.2, "FiT": 0.1, "Battery Rebate": 0.5, "PV rebate federal": 0.4})
    for name, select in [("low", min), ("mid", lambda v: sorted(v)[len(v)//2]), ("high", max)]:
        result[name] = parameters({i.name: float(select(i.values)) for i in ALL_INPUTS})
    for run in read(ROOT / "Vensim_test_runs/inputs.json")["runs"]:
        result[run["id"]] = parameters(run["inputs"])
    for i, spec in enumerate(ALL_INPUTS):
        values = spec.values if spec.binary or spec.choice_labels else [min(spec.values), max(spec.values)]
        for j, v in enumerate(values):
            result[f"lever_{i:02d}_{j}"] = {**base, spec.name: float(v)}
    for i, policy in enumerate(exp.all_policy_combos()):
        result[f"policy_{i:03d}"] = parameters({**policy, exp.EXPLORATORY_SWITCH: 1})
    for i, (name, bounds) in enumerate(exp.UNCERTAINTY_BOUNDS.items()):
        for j, value in enumerate(bounds):
            result[f"uncertainty_{i:02d}_{j}"] = parameters({name: value, exp.EXPLORATORY_SWITCH: 1})
    samples = pd.read_parquet(exp.SAMPLES_PATH)
    if len(samples) != 50 or not set(exp.UNCERTAINTY_ORDER) <= set(samples):
        raise ValueError("Unexpected uncertainty samples")
    for which, select in [("min", min), ("max", max)]:
        policy = {k: select(v) for k, v in exp.POLICY_GRID.items()}
        for i, sample in enumerate(samples[exp.UNCERTAINTY_ORDER].to_dict("records")):
            result[f"sample_{which}_{i:02d}"] = parameters({**policy, **sample, exp.EXPLORATORY_SWITCH: 1})
    return result


def compare(reference, candidate, export, exact=False):
    if set(reference) != set(candidate):
        return {"pass": False, "reason": "Output sets differ"}
    rows = []
    from pysd_explore_config import ALL_INPUTS
    discrete = {i.name for i in ALL_INPUTS if i.binary or i.choice_labels}
    for name, a in reference.items():
        b = candidate[name]
        if a.shape != b.shape or a.shape[0] != len(YEARS) or not (np.isfinite(a).all() and np.isfinite(b).all()):
            rows.append({"variable": name, "pass": False, "reason": "Invalid shape or nonfinite values"})
            continue
        error = np.abs(a-b)
        scale = np.maximum(1., np.max(np.abs(a), axis=0))
        limit = np.zeros_like(a) if exact or name.strip('"') in discrete else 1e-10*scale + 1e-8*np.abs(a)
        failed = error > limit
        row = {"variable": name, "pass": not bool(failed.any()), "cells": a.size,
               "failures": int(failed.sum()), "max_abs": float(error.max())}
        if failed.any():
            index = tuple(np.argwhere(failed)[0])
            spec = next(v for v in export if v["name"] == name)
            row.update(year=YEARS[index[0]], coordinates={d: spec["coords"][d][i] for d, i in zip(spec["dims"], index[1:])},
                       python=float(a[index]), julia=float(b[index]), tolerance=float(limit[index]))
        rows.append(row)
    return {"pass": bool(rows) and all(r["pass"] for r in rows), "rows": rows}


def energy(arrays):
    request = np.maximum(arrays["Hourly available supply by Supplier"], 0.)
    allocated = arrays["Electricity dispatched"]
    available = arrays["Hourly demand and PHS"]
    target = np.minimum(request.sum(axis=-1), available)
    error = abs(allocated.sum(axis=-1)-target)
    tolerance = 1e-10*np.maximum(1., abs(target).max(axis=0)) + 1e-8*abs(target)
    bad = (error > tolerance) | np.any((allocated < 0) | (allocated > request), axis=-1) | (available < 0)
    return {"pass": not bool(bad.any()), "failures": int(bad.sum()), "max_abs": float(error.max())}


def warning_review(messages, translation, variables):
    def interpolation_key(message):
        if "Data value missing or non-valid" not in message or "filled with the interpolation method" not in message:
            return None
        filename = re.search(r"File name:\s*'([^']+)'", message)
        cell = re.search(r"Reference cell:\s*'([^']+)'", message)
        if filename and cell:
            return (message.splitlines()[0].removeprefix("_ext_data_"), Path(filename[1]).name, cell[1])
    known = {interpolation_key(w["message"]) for w in messages} - {None}
    names = {v["python_name"] for v in variables.values()}
    blocking = []
    for warning in messages:
        message = warning["message"]
        acceptable = (interpolation_key(message) is not None or message == "Replacing a variable by a constant value."
                      or message == "chardet.universaldetector is deprecated, import UniversalDetector from chardet or chardet.detector instead"
                      or (message.startswith("_ext_data_") and message.splitlines()[0].removeprefix("_ext_data_") in names
                          and message.endswith("extrapolating data above the maximum value of the time")))
        if not acceptable:
            blocking.append(warning)
    blocking.extend(w for w in translation if interpolation_key(w["message"]) not in known)
    return {"pass": not blocking, "blocking": blocking, "python_count": len(messages), "translation_count": len(translation)}


def initialize(directory, affinity):
    global PYTHON, JULIA, TARGET
    if affinity is not None:
        os.sched_setaffinity(0, {affinity.get()})
    from .python_backend import PythonBackend
    from .runtime import JuliaBackend
    TARGET = Path(directory)
    JULIA = JuliaBackend(timeout=900)
    PYTHON = PythonBackend()
    for spec in JULIA.export:
        dims = PYTHON.variables[spec["name"]].get("subscripts", [])
        if dims != spec["dims"] or any(PYTHON.dimensions[d] != spec["coords"][d] for d in dims):
            raise ValueError("Python/Julia schema mismatch")


def check(job):
    name, params = job
    target = TARGET / name
    started = time.perf_counter()
    report = {"scenario": params, "pass": False}
    try:
        a = PYTHON.run_arrays(params)
        b = JULIA.run_arrays(params)
        result = compare(a, b, JULIA.export)
        from .physical import check as physical_check
        report.update(comparison=result, python_energy=energy(a), julia_energy=energy(b),
                      python_physical=physical_check(a), julia_physical=physical_check(b),
                      python_timing=PYTHON.last_timing, julia_timing=JULIA.last_timing)
        report["warnings"] = warning_review(PYTHON.warnings, read(JULIA.directory / "warnings.json"), PYTHON.variables)
        report["pass"] = all(report[k]["pass"] for k in ["comparison", "python_energy", "julia_energy", "python_physical", "julia_physical", "warnings"])
        if name == "base" or not report["pass"]:
            target.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(target / "python.npz", **a)
            np.savez_compressed(target / "julia.npz", **b)
    except Exception:
        report["error"] = traceback.format_exc()
    report["elapsed_seconds"] = time.perf_counter()-started
    dump(target / "report.json", report)
    dump(target / "warnings.json", PYTHON.warnings)
    print(name, "PASS" if report["pass"] else "FAIL", round(report["elapsed_seconds"], 2), flush=True)
    return name, report["pass"]


def repeat_checks(directory):
    from .python_backend import PythonBackend
    from .runtime import JuliaBackend
    selected = cases()
    results = {}
    for kind, factory in [("python", PythonBackend), ("julia", JuliaBackend)]:
        engine = factory()
        try:
            first = engine.run_arrays(selected["base"])
            high = engine.run_arrays(selected["high"])
            high_compilation = engine.last_timing.get("compilation_seconds", 0)
            repeat = engine.run_arrays(selected["base"])
            result = {"base_high_base_exact": all(np.array_equal(first[n], repeat[n]) for n in first)}
            if kind == "julia":
                result["warm_no_compilation"] = high_compilation == 0 and engine.last_timing["compilation_seconds"] == 0
                with concurrent.futures.ThreadPoolExecutor(2) as pool:
                    a = pool.submit(engine.run_arrays, selected["base"])
                    b = pool.submit(engine.run_arrays, selected["high"])
                    result["concurrent_isolation"] = (all(np.array_equal(first[n], a.result()[n]) for n in first)
                                                      and all(np.array_equal(high[n], b.result()[n]) for n in high))
                engine.process.kill()
                engine.process.wait()
                recovered = engine.run_arrays(selected["base"])
                result["crash_recovery_exact"] = all(np.array_equal(first[n], recovered[n]) for n in first)
                engine.close()
                fresh = factory()
                try:
                    other = fresh.run_arrays(selected["base"])
                    result["fresh_exact"] = all(np.array_equal(first[n], other[n]) for n in first)
                finally:
                    fresh.close()
            else:
                with np.load(Path(directory) / "base/python.npz") as previous:
                    result["fresh_process_exact"] = set(previous.files) == set(first) and all(np.array_equal(previous[n], first[n]) for n in first)
                from sure_pysd import OUTPUTS
                app = PythonBackend(outputs=OUTPUTS)
                shared = app.run_arrays(selected["base"])
                result["app_pruning_exact"] = all(np.array_equal(first[n], shared[n]) for n in shared)
                app.close()
            results[kind] = result
        finally:
            engine.close()
    dump(Path(directory) / "repeats.json", {"pass": all(all(r.values()) for r in results.values()), "results": results})


def certify(directory, targeted):
    directory = Path(directory)
    stamp = read(directory / "manifest.json")
    expected = cases()
    if stamp["cases"] != expected or stamp["build"] != digest(ROOT / "sure_julia/generated/build.json"):
        raise ValueError("Validation does not cover the current full model/scenario contract")
    small = read(Path(targeted) / "summary.json")
    current_patches = {p.name: digest(p) for p in (ROOT / "sure_julia/translator").glob("*.py")}
    if not small["pass"] or small["production_patches"] != current_patches:
        raise ValueError("Targeted tests belong to different translator code")
    repeat = read(directory / "repeats.json")
    required = {"python": {"base_high_base_exact", "fresh_process_exact", "app_pruning_exact"},
                "julia": {"base_high_base_exact", "warm_no_compilation", "concurrent_isolation", "crash_recovery_exact", "fresh_exact"}}
    if not repeat["pass"] or any(set(repeat["results"][engine]) != checks or
                                not all(repeat["results"][engine].values()) for engine, checks in required.items()):
        raise ValueError("State isolation checks failed")
    dump(directory / "targeted.json", small)
    evidence = {name: digest(directory / name) for name in ("manifest.json", "repeats.json", "targeted.json")}
    results = {}
    for name, params in expected.items():
        report = read(directory / name / "report.json")
        if report["scenario"] != params or not report["pass"]:
            raise ValueError(f"Unvalidated scenario: {name}")
        for filename in ["report.json", "warnings.json"]:
            evidence[f"{name}/{filename}"] = digest(directory / name / filename)
        results[name] = True
    dump(directory / "certificate.json", {"pass": True, "complete_suite": True, "cases": results, "build": stamp["build"],
         "targeted_sha256": digest(Path(targeted) / "summary.json"), "evidence": evidence, "identity": identity(stamp)})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--cases", nargs="+")
    parser.add_argument("--targeted", type=Path)
    parser.add_argument("--repeats", action="store_true")
    parser.add_argument("--certify", action="store_true")
    args = parser.parse_args()
    if args.certify:
        certify(args.directory, args.targeted)
        return
    if args.repeats:
        repeat_checks(args.directory)
        return
    all_cases = cases()
    selected = {n: all_cases[n] for n in args.cases} if args.cases else all_cases
    stamp = {"build": digest(ROOT / "sure_julia/generated/build.json"), "cases": selected,
             "samples": digest(ROOT / "precomputed/exploratory/uncertainty_samples.parquet")}
    args.directory.mkdir(parents=True, exist_ok=True)
    dump(args.directory / "summary.json", {"pass": False, "complete_suite": False, "status": "running"})
    (args.directory / "certificate.json").unlink(missing_ok=True)
    dump(args.directory / "manifest.json", stamp)
    if args.workers == 1:
        initialize(args.directory, None)
        results = dict(check(job) for job in selected.items())
    else:
        context = multiprocessing.get_context("spawn")
        affinity = context.Queue()
        for cpu in sorted(os.sched_getaffinity(0))[:args.workers]:
            affinity.put(cpu)
        with concurrent.futures.ProcessPoolExecutor(args.workers, mp_context=context, initializer=initialize,
                                                    initargs=(str(args.directory), affinity)) as pool:
            results = dict(pool.map(check, selected.items()))
    targeted = read(args.targeted / "summary.json") if args.targeted else {"pass": False}
    if digest(ROOT / "sure_julia/generated/build.json") != stamp["build"]:
        raise ValueError("Build changed during validation")
    complete = set(selected) == set(all_cases) and targeted["pass"]
    dump(args.directory / "summary.json", {"pass": all(results.values()), "complete_suite": complete, "targeted": targeted,
                                           "cases": results, "identity": identity(stamp)})
    if not all(results.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
