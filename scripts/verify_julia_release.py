"""Ensure a release image uses the model that generated its pinned dataset."""
import json
import hashlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


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
    if int(pin["tag"].removeprefix("data-v").split(".")[0]) >= 3:
        from sure_julia.common import digest
        certificate = provenance["validation_certificate"]
        generation = provenance["generation"]
        encoded = (json.dumps(certificate, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
        if (certificate.get("pass") is not True or not certificate.get("complete_suite")
                or len(certificate["cases"]) != 427 or not all(certificate["cases"].values())
                or certificate["build"] != generation["build"]
                or hashlib.sha256(encoded).hexdigest() != generation["validation_certificate_sha256"]):
            raise ValueError("Missing or inconsistent full v8 validation certificate")
        reviewed = json.loads((root / "docs/validation/v8-inputs.json").read_text())
        native = {p.name: digest(p) for p in (root / "Vensim").glob("*.vdfx")}
        if native != reviewed["native_inputs"] or native != provenance["native_inputs"]:
            raise ValueError("Native inputs differ from the reviewed v8 source")
        sample_hash = digest(root / "precomputed/exploratory/uncertainty_samples.parquet")
        if sample_hash != generation["sample_sha256"] or sample_hash != reviewed["uncertainty_samples_sha256"]:
            raise ValueError("The v8 uncertainty draws changed")
        sections = provenance["section_validation"]
        if (sections.get("pass") is not True or sections["scenarios"] != 1771
                or sections["configurations"] != 1779
                or sections["model_revision"] != actual["model_revision"]
                or len(sections["sections"]) != 6
                or any(s["python_julia"]["cells_beyond_tolerance"] for s in sections["sections"].values())):
            raise ValueError("Incomplete v8 section equivalence audit")
        curves = provenance["calibration_curves"]
        if (curves["model_sources"] != actual["sources"]
                or curves["validated_julia_comparison_pass"] is not True
                or curves["csv_sha256"] != digest(root / "content/system_dynamics/plots_data/calibration_sim_adoptions_v8.csv")):
            raise ValueError("Calibration plots and dataset have different model identities")
    import pandas as pd
    from pv_batteries.exploratory import validate_kpi_store
    from pv_batteries.exploratory_config import validate_samples
    validate_samples(pd.read_parquet(root / 'precomputed/exploratory/uncertainty_samples.parquet'))
    validate_kpi_store(pd.read_parquet(root / 'precomputed/exploratory_kpis.parquet'))


if __name__ == "__main__":
    verify(Path(__file__).resolve().parents[1])
