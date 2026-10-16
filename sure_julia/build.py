"""Build the audited SURE profile from versioned Vensim source and calibration.

Run with /opt/translator/bin/python -m sure_julia.build OUTPUT_DIRECTORY.
No simulation is performed by the translator; validation is a separate gate.
"""
import pickle
import shutil
import subprocess
import sys
import warnings
from pathlib import Path

import numpy as np

from .catalog import closure, defaults, inventory, outputs
from .common import CONFIG, ROOT, MODEL_VARIANT, MODEL_REVISION, MODEL_PY, MODEL_MDL, CALIBRATION, digest, dump, read, model_sources
from .translator.parameterize import CONTROLS, replace_once, resolve_name, transform
from .pv_budget import FLOWS


def build(target):
    from pysd.translators.vensim.vensim_file import VensimFile
    from pysd.builders.julia.julia_model_builder import JuliaModelBuilder, JuliaSectionBuilder
    from .translator import builder_patch, reduction_policy, stateful_patch, hotpath_patch
    target = Path(target).resolve()
    target.mkdir(parents=True, exist_ok=True)
    dump(target / "build.json", {"complete": False})
    checkout = Path(__import__("pysd").__file__).resolve().parents[1]
    git = ["git", "-c", f"safe.directory={checkout}"]
    if subprocess.check_output(git + ["rev-parse", "HEAD"], cwd=checkout, text=True).strip() != "8991d119e139029d4dec712d257cf5fcc3549b8f":
        raise ValueError("Wrong translator revision")
    if subprocess.check_output(git + ["diff", "--name-only"], cwd=checkout, text=True).strip():
        raise ValueError("Translator checkout must be clean")
    variables, dimensions = inventory()
    requested = outputs()
    with CALIBRATION.open("rb") as stream:
        calibrated = pickle.load(stream)
    scenario = defaults()
    params = {resolve_name(name, variables): spec for name, spec in calibrated.items()}
    params.update({resolve_name(name, variables): {"dims": [], "coords": {}, "values": value} for name, value in scenario.items()})
    hotpaths = set(hotpath_patch.HOTPATHS)
    builder_patch.apply()
    stateful_patch.configure_delay_update_policy({})
    policy = read(Path(__file__).with_name("translation-policy.json"))["reduction_policy"]
    policy = {**policy, "entries": [e for e in policy["entries"] if e["component"] not in hotpaths]}
    # v5 distributes demolition over all PV/battery categories directly;
    # the former PV/battery SUM site no longer exists in its source equation.
    policy["entries"] = [e for e in policy["entries"] if e["component"] != "Building demolition by archetype"]
    policy["entries"] = [{**e, "component": "Requested " + e["component"]} if e["component"] in FLOWS else e
                         for e in policy["entries"]]
    reduction_policy.configure(policy)
    original = JuliaSectionBuilder._process_element
    applied = set()

    def process(self, elem, identifier, is_control=False):
        if elem.name not in params or elem.name.strip('"') in CONTROLS:
            return original(self, elem, identifier, is_control)
        spec = params[elem.name]
        dims = variables[elem.name].get("subscripts", [])
        if dims != spec["dims"] or any(list(spec["coords"][d]) != dimensions[d] for d in dims):
            raise ValueError(f"Calibration coordinates differ: {elem.name}")
        values = np.asarray(spec["values"], dtype=np.float64)
        if not np.isfinite(values).all():
            raise ValueError(f"Nonfinite calibration: {elem.name}")
        expression = repr(float(values)) if not dims else ("reshape(Float64[" +
            ", ".join(repr(float(v)) for v in values.ravel(order="F")) + "], " + ", ".join(map(str, values.shape)) + ")")
        self.param_decls.append(f"@parameters {identifier} = {expression}")
        applied.add(elem.name)
        return []

    source_hashes = model_sources()
    for path in [MODEL_MDL, *(ROOT / "Vensim").glob(f"*_pysd_{MODEL_VARIANT}.csv")]:
        shutil.copy2(path, target / path.name)
    JuliaSectionBuilder._process_element = process
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            parsed = VensimFile(target / MODEL_MDL.name, encoding="latin-1")
            parsed.parse()
            abstract = parsed.get_abstract_model()
            original_source = VensimFile(ROOT / "Vensim/SURE.mdl", encoding="latin-1")
            original_source.parse()
            old_elements = {e.name: e for s in original_source.get_abstract_model().sections for e in s.elements}
            new_elements = {e.name: e for s in abstract.sections for e in s.elements}
            request_audit = []
            for name in FLOWS:
                old, new = old_elements["Requested " + name].components, new_elements["Requested " + name].components
                if len(old) != len(new) or any(repr(a.ast) != repr(b.ast) or a.subscripts != b.subscripts
                                              for a, b in zip(old, new)):
                    raise ValueError(f"Original PV request/EXCEPT clauses changed: {name}")
                request_audit.append({"component": name, "requested_component": "Requested " + name,
                                      "identical_clauses": len(old)})
            dump(target / "pv-request-audit.json", {"pass": True, "requests": request_audit,
                 "rebound_sum_sites": sum(e["component"].startswith("Requested ") for e in policy["entries"])})
            retained = closure(variables, requested) | set(params) | {"INITIAL TIME", "FINAL TIME", "TIME STEP", "SAVEPER"}
            for section in abstract.sections:
                section.elements = [e for e in section.elements if e.name in retained]
            builder = JuliaModelBuilder(abstract, data_format="json", backend="ode")
            path = builder.build_model()
        messages = [{"category": w.category.__name__, "message": str(w.message)} for w in caught]
        dump(target / "warnings.json", messages)
        # Only existing data interpolation notices are candidates for review.
        # Validation matches these against the Python input notices by file/cell.
        if any("Data value missing or non-valid" not in w["message"] or "filled with the interpolation method" not in w["message"] for w in messages):
            raise ValueError("Unclassified translator warning; inspect warnings.json")
        missing = set(params) - applied - {resolve_name(n, variables) for n in CONTROLS}
        if missing:
            raise ValueError(f"Unapplied parameters: {sorted(missing)}")
        generated, fields = transform(path.read_text(), list(scenario), scenario)
        generated = replace_once(generated, "function seneca_allocate_available(request, pp, available)", "function sure_v3_allocate_available(request, pp, available)")
        generated += "\n" + (CONFIG / "priority_allocation.jl").read_text()
        model = target / "SURE.jl"
        model.write_text(generated)
        namespace = builder.sections[0].namespace.namespace
        export = []
        for name in requested:
            key = next(v for k, v in namespace.items() if k.lower() == name.lower())
            dims = variables[name].get("subscripts", [])
            if builder.sections[0]._var_dims.get(key, []) != dims:
                raise ValueError(f"Dimension mismatch: {name}")
            export.append({"name": name, "julia_name": key, "dims": dims, "coords": {d: dimensions[d] for d in dims}})
        dump(target / "export.json", export)
        metadata = {"complete": True, "validated": False, "model": model.name, "parameters": fields, "defaults": scenario,
                    "model_revision": MODEL_REVISION,
                    "sources": source_hashes,
                    "implementation": {str(p.relative_to(ROOT)): digest(p) for p in Path(__file__).parent.rglob("*")
                                       if p.is_file() and p.suffix in {".py", ".jl", ".toml", ".lock", ".json"} and target not in p.parents},
                    "artifacts": {p.name: digest(p) for p in target.iterdir() if p.is_file() and p.name != "build.json"},
                    "delay_policy": "synchronous pre-step", "float": "Float64", "years": list(range(2011, 2051))}
        dump(target / "build.json", metadata)
        print(f"Built {len(requested)} outputs and {len(fields)} reusable parameters: {model}", flush=True)
    finally:
        JuliaSectionBuilder._process_element = original


if __name__ == "__main__":
    build(sys.argv[1])
