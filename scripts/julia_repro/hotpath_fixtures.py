"""Isolated Python-oracle tests for the current eight HS hotpaths.

The fixture gate is independent of full reference runs. It executes only the
unchanged helper definitions extracted from the current Python model, then
checks the Julia helper and a translated model containing all eight overrides.
"""
from __future__ import annotations

import ast
import itertools
from pathlib import Path
import warnings

import numpy as np

from .common import ROOT, CONFIG, RUNTIME, PINS, digest, dump, read, run_logged
from .hotpath_patch import HOTPATHS, HOTPATH_DIMS


def python_helpers():
    import xarray as xr
    source = ROOT / "Vensim/SURE_pysd_v3.py"
    tree = ast.parse(source.read_text())
    required = {"_hotpath_asarray", "_hotpath_idx_list", "_hotpath_da_like",
                "_hotpath_ms_normalize", "_hotpath_ms_exclude"}
    selected = [node for node in tree.body if
        isinstance(node, ast.FunctionDef) and node.name in required or
        isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_subscript_dict" for t in node.targets)]
    if {node.name for node in selected if isinstance(node, ast.FunctionDef)} != required:
        raise ValueError("Current Python HS helpers are missing")
    module = ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[]))
    namespace = {"np": np, "xr": xr}
    exec(compile(module, str(source), "exec"), namespace)
    return namespace


def oracle(target):
    import pysd
    import xarray as xr
    if pysd.__version__ != PINS["pysd_reference"]:
        raise ValueError("Hotpath oracle requires the pinned Python reference")
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    helpers = python_helpers()
    subs = helpers["_subscript_dict"]
    coordinates = {dim: subs[dim][:size] for dim, size in zip(HOTPATH_DIMS, (2,11,3,2,2))}
    shape = tuple(map(len, coordinates.values()))
    rng = np.random.default_rng(PINS["seed"])
    patterns = {
        "distinctive": np.arange(1, np.prod(shape)+1, dtype=np.float64).reshape(shape),
        "mixed_magnitudes": np.power(10., rng.uniform(-14., 8., shape)),
        "sparse": rng.uniform(.001, 1., shape)*(rng.random(shape)>.55),
    }
    # Keep at least one unexcluded renewable option positive in every cell.
    patterns["sparse"][:,subs["HS"].index("HeatPump"),:,:,:] += .125
    cases, models = [], []
    with (target/"inputs.bin").open("wb") as inputs, (target/"expected.bin").open("wb") as outputs:
        for pattern, data in patterns.items():
            utilities = {"Utility HS exp 3": data,
                         "Utility HS exp 3 no incentives": np.array(data[:,::-1,:,:,:]*1.125+.0001, order="C")}
            values = {name: xr.DataArray(value, coords=coordinates, dims=HOTPATH_DIMS)
                      for name, value in utilities.items()}
            indices = []
            for name, (source, exclusions) in HOTPATHS.items():
                excluded = [label for group in exclusions for label in subs.get(group,[group])]
                source_array = values[source].values
                expected = (helpers["_hotpath_ms_exclude"](values[source], excluded) if excluded else
                            helpers["_hotpath_da_like"](values[source], helpers["_hotpath_ms_normalize"](source_array)))
                if not np.isfinite(expected.values).all():
                    raise ValueError("Synthetic fixture unexpectedly produces nonfinite output")
                offset = inputs.tell()//8
                source_array.astype("<f8").ravel(order="C").tofile(inputs)
                expected.values.astype("<f8").ravel(order="C").tofile(outputs)
                cases.append({"name":name,"pattern":pattern,"shape":list(shape),"offset":offset,"elements":int(np.prod(shape)),
                              "excluded_indices":[subs["HS"].index(label)+1 for label in excluded],
                              "excluded_labels":excluded,"strides_bytes":list(source_array.strides)})
                indices.append(len(cases))
                values[name] = expected
            models.append({"name":pattern,"cases":indices,"utilities":{name:value.tolist() for name,value in utilities.items()}})
    dump(target/"cases.json",cases)
    dump(target/"model-inputs.json",models)
    dump(target/"metadata.json",{"dimensions":HOTPATH_DIMS,"coordinates":coordinates,"seed":PINS["seed"],
        "source_sha256":digest(ROOT/"Vensim/SURE_pysd_v3.py"),"cases":len(cases),"elements":sum(r["elements"] for r in cases),
        "inputs_sha256":digest(target/"inputs.bin"),"expected_sha256":digest(target/"expected.bin")})


def prepare(target):
    import pysd
    from . import builder_patch, hotpath_patch
    builder_patch.apply()
    hotpath_patch.apply()
    target = Path(target).resolve()
    metadata = read(target/"metadata.json")
    coordinates = metadata["coordinates"]
    domain = ",".join(HOTPATH_DIMS)
    summed = ",".join("HS!" if d=="HS" else d for d in HOTPATH_DIMS)
    models = []
    for model in read(target/"model-inputs.json"):
        lines = [f"{dim}: {','.join(labels)} ~~|" for dim,labels in coordinates.items()]
        lines.append("WithGas: Gas,GasST ~~|")
        for name, values in model["utilities"].items():
            array = np.asarray(values)
            for cell in itertools.product(*(range(len(labels)) for labels in coordinates.values())):
                labels = ",".join(coordinates[dim][i] for dim,i in zip(HOTPATH_DIMS,cell))
                lines.append(f"{name}[{labels}] = {float(array[cell])!r} ~~|")
        for name,(source,exclusions) in HOTPATHS.items():
            if not exclusions:
                lines.append(f"{name}[{domain}] = {source}[{domain}] / SUM({source}[{summed}]) ~~|")
            else:
                group = exclusions[0]
                selected = ",".join(group if d=="HS" else d for d in HOTPATH_DIMS)
                excluded_sum = ",".join((group+"!" if group=="WithGas" else group) if d=="HS" else d for d in HOTPATH_DIMS)
                subtract = f"SUM({source}[{excluded_sum}])" if group=="WithGas" else f"{source}[{excluded_sum}]"
                lines.append(f"{name}[{domain}] :EXCEPT: [{selected}] = {source}[{domain}] / (SUM({source}[{summed}]) - {subtract}) ~~|")
                lines.append(f"{name}[{selected}] = 0 ~~|")
        source = target/f"{model['name']}.mdl"
        source.write_text("{UTF-8}\n"+"\n".join(lines)+"\nINITIAL TIME=0 ~~|\nFINAL TIME=2 ~~|\nTIME STEP=1 ~~|\nSAVEPER=TIME STEP ~~|\n")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            path = pysd.translate_to_julia(source,data_format="json",backend="ode")
        if caught:
            raise ValueError("Hotpath translation warnings: "+"; ".join(str(w.message) for w in caught))
        models.append({"name":model["name"],"path":str(path),"cases":model["cases"],
                       "outputs":[name.lower().replace(" ","_") for name in HOTPATHS]})
    dump(target/"models.json",models)


def run(directory):
    from .execution import julia_command
    target = Path(directory)/"hotpath-fixtures"
    for function, environment in (("oracle","python-reference"),("prepare","python-julia")):
        command = f"from pathlib import Path; from scripts.julia_repro.hotpath_fixtures import {function}; {function}(Path({str(target)!r}))"
        run_logged([RUNTIME/environment/"bin/python","-B","-c",command],target/f"{function}.log")
    run_logged([*julia_command(),CONFIG/"test_hotpath.jl",target],target/"julia.log")
    result = read(target/"results.json")
    result["oracle"] = read(target/"metadata.json")
    dump(target/"results.json",result)
    return result
