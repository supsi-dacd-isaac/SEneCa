from __future__ import annotations

import ast
import importlib.metadata
import os
from pathlib import Path
import subprocess
import sys
import time
import warnings

import numpy as np

from scripts.julia_repro.common import ROOT, YEARS, digest, dump, read
from scripts.julia_repro.results import save_frame

REVISION = "17db1f4245c6bb0e8ef41a4cac5e8d3a6817cac6"


def prepare(directory):
    directory.mkdir(parents=True, exist_ok=False)
    source = directory / "source"
    names = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", REVISION], cwd=ROOT, text=True).splitlines()
    selected = [n for n in names if n in {
        "sure_pysd.py", "sure_paths.py", "constants_ref_v4.pkl", "data-release.json",
        "Vensim/SURE.mdl", "Vensim_test_runs/inputs.json", "Vensim_test_runs/outputs.parquet"
    } or (n.startswith("Vensim/") and "_pysd_v4." in n)
        or (n.startswith("pv_batteries/") and n.endswith("_config.py"))]
    for name in selected:
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(subprocess.check_output(["git", "show", f"{REVISION}:{name}"], cwd=ROOT))
    tree = ast.parse((source / "Vensim/SURE_pysd_v4.py").read_text())
    dimensions, variables = {}, {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_subscript_dict" for t in node.targets):
            dimensions = ast.literal_eval(node.value)
        if isinstance(node, ast.FunctionDef):
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr == "add":
                    fields = {k.arg: ast.literal_eval(k.value) for k in dec.keywords
                              if k.arg in {"name", "subscripts", "depends_on", "other_deps", "comp_type", "comp_subtype"}}
                    variables[fields["name"]] = {**fields, "python_name": node.name}
    native = read(source / "Vensim_test_runs/inputs.json")
    old = read(ROOT / "benchmarks/sure-v4/inherited-policy.json")
    diagnostics = list(dict.fromkeys(native["output_bases"] + old["diagnostics"]))
    manifest = {"revision": REVISION, "sources": {n: digest(source / n) for n in selected},
                "variables": variables, "dimensions": dimensions, "outputs": old["outputs"],
                "diagnostics": diagnostics, "native_outputs": native["output_bases"],
                "scenarios": {r["id"]: r["inputs"] for r in native["runs"]},
                "discrete": old.get("discrete", []), "packages": old["packages"],
                "native_metadata": native, "pins": old["pins"]}
    dump(directory / "manifest.json", manifest)
    return manifest


def run(directory, mode, cases):
    assert os.environ.get("PYTHONHASHSEED") == "0", "Start Python with PYTHONHASHSEED=0"
    manifest = read(directory / "manifest.json")
    source = directory / "source"
    for name, expected in manifest["sources"].items():
        assert digest(source / name) == expected, name
    packages = {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()}
    assert all(packages.get(k) == v for k, v in manifest["packages"].items() if k not in {"pip", "setuptools"}), "Environment drift"
    sys.path.insert(0, str(source))
    import sure_paths
    sure_paths.set_variant("v4")
    import sure_pysd as sp
    assert sp.OUTPUTS == manifest["outputs"], "App outputs changed"
    outputs = manifest["outputs"] if mode == "app" else manifest["diagnostics"]
    sp.OUTPUTS = outputs
    target = directory / "reference" / mode
    target.mkdir(parents=True, exist_ok=True)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        started = time.perf_counter()
        model = sp.load_model(prune=True)
        constants = sp.build_constant_params(model)
        dump(target / "load.json", {"seconds": time.perf_counter() - started,
             "dynamic_order": [s.py_name for s in model._dynamicstateful_elements],
             "initialization_order": model.initialize_order, "packages": packages})
        for i, case in enumerate(cases):
            case_name = case if case not in cases[:i] else f"{case}_repeat_{i}"
            prefix = target / case_name
            assert not prefix.with_suffix(".npz").exists(), "Do not overwrite results"
            scenario = manifest["scenarios"][case]
            assert all(sp.namespace_key(model, name) is not None for name in scenario)
            applied = sp.build_params(model, const_params=constants, scenario_inputs=scenario)
            serialized = {}
            for name, value in applied.items():
                serialized[name] = ({"dims": list(value.dims), "coords": {d: list(value.coords[d].values) for d in value.dims},
                                     "values": value.values.tolist()} if hasattr(value, "dims") else
                                    {"dims": [], "coords": {}, "values": float(value)})
            dump(prefix.with_suffix(".params.json"), serialized)
            print(f"Starting {mode}/{case_name}", flush=True)
            started = time.perf_counter()
            df = sp.run_scenario(model, const_params=constants, scenario_inputs=scenario,
                                 timestamps=YEARS, flatten=False, return_columns=outputs)
            elapsed = time.perf_counter() - started
            assert list(df.index) == YEARS and set(df.columns) == set(outputs)
            save_frame(prefix, df, outputs, manifest, flattened=False)
            dump(prefix.with_suffix(".timing.json"), {"seconds": elapsed, "scenario": scenario})
            dump(target / "warnings.json", [{"category": w.category.__name__, "message": str(w.message)} for w in caught])
            print(f"Completed {mode}/{case_name}: {elapsed:.2f}s", flush=True)


if __name__ == "__main__":
    directory = Path(sys.argv[2]).resolve()
    if sys.argv[1] == "prepare":
        prepare(directory)
    else:
        run(directory, sys.argv[1], sys.argv[3:])
