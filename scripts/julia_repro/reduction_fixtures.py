"""Non-associative SUM oracles across ranks, axis subsets and transposed data."""
from __future__ import annotations

import itertools
from pathlib import Path
import re
import warnings

from .common import CONFIG, RUNTIME, dump, read, run_logged

SHAPES = [(8,), (9,), (24,), (128,), (129,), (257,), (7, 24), (3, 8, 9), (2, 3, 8, 9), (2, 2, 3, 8, 9), (2, 2, 2, 3, 8, 9)]
CONTROL = "\nINITIAL TIME=0 ~~|\nFINAL TIME=1 ~~|\nTIME STEP=1 ~~|\nSAVEPER=TIME STEP ~~|\n"


def cases():
    import numpy as np
    result = []
    rng = np.random.default_rng(20261009)
    choices = np.array([-1e16, -1., -0.1, -1e-16, 0., 1e-16, 0.1, 1., 1e16])
    for shape in SHAPES:
        rank = len(shape)
        dims = [f"D{axis}" for axis in range(rank)]
        coords = {dim: [f"v{axis}p{i}" for i in range(size)] for axis, (dim, size) in enumerate(zip(dims, shape))}
        text = "\n".join(f"{dim}: {','.join(labels)} ~~|" for dim, labels in coords.items())
        text += f"\nX[{','.join(dims)}]=0 ~~|\nTransposed[{','.join(reversed(dims))}]=X[{','.join(dims)}] ~~|\nStock=INTEG(0,0) ~~|\n"
        outputs = []
        for source, ordering in [("X", dims), ("Transposed", list(reversed(dims)))]:
            for mask in range(1, 2**rank):
                selected = {dims[axis] for axis in range(rank) if mask & (1 << axis)}
                remaining = [dim for dim in ordering if dim not in selected]
                name = f"Sum {source} {mask}"
                lhs = name + (f"[{','.join(remaining)}]" if remaining else "")
                specs = ",".join(dim + ("!" if dim in selected else "") for dim in ordering)
                text += f"{lhs}=SUM({source}[{specs}]) ~~|\n"
                outputs.append({"name": name, "source": source, "reduced": [d for d in ordering if d in selected], "dims": remaining})
        values = rng.choice(choices, size=shape)
        if shape == (8,):
            # Actual annual residential PV terms at the first sensitive cell.
            values = np.array([6.4769640435753155, 0.7942570561595687, 1.1734774127619385,
                               8.850408925382723, 19.587046125275297, 7.172109520623,
                               1.0071625516980784, 0.6803833345268062])
        name = f"rank_{rank}_n{shape[0]}" if rank == 1 else f"rank_{rank}"
        result.append({"name": name, "shape": list(shape), "dims": dims,
                       "coords": coords, "values": values.tolist(), "text": "{UTF-8}\n" + text + CONTROL,
                       "outputs": outputs})
    return result


def prepare(target):
    import numpy as np
    import pysd
    from .builder_patch import apply
    apply()
    from pysd.builders.julia.julia_model_builder import JuliaSectionBuilder
    from pysd.builders.julia.julia_expressions_builder import JuliaASTVisitor
    target = Path(target).resolve()
    target.mkdir(parents=True, exist_ok=True)
    specifications = cases()
    dump(target / "cases.json", specifications)
    models = []
    original, original_call = JuliaSectionBuilder._process_element, JuliaASTVisitor._call
    for item, mode in itertools.product(specifications, ("current", "flat_numpy")):
        values = np.asarray(item["values"], dtype=np.float64)
        def process(self, element, identifier, is_control=False):
            if element.name == "X":
                flat = ", ".join(repr(float(value)) for value in values.ravel(order="F"))
                self.param_decls.append(f"@parameters {identifier} = reshape(Float64[{flat}], {', '.join(map(str, values.shape))})")
                return []
            return original(self, element, identifier, is_control)
        def call(self, node):
            value = original_call(self, node)
            if mode == "flat_numpy" and node.function.reference.upper() == "SUM":
                return re.sub(r"^sum\(", "seneca_numpy_sum(", value)
            return value
        JuliaSectionBuilder._process_element, JuliaASTVisitor._call = process, call
        source = target / mode / (item["name"] + ".mdl")
        source.parent.mkdir(exist_ok=True)
        source.write_text(item["text"])
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                path = pysd.translate_to_julia(source, backend="ode", data_format="json")
            if caught:
                raise ValueError(f"Reduction translation warnings: {[str(w.message) for w in caught]}")
            models.append({"name": item["name"], "mode": mode, "path": str(path)})
        finally:
            JuliaSectionBuilder._process_element, JuliaASTVisitor._call = original, original_call
    dump(target / "models.json", models)


def oracle(target):
    import numpy as np
    import pysd
    import xarray as xr
    if pysd.__version__ != "3.14.3":
        raise ValueError("Reduction oracle requires PySD 3.14.3")
    target = Path(target).resolve()
    result = {}
    for item in read(target / "cases.json"):
        source = target / "python" / (item["name"] + ".mdl")
        source.parent.mkdir(exist_ok=True)
        source.write_text(item["text"])
        model = pysd.read_vensim(source, initialize=False)
        values = np.asarray(item["values"], dtype=np.float64)
        model.set_components({"X": xr.DataArray(values, dims=item["dims"], coords=item["coords"])})
        model.initialize()
        outputs = [row["name"] for row in item["outputs"]]
        frame = model.run(return_columns=outputs, return_timestamps=[0], flatten_output=False)
        rows = []
        for spec in item["outputs"]:
            value = frame[spec["name"]].iloc[0]
            rows.append({**spec, "identifier": model._namespace[spec["name"]],
                         "values": np.asarray(value).ravel(order="C").tolist()})
        layouts = {name: {"dims": list(value.dims), "shape": list(value.shape), "strides": list(value.data.strides)}
                   for name in ("x", "transposed") for value in [getattr(model.components, name)()]}
        result[item["name"]] = {"layouts": layouts, "rows": rows}
    dump(target / "oracle.json", result)
    vector_cases = []
    rng = np.random.default_rng(20261009)
    for length in [*range(10), 128, 129, 257]:
        for pattern, value in [("zero", np.zeros(length)), ("negative_zero", np.full(length, -0.0)),
                               ("cancellation", np.resize([1e16, 1., -1e16, 0.1], length)),
                               ("positive", rng.random(length))]:
            vector_cases.append({"name": f"{pattern}_{length}", "values": value.tolist(), "sum": float(np.sum(value))})
    dump(target / "vector-oracles.json", vector_cases)


def run(directory):
    from .execution import julia_command
    target = Path(directory).resolve() / "reduction-fixtures"
    for function, runtime in (("prepare", "python-julia"), ("oracle", "python-reference")):
        command = f"from scripts.julia_repro.reduction_fixtures import {function}; {function}({str(target)!r})"
        run_logged([RUNTIME / runtime / "bin/python", "-B", "-c", command], target / f"{function}.log")
    run_logged([*julia_command(), CONFIG / "test_reductions.jl", target], target / "julia.log")
    return read(target / "results.json")
