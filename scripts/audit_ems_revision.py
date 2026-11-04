"""Audit regenerated EMS stores and quantify changes from the received revision."""
import argparse
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sure_julia.common import ROOT, MODEL_REVISION, read, dump, digest, model_sources
from sure_julia.python_batch import DESTINATIONS, jobs
from sure_julia.batch import configs


def audit(original, run, output):
    manifest = read(run / "manifest.json")
    planned = jobs()
    if (manifest["jobs"] != planned or manifest["sources"] != model_sources()
            or not manifest.get("verify_julia")
            or manifest["julia_build"] != digest(ROOT / "sure_julia/generated/build.json")):
        raise ValueError("Generation does not match the complete current EMS model/grid")
    reports = [read(run / "completed" / (j["id"] + ".json")) for j in planned]
    cells, maximum = 0, 0.
    for job, report in zip(planned, reports):
        comparison = report.get("julia_comparison") or {}
        if (report["parameters"] != job["parameters"] or not report["physical"]["pass"]
                or not comparison.get("pass")
                or {r["variable"] for r in comparison["rows"]} != set(job["outputs"])):
            raise ValueError("Missing or failed Python-Julia evidence")
        for name, expected in report["files"].items():
            if digest(run / name) != expected:
                raise ValueError("Generated part differs from the verified simulation")
        cells += sum(r["cells"] for r in comparison["rows"])
        maximum = max(maximum, max(r.get("max_tolerance_fraction", 0.) for r in comparison["rows"]))
    result = {"pass": True, "model_revision": MODEL_REVISION,
              "scenarios": len(planned), "configurations": sum(len(j["destinations"]) for j in planned),
              "python_julia_cells": cells, "max_python_julia_tolerance_fraction": maximum,
              "generation_manifest_sha256": digest(run / "manifest.json"), "sections": {}}
    for section, filename in DESTINATIONS.items():
        old_path, new_path = original / filename, run / "release/precomputed" / filename
        old, new = pd.read_parquet(old_path), pd.read_parquet(new_path)
        cfg = configs()[section.removesuffix("_gmd")]
        time = "year" if section.endswith("_gmd") else "Time"
        keys = cfg.INPUT_ORDER + [time]
        old, new = old.sort_values(keys).reset_index(drop=True), new.sort_values(keys).reset_index(drop=True)
        if (set(old) != set(new) or old.duplicated(keys).any() or new.duplicated(keys).any()
                or not old[keys].equals(new[keys])):
            raise ValueError(f"Changed columns, grid or years: {section}")
        names = sorted(set(old) - set(keys))
        a, b = old[names].to_numpy(), new[names].to_numpy()
        if not (np.isfinite(a).all() and np.isfinite(b).all()):
            raise ValueError("Nonfinite data")
        scale = old[names].abs().groupby([old[n] for n in cfg.INPUT_ORDER]).transform("max").to_numpy()
        error = abs(a-b)
        tolerance = 1e-10*np.maximum(1., scale) + 1e-8*abs(a)
        changed = error > tolerance
        variables = {}
        for i, name in enumerate(names):
            base = name.split("[")[0]
            row = variables.setdefault(base, {"max_abs": 0., "max_scaled_error": 0., "cells_beyond_old_tolerance": 0})
            row["max_abs"] = max(row["max_abs"], float(error[:,i].max()))
            row["max_scaled_error"] = max(row["max_scaled_error"], float((error[:,i]/np.maximum(1.,abs(a[:,i]))).max()))
            row["cells_beyond_old_tolerance"] += int(changed[:,i].sum())
        result["sections"][section] = {"original_sha256": digest(old_path), "new_sha256": digest(new_path),
            "rows": len(new), "cells": int(a.size), "cells_beyond_old_tolerance": int(changed.sum()),
            "variables": variables}
    # Differences from the old model are measured, not used to relax acceptance
    # between the two implementations of the corrected model.
    dump(output, result)
    print(f"Verified {len(planned)} Python-Julia simulations and {len(DESTINATIONS)} stores")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path, help="Directory containing the five received Parquets")
    parser.add_argument("run", type=Path, help="Complete python_batch --verify-julia run")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    audit(args.original, args.run, args.output)
