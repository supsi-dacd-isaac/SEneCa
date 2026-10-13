"""Isolated energy/PHS dependency trace; never changes a frozen run manifest.

Run as a module from the repository root with --run-dir <existing-run>:
  python-reference/bin/python -m scripts.julia_repro.trace reference --run-dir ...
  python-julia/bin/python -m scripts.julia_repro.trace export --run-dir ...
  julia --project=benchmarks/julia-repro benchmarks/julia-repro/run_model.jl \\
    <run>/debug/phs-trace/model-wrapper.jl <run>/debug/phs-trace/export.json \\
    <run>/debug/phs-trace/julia
  python-reference/bin/python -m scripts.julia_repro.trace compare --run-dir ...

Use common.environment() for all processes. The reference preserves the original
diagnostic pruning, applied parameters and stateful order, and requires all 102
shared outputs to remain bitwise identical. Export creates a read-only wrapper
for external DATA functions that the normal model observer does not expose.
This is diagnostic evidence and does not relax the full validation gate.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys
import time
import warnings

from scripts.julia_repro.common import ROOT, YEARS, PINS, read, dump, digest, check_sources
from scripts.julia_repro.inventory import closure, columns_for
from scripts.julia_repro.results import save_frame, compare as compare_snapshots, load_snapshot


def select(directory, depth=5):
    manifest = read(directory / "manifest.json")
    variables = {v["python_name"]: v for v in manifest["variables"].values()}
    retained = closure(variables, manifest["diagnostics"])
    energy_names = {
        "Solar electricity produced hourly", "Hourly electricity grid demand",
        "Hourly imported electricity", "Hourly exported electricity",
        "Hourly available supply by Supplier", "Total electricity produced hourly",
        "Hourly electricity demand and import", "Share grid demand per hour",
        "Electricity dispatched", "Electricity market price",
    }
    seeds = {k for k, v in variables.items() if k in retained and
             ("phs" in v["name"].lower() or v["name"] in energy_names)}
    deps = {k: set(v.get("depends_on", {})) for k, v in variables.items()}
    for variable in variables.values():
        for key, parts in variable.get("other_deps", {}).items():
            deps[key] = set(parts.get("initial", {})) | set(parts.get("step", {}))
    reached = set(seeds)
    frontier = set(seeds)
    for _ in range(depth):
        frontier = set().union(*(deps.get(k, set()) for k in frontier)) - reached
        reached.update(frontier)
    extra = sorted(variables[k]["name"] for k in reached if k in variables and k != "time")
    outputs = list(dict.fromkeys(manifest["diagnostics"] + extra))
    lookup = [name for name in outputs if manifest["variables"][name].get("comp_type") == "Lookup"]
    if lookup:
        raise ValueError(f"Trace must explicitly evaluate lookup arguments: {lookup}")
    selection = {
        "depth": depth, "outputs": outputs, "shared_outputs": manifest["diagnostics"],
        "seeds": sorted(variables[k]["name"] for k in seeds),
        "outside_app_dependency_closure": sorted(v["name"] for k, v in variables.items()
              if k not in retained and "phs" in v["name"].lower()),
        "manifest_sha256": digest(directory / "manifest.json"),
        "time_axis": YEARS,
    }
    dump(directory / "debug/phs-trace/selection.json", selection)
    return manifest, selection


def reference(directory):
    manifest, selection = select(directory)
    check_sources(manifest)
    if importlib.metadata.version("pysd") != PINS["pysd_reference"]:
        raise RuntimeError("Trace requires the frozen Python reference environment")
    current = {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()}
    differences = {k: (v, current.get(k)) for k, v in manifest["packages"].items()
                   if k not in {"pip", "setuptools"} and current.get(k) != v}
    if differences:
        raise RuntimeError(f"Reference environment drift: {differences}")
    sys.path.insert(0, str(ROOT))
    import sure_paths
    sure_paths.set_variant("v3")
    import sure_pysd as sp
    # Preserve the exact pruning traversal and stateful update order of the
    # frozen diagnostic reference. Every extra output is already reachable.
    sp.OUTPUTS = manifest["diagnostics"]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        started = time.perf_counter()
        model = sp.load_model(prune=True)
        dump(directory / "debug/phs-trace/stateful-order.json",
             [s.py_name for s in model._dynamicstateful_elements])
        constants = sp.build_constant_params(model)
        scenario = manifest["scenarios"]["base"]
        applied = sp.build_params(model, const_params=constants, scenario_inputs=scenario)
        params = {}
        for name, value in applied.items():
            params[name] = ({"dims": list(value.dims),
                "coords": {d: list(value.coords[d].values) for d in value.dims},
                "values": value.values.tolist()} if hasattr(value, "dims") else
                {"dims": [], "coords": {}, "values": float(value)})
        if params != read(directory / "reference/diagnostic/base.params.json"):
            raise RuntimeError("PHS trace changed applied parameters")
        print(f"Running expanded PHS trace: {len(selection['outputs'])} variables", flush=True)
        frame = sp.run_scenario(model, scenario_inputs=scenario, const_params=constants,
                               timestamps=YEARS, flatten=False, return_columns=selection["outputs"])
        target = directory / "debug/phs-reference"
        save_frame(target, frame, selection["outputs"], manifest, flattened=False)
        shared = compare_snapshots(directory / "reference/diagnostic/base", target,
                         outputs=selection["shared_outputs"], exact=True)
        dump(directory / "debug/phs-trace/shared-check.json", shared)
        import numpy as np
        _, arrays = load_snapshot(target)
        nonfinite = {name: int((~np.isfinite(values)).sum()) for name, values in arrays.items()
                     if not np.isfinite(values).all()}
        result = {"pass": shared["pass"] and not nonfinite,
            "variables": len(selection["outputs"]), "elements": sum(a.size for a in arrays.values()),
            "shared_variables": len(selection["shared_outputs"]), "shared_bitwise_identical": shared["pass"],
            "nonfinite": nonfinite, "seconds": time.perf_counter() - started,
            "manifest_sha256": selection["manifest_sha256"],
            "params_sha256": digest(directory / "reference/diagnostic/base.params.json"),
            "reference_sha256": digest(target.with_suffix(".npz")),
            "requested_scenario": scenario}
    dump(directory / "debug/phs-trace/warnings.json", [{"category": w.category.__name__, "message": str(w.message)} for w in caught])
    dump(directory / "debug/phs-trace/reference-result.json", result)
    print(result, flush=True)
    if not result["pass"]:
        raise RuntimeError("Expanded PHS trace does not reproduce the frozen oracle")


def export(directory):
    manifest, selection = select(directory)
    from scripts.julia_repro import builder_patch
    builder_patch.apply()
    from pysd.translators.vensim.vensim_file import VensimFile
    from pysd.builders.julia.namespace import JuliaNamespaceManager
    parsed = VensimFile(ROOT / "Vensim/SURE_pysd_v3.mdl", encoding="latin-1")
    parsed.parse()
    abstract = parsed.get_abstract_model()
    variables = {v["python_name"]: v for v in manifest["variables"].values()}
    reachable = closure(variables, manifest["diagnostics"])
    retained = {v["name"] for key, v in variables.items() if key in reachable}
    retained.update({"INITIAL TIME", "FINAL TIME", "TIME STEP", "SAVEPER"})
    namespace = JuliaNamespaceManager()
    for elem in abstract.sections[0].elements:
        if elem.name in retained:
            namespace.add_to_namespace(elem.name)
    existing = {item["name"]: item for item in read(directory / "julia/base/export.json")}
    generated = (directory / "julia/base/SURE_pysd_v3.jl").read_text()
    rows = []
    additions = []
    for name in selection["outputs"]:
        key = namespace.get(name)
        if key is None:
            raise ValueError(f"Unresolved Julia trace variable: {name}")
        dims = manifest["variables"][name].get("subscripts", [])
        if f'"{key}" =>' not in generated:
            # The normal observer contains stocks/auxiliaries/constants. DATA
            # remain external functions; expose only pure read-only evaluation.
            if manifest["variables"][name].get("comp_type") != "Data":
                raise ValueError(f"Julia observer does not export {name}: {key}")
            args = [f"i{i}" for i in range(len(dims))]
            expression = f"{key}({', '.join(args + ['c.time'])})"
            if dims:
                loops = [f"i{i} in 1:{len(manifest['dimensions'][dim])}" for i, dim in enumerate(dims)]
                expression = f"[{expression} for {', '.join(loops)}]"
            additions.append(f'_observed_getters[{json.dumps(key)}] = c -> {expression}')
        row = {"name": name, "julia_name": key, "dims": dims,
               "coords": {d: manifest["dimensions"][d] for d in dims}}
        if name in existing and existing[name] != row:
            raise ValueError(f"Trace namespace differs from original: {name}")
        rows.append(row)
    dump(directory / "debug/phs-trace/export.json", rows)
    # Freeze the generated inputs beside the wrapper. Root can retranslate the
    # scenario while a diagnostic trace compiles without mixing generations.
    frozen = directory / "debug/phs-trace/model"
    frozen.mkdir(parents=True, exist_ok=True)
    model_file = frozen / "SURE_pysd_v3.jl"
    data_file = frozen / "SURE_pysd_v3_data.json"
    for file in (model_file, data_file):
        shutil.copy2(directory / "julia/base" / file.name, file)
    wrapper = directory / "debug/phs-trace/model-wrapper.jl"
    wrapper.write_text(f'Base.include(@__MODULE__, {json.dumps(str(model_file))})\n' +
                       "\n".join(additions) + "\n")
    dump(directory / "debug/phs-trace/export-result.json", {
        "pass": True, "variables": len(rows), "manifest_sha256": selection["manifest_sha256"],
        "external_observers": len(additions), "wrapper_sha256": digest(wrapper),
        "generated_model_sha256": digest(model_file), "generated_data_sha256": digest(data_file)})
    print(f"Export ready: {len(rows)} variables", flush=True)


def compare(directory):
    import numpy as np
    manifest = read(directory / "manifest.json")
    exports = read(directory / "debug/phs-trace/export.json")
    raw = directory / "debug/phs-trace/julia"
    timing = read(raw / "timing.json")
    if timing["years"] != YEARS or timing["byte_order"] != "little":
        raise ValueError("Incomplete or incompatible Julia trace")
    metadata, arrays = {"years": timing["years"], "variables": {}}, {}
    for i, item in enumerate(exports):
        name, key = item["name"], f"v{i:04d}"
        columns = columns_for(name, manifest)
        array = np.fromfile(raw / f"{key}.bin", dtype="<f8")
        if array.size != len(YEARS) * len(columns):
            raise ValueError(f"Incomplete Julia trace: {name}")
        arrays[key] = array.reshape(len(YEARS), len(columns))
        metadata["variables"][name] = {"key": key, "columns": columns,
            "dims": item["dims"], "coords": item["coords"], "discrete": name in manifest.get("discrete", [])}
    candidate = directory / "debug/phs-candidate"
    np.savez_compressed(candidate.with_suffix(".npz"), **arrays)
    metadata["sha256"] = digest(candidate.with_suffix(".npz"))
    dump(candidate.with_suffix(".json"), metadata)
    result = compare_snapshots(directory / "debug/phs-reference", candidate)
    dump(directory / "debug/phs-trace/comparison.json", result)
    failures = sorted((r for r in result["rows"] if not r["pass"]),
                      key=lambda r: (r.get("year", 0), r["variable"]))
    dump(directory / "debug/phs-trace/first-divergences.json", failures)
    print(f"PHS trace: {len(failures)}/{len(exports)} variables differ", flush=True)
    for row in failures[:20]:
        print(row, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("reference", "export", "compare"))
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    globals()[args.phase](args.run_dir.resolve())
