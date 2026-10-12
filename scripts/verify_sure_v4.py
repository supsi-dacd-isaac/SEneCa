#!/usr/bin/env python3
"""Reproduce the isolated v4 Python/Julia/native Vensim comparison."""
from pathlib import Path
import argparse
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.julia_repro.common import ROOT, RUNTIME, CONFIG, dump, read, run_logged


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["prepare", "reference", "fixtures", "translate", "run", "validate", "all"])
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    directory = args.run_dir.resolve()
    phases = ["prepare", "reference", "fixtures", "translate", "run", "validate"] if args.phase == "all" else [args.phase]
    py, translator, jl = (RUNTIME / "python-reference/bin/python", RUNTIME / "python-julia/bin/python", RUNTIME / "julia-1.10.12/bin/julia")

    def python(module, arguments, log, executable=py):
        run_logged([executable, "-B", "-u", "-m", module, *arguments], directory / log)

    for phase in phases:
        print(f"v4: {phase}", flush=True)
        if phase == "prepare":
            # prepare refuses a nonempty result directory; the log stays outside.
            run_logged([py, "-B", "-m", "scripts.sure_v4.reference", "prepare", directory],
                       directory.parent / (directory.name + "-prepare.log"))
            python("scripts.sure_v4.validate", ["native", directory], "native.log")
        elif phase == "reference":
            cases = list(read(directory / "manifest.json")["scenarios"])
            for mode in ("app", "diagnostic"):
                python("scripts.sure_v4.reference", [mode, directory, *cases, "01_base"], mode + ".log")
                python("scripts.sure_v4.delay_audit", [directory, mode], f"delay-audit-{mode}.log")
            python("scripts.sure_v4.reference", ["fresh", directory, "01_base"], "fresh-python.log")
        elif phase == "fixtures":
            python("scripts.sure_v4.fixtures", [directory], "fixtures-python.log")
            run_logged([jl, "--startup-file=no", f"--project={CONFIG}", ROOT / "benchmarks/sure-v4/test_allocation.jl",
                        directory / "allocation-fixtures.json"], directory / "fixtures.log")
        elif phase == "translate":
            python("scripts.sure_v4.translate", [directory], "translation.log", executable=translator)
        elif phase == "run":
            cases = read(directory / "manifest.json")["scenarios"]
            dump(directory / "jobs.json", [{"id": k, "parameters": v} for k, v in cases.items()]
                 + [{"id": "01_base_repeat", "parameters": cases["01_base"]}])
            dump(directory / "fresh-jobs.json", [{"id": "01_base", "parameters": cases["01_base"]}])
            for jobs, out, log in [("jobs.json", "raw", "julia.log"), ("fresh-jobs.json", "raw-fresh", "fresh-julia.log")]:
                run_logged([jl, "--startup-file=no", f"--project={CONFIG}", ROOT / "benchmarks/julia-parametric/worker.jl",
                            directory / "model/SURE_v4.jl", directory / "model/export.json", directory / jobs, directory / out], directory / log)
        elif phase == "validate":
            python("scripts.sure_v4.validate", ["validate", directory], "validation.log")
            python("scripts.sure_v4.report", [directory], "report.log")


if __name__ == "__main__":
    main()
