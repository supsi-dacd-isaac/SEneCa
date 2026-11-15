"""Scenari del riferimento Vensim per la validazione Vensim–Julia.

Fonte delle leve: foglio "Input" di Input and Output Streamlit.xlsx (copia
datata passata in argomento). Fonte delle incertezze: foglio "Exploratory
analysis", con i campioni LHS riproducibili di pv_batteries.exploratory_config
(100 campioni, seed 20261004; qui i primi 30).

Gruppi (piano, sezione 8):
  calibration  2011–2025, valori del modello e file di calibrazione
  base         2011–2050, tutte le leve al valore Base del foglio
  extreme      tutte le leve al minimo / al massimo
  oat          una leva alla volta al minimo e al massimo, le altre al Base
  lhs          campione LHS i (0–29) con il mix di policy esplorativo
               POLICY_COMBOS[(37 * i) % 128] e l'interruttore Exploratory analysis = 1

Uso: python define_scenarios.py INPUT.xlsx OUT.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import openpyxl

ROOT = Path(r"C:\Users\matteo.palucci\SEneCa-v8")
sys.path.insert(0, str(ROOT))
from pv_batteries import exploratory_config as exp  # noqa: E402

N_LHS = 30


def read_levers(xlsx: Path) -> list[dict]:
    ws = openpyxl.load_workbook(xlsx, data_only=True)["Input"]
    rows = list(ws.iter_rows(values_only=True))
    head = [str(h).strip() if h else "" for h in rows[0]]
    col = {h: i for i, h in enumerate(head)}
    levers: dict[str, dict] = {}
    for r in rows[1:]:
        name = r[col["Variable name"]]
        if not name or r[col["Min"]] is None:
            continue
        name = str(name).strip()
        lo, hi, base = float(r[col["Min"]]), float(r[col["Max"]]), float(r[col["Base"]])
        # unità del foglio -> unità del modello (FiT: ct./kWh nel foglio, CHF/kWh nel modello)
        unit = str(r[col[next(h for h in col if h.startswith("Unit"))]] or "").strip()
        if unit.startswith("ct"):
            lo, hi, base = lo / 100, hi / 100, base / 100
        if name in levers:  # stessa variabile in più pagine (FiT): intervallo più ampio
            prev = levers[name]
            if prev["base"] != base:
                raise ValueError(f"Base diversi per {name}")
            prev["min"], prev["max"] = min(prev["min"], lo), max(prev["max"], hi)
            continue
        levers[name] = {"name": name, "min": lo, "max": hi, "base": base}
    return list(levers.values())


def main(xlsx: Path, out: Path) -> None:
    levers = read_levers(xlsx)
    base = {lv["name"]: lv["base"] for lv in levers}
    scenarios = [
        {"id": "calibration", "group": "calibration", "final_time": 2025, "settings": {}, "full": True},
        {"id": "base", "group": "base", "final_time": 2050, "settings": dict(base), "full": True},
        {"id": "all_min", "group": "extreme", "final_time": 2050,
         "settings": {lv["name"]: lv["min"] for lv in levers}, "full": True},
        {"id": "all_max", "group": "extreme", "final_time": 2050,
         "settings": {lv["name"]: lv["max"] for lv in levers}, "full": True},
    ]
    for k, lv in enumerate(levers):
        for side in ("min", "max"):
            s = dict(base)
            s[lv["name"]] = lv[side]
            scenarios.append({"id": f"oat_{k:02d}_{side}", "group": "oat", "final_time": 2050,
                              "settings": s, "full": False, "lever": lv["name"],
                              "same_as_base": lv[side] == lv["base"]})
    samples = exp.load_or_create_samples()
    combos = exp.all_policy_combos()
    for i in range(N_LHS):
        s = dict(base)
        s.update(combos[(37 * i) % len(combos)])
        s.update({k: float(samples.loc[i, k]) for k in exp.UNCERTAINTY_ORDER})
        s[exp.EXPLORATORY_SWITCH] = 1.0
        scenarios.append({"id": f"lhs_{i:02d}", "group": "lhs", "final_time": 2050, "settings": s,
                          "full": False, "sample_id": i, "policy_combo": (37 * i) % len(combos)})
    out.write_text(json.dumps({"source": xlsx.name, "levers": levers, "scenarios": scenarios},
                              indent=1, ensure_ascii=False), encoding="utf-8")
    groups: dict[str, int] = {}
    for s in scenarios:
        groups[s["group"]] = groups.get(s["group"], 0) + 1
    dup = sum(1 for s in scenarios if s.get("same_as_base"))
    print(f"{len(levers)} leve, {len(scenarios)} scenari {groups}; OAT uguali al Base: {dup}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
