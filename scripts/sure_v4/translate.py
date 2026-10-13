"""Translate the pinned v4 MDL, retaining tested general Julia builder patches.

The v3-only HS optimization is disabled: v4 again uses the source equations.
Existing reduction plans are inherited only for unchanged equations; the full
v4 simulation comparison remains mandatory and certifies no timings on failure.
"""
from __future__ import annotations

import importlib.metadata
from pathlib import Path
import shutil
import subprocess
import sys
import warnings

import numpy as np

from scripts.julia_repro.common import ROOT, RUNTIME, PINS, digest, dump, read
from scripts.julia_repro.inventory import closure
from scripts.julia_parametric.model import transform, replace_once


def build(directory):
    from pysd.translators.vensim.vensim_file import VensimFile
    from pysd.builders.julia.julia_model_builder import JuliaModelBuilder, JuliaSectionBuilder
    from scripts.julia_repro import builder_patch, hotpath_patch, reduction_policy, stateful_patch
    from scripts.julia_repro.translation import classify_warnings

    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=RUNTIME / "pysd", text=True).strip() == PINS["pysd_julia_commit"]
    assert not subprocess.check_output(["git", "diff", "--name-only"], cwd=RUNTIME / "pysd", text=True).strip()
    manifest = read(directory / "manifest.json")
    source, target = directory / "source", directory / "model"
    for name, expected in manifest["sources"].items():
        assert digest(source / name) == expected, name
    target.mkdir(parents=True, exist_ok=True)
    for path in (source / "Vensim").glob("*_pysd_v4.*"):
        if path.suffix in {".csv", ".mdl"}:
            shutil.copy2(path, target / path.name)
    old = read(ROOT / "benchmarks/sure-v4/inherited-policy.json")
    hotpaths = set(hotpath_patch.HOTPATHS)
    hotpath_patch.HOTPATHS.clear()
    builder_patch.apply()
    stateful_patch.configure_delay_update_policy(old["delay_update_policy"]["updated_reads"])
    policy = {**old["reduction_policy"], "entries": [e for e in old["reduction_policy"]["entries"] if e["component"] not in hotpaths]}
    reduction_policy.configure(policy)
    params = read(directory / "reference/diagnostic/01_base.params.json")
    original = JuliaSectionBuilder._process_element
    applied = set()

    def process(self, elem, identifier, is_control=False):
        if elem.name not in params:
            return original(self, elem, identifier, is_control)
        spec = params[elem.name]
        dims = manifest["variables"][elem.name].get("subscripts", [])
        assert dims == spec["dims"]
        values = np.asarray(spec["values"], dtype=float)
        assert np.isfinite(values).all()
        for dim in dims:
            assert spec["coords"][dim] == manifest["dimensions"][dim]
        expression = repr(float(values)) if not dims else (
            "reshape(Float64[" + ", ".join(repr(float(x)) for x in values.ravel(order="F"))
            + "], " + ", ".join(map(str, values.shape)) + ")")
        # Scenario controls are runtime getter equations in the parameterizer.
        if elem.name.strip('"').startswith("Provvedimento 1."):
            return original(self, elem, identifier, is_control)
        self.param_decls.append(f"@parameters {identifier} = {expression}")
        applied.add(elem.name)
        return []

    JuliaSectionBuilder._process_element = process
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        parsed = VensimFile(target / "SURE_pysd_v4.mdl", encoding="latin-1")
        parsed.parse()
        abstract = parsed.get_abstract_model()
        variables = {v["python_name"]: v for v in manifest["variables"].values()}
        reachable = closure(variables, manifest["diagnostics"])
        retained = {v["name"] for k, v in variables.items() if k in reachable}
        retained.update({"INITIAL TIME", "FINAL TIME", "TIME STEP", "SAVEPER"})
        for section in abstract.sections:
            section.elements = [e for e in section.elements if e.name in retained]
        builder = JuliaModelBuilder(abstract, data_format="json", backend="ode")
        path = builder.build_model()
    messages = [{"category": w.category.__name__, "message": str(w.message)} for w in caught]
    dump(target / "warnings.json", messages)
    classified = classify_warnings(messages, [w["message"] for w in read(directory / "reference/diagnostic/warnings.json")])
    dump(target / "warnings-classified.json", classified)
    assert not any(w["classification"] == "blocking" for w in classified), "Unsupported translation warning"
    missing = set(params) - applied
    assert missing == {'"Provvedimento 1.2"', '"Provvedimento 1.3"', '"Provvedimento 1.4"', '"Provvedimento 1.7"'}, missing
    generated, fields = transform(path.read_text(), list(manifest["scenarios"]["01_base"]), manifest["scenarios"]["01_base"])
    generated = replace_once(generated, "function seneca_allocate_available(request, pp, available)", "function sure_v3_allocate_available(request, pp, available)")
    generated += "\n" + (ROOT / "benchmarks/sure-v4/allocation.jl").read_text()
    model = target / "SURE_v4.jl"
    model.write_text(generated)
    export = []
    ns = builder.sections[0].namespace.namespace
    for name in manifest["diagnostics"]:
        key = next(v for k, v in ns.items() if k.lower() == name.lower())
        dims = manifest["variables"][name].get("subscripts", [])
        assert builder.sections[0]._var_dims.get(key, []) == dims, name
        export.append({"name": name, "julia_name": key, "dims": dims, "coords": {d: manifest["dimensions"][d] for d in dims}})
    dump(target / "export.json", export)
    dump(target / "build.json", {"revision": manifest["revision"], "model_sha256": digest(model),
         "translator_packages": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()},
         "parameters": fields, "applied_calibration": sorted(applied),
         "inherited_reduction_policy": policy, "delay_policy": old["delay_update_policy"],
         "hotpath_override_disabled": sorted(hotpaths), "validation_required": True,
         "artifacts": {p.name: digest(p) for p in target.iterdir() if p.is_file() and p.name != "build.json"}})


if __name__ == "__main__":
    build(Path(sys.argv[1]).resolve())
