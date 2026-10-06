"""Wrapper resumable dei 4 batch Vensim: rilancia il processo se la DLL chiede
un restart (exit 75) e, a fine corsa, verifica i parquet consolidati.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
RELAUNCH = 75

JOBS = [
    {
        "name": "pv",
        "script": ROOT / "pv_batteries" / "precompute_pv_batteries.py",
        "restart_env": "PVBAT_RESTARTS",
    },
    {
        "name": "risanamento",
        "script": ROOT / "pv_batteries" / "precompute_risanamento.py",
        "restart_env": "SECTION_RESTARTS",
    },
    {
        "name": "veicoli",
        "script": ROOT / "pv_batteries" / "precompute_veicoli.py",
        "restart_env": "SECTION_RESTARTS",
    },
    {
        "name": "elettricita",
        "script": ROOT / "pv_batteries" / "precompute_elettricita.py",
        "restart_env": "SECTION_RESTARTS",
    },
    {
        "name": "exploratory",
        "script": ROOT / "pv_batteries" / "precompute_exploratory.py",
        "restart_env": "EXPL_RESTARTS",
    },
]


def run_job(job: dict, extra: list[str]) -> None:
    n = 0
    while True:
        env = os.environ.copy()
        env[job["restart_env"]] = str(n)
        env["PYTHONPATH"] = os.pathsep.join(
            [str(ROOT), str(ROOT / "pv_batteries"), env.get("PYTHONPATH", "")])
        cmd = [str(PY), "-u", str(job["script"]), *extra]
        print(f"\n=== {job['name']} restart#{n} ===", flush=True)
        rc = subprocess.call(cmd, cwd=str(ROOT), env=env)
        if rc == 0:
            print(f"=== {job['name']} OK ===", flush=True)
            return
        if rc == RELAUNCH:
            n += 1
            continue
        raise SystemExit(f"{job['name']} fallito con exit {rc}")


def main() -> None:
    args = sys.argv[1:]
    names = {j["name"] for j in JOBS}
    selected = [a for a in args if a in names]
    extra = [a for a in args if a not in names]
    jobs = [j for j in JOBS if j["name"] in selected] if selected else JOBS
    for job in jobs:
        run_job(job, extra)


if __name__ == "__main__":
    main()
