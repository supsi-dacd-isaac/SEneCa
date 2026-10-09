from __future__ import annotations

import ast
import hashlib
import importlib.metadata
from contextlib import contextmanager
import resource
import sys
import time
import warnings

import numpy as np

from .common import ROOT, RUNTIME, CONFIG, PINS, YEARS, read, dump, check_sources, digest, run_logged
from .results import save_frame, load_snapshot, compare
from .inventory import columns_for


def reference_implementation():
    """Julia translator edits do not invalidate a frozen Python oracle."""
    files = [ROOT / "scripts/julia_repro" / name for name in
             ("reference.py", "results.py", "inventory.py")]
    files.append(CONFIG / "python-reference.lock")
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in files}
    common = ROOT / "scripts/julia_repro/common.py"
    tree = ast.parse(common.read_text())
    tree.body = [node for node in tree.body if not
                 (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and
                  node.name in {"experiment_hashes", "evidence_hashes"})]
    hashes["scripts/julia_repro/common.py#reference-semantics"] = hashlib.sha256(
        ast.dump(tree, include_attributes=False).encode()).hexdigest()
    return hashes


def reference_provenance(manifest, cases, mode, label, index):
    case = cases[index]
    return {"sources": manifest["sources"], "pins": manifest["pins"],
            "packages": manifest["packages"], "implementation": reference_implementation(),
            "scenario": manifest["scenarios"][case], "case": case, "mode": mode,
            "process_cases": cases, "label": label, "index": index,
            "outputs": manifest["outputs"] if mode == "app" else manifest["diagnostics"]}


def reference_ready(directory, manifest, cases, mode="app", label=None, index=0):
    """Resume only complete, finite results bound to their parameters and source."""
    case = cases[index]
    suffix = f"{label}_{index:02d}_{case}" if label else case
    target = directory / "reference" / mode / suffix
    try:
        provenance = read(target.with_suffix(".provenance.json"))
        if provenance["context"] != reference_provenance(manifest, cases, mode, label, index):
            return False
        extensions = (".json", ".npz", ".params.json", ".inputs.json", ".timing.json", ".warnings.json")
        if set(provenance["artifacts"]) != set(extensions):
            return False
        if any(digest(target.with_suffix(ext)) != provenance["artifacts"][ext] for ext in extensions):
            return False
        meta, arrays = load_snapshot(target)
        outputs = manifest["outputs"] if mode == "app" else manifest["diagnostics"]
        if meta["years"] != YEARS or set(meta["variables"]) != set(outputs):
            return False
        for name in outputs:
            item = meta["variables"][name]
            dims = manifest["variables"][name].get("subscripts", [])
            columns = columns_for(name, manifest)
            if (item["dims"] != dims or item["columns"] != columns or
                item["coords"] != {d: manifest["dimensions"][d] for d in dims} or
                arrays[name].shape != (len(YEARS), len(columns)) or not np.isfinite(arrays[name]).all()):
                return False
        return read(target.with_suffix(".inputs.json"))["requested"] == manifest["scenarios"][case]
    except (OSError, ValueError, KeyError, TypeError):
        return False


def run_reference_suite(directory, cases, *, resume=False):
    """Attempt all cases, preserve every failure, and never accept a partial suite."""
    from .packing import validate_real_snapshot

    manifest = read(directory / "manifest.json")
    check_sources(manifest)
    cases = list(dict.fromkeys(cases))
    script = ROOT / "scripts/benchmark_julia.py"
    result = {"pass": False, "status": "running", "selected_cases": cases,
              "full_suite": set(cases) == set(manifest["scenarios"]), "cases": {},
              "failures": [], "implementation": reference_implementation()}
    def save():
        dump(directory / "reference-suite.json", result)
    save()
    for case in cases:
        row = {"pass": False, "modes": {}}
        result["cases"][case] = row
        for mode in ("app", "diagnostic"):
            reused = resume and reference_ready(directory, manifest, [case], mode)
            try:
                if not reused:
                    run_logged([RUNTIME / "python-reference/bin/python", script, "_reference",
                                "--run-dir", directory, "--scenarios", case, "--mode", mode],
                               directory / "logs" / f"reference_{mode}_{case}.log")
                if not reference_ready(directory, manifest, [case], mode):
                    raise RuntimeError("Incomplete, nonfinite, or unbound reference artifact")
                row["modes"][mode] = {"pass": True, "reused": reused}
            except Exception as exc:
                row["modes"][mode] = {"pass": False, "error": str(exc)}
                result["failures"].append({"case": case, "stage": mode, "error": str(exc)})
            save()
        if all(r["pass"] for r in row["modes"].values()):
            try:
                report = compare(directory / "reference/app" / case,
                                 directory / "reference/diagnostic" / case, outputs=manifest["outputs"])
                dump(directory / "checks" / f"reference_{case}.json", report)
                if not report["pass"]:
                    raise RuntimeError("Diagnostic path differs from the current webapp")
                packing = validate_real_snapshot(directory / "reference/diagnostic" / case)
                dump(directory / "checks" / f"packing_{case}.json", packing)
                if not packing["pass"]:
                    raise RuntimeError("Lossless index conversion failed")
                row["pass"] = True
            except Exception as exc:
                result["failures"].append({"case": case, "stage": "checks", "error": str(exc)})
        if not row["pass"]:
            # A previous pass must not mask a failed reference rerun.
            dump(directory / "checks" / f"reference_{case}.json", {"pass": False, "reason": "Reference case failed", "case": row})
        save()
        print(f"Reference {case}: {'PASS' if row['pass'] else 'FAIL'} ({len(result['cases'])}/{len(cases)})", flush=True)

    determinism = {"pass": False, "comparisons": [], "failures": []}
    for label, seq in [("fresh_a", ["base"]), ("fresh_b", ["base"]),
                       ("sequence", ["base", "high", "base"])]:
        try:
            reused = resume and all(reference_ready(directory, manifest, seq, label=label, index=i)
                                    for i in range(len(seq)))
            if not reused:
                run_logged([RUNTIME / "python-reference/bin/python", script, "_reference",
                            "--run-dir", directory, "--scenarios", *seq, "--label", label],
                           directory / "logs" / f"reference_{label}.log")
            if not all(reference_ready(directory, manifest, seq, label=label, index=i) for i in range(len(seq))):
                raise RuntimeError("Incomplete reference process-state evidence")
        except Exception as exc:
            determinism["failures"].append({"label": label, "error": str(exc)})
    if not determinism["failures"]:
        try:
            if not reference_ready(directory, manifest, ["base"]):
                raise RuntimeError("A valid base reference is required for determinism")
            determinism["comparisons"] = [
                compare(directory / "reference/app/base", directory / "reference/app" / suffix, exact=True)
                for suffix in ("fresh_a_00_base", "fresh_b_00_base", "sequence_00_base", "sequence_02_base")]
            determinism["pass"] = all(r["pass"] for r in determinism["comparisons"])
        except Exception as exc:
            determinism["failures"].append({"stage": "comparison", "error": str(exc)})
    dump(directory / "checks/reference_determinism.json", determinism)
    result["determinism"] = determinism["pass"]
    if not determinism["pass"]:
        result["failures"].append({"stage": "determinism", "error": "Reference determinism failed"})
    result["selected_pass"] = all(row["pass"] for row in result["cases"].values()) and determinism["pass"]
    result["pass"] = result["selected_pass"] and result["full_suite"]
    result["status"] = "complete" if result["selected_pass"] else "failed"
    save()
    if not result["selected_pass"]:
        raise RuntimeError(f"Python reference failed in {len(result['failures'])} checks; see reference-suite.json")
    return result


@contextmanager
def phase_timers(model):
    """Observe existing calls, without changing equations, output or caching."""
    from pysd.py_backend.output import ModelOutput
    metrics, originals = {}, []
    def wrap(owner, name, metric):
        original = getattr(owner, name)
        local = name in vars(owner)
        def measured(*args, **kwargs):
            started = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                metrics[metric] = metrics.get(metric, 0.) + time.perf_counter() - started
        originals.append((owner, name, original, local))
        setattr(owner, name, measured)
    wrap(model, "_config_simulation", "initialization_and_configuration_seconds")
    wrap(model, "_integrate_step", "integration_seconds")
    for name in ("initialize", "update", "add_run_elements", "postprocess"):
        wrap(ModelOutput, name, "extraction_seconds")
    try:
        yield metrics
    finally:
        for owner, name, original, local in reversed(originals):
            if local:
                setattr(owner, name, original)
            else:
                delattr(owner, name)


def run_reference(directory, cases, mode="app", label=None):
    manifest = read(directory / "manifest.json")
    check_sources(manifest)
    if importlib.metadata.version("pysd") != PINS["pysd_reference"]:
        raise RuntimeError("Reference requires PySD 3.14.3")
    expected = manifest["packages"]
    current = {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()}
    differences = {k: (v, current.get(k)) for k, v in expected.items()
                   if k not in {"pip", "setuptools"} and current.get(k) != v}
    if differences:
        raise RuntimeError(f"Reference environment drift: {differences}")
    sys.path.insert(0, str(ROOT))
    import sure_paths
    sure_paths.set_variant("v3")
    import sure_pysd as sp
    outputs = manifest["outputs"] if mode == "app" else manifest["diagnostics"]
    if mode == "diagnostic":
        sp.OUTPUTS = outputs  # process-local, expands dependency closure without editing the app
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        started = time.perf_counter()
        model = sp.load_model(prune=True)
        constants = sp.build_constant_params(model)
        load_seconds = time.perf_counter() - started
        for index, case in enumerate(cases):
            scenario = manifest["scenarios"][case]
            ignored = [name for name in scenario if not sp._in_ns(model, name)]
            applied = sp.build_params(model, const_params=constants, scenario_inputs=scenario)
            params = {}
            for name, value in applied.items():
                if hasattr(value, "dims"):
                    params[name] = {"dims": list(value.dims), "coords": {d: list(value.coords[d].values)
                                    for d in value.dims}, "values": value.values.tolist()}
                else:
                    params[name] = {"dims": [], "coords": {}, "values": float(value)}
            suffix = f"{label}_{index:02d}_{case}" if label else case
            target = directory / "reference" / mode / suffix
            target.parent.mkdir(parents=True, exist_ok=True)
            target.with_suffix(".provenance.json").unlink(missing_ok=True)
            dump(target.with_suffix(".params.json"), params)
            dump(target.with_suffix(".inputs.json"), {"requested": scenario, "ignored_by_webapp": ignored})
            started = time.perf_counter()
            print(f"Running {mode}/{case}", flush=True)
            with phase_timers(model) as metrics:
                frame = sp.run_scenario(model, scenario_inputs=scenario, const_params=constants,
                                        timestamps=YEARS, flatten=mode == "app", return_columns=outputs)
            simulation_seconds = time.perf_counter() - started
            started = time.perf_counter()
            print(f"Serializing {mode}/{case}", flush=True)
            save_frame(target, frame, outputs, manifest, flattened=mode == "app")
            dump(target.with_suffix(".timing.json"), {
                "load_seconds": load_seconds if index == 0 else 0.,
                "simulation_and_capture_seconds": simulation_seconds,
                **metrics,
                "serialization_seconds": time.perf_counter() - started,
                "max_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "scenario": case, "mode": mode,
            })
            dump(target.with_suffix(".warnings.json"), [str(w.message) for w in caught])
            check_sources(manifest)
            dump(target.with_suffix(".provenance.json"), {
                "context": reference_provenance(manifest, cases, mode, label, index),
                "artifacts": {ext: digest(target.with_suffix(ext)) for ext in
                              (".json", ".npz", ".params.json", ".inputs.json", ".timing.json", ".warnings.json")},
            })
            print(f"Saved {mode}/{suffix}: {simulation_seconds:.2f}s", flush=True)
