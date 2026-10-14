"""Ensure a release image uses the model that generated its pinned dataset."""
import json
from pathlib import Path


def verify(root):
    root = Path(root)
    pin = json.loads((root / "data-release.json").read_text())
    if pin["tag"] == "data-v1.0.0":
        return  # Historical Vensim snapshot, explicitly predating Julia.
    provenance = json.loads((root / "provenance/build.json").read_text())
    if provenance["backend"] != "julia":
        raise ValueError("Expected a Julia-generated dataset")
    expected = provenance["model"]
    actual = json.loads((root / "sure_julia/generated/build.json").read_text())
    # Build metadata also includes non-numerical runners and diagnostics, which
    # can evolve without changing the generated equations or their inputs.
    for key in ("artifacts", "sources", "defaults", "parameters", "years", "float", "delay_policy", "model_revision"):
        if actual[key] != expected[key]:
            raise ValueError(f"Runtime and pinned dataset use different model {key}")
    for path in ("sure_julia/julia/Manifest.toml", "sure_julia/julia/Project.toml", "sure_julia/python.lock"):
        if actual["implementation"][path] != expected["implementation"][path]:
            raise ValueError(f"Runtime dependency lock differs from data generation: {path}")


if __name__ == "__main__":
    verify(Path(__file__).resolve().parents[1])
