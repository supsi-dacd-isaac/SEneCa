"""Seeded allocation stress oracles and reusable actual-SURE call capture.

Equivalence to Python and conservation by Python are reported separately:
SciPy's absolute gradient stopping threshold can leave substantial relative
residuals for very small requests. No input is removed for that reason.
"""
from __future__ import annotations

from pathlib import Path
import importlib.metadata
import os
import sys
import warnings

import numpy as np

from .common import CONFIG, ROOT, RUNTIME, PINS, YEARS, dump, read, digest, run_logged, check_sources


def conservation(row):
    request = np.maximum(np.asarray(row["request"], dtype=np.float64), 0.)
    expected = np.asarray(row["expected"], dtype=np.float64)
    target = min(float(np.sum(request)), float(row["available"]))
    error = abs(float(np.sum(expected)) - target)
    limit = PINS["atol_scale"]*max(1., abs(target)) + PINS["rtol"]*abs(target)
    return {"target": target, "allocated": float(np.sum(expected)), "absolute_error": error,
            "relative_error": error/max(abs(target), np.finfo(float).tiny),
            "tolerance": limit, "pass": error <= limit,
            "nonnegative": bool(np.all(expected >= 0)),
            "within_requests": bool(np.all(expected <= request))}


def stress_oracle(target):
    import pysd
    from pysd.py_backend.allocation import _allocate_available_1d
    if pysd.__version__ != "3.14.3":
        raise ValueError("Wrong allocation oracle")
    target.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(PINS["seed"])
    rows, failed, conservation_failures = [], [], []
    patterns = ("separated", "touching", "overlap", "nested", "large_offset")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for suppliers in (1, 3, 9, 17, 129):
            for scale in np.logspace(-10, 8, 7):
                for pattern in patterns:
                    q = scale*rng.uniform(.05, 1., suppliers)
                    if suppliers > 1:
                        q[rng.random(suppliers) < .15] = 0.
                        q[rng.random(suppliers) < .1] *= -1
                    pp = np.zeros((suppliers, 4), dtype=float)
                    pp[:, 0] = 1.
                    if pattern == "separated":
                        pp[:, 1], pp[:, 2] = np.arange(suppliers)*2. - 50., .1
                    elif pattern == "touching":
                        pp[:, 1], pp[:, 2] = np.arange(suppliers)*.25, .25
                    elif pattern == "overlap":
                        pp[:, 1], pp[:, 2] = rng.normal(0., .015, suppliers), .1
                    elif pattern == "nested":
                        pp[:, 1], pp[:, 2] = 1., rng.uniform(.05, .5, suppliers)
                    else:
                        pp[:, 1], pp[:, 2] = 1e6+rng.normal(0., .0001, suppliers), .0002
                    total = float(np.sum(np.maximum(q, 0.)))
                    for fraction in (0., 1e-12, .0001, .1, .499, .9, 1.-1e-12, 1., 1.1):
                        row = {"request": q.tolist(), "pp": pp.tolist(), "available": total*fraction,
                               "suppliers": suppliers, "scale": float(scale), "pattern": pattern,
                               "fraction": fraction}
                        try:
                            row["expected"] = np.asarray(_allocate_available_1d(np.maximum(q, 0.), pp, row["available"]), dtype=float).tolist()
                            if not np.isfinite(row["expected"]).all():
                                raise ValueError("Nonfinite Python allocation")
                            row["python_conservation"] = conservation(row)
                            if not row["python_conservation"]["pass"]:
                                conservation_failures.append({"case": len(rows)+1, **row["python_conservation"],
                                                              "scale": float(scale), "pattern": pattern})
                            rows.append(row)
                        except Exception as exc:
                            failed.append({**row, "error": str(exc)})
    dump(target / "cases.json", rows)
    dump(target / "python-audit.json", {"pass": not failed, "seed": PINS["seed"],
         "cases": len(rows), "failures": failed, "conservation_failures": conservation_failures,
         "conservation_failure_count": len(conservation_failures),
         "max_conservation_absolute_error": max((row["python_conservation"]["absolute_error"] for row in rows), default=0.),
         "warnings": [str(w.message) for w in caught]})


def capture_sure(directory, cases=("base",), target=None):
    """Certify calls only after reproducing the frozen diagnostic oracle bitwise.

    Invoke in a fresh reference process with common.environment(). The seed is
    part of the actual interpreter startup, because PySD prunes stateful objects
    through a set and its iteration order affects DELAY FIXED evaluation.
    """
    from .reference import reference_ready
    from .results import save_frame, compare, load_snapshot

    directory = Path(directory)
    target = Path(target) if target is not None else directory / "allocation-real"
    target.mkdir(parents=True, exist_ok=True)
    dump(target / "python-audit.json", {"pass": False, "status": "incomplete"})
    if os.environ.get("PYTHONHASHSEED") != "0" or sys.flags.hash_randomization != 0:
        raise ValueError("SURE capture requires PYTHONHASHSEED=0 at interpreter startup")
    manifest = read(directory / "manifest.json")
    check_sources(manifest)
    cases = list(cases)
    if not cases or len(cases) != len(set(cases)):
        raise ValueError("Capture scenarios must be nonempty and unique")
    packages = {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()}
    drift = {k: (v, packages.get(k)) for k, v in manifest["packages"].items()
             if k not in {"pip", "setuptools"} and packages.get(k) != v}
    if drift:
        raise ValueError(f"Reference environment drift: {drift}")
    references = {}
    for case in cases:
        if not reference_ready(directory, manifest, [case], mode="diagnostic"):
            raise ValueError(f"Frozen diagnostic reference is missing or stale: {case}")
        baseline = directory / "reference/diagnostic" / case
        references[case] = {ext: digest(baseline.with_suffix(ext)) for ext in
                            (".json", ".npz", ".params.json", ".provenance.json")}
    implementation = digest(Path(__file__))
    import pysd
    import pysd.py_backend.allocation as allocation
    import sure_paths
    if pysd.__version__ != PINS["pysd_reference"]:
        raise ValueError("Wrong SURE allocation oracle")
    sure_paths.set_variant("v3")
    import sure_pysd as sp
    original_outputs = sp.OUTPUTS
    original = allocation._allocate_available_1d
    captured, verified = [], {}
    state_order = []
    try:
        sp.OUTPUTS = manifest["diagnostics"]
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            model = sp.load_model(prune=True)
            constants = sp.build_constant_params(model)
            state_order = [state.py_name for state in model._dynamicstateful_elements]
            for case in cases:
                baseline = directory / "reference/diagnostic" / case
                scenario = manifest["scenarios"][case]
                params = {}
                for name, value in sp.build_params(model, const_params=constants, scenario_inputs=scenario).items():
                    params[name] = ({"dims": list(value.dims),
                        "coords": {d: list(value.coords[d].values) for d in value.dims},
                        "values": value.values.tolist()} if hasattr(value, "dims") else
                        {"dims": [], "coords": {}, "values": float(value)})
                if params != read(baseline.with_suffix(".params.json")):
                    raise ValueError(f"Capture changes the frozen applied parameters: {case}")
                snapshot = target / f"diagnostic-{case}"
                dump(snapshot.with_suffix(".params.json"), params)
                first_call = len(captured)
                def capture(request, pp, available):
                    result = original(request, pp, available)
                    captured.append({"request": np.asarray(request).tolist(), "pp": np.asarray(pp).tolist(),
                                     "available": float(available), "expected": np.asarray(result).tolist(),
                                     "scenario": case, "time": float(model.time())})
                    return result
                allocation._allocate_available_1d = capture
                frame = sp.run_scenario(model, scenario_inputs=scenario, const_params=constants,
                                       timestamps=YEARS, flatten=False, return_columns=manifest["diagnostics"])
                save_frame(snapshot, frame, manifest["diagnostics"], manifest, flattened=False)
                shared = compare(baseline, snapshot, exact=True)
                _, expected = load_snapshot(baseline)
                _, observed = load_snapshot(snapshot)
                bitwise = all(np.array_equal(expected[name].view(np.uint64), observed[name].view(np.uint64))
                              for name in manifest["diagnostics"])
                dump(snapshot.with_suffix(".comparison.json"), {**shared, "bitwise": bitwise})
                if not shared["pass"] or not bitwise:
                    raise ValueError(f"Allocation instrumentation changes frozen outputs: {case}")
                verified[case] = {"shared_bitwise": True, "outputs": len(manifest["diagnostics"]),
                    "first_call": first_call, "calls": len(captured)-first_call,
                    "snapshot_sha256": digest(snapshot.with_suffix(".npz")),
                    "params_sha256": digest(snapshot.with_suffix(".params.json")),
                    "scenario": scenario}
    finally:
        allocation._allocate_available_1d = original
        sp.OUTPUTS = original_outputs
        dump(target / "warnings.json", [{"category": w.category.__name__, "message": str(w.message)}
                                       for w in caught] if "caught" in locals() else [])
    check_sources(manifest)
    if digest(Path(__file__)) != implementation:
        raise ValueError("Capture implementation changed during execution")
    for case in cases:
        baseline = directory / "reference/diagnostic" / case
        if (not reference_ready(directory, manifest, [case], mode="diagnostic") or
            any(digest(baseline.with_suffix(ext)) != sha for ext, sha in references[case].items())):
            raise ValueError(f"Frozen reference changed during capture: {case}")
    failures = []
    for i, row in enumerate(captured, 1):
        row["python_conservation"] = conservation(row)
        if not row["python_conservation"]["pass"]:
            failures.append({"case": i, **row["python_conservation"], "time": row["time"], "scenario": row["scenario"]})
    dump(target / "cases.json", captured)
    dump(target / "python-audit.json", {"pass": True, "status": "certified", "cases": len(captured), "scenarios": cases,
                                       "conservation_failures": failures, "conservation_failure_count": len(failures),
        "source_hashes": manifest["sources"], "reference_artifacts": references, "verified_snapshots": verified,
        "stateful_order": state_order, "python": sys.version, "packages": packages,
        "environment": {name: os.environ.get(name) for name in
             ("PYTHONHASHSEED", "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS")},
        "hash_randomization": sys.flags.hash_randomization,
        "manifest_sha256": digest(directory / "manifest.json"), "implementation_sha256": implementation,
        "cases_sha256": digest(target / "cases.json"), "warnings": [str(w.message) for w in caught]})
    return target


def run(directory):
    from .execution import julia_command
    target = Path(directory) / "allocation-stress"
    command = f"from pathlib import Path; from scripts.julia_repro.allocation_fixtures import stress_oracle; stress_oracle(Path({str(target)!r}))"
    run_logged([RUNTIME / "python-reference/bin/python", "-B", "-c", command], target / "python.log")
    run_logged([*julia_command(), CONFIG / "test_allocation.jl", target / "cases.json", target / "julia-results.json"], target / "julia.log")
    result = {"python": read(target / "python-audit.json"), "julia": read(target / "julia-results.json"),
              "cases_sha256": digest(target / "cases.json")}
    result["pass"] = result["python"]["pass"] and result["julia"]["pass"]
    dump(target / "results.json", result)
    return result
