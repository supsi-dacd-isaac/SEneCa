#!/usr/bin/env python3
"""Compare certified Julia SURE with the existing native Vensim archives."""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
import sys
import warnings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.julia_repro.common import YEARS, digest, dump, read, run_logged
from scripts.julia_repro.execution import check_benchmark_gate, julia_command
from scripts.julia_repro.comparison import compare as compare_python
from scripts.julia_repro.results import save_frame
from scripts.julia_parametric.model import resolve_name
from scripts.benchmark_julia_parametric import implementation as parametric_implementation, runtime_signature
from scripts.verify_julia_benchmark_timing import prevent_idle_sleep
from scripts.vensim_comparison.core import prepare, convert_raw, comparison, reconstruct_snapshot


def implementation():
    paths = [Path(__file__), *sorted((ROOT / "scripts/vensim_comparison").glob("*.py")),
             *sorted((ROOT / "tests").glob("test_vensim_comparison*.py"))]
    return {str(path): digest(path) for path in paths}


def verify(reference, parametric, target):
    inventory = read(target / "inventory.json")
    for path, sha in inventory["files"].items():
        if digest(path) != sha:
            raise ValueError(f"Comparison source changed: {path}")
    for path, sha in inventory["references"].items():
        if digest(target / path) != sha:
            raise ValueError(f"Native snapshot changed: {path}")
    certificate = read(parametric / "model/model.json")
    validation = read(parametric / "validate/report.json")
    if (not validation["pass"] or runtime_signature(validation["implementation"]) != runtime_signature(parametric_implementation())
            or validation["model_sha256"] != inventory["model_sha256"]):
        raise ValueError("Julia runtime no longer matches its numerical validation")
    for name, sha in certificate["artifacts"].items():
        if digest(parametric / "model" / name) != sha:
            raise ValueError(f"Julia model/data changed: {name}")
    if read(target / "jobs.json") != inventory["jobs"]:
        raise ValueError("Scenario jobs changed")
    return inventory


def execute(reference, parametric, target):
    check_benchmark_gate(reference)
    inventory = verify(reference, parametric, target)
    signature = implementation()
    if (target / "raw").exists():
        raise ValueError("Preserve previous raw runs; choose a new directory")
    context = {"implementation": signature, "inventory_sha256": digest(target / "inventory.json"),
               "export_sha256": digest(target / "export.json"), "model_sha256": inventory["model_sha256"]}
    dump(target / "execution.json", {"completed": False, **context})
    model = parametric / "model" / read(parametric / "model/model.json")["model"]
    with prevent_idle_sleep(target / "caffeinate.log"):
        run_logged([*julia_command(), ROOT / "benchmarks/julia-parametric/worker.jl", model,
                    target / "export.json", target / "jobs.json", target / "raw"], target / "run.log")
    if "warning" in (target / "run.log").read_text().lower():
        raise ValueError("Unreviewed Julia warning")
    export, manifest = read(target / "export.json"), read(reference / "manifest.json")
    for job in inventory["jobs"]:
        timing = read(target / "raw" / job["id"] / "timing.json")
        if timing["parameters"] != job["parameters"]:
            raise ValueError("Julia applied different parameters")
        convert_raw(target / "raw" / job["id"], target / "candidate" / job["id"], export, manifest)
    verify(reference, parametric, target)
    if signature != implementation():
        raise ValueError("Comparison implementation changed during execution")
    artifacts = {str(p.relative_to(target)): digest(p) for folder in ("raw", "candidate")
                 for p in sorted((target / folder).rglob("*")) if p.is_file()}
    dump(target / "execution.json", {"completed": True, **context, "artifacts": artifacts})
    summarize(reference, parametric, target)


def verify_execution(target, inventory):
    execution = read(target / "execution.json")
    if not execution["completed"] or execution["model_sha256"] != inventory["model_sha256"]:
        raise ValueError("No complete Julia execution")
    if (execution["inventory_sha256"] != digest(target / "inventory.json")
            or execution["export_sha256"] != digest(target / "export.json")):
        raise ValueError("Execution inputs changed")
    for path, sha in execution["artifacts"].items():
        if digest(target / path) != sha:
            raise ValueError(f"Julia evidence changed: {path}")


def summarize(reference, parametric, target):
    inventory = verify(reference, parametric, target)
    verify_execution(target, inventory)
    result = {"completed": True, "native_equivalence_certified": False,
              "parameter_provenance_complete": False, "execution_sha256": digest(target / "execution.json"),
              "comparison_implementation": implementation(), "reconstructions": {}, "cases": []}
    for case in inventory["cases"]:
        compared = comparison(target / "vensim" / case["id"], target / "candidate" / case["job"])
        raw_pass = compared["pass"]
        if case["section"] == "elettricita":
            if case["id"] not in result["reconstructions"]:
                result["reconstructions"][case["id"]] = reconstruct_snapshot(
                    target / "vensim" / case["id"], target / "reconstructed" / case["id"], ROOT / "Vensim/SURE.mdl")
            reconstructed = comparison(target / "reconstructed" / case["id"], target / "candidate" / case["job"])
            dump(target / "comparisons-raw" / f"{case['id']}_{case['profile']}.json", compared)
            compared = {**reconstructed, "reconstruction": result["reconstructions"][case["id"]],
                        "raw_reference_pass": raw_pass}
        filename = f"{case['id']}_{case['profile']}.json"
        dump(target / "comparisons" / filename, compared)
        rows = compared["rows"]
        result["cases"].append({**case, "raw_reference_pass": raw_pass, "uses_reconstruction": "reconstruction" in compared,
            "numerical_pass": compared["pass"], "variables": len(rows),
            "variables_pass": sum(row["pass"] for row in rows),
            "cells": sum(row.get("cells", 0) for row in rows),
            "failures": sum(row.get("failures", 0) for row in rows),
            "max_fraction_variable_scale": max((row.get("max_fraction_variable_scale", 0) for row in rows), default=None),
            "earliest_divergence": min((row["first_divergence"]["year"] for row in rows if "first_divergence" in row), default=None)})
        print(f"{case['id']} {case['profile']}: {result['cases'][-1]['variables_pass']}/{len(rows)} near-numerical matches", flush=True)
    result["numerical_pass"] = all(c["numerical_pass"] for c in result["cases"])
    result["comparisons"] = {p.name: digest(p) for p in sorted((target / "comparisons").glob("*.json"))}
    result["derived_evidence"] = {str(p.relative_to(target)): digest(p) for folder in ("comparisons-raw", "reconstructed")
                                  for p in sorted((target / folder).glob("*")) if p.is_file()}
    dump(target / "report.json", result)
    return result


def oracle_destination(target, name):
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", name):
        raise ValueError("Invalid oracle directory name")
    return target / name


def python_oracle(reference, parametric, target, job_ids=None, oracle_name="python"):
    if os.environ.get("PYTHONHASHSEED") != "0" or sys.flags.hash_randomization != 0:
        raise RuntimeError("Start with PYTHONHASHSEED=0")
    import sure_paths
    sure_paths.set_variant("v3")
    import sure_pysd as sp
    inventory = verify(reference, parametric, target)
    jobs = {c["job"]: c for c in inventory["cases"]
            if (("base" in c["labels"] and c["profile"] == "mdl_defaults") if job_ids is None else c["job"] in job_ids)}
    if not jobs or (job_ids is not None and set(jobs) != set(job_ids)):
        raise ValueError("Unknown or empty oracle job selection")
    destination = oracle_destination(target, oracle_name)
    destination.mkdir(exist_ok=False)
    known = read(reference / "reference/app/base.warnings.json")
    report = {"completed": False, "implementation": implementation(), "jobs": {}, "warnings": {}}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        model = sp.load_model(prune=True)
    report["warnings"]["load"] = [str(w.message) for w in caught]
    if any(str(w.message) not in known for w in caught):
        raise ValueError("Unknown Python load warning")
    outputs = [e["name"] for e in read(target / "export.json")]
    manifest = read(reference / "manifest.json")
    for job, case in jobs.items():
        params = {resolve_name(name, model._namespace): value for name, value in case["parameters"].items()}
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            frame = sp.run_scenario(model, scenario_inputs=params, return_columns=outputs, timestamps=YEARS)
        report["warnings"][job] = [str(w.message) for w in caught]
        if any(str(w.message) not in known for w in caught):
            raise ValueError("Unknown Python run warning")
        save_frame(destination / job, frame, outputs, manifest)
        dump(destination / f"{job}.params.json", params)
        report["jobs"][job] = {"labels": case["labels"], "section": case["section"]}
        dump(destination / "report.json", report)
        print(f"Python oracle {case['section']}: complete", flush=True)
    verify(reference, parametric, target)
    if report["implementation"] != implementation():
        raise ValueError("Oracle source changed during execution")
    report["completed"] = True
    report["artifacts"] = {p.name: digest(p) for p in sorted(destination.iterdir()) if p.is_file() and p.name != "report.json"}
    dump(destination / "report.json", report)


def triangulate(reference, parametric, target, oracle_name="python"):
    inventory = verify(reference, parametric, target)
    verify_execution(target, inventory)
    destination = oracle_destination(target, oracle_name)
    oracle = read(destination / "report.json")
    if not oracle["completed"] or any(digest(destination / p) != sha for p, sha in oracle["artifacts"].items()):
        raise ValueError("Unverified Python oracle")
    result = {"oracle_sha256": digest(destination / "report.json"), "implementation": implementation(), "jobs": {}}
    for job in oracle["jobs"]:
        comparison_ = compare_python(destination / job, target / "candidate" / job)
        native = {case["id"]: comparison(target / "vensim" / case["id"], destination / job)
                  for case in inventory["cases"] if case["job"] == job and case["profile"] == "mdl_defaults"}
        reconstructed = {}
        for case in inventory["cases"]:
            if case["job"] == job and case["section"] == "elettricita" and case["profile"] == "mdl_defaults":
                reconstruct_snapshot(target / "vensim" / case["id"], target / "reconstructed" / case["id"], ROOT / "Vensim/SURE.mdl")
                reconstructed[case["id"]] = comparison(target / "reconstructed" / case["id"], destination / job)
        result["jobs"][job] = {"python_julia": comparison_, "vensim_python": native,
                               "vensim_python_with_mdl_reconstruction": reconstructed}
    filename = "triangulation.json" if oracle_name == "python" else f"triangulation-{oracle_name}.json"
    dump(target / filename, result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("inventory", "run", "compare", "python", "triangulate"))
    parser.add_argument("--suite", choices=("pilot", "targeted", "full"), default="pilot")
    parser.add_argument("--run-dir", type=Path, default=ROOT / "dist/vensim-comparison/20261012-pilot")
    parser.add_argument("--reference", type=Path, default=ROOT / "dist/julia-repro/20261009-reproducibility")
    parser.add_argument("--parametric", type=Path, default=ROOT / "dist/julia-parametric/20261009")
    parser.add_argument("--python-job", action="append", help="Explicit job id to triangulate; repeat for multiple jobs")
    parser.add_argument("--oracle-name", default="python", help="Separate output directory for additional Python oracle jobs")
    args = parser.parse_args()
    reference, parametric, target = args.reference.resolve(), args.parametric.resolve(), args.run_dir.resolve()
    if args.phase == "inventory":
        prepare(reference, parametric, target, args.suite)
    elif args.phase == "run":
        execute(reference, parametric, target)
    elif args.phase == "python":
        python_oracle(reference, parametric, target, args.python_job, args.oracle_name)
    elif args.phase == "triangulate":
        triangulate(reference, parametric, target, args.oracle_name)
    else:
        summarize(reference, parametric, target)


if __name__ == "__main__":
    main()
