from __future__ import annotations

import json
import statistics
import time
import numpy as np

from .common import ROOT, RUNTIME, CONFIG, YEARS, read, dump, digest, run_logged, experiment_hashes, evidence_hashes
from .inventory import columns_for
from .results import compare


def julia_command():
    return [RUNTIME / "julia-1.10.12/bin/julia", "--startup-file=no", f"--project={CONFIG}"]


def convert(directory, case, raw, destination, *, app_outputs=False):
    manifest = read(directory / "manifest.json")
    exports = read(directory / "julia" / case / ("export-app.json" if app_outputs else "export.json"))
    timing = read(raw / "timing.json")
    if timing["years"] != YEARS or timing["byte_order"] != "little":
        raise ValueError("Incomplete or incompatible Julia output")
    metadata, arrays = {"years": timing["years"], "variables": {}}, {}
    for i, item in enumerate(exports):
        name = item["name"]
        key = f"v{i:04d}"
        columns = columns_for(name, manifest)
        array = np.fromfile(raw / f"{key}.bin", dtype="<f8")
        if array.size != len(YEARS)*len(columns):
            raise ValueError(f"Incomplete Julia data: {name}")
        arrays[key] = array.reshape(len(YEARS), len(columns))
        metadata["variables"][name] = {"key": key, "columns": columns,
                                     "dims": item["dims"], "coords": item["coords"],
                                     "discrete": name in manifest.get("discrete", [])}
    destination.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(destination.with_suffix(".npz"), **arrays)
    metadata["sha256"] = digest(destination.with_suffix(".npz"))
    dump(destination.with_suffix(".json"), metadata)


def run_julia(directory, case, raw, iterations=1, *, app_outputs=False):
    target = directory / "julia" / case
    translation = read(target / "translation.json")
    if not translation["pass"] or translation["sha256"] != digest(target / translation["model"]):
        raise ValueError("Unverified or modified Julia translation")
    if translation["params_sha256"] != digest(directory / "reference/app" / f"{case}.params.json"):
        raise ValueError("Applied Python parameters changed since translation")
    if translation["experiment"] != experiment_hashes():
        raise ValueError("Experiment changed since translation; retranslate before validating")
    if any(digest(target / name) != sha for name, sha in translation["generated_hashes"].items()):
        raise ValueError("Generated model, data or export metadata changed")
    run_logged([*julia_command(), CONFIG / "run_model.jl", target / translation["model"],
                target / ("export-app.json" if app_outputs else "export.json"), raw, iterations], raw.with_suffix(".log"))
    if "Warning" in raw.with_suffix(".log").read_text():
        raise RuntimeError(f"Julia runtime warning requires review: {raw.with_suffix('.log')}")


def validate(directory, cases):
    dump(directory / "validation.json", {"pass": False, "full_suite": False, "status": "incomplete"})
    manifest = read(directory / "manifest.json")
    fixtures = read(directory / "fixtures.json")
    if not fixtures["pass"] or fixtures["experiment"] != experiment_hashes():
        raise ValueError("Semantic fixtures must pass with the current experiment")
    reports = {}
    if not {"base", "high"} <= set(cases):
        raise ValueError("Validation requires base and high for the process-state checks")
    if not read(directory / "checks/reference_determinism.json")["pass"]:
        raise ValueError("Reference determinism must pass before Julia validation")
    for suffix in ("fresh_a_00_base", "fresh_b_00_base", "sequence_00_base", "sequence_02_base"):
        if not compare(directory / "reference/app/base", directory / "reference/app" / suffix, exact=True)["pass"]:
            raise ValueError("Reference repeatability evidence changed")
    for case in cases:
        baseline = read(directory / "checks" / f"reference_{case}.json")
        if not baseline["pass"]:
            raise ValueError(f"Invalid reference: {case}")
        # Recheck the actual files instead of trusting a possibly stale check JSON.
        if not compare(directory / "reference/app" / case,
                       directory / "reference/diagnostic" / case, outputs=manifest["outputs"])["pass"]:
            raise ValueError(f"Reference changed or diagnostic mismatch: {case}")
        raw = directory / "raw" / case
        run_julia(directory, case, raw)
        candidate = directory / "candidate" / case
        convert(directory, case, raw, candidate)
        report = compare(directory / "reference/diagnostic" / case, candidate)
        dump(directory / "checks" / f"julia_{case}.json", report)
        reports[case] = report
    # Two independent starts and a shared-process base/high/base sequence.
    for label in ("fresh_a", "fresh_b"):
        raw = directory / "raw" / label
        run_julia(directory, "base", raw)
        convert(directory, "base", raw, directory / "candidate" / label)
        reports[label] = compare(directory / "candidate/base", directory / "candidate" / label, exact=True)
    sequence = directory / "raw/sequence"
    sequence.mkdir(parents=True, exist_ok=True)
    commands = [f'include({json.dumps(str(CONFIG / "run_model.jl"))})', 'models = Dict{String,Module}()']
    for index, case in enumerate(("base", "high", "base")):
        target = directory / "julia" / case
        tr = read(target / "translation.json")
        commands.append("execute(" + ", ".join(json.dumps(str(x)) for x in
                         (target / tr["model"], target / "export.json", sequence / str(index))) + "; cache=models)")
    driver = sequence / "driver.jl"
    driver.write_text("\n".join(commands)+"\n")
    run_logged([*julia_command(), driver], sequence / "run.log")
    for index in (0, 2):
        destination = directory / "candidate" / f"sequence_{index}_base"
        convert(directory, "base", sequence / str(index), destination)
        reports[f"sequence_{index}"] = compare(directory / "candidate/base", destination, exact=True)
    complete = set(cases) == set(manifest["scenarios"])
    passed = all(r["pass"] for r in reports.values())
    result = {"pass": passed and complete, "selected_pass": passed, "full_suite": complete,
              "experiment": experiment_hashes(), "evidence": evidence_hashes(directory),
              "cases": {k: r["pass"] for k, r in reports.items()},
              "determinism": {k: r for k, r in reports.items() if k not in cases}}
    dump(directory / "validation.json", result)
    if not passed:
        raise RuntimeError("Numerical validation failed; inspect checks/julia_*.json")


def check_benchmark_gate(directory):
    validation = read(directory / "validation.json")
    if not validation["pass"] or not validation["full_suite"] or validation["experiment"] != experiment_hashes():
        raise RuntimeError("Benchmark requires complete, current numerical validation")
    if validation.get("evidence") != evidence_hashes(directory):
        raise RuntimeError("Validation evidence changed; rerun validation before benchmarking")
    ref_determinism = read(directory / "checks/reference_determinism.json")
    if not ref_determinism["pass"]:
        raise RuntimeError("Reference determinism must pass")


def summarize_timings(rows):
    groups = {}
    for row in rows:
        key = (row["engine"], row["scenario"], row["kind"])
        groups.setdefault(key, []).append(row)
    result = []
    for (engine, scenario, kind), items in groups.items():
        metrics = {}
        for key in sorted(set().union(*(r.keys() for r in items))):
            if key.endswith("_seconds") or key == "max_rss_bytes":
                values = [r[key] for r in items if key in r]
                metrics[key] = {"values": values, "median": statistics.median(values),
                                "min": min(values), "max": max(values)}
        result.append({"engine": engine, "scenario": scenario, "kind": kind, "metrics": metrics})
    return result


def benchmark(directory):
    check_benchmark_gate(directory)
    rows = []
    script = ROOT / "scripts/benchmark_julia.py"
    def check_result(case, candidate):
        result = compare(directory / "reference/app" / case, candidate)
        if not result["pass"]:
            dump(directory / "benchmark-failure.json", result)
            raise RuntimeError("A timed execution changed numerical results; benchmark invalid")
    for case in ("base", "mid", "high"):
        for engine in ("python", "julia"):
            for repeat in range(3):
                start = time.perf_counter()
                if engine == "python":
                    label = f"bench_cold_{repeat}"
                    run_logged([RUNTIME / "python-reference/bin/python", script, "_reference", "--run-dir", directory,
                                "--scenarios", case, "--label", label], directory / "logs" / f"{engine}_{case}_{label}.log")
                    elapsed = time.perf_counter()-start
                    timing = read(directory / "reference/app" / f"{label}_00_{case}.timing.json")
                    candidate = directory / "reference/app" / f"{label}_00_{case}"
                else:
                    raw = directory / "benchmark" / case / f"cold_{repeat}"
                    run_julia(directory, case, raw, app_outputs=True)
                    elapsed = time.perf_counter()-start
                    timing = read(raw / "timing.json")
                    candidate = directory / "benchmark/converted" / f"{case}_cold_{repeat}"
                    convert(directory, case, raw, candidate, app_outputs=True)
                rows.append({"engine": engine, "scenario": case, "kind": "fresh_process",
                             "wall_seconds": elapsed, **timing})
                check_result(case, candidate)
            if engine == "python":
                run_logged([RUNTIME / "python-reference/bin/python", script, "_reference", "--run-dir", directory,
                            "--scenarios", *([case]*6), "--label", "bench_warm"], directory / "logs" / f"warm_{case}.log")
                timings = [read(directory / "reference/app" / f"bench_warm_{i:02d}_{case}.timing.json") for i in range(1,6)]
                for i in range(6):
                    check_result(case, directory / "reference/app" / f"bench_warm_{i:02d}_{case}")
            else:
                raw = directory / "benchmark" / case / "warm"
                run_julia(directory, case, raw, 6, app_outputs=True)
                timings = [read(raw / str(i) / "timing.json") for i in range(2,7)]
                for i in range(1,7):
                    candidate = directory / "benchmark/converted" / f"{case}_warm_{i}"
                    convert(directory, case, raw / str(i), candidate, app_outputs=True)
                    check_result(case, candidate)
            rows.extend({"engine": engine, "scenario": case, "kind": "warm_same_scenario", **t} for t in timings)
    dump(directory / "benchmark.json", {"measurements": rows, "summary": summarize_timings(rows),
         "note": "Fresh process uses installed/precompiled packages; warm reuses the same compiled scenario. Python simulation includes capture; Julia first solve includes JIT."})
