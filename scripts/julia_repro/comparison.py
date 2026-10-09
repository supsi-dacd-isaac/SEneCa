"""User-authorized candidate tolerance without altering the frozen oracle."""
from __future__ import annotations

import copy
import numpy as np

from .common import CONFIG, YEARS, read
from .results import compare as strict_compare, load_snapshot


def compare(reference, candidate, *, outputs=None, exact=False):
    strict = strict_compare(reference, candidate, outputs=outputs, exact=exact)
    if exact:
        return strict
    policy = read(CONFIG / "acceptance.json")
    atol, rtol = policy["atol_scale"], policy["rtol"]
    if not (np.isfinite(atol) and np.isfinite(rtol) and atol >= 0 and rtol >= 0):
        raise ValueError("Invalid numerical acceptance tolerances")
    rm, ra = load_snapshot(reference)
    _, ca = load_snapshot(candidate)
    rows = copy.deepcopy(strict["rows"])
    for row in rows:
        name = row["variable"]
        # The strict comparison must first certify the entire schema and
        # finiteness. Never turn a missing coordinate or invalid value into PASS.
        if "reason" in row or rm["variables"][name].get("discrete", False):
            continue
        a, b = ra[name], ca[name]
        scale = np.maximum(1., np.max(np.abs(a), axis=0))
        limit = atol*scale + rtol*np.abs(a)
        error = np.abs(a-b)
        failures = error > limit
        for key in ("year", "column", "reference", "candidate", "tolerance"):
            row.pop(key, None)
        row.update({"pass": not bool(failures.any()), "failures": int(failures.sum()),
                    "max_tolerance_fraction": float(np.max(np.divide(error, limit,
                        out=np.where(error == 0., 0., np.inf), where=limit != 0.)))})
        if failures.any():
            t, j = np.argwhere(failures)[0]
            row.update(year=YEARS[int(t)], column=rm["variables"][name]["columns"][int(j)],
                       reference=float(a[t,j]), candidate=float(b[t,j]), tolerance=float(limit[t,j]))
    return {"pass": bool(rows) and all(row["pass"] for row in rows), "rows": rows,
            "strict": strict, "acceptance_policy": policy}
