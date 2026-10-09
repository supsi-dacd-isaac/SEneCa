"""Coordinate/reduction regressions for the six-axis SURE construction flow."""
from __future__ import annotations

import itertools
import shutil
import warnings

from .common import CONFIG, RUNTIME, dump, read, run_logged

CONTROL = "\nINITIAL TIME = 0 ~~|\nFINAL TIME = 2 ~~|\nTIME STEP = 1 ~~|\nSAVEPER = TIME STEP ~~|\n"


def prepare(target):
    import pysd
    from . import builder_patch, indexing_patch
    builder_patch.apply()
    indexing_patch.apply()
    target.mkdir(parents=True, exist_ok=True)
    dimensions = {"District": ["d0", "d1"], "HS": ["h0", "h1"],
                  "Performance": ["p0", "p1", "p2", "p3", "p4"],
                  "Type": ["t0", "t1", "t2"], "PVpanel": ["PVyes", "PVno"],
                  "Battery": ["Bno", "Byes"]}
    text = "\n".join(f"{d}: {','.join(labels)} ~~|" for d, labels in dimensions.items())
    text += "\nPerformanceLow: p0,p1 ~~|\nPerformanceHigh: p2,p3,p4 ~~|\n"
    for indices in itertools.product(*(range(len(v)) for v in dimensions.values())):
        labels = ",".join(v[i] for v, i in zip(dimensions.values(), indices))
        value = sum((i + 1)*10**axis for axis, i in enumerate(indices))
        text += f"Initial[{labels}] = {value} ~~|\n"
    signature = ",".join(dimensions)
    text += f"Heating Solution[{signature}] = INTEG(0, Initial[{signature}]) ~~|\n"
    text += "Profile[PerformanceHigh] = 11,23,37 ~~|\n"
    text += "Construction[District,PerformanceLow,Type,PVpanel] = 0 ~~|\n"
    text += "Construction[District,PerformanceHigh,Type,PVyes] = SUM(Heating Solution[District,HS!,PerformanceHigh,Type,PVpanel!,Battery!]) + 2*SUM(Heating Solution[District,HS!,PerformanceHigh,Type,PVyes,Battery!]) + Profile[PerformanceHigh] ~~|\n"
    text += "Construction[District,PerformanceHigh,Type,PVno] = Construction[District,PerformanceHigh,Type,PVyes]*3 ~~|\n"
    text += "Restricted[PerformanceHigh] = SUM(Heating Solution[District!,HS!,PerformanceHigh,Type!,PVpanel!,Battery!]) ~~|\n"
    text += "Low selected[District,Type] = SUM(Heating Solution[District,HS!,p0,Type,PVyes,Battery!]) ~~|\n"
    text += "Subgroup sum[District,Type] = SUM(Heating Solution[District,HS!,PerformanceHigh!,Type,PVyes,Battery!]) ~~|\n"
    text += "Total = SUM(Construction[District!,Performance!,Type!,PVpanel!]) ~~|\n"
    models = [{"name": "sure_construction", "text": text,
               "outputs": ["Heating Solution", "Construction", "Restricted", "Low selected", "Subgroup sum", "Total"]}]
    text = "A: a0,a1 ~~|\nB: b0,b1 ~~|\nX[a0,b0] = 2 ~~|\nX[a0,b1] = 3 ~~|\nX[a1,b0] = 5 ~~|\nX[a1,b1] = 7 ~~|\nWeight[B] = 11,13 ~~|\n"
    text += "Shared[A,B] = SUM(X[A!,B!]*Weight[B!]) ~~|\nLocal sum[A,B] = SUM(X[A,B!]*Weight[B!]) ~~|\n"
    text += "Nested[A] = SUM(X[A,B!] * SUM(Weight[B!])) ~~|\nStock[A,B] = INTEG(Shared[A,B]+Local sum[A,B], X[A,B]) ~~|\n"
    models.append({"name": "shadowing_and_shared_sum", "text": text, "outputs": ["Shared", "Local sum", "Nested", "Stock"]})
    text = "A: a0,a1 ~~|\nB: b0,b1,b2 ~~|\nTail: b1,b2 ~~|\n"
    text += "Vector[A,b0] = 11,13 ~~|\nVector[a0,Tail] = 17,19 ~~|\nVector[a1,Tail] = 23,29 ~~|\nMatrix[A,B] = 31,37,41;43,47,53 ~~|\nStock[A,B] = INTEG(Vector[A,B]+Matrix[A,B], Vector[A,B]) ~~|\n"
    models.append({"name": "multicomponent_array", "text": text, "outputs": ["Vector", "Matrix", "Stock"]})
    text = 'D: d0,d1 ~~|\n"Battery capacity < 100 kW"[D] = INTEG(3, 7) ~~|\n"Battery capacity > 100 kW"[D] = INTEG(11, 13) ~~|\n'
    text += 'Small = SUM("Battery capacity < 100 kW"[D!]) ~~|\nLarge = SUM("Battery capacity > 100 kW"[D!]) ~~|\n'
    text += 'Capacity[D] = "Battery capacity < 100 kW"[D] + "Battery capacity > 100 kW"[D] ~~|\n'
    text += '"Initial grant > 15 kW"=2300 ~~|\n"Initial grant < 15 kW"=1700 ~~|\n"Rate > 15 kW"=37 ~~|\n"Rate < 15 kW"=19 ~~|\n'
    text += 'Capacity per cell[d0] = 14 ~~|\nCapacity per cell[d1] = 16 ~~|\nGrant[D] = IF THEN ELSE(Capacity per cell[D]<15,"Initial grant < 15 kW"+"Rate < 15 kW"*Capacity per cell[D],"Initial grant > 15 kW"+"Rate > 15 kW"*Capacity per cell[D]) ~~|\n'
    models.append({"name": "quoted_name_collisions", "text": text, "outputs": ["Small", "Large", "Capacity", "Grant"]})
    for item in models:
        source = target / f"{item['name']}.mdl"
        source.write_text("{UTF-8}\n" + item.pop("text") + CONTROL)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            item["path"] = str(pysd.translate_to_julia(source, data_format="json", backend="ode"))
        if caught:
            raise ValueError("; ".join(str(w.message) for w in caught))
    dump(target / "models.json", models)


def oracle(target):
    import numpy as np
    import pysd
    import fix_selfref_sure
    from pathlib import Path
    if pysd.__version__ != "3.14.3":
        raise ValueError("Wrong indexing oracle")
    reference = target / "python"
    reference.mkdir(exist_ok=True)
    results = {}
    for item in read(target / "models.json"):
        source = target / f"{item['name']}.mdl"
        shutil.copy2(source, reference / source.name)
        model = pysd.read_vensim(reference / source.name, initialize=False)
        fix_selfref_sure.PY = Path(model.py_model_file)
        fix_selfref_sure.main()
        model = pysd.load(model.py_model_file)
        frame = model.run(return_columns=item["outputs"], return_timestamps=[0, 1, 2], flatten_output=False)
        records = []
        for name in item["outputs"]:
            first = frame[name].iloc[0]
            dims = list(first.dims) if hasattr(first, "dims") else []
            records.append({"name": name, "identifier": model._namespace[name], "dimensions": dims,
                            "coordinates": {d: first.coords[d].values.tolist() for d in dims},
                            "values": [np.asarray(value).ravel(order="C").tolist() for value in frame[name]]})
        results[item["name"]] = records
    dump(target / "oracle.json", results)


def run(directory):
    from .execution import julia_command
    target = directory / "indexing-fixtures"
    for function, environment in (("prepare", "python-julia"), ("oracle", "python-reference")):
        command = f"from pathlib import Path; from scripts.julia_repro.indexing_fixtures import {function}; {function}(Path({str(target)!r}))"
        run_logged([RUNTIME / environment / "bin/python", "-B", "-c", command], target / f"{function}.log")
    run_logged([*julia_command(), CONFIG / "test_indexing.jl", target], target / "julia.log")
    return read(target / "results.json")
