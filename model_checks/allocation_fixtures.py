from __future__ import annotations

import ast
from pathlib import Path
import sys

import numpy as np
import xarray as xr
from pysd.py_backend.allocation import allocate_available, allocate_by_priority

from sure_julia.common import MODEL_PY, dump


def prepare(directory):
    source = MODEL_PY.read_text()
    fn = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "allocate_by_priority")
    namespace = {"np": np, "xr": xr, "_pysd_allocate_available": allocate_available,
                 "_pysd_allocate_by_priority": allocate_by_priority}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(MODEL_PY), "exec"), namespace)
    wrapper = namespace["allocate_by_priority"]
    cases = []
    rng = np.random.default_rng(20261012)
    for n in (1, 2, 4, 10, 15):
        for i in range(20):
            q = rng.uniform(0, 100, n)
            q[0] = (-10 if i % 3 == 0 else 0 if i % 3 == 1 else q[0])
            p = rng.integers(1, 5, n).astype(float)
            width = (0.01, 1., 3., 10.)[i % 4]
            supply = max(0., max(q, default=0)) * n * (0., .2, .8, 2.)[i % 4]
            profile = np.array([np.ones(n), p, np.full(n, width), np.zeros(n)]).T
            q = np.maximum(q, 0.)
            request = xr.DataArray(q, dims=["Supplier"])
            pp = xr.DataArray(profile, dims=["Supplier", "PProfile"])
            out = wrapper(request, pp.isel(PProfile=1), width, supply).values
            cases.append({"request": q.tolist(), "pp": profile.tolist(), "supply": float(supply), "expected": out.tolist()})
    # Native handoff vectors, ties, overlaps, tiny imports and full-capacity endpoints.
    from model_checks.dispatch_validation import cases as dispatch_cases
    for label, q, costs, supply in dispatch_cases():
        q = np.maximum(q, 0.)
        width = .1
        pp = np.column_stack([np.ones(len(q)), -costs, np.full(len(q), width), np.zeros(len(q))])
        out = wrapper(xr.DataArray(q, dims=["Supplier"]), xr.DataArray(-costs, dims=["Supplier"]), width, supply).values
        cases.append({"request": q.tolist(), "pp": pp.tolist(), "supply": float(supply), "expected": out.tolist()})
    for ulps in (0, 1, 2, 4):
        q = np.array([.2, .1, .3, .2, .5, 10., .1, .2, .1])
        supply = q.sum() - ulps * np.spacing(q.sum())
        priority = -np.arange(9, dtype=float)
        profile = np.column_stack([np.ones(9), priority, np.full(9, .1), np.zeros(9)])
        out = wrapper(xr.DataArray(q, dims=["Supplier"]), xr.DataArray(priority, dims=["Supplier"]), .1, supply).values
        cases.append({"request": q.tolist(), "pp": profile.tolist(), "supply": float(supply), "expected": out.tolist()})
    dump(directory / "allocation-fixtures.json", cases)


if __name__ == "__main__":
    prepare(Path(sys.argv[1]).resolve())
