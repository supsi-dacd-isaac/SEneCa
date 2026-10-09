"""Bitwise inline/named lookup checks, independent of full SURE references."""
from pathlib import Path
import shutil
import warnings

from .common import CONFIG, RUNTIME, PINS, dump, read, run_logged


def prepare(target):
    import pysd
    from . import builder_patch, lookup_patch
    builder_patch.apply()
    lookup_patch.apply()
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    text = """{UTF-8}
A: a,b,c,d ~~|
Offset[a] = 0.0626778283043073 ~~|
Offset[b] = 0.392816278134876 ~~|
Offset[c] = 0.670132649021879 ~~|
Offset[d] = 1.36580079711349 ~~|
Table ((0,1),(0.25,0.68),(0.5,0.48),(0.75,0.37),(1,0.3),(1.5,0.23),(1.75,0.205),(2.5,0.15),(4,0.08)) ~~|
Inline[A] = WITH LOOKUP(Offset[A]+Time/7, ((0,1),(0.25,0.68),(0.5,0.48),(0.75,0.37),(1,0.3),(1.5,0.23),(1.75,0.205),(2.5,0.15),(4,0.08))) ~~|
Named[A] = Table(Offset[A]+Time/7) ~~|
Stock[A] = INTEG(Inline[A]+Named[A],0) ~~|
INITIAL TIME = 0 ~~|
FINAL TIME = 2 ~~|
TIME STEP = 1 ~~|
SAVEPER = TIME STEP ~~|
"""
    source = target / "lookups.mdl"
    source.write_text(text)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        model = pysd.translate_to_julia(source, backend="ode", data_format="json")
    if caught:
        raise ValueError("; ".join(str(w.message) for w in caught))
    dump(target / "model.json", {"path": str(model), "outputs": ["Inline", "Named", "Stock"]})


def oracle(target):
    import numpy as np
    import pysd
    from pysd.py_backend.lookups import HardcodedLookups
    if pysd.__version__ != PINS["pysd_reference"] or np.__version__ != "2.4.6":
        raise ValueError("Lookup fixture requires the frozen Python environment")
    target = Path(target)
    rng = np.random.default_rng(PINS["seed"])
    tables = [([0., .25, .5, .75, 1., 1.5, 1.75, 2.5, 4.],
               [1., .68, .48, .37, .3, .23, .205, .15, .08]),
              ([0., 5., 10., 20., 70., 100., 200.], [490., 490., 490., 550., 685., 1250., 2250.]),
              ([0.], [-0.])]
    for _ in range(12):
        xs = np.cumsum(rng.uniform(.0001, 3., 13))
        tables.append((xs.tolist(), (rng.normal(size=13)*10**rng.uniform(-8,8)).tolist()))
    cases = []
    for number, (xs, ys) in enumerate(tables):
        queries = np.concatenate(([xs[0]-1., xs[-1]+1.], xs,
            np.nextafter(xs, -np.inf), np.nextafter(xs, np.inf),
            rng.uniform(xs[0]-1., xs[-1]+1., 257))).tolist()
        cases.append({"name": f"numpy_{number}", "mode": "interpolate", "xs": xs, "ys": ys,
                      "queries": queries, "expected": np.interp(queries, xs, ys).tolist()})
        if len(xs) > 1:
            for mode in ("interpolate", "extrapolate", "hold_backward"):
                lookup = HardcodedLookups(xs, ys, {}, mode, {}, f"oracle_{number}")
                lookup.initialize()
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    expected = [lookup(x) for x in queries]
                cases.append({"name": f"named_{mode}_{number}", "mode": mode, "xs": xs, "ys": ys,
                              "queries": queries, "expected": expected})
    dump(target / "cases.json", cases)
    source = target / "lookups.mdl"
    reference = target / "python"
    reference.mkdir(exist_ok=True)
    shutil.copy2(source, reference / source.name)
    model = pysd.read_vensim(reference / source.name)
    spec = read(target / "model.json")
    frame = model.run(return_columns=spec["outputs"], return_timestamps=[0.,1.,2.], flatten_output=False)
    records = []
    for name in spec["outputs"]:
        records.append({"name":name, "identifier":model._namespace[name],
                        "values":[np.asarray(value).ravel(order="C").tolist() for value in frame[name]]})
    dump(target / "model-oracle.json", records)


def run(directory):
    from .execution import julia_command
    target = Path(directory).resolve() / "lookup-fixtures"
    for function, runtime in (("prepare","python-julia"),("oracle","python-reference")):
        command = f"from scripts.julia_repro.lookup_fixtures import {function}; {function}({str(target)!r})"
        run_logged([RUNTIME/runtime/"bin/python", "-B", "-c", command],target/f"{function}.log")
    run_logged([*julia_command(), CONFIG/"test_lookup.jl", target], target/"julia.log")
    return read(target/"results.json")
