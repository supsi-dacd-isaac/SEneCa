"""Compare every supplied EMS Python scenario with the translated Julia model.

Read-only with respect to the five received Parquets. Reports are resumable only
with identical model, data, parameters and validation code. No release or deploy.
"""
import argparse
import concurrent.futures
import hashlib
import multiprocessing
from pathlib import Path
import time
import traceback

import numpy as np
import pandas as pd

from .common import ROOT, YEARS, MODEL_REVISION, MODEL_VARIANT, digest, dump, read, model_sources
from .python_batch import SECTIONS, DESTINATIONS, jobs
from .batch import configs, gmd
from .runtime import JuliaBackend, frame_from_arrays


def verify_sources():
    received = read(ROOT / "provenance/sections.json")
    if (received["backend"], received["model_variant"], received["model_revision"]) != (
            "python", MODEL_VARIANT, MODEL_REVISION):
        raise ValueError("The received stores belong to a different model/backend")
    checked = {}
    audit_only = {"sure_julia/pv_budget.py", "sure_julia/pv-budget.json"}
    if {n.replace("\\", "/") for n in received["sources"]} != set(model_sources()):
        raise ValueError("Incomplete received model/input provenance")
    for name, expected in received["sources"].items():
        name = name.replace("\\", "/")
        # These two files describe the audit, not the equations or input data;
        # their Windows paths have been made portable in this checkout.
        if name in audit_only:
            continue
        path = ROOT / name
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() == expected:
            checked[name] = "identical bytes"
        elif path.suffix in {".py", ".json", ".csv"} and hashlib.sha256(
                data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")).hexdigest() == expected:
            checked[name] = "identical content; received hash uses CRLF"
        else:
            raise ValueError(f"Model/input differs from the received Python stores: {name}")
    return checked


def compare_values(reference, candidate):
    if reference.shape != candidate.shape or not (
            np.isfinite(reference).all() and np.isfinite(candidate).all()):
        return {"pass": False, "reason": "Shape mismatch or nonfinite values"}
    error = abs(candidate - reference)
    tolerance = 1e-10 * np.maximum(1., abs(reference).max(axis=0)) + 1e-8 * abs(reference)
    failed = error > tolerance
    result = {"pass": not bool(failed.any()), "exact": bool(np.array_equal(reference, candidate)),
              "cells": int(reference.size), "failures": int(failed.sum()),
              "max_abs": float(error.max()), "max_tolerance_fraction": float((error / tolerance).max())}
    if failed.any():
        index = tuple(np.argwhere(failed)[0])
        result.update(first_index=[int(i) for i in index], python=float(reference[index]),
                      julia=float(candidate[index]), tolerance=float(tolerance[index]))
    return result


def initialize(directory):
    global ENGINE, EXPORT, CONFIGS, STORES, INDICES, TARGET
    TARGET = Path(directory)
    ENGINE = JuliaBackend(timeout=900)
    EXPORT = {item["name"]: item for item in ENGINE.export}
    CONFIGS, STORES, INDICES = configs(), {}, {}
    for section, filename in DESTINATIONS.items():
        frame = STORES[section] = pd.read_parquet(ROOT / "precomputed" / filename)
        cfg = CONFIGS[section.removesuffix("_gmd")]
        INDICES[section] = frame.groupby(cfg.INPUT_ORDER, sort=False).indices


def reference_rows(section, inputs):
    cfg = CONFIGS[section.removesuffix("_gmd")]
    key = tuple(inputs[n] for n in cfg.INPUT_ORDER)
    if key not in INDICES[section]:
        raise ValueError(f"Missing received scenario: {section}/{inputs}")
    return STORES[section].iloc[INDICES[section][key]]


def check(job):
    started = time.perf_counter()
    report = {"pass": False, "parameters": job["parameters"], "destinations": []}
    try:
        arrays = ENGINE.run_arrays(job["parameters"], job["outputs"])
        for destination in job["destinations"]:
            section, inputs = destination["section"], destination["inputs"]
            cfg = CONFIGS[section]
            candidate = frame_from_arrays({n: arrays[n] for n in cfg.OUTPUT_BASES},
                                          [EXPORT[n] for n in cfg.OUTPUT_BASES])
            reference = reference_rows(section, inputs).sort_values("Time").set_index("Time")
            if list(reference.index) != YEARS or set(reference) != set(candidate) | set(cfg.INPUT_ORDER):
                raise ValueError(f"Invalid received years/columns: {section}")
            values = compare_values(reference[candidate.columns].to_numpy(), candidate.to_numpy())
            entry = {**destination, "trajectory": values}
            if not values["pass"] and "first_index" in values:
                row, col = values["first_index"]
                values.update(year=YEARS[row], variable=str(candidate.columns[col]))
            if getattr(cfg, "GMD_SPEC", None):
                audit = []
                derived = gmd(arrays, cfg.GMD_SPEC, EXPORT, audit)
                supplied = reference_rows(section + "_gmd", inputs)
                if len(supplied) != 1 or supplied["year"].iloc[0] != 2050:
                    raise ValueError(f"Invalid received GMD row: {section}")
                names = list(derived)
                entry["gmd"] = compare_values(supplied[names].to_numpy(),
                                               np.array([[derived[n] for n in names]]))
                entry["gmd_weight_audit"] = audit
            report["destinations"].append(entry)
        report.update(physical=ENGINE.last_physical, timing=ENGINE.last_timing)
        report["pass"] = report["physical"]["pass"] and all(
            row["trajectory"]["pass"] and row.get("gmd", {"pass": True})["pass"]
            for row in report["destinations"])
    except Exception:
        report["error"] = traceback.format_exc()
    report["seconds"] = time.perf_counter() - started
    dump(TARGET / "cases" / (job["id"] + ".json"), report)
    print(job["id"][:12], "PASS" if report["pass"] else "FAIL", round(report["seconds"], 2), flush=True)
    return job["id"], report["pass"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--limit", type=int, help="Pilot only; never produces a complete-grid result")
    args = parser.parse_args()
    if args.workers < 1 or args.limit is not None and args.limit < 1:
        parser.error("workers and limit must be positive")
    source_check = verify_sources()
    planned = jobs()
    selected = planned[:args.limit] if args.limit else planned
    stamp = {"model_revision": MODEL_REVISION, "build": digest(ROOT / "sure_julia/generated/build.json"),
             "runner": digest(Path(__file__)), "jobs": selected,
             "data": {name: digest(ROOT / "precomputed" / name) for name in DESTINATIONS.values()},
             "provenance": digest(ROOT / "provenance/sections.json"), "sources": source_check,
             "tolerance": "abs(Julia-Python) <= 1e-10*max(1,max_time(abs(Python))) + 1e-8*abs(Python)"}
    args.directory.mkdir(parents=True, exist_ok=True)
    manifest = args.directory / "manifest.json"
    if manifest.exists() and read(manifest) != stamp:
        raise ValueError("Model/data/runner changed: use a new validation directory")
    dump(manifest, stamp)
    pending = []
    for job in selected:
        path = args.directory / "cases" / (job["id"] + ".json")
        old = read(path) if path.exists() else {}
        if not (old.get("pass") and old.get("parameters") == job["parameters"]):
            pending.append(job)
    dump(args.directory / "summary.json", {"pass": False, "status": "running", "remaining": len(pending)})
    if pending:
        if args.workers == 1:
            initialize(args.directory)
            try:
                for job in pending:
                    check(job)
            finally:
                ENGINE.close()
        else:
            with concurrent.futures.ProcessPoolExecutor(args.workers,
                    mp_context=multiprocessing.get_context("spawn"), initializer=initialize,
                    initargs=(str(args.directory),)) as pool:
                list(pool.map(check, pending))
    if (digest(ROOT / "sure_julia/generated/build.json") != stamp["build"]
            or digest(Path(__file__)) != stamp["runner"]
            or any(digest(ROOT / "precomputed" / n) != value for n, value in stamp["data"].items())
            or verify_sources() != stamp["sources"]):
        raise ValueError("Build, runner or received data changed during validation")
    reports = [read(args.directory / "cases" / (job["id"] + ".json")) for job in selected]
    values = [entry[k] for report in reports for entry in report["destinations"]
              for k in ("trajectory", "gmd") if k in entry]
    passed = all(r["pass"] for r in reports)
    summary = {"pass": passed, "complete_grid": len(selected) == len(planned),
               "scenarios": len(selected), "configurations": sum(len(j["destinations"]) for j in selected),
               "failed": [j["id"] for j, r in zip(selected, reports) if not r["pass"]],
               "cells": sum(v.get("cells", 0) for v in values),
               "max_tolerance_fraction": max((v.get("max_tolerance_fraction", 0.) for v in values), default=0.),
               "all_bitwise_equal": bool(values) and all(v.get("exact", False) for v in values),
               "manifest_sha256": digest(manifest)}
    dump(args.directory / "summary.json", summary)
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
