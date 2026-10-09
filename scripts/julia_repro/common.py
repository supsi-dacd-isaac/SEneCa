from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "benchmarks/julia-repro"
RUNTIME = ROOT / "dist/julia-repro/runtime"
PINS = json.loads((CONFIG / "pins.json").read_text())
YEARS = list(range(PINS["initial_time"], PINS["final_time"] + 1))


def dump(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def environment():
    return {**os.environ, "SURE_VARIANT": "v3", "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0", "JULIA_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
            "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1",
            "JULIA_DEPOT_PATH": str(RUNTIME / "julia-depot")}


def run_logged(command, log, *, cwd=ROOT):
    """Keep diagnostics even on failure; never hide a failed subprocess."""
    log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w") as out:
        result = subprocess.run([str(x) for x in command], cwd=cwd, env=environment(),
                                stdout=out, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"Exit {result.returncode}: {' '.join(map(str, command))}; log: {log}")


def source_hashes():
    files = [ROOT / "Vensim/SURE_pysd_v3.py", ROOT / "Vensim/SURE_pysd_v3.mdl",
             ROOT / "constants_ref_v3.pkl", ROOT / "sure_pysd.py", ROOT / "sure_paths.py",
             ROOT / "pysd_explore_config.py", ROOT / "data-release.json"]
    files += sorted((ROOT / "Vensim").glob("*_pysd_v3.csv"))
    files += sorted((ROOT / "pv_batteries").glob("*_config.py"))
    return {str(p.relative_to(ROOT)): digest(p) for p in files}


def experiment_hashes():
    files = sorted((ROOT / "scripts/julia_repro").glob("*.py"))
    files += [ROOT / "scripts/benchmark_julia.py", ROOT / "scripts/setup_julia_repro.py", ROOT / "fix_selfref_sure.py"]
    files += sorted((ROOT / "tests").glob("test_julia*.py"))
    files += sorted(p for p in CONFIG.rglob("*") if p.is_file() and p.suffix != ".md")
    return {str(p.relative_to(ROOT)): digest(p) for p in files}


def check_sources(manifest):
    if manifest["sources"] != source_hashes():
        raise RuntimeError("Model/data/config changed since inventory; create a new run.")
    if manifest["pins"] != PINS:
        raise RuntimeError("Runtime pins changed since inventory; create a new run.")
    scenario_hash = hashlib.sha256(json.dumps(manifest["scenarios"], sort_keys=True,
                                              separators=(",", ":")).encode()).hexdigest()
    if manifest.get("scenarios_sha256") != scenario_hash:
        raise RuntimeError("Scenario manifest checksum mismatch")


def evidence_hashes(directory):
    """Freeze validation inputs and results; benchmark artefacts are independent."""
    files = [directory / "manifest.json", directory / "fixtures.json"]
    for folder in ("reference", "candidate", "checks", "julia", "reduction-samples"):
        for path in (directory / folder).rglob("*"):
            if path.is_file() and not path.name.startswith("bench_"):
                files.append(path)
    for path in (directory / "julia").glob("*/translation.json"):
        translation = read(path)
        for policy_name in ("delay_update_policy", "reduction_policy"):
            policy = translation.get(policy_name, {})
            files.extend(directory / name for name in policy.get("evidence", {}))
    return {str(p.relative_to(directory)): digest(p) for p in sorted(set(files))}
