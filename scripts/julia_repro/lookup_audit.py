"""Capture SURE's actual np.interp calls while certifying unchanged outputs."""
from pathlib import Path
import importlib.metadata
import os
import sys
import warnings

import numpy as np

from .common import CONFIG, ROOT, RUNTIME, YEARS, check_sources, digest, dump, read, run_logged
from .reference import reference_ready
from .results import load_snapshot, save_frame


def capture(directory, case="base"):
    directory = Path(directory).resolve()
    manifest = read(directory/"manifest.json")
    check_sources(manifest)
    installed = {d.metadata["Name"]:d.version for d in importlib.metadata.distributions()}
    if (os.environ.get("PYTHONHASHSEED") != "0" or sys.flags.hash_randomization != 0 or
            any(installed.get(n) != v for n,v in manifest["packages"].items()
                if n not in {"pip","setuptools"})):
        raise RuntimeError("Lookup audit requires the frozen Python environment and hash seed")
    if not reference_ready(directory, manifest, [case], mode="diagnostic"):
        raise RuntimeError("Lookup audit requires a certified frozen reference")
    target = directory/"debug/lookup-audit"/case
    target.mkdir(parents=True, exist_ok=True)
    dump(target/"capture.json", {"pass":False,"case":case,"status":"incomplete"})
    import sure_paths
    sure_paths.set_variant("v3")
    import sure_pysd as sp
    original_outputs = sp.OUTPUTS
    sp.OUTPUTS = manifest["diagnostics"]
    records, offset = [], 0
    with (target/"input.bin").open("wb") as inputs, (target/"expected.bin").open("wb") as expected:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            model = sp.load_model(prune=True)
            constants = sp.build_constant_params(model)
            module = model.components._components
            original_numpy = module.np

            class Proxy:
                def __getattr__(self,name):
                    return getattr(original_numpy,name)

                def interp(self, x, xs, ys, *args, **kwargs):
                    nonlocal offset
                    if args or kwargs:
                        raise ValueError("Unverified np.interp arguments")
                    value = original_numpy.interp(x,xs,ys)
                    a,b = np.asarray(x,dtype=np.float64),np.asarray(value,dtype=np.float64)
                    if not np.isfinite(a).all() or not np.isfinite(b).all():
                        raise ValueError("Nonfinite inline lookup sample")
                    a.ravel(order="C").astype("<f8").tofile(inputs)
                    b.ravel(order="C").astype("<f8").tofile(expected)
                    parent = sys._getframe(1)
                    records.append({"component":parent.f_code.co_name,"line":parent.f_lineno,
                        "time":float(model.time()),"phase":getattr(model.time,"stage","unknown"),
                        "xs":list(xs),"ys":list(ys),"shape":list(a.shape),
                        "offset":offset,"count":a.size})
                    offset += a.size
                    return value

            module.np = Proxy()
            try:
                frame = sp.run_scenario(model, scenario_inputs=manifest["scenarios"][case],
                    const_params=constants,timestamps=YEARS,flatten=False,return_columns=manifest["diagnostics"])
            finally:
                module.np = original_numpy
                sp.OUTPUTS = original_outputs
    save_frame(target/"snapshot",frame,manifest["diagnostics"],manifest,flattened=False)
    _,reference = load_snapshot(directory/"reference/diagnostic"/case)
    _,candidate = load_snapshot(target/"snapshot")
    bitwise = all(np.array_equal(reference[n].view(np.uint64),candidate[n].view(np.uint64)) for n in reference)
    if not bitwise:
        raise RuntimeError("Lookup instrumentation changed the frozen reference")
    dump(target/"records.json",records)
    dump(target/"warnings.json",[{"category":w.category.__name__,"message":str(w.message)} for w in caught])
    check_sources(manifest)
    if not reference_ready(directory,manifest,[case],mode="diagnostic"):
        raise RuntimeError("Reference provenance changed during lookup capture")
    artifacts = ["input.bin","expected.bin","records.json","snapshot.json","snapshot.npz","warnings.json"]
    report={"pass":True,"case":case,"uint64_bitwise":True,"shared_outputs":len(reference),
        "calls":len(records),"cells":offset,"sources":manifest["sources"],"pins":manifest["pins"],
        "packages":manifest["packages"],"implementation_sha256":digest(Path(__file__)),
        "reference":{suffix:digest((directory/"reference/diagnostic"/case).with_suffix(suffix))
            for suffix in (".json",".npz",".params.json",".provenance.json")},
        "artifacts":{name:digest(target/name) for name in artifacts}}
    dump(target/"capture.json",report)
    return report


def run(directory, case="base"):
    from .execution import julia_command
    directory=Path(directory).resolve()
    target=directory/"debug/lookup-audit"/case
    command=f"from scripts.julia_repro.lookup_audit import capture; capture({str(directory)!r},case={case!r})"
    run_logged([RUNTIME/"python-reference/bin/python","-B","-c",command],target/"capture.log")
    run_logged([*julia_command(),CONFIG/"test_lookup_audit.jl",target],target/"julia.log")
    result=read(target/"results.json")
    result.update({"capture_sha256":digest(target/"capture.json"),"kernel_sha256":digest(CONFIG/"lookup.jl"),
                   "harness_sha256":digest(CONFIG/"test_lookup_audit.jl")})
    dump(target/"results.json",result)
    return result
