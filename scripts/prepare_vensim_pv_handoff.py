"""Package the corrected native source, complete inputs and numerical references.

Run after Python–Julia certification. No release is created or published.
"""
import argparse
from pathlib import Path
import pickle
import shutil
import sys
import zipfile

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sure_julia.common import ROOT, MODEL_REVISION, CALIBRATION, YEARS, digest, dump, read
from sure_julia.runtime import JuliaBackend
from sure_julia.validation import cases, compare


def prepare(validation, target):
    certificate = read(validation / "certificate.json")
    build = ROOT / "sure_julia/generated/build.json"
    if not certificate["pass"] or not certificate["complete_suite"] or certificate["build"] != digest(build):
        raise ValueError("Current complete Python–Julia certification required")
    for name, checksum in certificate["evidence"].items():
        if digest(validation / name) != checksum:
            raise ValueError("Validation evidence changed")
    target.mkdir(parents=True, exist_ok=False)
    scenarios = cases()
    dump(target / "scenarios.json", scenarios)
    with CALIBRATION.open("rb") as stream:
        calibrated = pickle.load(stream)
    def plain(value):
        if isinstance(value, dict):
            return {str(k): plain(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [plain(v) for v in value]
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, np.generic):
            return value.item()
        return value
    dump(target / "calibration.json", plain(calibrated))
    for source, name in [
        (ROOT / "Vensim/SURE_v6_pvbounded.mdl", "SURE_v6_pvbounded.mdl"),
        (ROOT / "Vensim/SURE.mdl", "SURE_v6_original.mdl"),
        (ROOT / "sure_julia/pv-budget.json", "source-audit.json"),
        (ROOT / "benchmarks/sure-production/PV_BUDGET_VENSIM.md", "README.md"),
        (ROOT / "benchmarks/sure-production/pv-budget-native.diff", "pv-budget-native.diff"),
        (ROOT / "benchmarks/sure-production/pv-budget-base-trace-20261014.json", "pv-budget-base-trace-20261014.json"),
        (ROOT / "sure_julia/generated/export.json", "export.json"),
        (ROOT / "data-release.json", "historical-data-inputs.json"),
        (build, "build.json"),
        (validation / "certificate.json", "python-julia-certificate.json"),
        (validation / "repeats.json", "state-isolation.json"),
    ]:
        shutil.copy2(source, target / name)
    # All cases carry full inputs and comparison reports; four initial native
    # regression cases also carry raw Float64 references with explicit axes.
    selected = ["base", "high", "regression_negative_stock", "sample_min_12"]
    engine = JuliaBackend(timeout=900)
    try:
        for name in selected:
            arrays = engine.run_arrays(scenarios[name])
            if name == "base":
                with np.load(validation / "base/python.npz") as reference:
                    comparison = compare({n: reference[n] for n in reference.files}, arrays, engine.export)
                if not comparison["pass"]:
                    raise ValueError("Native handoff base differs from the validated Python reference")
                dump(target / "base.reference-check.json", comparison)
            np.savez_compressed(target / f"{name}.julia.npz", **arrays)
            dump(target / f"{name}.physical.json", engine.last_physical)
    finally:
        engine.close()
    shutil.copy2(validation / "base/python.npz", target / "base.python.npz")
    for name in scenarios:
        folder = target / "comparison" / name
        folder.mkdir(parents=True)
        for filename in ("report.json", "warnings.json"):
            shutil.copy2(validation / name / filename, folder / filename)
    dump(target / "manifest.json", {
        "model_revision": MODEL_REVISION, "native_verified": False,
        "status": "awaiting_native_vensim_review_no_release_or_deploy",
        "years": YEARS, "time_step": 1, "saveper": "TIME STEP", "method": "Euler",
        "calibration_sha256": digest(CALIBRATION), "calibrated_components": len(calibrated),
        "fixed_controls": {"ICE ban year": 2050, "Deflussi minimi LPAc": 1, "Cambiamento climatico Hydro": 1},
        "scenario_count": len(scenarios), "parameters_per_scenario": 40,
        "raw_reference_cases": selected, "raw_reference_precision": "Float64",
        "handoff_generator_sha256": digest(__file__),
        "data_inputs": "Use the same native external files as SURE v6; these are not bundled",
        "files": {str(p.relative_to(target)): digest(p) for p in sorted(target.rglob("*")) if p.is_file()},
    })
    archive = target.with_suffix(".zip")
    if archive.exists():
        raise ValueError("Archive already exists")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as package:
        for path in sorted(target.rglob("*")):
            if path.is_file():
                package.write(path, str(path.relative_to(target)))
    print(f"{archive}: {digest(archive)}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("validation", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    prepare(args.validation, args.target)
