#!/usr/bin/env python3
"""Local SURE parameter reuse and formerly ignored control experiments."""
from __future__ import annotations

import argparse
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.julia_repro.common import digest, dump, read, run_logged
from scripts.julia_repro.execution import check_benchmark_gate, convert, julia_command
from scripts.julia_repro.comparison import compare
from scripts.julia_repro.energy import check_snapshot
from scripts.julia_parametric.model import CONTROLS, build
from scripts.verify_julia_benchmark_timing import MacClocks, audit_interval, prevent_idle_sleep


def implementation():
    files = [ROOT / "scripts/julia_parametric/model.py"]
    files += sorted((ROOT / "benchmarks/julia-parametric").glob("*.jl"))
    files += [Path(__file__), ROOT / "scripts/verify_julia_benchmark_timing.py"]
    files += sorted((ROOT / "tests").glob("test_parametric*.py"))
    files += [ROOT / "tests/parametric_api.jl"]
    return {str(p.relative_to(ROOT)): digest(p) for p in files}


def runtime_signature(signature):
    """Only orchestration/tests may change after a completed numerical run.

    The frozen comparison and dependency code is separately checked by
    check_benchmark_gate. Keep the actual execution signature in each report.
    """
    return {name: sha for name, sha in signature.items()
            if name not in {"scripts/benchmark_julia_parametric.py"} and not name.startswith("tests/")}


def verify_control_reference(target):
    folder = target / "controls"
    certificate = read(folder / "report.json")
    if not certificate["pass"]:
        raise ValueError("Regenerated Python controls have not passed")
    for path, sha in certificate["source_context"].items():
        if digest(path) != sha:
            raise ValueError(f"Control reference source changed: {path}")
    for path, sha in certificate["artifacts"].items():
        if digest(folder / path) != sha:
            raise ValueError(f"Control reference evidence changed: {path}")
    return digest(folder / "report.json")


def jobs_for(reference, target, phase):
    manifest = read(reference / "manifest.json")
    def job(label, case, *, controls=False):
        parameters = dict(manifest["scenarios"][case])
        if not controls:
            parameters.update(dict.fromkeys(CONTROLS, 0.))
        return {"id": label, "case": case, "parameters": parameters, "reference": str(reference / "reference/diagnostic" / case)}
    if phase == "pilot":
        return [job("base_a", "base"), job("high", "high"), job("base_b", "base")]
    if phase == "validate":
        return ([job(case, case) for case in manifest["scenarios"]] +
                [job("replay_base_a", "base"), job("replay_high", "high"), job("replay_base_b", "base")])
    if phase == "controls":
        jobs = [{"id": label, "case": label, "parameters": params,
                 "reference": str(target / "controls/reference" / label)}
                for label, params in read(target / "controls/scenarios.json").items()]
        jobs.append({**jobs[0], "id": "replay_base"})
        return jobs
    if phase == "benchmark":
        jobs = [job(f"warmup_{case}", case, controls=True) for case in ("base", "mid", "high")]
        jobs += [job(f"repeat_{i}_{case}", case, controls=True) for i in range(5) for case in ("base", "mid", "high")]
        for item in jobs:
            item["reference"] = str(target / "controls/reference" / item["case"])
        return jobs
    raise ValueError(phase)


def execute(reference, target, phase):
    check_benchmark_gate(reference)
    signature = implementation()
    certificate = read(target / "model/model.json")
    model = target / "model" / certificate["model"]
    if digest(model) != certificate["model_sha256"] or certificate["implementation_sha256"] != digest(ROOT / "scripts/julia_parametric/model.py"):
        raise ValueError("Stale parameterized model")
    def verify_inputs():
        if any(digest(target / "model" / name) != sha for name, sha in certificate["artifacts"].items()):
            raise ValueError("Parameterized model/data/export artifacts changed")
    verify_inputs()
    control_certificate = verify_control_reference(target) if phase in ("controls", "benchmark") else None
    if phase == "benchmark":
        validation = read(target / "validate/report.json")
        if (not validation["pass"] or runtime_signature(validation["implementation"]) != runtime_signature(signature)
                or validation["model_sha256"] != digest(model)):
            raise ValueError("Validate the current parameterized model before benchmarking")
        controlled = read(target / "controls-run/report.json")
        if not controlled["pass"] or controlled["implementation"] != signature:
            raise ValueError("Validate resolved controls before benchmarking")
        for certificate_ in (validation, controlled):
            if any(digest(target / name) != sha for name, sha in certificate_["artifacts"].items()):
                raise ValueError("Numerical validation evidence changed")
            if any(digest(path) != sha for path, sha in certificate_["references"].items()):
                raise ValueError("Numerical validation reference changed")
        if controlled["control_reference_sha256"] != control_certificate:
            raise ValueError("Resolved control reference changed since validation")
    destination = target / ("controls-run" if phase == "controls" else phase)
    destination.mkdir(parents=True, exist_ok=True)
    if (destination / "raw").exists():
        raise ValueError("Choose a new phase directory; old attempts are preserved")
    jobs = jobs_for(reference, target, phase)
    dump(destination / "jobs.json", jobs)
    context = {"implementation": signature, "model_sha256": digest(model),
               "control_reference_sha256": control_certificate,
               "original_validation_sha256": digest(reference / "validation.json"),
               "jobs_sha256": digest(destination / "jobs.json"),
               "references": {str(Path(j["reference"]).with_suffix(suffix)): digest(Path(j["reference"]).with_suffix(suffix))
                              for j in jobs for suffix in (".json", ".npz")}}
    if phase == "controls":
        context["references"].update({str(target / "controls/diagnostic" / f"{label}{suffix}"):
                                     digest(target / "controls/diagnostic" / f"{label}{suffix}")
                                     for label in read(target / "controls/scenarios.json") for suffix in (".json", ".npz")})
    result = {"pass": False, "phase": phase, "status": "running", **context, "checks": {}}
    dump(destination / "report.json", result)
    app = phase == "benchmark"
    export = target / "model" / ("export-app.json" if app else "export.json")
    clocks = MacClocks()
    try:
        with prevent_idle_sleep(destination / "caffeinate.log"):
            start = clocks.sample()
            run_logged([*julia_command(), ROOT / "benchmarks/julia-parametric/worker.jl", model, export,
                        destination / "jobs.json", destination / "raw"], destination / "run.log")
            result["clock_guard"] = audit_interval(start, clocks.sample())
        if "warning" in (destination / "run.log").read_text().lower():
            raise ValueError("Runtime warning requires review")
        if phase == "benchmark" and not result["clock_guard"]["pass"]:
            raise ValueError("Suspension invalidated benchmark")
        load = read(destination / "raw/load.json")
        if load["loads"] != 1 or not math.isfinite(load["seconds"]) or load["seconds"] < 0:
            raise ValueError("Expected one finite model load")
        result["load"] = load
        timings = []
        for job in jobs:
            raw = destination / "raw" / job["id"]
            candidate = destination / "candidate" / job["id"]
            # Export order and coordinates are inherited from the certified
            # model, not guessed from Julia's physical array storage order.
            convert(reference, "base", raw, candidate, app_outputs=app)
            compared = compare(Path(job["reference"]), candidate,
                               outputs=read(reference / "manifest.json")["outputs"] if phase == "controls" else None)
            if phase == "controls":
                label = "base" if job["id"] == "replay_base" else job["id"]
                compared["diagnostic"] = compare(target / "controls/diagnostic" / label, candidate,
                    outputs=list(read(target / "controls/diagnostic" / f"{label}.json")["variables"]))
                compared["pass"] = compared["pass"] and compared["diagnostic"]["pass"]
            if not app:
                compared["conservation"] = check_snapshot(candidate)
                compared["pass"] = compared["pass"] and compared["conservation"]["pass"]
            dump(destination / "checks" / f"{job['id']}.json", compared)
            timing = read(raw / "timing.json")
            if timing["module_id"] != load["module_id"] or timing["parameter_type"] != "Main.SURESession.SUREParameters":
                raise ValueError("Request switched module or parameter type")
            if timing["parameters"] != job["parameters"]:
                raise ValueError("Applied parameters differ")
            if not all(math.isfinite(timing[k]) and timing[k] >= 0 for k in (
                    "configuration_seconds", "initialize_seconds", "solve_seconds", "extraction_seconds",
                    "simulation_and_capture_seconds", "request_wall_seconds", "compilation_seconds")):
                raise ValueError("Invalid request timing")
            if timing["simulation_and_capture_seconds"] > timing["request_wall_seconds"] + .001:
                raise ValueError("Phase timings exceed request duration")
            if abs(sum(timing[k] for k in ("configuration_seconds", "initialize_seconds", "solve_seconds", "extraction_seconds"))
                   - timing["simulation_and_capture_seconds"]) > .001:
                raise ValueError("Inconsistent request phase total")
            timings.append({"id": job["id"], "scenario": job["case"], **timing})
            result["checks"][job["id"]] = compared["pass"]
            dump(destination / "report.json", result)
            print(f"{phase} {job['id']}: {'PASS' if compared['pass'] else 'FAIL'}", flush=True)
        result["checks"]["no_scenario_recompilation"] = all(t["compilation_seconds"] == 0 for t in timings[1:])
        measured = load["seconds"] + sum(t["request_wall_seconds"] for t in timings)
        result["timing_consistency"] = {"measured_seconds": measured,
            "outer_awake_seconds": result["clock_guard"]["awake_seconds"],
            "pass": measured <= result["clock_guard"]["awake_lower_seconds"] + .01}
        if not result["timing_consistency"]["pass"]:
            raise ValueError("Request durations exceed total process awake time")
        if phase in ("pilot", "validate", "controls"):
            first, last = (("base_a", "base_b") if phase == "pilot" else
                           ("base", "replay_base_b" if phase == "validate" else "replay_base"))
            repeat = compare(destination / "candidate" / first, destination / "candidate" / last, exact=True)
            dump(destination / "repeatability.json", repeat)
            result["checks"]["base_after_high_exact"] = repeat["pass"]
        if signature != implementation() or digest(model) != context["model_sha256"]:
            raise ValueError("Experiment changed during execution")
        verify_inputs()
        if any(digest(path) != sha for path, sha in context["references"].items()):
            raise ValueError("Reference snapshots changed during comparison")
        if control_certificate is not None and verify_control_reference(target) != control_certificate:
            raise ValueError("Control reference certificate changed during execution")
        check_benchmark_gate(reference)
        result.update(status="complete", pass_=all(result["checks"].values()), timings=timings)
        result["pass"] = result.pop("pass_")
        result["artifacts"] = {str(p.relative_to(target)): digest(p) for p in sorted(destination.rglob("*"))
                               if p.is_file() and p != destination / "report.json"}
        dump(destination / "report.json", result)
        if not result["pass"]:
            raise RuntimeError("Parameterized comparison failed")
        return result
    except BaseException as exc:
        result.update({"pass": False, "status": "failed", "error": f"{type(exc).__name__}: {exc}"})
        dump(destination / "report.json", result)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("build", "pilot", "validate", "controls", "benchmark"))
    parser.add_argument("--reference", type=Path, default=ROOT / "dist/julia-repro/20261009-reproducibility")
    parser.add_argument("--run-dir", type=Path, default=ROOT / "dist/julia-parametric/20261009")
    args = parser.parse_args()
    if args.phase == "build":
        build(args.reference, args.run_dir / "model")
    else:
        execute(args.reference.resolve(), args.run_dir.resolve(), args.phase)


if __name__ == "__main__":
    main()
