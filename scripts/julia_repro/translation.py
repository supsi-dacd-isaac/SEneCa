from __future__ import annotations

import shutil
import subprocess
import time
import warnings
import re
import numpy as np

from .common import ROOT, RUNTIME, PINS, read, dump, digest, experiment_hashes
from . import builder_patch


def classify_warnings(messages, reference):
    """Only recognize interpolation notices already present in the Python oracle."""
    def data_notice(message):
        if "Data value missing or non-valid" not in message or "filled with the interpolation method" not in message:
            return None
        filename = re.search(r"File name:\s*'([^']+)'", message)
        cell = re.search(r"Reference cell:\s*'([^']+)'", message)
        if not filename or not cell:
            return None
        return (message.splitlines()[0].removeprefix("_ext_data_"),
                filename[1].split("/")[-1], cell[1])
    known = {data_notice(m) for m in reference} - {None}
    return [{**m, "classification": "existing_python_input_interpolation"
             if data_notice(m["message"]) in known else "blocking"} for m in messages]


def translate(directory, case):
    from pysd.translators.vensim.vensim_file import VensimFile
    from pysd.builders.julia.julia_model_builder import JuliaModelBuilder, JuliaSectionBuilder
    manifest = read(directory / "manifest.json")
    checkout = RUNTIME / "pysd"
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=checkout, text=True).strip()
    if actual != PINS["pysd_julia_commit"]:
        raise RuntimeError("Unexpected upstream PySD revision")
    if subprocess.check_output(["git", "diff", "--name-only"], cwd=checkout, text=True).strip():
        raise RuntimeError("Upstream checkout was modified; use only versioned experiment patches")
    params_path = directory / "reference/app" / f"{case}.params.json"
    params = read(params_path)
    target = directory / "julia" / case
    target.mkdir(parents=True, exist_ok=True)
    # Invalidate any previous successful translation before attempting a rebuild.
    dump(target / "translation.json", {"pass": False, "status": "incomplete"})
    source = target / "SURE_pysd_v3.mdl"
    shutil.copy2(ROOT / "Vensim/SURE_pysd_v3.mdl", source)
    for path in (ROOT / "Vensim").glob("*_pysd_v3.csv"):
        shutil.copy2(path, target / path.name)
    builder_patch.apply()
    original = JuliaSectionBuilder._process_element
    applied = set()

    def process(self, elem, identifier, is_control=False):
        if elem.name not in params:
            return original(self, elem, identifier, is_control)
        spec = params[elem.name]
        values = np.asarray(spec["values"], dtype=np.float64)
        if not np.isfinite(values).all():
            raise ValueError(f"Nonfinite calibrated parameter: {elem.name}")
        dims = manifest["variables"][elem.name].get("subscripts", [])
        if spec["dims"] != dims:
            raise ValueError(f"Parameter dimension mismatch: {elem.name}")
        for dim in dims:
            if spec["coords"][dim] != manifest["dimensions"][dim]:
                raise ValueError(f"Parameter coordinate mismatch: {elem.name}/{dim}")
        if not dims:
            expression = repr(float(values))
        else:
            # Julia is column-major; explicit values and labels make the mapping auditable.
            flattened = ", ".join(repr(float(x)) for x in values.ravel(order="F"))
            expression = f"reshape(Float64[{flattened}], {', '.join(map(str, values.shape))})"
        self.param_decls.append(f"@parameters {identifier} = {expression}")
        applied.add(elem.name)
        return []

    JuliaSectionBuilder._process_element = process
    started = time.perf_counter()
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                parsed = VensimFile(source, encoding="latin-1")
                parsed.parse()
                builder = JuliaModelBuilder(parsed.get_abstract_model(), data_format="json", backend="ode")
                path = builder.build_model()
                if applied != set(params):
                    raise ValueError(f"Unapplied calibrated parameters: {sorted(set(params)-applied)}")
            finally:
                messages = classify_warnings([{"category": w.category.__name__, "message": str(w.message)} for w in caught],
                                             read(directory / "reference/app" / f"{case}.warnings.json"))
                dump(target / "translation-warnings.json", messages)
        blocking = [m for m in messages if m["classification"] == "blocking"]
        if blocking:
            raise ValueError(f"Translation has {len(blocking)} blocking warnings; validation blocked")
        namespace = builder.sections[0].namespace.namespace
        export = []
        for name in manifest["diagnostics"]:
            key = namespace.get(name) or namespace.get(name.lower())
            if key is None:
                # Names in the builder are normalized; resolve by exact normalized spelling only.
                key = next((v for k, v in namespace.items() if k.lower() == name.lower()), None)
            if key is None:
                raise ValueError(f"Missing Julia output name: {name}")
            dims = manifest["variables"][name].get("subscripts", [])
            if builder.sections[0]._var_dims.get(key, []) != dims:
                raise ValueError(f"Julia dimension declaration differs for {name}: {builder.sections[0]._var_dims.get(key)} != {dims}")
            export.append({"name": name, "julia_name": key, "dims": dims,
                           "coords": {d: manifest["dimensions"][d] for d in dims}})
        dump(target / "export.json", export)
        dump(target / "export-app.json", [item for item in export if item["name"] in manifest["outputs"]])
        dump(target / "translation.json", {"pass": True, "model": path.name,
             "sha256": digest(path), "params_sha256": digest(params_path),
             "generated_hashes": {p.name: digest(p) for p in target.iterdir()
                                  if p.suffix in {".jl", ".csv", ".mdl", ".json"} and p.name != "translation.json"},
             "seconds": time.perf_counter()-started, "experiment": experiment_hashes(),
             "applied_parameters": sorted(applied), "upstream": actual})
    finally:
        JuliaSectionBuilder._process_element = original
