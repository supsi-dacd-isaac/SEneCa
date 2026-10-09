"""Regenerate copies, verify quoted control names, and run complete scenarios."""
from __future__ import annotations

import ast
import importlib
import os
from pathlib import Path
import re
import shutil
import sys
from types import SimpleNamespace
import warnings

from scripts.julia_repro.common import ROOT, YEARS, check_sources, digest, dump, read
from scripts.julia_repro.results import save_frame, compare, load_snapshot
from scripts.julia_repro.inventory import columns_for
from scripts.julia_repro.energy import check_snapshot
from scripts.julia_repro.translation import classify_warnings
from .model import CONTROLS, resolve_name


def regenerate(target):
    import pysd
    import patch_model_sure as adapter
    import sure_paths
    target.mkdir(parents=True, exist_ok=False)
    for source in (ROOT / "Vensim").glob("*.csv"):
        if "_pysd" not in source.name:
            shutil.copy2(source, target / source.name)
    adapter.MODEL_DIR = target
    adapter.SRC_MDL = ROOT / "Vensim/SURE.mdl"
    adapter.paths = SimpleNamespace(pysd_mdl=lambda: target / "SURE_pysd_v3.mdl",
        data_csv=sure_paths.data_csv, describe=lambda: "Isolated regeneration from original SURE.mdl")
    adapter.main()
    source = target / "SURE_pysd_v3.mdl"
    original = (ROOT / "Vensim/SURE_pysd_v3.mdl").read_text(encoding="latin-1")
    generated = source.read_text(encoding="latin-1")
    if "Sketch information" not in original or "Sketch information" not in generated:
        raise ValueError("Unknown Vensim model/sketch boundary")
    if original.split("Sketch information", 1)[0] != generated.split("Sketch information", 1)[0]:
        raise ValueError("Original Vensim equations changed; separate model validation required")
    data_equal = {p.name: p.read_text(encoding="latin-1") == (ROOT / "Vensim" / p.name).read_text(encoding="latin-1")
                  for p in target.glob("*_pysd_v3.csv")}
    if len(data_equal) != 6 or not all(data_equal.values()):
        raise ValueError("Regenerated input data differ from the frozen release")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        model = pysd.read_vensim(str(source), initialize=False)
        py = Path(model.py_model_file)
        for module in ("fix_selfref_sure", "fix_allocate_sure", "patch_hotpaths_sure"):
            patch = importlib.import_module(module)
            patch.PY = py
            patch.main()
    dump(target / "regeneration.json", {"mdl_sha256": digest(source), "python_sha256": digest(py),
         "original_mdl_sha256": digest(ROOT / "Vensim/SURE.mdl"),
         "equations_identical": True, "data_identical_after_newline_normalization": data_equal,
         "warnings": [str(w.message) for w in caught], "pysd": pysd.__version__})
    return py


def run(reference, target):
    if os.environ.get("PYTHONHASHSEED") != "0" or sys.flags.hash_randomization != 0:
        raise RuntimeError("Start interpreter with PYTHONHASHSEED=0")
    import pysd
    import sure_paths
    sure_paths.set_variant("v3")
    import sure_pysd as sp
    manifest = read(reference / "manifest.json")
    check_sources(manifest)
    target.mkdir(parents=True, exist_ok=True)
    sources = [Path(__file__), ROOT / "scripts/julia_parametric/model.py", ROOT / "Vensim/SURE.mdl"]
    sources += [ROOT / name for name in ("patch_model_sure.py", "fix_selfref_sure.py", "fix_allocate_sure.py", "patch_hotpaths_sure.py")]
    sources += [p for p in (ROOT / "Vensim").glob("*.csv") if "_pysd" not in p.name]
    context = {str(p): digest(p) for p in sources}
    py = regenerate(target / "regenerated")
    current = ROOT / "Vensim/SURE_pysd_v3.py"
    def functions(path):
        result = {}
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.FunctionDef):
                node.decorator_list = []
                result[node.name] = ast.dump(node, include_attributes=False)
        return result
    old, new = functions(current), functions(py)
    difference = [name for name in sorted(set(old) | set(new)) if old.get(name) != new.get(name)]
    report = {"pass": False, "regenerated_function_body_differences": difference, "names": {}, "cases": {},
              "source_context": context, "manifest_sha256": digest(reference / "manifest.json"), "energy": {}}
    if difference:
        raise ValueError(f"Regenerated Python equations differ: {difference}")
    dump(target / "report.json", report)
    # Use the regenerated model for all runs. Identical decorated function ASTs
    # demonstrate preservation of equations and the current postprocessors.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        model = pysd.load(str(py))
        model.select_submodel(vars=sp._output_closure_vars(model))
    dump(target / "load-warnings.json", [str(w.message) for w in caught])
    for name in CONTROLS:
        canonical = resolve_name(name, model._namespace)
        report["names"][name] = {"canonical": canonical, "python": model._namespace[canonical],
                                 "legacy_lookup": sp._in_ns(model, name), "resolved_lookup": sp._in_ns(model, canonical)}
    scenarios = {"base": dict(manifest["scenarios"]["base"])}
    for name in CONTROLS:
        scenarios[name.replace(" ", "_").replace(".", "_")] = {**scenarios["base"], name: 1.}
    scenarios["all_controls"] = {**scenarios["base"], **dict.fromkeys(CONTROLS, 1.)}
    scenarios["mid"] = manifest["scenarios"]["mid"]
    scenarios["high"] = manifest["scenarios"]["high"]
    dump(target / "scenarios.json", scenarios)
    # Direct scenario parameters are resolved explicitly, then passed through
    # the existing webapp runner. The original filtering code remains intact.
    # This auxiliary is already a dependency of the 52 app outputs. Capturing
    # it does not enlarge the pruned model or change the state update ordering.
    outputs = list(dict.fromkeys(manifest["outputs"] + ["Hourly demand and PHS"]))
    known_warnings = read(reference / "reference/app/base.warnings.json")
    report["warnings"] = {"regeneration": [], "load": [], "runs": {}}
    parameters_set = set(sp.build_params(model, scenario_inputs={resolve_name(k, model._namespace): v for k, v in scenarios["base"].items()}))
    calibrated_overrides = set(read(reference / "reference/app/base.params.json")) - set(scenarios["base"])
    for message in read(target / "regenerated/regeneration.json")["warnings"]:
        match = re.match(r"Variable '(.*?)' is defined with different (types|subtypes): '([^']+)'\.", message)
        if not match:
            raise ValueError(f"Unreviewed translation warning: {message}")
        name, kind, values = match.groups()
        field = "comp_type" if kind == "types" else "comp_subtype"
        existing = manifest["variables"].get(name, {}).get(field, "")
        if ((name in parameters_set and name not in calibrated_overrides) or
                set(map(str.strip, existing.split(","))) != set(map(str.strip, values.split(",")))):
            raise ValueError(f"New or parameter-sensitive metadata warning: {message}")
        report["warnings"]["regeneration"].append({"message": message, "classification":
            "existing_mixed_metadata_complete_calibrated_override" if name in calibrated_overrides else
            "existing_mixed_component_metadata_not_overridden"})
    for message in read(target / "load-warnings.json"):
        if message == "Selecting submodel, to run the full model again use model.reload()":
            report["warnings"]["load"].append({"message": message, "classification": "explicit_app_dependency_pruning"})
        else:
            record = classify_warnings([{"message": message}], known_warnings)[0]
            if record["classification"] == "blocking":
                raise ValueError(f"Unreviewed load warning: {message}")
            report["warnings"]["load"].append(record)
    app_columns = [column for name in manifest["outputs"] for column in columns_for(name, manifest)]
    for label, values in [*scenarios.items(), ("base_after_high", scenarios["base"])]:
        resolved = {resolve_name(name, model._namespace): value for name, value in values.items()}
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            frame = sp.run_scenario(model, scenario_inputs=resolved, return_columns=outputs, timestamps=YEARS)
        destination = target / "reference" / label
        destination.parent.mkdir(parents=True, exist_ok=True)
        save_frame(destination, frame.loc[:, app_columns], manifest["outputs"], manifest)
        diagnostic = target / "diagnostic" / label
        diagnostic.parent.mkdir(parents=True, exist_ok=True)
        save_frame(diagnostic, frame, outputs, manifest)
        report["energy"][label] = check_snapshot(diagnostic)
        dump(destination.with_suffix(".warnings.json"), [str(w.message) for w in caught])
        classified = [({"message": str(w.message), "classification": "existing_python_runtime_warning"}
                       if str(w.message) in known_warnings else
                       classify_warnings([{"message": str(w.message)}], known_warnings)[0]) for w in caught]
        report["warnings"]["runs"][label] = classified
        if any(w["classification"] == "blocking" for w in classified):
            raise ValueError(f"Unreviewed scenario warning: {label}")
        applied = sp.build_params(model, scenario_inputs=resolved)
        params = {name: ({"dims": list(value.dims), "coords": {d: list(value.coords[d].values) for d in value.dims}, "values": value.values.tolist()}
                        if hasattr(value, "dims") else {"dims": [], "coords": {}, "values": float(value)})
                  for name, value in applied.items()}
        dump(destination.with_suffix(".params.json"), params)
        dump(destination.with_suffix(".requested.json"), {"requested": values, "resolved_names": resolved})
        if label == "base":
            comparison = compare(reference / "reference/app/base", destination, exact=True)
            report["regenerated_base_matches_current"] = comparison["pass"]
        elif label == "base_after_high":
            comparison = compare(target / "reference/base", destination, exact=True)
            report["base_after_high_exact"] = comparison["pass"]
        else:
            comparison = compare(target / "reference/base", destination, exact=True)
            report["cases"][label] = {"changed_outputs": [row["variable"] for row in comparison["rows"] if not row["pass"]],
                                      "requested": values, "applied": resolved}
        dump(target / "comparisons" / f"{label}.json", comparison)
        dump(target / "report.json", report)
        print(f"Regenerated Python {label}: completed", flush=True)
    report["pass"] = (report["regenerated_base_matches_current"] and
                       report["base_after_high_exact"] and all(item["pass"] for item in report["energy"].values()) and
                       all(not item["legacy_lookup"] and item["resolved_lookup"] for item in report["names"].values()) and
                       all(item["changed_outputs"] for item in report["cases"].values()))
    check_sources(manifest)
    if any(digest(path) != sha for path, sha in context.items()):
        raise ValueError("Control experiment sources changed")
    report["artifacts"] = {str(p.relative_to(target)): digest(p) for p in sorted(target.rglob("*"))
                           if p.is_file() and p != target / "report.json"}
    dump(target / "report.json", report)
    if not report["pass"]:
        raise RuntimeError("Control probe did not satisfy all checks")
    return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=ROOT / "dist/julia-repro/20261009-reproducibility")
    parser.add_argument("--run-dir", type=Path, default=ROOT / "dist/julia-parametric/20261009/controls")
    args = parser.parse_args()
    run(args.reference.resolve(), args.run_dir.resolve())
