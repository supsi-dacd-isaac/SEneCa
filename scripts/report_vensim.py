#!/usr/bin/env python3
"""Summarize frozen native comparisons, including supplier-wise annual totals."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from scripts.compare_vensim import implementation, verify, verify_execution, oracle_destination
from scripts.julia_repro.common import YEARS, digest, dump, read
from scripts.julia_repro.results import load_snapshot
from scripts.vensim_comparison.core import SECTIONS


def annual_series(meta, values):
    """Sum representative month/hour profiles with the app's 365/12 factor."""
    dims, coords = meta["dims"], meta["coords"]
    if "Month" not in dims or "Hour" not in dims:
        return None
    axes = tuple(1 + dims.index(d) for d in ("Month", "Hour"))
    shape = (len(YEARS), *(len(coords[d]) for d in dims))
    reduced = values.reshape(shape).sum(axis=axes) * (365/12)
    remaining = [d for d in dims if d not in ("Month", "Hour")]
    if remaining not in ([], ["Supplier"]):
        raise ValueError(f"Unexpected annual dimensions: {remaining}")
    labels = coords["Supplier"] if remaining else ["total"]
    return labels, reduced.reshape(len(YEARS), len(labels))


def native_path(target, case):
    return target / ("reconstructed" if case["section"] == "elettricita" else "vensim") / case["id"]


def analyze(reference, parametric, target, oracle, extra_oracles=()):
    inventory = verify(reference, parametric, target)
    verify_execution(target, inventory)
    report = read(target / "report.json")
    if report["comparison_implementation"] != implementation():
        raise ValueError("Re-run compare with the current comparison code")
    for name, sha in report["comparisons"].items():
        if digest(target / "comparisons" / name) != sha:
            raise ValueError(f"Modified comparison: {name}")
    for name, sha in report["derived_evidence"].items():
        if digest(target / name) != sha:
            raise ValueError(f"Modified reconstruction: {name}")
    cases = [c for c in report["cases"] if c["profile"] == "mdl_defaults"]
    summary = {"model_sha256": inventory["model_sha256"], "report_sha256": digest(target / "report.json"),
               "analysis_sha256": digest(Path(__file__)), "sections": {}, "controls": {},
               "defaults_differ": inventory["defaults_differ"], "comparison_count": len(report["cases"]),
               "native_scenarios_compared": len(cases), "unique_julia_jobs": len(inventory["jobs"]),
               "native_equivalence_certified": False}
    all_rows, annual_rows = [], []
    for case in report["cases"]:
        result = read(target / "comparisons" / f"{case['id']}_{case['profile']}.json")
        for row in result["rows"]:
            all_rows.append({"case": case["id"], "labels": ",".join(case["labels"]), "section": case["section"],
                             "profile": case["profile"], **{k: v for k, v in row.items() if not isinstance(v, (dict, list))}})
        if case["section"] != "elettricita":
            continue
        meta, a = load_snapshot(native_path(target, case))
        _, b = load_snapshot(target / "candidate" / case["job"])
        for name, item in meta["variables"].items():
            labels, ar = annual_series(item, a[name])
            _, br = annual_series(item, b[name])
            for j, label in enumerate(labels):
                av, bv = ar[:, j], br[:, j]
                err = abs(av-bv)
                peak = float(abs(av).max())
                significant = abs(av) >= .01 * (peak or 1.)
                annual_rows.append({"case": case["id"], "profile": case["profile"], "variable": name,
                    "supplier": label, "native_peak_GWh": peak, "max_abs_GWh": float(err.max()),
                    "max_percent_of_native_peak": float(100*err.max()/peak) if peak else None,
                    "max_relative_percent_significant": float(100*(err[significant]/abs(av[significant])).max()) if significant.any() else None,
                    "vensim_2050_GWh": float(av[-1]), "julia_2050_GWh": float(bv[-1])})
    for section in SECTIONS:
        selected = [c for c in cases if c["section"] == section]
        rows = [r for r in all_rows if r["section"] == section and r["profile"] == "mdl_defaults"]
        by_case = []
        for case in selected:
            variables = read(target / "comparisons" / f"{case['id']}_mdl_defaults.json")["rows"]
            worst = max(variables, key=lambda r: r["max_fraction_variable_scale"])
            by_case.append({"id": case["id"], "labels": case["labels"], "job": case["job"],
                            "worst": {k: worst[k] for k in ("variable", "max_abs", "max_fraction_variable_scale", "maximum_difference")},
                            "first_divergence": min((r["first_divergence"]["year"] for r in variables if "first_divergence" in r), default=None)})
        summary["sections"][section] = {**inventory["sections"][section], "cells_compared": sum(r["cells"] for r in rows),
            "numerical_failures": sum(r["failures"] for r in rows), "beyond_one_percent_diagnostic": sum(r["beyond_one_percent"] for r in rows),
            "variable_comparisons": len(rows), "variables_matching": sum(r["pass"] for r in rows),
            "cases": by_case, "worst": max(by_case, key=lambda c: c["worst"]["max_fraction_variable_scale"])}
    # Paired changes keep the same unknown native background defaults. They
    # test that each control acts in both engines, not full equivalence.
    base = next(c for c in cases if c["section"] == "elettricita" and "base" in c["labels"])
    meta, na = load_snapshot(native_path(target, base))
    _, ja = load_snapshot(target / "candidate" / base["job"])
    # With Provvedimento 1.3=0, the MDL pumping profile is the normalized
    # inverse of PHS supply, clipped at 0.001681. The observed annual total
    # cancels when testing only this shape identity; it is not recalibrated.
    supply_name = "Hourly available supply by Supplier"
    supply_meta = meta["variables"][supply_name]
    if supply_meta["dims"] != ["Month", "Hour", "Supplier"]:
        raise ValueError("Unexpected PHS supply coordinates")
    shape = (len(YEARS), *(len(supply_meta["coords"][d]) for d in supply_meta["dims"]))
    supplier = supply_meta["coords"]["Supplier"].index("PHS")
    phs = {}
    for engine, arrays in (("vensim", na), ("julia", ja)):
        supply = arrays[supply_name].reshape(shape)[:, :, :, supplier]
        demand = arrays["PHS hourly demand"].reshape(shape[:3])
        inverse = 1/np.maximum(supply, .001681)
        rebuilt = inverse/inverse.sum(axis=(1,2), keepdims=True)*demand.sum(axis=(1,2), keepdims=True)
        phs[engine] = {"shape_identity_max_abs_GWh": float(abs(rebuilt-demand).max())}
    difference = abs(na["PHS hourly demand"]-ja["PHS hourly demand"])
    t, j = np.unravel_index(difference.argmax(), difference.shape)
    month, hour = np.unravel_index(j, shape[1:3])
    phs["largest_pumping_difference"] = {"year": YEARS[t], "month": supply_meta["coords"]["Month"][month],
        "hour": supply_meta["coords"]["Hour"][hour],
        "demand_vensim_GWh": float(na["PHS hourly demand"][t,j]), "demand_julia_GWh": float(ja["PHS hourly demand"][t,j]),
        "supply_vensim_GWh": float(na[supply_name].reshape(shape)[t,month,hour,supplier]),
        "supply_julia_GWh": float(ja[supply_name].reshape(shape)[t,month,hour,supplier])}
    summary["base_phs_profile_diagnostic"] = phs
    for case in cases:
        if case["section"] != "elettricita":
            continue
        changed = [k for k in base["inputs"] if case["inputs"][k] != base["inputs"][k]]
        if len(changed) != 1 or not changed[0].startswith("Provvedimento"):
            continue
        _, nb = load_snapshot(native_path(target, case))
        _, jb = load_snapshot(target / "candidate" / case["job"])
        rows = []
        for name, item in meta["variables"].items():
            dn, dj = nb[name]-na[name], jb[name]-ja[name]
            limit = 1e-10*np.maximum(1., abs(na[name]).max(axis=0)) + 1e-8*abs(na[name])
            active_n, active_j = (abs(dn) > limit).any(axis=1), (abs(dj) > limit).any(axis=1)
            labels, an = annual_series(item, dn)
            _, aj = annual_series(item, dj)
            rows.append({"variable": name, "first_native_effect": YEARS[int(active_n.argmax())] if active_n.any() else None,
                         "first_julia_effect": YEARS[int(active_j.argmax())] if active_j.any() else None,
                         "native_max_effect": float(abs(dn).max()), "julia_max_effect": float(abs(dj).max()),
                         "max_effect_difference": float(abs(dn-dj).max()),
                         "annual_2050_effect_GWh": {label: {"vensim": float(an[-1,j]), "julia": float(aj[-1,j])} for j, label in enumerate(labels)}})
        summary["controls"][changed[0]] = {"case": case["id"], "rows": rows}
    if oracle:
        oi = verify(reference, parametric, oracle)
        verify_execution(oracle, oi)
        tr = read(oracle / "triangulation.json")
        py = read(oracle / "python/report.json")
        if (not py["completed"] or digest(oracle / "python/report.json") != tr["oracle_sha256"]
                or any(digest(oracle / "python" / name) != sha for name, sha in py["artifacts"].items())):
            raise ValueError("Oracle artifacts changed")
        if tr["implementation"] != implementation() or oi["model_sha256"] != inventory["model_sha256"]:
            raise ValueError("Oracle model or comparison changed")
        if any(job not in {j["id"] for j in inventory["jobs"]} for job in tr["jobs"]):
            raise ValueError("Oracle scenario not present in this suite")
        summary["python_julia"] = {"source": str(oracle), "triangulation_sha256": digest(oracle / "triangulation.json"),
            "jobs": {job: {"pass": result["python_julia"]["pass"], "variables": len(result["python_julia"]["rows"]),
                "max_tolerance_fraction": max(r["max_tolerance_fraction"] for r in result["python_julia"]["rows"])}
                for job, result in tr["jobs"].items()}}
        replay = {}
        available = {j["id"]: j for j in inventory["jobs"]}
        for job in oi["jobs"]:
            if job["id"] not in available:
                continue
            if job != available[job["id"]]:
                raise ValueError("Replayed scenario parameters differ")
            am, av = load_snapshot(oracle / "candidate" / job["id"])
            bm, bv = load_snapshot(target / "candidate" / job["id"])
            replay[job["id"]] = (am["years"] == bm["years"] and am["variables"] == bm["variables"]
                                 and all(np.array_equal(av[n], bv[n]) for n in av))
        summary["pilot_replay_exact"] = replay
    summary["additional_oracles"] = {}
    for name in extra_oracles:
        destination = oracle_destination(target, name)
        tri_path = target / f"triangulation-{name}.json"
        tri, py = read(tri_path), read(destination / "report.json")
        if (not py["completed"] or tri["implementation"] != implementation()
                or tri["oracle_sha256"] != digest(destination / "report.json")
                or any(digest(destination / p) != sha for p, sha in py["artifacts"].items())):
            raise ValueError(f"Additional oracle changed: {name}")
        summary["additional_oracles"][name] = {"triangulation_sha256": digest(tri_path),
            "jobs": {job: {"pass": result["python_julia"]["pass"], "variables": len(result["python_julia"]["rows"]),
                "max_tolerance_fraction": max(r["max_tolerance_fraction"] for r in result["python_julia"]["rows"])}
                for job, result in tri["jobs"].items()}}
    destination = target / "analysis"
    dump(destination / "summary.json", summary)
    for name, rows in (("variables.csv", all_rows), ("annual-by-supplier.csv", annual_rows)):
        fields = list(dict.fromkeys(key for row in rows for key in row))
        with (destination / name).open("w", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=fields)
            writer.writeheader(); writer.writerows(rows)
    dump(destination / "artifacts.json", {p.name: digest(p) for p in sorted(destination.iterdir())
                                          if p.is_file() and p.name != "artifacts.json"})
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--oracle-dir", type=Path)
    parser.add_argument("--extra-oracle-name", action="append", default=[])
    parser.add_argument("--reference", type=Path, default=ROOT / "dist/julia-repro/20261009-reproducibility")
    parser.add_argument("--parametric", type=Path, default=ROOT / "dist/julia-parametric/20261009")
    args = parser.parse_args()
    summary = analyze(args.reference.resolve(), args.parametric.resolve(), args.run_dir.resolve(),
                      args.oracle_dir.resolve() if args.oracle_dir else None, args.extra_oracle_name)
    print(f"Analyzed {summary['native_scenarios_compared']} native scenarios; numerical certification: False")


if __name__ == "__main__":
    main()
