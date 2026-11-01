"""Regenerate the three result-section stores with the pinned Python oracle.

This is the local (Windows/macOS) counterpart of ``sure_julia.batch`` for the
"Simulazioni SEneCa" pages only: PV e batterie, Riscaldamento e risanamento
and Veicoli. It uses the same Parquet layout, GMD definition and physical
checks, but runs ``PythonBackend`` processes instead of Julia workers.
Destinations whose inputs differ only in a lever that the model ignores
(``INACTIVE_UNLESS`` in the section config) share one simulation.
A Julia release still requires the gated procedure in docs/julia-production.md.

    python -m sure_julia.python_batch runs/ems1-sections --workers 8
    python -m sure_julia.python_batch runs/ems1-sections --install
"""
import argparse
import concurrent.futures
import hashlib
import itertools
import json
import multiprocessing
from pathlib import Path
import shutil
import time
import traceback

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from .batch import atomic_parquet, configs, gmd
from .catalog import parameters
from .common import ROOT, MODEL_REVISION, MODEL_VARIANT, digest, dump, identity, model_sources, read
from .runtime import frame_from_arrays

SECTIONS = ("pv_batteries", "risanamento", "veicoli")
DESTINATIONS = {"pv_batteries": "pv_batteries_scenarios.parquet", "pv_batteries_gmd": "pv_batteries_gmd.parquet",
                "risanamento": "risanamento_scenarios.parquet", "risanamento_gmd": "risanamento_gmd.parquet",
                "veicoli": "veicoli_scenarios.parquet"}


def simulated_inputs(cfg, inputs):
    """Inputs actually sent to the model: ignored levers go back to Base."""
    result = dict(inputs)
    for name, switch in getattr(cfg, "INACTIVE_UNLESS", {}).items():
        if result.get(switch) == 0:
            result[name] = cfg.BASE_SCENARIO[name]
    return result


def destination_id(job_id, destination):
    return f"{job_id[:16]}-{identity(destination)[:12]}"


def jobs():
    result = {}
    for section, cfg in configs().items():
        if section not in SECTIONS:
            continue
        names = list(dict.fromkeys(list(cfg.OUTPUT_BASES) + list(getattr(cfg, "GMD_VARS", []))))
        for values in itertools.product(*(cfg.INPUT_GRID[n] for n in cfg.INPUT_ORDER)):
            inputs = dict(zip(cfg.INPUT_ORDER, map(float, values)))
            params = parameters(simulated_inputs(cfg, inputs))
            key = identity(params)
            job = result.setdefault(key, {"id": key, "parameters": params, "destinations": [], "outputs": []})
            job["destinations"].append({"section": section, "inputs": inputs})
            job["outputs"] = list(dict.fromkeys(job["outputs"] + names))
    if sum(len(j["destinations"]) for j in result.values()) != 1197:
        raise ValueError("Result-section grid changed; reapprove coverage")
    return list(result.values())


def all_outputs():
    cfgs = configs()
    return list(dict.fromkeys(n for s in SECTIONS for n in
                              list(cfgs[s].OUTPUT_BASES) + list(getattr(cfgs[s], "GMD_VARS", []))))


def initialize(directory):
    global ENGINE, TARGET, EXPORT, CONFIGS
    from .python_backend import PythonBackend
    TARGET = Path(directory)
    ENGINE = PythonBackend(outputs=all_outputs())
    EXPORT = {n: {"name": n, "dims": ENGINE.variables[n].get("subscripts", []),
                  "coords": {d: ENGINE.dimensions[d] for d in ENGINE.variables[n].get("subscripts", [])}}
              for n in ENGINE.outputs}
    CONFIGS = configs()


def _execute(job):
    started = time.perf_counter()
    arrays = ENGINE.run_arrays(job["parameters"], job["outputs"])
    value_hash = hashlib.sha256()
    for name in sorted(arrays):
        value_hash.update(name.encode())
        value_hash.update(arrays[name].astype("<f8", copy=False).tobytes(order="C"))
    paths, gmd_audit = [], []
    for dest in job["destinations"]:
        section, inputs = dest["section"], dest["inputs"]
        cfg = CONFIGS[section]
        frame = frame_from_arrays({n: arrays[n] for n in cfg.OUTPUT_BASES},
                                  [EXPORT[n] for n in cfg.OUTPUT_BASES]).reset_index()
        for name, value in inputs.items():
            frame[name] = value
        part = destination_id(job["id"], dest)
        if getattr(cfg, "GMD_VARS", []):
            gmd_path = TARGET / "parts" / f"{section}_gmd" / f"{part}.parquet"
            atomic_parquet(pd.DataFrame([{**inputs, **gmd(arrays, cfg.GMD_SPEC, EXPORT, gmd_audit), "year": 2050}]), gmd_path)
            paths.append(gmd_path)
        if not np.isfinite(frame.select_dtypes(include="number").to_numpy()).all():
            raise ValueError("Nonfinite release data")
        path = TARGET / "parts" / section / f"{part}.parquet"
        atomic_parquet(frame, path)
        paths.append(path)
    report = {"status": "complete", "parameters": job["parameters"], "destinations": job["destinations"],
              "value_sha256": value_hash.hexdigest(), "timing": ENGINE.last_timing, "physical": ENGINE.last_physical,
              "elapsed_seconds": time.perf_counter()-started, "gmd_weight_audit": gmd_audit,
              "warnings": ENGINE.warnings, "files": {str(p.relative_to(TARGET)): digest(p) for p in paths}}
    dump(TARGET / "completed" / f"{job['id']}.json", report)
    (TARGET / "failed" / f"{job['id']}.json").unlink(missing_ok=True)
    return job["id"], report["elapsed_seconds"]


def execute(job):
    """Record a failed scenario and keep the worker; never return partial data.

    Exceptions such as PhysicalInvariantError carry arrays and do not survive
    pickling back to the parent, which would break the whole pool.
    """
    try:
        key, seconds = _execute(job)
        return key, seconds, None
    except Exception as error:
        dump(TARGET / "failed" / f"{job['id']}.json", {**job, "status": "failed", "error": traceback.format_exc()})
        return job["id"], None, f"{type(error).__name__}: {str(error)[:200]}"


def consolidate(directory, planned):
    release = directory / "release/precomputed"
    release.mkdir(parents=True, exist_ok=True)
    provenance = []
    for job in planned:
        report = read(directory / "completed" / f"{job['id']}.json")
        if report["parameters"] != job["parameters"] or not report["physical"]["pass"]:
            raise ValueError("Completed job differs or failed physical checks")
        for name, expected in report["files"].items():
            if digest(directory / name) != expected:
                raise ValueError("Completed output checksum differs")
        provenance.append({"scenario_id": job["id"], "parameters_json": json.dumps(job["parameters"], sort_keys=True),
                           "destinations_json": json.dumps(job["destinations"], sort_keys=True),
                           "gmd_weight_audit_json": json.dumps(report["gmd_weight_audit"], sort_keys=True),
                           "physical_checks_json": json.dumps(report["physical"], sort_keys=True),
                           "output_sha256": report["value_sha256"], "seconds": report["elapsed_seconds"], "backend": "python"})
    for section, filename in DESTINATIONS.items():
        files = sorted((directory / "parts" / section).glob("*.parquet"))
        expected = sum(d["section"] == section.removesuffix("_gmd") for j in planned for d in j["destinations"])
        if len(files) != expected:
            raise ValueError(f"Incomplete section {section}: {len(files)}/{expected}")
        temp = release / (filename + ".tmp")
        with pq.ParquetWriter(temp, pq.read_schema(files[0])) as writer:
            for path in files:
                writer.write_table(pq.read_table(path))
        temp.replace(release / filename)
    atomic_parquet(pd.DataFrame(provenance), directory / "release/provenance/sections.parquet")
    import pysd
    dump(directory / "release/provenance/sections.json", {
        "backend": "python", "pysd_version": pysd.__version__, "model_variant": MODEL_VARIANT,
        "model_revision": MODEL_REVISION, "sources": model_sources(),
        "generation_manifest_sha256": digest(directory / "manifest.json"),
        "scenarios_sha256": digest(directory / "release/provenance/sections.parquet"),
        "sections": list(SECTIONS), "unused": ["elettricita_hourly.parquet", "exploratory_kpis.parquet"],
        "julia_validation": "pending", "native_vensim_equivalent": False})


def install(directory):
    """Copy the consolidated section stores over the installed dataset."""
    source = directory / "release/precomputed"
    for filename in DESTINATIONS.values():
        shutil.copy2(source / filename, ROOT / "precomputed" / filename)
    shutil.copy2(directory / "release/provenance/sections.json", ROOT / "provenance/sections.json")
    print(f"Installed {len(DESTINATIONS)} section stores from {source}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--workers", type=int, default=max(1, multiprocessing.cpu_count() - 2))
    parser.add_argument("--pilot", type=int, default=0, help="Run only N evenly spaced scenarios")
    parser.add_argument("--install", action="store_true", help="Install a consolidated run into precomputed/")
    args = parser.parse_args()
    if args.install:
        return install(args.directory)
    planned = jobs()
    if args.pilot:
        planned = [planned[i] for i in np.linspace(0, len(planned)-1, args.pilot, dtype=int)]
    stamp = {"backend": "python", "sources": model_sources(), "jobs": planned,
             "code": {str(p.relative_to(ROOT)): digest(p) for p in
                      [*Path(__file__).parent.glob("*.py"), *(ROOT / "pv_batteries").glob("*config.py"),
                       ROOT / "pv_batteries/gmd.py", ROOT / "pysd_explore_config.py", ROOT / "sure_pysd.py"]}}
    args.directory.mkdir(parents=True, exist_ok=True)
    manifest = args.directory / "manifest.json"
    if manifest.exists() and read(manifest) != stamp:
        previous = read(manifest)
        driver = str(Path(__file__).relative_to(ROOT))
        same = {k: v for k, v in previous.items() if k != "driver_revisions"}
        same["code"] = {**same["code"], driver: stamp["code"][driver]}
        if same != stamp:
            raise ValueError("Cannot resume a different configuration")
        # Only this scheduling driver changed: completed outputs stay valid.
        stamp["driver_revisions"] = previous.get("driver_revisions", []) + [previous["code"][driver]]
    dump(manifest, stamp)
    pending = []
    for job in planned:
        done = args.directory / "completed" / f"{job['id']}.json"
        if not done.exists():
            pending.append(job)
            continue
        report = read(done)
        if report["parameters"] != job["parameters"] or any(digest(args.directory / p) != h for p, h in report["files"].items()):
            raise ValueError("Invalid checkpoint")
    started = time.perf_counter()
    print(f"{len(pending)}/{len(planned)} scenarios pending, {args.workers} workers", flush=True)
    failed = []
    if pending:
        context = multiprocessing.get_context("spawn")
        with concurrent.futures.ProcessPoolExecutor(args.workers, mp_context=context, initializer=initialize,
                                                    initargs=(str(args.directory),)) as pool:
            futures = [pool.submit(execute, job) for job in pending]
            try:
                for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
                    key, seconds, error = future.result()
                    if error:
                        failed.append(key)
                    elapsed = time.perf_counter()-started
                    dump(args.directory / "progress.json", {"done": len(planned)-len(pending)+i, "total": len(planned),
                                                            "failed": len(failed), "seconds": elapsed,
                                                            "eta_seconds": elapsed/i*(len(pending)-i)})
                    print(i, "/", len(pending), key[:12], error or round(seconds, 1), flush=True)
            except Exception:
                pool.shutdown(wait=True, cancel_futures=True)
                raise
    if failed:
        dump(args.directory / "summary.json", {"complete": False, "scenarios": len(planned), "failed": failed,
                                                "seconds": time.perf_counter()-started, "workers": args.workers})
        raise SystemExit(f"{len(failed)} scenarios failed; see {args.directory / 'failed'}. Nothing consolidated.")
    if not args.pilot:
        consolidate(args.directory, planned)
    dump(args.directory / "summary.json", {"complete": True, "scenarios": len(planned),
                                            "seconds": time.perf_counter()-started, "workers": args.workers})


if __name__ == "__main__":
    main()
