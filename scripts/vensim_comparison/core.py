from __future__ import annotations

import ast
import hashlib
import importlib
import itertools
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from scripts.julia_repro.common import ROOT, YEARS, digest, dump, read
from scripts.julia_repro.inventory import columns_for
from scripts.julia_repro.results import save_frame, load_snapshot
from scripts.julia_parametric.model import resolve_name

SECTIONS = ("pv_batteries", "risanamento", "veicoli", "elettricita")


def config(section):
    return importlib.import_module(f"pv_batteries.{section}_config")


def source_defaults(manifest, names):
    """Literal MDL defaults are a documented hypothesis, not VPMX provenance."""
    nodes = {n.name: n for n in ast.parse((ROOT / "Vensim/SURE_pysd_v3.py").read_text()).body
             if isinstance(n, ast.FunctionDef)}
    result = {}
    for name in names:
        canonical = resolve_name(name, manifest["variables"])
        node = nodes[manifest["variables"][canonical]["python_name"]]
        body = [n for n in node.body if not isinstance(n, ast.Expr)]
        if len(body) != 1 or not isinstance(body[0], ast.Return):
            raise ValueError(f"Not a literal scenario default: {name}")
        result[name] = float(ast.literal_eval(body[0].value))
    return result


def parameter_key(values):
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


def selections(cfg, suite):
    cases = {"base": cfg.BASE_SCENARIO,
             "low": {k: min(v) for k, v in cfg.INPUT_GRID.items()},
             "mid": {k: sorted(v)[len(v)//2] for k, v in cfg.INPUT_GRID.items()},
             "high": {k: max(v) for k, v in cfg.INPUT_GRID.items()}}
    if suite == "targeted":
        for i, (name, values) in enumerate(cfg.INPUT_GRID.items()):
            for j, value in enumerate(values):
                cases[f"lever_{i}_{j}"] = {**cfg.BASE_SCENARIO, name: value}
        rng = np.random.default_rng(20261012)
        for i in range(8):
            cases[f"random_{i}"] = {k: float(rng.choice(v)) for k, v in cfg.INPUT_GRID.items()}
    elif suite == "full":
        cases.update({f"grid_{i:04d}": dict(zip(cfg.INPUT_GRID, combo))
                      for i, combo in enumerate(itertools.product(*cfg.INPUT_GRID.values()))})
    elif suite != "pilot":
        raise ValueError(suite)
    unique = {}
    for label, values in cases.items():
        values = {k: float(v) for k, v in values.items()}
        key = parameter_key(values)
        unique.setdefault(key, {"labels": [], "inputs": values})["labels"].append(label)
    return list(unique.values())


def hourly_frame(table, expected_columns, *, allow_missing=False):
    frame = table.to_pandas()
    if not allow_missing and len(frame) != len(YEARS) * len(expected_columns):
        raise ValueError("Missing or extra native hourly cells")
    if frame.duplicated(["variable", "month", "hour", "supplier", "year"]).any():
        raise ValueError("Duplicate native Vensim cells")
    subs = frame.month + "," + frame.hour
    subs = subs.where(frame.supplier == "", subs + "," + frame.supplier)
    frame["column"] = frame.variable + "[" + subs + "]"
    wide = frame.pivot(index="year", columns="column", values="value")
    if set(wide.columns) != set(expected_columns) or list(wide.index) != YEARS:
        raise ValueError("Native hourly schema or years differ")
    return wide.loc[YEARS, expected_columns]


def reconstruct_import(frame, model_text):
    """A separate MDL-based hypothesis; never change the archived reference."""
    equation = r"Hourly exported electricity\[Month,Hour,Import\]\s*=\s*0\s*(?:~~|~)"
    if not re.search(equation, model_text):
        raise ValueError("The source MDL does not prove the zero Import export equation")
    columns = [c for c in frame if c.startswith("Hourly exported electricity[") and c.endswith(",Import]")]
    if not columns or list(frame.index) != YEARS:
        raise ValueError("Missing Import coordinates or years")
    a = frame.to_numpy()
    missing = np.isnan(a)
    expected = np.zeros_like(missing)
    expected[1:, [frame.columns.get_loc(c) for c in columns]] = True
    if (not np.array_equal(missing, expected) or not np.isfinite(a[~missing]).all()
            or not (frame.loc[YEARS[0], columns] == 0).all()):
        raise ValueError("Missing data are not exactly the documented sparse constant")
    reconstructed = frame.copy()
    reconstructed.loc[YEARS[1:], columns] = 0.
    return reconstructed, {"variable": "Hourly exported electricity", "supplier": "Import",
        "years": YEARS[1:], "columns": columns, "cells": int(missing.sum()), "value": 0.,
        "provenance": "Reconstructed from the MDL equation, not measured VPMX results"}


def reconstruct_snapshot(source, destination, model_path):
    meta, arrays = load_snapshot(source)
    frame = pd.DataFrame({column: arrays[name][:, j] for name, item in meta["variables"].items()
                          for j, column in enumerate(item["columns"])}, index=meta["years"])
    corrected, certificate = reconstruct_import(frame, model_path.read_text())
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = {item["key"]: corrected[item["columns"]].to_numpy()
            for item in meta["variables"].values()}
    np.savez_compressed(destination.with_suffix(".npz"), **data)
    meta["sha256"] = digest(destination.with_suffix(".npz"))
    dump(destination.with_suffix(".json"), meta)
    certificate.update(source_sha256=digest(source.with_suffix(".json")),
                       mdl_sha256=digest(model_path), reconstructed_sha256=digest(destination.with_suffix(".json")))
    dump(destination.with_suffix(".reconstruction.json"), certificate)
    return certificate


def frame_audit(frame, columns):
    values = frame[columns].to_numpy(dtype=np.float64)
    finite = np.isfinite(values)
    return {"cells": int(values.size), "nonfinite": int((~finite).sum()),
            "exact_float32_values": int((finite & (values.astype(np.float32).astype(np.float64) == values)).sum())}


def prepare(reference, parametric, target, suite):
    target.mkdir(parents=True, exist_ok=False)
    manifest = read(reference / "manifest.json")
    model_certificate = read(parametric / "model/model.json")
    defaults = source_defaults(manifest, model_certificate["parameters"])
    ui = model_certificate["defaults"]
    exports = read(parametric / "model/export.json")
    outputs = list(dict.fromkeys(name for section in SECTIONS for name in config(section).OUTPUT_BASES))
    export = [item for item in exports if item["name"] in outputs]
    if {item["name"] for item in export} != set(outputs):
        raise ValueError("Some Vensim outputs have no certified Julia export")
    dump(target / "export.json", export)
    report = {"suite": suite, "sections": {}, "source_defaults": defaults,
              "ui_defaults": ui, "defaults_differ": {k: {"mdl": defaults[k], "ui": ui[k]} for k in defaults if defaults[k] != ui[k]},
              "default_provenance": "MDL literals; untouched VPMX inputs were not stored in the archives and are unverified",
              "release": read(ROOT / "data-release.json"), "files": {}, "jobs": [], "cases": [],
              "model_sha256": model_certificate["model_sha256"]}
    bound = [ROOT / "Vensim/SURE.mdl", ROOT / "Vensim/SURE.vpmx", ROOT / "Vensim/SURE_pysd_v3.py",
             ROOT / "constants_ref_v3.pkl", ROOT / "data-release.json", ROOT / ".data-release-installed.json",
             reference / "manifest.json", parametric / "model/model.json", parametric / "model" / model_certificate["model"]]
    bound += [ROOT / "pv_batteries" / name for name in ("vensim_runner.py", "section_engine.py", "section_engine_hourly.py", "precompute_pv_batteries.py")]
    for section in SECTIONS:
        cfg = config(section)
        bound.append(Path(cfg.__file__))
        path = ROOT / "precomputed" / ("elettricita_hourly.parquet" if section == "elettricita" else f"{section}_scenarios.parquet")
        bound.append(path)
        columns = [c for name in cfg.OUTPUT_BASES for c in columns_for(name, manifest)]
        selected = selections(cfg, suite)
        wanted = {tuple(row["inputs"][name] for name in cfg.INPUT_GRID): row for row in selected}
        found, archive = {}, []
        if section == "elettricita":
            parquet = pq.ParquetFile(path)
            for g in range(parquet.num_row_groups):
                table = parquet.read_row_group(g)
                inputs = {name: table[name].unique().to_pylist() for name in cfg.INPUT_GRID}
                if any(len(v) != 1 for v in inputs.values()):
                    raise ValueError("Hourly row group is not a single scenario")
                inputs = {k: float(v[0]) for k, v in inputs.items()}
                key = tuple(inputs[name] for name in cfg.INPUT_GRID)
                if key in found:
                    raise ValueError("Repeated hourly scenario")
                frame = hourly_frame(table, columns, allow_missing=True)
                # Reject any pattern other than the one explicitly documented
                # by the source equation. Keep the missing values in raw evidence.
                _, reconstruction = reconstruct_import(frame, (ROOT / "Vensim/SURE.mdl").read_text())
                audit = frame_audit(frame, columns)
                audit.update(stored_cells=table.num_rows, stored_nonfinite=int((~np.isfinite(table["value"].to_numpy())).sum()),
                             missing_cells=reconstruction["cells"])
                archive.append({"inputs": inputs, **audit})
                found[key] = True
                if key in wanted:
                    wanted[key]["frame"] = frame
        else:
            data = pq.read_table(path).to_pandas()
            if set(data.columns) != set(columns + ["Time"] + list(cfg.INPUT_GRID)):
                raise ValueError(f"Unexpected archive columns: {section}")
            for key, group in data.groupby(list(cfg.INPUT_GRID), sort=False):
                frame = group.set_index("Time").sort_index()
                if frame.index.duplicated().any() or list(frame.index) != YEARS:
                    raise ValueError("Incomplete or duplicated native time series")
                inputs = dict(zip(cfg.INPUT_GRID, map(float, key)))
                archive.append({"inputs": inputs, **frame_audit(frame, columns)})
                found[key] = True
                if key in wanted:
                    wanted[key]["frame"] = frame[columns]
        expected_keys = set(itertools.product(*cfg.INPUT_GRID.values()))
        if set(found) != expected_keys or not set(wanted).issubset(found):
            raise ValueError(f"Native scenario grid differs: {section}")
        dump(target / "archive-audit" / f"{section}.json", archive)
        report["sections"][section] = {"archive_scenarios": len(archive), "selected_scenarios": len(selected),
            "variables": len(cfg.OUTPUT_BASES), "series": len(columns),
            "cells": sum(a["cells"] for a in archive), "nonfinite": sum(a["nonfinite"] for a in archive),
            "stored_cells": sum(a.get("stored_cells", a["cells"]) for a in archive),
            "stored_nonfinite": sum(a.get("stored_nonfinite", a["nonfinite"]) for a in archive),
            "missing_cells": sum(a.get("missing_cells", 0) for a in archive),
            "non_float32": sum(a["cells"] - a["nonfinite"] - a["exact_float32_values"] for a in archive)}
        for index, selected_case in enumerate(selected):
            identifier = f"{section}_{index:03d}"
            snapshot = target / "vensim" / identifier
            snapshot.parent.mkdir(exist_ok=True)
            save_frame(snapshot, selected_case["frame"], cfg.OUTPUT_BASES, manifest)
            profiles = {"mdl_defaults": {**defaults, **selected_case["inputs"]}}
            # Counterfactual alignment check, never choose the best fit as proof
            # of the unpublished VPMX defaults.
            if "base" in selected_case["labels"]:
                profiles["ui_defaults"] = {**ui, **selected_case["inputs"]}
            for profile, parameters in profiles.items():
                job_id = parameter_key(parameters)
                report["cases"].append({"id": identifier, "section": section, "labels": selected_case["labels"],
                    "profile": profile, "job": job_id, "inputs": selected_case["inputs"], "parameters": parameters})
                if not any(job["id"] == job_id for job in report["jobs"]):
                    report["jobs"].append({"id": job_id, "parameters": parameters})
        print(f"Archive {section}: {len(archive)} scenarios audited, {len(selected)} selected", flush=True)
    report["files"] = {str(p): digest(p) for p in bound}
    report["references"] = {str(p.relative_to(target)): digest(p) for p in sorted((target / "vensim").glob("*"))}
    dump(target / "jobs.json", report["jobs"])
    dump(target / "inventory.json", report)
    return report


def convert_raw(raw, destination, export, manifest):
    timing = read(raw / "timing.json")
    if timing["years"] != YEARS or timing["byte_order"] != "little":
        raise ValueError("Incomplete Julia output")
    values = {}
    for i, item in enumerate(export):
        cols = columns_for(item["name"], manifest)
        array = np.fromfile(raw / f"v{i:04d}.bin", dtype="<f8")
        if array.size != len(YEARS) * len(cols):
            raise ValueError("Incomplete Julia variable")
        values.update(zip(cols, array.reshape(len(YEARS), len(cols)).T))
    destination.parent.mkdir(parents=True, exist_ok=True)
    save_frame(destination, pd.DataFrame(values, index=YEARS), [e["name"] for e in export], manifest)


def comparison(reference, candidate):
    rm, ra = load_snapshot(reference)
    cm, ca = load_snapshot(candidate)
    rows = []
    for name, metadata in rm["variables"].items():
        row = {"variable": name, "pass": False, "expected_cells": len(YEARS) * len(metadata["columns"])}
        rows.append(row)
        if rm["years"] != YEARS or cm["years"] != YEARS or name not in ca:
            row["reason"] = "Missing years or variable"
            continue
        if any(metadata[k] != cm["variables"][name][k] for k in ("dims", "coords", "columns")):
            row["reason"] = "Coordinate mismatch"
            continue
        a, b = ra[name], ca[name]
        row.update(reference_nonfinite=int((~np.isfinite(a)).sum()), candidate_nonfinite=int((~np.isfinite(b)).sum()))
        if (a.shape != b.shape or a.shape != (len(YEARS), len(metadata["columns"]))
                or not np.isfinite(a).all() or not np.isfinite(b).all()):
            row["reason"] = "Incomplete or nonfinite values"
            continue
        if not np.array_equal(a, a.astype(np.float32).astype(np.float64)):
            row["reason"] = "Archive is not an exact Float32 export"
            continue
        error = abs(a - b)
        series_scale = np.maximum(1., abs(a).max(axis=0))
        # Preserve the agreed near-numerical criterion. Quantization bounds
        # account only for the explicit c_float native export, not solver error.
        numerical = 1e-10 * series_scale + 1e-8 * abs(a)
        rounded = a.astype(np.float32)
        lower = (a + np.nextafter(rounded, np.float32(-np.inf)).astype(np.float64)) / 2
        upper = (a + np.nextafter(rounded, np.float32(np.inf)).astype(np.float64)) / 2
        serialization = np.maximum(a - lower, upper - a)
        if metadata.get("discrete", False):
            numerical = np.zeros_like(a)
            serialization = np.zeros_like(a)
        bad = error > numerical + serialization
        scale = float(abs(a).max()) or 1.
        significant = abs(a) >= .01*scale
        row.update({"pass": not bool(bad.any()), "cells": int(a.size), "failures": int(bad.sum()),
            "strict_failures": int((error > numerical).sum()), "same_float32": int((b.astype(np.float32) == rounded).sum()),
            "max_abs": float(error.max()), "max_fraction_variable_scale": float(error.max()/scale),
            "rms_fraction_variable_scale": float(np.sqrt(np.mean((error/scale)**2))),
            "beyond_one_percent": int((error > 1e-4*scale + .01*abs(a)).sum()),
            "variable_scale": scale,
            "max_relative_significant": float((error[significant] / abs(a[significant])).max()) if significant.any() else None,
            "max_fraction_by_year": (error.max(axis=1)/scale).tolist()})
        tmax, jmax = np.unravel_index(error.argmax(), error.shape)
        row["maximum_difference"] = {"year": YEARS[tmax], "column": metadata["columns"][jmax],
                                     "vensim": float(a[tmax,jmax]), "candidate": float(b[tmax,jmax])}
        if bad.any():
            t, j = np.argwhere(bad)[0]
            row["first_divergence"] = {"year": YEARS[t], "column": metadata["columns"][j],
                "vensim": float(a[t,j]), "candidate": float(b[t,j]), "difference": float(error[t,j]),
                "numerical_limit": float(numerical[t,j]), "float32_half_ulp": float(serialization[t,j])}
        if "Month" in metadata["dims"] and "Hour" in metadata["dims"]:
            shape = (len(YEARS), *(len(metadata["coords"][d]) for d in metadata["dims"]))
            axes = tuple(1 + metadata["dims"].index(d) for d in ("Month", "Hour"))
            ar, br = a.reshape(shape).sum(axis=axes) * (365/12), b.reshape(shape).sum(axis=axes) * (365/12)
            aggregate_scale = float(abs(ar).max()) or 1.
            mask = abs(ar) >= .01*aggregate_scale
            row["annual_aggregate"] = {"max_abs": float(abs(ar-br).max()), "days_per_month": 365/12,
                "max_fraction_scale": float(abs(ar-br).max()/aggregate_scale),
                "max_relative_significant": float((abs(ar-br)[mask]/abs(ar)[mask]).max()) if mask.any() else None}
    return {"pass": bool(rows) and all(row["pass"] for row in rows), "rows": rows}
