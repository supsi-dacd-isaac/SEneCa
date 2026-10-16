"""Verifica di coerenza PySD vs Vensim (SURE.vpmx) sugli scenari delle leve.

Stessa logica dello storico validate_coherence_sure.py: stesse leve su PySD e
sul .vpmx pubblicato, confronto delle variabili di output su 2011-2050.
"""
from __future__ import annotations

import argparse
import ctypes
import os
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.setrecursionlimit(1_000_000)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import sure_paths as paths  # noqa: E402

YEARS = np.arange(2011, 2051)
RTOL = 1e-2
ATOL_SCALE = 1e-4
SIGNIF_SCALE = 1e-2
PRACT_SCALE = 1e-2
PRACT_AGG = 5e-2

EXTRA_OUTPUTS = [
    "Electricity and heating and retrofit annual cost",
    "Average levy minus incentives archetype",
    "Average tax minus incentives archetype",
    "Batteries",
    "HeatPumps",
    "Levy Evolution",
    "Power by Type",
    "Annual CO2 emissions",
    "Total annual electricity consumed",
    "Total annual electricity demand",
    "Total annual electricity dispatched",
]


def build_scenarios() -> dict[str, dict[str, float]]:
    import pysd_explore_config as cfg

    base = {i.name: float(i.default) for i in cfg.ALL_INPUTS}
    lo = {i.name: float(min(i.values)) for i in cfg.ALL_INPUTS}
    hi = {i.name: float(max(i.values)) for i in cfg.ALL_INPUTS}
    mid = {i.name: float(sorted(i.values)[len(i.values) // 2]) for i in cfg.ALL_INPUTS}
    return {"base": base, "low": lo, "high": hi, "mid": mid}


class Vensim:
    def __init__(self):
        self.dll = ctypes.WinDLL(paths.DLL_PATH)
        d = self.dll
        d.vensim_command.argtypes = [ctypes.c_char_p]
        d.vensim_command.restype = ctypes.c_int
        d.vensim_get_data.argtypes = [
            ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_float),
            ctypes.c_int]
        d.vensim_get_data.restype = ctypes.c_int
        d.vensim_be_quiet.argtypes = [ctypes.c_int]
        d.vensim_be_quiet.restype = ctypes.c_int
        d.vensim_be_quiet(2)
        os.chdir(paths.VENSIM)
        self._cmd(f"SPECIAL>LOADMODEL|{paths.MODEL_VPMX}")
        self._maxn = 4096
        self._vv = (ctypes.c_float * self._maxn)()
        self._tt = (ctypes.c_float * self._maxn)()

    def _cmd(self, command: str):
        if self.dll.vensim_command(command.encode("mbcs")) != 1:
            raise RuntimeError(f"Comando Vensim fallito: {command}")

    def run(self, run_name: str, inputs: dict[str, float]) -> tuple[list[str], float]:
        self._cmd(f"SIMULATE>RUNNAME|{run_name}")
        skipped = []
        for var, val in inputs.items():
            # I nomi con virgolette in Vensim (Provvedimento 1.x) vanno quotati.
            quoted = f'"{var}"' if var.startswith("Provvedimento") else var
            cmd = f"SIMULATE>SETVAL|{quoted}={val}"
            if self.dll.vensim_command(cmd.encode("mbcs")) != 1:
                skipped.append(var)
        self._cmd("MENU>RUN|O")
        return skipped, self._horizon(run_name)

    def _horizon(self, run_name: str) -> float:
        n = self.dll.vensim_get_data(
            run_name.encode("mbcs"), b"Levy Evolution", b"Time",
            self._vv, self._tt, self._maxn)
        return float(self._tt[n - 1]) if n > 0 else float("nan")

    def series(self, run_name: str, label: str, years):
        n = self.dll.vensim_get_data(
            run_name.encode("mbcs"), label.encode("mbcs"), b"Time",
            self._vv, self._tt, self._maxn)
        if n <= 0:
            return None
        t = np.round(np.asarray(self._tt[:n], dtype=float)).astype(int)
        v = np.asarray(self._vv[:n], dtype=float)
        return pd.Series(v, index=t).reindex(years).to_numpy(dtype=float)


def _subscripts(col: str) -> list[str]:
    if "[" not in col:
        return []
    return col[col.index("[") + 1:col.rindex("]")].split(",")


def _aggregate_groups(cols: list[str]) -> dict[str, list[int]]:
    subs = [_subscripts(c) for c in cols]
    if not subs or not subs[0]:
        return {}
    hourly = [i for i, tok in enumerate(subs[0])
              if (tok.startswith("M") or tok.startswith("H")) and tok[1:].isdigit()]
    if not hourly:
        return {}
    groups: dict[str, list[int]] = {}
    for i, tok in enumerate(subs):
        key = ",".join(t for j, t in enumerate(tok) if j not in hourly) or "TOT"
        groups.setdefault(key, []).append(i)
    return groups


def compare_var(var, df, ven, run_name, max_elems, years):
    cols = [c for c in df.columns if c == var or c.startswith(var + "[")]
    if not cols:
        return None
    n_all = len(cols)
    if max_elems and len(cols) > max_elems and not _aggregate_groups(cols):
        step = int(np.ceil(len(cols) / max_elems))
        cols = cols[::step]

    P = np.vstack([df[c].reindex(years).to_numpy(dtype=float) for c in cols])
    B = np.full_like(P, np.nan)
    missing = 0
    for i, c in enumerate(cols):
        s = ven.series(run_name, c, years)
        if s is None:
            missing += 1
        else:
            B[i] = s

    valid = np.isfinite(B) & np.isfinite(P)
    if not valid.any():
        return {"var": var, "n_elems": len(cols), "n_fail": -1, "missing": missing,
                "max_rel": np.nan, "max_abs": np.nan, "scale": np.nan,
                "err_su_scala": np.nan, "agg_rel": np.nan, "worst": ""}

    scale = float(np.nanmax(np.abs(B[valid])))
    atol = max(scale * ATOL_SCALE, 1e-9)
    abs_err = np.where(valid, np.abs(P - B), 0.0)
    close = np.isclose(P, B, rtol=RTOL, atol=atol) | ~valid
    n_fail = int((~close).sum())

    signif = valid & (np.abs(B) > scale * SIGNIF_SCALE)
    rel = np.where(signif, abs_err / np.where(signif, np.abs(B), 1.0), np.nan)
    if np.isfinite(rel).any():
        k = int(np.nanargmax(np.nan_to_num(rel, nan=-1.0)))
        i, j = np.unravel_index(k, rel.shape)
        max_rel = float(rel[i, j])
        worst = f"{cols[i]} @ {int(years[j])}"
    else:
        max_rel, worst = 0.0, ""

    agg_rel = np.nan
    if len(cols) == n_all:
        groups = _aggregate_groups(cols)
        if groups:
            AP = np.vstack([P[idxs].sum(axis=0) for idxs in groups.values()])
            AB = np.vstack([B[idxs].sum(axis=0) for idxs in groups.values()])
            signif = np.abs(AB) > SIGNIF_SCALE * np.nanmax(np.abs(AB))
            if signif.any():
                agg_rel = float(np.nanmax(np.abs(AP - AB)[signif] / np.abs(AB)[signif]))

    return {"var": var, "n_elems": len(cols), "n_fail": n_fail, "missing": missing,
            "max_rel": max_rel, "max_abs": float(np.nanmax(abs_err)),
            "scale": scale, "err_su_scala": float(np.nanmax(abs_err) / scale) if scale else 0.0,
            "agg_rel": agg_rel, "worst": worst}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="v6")
    ap.add_argument("--scenarios", nargs="*", default=["base", "low", "mid", "high"])
    ap.add_argument("--max-elems", type=int, default=400)
    args = ap.parse_args()
    paths.set_variant(args.variant)

    import sure_pysd as sp

    print(paths.describe(), flush=True)
    scenarios = build_scenarios()
    outputs = list(dict.fromkeys(list(sp.OUTPUTS) + EXTRA_OUTPUTS))
    t0 = time.perf_counter()
    sp.OUTPUTS = outputs
    model = sp.load_model(prune=True)
    const = sp.build_constant_params(model)
    print(f"load+const: {time.perf_counter()-t0:.1f}s  (costanti calibrate: {len(const)})", flush=True)

    ns = model._namespace
    outputs = [o for o in outputs if o in ns]
    levers_all = sorted({k for s in scenarios.values() for k in s})
    levers_ok = [k for k in levers_all if sp.namespace_key(model, k)]
    levers_missing = [k for k in levers_all if sp.namespace_key(model, k) is None]
    print(f"output validati: {len(outputs)}   leve applicate: {len(levers_ok)}", flush=True)
    if levers_missing:
        print(f"leve non presenti nel modello (ignorate): {levers_missing}", flush=True)

    ven = Vensim()
    rows = []
    setval_ok = True
    for scen in args.scenarios:
        inputs = {k: v for k, v in scenarios[scen].items() if k in levers_ok}
        run_name = f"coh_{paths.variant() or 'def'}_{scen}"
        print(f"\n=== scenario '{scen}' ===", flush=True)
        t = time.perf_counter()
        skipped, horizon = ven.run(run_name, inputs)
        t_ven = time.perf_counter() - t
        if skipped:
            print(f"  !! SETVAL rifiutato da Vensim per: {skipped}", flush=True)
            setval_ok = False
        years = YEARS
        if np.isfinite(horizon) and horizon < YEARS[-1]:
            years = YEARS[YEARS < horizon]
            print(f"  !! Vensim interrotto al {int(horizon)}: confronto {years[0]}-{years[-1]}", flush=True)
        t = time.perf_counter()
        df = sp.run_scenario(model, const_params=const, scenario_inputs=inputs,
                             timestamps=YEARS, flatten=True, return_columns=outputs)
        df.index = np.round(np.asarray(df.index, dtype=float)).astype(int)
        print(f"  vensim {t_ven:.1f}s | pysd {time.perf_counter()-t:.1f}s | colonne {len(df.columns)}", flush=True)
        for var in outputs:
            r = compare_var(var, df, ven, run_name, args.max_elems, years)
            if r is None:
                print(f"  {var[:52]:52} -- assente", flush=True)
                continue
            r["scenario"] = scen
            r["fino_a"] = int(years[-1])
            r["strict"] = r["n_fail"] == 0 and r["missing"] == 0
            r["practical"] = r["missing"] == 0 and (
                r["err_su_scala"] <= PRACT_SCALE
                or (not np.isnan(r["agg_rel"]) and r["agg_rel"] <= PRACT_AGG))
            rows.append(r)
            tag = "OK" if r["strict"] else ("~OK" if r["practical"] else "DIFF")
            print(f"  {r['var'][:52]:52} el={r['n_elems']:5} fail={r['n_fail']:5} "
                  f"max_rel={r['max_rel']:.2e} err/scala={r['err_su_scala']:.1e} [{tag}]", flush=True)
            if not r["strict"] and r["worst"]:
                print(f"      worst: {r['worst']}  (missing={r['missing']})", flush=True)

    rep = pd.DataFrame(rows)
    out_csv = ROOT / f"coherence_report{paths.suffix()}.csv"
    rep.to_csv(out_csv, index=False)
    practical_ok = setval_ok and (rep.empty or bool(rep.practical.all()))
    print("\n" + "=" * 70, flush=True)
    print(f"Report: {out_csv.name}", flush=True)
    if not rep.empty:
        print(f"Confronti: {len(rep)}  identici: {int(rep.strict.sum())}  entro tolleranza: {int(rep.practical.sum())}", flush=True)
        bad = rep[~rep.practical]
        if not bad.empty:
            print(bad[["scenario", "var", "n_fail", "max_rel", "err_su_scala"]].to_string(index=False), flush=True)
    print("VERDETTO:", "COERENTE" if practical_ok else "DISCREPANZE PRESENTI", flush=True)
    raise SystemExit(0 if practical_ok else 1)


if __name__ == "__main__":
    main()
