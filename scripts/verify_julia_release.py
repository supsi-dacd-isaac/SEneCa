"""Ensure a release image uses the model that generated its pinned dataset."""
import json
import hashlib
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def normalized_warnings(warnings):
    """Checkout locations may differ; input filenames/cells/messages must not."""
    return [{**w, "message": re.sub(r"(File name:\s*)'([^']+)'",
            lambda m: m[1] + repr(Path(m[2].replace('\\', '/')).name), w["message"])} for w in warnings]


def verify_ems(root, provenance, actual):
    sections = json.loads((root / "provenance/sections.json").read_text())
    validation = sections.get("julia_validation", {})
    if (provenance["backend"] != "python" or sections["backend"] != "python"
            or not isinstance(validation, dict) or validation.get("pass") is not True
            or validation.get("scenarios") != 871):
        raise ValueError("EMS data must have complete independent Python-Julia verification")
    expected = provenance["model"]
    if (sections["model_revision"] != actual["model_revision"]
            or sections["sources"] != actual["sources"]
            or validation["build_sha256"] != provenance["model_metadata_sha256"]):
        raise ValueError("EMS data provenance differs from the verified model")
    scenarios = root / "provenance/sections.parquet"
    if hashlib.sha256(scenarios.read_bytes()).hexdigest() != sections["scenarios_sha256"]:
        raise ValueError("EMS scenario provenance checksum differs")
    certificate, audit = provenance["live_certificate"], provenance["data_audit"]
    if (certificate.get("pass") is not True or certificate.get("complete_suite") is not True
            or len(certificate.get("cases", {})) != 55 or not all(certificate["cases"].values())
            or certificate["build"] != provenance["model_metadata_sha256"]
            or audit.get("pass") is not True or audit.get("scenarios") != 871
            or audit.get("configurations") != 1197
            or audit.get("model_revision") != actual["model_revision"]
            or audit.get("generation_manifest_sha256") != sections["generation_manifest_sha256"]):
        raise ValueError("Incomplete EMS live/data validation evidence")
    from scripts.data_release import EMS_DATA_PATHS
    stores = {Path(p).stem.removesuffix("_scenarios"): p for p in EMS_DATA_PATHS if p.startswith("precomputed/")}
    if set(audit.get("sections", {})) != set(stores):
        raise ValueError("EMS audit does not cover every installed store")
    for section, path in stores.items():
        if hashlib.sha256((root / path).read_bytes()).hexdigest() != audit["sections"][section]["new_sha256"]:
            raise ValueError(f"EMS installed store differs from verified data: {section}")
    for key in ("sources", "defaults", "parameters", "years", "float", "delay_policy", "model_revision"):
        if actual[key] != expected[key]:
            raise ValueError(f"EMS runtime and data differ: {key}")
    # The warning text contains its build directory. All numerical artifacts
    # remain byte-identical; compare warning contents after removing only that path.
    numerical = lambda items: {k:v for k,v in items.items() if k != "warnings.json"}
    if numerical(actual["artifacts"]) != numerical(expected["artifacts"]):
        raise ValueError("EMS generated numerical artifacts differ")
    warnings = json.loads((root / "sure_julia/generated/warnings.json").read_text())
    if normalized_warnings(warnings) != provenance["translation_warnings"]:
        raise ValueError("EMS translation warnings differ")
    for path in ("sure_julia/julia/Manifest.toml", "sure_julia/julia/Project.toml", "sure_julia/python.lock"):
        if actual["implementation"][path] != expected["implementation"][path]:
            raise ValueError(f"EMS runtime dependency lock differs: {path}")


def verify(root):
    root = Path(root)
    pin = json.loads((root / "data-release.json").read_text())
    if pin["tag"] == "data-v1.0.0":
        return  # Historical Vensim snapshot, explicitly predating Julia.
    provenance = json.loads((root / "provenance/build.json").read_text())
    actual = json.loads((root / "sure_julia/generated/build.json").read_text())
    if pin["tag"].startswith("data-ems-v"):
        verify_ems(root, provenance, actual)
        return
    if provenance["backend"] != "julia":
        raise ValueError("Expected a Julia-generated dataset")
    expected = provenance["model"]
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
