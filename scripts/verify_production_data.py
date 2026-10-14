"""Audit a completed Julia dataset before packaging its immutable release."""
import argparse
import collections
import datetime
import json
from pathlib import Path
import statistics
import sys

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sure_julia.common import ROOT, MODEL_REVISION, YEARS, digest, dump, read
from pv_batteries import exploratory_config as exp
from pv_batteries.exploratory import validate_kpi_store


ROWS = {
    "precomputed/pv_batteries_scenarios.parquet": 12960,
    "precomputed/risanamento_scenarios.parquet": 48600,
    "precomputed/veicoli_scenarios.parquet": 5760,
    "precomputed/elettricita_hourly.parquet": 40919040,
    "precomputed/elettricita_combo_index.parquet": 96,
    "precomputed/exploratory_kpis.parquet": 12800,
    "precomputed/pv_batteries_gmd.parquet": 324,
    "precomputed/risanamento_gmd.parquet": 1215,
    "precomputed/exploratory/uncertainty_samples.parquet": 100,
    "provenance/scenarios.parquet": 14571,
}
CONFIGURATIONS = {"pv_batteries": 324, "risanamento": 1215,
                  "veicoli": 144, "elettricita": 96, "exploratory": 12800}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify(directory, resources=None):
    directory = Path(directory)
    release = directory / "release"
    summary, manifest = read(directory / "summary.json"), read(directory / "manifest.json")
    require(summary["complete"] and summary["scenarios"] == 14571, "Incomplete dataset")
    require(not list((directory / "failed").glob("*.json")), "Failed scenarios remain")
    provenance_build = read(release / "provenance/build.json")
    require(provenance_build["model"].get("model_revision") == MODEL_REVISION, "Wrong model revision")
    require(provenance_build["generation_manifest_sha256"] == digest(directory / "manifest.json"), "Generation manifest differs")
    require(provenance_build["generation"] == manifest, "Generation provenance differs")
    require(manifest["build"] == digest(ROOT / "sure_julia/generated/build.json"), "Generated build differs")
    require(provenance_build["scenarios_sha256"] == digest(release / "provenance/scenarios.parquet"), "Scenario provenance checksum differs")
    files = {}
    for name, expected in ROWS.items():
        path = release / name
        reader = pq.ParquetFile(path)
        require(reader.metadata.num_rows == expected, f"Incomplete rows: {name}")
        previous = ROOT / name
        if previous.exists():
            expected_columns = set(pq.read_schema(previous).names)
            if name == "precomputed/exploratory_kpis.parquet":
                expected_columns |= {"pv_self_coverage", "pv_self_consumed_gwh", "electricity_demand_gwh"}
            require(expected_columns == set(reader.schema_arrow.names), f"Application columns differ: {name}")
        for batch in reader.iter_batches(batch_size=65536):
            for field, column in zip(batch.schema, batch.columns):
                require(column.null_count == 0, f"Missing values: {name}/{field.name}")
                if pa.types.is_floating(field.type):
                    require(field.type == pa.float64(), f"Float64 required: {name}/{field.name}")
                    require(np.isfinite(column.to_numpy()).all(), f"Nonfinite values: {name}/{field.name}")
        files[name] = {"rows": expected, "bytes": path.stat().st_size, "sha256": digest(path)}
    require(files["precomputed/exploratory/uncertainty_samples.parquet"]["sha256"] == digest(exp.SAMPLES_PATH) == manifest["sample_sha256"], "Uncertainty samples changed")
    exp.validate_samples(pq.read_table(release / "precomputed/exploratory/uncertainty_samples.parquet").to_pandas())
    exploratory = pq.read_table(release / "precomputed/exploratory_kpis.parquet").to_pandas()
    validate_kpi_store(exploratory)
    rows = pq.read_table(release / "provenance/scenarios.parquet").to_pylist()
    by_id = {row["scenario_id"]: row for row in rows}
    require(len(by_id) == 14571 == len(manifest["jobs"]), "Duplicate/missing scenarios")
    require(set(by_id) == {job["id"] for job in manifest["jobs"]}, "Scenario coverage differs")
    times, negative, minimum = [], 0, 0.0
    destinations = collections.Counter()
    for job in manifest["jobs"]:
        report = read(directory / "completed" / (job["id"] + ".json"))
        row = by_id[job["id"]]
        require(report["status"] == "complete", f"Incomplete scenario: {job['id']}")
        require(len(report["parameters"]) == 40 and report["parameters"] == job["parameters"] == json.loads(row["parameters_json"]), "Scenario inputs differ")
        require(report["destinations"] == job["destinations"] == json.loads(row["destinations_json"]), "Scenario destinations differ")
        require(report["value_sha256"] == row["output_sha256"], "Numerical output identity differs")
        require(report["timing"]["years"] == YEARS, "Incomplete simulation years")
        require(report["timing"]["compilation_seconds"] == 0, "Compilation occurred after warm-up")
        physical = report["physical"]
        require(physical == json.loads(row["physical_checks_json"]), "Physical provenance differs")
        require(physical["pass"] and all(check["pass"] for check in physical["checks"].values()), f"Physical failure: {job['id']}")
        audit = report["gmd_weight_audit"]
        require(audit == json.loads(row["gmd_weight_audit_json"]), "GMD provenance differs")
        require(all(item["beyond_numerical_zero"] == 0 for item in audit), f"Negative GMD weights: {job['id']}")
        negative += any(item["excluded_cells"] > 0 for item in audit)
        minimum = min([minimum] + [item["minimum"] for item in audit])
        times.append(report["elapsed_seconds"])
        destinations.update(dest["section"] for dest in job["destinations"])
    require(dict(destinations) == CONFIGURATIONS, "Incomplete application configuration grids")
    result = {"pass": True, "model_revision": MODEL_REVISION, "files": files,
              "scenarios": len(by_id), "configurations": dict(destinations), "batch": summary,
              "scenario_seconds": {"mean": statistics.mean(times), "median": statistics.median(times),
                                   "min": min(times), "max": max(times)},
              "jit_after_warmup_seconds": 0.0,
              "gmd_audit": {"scenarios_with_roundoff_weights": negative,
                            "scenarios_with_substantive_negative_weights": 0, "minimum_weight": minimum},
              "finished_utc": datetime.datetime.fromtimestamp((directory / "summary.json").stat().st_mtime,
                                                               datetime.timezone.utc).isoformat()}
    if resources:
        samples = [json.loads(line) for line in Path(resources).read_text().splitlines()]
        samples = [sample for sample in samples if sample["phase"] == "full-regeneration"]
        require(bool(samples), "No full-regeneration resource samples")
        peak = max(sample["memory_current"] for sample in samples)
        require(peak <= 128 * 1024**3, "Memory budget exceeded")
        result["sampled_peak_container_memory_bytes"] = peak
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--resources", type=Path)
    args = parser.parse_args()
    result = verify(args.directory, args.resources)
    dump(args.output, result)
    print(json.dumps({key: value for key, value in result.items() if key != "files"}, indent=2))
