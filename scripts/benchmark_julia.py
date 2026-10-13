#!/usr/bin/env python3
"""Local, fail-closed SURE Python/Julia reproducibility runner."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.julia_repro.common import ROOT, RUNTIME, dump, read, run_logged, check_sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["inventory", "test", "reference", "translate", "validate", "benchmark", "report", "all", "_reference", "_translate"])
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--scenarios", nargs="+", help="Default: complete frozen scenario suite")
    parser.add_argument("--mode", choices=["app", "diagnostic"], default="app")
    parser.add_argument("--label")
    parser.add_argument("--resume", action="store_true", help="Reuse reference/Julia results only when their complete provenance still matches")
    parser.add_argument("--jobs", type=int, default=1, help="Independent Julia validation processes; benchmarks always run sequentially")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    directory = args.run_dir or ROOT / "dist/julia-repro" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = directory.resolve()
    if args.phase not in {"inventory", "all"} and not (directory / "manifest.json").is_file():
        parser.error("Use --run-dir with an existing inventory")
    directory.mkdir(parents=True, exist_ok=True)
    phases = ["inventory", "test", "reference", "translate", "validate", "benchmark"] if args.phase == "all" else [args.phase]
    script = Path(__file__).resolve()
    for phase in phases:
        print(f"{phase}: {directory}", flush=True)
        try:
            if not phase.startswith("_"):
                dump(directory / "status" / f"{phase}.json", {"status": "running"})
            if phase == "inventory":
                if (directory / "manifest.json").exists():
                    raise RuntimeError("Inventory is immutable; choose a new run directory")
                from scripts.julia_repro.inventory import make_inventory
                manifest = make_inventory(directory)
            else:
                manifest = read(directory / "manifest.json")
                check_sources(manifest)
            selected = args.scenarios or list(manifest["scenarios"])
            cases = [manifest["aliases"].get(s, s) for s in selected]
            for case in cases:
                if case not in manifest["scenarios"]:
                    raise ValueError(f"Unknown scenario {case}")
            if phase == "test":
                from scripts.julia_repro.fixtures import run
                run_logged([RUNTIME / "python-reference/bin/python", "-m", "unittest", "discover", "-s", "tests",
                            "-p", "test_julia*.py", "-v"], directory / "logs/unit-tests.log")
                if not run(directory)["pass"]:
                    raise RuntimeError("Julia semantic fixtures failed; see fixtures.json")
            elif phase == "reference":
                from scripts.julia_repro.reference import run_reference_suite
                run_reference_suite(directory, cases, resume=args.resume)
            elif phase == "_reference":
                import os
                if os.environ.get("PYTHONHASHSEED") != "0" or sys.flags.hash_randomization != 0:
                    raise RuntimeError("Reference requires PYTHONHASHSEED=0 at interpreter startup; use the public reference phase")
                from scripts.julia_repro.reference import run_reference
                run_reference(directory, cases, args.mode, args.label)
            elif phase == "translate":
                for case in cases:
                    run_logged([RUNTIME / "python-julia/bin/python", script, "_translate", "--run-dir", directory,
                                "--scenarios", case], directory / "logs" / f"translate_{case}.log")
            elif phase == "_translate":
                from scripts.julia_repro.translation import translate
                for case in cases:
                    translate(directory, case)
            elif phase == "validate":
                from scripts.julia_repro.execution import validate
                validate(directory, cases, resume=args.resume, jobs=args.jobs)
            elif phase == "benchmark":
                from scripts.julia_repro.execution import benchmark
                benchmark(directory)
            elif phase == "report":
                from scripts.julia_repro.reporting import write_report
                write_report(directory)
            if not phase.startswith("_"):
                dump(directory / "status" / f"{phase}.json", {"status": "complete", "scenarios": cases})
        except Exception as exc:
            if not phase.startswith("_"):
                dump(directory / "status" / f"{phase}.json", {"status": "failed", "error": str(exc)})
            raise
        finally:
            if not phase.startswith("_") and (directory / "manifest.json").exists():
                from scripts.julia_repro.reporting import write_report
                write_report(directory)
    print(f"Artifacts: {directory}")


if __name__ == "__main__":
    main()
