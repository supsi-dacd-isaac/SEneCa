"""Compact evidence for the delay experiment; full cell comparisons stay in dist."""
from pathlib import Path
import argparse

from scripts.julia_repro.common import read, dump, digest


def summarize(original, directory):
    r, old = read(directory / "validation.json"), read(original / "validation.json")
    summary = {key: r[key] for key in ("experimental_validation_pass", "python_julia_pass", "native_pass",
                                       "native_equivalence_certified", "compiled_module_reused", "evidence_sha256")}
    summary.update(scenarios=len(r["cases"]), variables_per_scenario=len(next(iter(r["cases"].values()))["python_julia"]["rows"]),
                   compared_values=sum(row["elements"] for case in r["cases"].values() for row in case["python_julia"]["rows"]),
                   max_tolerance_fraction=max(row.get("max_tolerance_fraction", 0.) for case in r["cases"].values()
                                              for row in case["python_julia"]["rows"]),
                   python_repeat=r["python_repeat"]["bitwise_identical"], julia_repeat=r["julia_repeat"]["bitwise_identical"],
                   order_probes={k: v["bitwise_identical"] for k, v in r["order_probes"].items()},
                   app_probes={k: v["pass"] for k, v in r["app_probes"].items()},
                   unreviewed_warnings=r["warnings"],
                   validation_sha256=digest(directory / "validation.json"),
                   baseline_validation_sha256=digest(original / "validation.json"), cases={})
    for case, row in r["cases"].items():
        measures = {}
        for name in ("PHS hourly demand", "Electricity dispatched", "Energy price"):
            versions = {}
            for label, rows in (("sequential", old["cases"][case]["vensim_reconstructed_vs_python"]["rows"]),
                                ("synchronous", row["native"]["rows"])):
                v = next(v for v in rows if v["variable"] == name)
                versions[label] = {k: v[k] for k in ("max_abs", "max_fraction_variable_scale", "maximum_difference", "first_divergence") if k in v}
                if "annual_aggregate" in v:
                    versions[label]["annual_aggregate"] = v["annual_aggregate"]
            measures[name] = versions
        summary["cases"][case] = measures
    dump(directory / "summary.json", summary)
    return summary


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--run-dir", type=Path, required=True)
    a = p.parse_args()
    summarize(a.baseline.resolve(), a.run_dir.resolve())
