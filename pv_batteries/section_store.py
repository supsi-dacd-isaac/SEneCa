"""Loader generico dello store pre-calcolato di una sezione.

Preferisce i parquet consolidati; se assenti, ricade sui file per-combo
(utile mentre il batch e' ancora in corso).
"""
from __future__ import annotations

import pandas as pd


def combo_key(values) -> str:
    return "_".join(f"{float(v):g}" for v in values)


def base_combo_key(cfg) -> str:
    return combo_key([cfg.BASE_SCENARIO[n] for n in cfg.INPUT_ORDER])


def load_traj_store(cfg) -> dict[str, pd.DataFrame]:
    store: dict[str, pd.DataFrame] = {}
    if cfg.CONSOLIDATED_TRAJ.exists():
        raw = pd.read_parquet(cfg.CONSOLIDATED_TRAJ)
        for key, g in raw.groupby(cfg.INPUT_ORDER):
            key = key if isinstance(key, tuple) else (key,)
            store[combo_key(key)] = (
                g.drop(columns=cfg.INPUT_ORDER).set_index("Time").sort_index())
        return store
    traj_dir = cfg.STORE_DIR / "traj"
    if traj_dir.exists():
        for fp in traj_dir.glob("*.parquet"):
            df = pd.read_parquet(fp)
            store[fp.stem] = (
                df.drop(columns=cfg.INPUT_ORDER, errors="ignore")
                .set_index("Time").sort_index())
    return store


def load_gmd_store(cfg) -> dict[str, dict]:
    measures = list(cfg.GMD_SPEC.keys())
    store: dict[str, dict] = {}
    if cfg.CONSOLIDATED_GMD.exists():
        raw = pd.read_parquet(cfg.CONSOLIDATED_GMD)
        for _, row in raw.iterrows():
            key = combo_key([row[c] for c in cfg.INPUT_ORDER])
            store[key] = {m: row.get(m) for m in measures}
        return store
    gmd_dir = cfg.STORE_DIR / "gmd"
    if gmd_dir.exists():
        for fp in gmd_dir.glob("*.parquet"):
            row = pd.read_parquet(fp).iloc[0]
            store[fp.stem] = {m: row.get(m) for m in measures}
    return store
