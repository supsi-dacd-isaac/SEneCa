"""Motore generico di pre-calcolo per una sezione del modello SURE.

Parametrizzato da un modulo di config (es. risanamento_config) che espone:
    VPMX, YEARS, FINAL_YEAR, INPUT_GRID, INPUT_ORDER, OUTPUT_BASES,
    GMD_SPEC, GMD_VARS, STORE_DIR, CONSOLIDATED_TRAJ, CONSOLIDATED_GMD,
    RUN_NAME, SECTION

Riusa vensim_runner (harness Vensim nativo) e la logica resumable + restart
preventivo gia' collaudata sulla sezione 1. A fine batch (consolidamento
riuscito) puo' rimuovere i file per-combo (cleanup) per non lasciare migliaia
di file piccoli.
"""
from __future__ import annotations

import argparse
import gc
import itertools
import json
import os
import shutil
import sys
import time
from datetime import datetime

import numpy as np
import pandas as pd

from gmd import compute_gmd_from_spec
from vensim_runner import VensimModel

MAXN = 5000  # serie annuali (40 punti): buffer ampio ma leggero
RELAUNCH_CODE = 75


def combo_key(combo) -> str:
    return "_".join(f"{float(v):g}" for v in combo)


def _all_combos(cfg):
    grids = [cfg.INPUT_GRID[name] for name in cfg.INPUT_ORDER]
    return [tuple(round(float(v), 4) for v in combo)
            for combo in itertools.product(*grids)]


def _combo_inputs(cfg, combo):
    return {name: val for name, val in zip(cfg.INPUT_ORDER, combo)}


def _series_to_year_map(t, v, year_list):
    out = {}
    ta = np.asarray(t, dtype=float)
    va = np.asarray(v, dtype=float)
    for yr in year_list:
        idx = np.where(np.isclose(ta, yr))[0]
        if len(idx):
            out[yr] = float(va[idx[0]])
    return out


def _read_trajectories(model, cfg, expand_cache, year_list):
    cols = {}
    for base in cfg.OUTPUT_BASES:
        for full in expand_cache[base]:
            t, v = model.get_series(cfg.RUN_NAME, full, maxn=MAXN)
            ymap = _series_to_year_map(t, v, year_list)
            cols[full] = [ymap.get(yr, np.nan) for yr in year_list]
    return pd.DataFrame(cols, index=pd.Index(year_list, name="Time"))


def _read_gmd_2050(model, cfg, expand_cache):
    values_2050 = {}
    for base in cfg.GMD_VARS:
        per_combo = {}
        for full in expand_cache[base]:
            t, v = model.get_series(cfg.RUN_NAME, full, maxn=MAXN)
            ta = np.asarray(t, dtype=float)
            va = np.asarray(v, dtype=float)
            idx = np.where(np.isclose(ta, cfg.FINAL_YEAR))[0]
            if len(idx):
                sub = full[len(base) + 1:-1] if full != base else ""
                per_combo[sub] = float(va[idx[0]])
        values_2050[base] = per_combo
    return compute_gmd_from_spec(values_2050, cfg.GMD_SPEC)


def _build_expand_cache(model, cfg):
    cache = {}
    for base in list(cfg.OUTPUT_BASES) + list(cfg.GMD_VARS):
        if base not in cache:
            cache[base] = model.expand_var(base)
    return cache


def _write_progress(progress_file, done, total, current, processed, t0):
    elapsed = time.perf_counter() - t0
    rate = processed / elapsed if elapsed else 0
    eta = (total - done) / rate if rate else 0
    payload = {
        "done": done, "total": total, "current": current,
        "elapsed_min": round(elapsed / 60, 2),
        "eta_min": round(eta / 60, 2),
        "updated": datetime.now().isoformat(timespec="seconds"),
    }
    progress_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"[{done}/{total}] {current} | elapsed {elapsed/60:.1f} min | "
          f"ETA {eta/60:.1f} min", flush=True)


def _consolidate(cfg, traj_dir, gmd_dir):
    traj_files = sorted(traj_dir.glob("*.parquet"))
    gmd_files = sorted(gmd_dir.glob("*.parquet"))
    if not traj_files:
        raise SystemExit("Nessuna traiettoria da consolidare in " + str(traj_dir))
    alltraj = pd.concat([pd.read_parquet(fp) for fp in traj_files],
                        ignore_index=True)
    alltraj.to_parquet(cfg.CONSOLIDATED_TRAJ)
    print(f"Consolidate {len(traj_files)} traiettorie -> {cfg.CONSOLIDATED_TRAJ} "
          f"({len(alltraj):,} righe)")
    if gmd_files:
        allgmd = pd.concat([pd.read_parquet(fp) for fp in gmd_files],
                           ignore_index=True)
        allgmd.to_parquet(cfg.CONSOLIDATED_GMD)
        print(f"Consolidate {len(gmd_files)} GMD -> {cfg.CONSOLIDATED_GMD} "
              f"({len(allgmd):,} righe)")
    return len(traj_files), len(gmd_files)


def _cleanup(cfg):
    """Rimuove i file per-combo dopo un consolidamento riuscito."""
    if cfg.STORE_DIR.exists():
        shutil.rmtree(cfg.STORE_DIR, ignore_errors=True)
    print(f"Cleanup: rimossi i file per-combo in {cfg.STORE_DIR}")


def run_cli(cfg):
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="processa al piu' N combo (0 = tutte)")
    ap.add_argument("--restart-every", type=int, default=100,
                    help="riavvia il processo ogni N combo (0 = mai)")
    ap.add_argument("--consolidate-only", action="store_true")
    ap.add_argument("--no-consolidate", action="store_true")
    ap.add_argument("--keep-parts", action="store_true",
                    help="non eliminare i file per-combo dopo il consolidamento")
    args = ap.parse_args()

    year_list = list(cfg.YEARS)
    traj_dir = cfg.STORE_DIR / "traj"
    gmd_dir = cfg.STORE_DIR / "gmd"
    progress_file = cfg.STORE_DIR / "_progress.json"
    restarts = int(os.environ.get("SECTION_RESTARTS", "0"))

    cfg.STORE_DIR.mkdir(parents=True, exist_ok=True)
    traj_dir.mkdir(parents=True, exist_ok=True)
    gmd_dir.mkdir(parents=True, exist_ok=True)

    if args.consolidate_only:
        _consolidate(cfg, traj_dir, gmd_dir)
        return

    combos = _all_combos(cfg)
    total = len(combos)
    has_gmd = bool(cfg.GMD_VARS)

    def _combo_done(c):
        if not (traj_dir / f"{combo_key(c)}.parquet").exists():
            return False
        if has_gmd and not (gmd_dir / f"{combo_key(c)}.parquet").exists():
            return False
        return True

    pending = [c for c in combos if not _combo_done(c)]
    already_done = total - len(pending)
    if args.limit:
        pending = pending[:args.limit]

    print(f"[{cfg.SECTION}] Combo totali: {total} | gia' fatte: {already_done} | "
          f"da calcolare: {len(pending)} | restart#{restarts}", flush=True)

    def finish():
        if not args.no_consolidate:
            nt, ng = _consolidate(cfg, traj_dir, gmd_dir)
            gmd_ok = (not has_gmd) or (ng >= total)
            if not args.keep_parts and nt >= total and gmd_ok:
                _cleanup(cfg)

    if not pending:
        print("Tutte le combo gia' calcolate.")
        finish()
        return

    model = VensimModel(cfg.VPMX, work_dir=cfg.STORE_DIR / "_runs")
    model.set_time(initial=year_list[0], final=year_list[-1], step=1)
    expand_cache = _build_expand_cache(model, cfg)
    print("Colonne output espanse:",
          sum(len(expand_cache[b]) for b in cfg.OUTPUT_BASES),
          "| elementi GMD:", {b: len(expand_cache[b]) for b in cfg.GMD_VARS},
          flush=True)

    def process_one(key, inputs):
        model.run(cfg.RUN_NAME, inputs)
        traj = _read_trajectories(model, cfg, expand_cache, year_list).reset_index()
        for name, val in inputs.items():
            traj[name] = val
        traj.to_parquet(traj_dir / f"{key}.parquet")
        if has_gmd:
            gmd_vals = _read_gmd_2050(model, cfg, expand_cache)
            gmd_row = {**inputs, **gmd_vals, "year": cfg.FINAL_YEAR}
            pd.DataFrame([gmd_row]).to_parquet(gmd_dir / f"{key}.parquet")

    t0 = time.perf_counter()
    n_pending = len(pending)
    for i, combo in enumerate(pending, start=1):
        key = combo_key(combo)
        inputs = _combo_inputs(cfg, combo)
        try:
            process_one(key, inputs)
        except OSError as e:
            print(f"OSError su {key}: {e} -> rilancio processo fresco",
                  flush=True)
            try:
                model.clear_runs()
            except Exception:
                pass
            sys.exit(RELAUNCH_CODE)

        _write_progress(progress_file, already_done + i, total, key, i, t0)
        model.clear_runs()
        if i % 10 == 0:
            gc.collect()

        if args.restart_every and i >= args.restart_every and i < n_pending:
            print(f"Restart preventivo dopo {i} combo (restart#{restarts+1})",
                  flush=True)
            sys.exit(RELAUNCH_CODE)

    print(f"\nCompletato in {(time.perf_counter()-t0)/60:.1f} min", flush=True)
    finish()
