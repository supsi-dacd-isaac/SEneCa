"""Reuse a completed batch after adding parameters at the value the model already used.

When new levers are added to the grid with the model default as base, every
scenario computed before is the same simulation with those levers at the
default: only its identity (hash of all parameters) changes. This copies such
results into a new run directory under the new identities, adding the new
input columns where a section stores its inputs, so that sure_julia.batch
computes only the new combinations.

Uso: python -m sure_julia.reuse_runs OLD_RUN NEW_RUN NAME=VALUE [NAME=VALUE ...]
Ogni NAME=VALUE è un parametro aggiunto e il valore usato implicitamente dal
vecchio batch (il default di SURE.mdl). Verificare poi con --check su alcuni
scenari che il ricalcolo dia lo stesso value_sha256.
"""
import shutil
import sys
from pathlib import Path

import pandas as pd

from .batch import atomic_parquet, jobs
from .common import digest, dump, identity, read


def reuse(old, new, added):
    old, new = Path(old), Path(new)
    by_key = {}
    for job in jobs():
        params = job["parameters"]
        if all(params[k] == v for k, v in added.items()):
            legacy = {k: v for k, v in params.items() if k not in added}
            by_key[identity(legacy)] = job
    reused = 0
    for path in sorted((old / "completed").glob("*.json")):
        report = read(path)
        job = by_key.get(identity(report["parameters"]))
        if job is None or path.stem != identity(report["parameters"]):
            continue  # combination no longer in the grid
        strip = lambda dests: sorted((d["section"], identity({k: v for k, v in d["inputs"].items() if k not in added}))
                                     for d in dests)
        if strip(job["destinations"]) != strip(report["destinations"]):
            continue  # same simulation now serves other pages: compute it again
        files = {}
        for name in report["files"]:
            source = old / name
            if digest(source) != report["files"][name]:
                raise ValueError(f"Old checkpoint changed: {name}")
            target_name = name.replace(path.stem, job["id"])
            target = new / target_name
            target.parent.mkdir(parents=True, exist_ok=True)
            section = Path(name).parent.name
            frame = pd.read_parquet(source)
            # sections that store their own inputs get the new input columns
            dest_inputs = next((d["inputs"] for d in job["destinations"] if d["section"] == section.removesuffix("_gmd")), {})
            extra = {k: v for k, v in dest_inputs.items() if k not in frame.columns}
            if extra:
                for k, v in extra.items():
                    frame[k] = v
                atomic_parquet(frame, target)
            else:
                shutil.copy2(source, target)
            files[target_name] = digest(target)
        dump(new / "completed" / f"{job['id']}.json",
             {**report, "parameters": job["parameters"], "destinations": job["destinations"], "files": files,
              "reused_from": {"run": str(old), "scenario_id": path.stem, "added_parameters": added}})
        reused += 1
    print(f"riusati {reused} scenari; da calcolare {len(jobs()) - reused}")


if __name__ == "__main__":
    old, new, *pairs = sys.argv[1:]
    reuse(old, new, {k: float(v) for k, v in (p.split("=", 1) for p in pairs)})
