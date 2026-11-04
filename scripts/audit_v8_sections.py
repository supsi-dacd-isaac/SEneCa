"""Verify every v8 section store and measure changes from the received preview.

The corrected Python/Julia comparison is a strict gate. Differences from the
uncorrected preview are reported separately and never relax that gate.
Hourly electricity is read one configuration at a time to bound memory.
"""
import argparse
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sure_julia.common import ROOT, MODEL_REVISION, digest, dump, model_sources, read
from sure_julia.python_batch import DESTINATIONS, jobs
from sure_julia.batch import configs


def compare_tables(reference, candidate, keys, scale_keys, values):
    a = reference.sort_values(keys).reset_index(drop=True)
    b = candidate.sort_values(keys).reset_index(drop=True)
    if (set(a) != set(b) or a.duplicated(keys).any() or b.duplicated(keys).any()
            or not a[keys].equals(b[keys])):
        raise ValueError("Store columns, scenario grid or coordinates differ")
    left, right = a[values].to_numpy(), b[values].to_numpy()
    if not (np.isfinite(left).all() and np.isfinite(right).all()):
        raise ValueError("Nonfinite section data")
    scale = a[values].abs().groupby([a[n] for n in scale_keys], dropna=False).transform("max").to_numpy()
    error = abs(left-right)
    tolerance = 1e-10*np.maximum(1., scale) + 1e-8*abs(left)
    return {"rows": len(a), "cells": int(left.size), "failures": int((error > tolerance).sum()),
            "max_tolerance_fraction": float((error/tolerance).max()),
            "max_abs": {n: float(error[:, i].max()) for i, n in enumerate(values)}}


def aggregate(rows):
    names = {name for row in rows for name in row["max_abs"]}
    return {"rows": sum(row["rows"] for row in rows),
            "cells": sum(row["cells"] for row in rows),
            "cells_beyond_tolerance": sum(row["failures"] for row in rows),
            "max_tolerance_fraction": max(row["max_tolerance_fraction"] for row in rows),
            "max_abs": {name: max(row["max_abs"].get(name, 0.) for row in rows) for name in names}}


def audit(preview, paired, generated, output):
    reviewed = read(ROOT / "docs/validation/v8-inputs.json")
    for filename, expected in reviewed["preview_stores_sha256"].items():
        if digest(preview / filename) != expected:
            raise ValueError(f"Reference is not the received v8 preview: {filename}")
    planned = jobs()
    manifest = read(paired / "manifest.json")
    if (manifest["jobs"] != planned or manifest["sources"] != model_sources()
            or not manifest.get("verify_julia")
            or manifest["julia_build"] != digest(ROOT / "sure_julia/generated/build.json")):
        raise ValueError("Paired generation does not cover the current v8 model and grid")
    if not read(paired / "summary.json")["complete"] or list((paired / "failed").glob("*.json")):
        raise ValueError("Paired generation is incomplete")
    cells, maximum = 0, 0.
    for job in planned:
        report = read(paired / "completed" / (job["id"] + ".json"))
        comparison = report.get("julia_comparison") or {}
        if (report["parameters"] != job["parameters"] or not report["physical"]["pass"]
                or not comparison.get("pass")
                or {r["variable"] for r in comparison["rows"]} != set(job["outputs"])):
            raise ValueError("Missing or failed scenario equivalence evidence")
        for path, expected in report["files"].items():
            if digest(paired / path) != expected:
                raise ValueError("A verified Python part changed")
        cells += sum(row["cells"] for row in comparison["rows"])
        maximum = max(maximum, max(row.get("max_tolerance_fraction", 0.) for row in comparison["rows"]))
    result = {"pass": True, "model_revision": MODEL_REVISION, "scenarios": len(planned),
              "configurations": sum(len(job["destinations"]) for job in planned),
              "python_julia_cells": cells, "max_python_julia_tolerance_fraction": maximum,
              "preview_archive_sha256": reviewed["preview_archive_sha256"],
              "paired_manifest_sha256": digest(paired / "manifest.json"), "sections": {}}
    reference = paired / "release/precomputed"
    julia = generated / "release/precomputed"
    for section, filename in DESTINATIONS.items():
        cfg = configs()[section.removesuffix("_gmd")]
        inputs = list(cfg.INPUT_ORDER)
        paths = [folder / filename for folder in (preview, reference, julia)]
        strict, changes = [], []
        if section == "elettricita":
            combos = pd.read_parquet(reference / "elettricita_combo_index.parquet")
            for folder in (preview, julia):
                other = pd.read_parquet(folder / "elettricita_combo_index.parquet")
                pd.testing.assert_frame_equal(combos.sort_values(inputs).reset_index(drop=True),
                                              other.sort_values(inputs).reset_index(drop=True), check_exact=True)
            for combo in combos.to_dict("records"):
                filters = [(name, "=", value) for name, value in combo.items()]
                frames = [pq.read_table(path, filters=filters).to_pandas() for path in paths]
                axes = ["variable", "month", "hour", "supplier"]
                keys = inputs + axes + ["year"]
                strict.append(compare_tables(frames[1], frames[2], keys, inputs+axes, ["value"]))
                changes.append(compare_tables(frames[0], frames[2], keys, inputs+axes, ["value"]))
        else:
            frames = [pd.read_parquet(path) for path in paths]
            keys = inputs + ["year" if section.endswith("_gmd") else "Time"]
            values = sorted(set(frames[0])-set(keys))
            strict.append(compare_tables(frames[1], frames[2], keys, inputs, values))
            changes.append(compare_tables(frames[0], frames[2], keys, inputs, values))
        verified, preview_delta = aggregate(strict), aggregate(changes)
        if verified["cells_beyond_tolerance"]:
            raise ValueError(f"Published Julia store differs from corrected Python: {section}")
        result["sections"][section] = {"python_julia": verified, "preview_delta": preview_delta,
            "sha256": dict(zip(("preview", "python", "julia"), map(digest, paths)))}
        print(section, "PASS", verified["cells"], "cells; preview differences:",
              preview_delta["cells_beyond_tolerance"], flush=True)
    dump(output, result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("preview", type=Path)
    parser.add_argument("paired", type=Path)
    parser.add_argument("generated", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    audit(args.preview, args.paired, args.generated, args.output)
