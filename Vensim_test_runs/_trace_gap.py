"""Scompone lo scarto Energy price / Electricity dispatched fra PySD e Vensim."""
from __future__ import annotations

import ctypes
import os
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.setrecursionlimit(1_000_000)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import sure_paths as paths  # noqa: E402

paths.set_variant("v6")
YEARS = np.arange(2011, 2051)
ORDER = ["Import", "Coal", "Nuclear", "Hydro", "PHS", "RoR", "Wind", "Solar", "Waste"]
FOCUS = [
    "Energy price",
    "Average energy price market",
    "Electricity market price",
    "Electricity dispatched",
    "Hourly available supply by Supplier",
    "Hourly demand and PHS",
]


def scenarios():
    import pysd_explore_config as cfg
    base = {i.name: float(i.default) for i in cfg.ALL_INPUTS}
    hi = {i.name: float(max(i.values)) for i in cfg.ALL_INPUTS}
    return {"base": base, "high": hi}


class Vensim:
    def __init__(self):
        self.dll = ctypes.WinDLL(paths.DLL_PATH)
        d = self.dll
        d.vensim_command.argtypes = [ctypes.c_char_p]
        d.vensim_command.restype = ctypes.c_int
        d.vensim_get_data.argtypes = [
            ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_float), ctypes.c_int]
        d.vensim_get_data.restype = ctypes.c_int
        d.vensim_be_quiet.argtypes = [ctypes.c_int]
        d.vensim_be_quiet(2)
        os.chdir(paths.VENSIM)
        if d.vensim_command(f"SPECIAL>LOADMODEL|{paths.MODEL_VPMX}".encode("mbcs")) != 1:
            raise RuntimeError("LOADMODEL")
        self._vv = (ctypes.c_float * 4096)()
        self._tt = (ctypes.c_float * 4096)()

    def run(self, name, inputs):
        d = self.dll
        if d.vensim_command(f"SIMULATE>RUNNAME|{name}".encode("mbcs")) != 1:
            raise RuntimeError("RUNNAME")
        skipped = []
        for var, val in inputs.items():
            q = f'"{var}"' if var.startswith("Provvedimento") else var
            if d.vensim_command(f"SIMULATE>SETVAL|{q}={val}".encode("mbcs")) != 1:
                skipped.append(var)
        if d.vensim_command(b"MENU>RUN|O") != 1:
            raise RuntimeError("RUN")
        return skipped

    def series(self, run, label):
        n = self.dll.vensim_get_data(
            run.encode("mbcs"), label.encode("mbcs"), b"Time", self._vv, self._tt, 4096)
        if n <= 0:
            return None
        t = np.round(np.asarray(self._tt[:n], dtype=float)).astype(int)
        v = np.asarray(self._vv[:n], dtype=float)
        return pd.Series(v, index=t).reindex(YEARS).to_numpy()


def marginal(dispatched):
    """Primo fornitore con dispacciamento > 0, nell'ordine del prezzo di mercato."""
    for name in ORDER:
        if name in dispatched and dispatched[name] > 0:
            return name
    return "none"


def main():
    import sure_pysd as sp
    from pysd.py_backend.allocation import allocate_available, allocate_by_priority

    sp.OUTPUTS = FOCUS
    model = sp.load_model(prune=True)
    const = sp.build_constant_params(model)
    sd = model.components._subscript_dict
    months, hours, suppliers = sd["Month"], sd["Hour"], sd["Supplier"]
    ven = Vensim()
    sc = scenarios()

    for scen in ("base", "high"):
        inputs = {k: v for k, v in sc[scen].items() if sp.namespace_key(model, k)}
        run = f"gap_{scen}"
        print(f"\n===== {scen} =====", flush=True)
        skipped = ven.run(run, inputs)
        print("SETVAL rifiutati:", skipped or "nessuno", flush=True)
        df = sp.run_scenario(model, const_params=const, scenario_inputs=inputs,
                             timestamps=YEARS, flatten=True, return_columns=FOCUS)
        df.index = np.round(np.asarray(df.index, dtype=float)).astype(int)

        # Prezzo: lo scarto di Energy price deve coincidere con quello del prezzo di mercato medio.
        ep = np.vstack([df[f"Energy price[{d}]"].to_numpy() for d in sd["District"]])
        ev = np.vstack([ven.series(run, f"Energy price[{d}]") for d in sd["District"]])
        ap = df["Average energy price market"].to_numpy()
        av = ven.series(run, "Average energy price market")
        print(f"Energy price max |d|={np.nanmax(np.abs(ep-ev)):.4e}  "
              f"scala={np.nanmax(np.abs(ev)):.4e}", flush=True)
        print(f"Average energy price market max |d|={np.nanmax(np.abs(ap-av)):.4e}  "
              f"scala={np.nanmax(np.abs(av)):.4e}", flush=True)

        def cached(label):
            key = (run, label)
            if key not in cached.store:
                cached.store[key] = ven.series(run, label)
            return cached.store[key]
        cached.store = {}

        flips = []
        hydro_neg = 0
        dispatch_abs = {s: 0.0 for s in suppliers}
        supply_abs = {s: 0.0 for s in suppliers}
        worst = None
        for m in months:
            for h in hours:
                d_p = {s: df[f"Electricity dispatched[{m},{h},{s}]"].to_numpy() for s in suppliers}
                d_v = {s: cached(f"Electricity dispatched[{m},{h},{s}]") for s in suppliers}
                s_p = {s: df[f"Hourly available supply by Supplier[{m},{h},{s}]"].to_numpy() for s in suppliers}
                s_v = {s: cached(f"Hourly available supply by Supplier[{m},{h},{s}]") for s in suppliers}
                dem_p_s = df[f"Hourly demand and PHS[{m},{h}]"].to_numpy()
                dem_v_s = cached(f"Hourly demand and PHS[{m},{h}]")
                price_p_s = df[f"Electricity market price[{m},{h}]"].to_numpy()
                price_v_s = cached(f"Electricity market price[{m},{h}]")
                for i, year in enumerate(YEARS):
                    if year < 2027:
                        continue
                    dp = {s: float(d_p[s][i]) for s in suppliers}
                    dv = {s: float(d_v[s][i]) for s in suppliers}
                    sply_p = {s: float(s_p[s][i]) for s in suppliers}
                    sply_v = {s: float(s_v[s][i]) for s in suppliers}
                    for s in suppliers:
                        dispatch_abs[s] += abs(dp[s] - dv[s])
                        supply_abs[s] += abs(sply_p[s] - sply_v[s])
                    if sply_v["Hydro"] < 0 or sply_p["Hydro"] < 0:
                        hydro_neg += 1
                    mp, mv = marginal(dp), marginal(dv)
                    if mp != mv:
                        dem_p = float(dem_p_s[i])
                        dem_v = float(dem_v_s[i])
                        price_p = float(price_p_s[i])
                        price_v = float(price_v_s[i])
                        rec = (year, m, h, mp, mv, price_p, price_v, dem_v)
                        flips.append(rec)
                        score = abs(price_p - price_v) * abs(dem_v)
                        if worst is None or score > worst[0]:
                            worst = (score, rec, dp, dv, sply_p, sply_v, dem_p, dem_v)
        print(f"Ore con idro disponibile negativo: {hydro_neg}", flush=True)
        print(f"Ore 2027-2050 con fornitore marginale diverso: {len(flips)}", flush=True)
        if flips:
            from collections import Counter
            print("  coppie PySD->Vensim:", Counter((a[3], a[4]) for a in flips).most_common(6), flush=True)
        print("Somma |scarto| dispacciamento per fornitore:",
              {k: round(v, 3) for k, v in sorted(dispatch_abs.items(), key=lambda kv: -kv[1])[:4]}, flush=True)
        print("Somma |scarto| offerta per fornitore:",
              {k: round(v, 3) for k, v in sorted(supply_abs.items(), key=lambda kv: -kv[1])[:4]}, flush=True)

        if worst is None:
            continue
        _, rec, dp, dv, sply_p, sply_v, dem_p, dem_v = worst
        year, m, h, mp, mv, price_p, price_v, dem_w, *_ = rec
        print(f"Ora che pesa di più sul prezzo: {year} {m} {h}  "
              f"marginale PySD={mp} ({price_p:.2f}) Vensim={mv} ({price_v:.2f}) CHF/MWh", flush=True)
        print(f"  domanda PySD={dem_p:.6f} Vensim={dem_v:.6f}", flush=True)
        for s in suppliers:
            print(f"  {s:8} offerta {sply_p[s]:10.5f} / {sply_v[s]:10.5f}   "
                  f"dispacciato {dp[s]:10.5f} / {dv[s]:10.5f}", flush=True)

        # Stessi input di Vensim, due algoritmi.
        req = np.array([max(sply_v[s], 0.0) for s in suppliers], dtype=float)
        req_raw = np.array([sply_v[s] for s in suppliers], dtype=float)
        costs = {
            "Solar": 2.0, "Wind": 1.0, "Nuclear": 10.0, "RoR": 11.0, "Hydro": 32.0,
            "Import": float("nan"), "PHS": 31.5, "Coal": 55.0, "Waste": 12.0,
        }
        # Il costo dell'import non è costante: lo deduciamo solo se serve al confronto degli algoritmi
        # usando la priorità -costo nota per gli altri. Per l'import usiamo il prezzo di mercato Vensim
        # se è il marginale, altrimenti un valore alto coerente con la curva storica (~90).
        import_cost = price_v if mv == "Import" else 90.0
        costs["Import"] = import_cost
        priority = np.array([-costs[s] for s in suppliers])
        width = np.full(len(suppliers), 0.1)
        by_pri = allocate_by_priority(
            xr_req(req, suppliers), xr_pri(priority, suppliers), 0.1, dem_v)
        print("  allocate_by_priority sugli input Vensim (idro negativo azzerato):",
              {s: round(float(by_pri.values[i]), 5) for i, s in enumerate(suppliers)}, flush=True)


def xr_req(values, suppliers):
    import xarray as xr
    return xr.DataArray(values, {"Supplier": list(suppliers)}, ["Supplier"])


def xr_pri(values, suppliers):
    import xarray as xr
    return xr.DataArray(values, {"Supplier": list(suppliers)}, ["Supplier"])


if __name__ == "__main__":
    main()
