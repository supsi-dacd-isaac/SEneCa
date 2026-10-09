#!/usr/bin/env python3
"""Install only the isolated, pinned runtimes used by benchmark_julia.py."""
from __future__ import annotations
from pathlib import Path
import platform
import subprocess
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.julia_repro.common import ROOT, CONFIG, RUNTIME, PINS, digest, environment, run_logged


def main():
    if (platform.system(), platform.machine()) != ("Darwin", "arm64"):
        raise SystemExit("This pinned local experiment targets macOS arm64; do not silently select another Julia build.")
    if platform.python_version() != PINS["python"]:
        raise SystemExit(f"Use the existing Python {PINS['python']} interpreter to reproduce the reference.")
    RUNTIME.mkdir(parents=True, exist_ok=True)
    upstream = RUNTIME / "pysd"
    if not upstream.exists():
        subprocess.run(["git", "clone", "https://github.com/SDXorg/pysd.git", upstream], check=True)
        subprocess.run(["git", "checkout", PINS["pysd_julia_commit"]], cwd=upstream, check=True)
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=upstream, text=True).strip()
    if actual != PINS["pysd_julia_commit"]:
        raise RuntimeError("Existing experiment checkout has another revision")
    subprocess.run(["git", "-c", "submodule.pysd/builders/julia/PySD.jl.url=https://github.com/rogersamso/PySD.jl.git",
                    "submodule", "update", "--init", "pysd/builders/julia/PySD.jl"], cwd=upstream, check=True)
    companion = upstream / "pysd/builders/julia/PySD.jl"
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=companion, text=True).strip() != PINS["pysd_jl_commit"]:
        raise RuntimeError("Unexpected PySD.jl revision")
    lock = CONFIG / "python-reference.lock"
    for name in ("python-reference", "python-julia"):
        venv = RUNTIME / name
        python = venv / "bin/python"
        if not python.exists():
            subprocess.run([ROOT / ".venv/bin/python", "-m", "venv", venv], check=True)
        marker = venv / ".repro-lock"
        fingerprint = digest(lock) + (PINS["pysd_julia_commit"] if name == "python-julia" else "")
        if not marker.exists() or marker.read_text() != fingerprint:
            run_logged([python, "-m", "pip", "install", "-r", lock], RUNTIME / f"{name}-install.log")
            if name == "python-julia":
                run_logged([python, "-m", "pip", "install", "--no-deps", "-e", upstream], RUNTIME / "python-julia-editable.log")
            marker.write_text(fingerprint)
    archive = RUNTIME / "julia.tar.gz"
    if not archive.exists():
        subprocess.run(["curl", "--fail", "--location", "--retry", "3",
                        "https://julialang-s3.julialang.org/bin/mac/aarch64/1.10/julia-1.10.12-macaarch64.tar.gz",
                        "--output", archive], check=True)
    if digest(archive) != PINS["julia_macos_arm64_sha256"]:
        raise RuntimeError("Julia archive checksum mismatch")
    julia = RUNTIME / "julia-1.10.12/bin/julia"
    if not julia.exists():
        with tarfile.open(archive) as tar:
            tar.extractall(RUNTIME, filter="data")
    env = {**environment(), "JULIA_PKG_PRECOMPILE_AUTO": "0"}
    subprocess.run([julia, "--startup-file=no", f"--project={CONFIG}", "-e",
                    'VERSION == v"1.10.12" || error("Wrong Julia version"); using Pkg; Pkg.instantiate()'],
                   env=env, check=True)
    print(f"Isolated runtimes ready: {RUNTIME}")


if __name__ == "__main__":
    main()
