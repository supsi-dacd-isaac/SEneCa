"""Esporta 10 run di SURE.vpmx in JSON + Parquet, senza file .vdf.

I valori restano leggibili senza licenza Vensim: inputs.json descrive le leve,
outputs.parquet le serie 2011-2050 (nome PySD = variable oppure variable[element]).
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent
PVBAT = ROOT / "pv_batteries"
for p in (str(ROOT), str(PVBAT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import sure_pysd as sp  # noqa: E402
from pv_batteries.elettricita_config import BASE_SCENARIO as ELE_BASE  # noqa: E402
from pv_batteries.pv_batteries_config import BASE_SCENARIO as PV_BASE  # noqa: E402
from pv_batteries.risanamento_config import BASE_SCENARIO as RIS_BASE  # noqa: E402
from pv_batteries.veicoli_config import BASE_SCENARIO as VEI_BASE  # noqa: E402
from pv_batteries.vensim_runner import VensimModel  # noqa: E402
from validate_coherence_sure import EXTRA_OUTPUTS  # noqa: E402

OUT_DIR = ROOT / "Vensim_test_runs"
PARTS_DIR = OUT_DIR / "_parts"
WORK_DIR = OUT_DIR / "_runs"
PARQUET = OUT_DIR / "outputs.parquet"
INPUTS_JSON = OUT_DIR / "inputs.json"
VPMX = ROOT / "Vensim" / "SURE.vpmx"

INITIAL, FINAL, STEP = 2011, 2050, 1
YEARS = list(range(INITIAL, FINAL + 1))

# Ordine stabile: pagine PV, riscaldamento, veicoli, poi i provvedimenti PECC.
INPUT_ORDER = [
    "PV rebate cantonal",
    "FiT",
    "Battery Rebate",
    "PV rebate federal",
    "PV reg scenario",
    "Energy Community scenario",
    "Grant share HP",
    "Grant share PelletBoiler",
    "Grant share DH",
    "Retrofit incentive input",
    "CO2 tax",
    "MuKEn scenario",
    "EV charger incentive input",
    "CO2 coefficient ICE",
    "EV annual cost reduction input",
    "ICE fuel price input",
    "Provvedimento 1.2",
    "Provvedimento 1.3",
    "Provvedimento 1.4",
    "Provvedimento 1.7",
]

# Non impostate: restano al default del modello pubblicato.
UNSET_LEVERS = {
    "ICE ban year": (
        "Non impostata. Resta al default del modello pubblicato "
        "(2050, nessun divieto effettivo)."
    ),
    "Deflussi minimi LPAc": (
        "Non impostata. Resta al default del modello pubblicato."
    ),
    "Cambiamento climatico Hydro": (
        "Non impostata. Resta al default del modello pubblicato."
    ),
}

BASE: dict[str, float] = {}
for src in (PV_BASE, RIS_BASE, VEI_BASE, ELE_BASE):
    BASE.update(src)
missing = [k for k in INPUT_ORDER if k not in BASE]
if missing or set(BASE) != set(INPUT_ORDER):
    raise RuntimeError(f"Leve Base non allineate a INPUT_ORDER: {missing}")

# (id, nota, override rispetto al Base). Le leve assenti restano al Base.
SCENARIOS: list[tuple[str, str, dict[str, float]]] = [
    ("01_base", "Base di PV, riscaldamento, veicoli ed elettricità.", {}),
    (
        "02_pv_max",
        "Rimborsi PV e batterie al massimo, FiT 0.10, obbligo PV e comunità energetica attivi.",
        {
            "PV rebate cantonal": 0.2,
            "FiT": 0.10,
            "Battery Rebate": 0.5,
            "PV rebate federal": 0.4,
            "PV reg scenario": 1.0,
            "Energy Community scenario": 1.0,
        },
    ),
    (
        "03_pv_min",
        "Tutte le leve PV a zero, incluso l'obbligo.",
        {
            "PV rebate cantonal": 0.0,
            "FiT": 0.0,
            "Battery Rebate": 0.0,
            "PV rebate federal": 0.0,
            "PV reg scenario": 0.0,
            "Energy Community scenario": 0.0,
        },
    ),
    (
        "04_fit_005",
        "Solo FiT 0.05, il valore alto della pagina Elettricità.",
        {"FiT": 0.05},
    ),
    (
        "05_heat_max",
        "Rimborsi 0.4, incentivo risanamento 100, tassa CO2 240, MuKEn 2.",
        {
            "Grant share HP": 0.4,
            "Grant share PelletBoiler": 0.4,
            "Grant share DH": 0.4,
            "Retrofit incentive input": 100.0,
            "CO2 tax": 240.0,
            "MuKEn scenario": 2.0,
        },
    ),
    (
        "06_heat_min",
        "Rimborsi, incentivo e tassa a 0, MuKEn 0.",
        {
            "Grant share HP": 0.0,
            "Grant share PelletBoiler": 0.0,
            "Grant share DH": 0.0,
            "Retrofit incentive input": 0.0,
            "CO2 tax": 0.0,
            "MuKEn scenario": 0.0,
        },
    ),
    (
        "07_vehicles_max",
        "Colonnina 4000, coefficiente ICE 4, riduzione costo EV 0.03, carburante 3.",
        {
            "EV charger incentive input": 4000.0,
            "CO2 coefficient ICE": 4.0,
            "EV annual cost reduction input": 0.03,
            "ICE fuel price input": 3.0,
        },
    ),
    (
        "08_vehicles_min",
        "Colonnina 0, coefficiente ICE 1, riduzione costo EV 0, carburante 2.",
        {
            "EV charger incentive input": 0.0,
            "CO2 coefficient ICE": 1.0,
            "EV annual cost reduction input": 0.0,
            "ICE fuel price input": 2.0,
        },
    ),
    (
        "09_hydro_on",
        "Provvedimenti PECC 1.2, 1.3, 1.4 e 1.7 tutti attivi.",
        {
            "Provvedimento 1.2": 1.0,
            "Provvedimento 1.3": 1.0,
            "Provvedimento 1.4": 1.0,
            "Provvedimento 1.7": 1.0,
        },
    ),
    (
        "10_mixed",
        "FiT 0.05, rimborso PV federale 0.4, comunità energetica, MuKEn 2, "
        "tassa CO2 240, colonnina 4000, carburante 3, provvedimenti 1.2 e 1.3 attivi.",
        {
            "FiT": 0.05,
            "PV rebate federal": 0.4,
            "Energy Community scenario": 1.0,
            "MuKEn scenario": 2.0,
            "CO2 tax": 240.0,
            "EV charger incentive input": 4000.0,
            "ICE fuel price input": 3.0,
            "Provvedimento 1.2": 1.0,
            "Provvedimento 1.3": 1.0,
        },
    ),
]


def scenario_inputs(overrides: dict[str, float]) -> dict[str, float]:
    merged = dict(BASE)
    unknown = [k for k in overrides if k not in merged]
    if unknown:
        raise KeyError(f"Override su leve sconosciute: {unknown}")
    merged.update(overrides)
    return {k: float(merged[k]) for k in INPUT_ORDER}


def output_bases() -> list[str]:
    bases: list[str] = []
    for name in list(sp.OUTPUTS) + list(EXTRA_OUTPUTS):
        if name not in bases:
            bases.append(name)
    return bases


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def split_element(base: str, full: str) -> str:
    """Contenuto delle parentesi finali. Vuoto se la serie è scalare."""
    if full == base:
        return ""
    if full.startswith(base):
        rest = full[len(base):]
        if rest.startswith("[") and rest.endswith("]"):
            return rest[1:-1]
    if full.endswith("]") and "[" in full:
        return full[full.rindex("[") + 1:-1]
    return ""


def quiet_dll(model: VensimModel) -> None:
    """Evita il dialogo modale di Vensim se una simulazione va in errore."""
    dll = model.dll
    dll.vensim_be_quiet.argtypes = [ctypes.c_int]
    dll.vensim_be_quiet.restype = ctypes.c_int
    dll.vensim_be_quiet(2)


def horizon_year(model: VensimModel, run_name: str) -> float:
    t, _v = model.get_series(run_name, "Time", maxn=5000)
    return float(t[-1]) if t else float("nan")


def read_run(model: VensimModel, run_name: str, bases: list[str],
             expand_cache: dict[str, list[str]], years: list[int]) -> tuple[pd.DataFrame, list[str]]:
    variables: list[str] = []
    elements: list[str] = []
    year_col: list[int] = []
    values: list[float] = []
    missing: list[str] = []
    year_set = set(years)
    for base in bases:
        names = expand_cache.get(base) or []
        if not names:
            missing.append(base)
            continue
        for full in names:
            try:
                t, v = model.get_series(run_name, full, maxn=5000)
            except RuntimeError:
                missing.append(full)
                continue
            element = split_element(base, full)
            for ti, vi in zip(t, v):
                yr = int(round(float(ti)))
                if yr not in year_set or abs(float(ti) - yr) > 1e-3:
                    continue
                variables.append(base)
                elements.append(element)
                year_col.append(yr)
                values.append(float(vi))
    df = pd.DataFrame({
        "run_id": run_name,
        "variable": variables,
        "element": elements,
        "year": np.asarray(year_col, dtype=np.int16),
        "value": np.asarray(values, dtype=np.float32),
    })
    return df, missing


def cleanup_run_files(work: Path) -> None:
    if not work.exists():
        return
    for p in work.iterdir():
        if p.suffix.lower() in {".vdf", ".vdfx"}:
            p.unlink(missing_ok=True)


def consolidate(parts: list[Path]) -> int:
    if PARQUET.exists():
        PARQUET.unlink()
    n_rows = 0
    writer = None
    try:
        for fp in parts:
            table = pq.read_table(fp)
            if writer is None:
                writer = pq.ParquetWriter(PARQUET, table.schema)
            else:
                table = table.cast(writer.schema)
            writer.write_table(table)
            n_rows += table.num_rows
            del table
    finally:
        if writer is not None:
            writer.close()
    return n_rows


def main() -> None:
    if not VPMX.is_file():
        raise SystemExit(f"Modello assente: {VPMX}")
    bases = output_bases()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PARTS_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Modello: {VPMX.name}  output: {len(bases)} variabili base", flush=True)
    print("SHA-256 del .vpmx ...", flush=True)
    digest = file_sha256(VPMX)
    print(digest, flush=True)

    model = VensimModel(VPMX, work_dir=WORK_DIR)
    quiet_dll(model)
    model.set_time(initial=INITIAL, final=FINAL, step=STEP)

    expand_cache: dict[str, list[str]] = {}
    for base in bases:
        try:
            expand_cache[base] = model.expand_var(base)
        except Exception as exc:  # noqa: BLE001 - una base illeggibile non blocca le altre
            print(f"  expand fallito per {base}: {exc}", flush=True)
            expand_cache[base] = []
    n_series = sum(len(v) for v in expand_cache.values())
    print(f"Serie da leggere per run: {n_series}", flush=True)

    run_meta = []
    t0 = time.perf_counter()
    for i, (run_id, note, overrides) in enumerate(SCENARIOS, start=1):
        inputs = scenario_inputs(overrides)
        part = PARTS_DIR / f"{run_id}.parquet"
        meta_path = PARTS_DIR / f"{run_id}.json"
        if part.is_file() and meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            run_meta.append(meta)
            print(f"[{i}/10] {run_id} già esportato ({meta['n_rows']} righe)", flush=True)
            continue

        print(f"[{i}/10] {run_id} ...", flush=True)
        t = time.perf_counter()
        model.run(run_id, inputs)
        horizon = horizon_year(model, run_id)
        years = YEARS
        if np.isfinite(horizon) and horizon < FINAL:
            years = [y for y in YEARS if y < horizon]
            print(f"  simulazione interrotta a {horizon}: tengo gli anni fino a {years[-1]}",
                  flush=True)
        df, missing = read_run(model, run_id, bases, expand_cache, years)
        df.to_parquet(part, index=False)
        meta = {
            "id": run_id,
            "note": note,
            "inputs": inputs,
            "horizon": None if not np.isfinite(horizon) else float(horizon),
            "years": [int(years[0]), int(years[-1])] if years else [],
            "n_rows": int(len(df)),
            "n_missing": len(missing),
            "missing_sample": missing[:20],
        }
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        run_meta.append(meta)
        model.clear_runs()
        cleanup_run_files(WORK_DIR)
        print(f"  {len(df):,} righe | mancanti {len(missing)} | "
              f"{time.perf_counter() - t:.1f}s", flush=True)

    n_rows = consolidate([PARTS_DIR / f"{rid}.parquet" for rid, _n, _o in SCENARIOS])
    payload = {
        "model": "Vensim/SURE.vpmx",
        "model_sha256": digest,
        "model_bytes": VPMX.stat().st_size,
        "initial_time": INITIAL,
        "final_time": FINAL,
        "time_step": STEP,
        "value_dtype": "float32",
        "value_note": (
            "I valori sono quelli restituiti da vendll64.dll in float32 "
            "e sono salvati come float32. FiT è in CHF/kWh (0.05 = 5 Rp/kWh)."
        ),
        "unset_levers": UNSET_LEVERS,
        "output_bases": bases,
        "parquet": {
            "file": "outputs.parquet",
            "columns": ["run_id", "variable", "element", "year", "value"],
            "name_rule": (
                "Il nome PySD corrispondente è `variable` se element è vuoto, "
                "altrimenti `variable[element]`."
            ),
            "n_rows": n_rows,
        },
        "runs": run_meta,
    }
    INPUTS_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    # VensimModel cambia la cwd sulla cartella di lavoro: da lì Windows non
    # lascia cancellare la directory stessa.
    os.chdir(ROOT)
    shutil.rmtree(PARTS_DIR, ignore_errors=True)
    shutil.rmtree(WORK_DIR, ignore_errors=True)
    print(f"Scritti {INPUTS_JSON.name} e {PARQUET.name} ({n_rows:,} righe) "
          f"in {(time.perf_counter() - t0) / 60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
