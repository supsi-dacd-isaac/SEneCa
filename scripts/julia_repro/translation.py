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
    experiment = experiment_hashes()
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
    from .delay_audit import ensure_policy
    from .stateful_patch import configure_delay_update_policy
    from .reduction_policy import ensure_policy as ensure_reduction_policy, configure as configure_reductions
    delay_policy = ensure_policy(directory)
    reduction_policy = ensure_reduction_policy(directory, case)
    for name in list(delay_policy["evidence"]):
        base = directory / name.removesuffix(".audit.json")
        for suffix in (".json", ".npz", ".inputs.npz", ".comparison.json"):
            proof = base.with_suffix(suffix)
            delay_policy["evidence"][str(proof.relative_to(directory))] = digest(proof)
    configure_delay_update_policy(delay_policy["updated_reads"])
    configure_reductions(reduction_policy)
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
                abstract = parsed.get_abstract_model()
                # Match the Python app's dependency pruning, including initial
                # dependencies and every requested diagnostic. Equations and
                # dimensions of the retained model remain unchanged.
                from .inventory import closure
                variables = {v["python_name"]: v for v in manifest["variables"].values()}
                reachable = closure(variables, manifest["diagnostics"])
                retained = {v["name"] for key, v in variables.items() if key in reachable}
                retained.update({"INITIAL TIME", "FINAL TIME", "TIME STEP", "SAVEPER"})
                removed = []
                for section in abstract.sections:
                    removed.extend(e.name for e in section.elements if e.name not in retained)
                    section.elements = [e for e in section.elements if e.name in retained]
                builder = JuliaModelBuilder(abstract, data_format="json", backend="ode")
                path = builder.build_model()
                used_policy = getattr(builder.sections[0], "_seneca_delay_update_policy_used", {})
                if set(used_policy) != set(delay_policy["updated_reads"]):
                    raise ValueError("Python sequential-update policy was not completely applied")
                used_reductions = getattr(builder.sections[0].namespace, "_seneca_sum_policy_used", {})
                expected_reductions = {entry["id"]: entry["plan"] for entry in reduction_policy["entries"]}
                if used_reductions != expected_reductions:
                    raise ValueError(f"SUM layout policy was not completely applied: {set(expected_reductions)-set(used_reductions)}")
                from .hotpath_patch import HOTPATHS
                python_hotpaths = getattr(builder.sections[0], "_seneca_python_hotpaths", [])
                hotpath_names = [item["name"] for item in python_hotpaths]
                if len(hotpath_names) != len(set(hotpath_names)) or set(hotpath_names) != set(HOTPATHS) & retained:
                    raise ValueError("Current Python HS normalization optimizations were not completely applied")
                from .numpy_math_patch import platform_contract
                numpy_math = getattr(builder.sections[0], "_seneca_numpy_math", {})
                if numpy_math.get("platform") != platform_contract() or numpy_math.get("operations") != ["EXP", "POWER"]:
                    raise ValueError("Frozen NumPy elementary math compatibility was not applied")
                numpy_lookup = getattr(builder.sections[0], "_seneca_numpy_lookup", {})
                if not numpy_lookup.get("count") or len(set(numpy_lookup["tables"])) != numpy_lookup["count"]:
                    raise ValueError("Frozen NumPy lookup compatibility was not applied")
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
        if experiment_hashes() != experiment:
            raise RuntimeError("Experiment changed during translation; regenerate under a fixed version")
        dump(target / "translation.json", {"pass": True, "model": path.name,
             "sha256": digest(path), "params_sha256": digest(params_path),
             "generated_hashes": {p.name: digest(p) for p in target.iterdir()
                                  if p.suffix in {".jl", ".csv", ".mdl", ".json"} and p.name != "translation.json"},
             "seconds": time.perf_counter()-started, "experiment": experiment,
             "pruned_elements": removed,
             "data_expressions": getattr(builder.sections[0], "_seneca_data_expressions", []),
             "delay_update_policy": delay_policy, "delay_update_policy_used": used_policy,
             "reduction_policy": reduction_policy, "reduction_policy_used": used_reductions,
             "python_hotpaths": python_hotpaths,
             "numpy_math": numpy_math,
             "numpy_lookup": numpy_lookup,
             "applied_parameters": sorted(applied), "upstream": actual})
    finally:
        JuliaSectionBuilder._process_element = original
        configure_delay_update_policy({})
        configure_reductions({})
