"""Riepilogo dei risultati di validate_scenarios.jl (per il rapporto di validazione).

Uso: python summarize.py RESULTS_DIR SCENARIOS.json RUNS.jsonl OUT.md
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

res_dir, scen_file, runs_file, out = map(Path, sys.argv[1:5])
spec = json.loads(scen_file.read_text(encoding="utf-8"))
runs = {json.loads(l)["id"]: json.loads(l) for l in runs_file.read_text(encoding="utf-8").splitlines() if l.strip()}
rows, missing = [], []
for sc in spec["scenarios"]:
    f = res_dir / f"{sc['id']}.json"
    if not f.exists():
        missing.append(sc["id"])
        continue
    rows.append((sc, json.loads(f.read_text(encoding="utf-8"))))

lines = []
P = lines.append
tot = Counter()
inject_nonnoise = []
neg_phys = defaultdict(list)
out_max = defaultdict(float)
for sc, r in rows:
    i, f = r["inject"], r["full"]
    tot["scenari"] += 1
    tot["valori"] += i["values"]
    tot["fuori_inject"] += i["values_out"]
    tot["identici_inject"] += i["identical"]
    tot["identici_full"] += f["identical"]
    tot["fuori_full"] += f["values_out"]
    for w in i["worst_series"]:
        b = w["name"].split("[")[0].strip('"')
        if "check" not in b.lower():
            inject_nonnoise.append((sc["id"], w["name"], w["first_year"], w["max_rel"]))
    for k, v in r["negative_stocks"].items():
        if k != "Cumulative retrofit cost":
            neg_phys[k].append((sc["id"], v))
    for k, v in f["outputs_max_norm_err"].items():
        out_max[k] = max(out_max[k], v)

P(f"Scenari validati: {tot['scenari']} su {len(spec['scenarios'])}" + (f" (mancano: {', '.join(missing)})" if missing else ""))
P(f"Valori confrontati: {tot['valori']:,}")
P(f"Corsa con allocazione Vensim: fuori tolleranza {tot['fuori_inject']:,} ({100*tot['fuori_inject']/max(tot['valori'],1):.4f}%), "
  f"identici bit per bit {100*tot['identici_inject']/max(tot['valori'],1):.1f}%")
P(f"Corsa completa: fuori tolleranza {tot['fuori_full']:,} ({100*tot['fuori_full']/max(tot['valori'],1):.3f}%), "
  f"identici bit per bit {100*tot['identici_full']/max(tot['valori'],1):.1f}%")
P("")
P("| Scenario | Gruppo | Anni | Inject: serie fuori (controlli / altre) | Full: serie fuori | Full: max scarto dispatch | Full: max scarto stock | Full: max scarto uscite |")
P("|---|---|---|---|---|---|---|---|")
for sc, r in rows:
    i, f = r["inject"], r["full"]
    g = i["series_out_by_group"]
    ctrl = g.get("controlli", 0)
    other = i["series_out"] - ctrl
    om = max(f["outputs_max_norm_err"].values()) if f["outputs_max_norm_err"] else 0
    yrs = r.get("compared_years", [2011, 2050])
    trunc = f" (Vensim fermo al {r['vensim_truncated_at']})" if r.get("vensim_truncated_at") else ""
    P(f"| {sc['id']}{' = base' if sc.get('same_as_base') else ''} | {sc['group']} | {yrs[0]}–{yrs[1]}{trunc} | {ctrl} / {other} | "
      f"{f['series_out']} | {f['max_norm_err_by_group'].get('a_valle_allocazione', 0):.1e} | {f['stocks_max_norm_err']:.1e} | {om:.1e} |")
P("")
P("Serie fuori tolleranza nella corsa con allocazione Vensim, escluse le variabili di controllo:")
c = Counter(n.split("[")[0] for _, n, _, _ in inject_nonnoise)
for k, v in c.most_common(20):
    ex = max((x for x in inject_nonnoise if x[1].split("[")[0] == k), key=lambda x: x[3])
    P(f"- {k}: {v} casi; max scarto rel {ex[3]:.2e} ({ex[0]}, {ex[1]}, dal {ex[2]})")
P("")
P("Stock fisici negativi (< -1e-10), esclusi i costi cumulati:")
if not neg_phys:
    P("- nessuno")
for k, lst in neg_phys.items():
    P(f"- {k}: {len(lst)} scenari, es. " + "; ".join(f"{s} julia {v['min_julia']:.3g} vensim {v['min_vensim']:.3g}" for s, v in lst[:5]))
P("")
P("Uscite della webapp e ingressi degli indici di equità: max scarto (rispetto al massimo della serie) sulla corsa completa:")
for k, v in sorted(out_max.items(), key=lambda kv: -kv[1])[:20]:
    P(f"- {k}: {v:.1e}")
setval = {k: v["setval_errors"] for k, v in runs.items() if v.get("setval_errors")}
P("")
P("Controllo delle leve impostate (SETVAL): " + ("tutte applicate" if not setval else json.dumps(setval)))
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines[:6]))
