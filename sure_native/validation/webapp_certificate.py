"""Certificato del build nativo per sure_julia/batch.py.

Prove richieste (come sure_julia/validation.py per il build PySD):
  - validazione Vensim–Julia sui 76 scenari (validate_scenarios.jl, risultati JSON);
  - lo stesso modello passato dal worker della webapp (webapp_check.py): controlli
    fisici superati e scarti mai oltre quelli della validazione;
  - isolamento dello stato: base -> all_max -> base identico, nessuna compilazione
    dopo il riscaldamento, richieste concorrenti, ripresa dopo l'arresto del worker,
    nuovo processo identico.

Uso: python -m sure_native.validation.webapp_certificate SCEN_DIR OUT_DIR
SCEN_DIR contiene scenarios.json, results/, summary.md, webapp_check_all.json.
"""
import json
import shutil
import sys
import threading
from pathlib import Path

import numpy as np

from sure_julia.common import ROOT, digest, dump, identity, read
from sure_julia.runtime import JuliaBackend

BUILD = ROOT / "sure_native/generated"


def exact(a, b):
    return set(a) == set(b) and all(np.array_equal(a[n], b[n]) for n in a)


def repeats(spec):
    sc = {s["id"]: s for s in spec["scenarios"]}
    from sure_julia.catalog import defaults
    known = set(defaults())
    base = {k: v for k, v in sc["base"]["settings"].items() if k in known}
    high = {k: v for k, v in sc["all_max"]["settings"].items() if k in known}
    engine = JuliaBackend(BUILD, timeout=900)
    r = {}
    try:
        engine.run_arrays()                       # riscaldamento con tutte le uscite
        first = engine.run_arrays(base)
        r["warm_no_compilation"] = engine.last_timing["compilation_seconds"] == 0
        h = engine.run_arrays(high)
        again = engine.run_arrays(base)
        r["base_high_base_exact"] = exact(first, again) and not exact(first, h)
        out = {}
        threads = [threading.Thread(target=lambda k, p: out.__setitem__(k, engine.run_arrays(p)), args=(k, p))
                   for k, p in (("base", base), ("high", high))]
        [t.start() for t in threads]; [t.join() for t in threads]
        r["concurrent_isolation"] = exact(out["base"], first) and exact(out["high"], h)
        engine.process.kill(); engine.process.wait()
        r["crash_recovery_exact"] = exact(engine.run_arrays(base), first)
    finally:
        engine.close()
    fresh = JuliaBackend(BUILD, timeout=900)
    try:
        r["fresh_exact"] = exact(fresh.run_arrays(base), first)
    finally:
        fresh.close()
    return r


def main(scen_dir, out_dir):
    scen_dir, out_dir = Path(scen_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    spec = json.loads((scen_dir / "scenarios.json").read_text(encoding="utf-8"))
    ids = [s["id"] for s in spec["scenarios"]]
    check = read(scen_dir / "webapp_check_all.json")["scenarios"]
    problems = []
    if sorted(r["id"] for r in check) != sorted(ids):
        problems.append("prova della webapp incompleta")
    for r in check:
        v = read(scen_dir / "results" / f"{r['id']}.json")
        bound = max(v["full"]["max_norm_err_by_group"].values())
        if not r["physical_pass"]:
            problems.append(f"{r['id']}: controlli fisici")
        if r["max_norm_err"] > bound * 1.01 + 1e-9:
            problems.append(f"{r['id']}: scarto {r['max_norm_err']:.2e} oltre la validazione {bound:.2e}")
    for name in ["scenarios.json", "summary.md", "webapp_check_all.json"]:
        shutil.copy2(scen_dir / name, out_dir / name)
    shutil.copytree(scen_dir / "results", out_dir / "results", dirs_exist_ok=True)
    dump(out_dir / "manifest.json", {"build": digest(BUILD / "build.json"), "scenarios": ids,
                                     "reference": "Vensim DSS, 76 scenari (sure_native/validation)"})
    rep = repeats(spec)
    dump(out_dir / "repeats.json", {"pass": all(rep.values()), "results": {"julia": rep}})
    if not all(rep.values()):
        problems.append(f"isolamento dello stato: {rep}")
    evidence = {p.relative_to(out_dir).as_posix(): digest(p) for p in sorted(out_dir.rglob("*"))
                if p.is_file() and p.name != "certificate.json"}
    cert = {"pass": not problems, "complete_suite": len(check) == len(ids), "problems": problems,
            "build": digest(BUILD / "build.json"), "evidence": evidence,
            "identity": identity(read(out_dir / "manifest.json"))}
    dump(out_dir / "certificate.json", cert)
    print(json.dumps({"pass": cert["pass"], "problems": problems, "repeats": rep}, indent=1))


if __name__ == "__main__":
    main(*sys.argv[1:3])
