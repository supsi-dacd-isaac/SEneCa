"""Small executable Julia regressions, independent of the full SURE run."""
from __future__ import annotations
import itertools
from pathlib import Path
import warnings

from sure_julia.common import dump, read


CONTROL = "\nINITIAL TIME = 0 ~~|\nFINAL TIME = 6 ~~|\nTIME STEP = 1 ~~|\nSAVEPER = TIME STEP ~~|\n"


def prepare(directory):
    import pysd
    from sure_julia.translator.builder_patch import apply
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


def python_oracles(target):
    """Run the same tiny models with unmodified PySD 3.14.3."""
    import shutil
    import numpy as np
    import pysd
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
