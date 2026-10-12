from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from scripts.julia_repro.common import ROOT, CONFIG, YEARS, digest, dump, read, experiment_hashes
from scripts.julia_repro.inventory import columns_for
from scripts.julia_repro.results import save_frame, load_snapshot
from scripts.julia_repro.comparison import compare
from scripts.julia_repro.energy import check_snapshot
from scripts.vensim_comparison.core import comparison, reconstruct_import, convert_raw


def exact_replay(a, b):
    result = compare(a, b, exact=True)
    _, aa = load_snapshot(a)
    _, bb = load_snapshot(b)
    result["bitwise_identical"] = result["pass"] and all(
        np.array_equal(values.view(np.uint64), bb[name].view(np.uint64)) for name, values in aa.items())
    result["pass"] = result["pass"] and result["bitwise_identical"]
    return result


def warning_review(directory, manifest):
    from scripts.julia_repro.translation import classify_warnings
    reference = read(directory / "reference/diagnostic/warnings.json")
    translation = classify_warnings(read(directory / "model/warnings.json"), [w["message"] for w in reference])
    known_names = {v["python_name"] for v in manifest["variables"].values()}
    messages = []
    for mode in ("app", "diagnostic", "fresh"):
        for warning in read(directory / "reference" / mode / "warnings.json"):
            msg = warning["message"]
            if "Data value missing or non-valid" in msg and "filled with the interpolation method" in msg:
                reason = "input_interpolation_used_by_both_engines"
            elif msg.startswith("_ext_data_") and msg.endswith("extrapolating data above the maximum value of the time") and msg.splitlines()[0].removeprefix("_ext_data_") in known_names:
                reason = "hold_last_external_value_used_by_both_engines"
            elif msg == "Replacing a variable by a constant value.":
                reason = "explicit_calibration_or_scenario_override"
            elif msg == "chardet.universaldetector is deprecated, import UniversalDetector from chardet or chardet.detector instead":
                reason = "dependency_deprecation_no_model_semantics"
            else:
                reason = "blocking"
            messages.append({**warning, "mode": mode, "classification": reason})
    dump(directory / "warnings-reviewed.json", {"python": messages, "translation": translation})
    return {"pass": not any(m["classification"] == "blocking" for m in messages + translation),
            "python_count": len(messages), "translation_count": len(translation),
            "review_sha256": digest(directory / "warnings-reviewed.json")}


def finish(directory, manifest, report):
    export = read(directory / "model/export.json")
    candidate = directory / "candidate"
    convert_raw(directory / "raw/01_base_repeat", candidate / "01_base_repeat", export, manifest)
    convert_raw(directory / "raw-fresh/01_base", candidate / "01_base_fresh", export, manifest)
    repeat = {}
    for mode in ("app", "diagnostic"):
        root = directory / "reference" / mode
        repeat[f"python_{mode}_sequence"] = exact_replay(root / "01_base", root / "01_base_repeat_10")
    repeat["python_fresh"] = exact_replay(directory / "reference/diagnostic/01_base", directory / "reference/fresh/01_base")
    repeat["julia_sequence"] = exact_replay(candidate / "01_base", candidate / "01_base_repeat")
    repeat["julia_fresh"] = exact_replay(candidate / "01_base", candidate / "01_base_fresh")
    report["reproducibility"] = repeat
    jobs = read(directory / "jobs.json")
    load = read(directory / "raw/load.json")
    timing = [read(directory / "raw" / job["id"] / "timing.json") for job in jobs]
    report["compiled_module_reused"] = (load["loads"] == 1
        and all(t["module_id"] == load["module_id"] for t in timing)
        and len({t["parameter_type"] for t in timing}) == 1
        and all(t["compilation_seconds"] == 0 for t in timing[1:])
        and all(t["parameters"] == job["parameters"] and t["initial_state_preserved"] for t, job in zip(timing, jobs)))
    expected = read(ROOT / "benchmarks/sure-v4/inherited-policy.json")["delay_update_policy"]["updated_reads"]
    audits = [read(directory / "debug/delay-audit" / mode / "01_base.audit.json") for mode in ("app", "diagnostic")]
    report["delay_update_audit_pass"] = all(a["pass"] and {
        k: v["reads_updated_states"] for k, v in a["delays"].items() if v["reads_updated_states"]} == expected for a in audits)
    report["warnings"] = warning_review(directory, manifest)
    fixtures = read(directory / "allocation-result.json")
    report["allocation_fixtures_pass"] = fixtures == {"pass": True, "cases": 104, "checks": 314}
    report["alignment_pass"] = (report["python_julia_pass"] and all(r["pass"] for r in repeat.values())
        and report["compiled_module_reused"] and report["delay_update_audit_pass"] and report["warnings"]["pass"]
        and report["allocation_fixtures_pass"] and all(r["python_energy"]["pass"] and r["julia_energy"]["pass"] for r in report["cases"].values()))
    report["pass"] = report["alignment_pass"] and report["native_reconstructed_pass"]
    report["native_equivalence_certified"] = False  # Sparse archive and unpublished source provenance remain explicit.
    # Bind all evidence to the final code, model, calibration, data and scenarios.
    implementation = experiment_hashes()
    for path in [*sorted((ROOT / "scripts/sure_v4").glob("*.py")), ROOT / "scripts/verify_sure_v4.py",
                 ROOT / "scripts/julia_parametric/model.py", ROOT / "benchmarks/julia-parametric/worker.jl",
                 *sorted((ROOT / "benchmarks/sure-v4").glob("*.jl")), ROOT / "benchmarks/sure-v4/inherited-policy.json",
                 ROOT / "scripts/vensim_comparison/core.py"]:
        implementation[str(path.relative_to(ROOT))] = digest(path)
    artifacts = {str(p.relative_to(directory)): digest(p) for p in sorted(directory.rglob("*")) if p.is_file()
                 and p.suffix in {".json", ".npz", ".bin", ".csv", ".mdl", ".jl", ".pkl", ".parquet", ".py"}
                 and p.name not in {"validation.json", "partial-validation.json", "evidence.json", "summary.json"}}
    dump(directory / "evidence.json", {"implementation": implementation, "artifacts": artifacts,
         "manifest_sha256": digest(directory / "manifest.json"), "native_inputs_sha256": digest(directory / "source/Vensim_test_runs/inputs.json")})
    report["evidence_sha256"] = digest(directory / "evidence.json")


def native(directory):
    manifest = read(directory / "manifest.json")
    outputs = manifest["native_outputs"]
    columns = [c for name in outputs for c in columns_for(name, manifest)]
    file = directory / "source/Vensim_test_runs/outputs.parquet"
    table = pq.ParquetFile(file)
    audit = {}
    for g in range(table.num_row_groups):
        data = table.read_row_group(g).to_pandas()
        ids = data.run_id.unique()
        assert len(ids) == 1 and ids[0] in manifest["scenarios"]
        case = str(ids[0])
        assert case not in audit and not data.duplicated(["variable", "element", "year"]).any()
        assert np.isfinite(data.value).all() and data.value.dtype == np.float32
        data["column"] = np.where(data.element == "", data.variable, data.variable.astype(str) + "[" + data.element.astype(str) + "]")
        frame = data.pivot(index="year", columns="column", values="value")
        assert set(frame.columns) == set(columns) and list(frame.index) == YEARS
        frame = frame.loc[YEARS, columns]
        raw = directory / "native/raw" / case
        raw.parent.mkdir(parents=True, exist_ok=True)
        save_frame(raw, frame, outputs, manifest)
        corrected, certificate = reconstruct_import(frame, (directory / "source/Vensim/SURE.mdl").read_text())
        filled = directory / "native/reconstructed" / case
        filled.parent.mkdir(parents=True, exist_ok=True)
        save_frame(filled, corrected, outputs, manifest)
        dump(filled.with_suffix(".reconstruction.json"), certificate)
        audit[case] = {"stored_cells": len(data), "series": len(columns),
                       "reconstructed_cells": certificate["cells"], "raw_snapshot_sha256": digest(raw.with_suffix(".json"))}
    assert set(audit) == set(manifest["scenarios"])
    dump(directory / "native/audit.json", audit)


def validate(directory, *, partial=False):
    manifest = read(directory / "manifest.json")
    for name, expected in manifest["sources"].items():
        assert digest(directory / "source" / name) == expected, name
    build = read(directory / "model/build.json")
    for name, expected in build["artifacts"].items():
        assert digest(directory / "model" / name) == expected, name
    exports = read(directory / "model/export.json")
    report = {"pass": False, "status": "partial" if partial else "complete", "cases": {}}
    for case in manifest["scenarios"]:
        py = directory / "reference/diagnostic" / case
        app = directory / "reference/app" / case
        raw = directory / "raw" / case
        if partial and not (raw / "timing.json").exists():
            continue
        julia = directory / "candidate" / case
        convert_raw(raw, julia, exports, manifest)
        row = {"app_vs_diagnostic": compare(app, py, outputs=manifest["outputs"], exact=True),
               "python_vs_julia": compare(py, julia),
               "python_energy": check_snapshot(py), "julia_energy": check_snapshot(julia),
               "vensim_raw_vs_python": comparison(directory / "native/raw" / case, py),
               "vensim_raw_vs_julia": comparison(directory / "native/raw" / case, julia),
               "vensim_reconstructed_vs_python": comparison(directory / "native/reconstructed" / case, py),
               "vensim_reconstructed_vs_julia": comparison(directory / "native/reconstructed" / case, julia)}
        report["cases"][case] = row
        print(case, {k: v["pass"] for k, v in row.items()}, flush=True)
        for item in row["python_vs_julia"]["rows"]:
            if not item["pass"]:
                print("DIVERGENCE", item, flush=True)
    report["python_julia_pass"] = len(report["cases"]) == len(manifest["scenarios"]) and all(
        r["python_vs_julia"]["pass"] and r["app_vs_diagnostic"]["pass"] for r in report["cases"].values())
    report["native_reconstructed_pass"] = len(report["cases"]) == len(manifest["scenarios"]) and all(
        r["vensim_reconstructed_vs_python"]["pass"] and r["vensim_reconstructed_vs_julia"]["pass"] for r in report["cases"].values())
    if not partial:
        finish(directory, manifest, report)
    dump(directory / ("partial-validation.json" if partial else "validation.json"), report)
    return report


if __name__ == "__main__":
    directory = Path(sys.argv[2]).resolve()
    if sys.argv[1] == "native":
        native(directory)
    else:
        validate(directory, partial=sys.argv[1] == "partial")
