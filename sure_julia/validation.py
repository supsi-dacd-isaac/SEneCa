"""Full-cell comparison and the production scenario acceptance suite."""
import argparse
import concurrent.futures
import itertools
import multiprocessing
import os
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
        report.update(comparison=result, python_energy=energy(a), julia_energy=energy(b),
                      python_timing=PYTHON.last_timing, julia_timing=JULIA.last_timing)
        report["pass"] = result["pass"] and report["python_energy"]["pass"] and report["julia_energy"]["pass"]
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--cases", nargs="+")
    args = parser.parse_args()
    all_cases = cases()
    selected = {n: all_cases[n] for n in args.cases} if args.cases else all_cases
    stamp = {"build": digest(ROOT / "sure_julia/generated/build.json"), "cases": selected,
             "samples": digest(ROOT / "precomputed/exploratory/uncertainty_samples.parquet")}
    args.directory.mkdir(parents=True, exist_ok=True)
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
    dump(args.directory / "summary.json", {"pass": all(results.values()), "cases": results, "identity": identity(stamp)})
    if not all(results.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
