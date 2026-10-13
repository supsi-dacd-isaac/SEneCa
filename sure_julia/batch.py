"""Resumable, atomic regeneration of all application data using Julia workers."""
import argparse
import concurrent.futures
import hashlib
import itertools
import multiprocessing
import os
from pathlib import Path
import shutil
import time

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .catalog import parameters
from .common import ROOT, YEARS, digest, dump, identity, read
from .runtime import JuliaBackend, frame_from_arrays


def configs():
    from pv_batteries import pv_batteries_config as pv, risanamento_config as ris, veicoli_config as vei, elettricita_config as elec, exploratory_config as exp
    return dict(pv_batteries=pv, risanamento=ris, veicoli=vei, elettricita=elec, exploratory=exp)


def jobs():
    result = {}
    def add(params, destination, names):
        params = parameters(params)
        key = identity(params)
        job = result.setdefault(key, {"id": key, "parameters": params, "destinations": [], "outputs": []})
        job["destinations"].append(destination)
        job["outputs"] = list(dict.fromkeys(job["outputs"] + names))
    for section, cfg in configs().items():
        if section == "exploratory":
            samples = pd.read_parquet(cfg.SAMPLES_PATH)
            if len(samples) != 50:
                raise ValueError("Expected the original fifty uncertainty samples")
            for pid, policy in enumerate(cfg.all_policy_combos()):
                for sid, sample in enumerate(samples[cfg.UNCERTAINTY_ORDER].to_dict("records")):
                    add({**policy, **sample, cfg.EXPLORATORY_SWITCH: 1},
                        {"section": section, "policy_id": pid, "sample_id": sid, "inputs": policy},
                        list(dict.fromkeys(list(cfg.GMD_VARS) + list(cfg.SCALAR_OUTPUTS.values()) + [cfg.CANTONAL_FUNDS_VAR])))
        else:
            for values in itertools.product(*(cfg.INPUT_GRID[n] for n in cfg.INPUT_ORDER)):
                inputs = dict(zip(cfg.INPUT_ORDER, map(float, values)))
                add(inputs, {"section": section, "inputs": inputs},
                    list(dict.fromkeys(list(cfg.OUTPUT_BASES) + list(getattr(cfg, "GMD_VARS", [])))))
    if sum(len(j["destinations"]) for j in result.values()) != 8179:
        raise ValueError("Scenario grid changed; reapprove coverage")
    return list(result.values())


def gmd(arrays, specs, export):
    # Fail before the legacy GMD helper can discard nonfinite or negative weights.
    from pv_batteries.gmd import compute_gmd_from_spec
    values = {}
    for name in {s[k] for s in specs.values() for k in ("weight", "value")}:
        spec = export[name]
        labels = itertools.product(*(spec["coords"][d] for d in spec["dims"]))
        numbers = arrays[name][-1].ravel(order="C")
        if not np.isfinite(numbers).all():
            raise ValueError(f"Nonfinite GMD input: {name}")
        values[name] = {",".join(label): float(v) for label, v in zip(labels, numbers)}
    for spec in specs.values():
        if set(values[spec["weight"]]) != set(values[spec["value"]]):
            raise ValueError("GMD coordinates differ")
        if any(v < 0 for v in values[spec["weight"]].values()):
            raise ValueError("Negative GMD weights")
    result = compute_gmd_from_spec(values, specs)
    if not all(np.isfinite(v) for v in result.values()):
        raise ValueError("Invalid GMD")
    return result


def atomic_parquet(frame, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".tmp")
    frame.to_parquet(temp, index=False)
    temp.replace(target)


def hourly(arrays, names, export):
    blocks = []
    for name in names:
        spec = export[name]
        dims = spec["dims"]
        if dims not in (["Month", "Hour"], ["Month", "Hour", "Supplier"]):
            raise ValueError(f"Unsupported hourly axes: {name}/{dims}")
        coords = pd.MultiIndex.from_product([YEARS] + [spec["coords"][d] for d in dims], names=["year"]+dims).to_frame(index=False)
        coords.rename(columns={"Month": "month", "Hour": "hour", "Supplier": "supplier"}, inplace=True)
        if "supplier" not in coords:
            coords["supplier"] = ""
        coords["variable"] = name
        coords["value"] = arrays[name].ravel(order="C")
        blocks.append(coords[["variable", "month", "hour", "supplier", "year", "value"]])
    return pd.concat(blocks, ignore_index=True)


def initialize(directory, affinity=None):
    global ENGINE, TARGET, EXPORT, CONFIGS
    if affinity is not None:
        os.sched_setaffinity(0, {affinity.get()})
    TARGET = Path(directory)
    ENGINE = JuliaBackend(timeout=900)
    EXPORT = {s["name"]: s for s in ENGINE.export}
    CONFIGS = configs()
    # Compile all observable paths once, including outputs needed by other sections.
    ENGINE.run_arrays()


def execute(job):
    started = time.perf_counter()
    arrays = ENGINE.run_arrays(job["parameters"], job["outputs"])
    if ENGINE.last_timing["compilation_seconds"] != 0:
        raise RuntimeError("Unexpected compilation after worker warm-up")
    value_hash = hashlib.sha256()
    for name in sorted(arrays):
        value_hash.update(name.encode())
        value_hash.update(arrays[name].astype("<f8", copy=False).tobytes(order="C"))
    paths = []
    for dest in job["destinations"]:
        section = dest["section"]
        cfg = CONFIGS[section]
        inputs = dest["inputs"]
        target = TARGET / "parts" / section
        if section == "exploratory":
            kpis = gmd(arrays, cfg.GMD_SPEC, EXPORT)
            kpis.update({k: float(arrays[n][-1].sum()) for k, n in cfg.SCALAR_OUTPUTS.items()})
            kpis["cantonal_spend"] = float(arrays[cfg.CANTONAL_FUNDS_VAR][YEARS.index(cfg.CANTONAL_SPEND_START):].sum())
            frame = pd.DataFrame([{"policy_id": dest["policy_id"], "sample_id": dest["sample_id"], **inputs, **kpis, "completed": 1.0}])
            path = target / f"{job['id']}.parquet"
        elif section == "elettricita":
            frame = hourly(arrays, cfg.OUTPUT_BASES, EXPORT)
            for name, value in inputs.items():
                frame[name] = value
            path = target / f"{job['id']}.parquet"
        else:
            frame = frame_from_arrays({n: arrays[n] for n in cfg.OUTPUT_BASES}, [EXPORT[n] for n in cfg.OUTPUT_BASES]).reset_index()
            for name, value in inputs.items():
                frame[name] = value
            path = target / f"{job['id']}.parquet"
            if getattr(cfg, "GMD_VARS", []):
                gmd_path = TARGET / "parts" / f"{section}_gmd" / f"{job['id']}.parquet"
                atomic_parquet(pd.DataFrame([{**inputs, **gmd(arrays, cfg.GMD_SPEC, EXPORT), "year": 2050}]), gmd_path)
                paths.append(gmd_path)
        if not np.isfinite(frame.select_dtypes(include="number").to_numpy()).all():
            raise ValueError("Nonfinite release data")
        atomic_parquet(frame, path)
        paths.append(path)
    report = {"parameters": job["parameters"], "destinations": job["destinations"], "value_sha256": value_hash.hexdigest(),
              "timing": ENGINE.last_timing, "elapsed_seconds": time.perf_counter()-started,
              "files": {str(p.relative_to(TARGET)): digest(p) for p in paths}}
    dump(TARGET / "completed" / f"{job['id']}.json", report)
    return job["id"], report["elapsed_seconds"]


def consolidate(directory, planned):
    directory = Path(directory)
    destinations = {"pv_batteries": "pv_batteries_scenarios.parquet", "pv_batteries_gmd": "pv_batteries_gmd.parquet",
                    "risanamento": "risanamento_scenarios.parquet", "risanamento_gmd": "risanamento_gmd.parquet",
                    "veicoli": "veicoli_scenarios.parquet", "elettricita": "elettricita_hourly.parquet", "exploratory": "exploratory_kpis.parquet"}
    release = directory / "release/precomputed"
    release.mkdir(parents=True, exist_ok=True)
    provenance = []
    for job in planned:
        report = read(directory / "completed" / f"{job['id']}.json")
        if report["parameters"] != job["parameters"]:
            raise ValueError("Completed job parameters differ")
        for name, expected in report["files"].items():
            if digest(directory / name) != expected:
                raise ValueError("Completed output checksum differs")
        provenance.append({"scenario_id": job["id"], "parameters_json": __import__("json").dumps(job["parameters"], sort_keys=True),
                           "destinations_json": __import__("json").dumps(job["destinations"], sort_keys=True),
                           "output_sha256": report["value_sha256"], "seconds": report["elapsed_seconds"], "backend": "julia"})
    for section, filename in destinations.items():
        files = sorted((directory / "parts" / section).glob("*.parquet"))
        base_section = section.removesuffix("_gmd")
        expected = sum(d["section"] == base_section for j in planned for d in j["destinations"])
        if len(files) != expected:
            raise ValueError(f"Incomplete section {section}: {len(files)}/{expected}")
        temp = release / (filename + ".tmp")
        with pq.ParquetWriter(temp, pq.read_schema(files[0])) as writer:
            for path in files:
                table = pq.read_table(path)
                writer.write_table(table)
        temp.replace(release / filename)
    electricity = [d["inputs"] for j in planned for d in j["destinations"] if d["section"] == "elettricita"]
    atomic_parquet(pd.DataFrame(electricity), release / "elettricita_combo_index.parquet")
    (release / "exploratory").mkdir(exist_ok=True)
    shutil.copy2(ROOT / "precomputed/exploratory/uncertainty_samples.parquet", release / "exploratory/uncertainty_samples.parquet")
    atomic_parquet(pd.DataFrame(provenance), directory / "release/provenance/scenarios.parquet")
    dump(directory / "release/provenance/build.json", {
        "backend": "julia", "model": read(ROOT / "sure_julia/generated/build.json"),
        "generation_manifest_sha256": digest(directory / "manifest.json"),
        "scenarios_sha256": digest(directory / "release/provenance/scenarios.parquet"),
        "numerical_tolerance": {"atol_scale": 1e-10, "rtol": 1e-8},
        "reference": "SURE v4; synchronous DELAY FIXED; exact allocation",
        "native_vensim_equivalent": False,
        "legacy_vensim_files": "Historical input/reference archives retained from data-v1.0.0; not Julia outputs"})


def compare_pilots(serial, parallel, output):
    serial, parallel = Path(serial), Path(parallel)
    left, right = read(serial / "manifest.json"), read(parallel / "manifest.json")
    if left != right or len(left["jobs"]) != 100:
        raise ValueError("Pilot configurations differ")
    rows = []
    for job in left["jobs"]:
        a = read(serial / "completed" / f"{job['id']}.json")
        b = read(parallel / "completed" / f"{job['id']}.json")
        rows.append({"scenario_id": job["id"], "pass": a["value_sha256"] == b["value_sha256"],
                     "serial_seconds": a["elapsed_seconds"], "parallel_seconds": b["elapsed_seconds"]})
    summary = {"pass": all(r["pass"] for r in rows), "rows": rows,
               "serial": read(serial / "summary.json"), "parallel": read(parallel / "summary.json")}
    dump(output, summary)
    if not summary["pass"]:
        raise ValueError("Parallel pilot changed results")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--workers", type=int, default=32)
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--consolidate-only", action="store_true")
    parser.add_argument("--validation", type=Path, required=True)
    args = parser.parse_args()
    certificate = read(args.validation / "summary.json")
    if not certificate["pass"] or not certificate.get("complete_suite"):
        raise ValueError("Validation must pass before regeneration")
    if not read(args.validation / "repeats.json")["pass"]:
        raise ValueError("State isolation checks must pass before regeneration")
    if read(args.validation / "manifest.json")["build"] != digest(ROOT / "sure_julia/generated/build.json"):
        raise ValueError("Validation belongs to another build")
    planned = jobs()
    if args.pilot:
        planned = [planned[i] for i in np.linspace(0, len(planned)-1, 100, dtype=int)]
    stamp = {"build": digest(ROOT / "sure_julia/generated/build.json"), "jobs": planned,
             "sample_sha256": digest(ROOT / "precomputed/exploratory/uncertainty_samples.parquet"),
             "code": {p.name: digest(p) for p in Path(__file__).parent.glob("*.py")}}
    args.directory.mkdir(parents=True, exist_ok=True)
    manifest = args.directory / "manifest.json"
    if manifest.exists() and read(manifest) != stamp:
        raise ValueError("Cannot resume a different configuration")
    dump(manifest, stamp)
    pending = []
    for job in planned:
        done = args.directory / "completed" / f"{job['id']}.json"
        if done.exists():
            report = read(done)
            if report["parameters"] != job["parameters"] or any(digest(args.directory / p) != h for p, h in report["files"].items()):
                raise ValueError("Invalid checkpoint")
        else:
            pending.append(job)
    started = time.perf_counter()
    if not args.consolidate_only and pending:
        context = multiprocessing.get_context("spawn")
        affinity = context.Queue()
        cpus = sorted(os.sched_getaffinity(0))
        if not 1 <= args.workers <= len(cpus):
            raise ValueError("Workers exceed allocated cores")
        for cpu in cpus[:args.workers]:
            affinity.put(cpu)
        with concurrent.futures.ProcessPoolExecutor(args.workers, mp_context=context, initializer=initialize,
                                                    initargs=(str(args.directory), affinity)) as pool:
            futures = [pool.submit(execute, job) for job in pending]
            for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
                key, seconds = future.result()
                dump(args.directory / "progress.json", {"done": len(planned)-len(pending)+i, "total": len(planned), "seconds": time.perf_counter()-started})
                print(i, "/", len(pending), key[:12], round(seconds, 2), flush=True)
    if not args.pilot:
        consolidate(args.directory, planned)
    dump(args.directory / "summary.json", {"complete": True, "scenarios": len(planned), "seconds": time.perf_counter()-started, "workers": args.workers})


if __name__ == "__main__":
    main()
