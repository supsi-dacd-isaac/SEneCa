from __future__ import annotations

import numpy as np
from .common import PINS, YEARS, dump, read, digest
from .inventory import columns_for


def save_frame(path, df, outputs, manifest, *, flattened=True):
    metadata, arrays = {"years": list(map(float, df.index)), "variables": {}}, {}
    expected = []
    for i, variable in enumerate(outputs):
        columns = columns_for(variable, manifest)
        expected.extend(columns)
        if flattened and not set(columns).issubset(df.columns):
            raise ValueError(f"Missing columns of {variable}")
        key = f"v{i:04d}"
        dims = manifest["variables"][variable].get("subscripts", [])
        if flattened:
            arrays[key] = df.loc[:, columns].to_numpy(dtype=np.float64)
        elif dims:
            values = []
            for value in df[variable]:
                if set(value.dims) != set(dims) or any(list(value.coords[d].values) != manifest["dimensions"][d] for d in dims):
                    raise ValueError(f"Diagnostic coordinate mismatch: {variable}")
                values.append(value.transpose(*dims).values.ravel(order="C"))
            arrays[key] = np.asarray(values, dtype=np.float64)
        else:
            arrays[key] = df[variable].to_numpy(dtype=np.float64).reshape(-1, 1)
        metadata["variables"][variable] = {"key": key, "columns": columns, "dims": dims,
            "discrete": variable in manifest.get("discrete", []),
            "coords": {d: manifest["dimensions"][d] for d in dims}}
    if len(expected) != len(set(expected)) or set(df.columns) != set(expected if flattened else outputs) or df.columns.has_duplicates:
        raise ValueError("Unexpected or duplicate result columns")
    np.savez_compressed(path.with_suffix(".npz"), **arrays)
    metadata["sha256"] = digest(path.with_suffix(".npz"))
    dump(path.with_suffix(".json"), metadata)


def load_snapshot(path):
    meta = read(path.with_suffix(".json"))
    if digest(path.with_suffix(".npz")) != meta["sha256"]:
        raise ValueError(f"Corrupt result: {path}")
    with np.load(path.with_suffix(".npz"), allow_pickle=False) as data:
        arrays = {name: data[v["key"]].copy() for name, v in meta["variables"].items()}
    return meta, arrays


def compare(reference, candidate, *, outputs=None, exact=False):
    rm, ra = load_snapshot(reference)
    cm, ca = load_snapshot(candidate)
    rows = []
    required = list(rm["variables"]) if outputs is None else outputs
    if outputs is None and set(rm["variables"]) != set(cm["variables"]):
        rows.append({"variable": "__schema__", "pass": False, "reason": "variable set mismatch"})
    for name in required:
        row = {"variable": name, "pass": False}
        rows.append(row)
        if rm["years"] != YEARS or cm["years"] != YEARS:
            row["reason"] = "timestamps must be exactly 2011..2050"
            continue
        if name not in ra or name not in ca:
            row["reason"] = "missing variable"
            continue
        for field in ("dims", "coords", "columns"):
            if rm["variables"][name][field] != cm["variables"][name][field]:
                row["reason"] = f"{field} mismatch"
                break
        if "reason" in row:
            continue
        a, b = ra[name], ca[name]
        if a.shape != b.shape or a.shape != (len(YEARS), len(rm["variables"][name]["columns"])):
            row["reason"] = "shape mismatch"
            continue
        finite = np.isfinite(a) & np.isfinite(b)
        if not finite.all():
            where = np.argwhere(~finite)[0]
            row.update(reason="nonfinite reference" if not np.isfinite(a).all() else "nonfinite candidate",
                       year=YEARS[int(where[0])], column=rm["variables"][name]["columns"][int(where[1])])
            continue
        error = np.abs(a - b)
        scale = np.maximum(1., np.max(np.abs(a), axis=0))
        discrete = rm["variables"][name].get("discrete", False)
        if discrete != cm["variables"][name].get("discrete", False):
            row["reason"] = "discrete classification mismatch"
            continue
        limit = np.zeros_like(a) if exact or discrete else PINS["atol_scale"] * scale + PINS["rtol"] * np.abs(a)
        failures = error > limit
        row.update({"pass": not failures.any(), "elements": int(a.size), "failures": int(failures.sum()),
                    "max_abs": float(error.max()),
                    "max_scaled_error": float((error / scale).max())})
        if failures.any():
            t, j = np.argwhere(failures)[0]
            row.update(year=YEARS[int(t)], column=rm["variables"][name]["columns"][int(j)],
                       reference=float(a[t, j]), candidate=float(b[t, j]), tolerance=float(limit[t, j]))
    return {"pass": bool(rows) and all(r["pass"] for r in rows), "rows": rows}
