"""Executable external-input regressions against unmodified PySD 3.14.3."""
from __future__ import annotations

import itertools
from pathlib import Path
import shutil
import warnings

from .common import CONFIG, RUNTIME, dump, read, run_logged

CONTROL = "\nINITIAL TIME = 0 ~~|\nFINAL TIME = 6 ~~|\nTIME STEP = 1 ~~|\nSAVEPER = TIME STEP ~~|\n"
QUERIES = [-1., 0., .1, 1., 2., 2.1, 3., 5., 6., 7.]


def prepare(target):
    import pysd
    from . import builder_patch, external_patch, ode_patch
    builder_patch.apply()
    external_patch.apply()
    ode_patch.apply()
    target.mkdir(parents=True, exist_ok=True)
    models = []
    for kind in ("data", "lookup"):
        for rank in range(7):
            name = f"{kind}_rank_{rank}"
            dims = [f"D{i}" for i in range(rank)]
            signature = "[" + ",".join(dims) + "]" if dims else ""
            bang = "[" + ",".join(d + "!" for d in dims) + "]" if dims else ""
            declarations = "\n".join(f"{d}: z{i},a{i} ~~|" for i, d in enumerate(dims))
            rows = ["Time,0,2,6"]
            for cell in itertools.product((0, 1), repeat=rank):
                number = 10 + sum((i + 1)*7**axis for axis, i in enumerate(cell))
                rows.append(f"Cell,{number},{number*2 + 3},{number*5 - 7}")
            (target / f"{name}.csv").write_text("\n".join(rows) + "\n")
            text = ""
            for row, fixed in enumerate(itertools.product((0, 1), repeat=max(rank-1, 0))):
                spec = [f"{'z' if index == 0 else 'a'}{axis}" for axis, index in enumerate(fixed)]
                if rank:
                    spec.append(dims[-1])
                component = "[" + ",".join(spec) + "]" if spec else ""
                cell = 2 + row*(2 if rank else 1)
                if kind == "data":
                    text += f"X{component}:INTERPOLATE: := GET DIRECT DATA('{name}.csv','','1','B{cell}') ~~|\n"
                else:
                    text += f"X{component} = GET DIRECT LOOKUPS('{name}.csv','','1','B{cell}') ~~|\n"
            if kind == "data":
                text += f"Y{signature} = X{signature} ~~|\n"
                sum_expr = f"SUM(X{bang})" if dims else "X"
            else:
                text += f"Y{signature} = X{signature}(Time) ~~|\n"
                sum_expr = f"SUM(X{bang}(Time))" if dims else "X(Time)"
            text += f"Stock = INTEG({sum_expr}, 0) ~~|"
            models.append({"name": name, "kind": kind, "dims": dims,
                           "text": declarations + "\n" + text + CONTROL})
    for mode in ("hold backward", "look forward", "raw"):
        name = mode.replace(" ", "_")
        (target / f"{name}.csv").write_text("Time,0,2,6\nValue,10,21,80\n")
        text = f"X:{mode.upper()}: := GET DIRECT DATA('{name}.csv','','1','B2') ~~|\nY = X ~~|\nStock = INTEG(1, 0) ~~|" + CONTROL
        models.append({"name": name, "kind": "data", "dims": [], "text": text})
    for rank in (1, 2, 3):
        dims = [f"D{i}" for i in range(rank)]
        declarations = "\n".join(f"{d}: z{i},a{i} ~~|" for i, d in enumerate(dims))
        text = declarations + "\n"
        for cell in itertools.product((0, 1), repeat=rank):
            number = 10 + sum((i + 1)*7**axis for axis, i in enumerate(cell))
            spec = ",".join(f"{'z' if index == 0 else 'a'}{axis}" for axis, index in enumerate(cell))
            text += f"X[{spec}] ((0,{number}),(2,{2*number+3}),(6,{5*number-7})) ~~|\n"
        signature = ",".join(dims)
        bang = ",".join(d + "!" for d in dims)
        text += f"Y[{signature}] = X[{signature}](Time) ~~|\nStock = INTEG(SUM(X[{bang}](Time)),0) ~~|"
        models.append({"name": f"inline_rank_{rank}", "kind": "lookup", "dims": dims, "text": text + CONTROL})
    # Split and deliberately reordered definitions; the subgroup is not axis 1.
    for kind in ("data", "lookup"):
        name = f"{kind}_subgroup"
        (target / f"{name}.csv").write_text("Time,0,2,6\nA,10,21,80\nB,30,49,90\nC,50,77,110\nD,70,88,120\nE,130,170,220\nF,190,230,300\n")
        declarations = "D0: z0,a0 ~~|\nD1: z1,a1,b1 ~~|\nTail: a1,b1 ~~|\n"
        if kind == "data":
            text = f"X[z0,Tail]:INTERPOLATE: := GET DIRECT DATA('{name}.csv','','1','B2') ~~|\nX[a0,Tail]:INTERPOLATE: := GET DIRECT DATA('{name}.csv','','1','B4') ~~|\nX[D0,z1]:INTERPOLATE: := GET DIRECT DATA('{name}.csv','','1','B6') ~~|\nY[D0,D1] = X[D0,D1] ~~|\nStock = INTEG(SUM(X[D0!,D1!]),0) ~~|"
        else:
            text = f"X[z0,Tail] = GET DIRECT LOOKUPS('{name}.csv','','1','B2') ~~|\nX[a0,Tail] = GET DIRECT LOOKUPS('{name}.csv','','1','B4') ~~|\nX[D0,z1] = GET DIRECT LOOKUPS('{name}.csv','','1','B6') ~~|\nY[D0,D1] = X[D0,D1](Time) ~~|\nStock = INTEG(SUM(X[D0!,D1!](Time)),0) ~~|"
        models.append({"name": name, "kind": kind, "dims": ["D0", "D1"], "text": declarations + text + CONTROL})
    for model in models:
        source = target / f"{model['name']}.mdl"
        source.write_text("{UTF-8}\n" + model.pop("text"))
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            path = pysd.translate_to_julia(source, backend="ode", data_format="json")
        if caught:
            raise ValueError("; ".join(str(w.message) for w in caught))
        model["path"] = str(path)
    dump(target / "models.json", models)


def oracle(target):
    import numpy as np
    import pysd
    if pysd.__version__ != "3.14.3":
        raise ValueError("Wrong external input oracle")
    reference = target / "python"
    reference.mkdir(exist_ok=True)
    for path in target.glob("*.csv"):
        shutil.copy2(path, reference / path.name)
    oracles = {}
    for item in read(target / "models.json"):
        source = target / f"{item['name']}.mdl"
        shutil.copy2(source, reference / source.name)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = pysd.read_vensim(reference / source.name)
            values = []
            for t in QUERIES:
                model.time.update(t)
                model.clean_caches()
                data = model.components.y()
                if item["dims"]:
                    data = data.transpose(*item["dims"])
                values.append(np.asarray(data, dtype=float).ravel(order="C").tolist())
            if item["name"] == "raw":
                stocks = None
            else:
                frame = model.run(return_columns=["Stock"], return_timestamps=list(range(7)))
                stocks = frame["Stock"].tolist()
        oracles[item["name"]] = {"queries": QUERIES, "values": values, "stocks": stocks}
    # JSON has no NaN: preserve its expected location explicitly.
    def encode(value):
        if isinstance(value, list):
            return [encode(v) for v in value]
        if isinstance(value, dict):
            return {k: encode(v) for k, v in value.items()}
        if isinstance(value, float) and np.isnan(value):
            return None
        return value
    dump(target / "oracle.json", encode(oracles))


def run(directory):
    from .execution import julia_command
    target = directory / "external-fixtures"
    for function, environment in (("prepare", "python-julia"), ("oracle", "python-reference")):
        command = f"from pathlib import Path; from scripts.julia_repro.external_fixtures import {function}; {function}(Path({str(target)!r}))"
        run_logged([RUNTIME / environment / "bin/python", "-B", "-c", command], target / f"{function}.log")
    run_logged([*julia_command(), CONFIG / "test_external.jl", target], target / "julia.log")
    return read(target / "results.json")
