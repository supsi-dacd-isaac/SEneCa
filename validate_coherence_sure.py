"""Verifica di coerenza PySD vs Vensim (SURE.vpmx) su piu' scenari e variabili.

Per ogni scenario:
  * la stessa combinazione di leve viene applicata a PySD (via `params`) e a
    Vensim (via `SIMULATE>SETVAL` sul modello pubblicato SURE.vpmx);
  * si confrontano tutte le colonne flatten delle variabili di output
    (subscript inclusi) su 2011-2050, o sull'orizzonte piu' corto raggiunto da
    Vensim quando la sua simulazione aborta.

Il confronto usa `np.isclose(rtol, atol)` con atol scalato sulla grandezza
tipica della variabile: gli elementi con valore ~0 (archetipi rari) non
generano falsi positivi di errore relativo.

Uso:
    .\\.venv\\Scripts\\python.exe validate_coherence_sure.py --variant v2
    .\\.venv\\Scripts\\python.exe validate_coherence_sure.py --variant v2 --scenarios base high
    .\\.venv\\Scripts\\python.exe validate_coherence_sure.py --variant v2 --full --alloc-check
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

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import sure_paths as paths  # noqa: E402

YEARS = np.arange(2011, 2051)
RTOL = 1e-2          # tolleranza relativa "di accettazione" elemento per elemento
ATOL_SCALE = 1e-4    # atol = ATOL_SCALE * max|riferimento| della variabile
SIGNIF_SCALE = 1e-2  # errore relativo riportato solo dove |ref| > 1% della scala

# Criterio "pratico", per le variabili che passano da ALLOCATE AVAILABLE.
# PySD risolve l'allocazione oraria in modo esatto (l'energia dispacciata
# coincide con la domanda entro ~1e-12 GWh/h), mentre Vensim si ferma alla
# propria tolleranza: ~1e-2 GWh/h di picco, che su un anno intero fanno alcuni
# GWh non conciliati - dello stesso ordine della produzione annua dei fornitori
# marginali. Le differenze pysd-Vensim su quei fornitori sono quindi dominate
# dall'imprecisione di Vensim. Vedi --alloc-check per la misura, e la nota nel
# docstring di pysd.py_backend.allocation.allocate_available.
PRACT_SCALE = 1e-2
PRACT_AGG = 5e-2

# Variabili extra (subscripted, non nei chart Risultati) usate come controllo
# strutturale: costi, incentivi, stock e l'allocazione oraria del mercato.
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


# --------------------------------------------------------------------------
# Scenari
# --------------------------------------------------------------------------
def build_scenarios() -> dict[str, dict[str, float]]:
    """base / min / max / mid dalle INPUT_GRID delle pagine Risultati."""
    import pysd_explore_config as cfg

    base = {i.name: float(i.default) for i in cfg.ALL_INPUTS}
    lo = {i.name: float(min(i.values)) for i in cfg.ALL_INPUTS}
    hi = {i.name: float(max(i.values)) for i in cfg.ALL_INPUTS}
    mid = {i.name: float(sorted(i.values)[len(i.values) // 2]) for i in cfg.ALL_INPUTS}
    return {"base": base, "low": lo, "high": hi, "mid": mid}


# --------------------------------------------------------------------------
# Lato Vensim
# --------------------------------------------------------------------------
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
        # Senza questo Vensim apre un dialogo modale sugli errori di simulazione
        # (es. overflow) e la chiamata alla DLL resta bloccata per sempre.
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
        """Lancia il run.

        Ritorna (leve rifiutate perche' assenti dal .vpmx, ultimo anno simulato).
        L'ultimo anno puo' essere < 2050: su alcune combinazioni di leve la
        simulazione Vensim aborta e il run resta troncato.
        """
        self._cmd(f"SIMULATE>RUNNAME|{run_name}")
        skipped = []
        for var, val in inputs.items():
            if self.dll.vensim_command(
                    f"SIMULATE>SETVAL|{var}={val}".encode("mbcs")) != 1:
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


# --------------------------------------------------------------------------
# Confronto
# --------------------------------------------------------------------------
def _subscripts(col: str) -> list[str]:
    if "[" not in col:
        return []
    return col[col.index("[") + 1:col.rindex("]")].split(",")


def _aggregate_groups(cols: list[str]) -> dict[str, list[int]]:
    """Raggruppa gli elementi orari sommando su Month e Hour.

    'Electricity dispatched[M6,H15,Import]' -> gruppo 'Import'. Ritorna {} se la
    variabile non e' oraria (nessuna aggregazione sensata).
    """
    subs = [_subscripts(c) for c in cols]
    if not subs or not subs[0]:
        return {}
    hourly = [i for i, tok in enumerate(subs[0])
              if tok.startswith("M") and tok[1:].isdigit()]
    hourly += [i for i, tok in enumerate(subs[0])
               if tok.startswith("H") and tok[1:].isdigit()]
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
    if max_elems and len(cols) > max_elems:
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

    # Aggregato orario (= cio' che viene graficato: totale annuo per supplier).
    # Valutato solo dove il totale e' significativo: l'errore relativo su un
    # supplier che in un dato anno produce ~0 non dice nulla di utile.
    agg_rel = np.nan
    if len(cols) == n_all:
        groups = _aggregate_groups(cols)
        if groups:
            AP = np.vstack([P[idxs].sum(axis=0) for idxs in groups.values()])
            AB = np.vstack([B[idxs].sum(axis=0) for idxs in groups.values()])
            signif = np.abs(AB) > SIGNIF_SCALE * np.nanmax(np.abs(AB))
            if signif.any():
                agg_rel = float(np.nanmax(
                    np.abs(AP - AB)[signif] / np.abs(AB)[signif]))

    return {"var": var, "n_elems": len(cols), "n_fail": n_fail, "missing": missing,
            "max_rel": max_rel, "max_abs": float(np.nanmax(abs_err)),
            "scale": scale, "err_su_scala": float(np.nanmax(abs_err) / scale) if scale else 0.0,
            "agg_rel": agg_rel, "worst": worst}


def allocation_conservation(df, ven, run_name, suppliers, months, hours, years):
    """Confronta sum_supplier(Electricity dispatched) con Hourly demand and PHS.

    ALLOCATE AVAILABLE deve dispacciare esattamente `avail` quando la richiesta
    totale la eccede: quantifica quanto ciascun motore rispetta il vincolo.
    """
    print("\n--- Conservazione ALLOCATE AVAILABLE (dispacciato - domanda) ---")
    errs_p, errs_v = [], []
    ann_p = np.zeros(len(years))
    ann_v = np.zeros(len(years))
    for m in months:
        for h in hours:
            dem_cols = f"Hourly demand and PHS[{m},{h}]"
            if dem_cols not in df.columns:
                continue
            dp = df[dem_cols].reindex(years).to_numpy(dtype=float)
            dv = ven.series(run_name, dem_cols, years)
            sp_ = np.zeros_like(dp)
            sv = np.zeros_like(dp)
            for s in suppliers:
                lab = f"Electricity dispatched[{m},{h},{s}]"
                if lab in df.columns:
                    sp_ += df[lab].reindex(years).to_numpy(dtype=float)
                sr = ven.series(run_name, lab, years)
                if sr is not None:
                    sv += sr
            errs_p.append(np.abs(sp_ - dp))
            errs_v.append(np.abs(sv - dv))
            ann_p += np.abs(sp_ - dp)
            ann_v += np.abs(sv - dv)
    if not errs_p:
        print("  (dati insufficienti)")
        return
    ep, ev = np.concatenate(errs_p), np.concatenate(errs_v)
    print(f"  celle (mese,ora,anno) esaminate: {ep.size}")
    print(f"  PySD   : errore max={ep.max():.3e}  medio={ep.mean():.3e} GWh/h")
    print(f"  Vensim : errore max={ev.max():.3e}  medio={ev.mean():.3e} GWh/h")
    print(f"  energia annua non conciliata (somma su mesi/ore, max sugli anni): "
          f"PySD {ann_p.max():.3e} GWh, Vensim {ann_v.max():.3f} GWh")
    print("  -> lo scarto sul dispacciamento orario nasce dalla tolleranza del "
          "solver di Vensim, non dalla traduzione." if ev.max() > 10 * ep.max()
          else "  -> i due motori conservano in modo comparabile.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variant", default=None, help="Variante da validare (es. v2)")
    ap.add_argument("--scenarios", nargs="*",
                    default=["base", "low", "mid", "high"])
    ap.add_argument("--max-elems", type=int, default=400,
                    help="Sotto-campionamento degli elementi per variabile (0 = tutti)")
    ap.add_argument("--no-prune", action="store_true",
                    help="Non potare il modello PySD (piu' lento, copertura piena)")
    ap.add_argument("--full", action="store_true",
                    help="Tutti gli elementi e tutti gli scenari, senza potatura")
    ap.add_argument("--out", default=None, help="CSV di report")
    ap.add_argument("--alloc-check", action="store_true",
                    help="Verifica la conservazione di ALLOCATE AVAILABLE "
                         "(somma dispacciata per ora == domanda) su PySD e Vensim")
    args = ap.parse_args()

    if args.variant is not None:
        paths.set_variant(args.variant)
    if args.full:
        args.max_elems = 0
        args.no_prune = True
        args.scenarios = ["base", "low", "mid", "high"]

    import sure_pysd as sp

    print(paths.describe())
    if not paths.pysd_py().is_file():
        raise SystemExit(f"Modello tradotto assente: {paths.pysd_py()}")

    scenarios = build_scenarios()
    outputs = list(dict.fromkeys(list(sp.OUTPUTS) + EXTRA_OUTPUTS))
    if args.alloc_check:
        outputs.append("Hourly demand and PHS")

    t0 = time.perf_counter()
    sp.OUTPUTS = outputs
    model = sp.load_model(prune=not args.no_prune)
    const = sp.build_constant_params(model)
    print(f"load+const: {time.perf_counter()-t0:.1f}s  (costanti calibrate: {len(const)})")

    ns = model._namespace
    outputs = [o for o in outputs if o in ns]
    levers_all = sorted({k for s in scenarios.values() for k in s})
    levers_ok = [k for k in levers_all if k in ns]
    levers_missing = [k for k in levers_all if k not in ns]
    print(f"output validati: {len(outputs)}   leve applicate: {len(levers_ok)}")
    if levers_missing:
        print(f"leve non presenti nel modello (ignorate): {levers_missing}")

    ven = Vensim()
    rows = []
    setval_ok = True

    for scen in args.scenarios:
        inputs = {k: v for k, v in scenarios[scen].items() if k in levers_ok}
        run_name = f"coh_{paths.variant() or 'def'}_{scen}"
        print(f"\n=== scenario '{scen}' ===")
        print("  " + " | ".join(f"{k}={v:g}" for k, v in list(inputs.items())[:6]) + " ...")

        t = time.perf_counter()
        skipped, horizon = ven.run(run_name, inputs)
        t_ven = time.perf_counter() - t
        if skipped:
            print(f"  !! SETVAL rifiutato da Vensim per: {skipped}")
            setval_ok = False

        # Quando la simulazione Vensim aborta, l'ultimo punto salvato e' una
        # copia del precedente (il passo non e' stato completato): va scartato.
        years = YEARS
        if np.isfinite(horizon) and horizon < YEARS[-1]:
            years = YEARS[YEARS < horizon]
            print(f"  !! la simulazione Vensim si e' interrotta al {int(horizon)}: "
                  f"confronto limitato a {years[0]}-{years[-1]}")

        t = time.perf_counter()
        df = sp.run_scenario(model, const_params=const, scenario_inputs=inputs,
                             timestamps=YEARS, flatten=True, return_columns=outputs)
        df.index = np.round(np.asarray(df.index, dtype=float)).astype(int)
        print(f"  vensim {t_ven:.1f}s | pysd {time.perf_counter()-t:.1f}s "
              f"| colonne {len(df.columns)}")

        if args.alloc_check:
            sd = model.components._subscript_dict
            allocation_conservation(df, ven, run_name, sd["Supplier"],
                                    sd["Month"], sd["Hour"], years)

        for var in outputs:
            if var == "Hourly demand and PHS":
                continue
            r = compare_var(var, df, ven, run_name, args.max_elems, years)
            if r is None:
                print(f"  {var[:52]:52} -- assente nell'output pysd")
                continue
            r["scenario"] = scen
            r["fino_a"] = int(years[-1])
            r["strict"] = r["n_fail"] == 0 and r["missing"] == 0
            # Le variabili orarie passano dal solver di ALLOCATE AVAILABLE: per
            # queste il criterio e' sull'aggregato annuo per supplier, che e'
            # anche la grandezza effettivamente graficata.
            r["practical"] = r["missing"] == 0 and (
                r["err_su_scala"] <= PRACT_SCALE
                or (not np.isnan(r["agg_rel"]) and r["agg_rel"] <= PRACT_AGG))
            rows.append(r)
            tag = "OK" if r["strict"] else ("~OK" if r["practical"] else "DIFF")
            agg = "  -  " if np.isnan(r["agg_rel"]) else f"{r['agg_rel']:.1e}"
            print(f"  {r['var'][:52]:52} el={r['n_elems']:5} fail={r['n_fail']:5} "
                  f"max_rel={r['max_rel']:.2e} err/scala={r['err_su_scala']:.1e} "
                  f"agg={agg} [{tag}]")
            if not r["strict"] and r["worst"]:
                print(f"      worst: {r['worst']}  (missing={r['missing']})")

    rep = pd.DataFrame(rows)
    out_csv = Path(args.out) if args.out else ROOT / f"coherence_report{paths.suffix()}.csv"
    rep.to_csv(out_csv, index=False)

    print("\n" + "=" * 70)
    print(f"Report: {out_csv.name}")
    strict_ok = practical_ok = setval_ok
    if not rep.empty:
        loose = rep[~rep.strict]
        bad = rep[~rep.practical]
        strict_ok &= loose.empty
        practical_ok &= bad.empty
        print(f"Variabili*scenario confrontati: {len(rep)}")
        print(f"  identici entro rtol={RTOL:g} su ogni elemento : {len(rep) - len(loose)}")
        print(f"  entro {PRACT_SCALE:g} della scala e {PRACT_AGG:g} sugli aggregati : "
              f"{len(rep) - len(bad)}")
        cols = ["scenario", "var", "n_elems", "n_fail", "max_rel",
                "err_su_scala", "agg_rel"]
        if not loose.empty:
            print("\nNon identici elemento per elemento:")
            print(loose[cols].to_string(index=False))
        if not bad.empty:
            print("\nOltre anche il criterio pratico:")
            print(bad[cols].to_string(index=False))
    print("\nVERDETTO:",
          "COERENTE (identita' elemento per elemento)" if strict_ok
          else ("COERENTE entro tolleranza del solver di allocazione"
                if practical_ok else "DISCREPANZE PRESENTI"))
    raise SystemExit(0 if practical_ok else 1)


if __name__ == "__main__":
    main()
