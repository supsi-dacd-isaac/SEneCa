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
    args = parser.parse_args()
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
                            "-p", "test_julia_repro.py", "-v"], directory / "logs/unit-tests.log")
                if not run(directory)["pass"]:
                    raise RuntimeError("Julia semantic fixtures failed; see fixtures.json")
            elif phase == "reference":
                from scripts.julia_repro.results import compare
                from scripts.julia_repro.packing import validate_real_snapshot
                for case in cases:
                    for mode in ("app", "diagnostic"):
                        run_logged([RUNTIME / "python-reference/bin/python", script, "_reference",
                                    "--run-dir", directory, "--scenarios", case, "--mode", mode],
                                   directory / "logs" / f"reference_{mode}_{case}.log")
                    report = compare(directory / "reference/app" / case,
                                     directory / "reference/diagnostic" / case, outputs=manifest["outputs"])
                    dump(directory / "checks" / f"reference_{case}.json", report)
                    if not report["pass"]:
                        raise RuntimeError(f"Reference invalid or diagnostic path differs: {case}")
                    dump(directory / "checks" / f"packing_{case}.json",
                         validate_real_snapshot(directory / "reference/diagnostic" / case))
                for label, seq in [("fresh_a", ["base"]), ("fresh_b", ["base"]),
                                   ("sequence", ["base", "high", "base"])]:
                    run_logged([RUNTIME / "python-reference/bin/python", script, "_reference",
                                "--run-dir", directory, "--scenarios", *seq, "--label", label],
                               directory / "logs" / f"reference_{label}.log")
                reports = [compare(directory / "reference/app/base", directory / "reference/app" / suffix, exact=True)
                           for suffix in ["fresh_a_00_base", "fresh_b_00_base", "sequence_00_base", "sequence_02_base"]]
                dump(directory / "checks/reference_determinism.json", {"pass": all(r["pass"] for r in reports), "comparisons": reports})
                if not all(r["pass"] for r in reports):
                    raise RuntimeError("Reference determinism failed")
            elif phase == "_reference":
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
                validate(directory, cases)
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
