"""Summarize complete validation without replacing its per-cell evidence."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sure_julia.common import ROOT, MODEL_REVISION, digest, dump, read
from sure_julia.validation import cases


def summarize(directory, output):
    manifest = read(directory / "manifest.json")
    if manifest["cases"] != cases() or manifest["build"] != digest(ROOT / "sure_julia/generated/build.json"):
        raise ValueError("Validation has a different scenario or model identity")
    gates = ["comparison", "python_physical", "julia_physical", "python_energy", "julia_energy", "warnings"]
    totals = dict.fromkeys(gates, 0)
    rows, maxima, evidence, minima = [], {}, {}, {}
    cells = 0
    for name in manifest["cases"]:
        path = directory / name / "report.json"
        report = read(path)
        rows.append({"case": name, "pass": report["pass"]})
        for gate in gates:
            totals[gate] += bool(report.get(gate, {}).get("pass"))
        for row in report.get("comparison", {}).get("rows", []):
            cells += row.get("cells", 0)
            if "max_abs" in row and row["max_abs"] >= maxima.get(row["variable"], {}).get("max_abs", -1):
                maxima[row["variable"]] = {"case": name, "max_abs": row["max_abs"]}
        for engine in ("python", "julia"):
            for variable in ("Heating Solution", "Annual archetypes"):
                check = report.get(engine + "_physical", {}).get("checks", {}).get("nonnegative:" + variable)
                key = engine + ":" + variable
                if check and check["minimum"] < minima.get(key, {}).get("minimum", float("inf")):
                    minima[key] = {"case": name, "minimum": check["minimum"]}
        evidence[name] = digest(path)
    result = {"model_revision": MODEL_REVISION, "pass": all(r["pass"] for r in rows),
              "cases": len(rows), "passing_cases": sum(r["pass"] for r in rows),
              "compared_values": cells, "outputs": len(maxima), "passing_gates": totals,
              "minima": minima, "maximum_absolute_errors": maxima, "case_results": rows,
              "report_sha256": evidence, "validation_manifest_sha256": digest(directory / "manifest.json"),
              "native_vensim_verified": False, "release_and_deploy": "Await colleague's native Vensim verification"}
    dump(output, result)
    print({k: result[k] for k in ("pass", "cases", "passing_cases", "compared_values", "outputs", "minima")})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("validation", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    summarize(args.validation, args.output)
