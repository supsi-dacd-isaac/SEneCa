"""Review the 2026-10-13 native archive against the frozen synchronous experiment.

prepare/simulate/analyze are separate so raw evidence and costly simulations
are never overwritten. Native-input allocation replay is a diagnostic: its
inputs have already been rounded to Float32 by the Vensim export.
"""
from pathlib import Path
from types import SimpleNamespace
import argparse
import hashlib
import shutil
import zipfile

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from scripts.julia_repro.common import ROOT, RUNTIME, CONFIG, YEARS, digest, dump, read, run_logged
from scripts.julia_repro.results import load_snapshot, save_frame
from scripts.julia_repro.inventory import columns_for
from scripts.julia_repro.comparison import compare
from scripts.sure_v4.synchronous_delays import install
from scripts.vensim_comparison.core import comparison, convert_raw

ARCHIVE_SHA = "2b587916c3d99cec015c2c7d1f18364c99b49f238d521a766c5539d365eb97c6"
EXTRA = ["Hourly demand and PHS", "Priority vector by supplier", "Marginal cost by supplier",
         "Hourly imported electricity", "PHS hourly supply", "Hour factor PHS consumption",
         "Seasonal PHS monthly demand", "Seasonal PHS monthly production",
         "Seasonal PHS hourly demand", "Seasonal PHS hourly production"]


def prepare(directory, archive, baseline, synchronous):
    if digest(archive) != ARCHIVE_SHA:
        raise ValueError("Unexpected native ZIP checksum")
    directory.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive) as bundle:
        for item in bundle.infolist():
            if not (directory / item.filename).resolve().is_relative_to(directory.resolve()):
                raise ValueError("Unsafe archive path")
        bundle.extractall(directory)
    manifest = read(synchronous / "manifest.json")
    manifest["diagnostics"] = list(dict.fromkeys(manifest["diagnostics"] + EXTRA))
    dump(directory / "manifest.json", manifest)
    (directory / "source").symlink_to(baseline / "source", target_is_directory=True)
    (directory / "model").mkdir()
    for name in ("SURE_v4_synchronous.jl", "SURE_pysd_v4_data.json"):
        (directory / "model" / name).symlink_to(synchronous / "model" / name)
    export = read(synchronous / "model/export.json")
    for name in EXTRA:
        if name in {e["name"] for e in export}:
            continue
        v = manifest["variables"][name]
        dims = v.get("subscripts", [])
        export.append({"name": name, "julia_name": v["python_name"], "dims": dims,
                       "coords": {d: manifest["dimensions"][d] for d in dims}})
    dump(directory / "model/export.json", export)
    dump(directory / "jobs.json", [{"id": "01_base", "parameters": manifest["scenarios"]["01_base"]}])


def simulate(directory, baseline):
    run_logged([RUNTIME / "python-reference/bin/python", "-B", "-u", "-m",
                "scripts.sure_v4.probe_delay_order", baseline, directory, "staged-before", "01_base"],
               directory / "python.log")
    run_logged([RUNTIME / "julia-1.10.12/bin/julia", "--startup-file=no", f"--project={CONFIG}",
                ROOT / "benchmarks/julia-parametric/worker.jl", directory / "model/SURE_v4_synchronous.jl",
                directory / "model/export.json", directory / "jobs.json", directory / "raw"],
               directory / "julia.log")


def native_frame(path):
    df = pq.read_table(path).to_pandas()
    if set(df.columns) != {"run_id", "variable", "element", "year", "value"}:
        raise ValueError("Unexpected native schema")
    if set(df.run_id) != {"01_base"} or df.duplicated(["variable", "element", "year"]).any():
        raise ValueError("Unexpected scenario or duplicate native coordinates")
    if not np.isfinite(df[["year", "value"]].to_numpy()).all() or df.value.dtype != np.float32:
        raise ValueError("Expected finite Float32 exports")
    return df


def wide(df, names, manifest):
    df = df[df.variable.isin(names)].copy()
    df["column"] = df.variable + ("[" + df.element + "]").where(df.element != "", "")
    frame = df.pivot(index="year", columns="column", values="value")
    columns = [col for name in names for col in columns_for(name, manifest)]
    if set(frame.columns) != set(columns) or list(frame.index) != YEARS:
        raise ValueError("Unexpected native labels or years")
    frame = frame[columns]
    if not np.isfinite(frame.to_numpy()).all():
        raise ValueError("Incomplete native grid; no implicit filling")
    return frame


def half_ulp(values):
    f = np.asarray(values, dtype=np.float32)
    return np.maximum(np.nextafter(f, np.float32(np.inf)).astype(float) - f.astype(float),
                      f.astype(float) - np.nextafter(f, np.float32(-np.inf)).astype(float)) / 2


def delay_check(raw):
    from pysd.py_backend.statefuls import Smooth, DelayFixed
    runs = read(raw / "delay-fixed/native-same-process.json")["runs"]
    initial = runs["full-1"]
    fresh_runs = read(raw / "delay-fixed/new-process.json")["runs"]
    assert len(fresh_runs) == 1
    fresh = next(iter(fresh_runs.values()))
    if set(fresh) != set(initial):
        raise ValueError("Native delay schema differs")
    for run in [*runs.values(), fresh]:
        if set(run) != set(initial):
            raise ValueError("Missing native delay outputs")
        n = len(run["Input"]["times"])
        for name, series in run.items():
            assert series["times"] == list(map(float, range(n)))
            np.testing.assert_array_equal(series["values"], initial[name]["values"][:n])
    report = {}
    for tag, years in (("001", .01), ("01", .1), ("1", 1.), ("2", 2.), ("4", 4.)):
        reference = initial[f"Nested_delay_{tag}"]["values"]
        np.testing.assert_array_equal(reference, initial[f"Named_delay_{tag}"]["values"])
        modes = {}
        for staged, reverse in ((True, False), (True, True), (False, True)):
            time = [0.]
            smooth = Smooth(lambda: 10. if time[0] >= 1 else 0., lambda: 2., lambda: 0., lambda: 1, "s")
            delay = DelayFixed(smooth, lambda: years, lambda: 0., lambda: 1., "d")
            objects = [smooth, delay] if reverse else [delay, smooth]
            model = SimpleNamespace(_dynamicstateful_elements=objects)
            def step(dt):
                next_states = [o.state + o.ddt() * dt for o in objects]
                for o, state in zip(objects, next_states):
                    o.update(state)
            model._euler_step = step
            if staged:
                install(model)
            smooth.initialize()
            delay.initialize()
            actual = [float(delay())]
            smoothed = [float(smooth())]
            for t in range(8):
                time[0] = float(t)
                model._euler_step(1.)
                actual.append(float(delay()))
                smoothed.append(float(smooth()))
            np.testing.assert_array_equal(smoothed, initial["Smoothed"]["values"])
            error = float(np.max(np.abs(np.asarray(actual) - reference)))
            modes[f"{'staged' if staged else 'sequential'}_{'smooth_first' if reverse else 'delay_first'}"] = error
            if staged:
                assert error == 0
        report[str(years)] = modes
    return {"delays": report, "native_repeats_exact": True, "native_named_nested_exact": True}


def allocation_replay(directory, raw, native, manifest):
    from pysd.py_backend.allocation import _allocate_by_priority_1d
    names = ["Hourly available supply by Supplier", "Hourly demand and PHS", "Priority vector by supplier",
             "Electricity dispatched", "Marginal cost by supplier"]
    frame = wide(native, names, manifest)
    def array(name):
        dims = manifest["variables"][name].get("subscripts", [])
        shape = (40, *(len(manifest["dimensions"][d]) for d in dims))
        return frame[columns_for(name, manifest)].to_numpy(dtype=float).reshape(shape)
    q, supply, pp, actual, costs = map(array, names)
    assert np.all(pp[:, :, 0] == 1) and np.all(pp[:, :, 2] == pp[:, :1, 2])
    calculated = np.empty_like(actual)
    fixtures = []
    # Include all 50 synthetic cases in the exact same Julia helper test.
    for c in read(raw / "native-probe/cases.json"):
        profile = np.array([np.ones(9), c["priority"], np.full(9, c["width"]), np.zeros(9)]).T
        fixtures.append({"request": c["request"], "pp": profile.tolist(), "supply": c["supply"], "expected": c["expected"]})
    for t, m, h in np.ndindex(supply.shape):
        # Published Python v4 clips negative requests and rounds common widths
        # to six decimal places before calling _allocate_by_priority_1d.
        result = _allocate_by_priority_1d(np.maximum(q[t, m, h], 0), pp[t, :, 1],
                                          float(np.round(pp[t, 0, 2], 6)), supply[t, m, h])
        calculated[t, m, h] = result
        fixtures.append({"request": q[t, m, h].tolist(), "pp": pp[t].tolist(),
                         "supply": float(supply[t, m, h]), "expected": result.tolist()})
    dump(directory / "allocation-fixtures.json", fixtures)
    run_logged([RUNTIME / "julia-1.10.12/bin/julia", "--startup-file=no", f"--project={CONFIG}",
                ROOT / "benchmarks/sure-v4-alignment/replay_allocation.jl", directory / "allocation-fixtures.json"],
               directory / "allocation-julia.log")
    error = abs(actual - calculated)
    balance = actual.sum(axis=-1) - np.minimum(np.maximum(q, 0).sum(axis=-1), supply)
    # Conservative uncertainty due ONLY to exported inputs and outputs.
    balance_quantization = half_ulp(actual).sum(axis=-1) + half_ulp(q).sum(axis=-1) + half_ulp(supply)
    suppliers = manifest["dimensions"]["Supplier"]
    imp = suppliers.index("Import")
    switches = (actual[..., imp] > 0) != (calculated[..., imp] > 0)
    # Reproduce the audited Electricity market price decision chain.
    price_order = [suppliers.index(s) for s in ("Import", "Coal", "Nuclear", "Hydro", "PHS", "RoR", "Wind", "Solar")]
    def price(allocation):
        out = np.broadcast_to(costs[:, None, None, suppliers.index("Solar")], supply.shape).copy()
        for i in reversed(price_order):
            out = np.where(allocation[..., i] > 0, costs[:, None, None, i], out)
        return out
    native_price, replay_price = price(actual), price(calculated)
    records = []
    for t, m, h in np.argwhere(switches):
        gap = float(supply[t,m,h] - np.maximum(q[t,m,h,pp[t,:,1] > pp[t,imp,1]],0).sum())
        budget = float(half_ulp(supply[t,m,h]) + half_ulp(q[t,m,h]).sum())
        records.append({"year": YEARS[t], "month": manifest["dimensions"]["Month"][m],
                        "hour": manifest["dimensions"]["Hour"][h],
                        "native_import": float(actual[t,m,h,imp]), "replay_import": float(calculated[t,m,h,imp]),
                        "supply_gap_above_import": gap, "input_quantization_bound": budget,
                        "native_balance_error": float(balance[t,m,h]),
                        "native_price": float(native_price[t,m,h]), "replay_price": float(replay_price[t,m,h])})
    dump(directory / "allocation-import-switches.json", records)
    np.savez_compressed(directory / "allocation-replay.npz", native=actual, replay=calculated,
                        requests=q, supply=supply, profile=pp, balance=balance)
    return {"hours": int(supply.size), "cells": int(actual.size), "max_abs": float(error.max()),
            "max_native_balance_error": float(abs(balance).max()),
            "native_balance_range": [float(balance.min()), float(balance.max())],
            "hours_balance_exceeds_export_quantization": int((abs(balance) > balance_quantization).sum()),
            "negative_request_cells": int((q < 0).sum()), "import_switches": len(records),
            "native_zero_replay_positive": sum(r["native_import"] == 0 for r in records),
            "switches_outside_input_quantization": sum(abs(r["supply_gap_above_import"]) > r["input_quantization_bound"] for r in records),
            "minimum_gap_quantization_ratio": min((abs(r["supply_gap_above_import"]) / r["input_quantization_bound"] for r in records), default=None),
            "price_switches": int((native_price != replay_price).sum()),
            "max_hourly_price_difference": float(abs(native_price-replay_price).max()),
            "price_units": "CHF/MWh; reconstructed with the frozen SURE Electricity market price equation",
            "first_import_switch": records[0] if records else None,
            "input_precision": "Float32 exports, not native internal Float64 inputs",
            "julia_helper": read(directory / "allocation-result.json")}


def analyze(directory, archive, baseline, synchronous, probe):
    if digest(archive) != ARCHIVE_SHA:
        raise ValueError("Unexpected archive checksum")
    raw = directory / "sure-alignment"
    with zipfile.ZipFile(archive) as bundle:
        for name in bundle.namelist():
            if (directory / name).read_bytes() != bundle.read(name):
                raise ValueError(f"Raw evidence changed: {name}")
    identity = {}
    native_manifest = read(raw / "native-probe/manifest.json")
    generator = (ROOT / "scripts/sure_v4/allocation_probe.py").read_bytes()
    assert hashlib.sha256(generator.replace(b"\n", b"\r\n")).hexdigest() == native_manifest["generator_sha256"]
    assert native_manifest["source_sha256"] == digest(baseline / "source/Vensim/SURE.mdl")
    for name, sha in native_manifest["files"].items():
        a, b = (raw / "native-probe" / name), (probe / name)
        assert digest(a) == sha
        same = a.read_bytes().replace(b"\r\n", b"\n") == b.read_bytes().replace(b"\r\n", b"\n")
        identity[name] = {"native_sha256": sha, "local_sha256": digest(b), "same_normalized_text": same}
        assert same, name
    manifest = read(directory / "manifest.json")
    assert digest(directory / "model/SURE_v4_synchronous.jl") == digest(synchronous / "model/SURE_v4_synchronous.jl")
    requested = read(raw / "original/applied-01-base.json")[0]["requested"]
    assert requested == manifest["scenarios"]["01_base"]
    reference = pq.read_table(baseline / "source/Vensim_test_runs/outputs.parquet",
                              filters=[("run_id", "=", "01_base")]).to_pandas()
    outputs = native_frame(raw / "original/outputs-01-base.parquet")
    keys = ["run_id", "variable", "element", "year"]
    merged = reference.merge(outputs, on=keys, how="outer", suffixes=("_old", "_new"), indicator=True, validate="one_to_one")
    assert (merged._merge == "both").all()
    np.testing.assert_array_equal(merged.value_old.to_numpy(dtype=np.float32), merged.value_new.to_numpy())
    diagnostics = native_frame(raw / "original/diagnostics-01-base.parquet")
    assert set(diagnostics.variable) == set(EXTRA)
    save_frame(directory / "native-diagnostics", wide(diagnostics, EXTRA, manifest), EXTRA, manifest)
    export = read(directory / "model/export.json")
    convert_raw(directory / "raw/01_base", directory / "candidate/01_base", export, manifest)
    py = directory / "reference/staged-before/01_base"
    jl = directory / "candidate/01_base"
    shared = read(synchronous / "manifest.json")["diagnostics"]
    unchanged = {
        "python": compare(synchronous / "reference/staged-before/01_base", py, outputs=shared, exact=True),
        "julia": compare(synchronous / "candidate/01_base", jl, outputs=shared, exact=True)}
    engine_check = compare(py, jl)
    assert engine_check["pass"] and all(r["pass"] for r in unchanged.values())
    allowed = {(w["category"], w["message"]) for w in read(synchronous / "reference/staged-before/warnings.json")}
    unreviewed = [w for w in read(directory / "reference/staged-before/warnings.json")
                  if (w["category"], w["message"]) not in allowed]
    assert not unreviewed, unreviewed
    # Preserve the supplied report; recompute the native comparison separately.
    from scripts.sure_v4.allocation_probe import compare_native
    local = directory / "synthetic-check"
    local.mkdir(exist_ok=True)
    shutil.copyfile(raw / "native-probe-result/native.json", local / "native.json")
    allocation_static = compare_native(raw / "native-probe", local)
    native_all = pd.concat([outputs, diagnostics], ignore_index=True)
    report = {"archive_sha256": ARCHIVE_SHA, "normalized_probe_identity": identity,
              "base_reexport_exact": True, "base_reexport_rows": len(outputs),
              "native_diagnostics_rows": len(diagnostics), "scenario_parameters_equal": True,
              "delay": delay_check(raw), "static_allocation": allocation_static["functions"],
              "extended_python_julia": engine_check, "unchanged_shared_outputs": unchanged,
              "native_vs_python": comparison(directory / "native-diagnostics", py),
              "native_vs_julia": comparison(directory / "native-diagnostics", jl),
              "native_input_allocation_replay": allocation_replay(directory, raw, native_all, manifest),
              "unreviewed_warnings": unreviewed, "native_equivalence_certified": False}
    dump(directory / "review.json", report)
    summary = {key: report[key] for key in ("archive_sha256", "normalized_probe_identity", "base_reexport_exact",
        "base_reexport_rows", "native_diagnostics_rows", "scenario_parameters_equal", "delay", "static_allocation",
        "native_input_allocation_replay", "unreviewed_warnings", "native_equivalence_certified")}
    summary["python_julia"] = {"pass": engine_check["pass"], "variables": len(engine_check["rows"]),
        "cells": sum(r["elements"] for r in engine_check["rows"]),
        "max_abs": max(r["max_abs"] for r in engine_check["rows"]),
        "shared_outputs_unchanged": {k: r["pass"] for k, r in unchanged.items()}}
    summary["diagnostics"] = [{k: row[k] for k in ("variable", "pass", "cells", "failures", "max_abs", "first_divergence") if k in row}
                              for row in report["native_vs_julia"]["rows"]]
    summary["review_sha256"] = digest(directory / "review.json")
    dump(directory / "summary.json", summary)
    evidence = {str(p.relative_to(directory)): digest(p) for p in sorted(directory.rglob("*"))
                if p.is_file() and p.name not in {"evidence.json", "analyze.log"}}
    dump(directory / "evidence.json", {"files": evidence, "archive_sha256": digest(archive),
         "implementation": {str(p.relative_to(ROOT)): digest(p) for p in (
             Path(__file__), ROOT / "scripts/sure_v4/synchronous_delays.py",
             ROOT / "scripts/sure_v4/allocation_probe.py", ROOT / "scripts/sure_v4/reference.py",
             ROOT / "scripts/sure_v4/probe_delay_order.py", ROOT / "scripts/julia_repro/comparison.py",
             ROOT / "scripts/julia_repro/results.py", ROOT / "scripts/vensim_comparison/core.py",
             ROOT / "benchmarks/julia-parametric/worker.jl", ROOT / "benchmarks/julia-repro/acceptance.json",
             ROOT / "benchmarks/julia-repro/allocation.jl", ROOT / "benchmarks/sure-v4/allocation.jl",
             ROOT / "benchmarks/sure-v4-alignment/replay_allocation.jl")}})
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("phase", choices=["prepare", "simulate", "analyze", "all"])
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--baseline", type=Path, default=ROOT / "dist/sure-v4/20261012-alignment")
    p.add_argument("--synchronous", type=Path, default=ROOT / "dist/sure-alignment/20261012-synchronous")
    p.add_argument("--probe", type=Path, default=ROOT / "dist/sure-alignment/20261012-native-ready")
    a = p.parse_args()
    d, archive, baseline, synchronous, probe = [v.resolve() for v in (a.run_dir, a.archive, a.baseline, a.synchronous, a.probe)]
    if a.phase in {"prepare", "all"}:
        prepare(d, archive, baseline, synchronous)
    if a.phase in {"simulate", "all"}:
        simulate(d, baseline)
    if a.phase in {"analyze", "all"}:
        report = analyze(d, archive, baseline, synchronous, probe)
        print({k: report[k] for k in ("base_reexport_exact", "delay", "native_input_allocation_replay", "native_equivalence_certified")})
