from __future__ import annotations

import ast
import collections
import importlib.metadata
import itertools
import hashlib
import json
import platform
import random
import re
import subprocess
import sys

from .common import ROOT, PINS, dump, source_hashes, experiment_hashes


def model_inventory():
    tree = ast.parse((ROOT / "Vensim/SURE_pysd_v3.py").read_text())
    variables, dimensions = {}, {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "_subscript_dict" for t in node.targets):
            dimensions = ast.literal_eval(node.value)
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            fields = {k.arg: ast.literal_eval(k.value) for k in dec.keywords
                      if k.arg in {"name", "subscripts", "depends_on", "other_deps",
                                   "comp_type", "comp_subtype"}}
            if "name" in fields:
                variables[node.name] = fields
    text = (ROOT / "Vensim/SURE_pysd_v3.mdl").read_text(encoding="latin-1")
    text = re.sub(r"\\\s*\n\s*", "", text)
    exclusions = [{"name": m[1].strip(), "rank": len(m[2].split(","))}
                  for m in re.finditer(r"(?m)^([^\n=~|]+?)\[([^\]]+)\]\s*:EXCEPT:", text)]
    return variables, dimensions, exclusions


def closure(variables, outputs):
    names = {v["name"]: k for k, v in variables.items()}
    deps = {k: set(v.get("depends_on", {})) for k, v in variables.items()}
    for v in variables.values():
        for name, parts in v.get("other_deps", {}).items():
            deps[name] = set(parts.get("initial", {})) | set(parts.get("step", {}))
    seen, todo = set(), [names[n] for n in outputs]
    while todo:
        name = todo.pop()
        if name not in seen:
            seen.add(name)
            todo.extend(deps.get(name, ()))
    return seen


def scenarios(inputs):
    base = {i.name: float(i.default) for i in inputs}
    candidates = [("base", base)]
    for name, selector in [("low", min), ("mid", lambda x: sorted(x)[len(x)//2]), ("high", max)]:
        candidates.append((name, {i.name: float(selector(i.values)) for i in inputs}))
    for n, inp in enumerate(inputs):
        choices = inp.values if inp.binary or inp.choice_labels else [min(inp.values), max(inp.values)]
        for j, value in enumerate(choices):
            candidates.append((f"lever_{n:02d}_{j:02d}", {**base, inp.name: float(value)}))
    rng = random.Random(PINS["seed"])
    for i in range(8):
        candidates.append((f"random_{i:02d}", {v.name: float(rng.choice(v.values)) for v in inputs}))
    unique, aliases, known = {}, {}, {}
    for name, params in candidates:
        key = tuple(sorted(params.items()))
        if key in known:
            aliases[name] = known[key]
        else:
            known[key] = name
            unique[name] = params
    return unique, aliases


def make_inventory(directory):
    sys.path.insert(0, str(ROOT))
    if platform.python_version() != PINS["python"]:
        raise RuntimeError(f"Inventory requires the reference Python {PINS['python']}")
    import sure_paths
    sure_paths.set_variant("v3")
    import sure_pysd as sp
    import pysd_explore_config as cfg
    from scripts.data_release import verify_installed, load_pin
    verify_installed(ROOT, load_pin(ROOT / "data-release.json"))
    variables, dimensions, exclusions = model_inventory()
    reachable = closure(variables, sp.OUTPUTS)
    six = [v["name"] for k, v in variables.items() if k in reachable and len(v.get("subscripts", [])) == 6]
    relevant_except = sorted({e["name"] for e in exclusions
                              if any(k in reachable and v["name"] == e["name"] for k, v in variables.items())})
    discrete = [i.pysd_name for i in cfg.ALL_INPUTS if (i.binary or i.choice_labels)
                and any(v["name"] == i.pysd_name for v in variables.values())]
    diagnostics = list(dict.fromkeys(sp.OUTPUTS + six + relevant_except +
                                    ["Hourly demand and PHS", "Electricity dispatched"] + discrete))
    by_name = {v["name"]: {**v, "python_name": k} for k, v in variables.items()}
    missing = set(diagnostics) - set(by_name)
    if missing:
        raise ValueError(f"Missing required outputs: {sorted(missing)}")
    cases, aliases = scenarios(cfg.ALL_INPUTS)
    scenario_hash = hashlib.sha256(json.dumps(cases, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    manifest = {
        "schema": 1, "pins": PINS, "sources": source_hashes(), "experiment": experiment_hashes(),
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "python": sys.version, "platform": platform.platform(), "machine": platform.machine(),
        "packages": dict(sorted((d.metadata["Name"], d.version) for d in importlib.metadata.distributions())),
        "dimensions": dimensions, "variables": by_name, "outputs": sp.OUTPUTS,
        "diagnostics": diagnostics, "six_dimensional": six, "exclusions": exclusions,
        "discrete": discrete,
        "rank_counts": dict(collections.Counter(len(v.get("subscripts", [])) for v in variables.values())),
        "scenarios": cases, "aliases": aliases,
        "scenarios_sha256": scenario_hash,
        "packed_coordinates": {
            "Archetipo": list(itertools.product(*(dimensions[d] for d in ("District", "Performance", "Type")))),
            "HS": dimensions["HS"],
            "Configurazione": list(itertools.product(dimensions["PVpanel"], dimensions["Battery"])),
        },
        "ignored_ui_levers": [i.name for i in cfg.ALL_INPUTS if i.pysd_name not in by_name],
    }
    dump(directory / "manifest.json", manifest)
    return manifest


def columns_for(variable, manifest):
    dims = manifest["variables"][variable].get("subscripts", [])
    if not dims:
        return [variable]
    return [variable + "[" + ",".join(x) + "]" for x in
            itertools.product(*(manifest["dimensions"][d] for d in dims))]
