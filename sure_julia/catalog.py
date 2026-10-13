"""Explicit labels, parameters and dependency closure for the supported model."""
import ast
import math
from pathlib import Path

from .common import ROOT, read


def defaults():
    from pysd_explore_config import base_ui_values
    from pv_batteries import exploratory_config as cfg
    result = base_ui_values()
    for name in cfg.POLICY_ORDER:
        result.setdefault(name, 0.0)
    result[cfg.EXPLORATORY_SWITCH] = 0.0
    result.update({name: 0.0 for name in cfg.UNCERTAINTY_ORDER})
    if len(result) != 40:
        raise ValueError("Reaudit the SURE parameter contract")
    return result


def parameters(values=None):
    result = defaults()
    if extra := set(values or {}) - set(result):
        raise ValueError(f"Unknown parameters: {sorted(extra)}")
    result.update({k: float(v) for k, v in (values or {}).items()})
    if not all(math.isfinite(v) for v in result.values()):
        raise ValueError("Nonfinite scenario parameter")
    from pysd_explore_config import ALL_INPUTS
    for spec in ALL_INPUTS:
        if (spec.binary or spec.choice_labels or spec.name.startswith("Provvedimento ")) and result[spec.name] not in spec.values:
            raise ValueError(f"Invalid categorical parameter: {spec.name}")
    if result["Exploratory analysis"] not in (0, 1) or result["Cantonal PV support"] not in (0, 1):
        raise ValueError("Invalid exploratory switch")
    return result


def inventory():
    tree = ast.parse((ROOT / "Vensim/SURE_pysd_v4.py").read_text())
    variables, dimensions = {}, {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_subscript_dict" for t in node.targets):
            dimensions = ast.literal_eval(node.value)
        if isinstance(node, ast.FunctionDef):
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr == "add":
                    fields = {k.arg: ast.literal_eval(k.value) for k in dec.keywords if k.arg in
                              {"name", "subscripts", "depends_on", "other_deps", "comp_type", "comp_subtype"}}
                    variables[fields["name"]] = {**fields, "python_name": node.name}
    return variables, dimensions


def outputs():
    from sure_pysd import OUTPUTS
    from pv_batteries import exploratory_config as exp, pv_batteries_config as pv, risanamento_config as ris
    policy = read(Path(__file__).with_name("translation-policy.json"))
    native = read(ROOT / "Vensim_test_runs/inputs.json")
    extra = ["Hourly demand and PHS", "Priority vector by supplier", "Marginal cost by supplier",
             "Hourly imported electricity", "PHS hourly supply", "Hour factor PHS consumption",
             "Seasonal PHS monthly demand", "Seasonal PHS monthly production",
             "Seasonal PHS hourly demand", "Seasonal PHS hourly production"]
    return list(dict.fromkeys(list(OUTPUTS) + policy["diagnostics"] + native["output_bases"] + extra
                + list(pv.GMD_VARS) + list(ris.GMD_VARS) + list(exp.GMD_VARS)
                + list(exp.SCALAR_OUTPUTS.values()) + [exp.CANTONAL_FUNDS_VAR]))


def closure(variables, requested):
    names = {v["name"]: v["python_name"] for v in variables.values()}
    deps = {v["python_name"]: set(v.get("depends_on", {})) for v in variables.values()}
    for v in variables.values():
        for name, parts in v.get("other_deps", {}).items():
            deps[name] = set(parts.get("initial", {})) | set(parts.get("step", {}))
    seen, todo = set(), [names[n] for n in requested]
    while todo:
        name = todo.pop()
        if name not in seen:
            seen.add(name)
            todo.extend(deps.get(name, ()))
    return {v["name"] for v in variables.values() if v["python_name"] in seen}
