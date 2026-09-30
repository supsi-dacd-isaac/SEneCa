"""Pre-calcolo delle 486 combinazioni "PV e Batterie" col modello nativo Vensim.

Usa SURE.vpmx tramite la DLL (vensim_runner) -> molto piu' veloce di PySD.
Per ogni combinazione salva:
- la traiettoria 2011-2050 di tutti gli output (subscript espansi) in
  precomputed/pv_batteries/traj/<key>.parquet
- le misure di equity gmd_cost/gmd_levy al 2050 in
  precomputed/pv_batteries/gmd/<key>.parquet
Resumable: le combo gia' presenti vengono saltate. Alla fine consolida in
precomputed/pv_batteries_scenarios.parquet e precomputed/pv_batteries_gmd.parquet.

Esempi:
    # test veloce (3 combo)
    .\\.venv\\Scripts\\python.exe pv_batteries\\precompute_pv_batteries.py --limit 3
    # batch completo
    .\\.venv\\Scripts\\python.exe pv_batteries\\precompute_pv_batteries.py
    # solo consolidamento
    .\\.venv\\Scripts\\python.exe pv_batteries\\precompute_pv_batteries.py --consolidate-only
"""
from __future__ import annotations

import argparse
import gc
import itertools
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
for p in (str(ROOT), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from pv_batteries_config import (  # noqa: E402
    FINAL_YEAR, GMD_VARS, INPUT_GRID, INPUT_ORDER, OUTPUT_BASES, STORE_DIR,
    VPMX, YEARS,
)
from gmd import compute_gmd_measures  # noqa: E402
from vensim_runner import VensimModel  # noqa: E402

TRAJ_DIR = STORE_DIR / "traj"
GMD_DIR = STORE_DIR / "gmd"
PROGRESS_FILE = STORE_DIR / "_progress.json"
CONSOLIDATED_TRAJ = ROOT / "precomputed" / "pv_batteries_scenarios.parquet"
CONSOLIDATED_GMD = ROOT / "precomputed" / "pv_batteries_gmd.parquet"

RUN_NAME = "pvbat"
YEAR_LIST = list(YEARS)
MAXN = 5000  # serie annuali (40 punti): buffer ampio ma leggero


def all_combos() -> list[tuple[float, ...]]:
    grids = [INPUT_GRID[name] for name in INPUT_ORDER]
    return [tuple(round(float(v), 4) for v in combo)
            for combo in itertools.product(*grids)]


def combo_inputs(combo: tuple[float, ...]) -> dict[str, float]:
    return {name: val for name, val in zip(INPUT_ORDER, combo)}


def combo_key(combo: tuple[float, ...]) -> str:
    return "_".join(f"{v:g}" for v in combo)


def _series_to_year_map(t, v) -> dict[int, float]:
    out = {}
    ta = np.asarray(t, dtype=float)
    va = np.asarray(v, dtype=float)
    for yr in YEAR_LIST:
        idx = np.where(np.isclose(ta, yr))[0]
        if len(idx):
            out[yr] = float(va[idx[0]])
    return out


def read_trajectories(model, expand_cache: dict) -> pd.DataFrame:
    """DataFrame (indice = anni 2011-2050) con tutti gli output subscript-espansi."""
    cols = {}
    for base in OUTPUT_BASES:
        for full in expand_cache[base]:
            t, v = model.get_series(RUN_NAME, full, maxn=MAXN)
            ymap = _series_to_year_map(t, v)
            cols[full] = [ymap.get(yr, np.nan) for yr in YEAR_LIST]
    df = pd.DataFrame(cols, index=pd.Index(YEAR_LIST, name="Time"))
    return df


def read_gmd_2050(model, expand_cache: dict) -> dict[str, float]:
    """Valori 2050 per subscript delle variabili GMD -> misure di equity."""
    values_2050: dict[str, dict[str, float]] = {}
    for base in GMD_VARS:
        per_combo = {}
        for full in expand_cache[base]:
            t, v = model.get_series(RUN_NAME, full, maxn=MAXN)
            ta = np.asarray(t, dtype=float)
            va = np.asarray(v, dtype=float)
            idx = np.where(np.isclose(ta, FINAL_YEAR))[0]
            if len(idx):
                sub = full[len(base) + 1:-1] if full != base else ""
                per_combo[sub] = float(va[idx[0]])
        values_2050[base] = per_combo
    return compute_gmd_measures(values_2050)


def build_expand_cache(model) -> dict:
    """Espansione subscript (una volta): base_var -> lista nomi completi."""
    cache = {}
    for base in list(OUTPUT_BASES) + list(GMD_VARS):
        if base not in cache:
            cache[base] = model.expand_var(base)
    return cache


def write_progress(done, total, current, processed, t0):
    """Progresso GLOBALE (done/total sull'intera griglia da 486).

    Il rate/ETA usano i combo processati IN QUESTO processo (processed) per
    restare accurati anche dopo un auto-restart.
    """
    elapsed = time.perf_counter() - t0
    rate = processed / elapsed if elapsed else 0
    eta = (total - done) / rate if rate else 0
    payload = {
        "done": done,
        "total": total,
        "current": current,
        "elapsed_min": round(elapsed / 60, 2),
        "eta_min": round(eta / 60, 2),
        "updated": datetime.now().isoformat(timespec="seconds"),
    }
    PROGRESS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"[{done}/{total}] {current} | elapsed {elapsed/60:.1f} min | "
          f"ETA {eta/60:.1f} min", flush=True)


def consolidate():
    traj_files = sorted(TRAJ_DIR.glob("*.parquet"))
    gmd_files = sorted(GMD_DIR.glob("*.parquet"))
    if not traj_files:
        raise SystemExit("Nessuna traiettoria da consolidare in " + str(TRAJ_DIR))
    frames = [pd.read_parquet(fp) for fp in traj_files]
    alltraj = pd.concat(frames, ignore_index=True)
    alltraj.to_parquet(CONSOLIDATED_TRAJ)
    print(f"Consolidate {len(traj_files)} traiettorie -> {CONSOLIDATED_TRAJ} "
          f"({len(alltraj):,} righe)")
    if gmd_files:
        allgmd = pd.concat([pd.read_parquet(fp) for fp in gmd_files],
                           ignore_index=True)
        allgmd.to_parquet(CONSOLIDATED_GMD)
        print(f"Consolidate {len(gmd_files)} GMD -> {CONSOLIDATED_GMD} "
              f"({len(allgmd):,} righe)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="processa al piu' N combo (0 = tutte)")
    ap.add_argument("--restart-every", type=int, default=100,
                    help="riavvia il processo ogni N combo (0 = mai) per "
                         "liberare handle/memoria della DLL")
    ap.add_argument("--consolidate-only", action="store_true")
    ap.add_argument("--no-consolidate", action="store_true")
    args = ap.parse_args()

    # Codice di uscita che segnala al wrapper esterno di rilanciare un processo
    # fresco (resetta handle/memoria della DLL). La ripresa e' resumable.
    RELAUNCH_CODE = 75
    restarts = int(os.environ.get("PVBAT_RESTARTS", "0"))

    STORE_DIR.mkdir(parents=True, exist_ok=True)
    TRAJ_DIR.mkdir(parents=True, exist_ok=True)
    GMD_DIR.mkdir(parents=True, exist_ok=True)

    if args.consolidate_only:
        consolidate()
        return

    combos = all_combos()
    total = len(combos)
    # Una combo e' "fatta" solo se ESISTONO ENTRAMBI i file (traiettoria + GMD):
    # evita di saltare combo con traiettoria salvata ma GMD non ancora scritto.
    pending = [c for c in combos
               if not ((TRAJ_DIR / f"{combo_key(c)}.parquet").exists()
                       and (GMD_DIR / f"{combo_key(c)}.parquet").exists())]
    already_done = total - len(pending)
    if args.limit:
        pending = pending[:args.limit]

    print(f"Combo totali: {total} | gia' fatte: {already_done} | "
          f"da calcolare: {len(pending)} | restart#{restarts}", flush=True)
    if not pending:
        print("Tutte le combo gia' calcolate.")
        if not args.no_consolidate:
            consolidate()
        return

    model = VensimModel(VPMX, work_dir=STORE_DIR / "_runs")
    model.set_time(initial=YEAR_LIST[0], final=YEAR_LIST[-1], step=1)
    expand_cache = build_expand_cache(model)
    ndims = {b: len(expand_cache[b]) for b in expand_cache}
    print("Colonne output espanse:",
          sum(ndims[b] for b in OUTPUT_BASES),
          "| elementi GMD:", {b: ndims[b] for b in GMD_VARS}, flush=True)

    def process_one(combo, key, inputs):
        model.run(RUN_NAME, inputs)
        traj = read_trajectories(model, expand_cache).reset_index()
        for name, val in inputs.items():
            traj[name] = val
        traj.to_parquet(TRAJ_DIR / f"{key}.parquet")
        gmd_vals = read_gmd_2050(model, expand_cache)
        gmd_row = {**inputs, **gmd_vals, "year": FINAL_YEAR}
        pd.DataFrame([gmd_row]).to_parquet(GMD_DIR / f"{key}.parquet")

    t0 = time.perf_counter()
    n_pending = len(pending)
    for i, combo in enumerate(pending, start=1):
        key = combo_key(combo)
        inputs = combo_inputs(combo)
        try:
            process_one(combo, key, inputs)
        except OSError as e:
            # Errore di risorse di sistema (es. WinError 1450): esci con codice
            # di rilancio; il wrapper riparte con un processo fresco (resumable).
            print(f"OSError su {key}: {e} -> rilancio processo fresco",
                  flush=True)
            try:
                model.clear_runs()
            except Exception:
                pass
            sys.exit(RELAUNCH_CODE)

        write_progress(already_done + i, total, key, i, t0)

        model.clear_runs()
        if i % 10 == 0:
            gc.collect()

        # Riavvio preventivo: se restano ancora combo, chiedi un processo fresco.
        if args.restart_every and i >= args.restart_every and i < n_pending:
            print(f"Restart preventivo dopo {i} combo (restart#{restarts+1})",
                  flush=True)
            sys.exit(RELAUNCH_CODE)

    print(f"\nCompletato in {(time.perf_counter()-t0)/60:.1f} min", flush=True)
    if not args.no_consolidate:
        consolidate()


if __name__ == "__main__":
    main()
