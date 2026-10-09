"""Capture the frozen Python SUM callsites and actual NumPy memory layouts.

The baseline module is instrumented only in memory. Every observation is bound
to an exact Python source position and the recorded outputs must remain UInt64
identical. Vensim binding requires matching source order, references and reduced
ranges; ambiguous components are reported instead of receiving a guessed map.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import fields, is_dataclass
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import warnings

import numpy as np

from .common import ROOT, PINS, YEARS, check_sources, digest, dump, read
from .results import compare, load_snapshot, save_frame


def _position(node):
    return (node.lineno, node.end_lineno, node.col_offset, node.end_col_offset)


def catalog(manifest):
    """Return source-position inventory and strictly verified Vensim bindings."""
    from pysd.translators.vensim.vensim_file import VensimFile
    from pysd.translators.structures.abstract_expressions import CallStructure, ReferenceStructure

    variables = manifest["variables"]
    python_names = {v["python_name"] for v in variables.values()}
    owner_to_component = {v["python_name"]: v["name"] for v in variables.values()}
    for variable in variables.values():
        owner_to_component.update({owner: variable["name"] for owner in variable.get("other_deps", {})})
    normalized = {name.lower().replace(" ", "_").strip('"'): v["python_name"] for name, v in variables.items()}
    source = ROOT / "Vensim/SURE_pysd_v3.py"
    text = source.read_text()
    source_lines = [line.encode("utf-8") for line in text.splitlines(keepends=True)]
    def source_segment(node):
        if node.lineno == node.end_lineno:
            return source_lines[node.lineno-1][node.col_offset:node.end_col_offset].decode("utf-8")
        return b"".join([source_lines[node.lineno-1][node.col_offset:],
                         *source_lines[node.lineno:node.end_lineno-1],
                         source_lines[node.end_lineno-1][:node.end_col_offset]]).decode("utf-8")
    tree = ast.parse(text)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    python_sites = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "sum"):
            continue
        owner, ancestor = None, node
        while ancestor in parents:
            ancestor = parents[ancestor]
            if isinstance(ancestor, ast.FunctionDef):
                owner = ancestor.name
                break
            if isinstance(ancestor, ast.Assign) and parents.get(ancestor) is tree:
                owner = next((t.id for t in ancestor.targets if isinstance(t, ast.Name)), None)
                break
        references = sorted(sub.func.id for sub in ast.walk(node.args[0])
                            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
                            and sub.func.id in python_names)
        dim = next((keyword.value for keyword in node.keywords if keyword.arg == "dim"), None)
        reduced = sorted(s.removesuffix("!") for s in ast.literal_eval(dim)) if dim else None
        python_sites.append({"position": list(_position(node)), "owner": owner,
                             "component": owner_to_component.get(owner), "references": references,
                             "reduced_ranges": reduced, "source": source_segment(node)})
    python_sites.sort(key=lambda site: (site["position"][0], site["position"][2]))

    parsed = VensimFile(ROOT / "Vensim/SURE_pysd_v3.mdl", encoding="latin-1")
    parsed.parse()
    vensim_sites = []
    def references(node):
        found = []
        if isinstance(node, ReferenceStructure):
            key = node.reference.lower().replace(" ", "_").strip('"')
            found.append(normalized.get(key, "__unmapped__:" + key))
        elif isinstance(node, CallStructure):
            # Builtin function identifiers are not model-variable references.
            key = node.function.reference.lower().replace(" ", "_").strip('"')
            if key in normalized:
                found.append(normalized[key])
            for argument in node.arguments:
                found.extend(references(argument))
        elif is_dataclass(node):
            for field in fields(node):
                found.extend(references(getattr(node, field.name)))
        elif isinstance(node, (list, tuple)):
            for child in node:
                found.extend(references(child))
        return found

    def reduced_ranges(node):
        found = set()
        if isinstance(node, ReferenceStructure) and node.subscripts is not None:
            found.update(s[:-1] for s in node.subscripts.subscripts if s.endswith("!"))
        elif isinstance(node, CallStructure):
            if node.function.reference.upper() in {"SUM", "VMAX", "VMIN", "PROD"}:
                return found
            found.update(reduced_ranges(node.function))
            for argument in node.arguments:
                found.update(reduced_ranges(argument))
        elif is_dataclass(node):
            for field in fields(node):
                found.update(reduced_ranges(getattr(node, field.name)))
        elif isinstance(node, (list, tuple)):
            for child in node:
                found.update(reduced_ranges(child))
        return found

    def visit(node, element, component, path):
        if isinstance(node, CallStructure) and node.function.reference.upper() == "SUM":
            vensim_sites.append({"element": element, "component_index": component,
                                 "ast_path": path, "references": sorted(references(node.arguments[0])),
                                 "reduced_ranges": sorted(reduced_ranges(node.arguments[0]))})
        if is_dataclass(node):
            for field in fields(node):
                visit(getattr(node, field.name), element, component, path + "." + field.name)
        elif isinstance(node, (list, tuple)):
            for index, child in enumerate(node):
                visit(child, element, component, path + f"[{index}]")
    for section in parsed.get_abstract_model().sections:
        for element in section.elements:
            for index, component in enumerate(element.components):
                visit(component.ast, element.name, index, "ast")

    py_groups, ven_groups = defaultdict(list), defaultdict(list)
    for site in python_sites:
        py_groups[site["component"]].append(site)
    for site in vensim_sites:
        ven_groups[site["element"]].append(site)
    bindings, rejected = [], []
    for component in sorted(set(py_groups) | set(ven_groups), key=str):
        py, ven = py_groups[component], ven_groups[component]
        signatures_match = len(py) == len(ven) and all(
            a["references"] == b["references"] and a["reduced_ranges"] == b["reduced_ranges"]
            for a, b in zip(py, ven))
        if not signatures_match:
            rejected.append({"component": component, "reason": "source-order count or signature mismatch",
                             "python": py, "vensim": ven})
            continue
        for index, (a, b) in enumerate(zip(py, ven)):
            binding = {"component": component, "ordinal": index, "python_position": a["position"],
                       "vensim_component_index": b["component_index"], "vensim_ast_path": b["ast_path"],
                       "references": a["references"], "reduced_ranges": a["reduced_ranges"]}
            binding["id"] = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()
            bindings.append(binding)
    return {"python": python_sites, "vensim": vensim_sites, "bindings": bindings, "rejected": rejected}


def run(directory, case="base"):
    if os.environ.get("PYTHONHASHSEED") != "0" or importlib.metadata.version("pysd") != PINS["pysd_reference"]:
        raise RuntimeError("Reduction audit requires the frozen Python version and hash seed")
    directory = Path(directory).resolve()
    manifest = read(directory / "manifest.json")
    check_sources(manifest)
    installed = {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()}
    if any(installed.get(name) != version for name, version in manifest["packages"].items()
           if name not in {"pip", "setuptools"}):
        raise RuntimeError("Reduction audit environment drift")
    target = directory / "debug/reduction-audit" / case
    target.mkdir(parents=True, exist_ok=True)
    sites = catalog(manifest)
    dump(target / "sites.json", sites)
    by_position = {tuple(site["position"]): site for site in sites["python"]}
    bindings = {tuple(site["python_position"]): site["id"] for site in sites["bindings"]}
    records, values, code_positions, observed, unmapped_calls = {}, {}, {}, set(), []
    import sure_paths
    sure_paths.set_variant("v3")
    import sure_pysd as sp
    sp.OUTPUTS = manifest["diagnostics"]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        model = sp.load_model(prune=True)
        constants = sp.build_constant_params(model)
        module = model.components._components
        original = module.sum
        def capture(x, dim=None):
            result = original(x, dim)
            frame = sys._getframe(1)
            positions = code_positions.get(frame.f_code)
            if positions is None:
                positions = code_positions[frame.f_code] = list(frame.f_code.co_positions())
            position = tuple(positions[frame.f_lasti // 2])
            site = by_position.get(position)
            if site is None:
                call = {"function": frame.f_code.co_name, "line": frame.f_lineno,
                        "position": list(position), "file": frame.f_code.co_filename}
                if call not in unmapped_calls:
                    unmapped_calls.append(call)
                return result
            observed.add(position)
            array = np.asarray(x.values)
            packed = np.array(array, copy=True, order="K")
            dimensions = list(x.dims)
            reduce_dims = list(dim or dimensions)
            layout = {"position": list(position), "component": site["component"], "owner": site["owner"],
                      "binding": bindings.get(position), "dims": dimensions, "shape": list(array.shape),
                      "strides": list(array.strides), "packed_strides": list(packed.strides),
                      "reduce_dims": reduce_dims, "reduce_axes": [dimensions.index(d) for d in reduce_dims],
                      "physical_axes_slow_to_fast": sorted(range(array.ndim), key=lambda axis: -abs(packed.strides[axis])),
                      "c_contiguous": bool(packed.flags.c_contiguous), "f_contiguous": bool(packed.flags.f_contiguous),
                      "result_dims": list(result.dims) if hasattr(result, "dims") else [],
                      "result_shape": list(np.asarray(result).shape)}
            key = hashlib.sha256(json.dumps(layout, sort_keys=True).encode()).hexdigest()
            if key not in records:
                sample = f"v{len(records):04d}"
                records[key] = {**layout, "sample": sample, "observations": {}, "calls": 0,
                                "finite_input": bool(np.isfinite(array).all())}
                values[sample] = packed
                values[sample + "_result"] = np.asarray(result, dtype=np.float64).copy()
            record = records[key]
            stage_time = f"{getattr(model.time, 'stage', 'unknown')}:{float(model.time()):g}"
            record["observations"][stage_time] = record["observations"].get(stage_time, 0) + 1
            record["calls"] += 1
            return result
        module.sum = capture
        try:
            frame = sp.run_scenario(model, scenario_inputs=manifest["scenarios"][case], const_params=constants,
                                    timestamps=YEARS, flatten=False, return_columns=manifest["diagnostics"])
        finally:
            module.sum = original
    save_frame(target / "snapshot", frame, manifest["diagnostics"], manifest, flattened=False)
    comparison = compare(directory / "reference/diagnostic" / case, target / "snapshot", exact=True)
    _, expected = load_snapshot(directory / "reference/diagnostic" / case)
    _, actual = load_snapshot(target / "snapshot")
    bitwise = all(np.array_equal(expected[name].view(np.uint64), actual[name].view(np.uint64)) for name in expected)
    dump(target / "comparison.json", comparison)
    dump(target / "layouts.json", list(records.values()))
    np.savez_compressed(target / "samples.npz", **values)
    dump(target / "warnings.json", [str(w.message) for w in caught])
    report = {"pass": comparison["pass"] and bitwise and not unmapped_calls, "case": case,
              "uint64_bitwise": bitwise, "calls": sum(record["calls"] for record in records.values()),
              "observed_sites": len(observed), "layouts": len(records), "catalog_sites": len(sites["python"]),
              "bound_sites": len(sites["bindings"]), "rejected_components": len(sites["rejected"]),
              "unmapped_calls": unmapped_calls,
              "unobserved_positions": [site["position"] for site in sites["python"] if tuple(site["position"]) not in observed],
              "sources": manifest["sources"], "pins": manifest["pins"], "packages": manifest["packages"],
              "implementation": digest(Path(__file__)), "hash_seed": "0",
              "stateful_order": [state.py_name for state in model._dynamicstateful_elements],
              "reference": {suffix: digest((directory / "reference/diagnostic" / case).with_suffix(suffix))
                            for suffix in (".json", ".npz", ".params.json", ".provenance.json")},
              "artifacts": {name: digest(target / name) for name in
                            ("sites.json", "layouts.json", "samples.npz", "snapshot.json", "snapshot.npz")}}
    dump(target / "result.json", report)
    print({key: report[key] for key in ("pass", "case", "uint64_bitwise", "calls", "observed_sites", "layouts", "bound_sites", "rejected_components", "unmapped_calls")}, flush=True)
    if not report["pass"]:
        raise RuntimeError("Reduction audit changed the oracle or could not identify actual Python callsites")
    return report
