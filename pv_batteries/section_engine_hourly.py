"""Motore pre-calcolo per output orari [Month,Hour,(Supplier)].

Salva formato long: variable, month, hour, supplier, year, value + colonne input.
"""
from __future__ import annotations

import argparse
import gc
import itertools
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from vensim_runner import VensimModel

MAXN = 5000
RELAUNCH_CODE = 75


def combo_key(combo) -> str:
    return "_".join(f"{float(v):g}" for v in combo)


def _all_combos(cfg):
    grids = [cfg.INPUT_GRID[name] for name in cfg.INPUT_ORDER]
    return [tuple(round(float(v), 4) for v in combo)
            for combo in itertools.product(*grids)]


def _combo_inputs(cfg, combo):
    return {name: val for name, val in zip(cfg.INPUT_ORDER, combo)}


def _parse_dims(base: str, full: str) -> tuple[str, str, str]:
    """Estrae (month, hour, supplier) da 'base[M1,H1,Solar]'."""
    if full == base:
        return "", "", ""
    m = re.match(re.escape(base) + r"\[(.*)\]$", full)
    if not m:
        return "", "", ""
    parts = [p.strip() for p in m.group(1).split(",")]
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    if len(parts) == 2:
        return parts[0], parts[1], ""
    return "", "", ""


def _series_to_year_map(t, v, year_list):
    out = {}
    ta = np.asarray(t, dtype=float)
    va = np.asarray(v, dtype=float)
    for yr in year_list:
        idx = np.where(np.isclose(ta, yr))[0]
        if len(idx):
            out[yr] = float(va[idx[0]])
    return out


def _read_hourly_long(model, cfg, expand_cache, year_list) -> pd.DataFrame:
    rows = []
    for base in cfg.OUTPUT_BASES:
        for full in expand_cache[base]:
            month, hour, supplier = _parse_dims(base, full)
            t, v = model.get_series(cfg.RUN_NAME, full, maxn=MAXN)
            ymap = _series_to_year_map(t, v, year_list)
            for yr, val in ymap.items():
                rows.append({
                    "variable": base,
                    "month": month,
                    "hour": hour,
                    "supplier": supplier,
                    "year": int(yr),
                    "value": val,
                })
    return pd.DataFrame(rows)


def _build_expand_cache(model, cfg):
    cache = {}
    for base in cfg.OUTPUT_BASES:
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


def _consolidate(cfg, hourly_dir) -> int:
    """Concatena i parquet per-combo in streaming.

    Con centinaia di combo lo store supera i 200 milioni di righe: si scrive un
    row group per file invece di tenere tutto in memoria. Ogni combo resta in un
    row group distinto, cosi' i filtri per input della webapp restano selettivi.
    """
    files = sorted(hourly_dir.glob("*.parquet"))
    if not files:
        raise SystemExit("Nessun file hourly da consolidare in " + str(hourly_dir))

    n_rows = 0
    combo_rows = []
    writer = None
    try:
        for fp in files:
            table = pq.read_table(fp)
            if writer is None:
                writer = pq.ParquetWriter(cfg.CONSOLIDATED_HOURLY, table.schema)
            else:
                table = table.cast(writer.schema)
            writer.write_table(table)
            n_rows += table.num_rows
            combo_rows.append(
                {c: table.column(c)[0].as_py() for c in cfg.INPUT_ORDER})
            del table
    finally:
        if writer is not None:
            writer.close()

    print(f"Consolidate {len(files)} combo -> {cfg.CONSOLIDATED_HOURLY} "
          f"({n_rows:,} righe)")
    index_path = getattr(cfg, "CONSOLIDATED_COMBO_INDEX", None)
    if index_path is not None:
        combo_idx = pd.DataFrame(combo_rows, columns=cfg.INPUT_ORDER)
        combo_idx = combo_idx.drop_duplicates()
        combo_idx.to_parquet(index_path, index=False)
        print(f"Indice combo -> {index_path} ({len(combo_idx):,} righe)")
    return len(files)


def _cleanup(cfg):
    if cfg.STORE_DIR.exists():
        shutil.rmtree(cfg.STORE_DIR, ignore_errors=True)
    print(f"Cleanup: rimossi i file per-combo in {cfg.STORE_DIR}")


def run_cli(cfg):
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--restart-every", type=int, default=50,
                    help="restart ogni N combo (lettura oraria intensiva)")
    ap.add_argument("--consolidate-only", action="store_true")
    ap.add_argument("--no-consolidate", action="store_true")
    ap.add_argument("--keep-parts", action="store_true")
    args = ap.parse_args()

    year_list = list(cfg.YEARS)
    hourly_dir = cfg.STORE_DIR / "hourly"
    progress_file = cfg.STORE_DIR / "_progress.json"
    restarts = int(os.environ.get("SECTION_RESTARTS", "0"))

    cfg.STORE_DIR.mkdir(parents=True, exist_ok=True)
    hourly_dir.mkdir(parents=True, exist_ok=True)

    if args.consolidate_only:
        _consolidate(cfg, hourly_dir)
        return

    combos = _all_combos(cfg)
    total = len(combos)
    pending = [c for c in combos
               if not (hourly_dir / f"{combo_key(c)}.parquet").exists()]
    already_done = total - len(pending)
    if args.limit:
        pending = pending[:args.limit]

    print(f"[{cfg.SECTION}] Combo totali: {total} | gia' fatte: {already_done} | "
          f"da calcolare: {len(pending)} | restart#{restarts}", flush=True)

    def finish():
        if not args.no_consolidate:
            n = _consolidate(cfg, hourly_dir)
            if not args.keep_parts and n >= total:
                _cleanup(cfg)

    if not pending:
        print("Tutte le combo gia' calcolate.")
        finish()
        return

    model = VensimModel(cfg.VPMX, work_dir=cfg.STORE_DIR / "_runs")
    model.set_time(initial=year_list[0], final=year_list[-1], step=1)
    expand_cache = _build_expand_cache(model, cfg)
    n_series = sum(len(expand_cache[b]) for b in cfg.OUTPUT_BASES)
    print(f"Serie orarie per combo: {n_series}", flush=True)

    def process_one(key, inputs):
        model.run(cfg.RUN_NAME, inputs)
        long_df = _read_hourly_long(model, cfg, expand_cache, year_list)
        for name, val in inputs.items():
            long_df[name] = val
        long_df.to_parquet(hourly_dir / f"{key}.parquet")

    t0 = time.perf_counter()
    n_pending = len(pending)
    for i, combo in enumerate(pending, start=1):
        key = combo_key(combo)
        inputs = _combo_inputs(cfg, combo)
        try:
            process_one(key, inputs)
        except (OSError, RuntimeError) as e:
            print(f"Errore su {key}: {e} -> rilancio", flush=True)
            try:
                model.clear_runs()
            except Exception:
                pass
            sys.exit(RELAUNCH_CODE)

        _write_progress(progress_file, already_done + i, total, key, i, t0)
        model.clear_runs()
        if i % 5 == 0:
            gc.collect()

        if args.restart_every and i >= args.restart_every and i < n_pending:
            print(f"Restart preventivo dopo {i} combo (restart#{restarts+1})",
                  flush=True)
            sys.exit(RELAUNCH_CODE)

    print(f"\nCompletato in {(time.perf_counter()-t0)/60:.1f} min", flush=True)
    finish()
