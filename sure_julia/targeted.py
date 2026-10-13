"""Run the retained small-model regression fixtures against production patches."""
import argparse
import importlib
from pathlib import Path
import subprocess
import sys

from .common import CONFIG, ROOT, digest, dump, read


def prepare(directory, julia):
    if julia:
        # Reuse audited fixture inputs, but translate with production code only.
        for name in ("builder_patch", "external_patch", "stateful_patch", "indexing_patch", "ode_patch",
                     "hotpath_patch", "numpy_math_patch", "lookup_patch", "reduction_policy"):
            sys.modules[f"scripts.julia_repro.{name}"] = importlib.import_module(f"sure_julia.translator.{name}")
        from .translator.builder_patch import apply
        apply()
    from scripts.julia_repro import fixtures, indexing_fixtures, external_fixtures, stateful_fixtures, semantic_fixtures
    if julia:
        fixtures.prepare(directory)
        if not read(directory / "fixtures/translation.json")["pass"]:
            raise ValueError("Small-model translation failed")
        indexing_fixtures.prepare(directory / "indexing")
        external_fixtures.prepare(directory / "external")
    else:
        fixtures.python_oracles(directory / "fixtures")
        fixtures.allocation_cases(directory / "fixtures/allocation.json")
        indexing_fixtures.oracle(directory / "indexing")
        external_fixtures.oracle(directory / "external")
        source = directory / "source"
        source.mkdir(exist_ok=True)
        if not (source / "Vensim").exists():
            (source / "Vensim").symlink_to(ROOT / "Vensim", target_is_directory=True)
        from scripts.sure_v4.fixtures import prepare as allocate
        allocate(directory)
    stateful_fixtures.prepare(directory / "stateful", reference=not julia)
    semantic_fixtures.prepare(directory / "semantics", reference=not julia)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--prepare", choices=["julia", "python"])
    args = parser.parse_args()
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if args.prepare:
        prepare(directory, args.prepare == "julia")
        return
    for interpreter, kind in [("/opt/translator/bin/python", "julia"), (sys.executable, "python")]:
        with (directory / f"prepare-{kind}.log").open("w") as log:
            subprocess.run([interpreter, "-m", "sure_julia.targeted", str(directory), "--prepare", kind], stdout=log, stderr=subprocess.STDOUT, check=True)
    results = {}
    for name, test, manifest in [("fixtures", "test_models.jl", "models.json"),
                                 ("indexing", "test_indexing.jl", "models.json"),
                                 ("external", "test_external.jl", "models.json"),
                                 ("stateful", "test_stateful_models.jl", "models.json"),
                                 ("semantics", "test_stateful_models.jl", "models.json")]:
        target = directory / name
        with (target / "julia.log").open("w") as log:
            subprocess.run(["julia", "--startup-file=no", f"--project={CONFIG}", str(ROOT / "benchmarks/julia-repro" / test),
                            str(target if name in {"indexing", "external"} else target / manifest),
                            str(target / "result.json")], stdout=log, stderr=subprocess.STDOUT, check=True)
        results[name] = read(target / ("results.json" if name in {"indexing", "external"} else "result.json"))
    with (directory / "allocation.log").open("w") as log:
        subprocess.run(["julia", "--startup-file=no", f"--project={CONFIG}", str(ROOT / "benchmarks/sure-v4/test_allocation.jl"),
                        str(directory / "allocation-fixtures.json")], stdout=log, stderr=subprocess.STDOUT, check=True)
    results["allocation"] = read(directory / "allocation-result.json")
    report = {"pass": all(v["pass"] for v in results.values()), "results": results,
              "production_patches": {p.name: digest(p) for p in (ROOT / "sure_julia/translator").glob("*.py")}}
    dump(directory / "summary.json", report)
    if not report["pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
