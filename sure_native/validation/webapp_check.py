"""Prova end-to-end del build nativo attraverso il backend della webapp.

Per ogni scenario di validazione scelto: JuliaBackend (sure_julia/runtime.py) con il
build nativo, parametri passati da sure_julia.catalog.parameters (come la webapp),
tutte le uscite del catalogo, controlli fisici di physical.py; poi confronto cella
per cella con il riferimento Vensim (.ref) dello scenario.

Uso: python -m sure_native.validation.webapp_check SCENARIOS.json REFS_DIR OUT.json [id,id,...]
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

from sure_julia.catalog import defaults
from sure_julia.runtime import JuliaBackend
from sure_julia.physical import PhysicalInvariantError
from sure_julia.common import ROOT


def norm(s):
    return " ".join(s.replace('"', "").replace("_", " ").lower().split())


def read_ref(d):
    names = (d / "names.txt").read_text(encoding="utf-8").split("\n")[:-1]
    times = np.fromfile(d / "times.f64")
    V = np.fromfile(d / "values.f64").reshape(len(names), len(times))
    idx = {}
    for i, n in enumerate(names):
        base, _, rest = n.partition("[")
        key = norm(base) + ("[" + ",".join(norm(x) for x in rest.rstrip("]").split(",")) + "]" if rest else "")
        idx[key] = i
    return idx, times, V


def main(scen_file, refs, out_file, only=None):
    import os
    if os.environ.get("ALLOW_EXTRA") == "1":
        # prova: accetta anche le leve del foglio assenti dal catalogo della webapp
        import sure_julia.runtime as rt
        rt.parameters = lambda values=None: {**defaults(), **{k: float(v) for k, v in (values or {}).items()}}
    spec = json.loads(Path(scen_file).read_text(encoding="utf-8"))
    params = set(defaults())
    engine = JuliaBackend(ROOT / "sure_native/generated")
    names = [x["name"] for x in engine.export]
    results = []
    t = time.time()
    engine.run_arrays(outputs=names[:1])
    warm = time.time() - t
    print(f"avvio e prima simulazione: {warm:.1f} s", flush=True)
    for sc in spec["scenarios"]:
        if only and sc["id"] not in only:
            continue
        unknown = set(sc["settings"]) - params
        settings = {k: v for k, v in sc["settings"].items() if k in params or os.environ.get("ALLOW_EXTRA") == "1"}
        refid = "base" if sc.get("same_as_base") else sc["id"]
        t = time.time()
        try:
            arrays = engine.run_arrays(settings, names)
            physical = engine.last_physical["pass"]
        except PhysicalInvariantError as e:
            arrays, physical = e.arrays, False
        secs = time.time() - t
        idx, times, V = read_ref(Path(refs) / f"{refid}.ref")
        T = min(len(times), 40)
        worst, missing = {}, 0
        for item in engine.export:
            a = arrays[item["name"]].reshape(40, -1)[:T]
            labels = [[]]
            for d in item["dims"]:
                labels = [l + [c] for l in labels for c in item["coords"][d]]
            key0 = norm(item["name"])
            rows = [idx.get(key0 + ("[" + ",".join(norm(c) for c in l) + "]" if l else "")) for l in labels]
            if any(r is None for r in rows):
                missing += 1
                continue
            ref = V[rows][:, :T].T
            ok = ~np.isnan(ref)
            if not ok.any():
                continue
            scale = max(np.abs(ref[ok]).max(), 1e-12)
            worst[item["name"]] = float(np.abs(a - ref)[ok].max() / scale)
        top = sorted(worst.items(), key=lambda kv: -kv[1])[:8]
        r = {"id": sc["id"], "seconds": secs, "compilation_seconds": engine.last_timing["compilation_seconds"], "physical_pass": physical, "unknown_settings": sorted(unknown),
             "outputs_compared": len(worst), "outputs_without_reference": missing,
             "max_norm_err": max(worst.values()), "worst": top}
        results.append(r)
        print(f"{sc['id']:14s} {secs:5.2f} s fisica {'OK' if physical else 'NO'} uscite {len(worst)} "
              f"max scarto {r['max_norm_err']:.1e} ({top[0][0]})" + (f" leve ignorate {sorted(unknown)}" if unknown else ""), flush=True)
    engine.close()
    Path(out_file).write_text(json.dumps({"warmup_seconds": warm, "scenarios": results}, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(*sys.argv[1:4], set(sys.argv[4].split(",")) if len(sys.argv) > 4 else None)
