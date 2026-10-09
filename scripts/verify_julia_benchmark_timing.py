#!/usr/bin/env python3
"""Remeasure Julia with an audited awake clock, without changing frozen code.

Julia 1.10.12/libuv uses mach_continuous_time (includes system suspend),
whereas the pinned Python perf_counter uses mach_absolute_time (excludes it).
The unchanged Julia runner is comparable only when the dual-clock guard proves
that suspend contributed less than 0.01 seconds during the measured interval.
No Base methods, model equations, validated files or original raw runs change.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import copy
import ctypes
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.julia_repro.common import digest, dump, experiment_hashes, read
from scripts.julia_repro.execution import (check_benchmark_gate, compare, convert,
                                          run_julia, summarize_timings)
from scripts.julia_repro.reference import reference_ready

SUSPEND_LIMIT_NS = 10_000_000
TIMING_SLACK_SECONDS = 0.01
SCENARIOS = ("base", "mid", "high")


def audit_interval(start, finish):
    """Bound the change in continuous-minus-absolute using two clock brackets."""
    keys = ("absolute_before_ns", "continuous_ns", "absolute_after_ns")
    for point in (start, finish):
        if any(type(point.get(key)) is not int or point[key] < 0 for key in keys):
            raise ValueError("Invalid clock sample")
        if point["absolute_before_ns"] > point["absolute_after_ns"]:
            raise ValueError("Clock bracket reversed")
    if (finish["absolute_before_ns"] < start["absolute_after_ns"]
            or finish["continuous_ns"] < start["continuous_ns"]):
        raise ValueError("Clock moved backwards across measured interval")
    lower = finish["continuous_ns"] - finish["absolute_after_ns"] - (
        start["continuous_ns"] - start["absolute_before_ns"])
    upper = finish["continuous_ns"] - finish["absolute_before_ns"] - (
        start["continuous_ns"] - start["absolute_after_ns"])
    widths = [p["absolute_after_ns"] - p["absolute_before_ns"] for p in (start, finish)]
    awake_lower = (finish["absolute_before_ns"] - start["absolute_after_ns"]) / 1e9
    awake_upper = (finish["absolute_after_ns"] - start["absolute_before_ns"]) / 1e9
    passed = upper < SUSPEND_LIMIT_NS and lower > -SUSPEND_LIMIT_NS and max(widths) < SUSPEND_LIMIT_NS
    return {"pass": passed, "start": start, "finish": finish,
            "suspend_lower_seconds": lower / 1e9, "suspend_upper_seconds": upper / 1e9,
            "awake_seconds": (awake_lower + awake_upper) / 2,
            "awake_lower_seconds": awake_lower, "awake_upper_seconds": awake_upper,
            "continuous_seconds": (finish["continuous_ns"] - start["continuous_ns"]) / 1e9,
            "limit_seconds": SUSPEND_LIMIT_NS / 1e9}


def validate_timings(timings, outer_awake_seconds, *, serialization=False, engine="julia"):
    """Validate disjoint phases; compilation and included u0 are nested timers."""
    if not math.isfinite(outer_awake_seconds) or outer_awake_seconds < 0:
        raise ValueError("Invalid outer awake duration")
    total = 0.
    for timing in timings:
        for key, value in timing.items():
            if key.endswith("_seconds") or key == "max_rss_bytes":
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                    raise ValueError(f"Invalid timer or memory value: {key}={value}")
        required = ["load_seconds", "simulation_and_capture_seconds", "max_rss_bytes"]
        if serialization:
            required.append("serialization_seconds")
        if any(key not in timing for key in required) or timing["max_rss_bytes"] <= 0:
            raise ValueError("Missing required timing or memory field")
        simulation = timing["simulation_and_capture_seconds"]
        if engine == "julia":
            parts = ("initialize_seconds", "solve_seconds", "extraction_seconds")
            if any(key not in timing for key in parts):
                raise ValueError("Missing Julia simulation phase")
            if abs(sum(timing[key] for key in parts) - simulation) > TIMING_SLACK_SECONDS:
                raise ValueError("Julia simulation total disagrees with its disjoint phases")
            if "initial_u0_construction_seconds" in timing:
                if abs(timing["load_excluding_initialization_seconds"] + timing["initial_u0_construction_seconds"]
                       - timing["load_seconds"]) > TIMING_SLACK_SECONDS:
                    raise ValueError("Julia load breakdown is inconsistent")
        total += timing["load_seconds"] + simulation
        if serialization:
            total += timing["serialization_seconds"]
    if total > outer_awake_seconds + TIMING_SLACK_SECONDS:
        raise ValueError(f"Disjoint phase total {total:g}s exceeds outer awake duration {outer_awake_seconds:g}s")
    return {"pass": True, "disjoint_phase_seconds": total, "outer_awake_seconds": outer_awake_seconds,
            "slack_seconds": TIMING_SLACK_SECONDS,
            "counted": "load + simulation_and_capture" + (" + serialization" if serialization else ""),
            "nested_not_added": ["compilation", "initial_u0_construction", "initialize", "solve", "extraction"]}


class MacClocks:
    class Timebase(ctypes.Structure):
        _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]

    def __init__(self):
        if platform.system() != "Darwin" or time.get_clock_info("perf_counter").implementation != "mach_absolute_time()":
            raise RuntimeError("This clock verification requires macOS mach_absolute_time Python clocks")
        self.library = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        info = self.Timebase()
        if self.library.mach_timebase_info(ctypes.byref(info)) != 0 or not info.numer or not info.denom:
            raise RuntimeError("Cannot read mach_timebase_info")
        self.numer, self.denom = info.numer, info.denom
        self.absolute, self.continuous = self.library.mach_absolute_time, self.library.mach_continuous_time
        self.absolute.restype = self.continuous.restype = ctypes.c_uint64
        self.absolute.argtypes = self.continuous.argtypes = []

    def sample(self):
        # Python integers avoid intermediate UInt64 multiplication overflow.
        a = self.absolute() * self.numer // self.denom
        c = self.continuous() * self.numer // self.denom
        b = self.absolute() * self.numer // self.denom
        return {"absolute_before_ns": a, "continuous_ns": c, "absolute_after_ns": b}


@contextmanager
def prevent_idle_sleep(log):
    """The assertion ends with this context or automatically when our PID exits."""
    with Path(log).open("wb") as stream:
        command = ["/usr/bin/caffeinate", "-i", "-w", str(os.getpid())]
        process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT)
        try:
            time.sleep(0.05)
            if process.poll() is not None:
                raise RuntimeError("caffeinate exited before the timing run")
            yield process, command
            if process.poll() is not None:
                raise RuntimeError("caffeinate exited during the timing run")
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def verified_python_rows(directory, original):
    """Keep 24 original Python rows only after verifying all 27 executions."""
    manifest = read(directory / "manifest.json")
    rows = [copy.deepcopy(row) for row in original["measurements"] if row["engine"] == "python"]
    if len(rows) != 24:
        raise ValueError("Expected exactly 24 original Python measurements")
    evidence, checks = {}, []
    def bind(path):
        evidence[str(path.relative_to(directory))] = digest(path)

    for case in SCENARIOS:
        cold = [row for row in rows if row["scenario"] == case and row["kind"] == "fresh_process"]
        warm = [row for row in rows if row["scenario"] == case and row["kind"] == "warm_same_scenario"]
        if len(cold) != 3 or len(warm) != 5:
            raise ValueError(f"Invalid original Python repeat counts: {case}")
        specifications = [(f"bench_cold_{i}", [case], 0, row) for i, row in enumerate(cold)]
        specifications += [("bench_warm", [case] * 6, i, None if i == 0 else warm[i-1]) for i in range(6)]
        for label, cases, index, row in specifications:
            if not reference_ready(directory, manifest, cases, label=label, index=index):
                raise ValueError(f"Stale original Python benchmark provenance: {case}/{label}/{index}")
            candidate = directory / "reference/app" / f"{label}_{index:02d}_{case}"
            result = compare(directory / "reference/app" / case, candidate, exact=True)
            if not result["pass"]:
                raise ValueError(f"Original Python timed output differs from frozen reference: {candidate}")
            timing = read(candidate.with_suffix(".timing.json"))
            # Row identity follows the preserved original order; every source
            # timing field must match, including scenario and load phase.
            if row is not None:
                if any(row.get(key) != value for key, value in timing.items()):
                    raise ValueError(f"Original Python row differs from its timing artifact: {candidate}")
                if row["simulation_and_serialization_seconds"] != timing["simulation_and_capture_seconds"] + timing["serialization_seconds"]:
                    raise ValueError("Original Python serialization total is inconsistent")
                outer = row.get("wall_seconds", timing["load_seconds"] + timing["simulation_and_capture_seconds"] + timing["serialization_seconds"])
                validate_timings([row], outer, serialization=True, engine="python")
            for suffix in (".json", ".npz", ".params.json", ".inputs.json", ".timing.json", ".warnings.json", ".provenance.json"):
                bind(candidate.with_suffix(suffix))
            log = directory / "logs" / (f"warm_{case}.log" if label == "bench_warm" else f"python_{case}_{label}.log")
            bind(log)
            checks.append({"scenario": case, "label": label, "index": index, "pass": True,
                           "warmup": label == "bench_warm" and index == 0,
                           "snapshot": str(candidate.relative_to(directory))})
    return rows, {"pass": True, "measurements": 24, "numerical_checks": checks, "evidence": evidence,
                  "clock": "Original Python perf_counter uses mach_absolute_time; historical dual-clock guard unavailable"}


def preflight(directory):
    check_benchmark_gate(directory)
    original_path = directory / "debug/clock-audit/benchmark-original.json"
    if not original_path.exists():
        candidate = read(directory / "benchmark.json")
        if len(candidate.get("measurements", [])) != 48:
            raise ValueError("No complete original benchmark to preserve")
        original_path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation protects previously preserved evidence.
        with original_path.open("xb") as destination, (directory / "benchmark.json").open("rb") as source:
            shutil.copyfileobj(source, destination)
    original = read(original_path)
    context = {"experiment": experiment_hashes(), "validation_sha256": digest(directory / "validation.json"),
               "original_benchmark_sha256": digest(original_path), "script_sha256": digest(Path(__file__))}
    if original.get("experiment") != context["experiment"] or original.get("validation_sha256") != context["validation_sha256"]:
        raise ValueError("Original benchmark was generated under different validation or source")
    rows, python = verified_python_rows(directory, original)
    return context, rows, python


def run(directory, attempt_id=None):
    directory = Path(directory).resolve()
    context, rows, python = preflight(directory)
    clocks = MacClocks()
    attempt_id = attempt_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{os.getpid()}"
    if not re.fullmatch(r"[A-Za-z0-9_-]+", attempt_id):
        raise ValueError("Attempt ID must contain only letters, digits, underscore or hyphen")
    target = directory / "benchmark-clock-verified" / attempt_id
    target.mkdir(parents=True, exist_ok=False)  # No resume and no silent replacement.
    audit_path = target / "audit.json"
    audit = {"pass": False, "status": "running", **context, "attempt_id": attempt_id,
             "python": python, "processes": [], "measurements": rows,
             "clock": {"duration": "mach_absolute_time", "suspend_detector": "mach_continuous_time minus mach_absolute_time",
                       "timebase_numer": clocks.numer, "timebase_denom": clocks.denom,
                       "suspend_limit_seconds": SUSPEND_LIMIT_NS / 1e9,
                       "julia_runner": "Unchanged time_ns; accepted only when no suspend is certified"}}

    def save():
        dump(audit_path, audit)

    def require_unchanged():
        if (experiment_hashes() != context["experiment"] or digest(directory / "validation.json") != context["validation_sha256"]
                or digest(Path(__file__)) != context["script_sha256"]
                or digest(directory / "debug/clock-audit/benchmark-original.json") != context["original_benchmark_sha256"]):
            raise RuntimeError("Source, validation, timing harness or original evidence changed")

    dump(directory / "benchmark.json", {"pass": False, "timing_valid": False, "numerical_pass": False,
         "status": "timing_verification_running", **context, "timing_audit": str(audit_path.relative_to(directory))})
    save()
    try:
        with prevent_idle_sleep(target / "caffeinate.log") as (inhibitor, command):
            audit["caffeinate"] = {"command": command, "pid": inhibitor.pid}
            for case in SCENARIOS:
                for label, iterations in [(f"cold_{i}", 1) for i in range(3)] + [("warm", 6)]:
                    require_unchanged()
                    process = {"scenario": case, "label": label, "iterations": iterations, "pass": False,
                               "status": "running", "outputs": []}
                    audit["processes"].append(process)
                    save()
                    raw = target / case / label
                    start = clocks.sample()
                    try:
                        run_julia(directory, case, raw, iterations, app_outputs=True)
                    finally:
                        finished = clocks.sample()
                        process["runner_guard"] = audit_interval(start, finished)
                        save()
                    if not process["runner_guard"]["pass"]:
                        raise RuntimeError(f"Suspend/clock uncertainty invalidates {case}/{label}")
                    timing_paths = [(raw if iterations == 1 else raw / str(i)) / "timing.json" for i in range(1, iterations+1)]
                    timing_hashes = [digest(path) for path in timing_paths]
                    timings = [read(path) for path in timing_paths]
                    if timing_hashes != [digest(path) for path in timing_paths]:
                        raise RuntimeError("Julia timing file changed while being read")
                    process["runner_phase_check"] = validate_timings(timings, process["runner_guard"]["awake_lower_seconds"])
                    for i, timing in enumerate(timings, 1):
                        if timing.get("iteration") != i:
                            raise ValueError("Missing or reordered Julia iteration")
                        destination = target / "converted" / f"{case}_{label}_{i}"
                        serialization_start = clocks.sample()
                        convert(directory, case, raw if iterations == 1 else raw / str(i), destination, app_outputs=True)
                        serialization_end = clocks.sample()
                        guard = audit_interval(serialization_start, serialization_end)
                        process["outputs"].append({"iteration": i, "snapshot": str(destination.relative_to(directory)),
                                                   "serialization_guard": guard, "warmup": iterations > 1 and i == 1})
                        if not guard["pass"]:
                            raise RuntimeError(f"Suspend during serialization: {case}/{label}/{i}")
                        timing["serialization_seconds"] = guard["awake_seconds"]
                    ending = clocks.sample()
                    process["complete_guard"] = audit_interval(start, ending)
                    if not process["complete_guard"]["pass"]:
                        raise RuntimeError(f"Suspend during complete process/capture: {case}/{label}")
                    process["complete_phase_check"] = validate_timings(timings, process["complete_guard"]["awake_lower_seconds"], serialization=True)
                    for timing, output, timing_path, timing_hash in zip(timings, process["outputs"], timing_paths, timing_hashes):
                        candidate = directory / output["snapshot"]
                        paths = [candidate.with_suffix(ext) for ext in (".json", ".npz")]
                        paths += [timing_path, raw.with_suffix(".log")]
                        proof = {str(path.relative_to(directory)): digest(path) for path in paths}
                        if proof[str(timing_path.relative_to(directory))] != timing_hash:
                            raise RuntimeError("Julia timing file changed before numerical comparison")
                        result = compare(directory / "reference/app" / case, candidate)
                        if any(digest(directory / name) != sha for name, sha in proof.items()):
                            raise RuntimeError("Benchmark output or timing changed during comparison")
                        check_path = target / "comparisons" / f"{case}_{label}_{timing['iteration']}.json"
                        dump(check_path, result)
                        proof[str(check_path.relative_to(directory))] = digest(check_path)
                        output["evidence_at_comparison"] = proof
                        output["comparison"] = str(check_path.relative_to(directory))
                        output["pass"] = bool(result["pass"])
                        if not result["pass"]:
                            raise RuntimeError(f"Numerical mismatch in timed run: {case}/{label}/{timing['iteration']}")
                        if output["warmup"]:
                            continue
                        row = {"engine": "julia", "scenario": case,
                               "kind": "fresh_process" if iterations == 1 else "warm_same_scenario", **timing,
                               "simulation_and_serialization_seconds": timing["simulation_and_capture_seconds"] + timing["serialization_seconds"]}
                        if iterations == 1:
                            row["wall_seconds"] = process["complete_guard"]["awake_seconds"]
                        rows.append(row)
                    process["pass"], process["status"] = True, "complete"
                    save()
                    print(f"Verified {case}/{label}: {iterations} numerical checks, awake {process['complete_guard']['awake_seconds']:.3f}s", flush=True)
        require_unchanged()
        check_benchmark_gate(directory)
        if any(digest(directory / name) != sha for name, sha in python["evidence"].items()):
            raise RuntimeError("Original Python benchmark artifacts changed during remeasurement")
        for process in audit["processes"]:
            for output in process["outputs"]:
                if any(digest(directory / name) != sha for name, sha in output["evidence_at_comparison"].items()):
                    raise RuntimeError("Timed output evidence changed after its numerical comparison")
        if len(rows) != 48 or len(audit["processes"]) != 12 or sum(len(p["outputs"]) for p in audit["processes"]) != 27:
            raise RuntimeError("Incomplete benchmark repeat coverage")
        audit["artifacts"] = {str(path.relative_to(directory)): digest(path) for path in sorted(target.rglob("*"))
                              if path.is_file() and path != audit_path}
        audit.update({"pass": True, "status": "complete", "timing_valid": True, "numerical_pass": True})
        save()
        dump(directory / "benchmark.json", {"pass": True, "status": "complete", "timing_valid": True, "numerical_pass": True,
             **context, "measurements": rows, "summary": summarize_timings(rows),
             "timing_audit": {"path": str(audit_path.relative_to(directory)), "sha256": digest(audit_path)},
             "note": "Python's 24 original awake-clock measurements retain verified provenance and exact outputs. Julia was rerun sequentially in 3 fresh processes and 6 same-scenario iterations (first warm-up omitted only from summaries). Every Julia process and serialization is dual-clock guarded, with certified suspend below 0.01s. All 54 outputs, including warm-ups, are verified. Compilation and u0 subtimers are nested and are not added twice."})
        return audit
    except BaseException as exc:
        audit.update({"pass": False, "status": "failed", "error": f"{type(exc).__name__}: {exc}"})
        if audit["processes"] and audit["processes"][-1]["status"] == "running":
            audit["processes"][-1]["status"] = "failed"
        audit["artifacts"] = {str(path.relative_to(directory)): digest(path) for path in sorted(target.rglob("*"))
                              if path.is_file() and path != audit_path}
        save()
        dump(directory / "benchmark.json", {"pass": False, "timing_valid": False, "numerical_pass": False,
             "status": "timing_verification_failed", **context,
             "timing_audit": {"path": str(audit_path.relative_to(directory)), "sha256": digest(audit_path)},
             "error": audit["error"]})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--attempt-id", help="New output directory name; an existing attempt is never resumed or overwritten")
    parser.add_argument("--check-only", action="store_true", help="Verify gates and original Python provenance without running Julia")
    args = parser.parse_args()
    if args.check_only:
        context, rows, python = preflight(args.run_dir.resolve())
        print({"pass": True, "python_rows": len(rows), "python_numerical_checks": len(python["numerical_checks"]),
               "experiment_files": len(context["experiment"]),
               **{key: value for key, value in context.items() if key != "experiment"}})
    else:
        run(args.run_dir, args.attempt_id)


if __name__ == "__main__":
    main()
