"""Additional conservation check on every observed SURE allocation cell."""
from __future__ import annotations

import numpy as np

from .common import PINS
from .results import load_snapshot


def check_snapshot(path):
    meta, arrays = load_snapshot(path)
    request_name = "Hourly available supply by Supplier"
    allocated_name = "Electricity dispatched"
    available_name = "Hourly demand and PHS"
    names = (request_name, allocated_name, available_name)
    if any(name not in arrays for name in names):
        return {"pass": False, "reason": "Missing conservation inputs"}
    request_meta, allocated_meta, available_meta = (meta["variables"][name] for name in names)
    dims = ["Month", "Hour", "Supplier"]
    if (request_meta["dims"] != dims or allocated_meta["dims"] != dims
            or available_meta["dims"] != dims[:-1]
            or request_meta["coords"] != allocated_meta["coords"]
            or available_meta["coords"] != {d: request_meta["coords"][d] for d in dims[:-1]}):
        return {"pass": False, "reason": "Conservation coordinates differ"}
    shape = (len(meta["years"]), *(len(request_meta["coords"][d]) for d in dims))
    request = np.maximum(arrays[request_name].reshape(shape), 0.)
    allocated = arrays[allocated_name].reshape(shape)
    available = arrays[available_name].reshape(shape[:-1])
    if (not all(np.isfinite(arrays[name]).all() for name in names)
            or np.any(available < 0)):
        return {"pass": False, "reason": "Nonfinite or invalid conservation inputs"}
    target = np.minimum(np.sum(request, axis=-1), available)
    total = np.sum(allocated, axis=-1)
    error = abs(total-target)
    scale = np.maximum(1., np.max(abs(target), axis=0))
    tolerance = PINS["atol_scale"]*scale + PINS["rtol"]*abs(target)
    invalid_bounds = np.any((allocated < 0) | (allocated > request), axis=-1)
    bad = (error > tolerance) | invalid_bounds
    result = {"pass": not bool(bad.any()), "cells": int(target.size),
              "failures": int(bad.sum()), "max_abs": float(error.max()),
              "bound_failures": int(invalid_bounds.sum())}
    if bad.any():
        year, month, hour = np.argwhere(bad)[0]
        result["first_failure"] = {
            "year": meta["years"][year], "Month": request_meta["coords"]["Month"][month],
            "Hour": request_meta["coords"]["Hour"][hour],
            "allocated": float(total[year, month, hour]),
            "target": float(target[year, month, hour]),
            "tolerance": float(tolerance[year, month, hour])}
    return result
