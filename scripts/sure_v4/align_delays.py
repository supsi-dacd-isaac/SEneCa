"""Reproducible pre-step delay experiment; leaves the certified v4 run intact."""
from pathlib import Path
import argparse
import shutil

from scripts.julia_repro.common import ROOT, RUNTIME, CONFIG, read, dump, digest, run_logged

ORIGINAL_SHA = "79b6f192545253b8ba654cac3acd9036c7368637dbdfeb9923b7589ad1939691"
OLD = """    updated = SenecaContext(u, t, false, 1224, parameters)
    updated.values[93] = reshape(copy(new_state[53709:53996]), 12, 24)
    updated.status[93] = 2
    _derivative__df_pipe_1_hourly_imported_electricity!(pending, updated)"""
NEW = "    _derivative__df_pipe_1_hourly_imported_electricity!(pending, c)"
PROBES = ["01_base", "09_hydro_on", "10_mixed"]


def migrate(source, destination):
    # These numeric offsets are specific to the frozen generated v4 artifact.
    if digest(source) != ORIGINAL_SHA:
        raise ValueError("Reaudit the generated state layout before migrating another model")
    text = source.read_text()
    if text.count(OLD) != 1:
        raise ValueError("Expected exactly one sequential nested-delay override")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x") as file:
        file.write(text.replace(OLD, NEW))
    dump(destination.parent / "migration.json", {
        "original_sha256": digest(source), "candidate_sha256": digest(destination),
        "removed_block": OLD, "policy": "All DELAY FIXED inputs read pre-step state. No parameter or allocation change."})


def prepare(original, directory):
    baseline = read(original / "validation.json")
    if not baseline["alignment_pass"]:
        raise ValueError("Requires a completed, passing v4 Python–Julia baseline")
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "source").symlink_to(original / "source", target_is_directory=True)
    shutil.copyfile(original / "manifest.json", directory / "manifest.json")
    migrate(original / "model/SURE_v4.jl", directory / "model/SURE_v4_synchronous.jl")
    for name in ("export.json", "SURE_pysd_v4_data.json"):
        shutil.copyfile(original / "model" / name, directory / "model" / name)
    scenarios = read(directory / "manifest.json")["scenarios"]
    dump(directory / "jobs.json", [{"id": k, "parameters": v} for k, v in scenarios.items()]
         + [{"id": "01_base_repeat", "parameters": scenarios["01_base"]}])
    dump(directory / "baseline.json", {"path": str(original), "validation_sha256": digest(original / "validation.json"),
         "evidence_sha256": digest(original / "evidence.json"), "manifest_sha256": digest(original / "manifest.json")})


def validate(original, directory):
    from scripts.julia_repro.comparison import compare
    from scripts.julia_repro.energy import check_snapshot
    from scripts.sure_v4.validate import exact_replay
    from scripts.vensim_comparison.core import convert_raw, comparison
    manifest, export = read(directory / "manifest.json"), read(directory / "model/export.json")
    for name, expected in manifest["sources"].items():
        if digest(directory / "source" / name) != expected:
            raise ValueError(f"Source drift: {name}")
    migration = read(directory / "model/migration.json")
    if digest(directory / "model/SURE_v4_synchronous.jl") != migration["candidate_sha256"]:
        raise ValueError("Candidate model drift")
    report = {"cases": {}, "order_probes": {}, "app_probes": {}, "native_equivalence_certified": False}
    for case in manifest["scenarios"]:
        py = directory / "reference/staged-before" / case
        jl = directory / "candidate" / case
        convert_raw(directory / "raw" / case, jl, export, manifest)
        report["cases"][case] = {
            "python_julia": compare(py, jl),
            "python_energy": check_snapshot(py), "julia_energy": check_snapshot(jl),
            "native": comparison(original / "native/reconstructed" / case, py)}
        if case in PROBES:
            report["order_probes"][case] = exact_replay(py, directory / "reference/staged-after" / case)
            report["app_probes"][case] = compare(directory / "reference/app" / case, py,
                                                 outputs=manifest["outputs"], exact=True)
        print(case, "Python–Julia", report["cases"][case]["python_julia"]["pass"], flush=True)
    convert_raw(directory / "raw/01_base_repeat", directory / "candidate/01_base_repeat", export, manifest)
    report["python_repeat"] = exact_replay(directory / "reference/staged-before/01_base",
                                           directory / "reference/staged-before/01_base_repeat_10")
    report["julia_repeat"] = exact_replay(directory / "candidate/01_base", directory / "candidate/01_base_repeat")
    jobs = read(directory / "jobs.json")
    load = read(directory / "raw/load.json")
    timings = [read(directory / "raw" / job["id"] / "timing.json") for job in jobs]
    report["compiled_module_reused"] = (load["loads"] == 1
        and all(t["module_id"] == load["module_id"] for t in timings)
        and len({t["parameter_type"] for t in timings}) == 1
        and all(t["compilation_seconds"] == 0 for t in timings[1:])
        and all(t["parameters"] == j["parameters"] and t["initial_state_preserved"] for t, j in zip(timings, jobs)))
    # The baseline translation's warning review remains required. New Python
    # warnings must be among its explicitly classified, nonblocking messages.
    reviewed = read(original / "warnings-reviewed.json")
    allowed = {(w["category"], w["message"]) for w in reviewed["python"] if w["classification"] != "blocking"}
    report["warnings"] = {mode: [w for w in read(directory / "reference" / mode / "warnings.json")
                                if (w["category"], w["message"]) not in allowed]
                          for mode in ("staged-before", "staged-after", "app")}
    report["python_julia_pass"] = all(r["python_julia"]["pass"] for r in report["cases"].values())
    report["experimental_validation_pass"] = (report["python_julia_pass"]
        and all(r[k]["pass"] for r in report["cases"].values() for k in ("python_energy", "julia_energy"))
        and all(r["pass"] for group in ("order_probes", "app_probes") for r in report[group].values())
        and report["python_repeat"]["pass"] and report["julia_repeat"]["pass"]
        and report["compiled_module_reused"] and not any(report["warnings"].values()))
    report["native_pass"] = all(r["native"]["pass"] for r in report["cases"].values())
    implementation = {str(p.relative_to(ROOT)): digest(p) for p in (
        ROOT / "scripts/sure_v4/align_delays.py", ROOT / "scripts/sure_v4/probe_delay_order.py",
        ROOT / "scripts/sure_v4/synchronous_delays.py", ROOT / "scripts/sure_v4/reference.py",
        ROOT / "benchmarks/julia-parametric/worker.jl")}
    artifacts = {str(p.relative_to(directory)): digest(p) for p in sorted(directory.rglob("*"))
                 if p.is_file() and p.suffix in {".json", ".npz", ".bin", ".jl"}
                 and p.name not in {"validation.json", "evidence.json", "summary.json"}}
    dump(directory / "evidence.json", {"implementation": implementation, "artifacts": artifacts})
    report["evidence_sha256"] = digest(directory / "evidence.json")
    dump(directory / "validation.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["prepare", "reference", "order", "app", "julia", "validate", "all"])
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    original, directory = args.baseline.resolve(), args.run_dir.resolve()
    phases = ["prepare", "reference", "order", "app", "julia", "validate"] if args.phase == "all" else [args.phase]
    for phase in phases:
        if phase == "prepare":
            prepare(original, directory)
        elif phase in {"reference", "order", "app"}:
            mode = {"reference": "staged-before", "order": "staged-after", "app": "staged-app"}[phase]
            cases = list(read(directory / "manifest.json")["scenarios"]) + ["01_base"] if phase == "reference" else PROBES
            run_logged([RUNTIME / "python-reference/bin/python", "-B", "-u", "-m", "scripts.sure_v4.probe_delay_order",
                        original, directory, mode, *cases], directory / f"{phase}.log")
        elif phase == "julia":
            run_logged([RUNTIME / "julia-1.10.12/bin/julia", "--startup-file=no", f"--project={CONFIG}",
                        ROOT / "benchmarks/julia-parametric/worker.jl", directory / "model/SURE_v4_synchronous.jl",
                        directory / "model/export.json", directory / "jobs.json", directory / "raw"], directory / "julia.log")
        elif phase == "validate":
            report = validate(original, directory)
            print({k: report[k] for k in ("experimental_validation_pass", "native_pass", "native_equivalence_certified")})


if __name__ == "__main__":
    main()
