"""Lossless 6D <-> 3D mapping, explicitly defined by labels (not reshape order)."""
from __future__ import annotations
import itertools
import numpy as np

DIMENSIONS = ("District", "HS", "Performance", "Type", "PVpanel", "Battery")


def mapping(coords):
    archetypes = list(itertools.product(*(coords[d] for d in ("District", "Performance", "Type"))))
    configurations = list(itertools.product(coords["PVpanel"], coords["Battery"]))
    positions = {d: {s: i for i, s in enumerate(coords[d])} for d in DIMENSIONS}
    for a, (district, performance, kind) in enumerate(archetypes):
        for h, heating in enumerate(coords["HS"]):
            for c, (pv, battery) in enumerate(configurations):
                original = tuple(positions[d][label] for d, label in zip(
                    DIMENSIONS, (district, heating, performance, kind, pv, battery)))
                yield original, (a, h, c)


def pack(values, coords):
    shape = tuple(len(coords[d]) for d in DIMENSIONS)
    if values.shape != shape:
        raise ValueError(f"Expected {shape}, got {values.shape}")
    out = np.empty((shape[0]*shape[2]*shape[3], shape[1], shape[4]*shape[5]), dtype=values.dtype)
    for original, packed in mapping(coords):
        out[packed] = values[original]
    return out


def unpack(values, coords):
    shape = tuple(len(coords[d]) for d in DIMENSIONS)
    if values.shape != (shape[0]*shape[2]*shape[3], shape[1], shape[4]*shape[5]):
        raise ValueError("Invalid packed shape")
    out = np.empty(shape, dtype=values.dtype)
    for original, packed in mapping(coords):
        out[original] = values[packed]
    return out


def validate_real_snapshot(path):
    from .results import load_snapshot
    meta, arrays = load_snapshot(path)
    checked = 0
    for name, item in meta["variables"].items():
        if item["dims"] != list(DIMENSIONS):
            continue
        shape = tuple(len(item["coords"][d]) for d in DIMENSIONS)
        for data in arrays[name]:
            original = data.reshape(shape)  # columns_for uses the same explicit product order
            restored = unpack(pack(original, item["coords"]), item["coords"])
            if not np.array_equal(original, restored):
                raise ValueError(f"Non-identical or nonfinite packing: {name}")
            checked += original.size
    if not checked:
        raise ValueError("No six-dimensional states checked")
    return {"pass": True, "cells_checked": checked}
