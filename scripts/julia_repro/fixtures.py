"""Small executable Julia regressions, independent of the full SURE run."""
from __future__ import annotations
import json
import itertools
from pathlib import Path
import subprocess
import warnings

from .common import ROOT, RUNTIME, CONFIG, dump, run_logged, experiment_hashes
from .execution import julia_command


CONTROL = "\nINITIAL TIME = 0 ~~|\nFINAL TIME = 6 ~~|\nTIME STEP = 1 ~~|\nSAVEPER = TIME STEP ~~|\n"


def prepare(directory):
    import pysd
    from .builder_patch import apply
    apply()
    target = directory / "fixtures"
    target.mkdir(parents=True, exist_ok=True)
    models = []
    for rank in range(1, 7):
        dims = [f"D{i}" for i in range(rank)]
        declarations = "\n".join(f"D{i}: a{i},b{i} ~~|" for i in range(rank))
        signature = ",".join(dims)
        excluded = ",".join([*dims[:-1], f"b{rank-1}"])
        text = declarations + f"\nX[{signature}] :EXCEPT: [{excluded}] = 7 ~~|\nX[{excluded}] = 11 ~~|"
        for cell in itertools.product((0, 1), repeat=rank):
            labels = ",".join(f"{'b' if index else 'a'}{axis}" for axis, index in enumerate(cell))
            value = sum((index+1)*10**axis for axis, index in enumerate(cell))
            text += f"\nY[{labels}] = {value} ~~|"
        text += f"\nStock[{signature}] = INTEG(X[{signature}], Y[{signature}]) ~~|"
        models.append((f"rank_{rank}", text + CONTROL))
    for delay in (0.01, 0.1, 1, 2, 4):
        models.append((f"delay_{str(delay).replace('.', '_')}", f"D = DELAY FIXED(Time, {delay}, -1) ~~|" + CONTROL))
    models.append(("selfref", "D0: a0,b0 ~~|\nX[a0] = 3 ~~|\nX[b0] = X[a0]*2 ~~|\nStock = INTEG(SUM(X[D0!]), 0) ~~|" + CONTROL))
    models.append(("subgroup", "D0: a0,b0,c0 ~~|\nTail: b0,c0 ~~|\nX[D0] :EXCEPT: [Tail] = 2 ~~|\nX[Tail] = 3 ~~|\nStock[D0] = INTEG(X[D0], X[D0]) ~~|" + CONTROL))
    (target / "input.csv").write_text("Time,0,2,6\nX,10,20,60\n")
    models.append(("external", "X:INTERPOLATE: := GET DIRECT DATA('input.csv','','1','B2') ~~|\nStock = INTEG(X, 0) ~~|" + CONTROL))
    translated, failures = [], []
    for name, text in models:
        source = target / f"{name}.mdl"
        source.write_text("{UTF-8}\n" + text)
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                path = pysd.translate_to_julia(source, backend="ode", data_format="json")
            if caught:
                raise ValueError("; ".join(str(x.message) for x in caught))
            translated.append({"name": name, "path": str(path)})
        except Exception as exc:
            failures.append({"fixture": name, "error": str(exc)})
    dump(target / "models.json", translated)
    dump(target / "translation.json", {"pass": not failures, "failures": failures})


def run(directory):
    experiment = experiment_hashes()
    target = directory / "fixtures"
    command = [RUNTIME / "python-julia/bin/python", "-B", "-c",
               "from pathlib import Path; from scripts.julia_repro.fixtures import prepare; prepare(Path(" + repr(str(directory)) + "))"]
    run_logged(command, target / "translation.log")
    run_logged([RUNTIME / "python-reference/bin/python", "-B", "-c",
                "from pathlib import Path; from scripts.julia_repro.fixtures import allocation_cases; allocation_cases(Path(" + repr(str(target / "allocation.json")) + "))"],
               target / "allocation-reference.log")
    from .common import read
    translation = read(target / "translation.json")
    run_logged([RUNTIME / "python-reference/bin/python", "-B", "-c",
                "from pathlib import Path; from scripts.julia_repro.fixtures import python_oracles; python_oracles(Path(" + repr(str(target)) + "))"],
               target / "python-oracles.log")
    try:
        run_logged([*julia_command(), CONFIG / "test_models.jl", target / "models.json", target / "julia-results.json"], target / "julia.log")
        julia = read(target / "julia-results.json")
    except Exception as exc:
        julia = {"pass": False, "error": str(exc)}
    try:
        smoke_runner(target)
        runner = {"pass": True}
    except Exception as exc:
        runner = {"pass": False, "error": str(exc)}
    additional = {}
    from . import external_fixtures, stateful_fixtures, semantic_fixtures, sure_external, indexing_fixtures, allocation_fixtures, reduction_fixtures, reduction_blocks, hotpath_fixtures, numpy_math_fixtures, lookup_fixtures
    for name, module in (("external", external_fixtures), ("stateful", stateful_fixtures),
                         ("semantics", semantic_fixtures), ("sure_inputs", sure_external),
                         ("indexing", indexing_fixtures), ("allocation_stress", allocation_fixtures),
                         ("reductions", reduction_fixtures), ("reduction_blocks", reduction_blocks),
                         ("hotpaths", hotpath_fixtures), ("numpy_math", numpy_math_fixtures),
                         ("lookups", lookup_fixtures)):
        try:
            additional[name] = module.run(directory)
        except Exception as exc:
            additional[name] = {"pass": False, "error": str(exc)}
    unchanged = experiment == experiment_hashes()
    result = {"pass": unchanged and translation["pass"] and julia["pass"] and runner["pass"]
              and all(item["pass"] for item in additional.values()), "translation": translation,
              "julia": julia, "runner": runner, **additional, "experiment": experiment,
              "experiment_unchanged": unchanged}
    dump(directory / "fixtures.json", result)
    return result


def smoke_runner(target):
    import numpy as np
    from .common import read
    dims = [f"D{i}" for i in range(6)]
    dump(target / "export.json", [{"name": "Stock", "julia_name": "stock", "dims": dims,
                                   "coords": {d: [f"a{i}", f"b{i}"] for i, d in enumerate(dims)}}])
    raw = target / "runner"
    run_logged([*julia_command(), CONFIG / "run_model.jl", target / "rank_6.jl",
                target / "export.json", raw, 2], target / "runner.log")
    expected = np.asarray(read(target / "python-oracles.json")["rank_6"]["variables"]["stock"])
    for iteration in (1, 2):
        timing = read(raw / str(iteration) / "timing.json")
        if timing["years"] != list(range(7)):
            raise ValueError("Runner truncated fixture years")
        actual = np.fromfile(raw / str(iteration) / "v0000.bin", dtype="<f8").reshape(7, 64)
        if not np.array_equal(actual, expected):
            raise ValueError("Runner changed coordinate order, state reset or numeric values")


def python_oracles(target):
    """Run the same tiny models with unmodified PySD 3.14.3."""
    import shutil
    import numpy as np
    import pysd
    from .common import read
    reference = target / "python"
    reference.mkdir(exist_ok=True)
    shutil.copy2(target / "input.csv", reference / "input.csv")
    results = {}
    for item in read(target / "models.json"):
        name = item["name"]
        shutil.copy2(target / f"{name}.mdl", reference / f"{name}.mdl")
        model = pysd.read_vensim(reference / f"{name}.mdl", initialize=False)
        if name == "selfref":
            # The reference is the current app, whose generated model already
            # received this repository correction. Apply it only to the tiny copy.
            import fix_selfref_sure
            fix_selfref_sure.PY = Path(model.py_model_file)
            fix_selfref_sure.main()
            model = pysd.load(model.py_model_file)
        else:
            model.initialize()
        outputs = ["D"] if name.startswith("delay_") else ["Stock", "X"]
        frame = model.run(return_columns=outputs, return_timestamps=list(range(7)), flatten_output=False)
        result = {"years": list(map(float, frame.index)), "variables": {}}
        for variable in outputs:
            result["variables"][variable.lower()] = [np.asarray(value).ravel(order="C").tolist() for value in frame[variable]]
        results[name] = result
    dump(target / "python-oracles.json", results)


def allocation_cases(path):
    import numpy as np
    from pysd.py_backend.allocation import _allocate_available_1d
    cases = []
    profiles = np.array([[1, 0., .1, 0], [1, 1., .1, 0], [1, 2., .1, 0]], dtype=float)
    for q in ([10., 20., 30.], [-10., 20., 30.], [0., 0., 0.], [1e-8, 20., 30.]):
        for available in (0., 1e-9, 15., 49.999, 100.):
            expected = _allocate_available_1d(np.maximum(q, 0.), profiles, available)
            cases.append({"request": q, "pp": profiles.tolist(), "available": available,
                          "expected": np.asarray(expected).tolist()})
    # Overlapping rectangles exercise simultaneous allocations, not just merit order.
    overlapping = profiles.copy(); overlapping[:,1] = [1., 1.01, 1.02]
    for available in (1., 25., 59.):
        q = np.array([10., 20., 30.])
        cases.append({"request": q.tolist(), "pp": overlapping.tolist(), "available": available,
                      "expected": np.asarray(_allocate_available_1d(q, overlapping, available)).tolist()})
    dump(path, cases)
