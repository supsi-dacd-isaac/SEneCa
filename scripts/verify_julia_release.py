"""Ensure a release image uses the model that generated its pinned dataset."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Files the native worker loads at run time: a change here changes the numbers.
NATIVE_RUNTIME = ("sure_native/Manifest.toml", "sure_native/Project.toml", "sure_native/webapp_worker.jl",
                  "sure_native/src/parser.jl", "sure_native/src/runtime.jl", "sure_native/src/simulate.jl")


def verify_native(root, expected):
    from sure_julia.common import NATIVE_REVISION, digest
    directory = root / "sure_native/generated"
    actual = json.loads((directory / "build.json").read_text())
    if not actual.get("complete") or actual.get("model_revision") != NATIVE_REVISION:
        raise ValueError("Incomplete native build or different revision")
    for key in ("worker", "artifacts", "sources", "years", "float", "model_revision"):
        if actual[key] != expected[key]:
            raise ValueError(f"Runtime and pinned dataset use different model {key}")
    for name, value in actual["artifacts"].items():
        if digest(directory / name) != value:
            raise ValueError(f"Native build file differs from its build record: {name}")
    for path in NATIVE_RUNTIME:
        if expected["implementation"][path] not in line_ending_digests(root / path):
            raise ValueError(f"Runtime file differs from data generation: {path}")


def line_ending_digests(path):
    """Digests of the file with LF or CRLF endings: the data were generated on
    Windows, the image is built from the LF files stored in git."""
    import hashlib
    lf = path.read_bytes().replace(b"\r\n", b"\n")
    return {hashlib.sha256(data).hexdigest() for data in (lf, lf.replace(b"\n", b"\r\n"))}


def verify(root):
    root = Path(root)
    pin = json.loads((root / "data-release.json").read_text())
    if pin["tag"] == "data-v1.0.0":
        return  # Historical Vensim snapshot, explicitly predating Julia.
    provenance = json.loads((root / "provenance/build.json").read_text())
    if provenance["backend"] != "julia":
        raise ValueError("Expected a Julia-generated dataset")
    expected = provenance["model"]
    if expected.get("worker") == "native":
        verify_native(root, expected)
    else:
        actual = json.loads((root / "sure_julia/generated/build.json").read_text())
        # Build metadata also includes non-numerical runners and diagnostics, which
        # can evolve without changing the generated equations or their inputs.
        for key in ("artifacts", "sources", "defaults", "parameters", "years", "float", "delay_policy", "model_revision"):
            if actual[key] != expected[key]:
                raise ValueError(f"Runtime and pinned dataset use different model {key}")
        for path in ("sure_julia/julia/Manifest.toml", "sure_julia/julia/Project.toml", "sure_julia/python.lock"):
            if actual["implementation"][path] != expected["implementation"][path]:
                raise ValueError(f"Runtime dependency lock differs from data generation: {path}")
    import pandas as pd
    from pv_batteries.exploratory import validate_kpi_store
    from pv_batteries.exploratory_config import validate_samples
    validate_samples(pd.read_parquet(root / 'precomputed/exploratory/uncertainty_samples.parquet'))
    validate_kpi_store(pd.read_parquet(root / 'precomputed/exploratory_kpis.parquet'))


if __name__ == "__main__":
    verify(Path(__file__).resolve().parents[1])
