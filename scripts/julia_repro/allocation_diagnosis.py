"""Attribute allocation discrepancies to input rounding or algorithm differences.

Run with the pinned reference Python and common.environment():
  python -m scripts.julia_repro.allocation_diagnosis --run-dir <run>

This supplemental diagnosis uses certified snapshots, including an expanded
reference containing Priority vector by supplier. It never changes an oracle,
acceptance threshold or candidate. A standalone Julia check exercises both sets
of inputs against fresh PySD 3.14.3 results. Defaults target the base debug trace.
"""
from __future__ import annotations

import argparse
import importlib.metadata
from pathlib import Path

import numpy as np

from .common import CONFIG, PINS, YEARS, check_sources, digest, dump, read, run_logged
from .execution import julia_command
from .reference import reference_ready
from .results import compare, load_snapshot


_JULIA_CHECK = '''using JSON3
Base.include(@__MODULE__, ARGS[1])
rows = JSON3.read(read(ARGS[2], String))
results = []
for (i,row) in enumerate(rows)
    profiles = reduce(vcat, (permutedims(Float64.(r)) for r in row.pp))
    expected = Float64.(row.expected)
    actual = seneca_allocate_vector(Float64.(row.request),profiles,Float64(row.available))
    push!(results, Dict("case"=>i,"source"=>String(row.source),"year"=>Int(row.year),
        "month"=>Int(row.month),"hour"=>Int(row.hour),"bitwise"=>isequal(actual,expected),
        "max_abs"=>maximum(abs.(actual.-expected)),"actual"=>actual))
end
result = Dict("cases"=>length(results),"all_bitwise"=>all(r["bitwise"] for r in results),
    "max_abs"=>maximum((r["max_abs"] for r in results); init=0.0),"results"=>results)
write(ARGS[3],JSON3.write(result))
println("Cases=",length(results)," all_bitwise=",result["all_bitwise"]," max_abs=",result["max_abs"])
'''


def _bitwise(a, b):
    return np.array_equal(np.asarray(a).view(np.uint64), np.asarray(b).view(np.uint64))


def _ulps(x, y):
    # Allocation requests and availability are nonnegative in SURE. Keep this
    # diagnostic explicit rather than using an invalid signed-float distance.
    if x < 0 or y < 0:
        raise ValueError("ULP diagnosis requires nonnegative allocation inputs")
    return abs(int(np.float64(x).view(np.uint64)) - int(np.float64(y).view(np.uint64)))


def diagnose(directory, *, case="base", candidate=None, profile_reference=None, target=None):
    from pysd.py_backend.allocation import _allocate_available_1d

    directory = Path(directory)
    target = Path(target) if target else directory / "debug/allocation-sensitive-reproduced"
    target.mkdir(parents=True, exist_ok=True)
    dump(target / "diagnosis.json", {"status": "incomplete"})
    manifest = read(directory / "manifest.json")
    check_sources(manifest)
    if importlib.metadata.version("pysd") != PINS["pysd_reference"]:
        raise ValueError("Allocation diagnosis requires the pinned Python oracle")
    packages = {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()}
    drift = {k: (v, packages.get(k)) for k, v in manifest["packages"].items()
             if k not in {"pip", "setuptools"} and packages.get(k) != v}
    if drift:
        raise ValueError(f"Reference environment drift: {drift}")
    if not reference_ready(directory, manifest, [case], mode="diagnostic"):
        raise ValueError("Frozen reference is stale or missing")
    reference = directory / "reference/diagnostic" / case
    candidate = Path(candidate) if candidate else directory / "candidate-debug" / case
    profile_reference = Path(profile_reference) if profile_reference else directory / "debug/phs-reference"
    paths = {"reference": reference, "candidate": candidate, "profiles": profile_reference}
    bound = {kind: {suffix: digest(path.with_suffix(suffix)) for suffix in (".json", ".npz")}
             for kind, path in paths.items()}
    rm, r = load_snapshot(reference)
    jm, j = load_snapshot(candidate)
    tm, traced = load_snapshot(profile_reference)
    shared = compare(reference, profile_reference, outputs=manifest["diagnostics"], exact=True)
    if not shared["pass"] or not all(_bitwise(r[name], traced[name]) for name in manifest["diagnostics"]):
        raise ValueError("Expanded profile reference does not reproduce the frozen diagnostics bitwise")
    if rm["years"] != jm["years"] or rm["years"] != tm["years"] or rm["years"] != YEARS:
        raise ValueError("Snapshot timestamps differ")
    qname, aname, oname = "Hourly available supply by Supplier", "Hourly demand and PHS", "Electricity dispatched"
    required = [qname, aname, oname, "Electricity consumed", "Hourly exported electricity"]
    for name in required:
        if name not in j or any(rm["variables"][name][field] != jm["variables"][name][field]
                               for field in ("dims", "coords", "columns")):
            raise ValueError(f"Allocation snapshot coordinate mismatch: {name}")
        if not np.isfinite(r[name]).all() or not np.isfinite(j[name]).all():
            raise ValueError(f"Nonfinite allocation snapshot: {name}")
    if rm["variables"][qname]["dims"] != ["Month", "Hour", "Supplier"]:
        raise ValueError("Unexpected SURE allocation dimensions")
    labels = rm["variables"][qname]["coords"]["Supplier"]
    months = rm["variables"][qname]["coords"]["Month"]
    hours = rm["variables"][qname]["coords"]["Hour"]
    shape = (len(YEARS), len(months), len(hours), len(labels))
    profile_name = "Priority vector by supplier"
    profile_meta = tm["variables"][profile_name]
    if (profile_meta["dims"] != ["Supplier", "pprofile"] or
        profile_meta["coords"]["Supplier"] != labels or
        profile_meta["coords"]["pprofile"] != ["ptype", "ppriority", "pwidth", "pextra"]):
        raise ValueError("Unexpected allocation priority coordinates")
    profiles = traced[profile_name].reshape(len(YEARS), len(labels), 4)
    qr, qj = (x[qname].reshape(shape) for x in (r, j))
    ar, aj = (x[aname].reshape(shape[:-1]) for x in (r, j))
    or_, oj = (x[oname].reshape(shape) for x in (r, j))
    failed = set()
    for name in [oname, "Electricity consumed", "Hourly exported electricity"]:
        limit = PINS["atol_scale"] * np.maximum(1., np.max(np.abs(r[name]), axis=0)) + PINS["rtol"]*np.abs(r[name])
        mask = (np.abs(r[name]-j[name]) > limit).reshape(shape)
        failed.update(tuple(map(int, index)) for index in np.argwhere(mask.any(axis=3)))
    rows, cases = [], []
    for t, month, hour in sorted(failed):
        idx = (t, month, hour)
        pp = profiles[t]
        yp = np.asarray(_allocate_available_1d(np.maximum(qr[idx], 0.), pp, ar[idx]))
        yj = np.asarray(_allocate_available_1d(np.maximum(qj[idx], 0.), pp, aj[idx]))
        if not _bitwise(yp, or_[idx]):
            raise ValueError(f"Python evaluator does not reproduce frozen allocation: {idx}")
        changes = [{"input": label, "python": float(x), "julia": float(y),
                    "abs_diff": abs(float(x-y)), "ulps": _ulps(x,y)}
                   for label, x, y in zip(labels, qr[idx], qj[idx]) if x != y]
        if ar[idx] != aj[idx]:
            changes.append({"input": "available", "python": float(ar[idx]), "julia": float(aj[idx]),
                            "abs_diff": abs(float(ar[idx]-aj[idx])), "ulps": _ulps(ar[idx],aj[idx])})
        row = {"year": YEARS[t], "month": month+1, "hour": hour+1,
               "month_label": months[month], "hour_label": hours[hour], "changed_inputs": changes,
               "request_python": qr[idx].tolist(), "request_julia": qj[idx].tolist(),
               "available_python": float(ar[idx]), "available_julia": float(aj[idx]), "profiles": pp.tolist(),
               "python_frozen": or_[idx].tolist(), "python_on_julia_inputs": yj.tolist(), "native_julia": oj[idx].tolist(),
               "python_on_julia_inputs_matches_native_bitwise": _bitwise(yj, oj[idx]),
               "native_algorithm_max_abs": float(np.max(np.abs(yj-oj[idx]))),
               "input_sensitivity_max_abs": float(np.max(np.abs(yp-yj))),
               "actual_difference_max_abs": float(np.max(np.abs(or_[idx]-oj[idx])))}
        rows.append(row)
        for label, q, a, expected in [("python-input", qr[idx], ar[idx], yp), ("julia-input", qj[idx], aj[idx], yj)]:
            cases.append({"request": q.tolist(), "available": float(a), "pp": pp.tolist(), "expected": expected.tolist(),
                          "year": YEARS[t], "month": month+1, "hour": hour+1, "source": label})
    dump(target / "cases.json", cases)
    (target / "run.jl").write_text(_JULIA_CHECK)
    helper_sha = digest(CONFIG / "allocation.jl")
    run_logged([*julia_command(), target / "run.jl", CONFIG / "allocation.jl", target / "cases.json", target / "native.json"],
               target / "native.log")
    if digest(CONFIG / "allocation.jl") != helper_sha:
        raise ValueError("Allocation helper changed during the standalone test")
    check_sources(manifest)
    if any(digest(path.with_suffix(suffix)) != sha for kind, path in paths.items() for suffix, sha in bound[kind].items()):
        raise ValueError("Snapshots changed during diagnosis")
    native = read(target / "native.json")
    report = {"status": "complete", "allocation_cells": len(rows),
        "native_matches_python_on_julia_inputs_bitwise": sum(row["python_on_julia_inputs_matches_native_bitwise"] for row in rows),
        "native_algorithm_max_abs": max((row["native_algorithm_max_abs"] for row in rows), default=0.),
        "input_sensitivity_max_abs": max((row["input_sensitivity_max_abs"] for row in rows), default=0.),
        "snapshot_paths": {kind: str(path) for kind, path in paths.items()}, "snapshot_hashes": bound,
        "manifest_sha256": digest(directory / "manifest.json"), "implementation_sha256": digest(Path(__file__)),
        "cases_sha256": digest(target / "cases.json"), "allocation_helper_sha256": helper_sha,
        "standalone_julia": {key: native[key] for key in ("cases", "all_bitwise", "max_abs")}, "rows": rows}
    dump(target / "diagnosis.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--case", default="base")
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--profile-reference", type=Path)
    parser.add_argument("--target", type=Path)
    args = parser.parse_args()
    result = diagnose(args.run_dir.resolve(), case=args.case, candidate=args.candidate,
                      profile_reference=args.profile_reference, target=args.target)
    print({key: value for key, value in result.items() if key != "rows"})
