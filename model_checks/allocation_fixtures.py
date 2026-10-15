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
    fn = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "allocate_available")
    namespace = {"np": np, "xr": xr, "_pysd_allocate_available": allocate_available,
                 "_pysd_allocate_by_priority": allocate_by_priority}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(MODEL_PY), "exec"), namespace)
    wrapper = namespace["allocate_available"]
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
            request = xr.DataArray(q, dims=["Supplier"])
            pp = xr.DataArray(profile, dims=["Supplier", "PProfile"])
            out = wrapper(request, pp, supply).values
            cases.append({"request": q.tolist(), "pp": profile.tolist(), "supply": float(supply), "expected": out.tolist()})
    # Explicit unequal-width fallback to the rectangular profile solver.
    profile = np.array([[1, 4, 1, 0], [1, 3, 2, 0], [1, 1, 3, 0]], dtype=float)
    for supply in (0., 2., 9., 30.):
        q = np.array([-2., 4., 10.])
        out = wrapper(xr.DataArray(q, dims=["Supplier"]), xr.DataArray(profile, dims=["Supplier", "PProfile"]), supply).values
        cases.append({"request": q.tolist(), "pp": profile.tolist(), "supply": supply, "expected": out.tolist()})
    dump(directory / "allocation-fixtures.json", cases)


if __name__ == "__main__":
    prepare(Path(sys.argv[1]).resolve())
