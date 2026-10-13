from __future__ import annotations

import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
import numpy as np

from .common import ROOT, RUNTIME, CONFIG, YEARS, read, dump, digest, run_logged, experiment_hashes, evidence_hashes
from .inventory import columns_for
from .comparison import compare


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


def verify_translation(directory, case):
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
    for policy in ("delay_update_policy", "reduction_policy"):
        if any(digest(directory / name) != sha for name, sha in translation.get(policy, {}).get("evidence", {}).items()):
            raise ValueError(f"Python semantic evidence changed: {policy}")
    return target, translation


def run_julia(directory, case, raw, iterations=1, *, app_outputs=False):
    target, translation = verify_translation(directory, case)
    run_logged([*julia_command(), CONFIG / "run_model.jl", target / translation["model"],
                target / ("export-app.json" if app_outputs else "export.json"), raw, iterations], raw.with_suffix(".log"))
    if "warning" in raw.with_suffix(".log").read_text().lower():
        raise RuntimeError(f"Julia runtime warning requires review: {raw.with_suffix('.log')}")


def validate(directory, cases, *, resume=False, jobs=1):
    if jobs < 1:
        raise ValueError("Validation jobs must be positive")
    cases = list(dict.fromkeys(cases))
    dump(directory / "validation.json", {"pass": False, "full_suite": False, "status": "incomplete"})
    manifest = read(directory / "manifest.json")
    from .reference import reference_ready
    from .common import check_sources
    check_sources(manifest)
    experiment = experiment_hashes()
    def require_current():
        check_sources(manifest)
        if experiment_hashes() != experiment:
            raise RuntimeError("Experiment changed during validation; mixed-version results cannot pass")
    fixtures = read(directory / "fixtures.json")
    if not fixtures["pass"] or fixtures["experiment"] != experiment_hashes():
        raise ValueError("Semantic fixtures must pass with the current experiment")
    reports, bound_contexts, bound_candidates = {}, {}, {}
    if not {"base", "high"} <= set(cases):
        raise ValueError("Validation requires base and high for the process-state checks")
    if not read(directory / "checks/reference_determinism.json")["pass"]:
        raise ValueError("Reference determinism must pass before Julia validation")
    for label in ("fresh_a", "fresh_b"):
        if not reference_ready(directory, manifest, ["base"], label=label, index=0):
            raise ValueError(f"Reference process evidence changed: {label}")
    for index in range(3):
        if not reference_ready(directory, manifest, ["base", "high", "base"], label="sequence", index=index):
            raise ValueError(f"Reference sequence evidence changed: {index}")
    for suffix in ("fresh_a_00_base", "fresh_b_00_base", "sequence_00_base", "sequence_02_base"):
        if not compare(directory / "reference/app/base", directory / "reference/app" / suffix, exact=True)["pass"]:
            raise ValueError("Reference repeatability evidence changed")
    def evaluate_case(case):
        require_current()
        for mode in ("app", "diagnostic"):
            if not reference_ready(directory, manifest, [case], mode=mode):
                raise ValueError(f"Missing or stale reference provenance: {case}/{mode}")
        baseline = read(directory / "checks" / f"reference_{case}.json")
        if not baseline["pass"]:
            raise ValueError(f"Invalid reference: {case}")
        from .packing import validate_real_snapshot
        if not validate_real_snapshot(directory / "reference/diagnostic" / case)["pass"]:
            raise ValueError(f"Reference coordinate packing failed: {case}")
        # Recheck the actual files instead of trusting a possibly stale check JSON.
        if not compare(directory / "reference/app" / case,
                       directory / "reference/diagnostic" / case, outputs=manifest["outputs"])["pass"]:
            raise ValueError(f"Reference changed or diagnostic mismatch: {case}")
        from .energy import check_snapshot
        reference_energy = check_snapshot(directory / "reference/diagnostic" / case)
        dump(directory / "checks" / f"conservation_reference_{case}.json", reference_energy)
        from .reduction_samples import run as check_reduction_samples
        reduction_samples = check_reduction_samples(directory, case=case)
        dump(directory / "checks" / f"reduction_samples_{case}.json", reduction_samples)
        if not reduction_samples["pass"]:
            raise ValueError(f"NumPy reduction kernel differs on real reference inputs: {case}")
        raw = directory / "raw" / case
        candidate = directory / "candidate" / case
        stamp = directory / "checks" / f"julia_{case}.provenance.json"
        target, translation = verify_translation(directory, case)
        context = {"experiment": experiment,
                   "translation": digest(target / "translation.json"),
                   "reference": {str(p.relative_to(directory)): digest(p) for p in
                                 [directory / "reference/diagnostic" / f"{case}{suffix}"
                                  for suffix in (".json", ".npz")]}}
        reusable = False
        if resume and stamp.exists() and candidate.with_suffix(".json").exists() and candidate.with_suffix(".npz").exists():
            saved = read(stamp)
            reusable = (saved.get("context") == context and
                        saved.get("candidate") == {suffix: digest(candidate.with_suffix(suffix))
                                                   for suffix in (".json", ".npz")})
        if not reusable:
            stamp.unlink(missing_ok=True)
            run_julia(directory, case, raw)
            convert(directory, case, raw, candidate)
        require_current()
        report = compare(directory / "reference/diagnostic" / case, candidate)
        candidate_energy = check_snapshot(candidate)
        dump(directory / "checks" / f"conservation_julia_{case}.json", candidate_energy)
        report["conservation"] = {"python": reference_energy, "julia": candidate_energy}
        report["pass"] = report["pass"] and reference_energy["pass"] and candidate_energy["pass"]
        dump(directory / "checks" / f"julia_{case}.json", report)
        candidate_hashes = {suffix: digest(candidate.with_suffix(suffix)) for suffix in (".json", ".npz")}
        dump(stamp, {"context": context, "candidate": candidate_hashes})
        return case, report, context, candidate_hashes

    # Each numerical engine remains single-threaded, in its own process and
    # directory. Only untimed scenario validation may run concurrently.
    with ThreadPoolExecutor(max_workers=jobs) if jobs > 1 else nullcontext() as pool:
        outcomes = pool.map(evaluate_case, cases) if pool else map(evaluate_case, cases)
        for case, report, context, candidate_hashes in outcomes:
            reports[case] = report
            bound_contexts[case] = context
            bound_candidates[case] = candidate_hashes
            dump(directory / "validation.json", {"pass": False, "full_suite": False,
                 "status": "running", "experiment": experiment, "jobs": jobs,
                 "cases": {k: r["pass"] for k, r in reports.items()}})
            print(f"Julia {case}: {'PASS' if report['pass'] else 'FAIL'} ({len(reports)}/{len(cases)})", flush=True)
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
        require_current()
        target, tr = verify_translation(directory, case)
        commands.append("execute(" + ", ".join(json.dumps(str(x)) for x in
                         (target / tr["model"], target / "export.json", sequence / str(index))) + "; cache=models)")
    driver = sequence / "driver.jl"
    driver.write_text("\n".join(commands)+"\n")
    run_logged([*julia_command(), driver], sequence / "run.log")
    if "warning" in (sequence / "run.log").read_text().lower():
        raise RuntimeError("Julia sequence runtime warning requires review")
    for index, case in enumerate(("base", "high", "base")):
        destination = directory / "candidate" / f"sequence_{index}_{case}"
        convert(directory, case, sequence / str(index), destination)
        reports[f"sequence_{index}"] = compare(directory / "candidate" / case, destination, exact=True)
    require_current()
    # Earlier cases may have finished an hour ago. Bind the final acceptance to
    # the exact files that were compared, not whatever is now in the directory.
    for case in cases:
        target, _ = verify_translation(directory, case)
        stamp = read(directory / "checks" / f"julia_{case}.provenance.json")
        candidate = directory / "candidate" / case
        context = bound_contexts[case]
        if (stamp["context"] != context or digest(target / "translation.json") != context["translation"]
            or any(digest(directory / path) != sha for path, sha in context["reference"].items())
            or stamp["candidate"] != bound_candidates[case]
            or bound_candidates[case] != {suffix: digest(candidate.with_suffix(suffix)) for suffix in (".json", ".npz")}):
            raise RuntimeError(f"Validation artifacts changed after comparison: {case}")
        for mode in ("app", "diagnostic"):
            if not reference_ready(directory, manifest, [case], mode=mode):
                raise RuntimeError(f"Reference artifacts changed after comparison: {case}/{mode}")
    complete = set(cases) == set(manifest["scenarios"])
    passed = all(r["pass"] for r in reports.values())
    result = {"pass": passed and complete, "selected_pass": passed, "full_suite": complete,
              "validation_jobs": jobs,
              "experiment": experiment, "evidence": evidence_hashes(directory),
              "cases": {k: r["pass"] for k, r in reports.items()},
              "determinism": {k: r for k, r in reports.items() if k not in cases}}
    dump(directory / "validation.json", result)
    if not passed:
        raise RuntimeError("Numerical validation failed; inspect checks/julia_*.json")


def check_benchmark_gate(directory):
    from .common import check_sources
    check_sources(read(directory / "manifest.json"))
    validation = read(directory / "validation.json")
    if not validation["pass"] or not validation["full_suite"] or validation["experiment"] != experiment_hashes():
        raise RuntimeError("Benchmark requires complete, current numerical validation")
    if validation.get("evidence") != evidence_hashes(directory):
        raise RuntimeError("Validation evidence changed; rerun validation before benchmarking")
    ref_determinism = read(directory / "checks/reference_determinism.json")
    if not ref_determinism["pass"]:
        raise RuntimeError("Reference determinism must pass")
    reference_suite = read(directory / "reference-suite.json")
    if not reference_suite["pass"] or not reference_suite["full_suite"]:
        raise RuntimeError("The complete Python reference suite must pass")


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
    context = {"experiment": experiment_hashes(),
               "validation_sha256": digest(directory / "validation.json")}
    dump(directory / "benchmark.json", {"pass": False, "status": "running", **context})
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
                    timing = read(raw / "timing.json")
                    candidate = directory / "benchmark/converted" / f"{case}_cold_{repeat}"
                    serialization_start = time.perf_counter()
                    convert(directory, case, raw, candidate, app_outputs=True)
                    timing["serialization_seconds"] = time.perf_counter()-serialization_start
                    elapsed = time.perf_counter()-start
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
                all_timings = [read(raw / str(i) / "timing.json") for i in range(1,7)]
                for i in range(1,7):
                    candidate = directory / "benchmark/converted" / f"{case}_warm_{i}"
                    serialization_start = time.perf_counter()
                    convert(directory, case, raw / str(i), candidate, app_outputs=True)
                    all_timings[i-1]["serialization_seconds"] = time.perf_counter()-serialization_start
                    check_result(case, candidate)
                timings = all_timings[1:]
            rows.extend({"engine": engine, "scenario": case, "kind": "warm_same_scenario", **t} for t in timings)
    for row in rows:
        row["simulation_and_serialization_seconds"] = row["simulation_and_capture_seconds"] + row["serialization_seconds"]
    check_benchmark_gate(directory)
    if (experiment_hashes() != context["experiment"] or
            digest(directory / "validation.json") != context["validation_sha256"]):
        raise RuntimeError("Validation changed during benchmarking; timing results cannot pass")
    dump(directory / "benchmark.json", {"pass": True, "status": "complete", **context,
         "measurements": rows, "summary": summarize_timings(rows),
         "note": "Fresh processes use precompiled packages; warm reuses the same compiled scenario. Both cold walls include canonical compressed snapshots. Compare complete simulation/capture or simulation/serialization totals: PySD captures compute auxiliaries and populate integration caches, so its individual phase boundaries differ from Julia. JIT is included in Julia wall times."})
