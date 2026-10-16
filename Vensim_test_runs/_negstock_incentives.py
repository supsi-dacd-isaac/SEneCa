"""Tre corse del vpmx pubblicato: base, incentivi FV max, retrofit max.

Misura il minimo e la massa negativa degli stock e delle adozioni PV/RCP/RCPv.
"""
from __future__ import annotations

import importlib.machinery
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
pyc = ROOT / "pv_batteries" / "__pycache__" / "vensim_runner.cpython-311.pyc"
vr = importlib.machinery.SourcelessFileLoader("vensim_runner", str(pyc)).load_module()
VensimModel = vr.VensimModel
_enc = vr._enc

VPMX = ROOT / "Vensim" / "SURE.vpmx"
OUT = ROOT / "Vensim_test_runs" / "diagnostic" / "negstock_incentives.json"
NEG = -1e-3

# Valori pubblicati nel mdl, e massimi della scala usata nell'interfaccia.
BASE = {
    "PV rebate cantonal": 0.1,
    "PV rebate federal": 0.2,
    "FiT": 0.0,
    "Battery Rebate": 0.5,
    "Retrofit incentive input": 60.0,
}
PV_MAX = {
    **BASE,
    "PV rebate cantonal": 0.2,
    "PV rebate federal": 0.4,
    "FiT": 0.10,
    "Battery Rebate": 0.5,
}
RETRO_MAX = {
    **BASE,
    "Retrofit incentive input": 100.0,
}
CASES = (("base", BASE), ("pv_max", PV_MAX), ("retrofit_max", RETRO_MAX))

STOCKS = [
    "Heating Solution",
    "Res VeryLow Buildings",
    "Res Low Buildings",
    "Res Moderate Buildings",
    "Res High Buildings",
    "Res VeryHigh Buildings",
    "PV kWh self consumed",
    "Total PV kWh SC",
    "PV kW installed Residential",
    '"Total PV kWh self consumed < 30"',
    '"Total PV kWh self consumed 30 - 100 kW"',
    '"Total PV kWh self consumed > 100 kW"',
    "Owned buildings with PV",
    "Rented buildings with PV",
    "Owned buildings with RCP",
    "Rented buildings with RCP",
    "Owned buildings with RCPv",
    "Rented buildings with RCPv",
    "Owned buildings with RCPv PVno",
    "Rented buildings with RCPv PVno",
]
FLOWS = [
    "Owners adopting PV",
    "Renters adopting PV",
    "Owners adopting RCP",
    "Renters adopting RCP",
    "Owners adopting RCPv",
    "Renters adopting RCPv",
    "Requested Owners adopting PV",
    "Requested Renters adopting PV",
    "Requested Owners adopting RCP",
    "Requested Renters adopting RCP",
    "Requested Owners adopting RCPv",
    "Requested Renters adopting RCPv",
    "Consumers adopting PV no",
    "Buildings adopting HS",
    "Buildings adopting HS for old age",
    "Buildings leaving HS",
    "Consumers leaving HS for old age",
    "Building demolition by archetype",
    "Buildings HS Renovation From",
    "Accepted PV adoption",
    "Available PV adoption",
]
PROBES = [
    "PV Hourly SC computed",
    "Available PV adoption",
    "PV hourly SC",
    "Heating Solution",
]


def expand(model, base: str) -> list[str]:
    try:
        names = model.expand_var(base)
    except Exception as exc:
        return [f"ERROR {exc}"]
    if len(names) == 1 and names[0] == base:
        # expand_var restituisce il nome base sia se è scalare, sia se manca.
        try:
            model.get_val(base)
            return names
        except Exception:
            return []
    return names


def scan(model, run: str, bases: list[str]) -> dict:
    vval, tval = model._buffers(64)
    dll = model.dll
    out = {}
    for base in bases:
        names = expand(model, base)
        if not names or (len(names) == 1 and str(names[0]).startswith("ERROR")):
            print(f"  manca {base}", flush=True)
            out[base] = {"missing": True}
            continue
        t0 = time.perf_counter()
        worst = float("inf")
        worst_at = None
        lows: list[dict] = []
        n_elem = 0
        n_elem_neg = 0
        n_points_neg = 0
        mass = 0.0
        sum_first = 0.0
        sum_last = 0.0
        mass_by_year: dict[int, float] = {}
        for full in names:
            n = dll.vensim_get_data(_enc(run), _enc(full), b"Time", vval, tval, 64)
            if n <= 0:
                continue
            n_elem += 1
            vals = np.ctypeslib.as_array(vval, shape=(n,)).astype(np.float64, copy=False)
            sum_first += float(vals[0])
            sum_last += float(vals[n - 1])
            local = float(vals.min())
            neg = vals < NEG
            if np.any(neg):
                n_elem_neg += 1
                n_points_neg += int(np.count_nonzero(neg))
                years = np.ctypeslib.as_array(tval, shape=(n,))
                i = int(np.argmin(vals))
                lows.append({
                    "element": full,
                    "year": int(round(float(years[i]))),
                    "value": local,
                })
                for yr, val in zip(years, vals):
                    if val < NEG:
                        y = int(round(float(yr)))
                        mass += float(val)
                        mass_by_year[y] = mass_by_year.get(y, 0.0) + float(val)
            if local < worst:
                years = np.ctypeslib.as_array(tval, shape=(n,))
                i = int(np.argmin(vals))
                worst = local
                worst_at = {
                    "element": full,
                    "year": int(round(float(years[i]))),
                    "value": worst,
                }
        worst_year = None
        if mass_by_year:
            y, m = min(mass_by_year.items(), key=lambda kv: kv[1])
            worst_year = {"year": y, "negative_mass": m}
        lows.sort(key=lambda item: item["value"])
        rec = {
            "n_elements": n_elem,
            "min": None if worst == float("inf") else worst,
            "sum_first": sum_first,
            "sum_last": sum_last,
            "n_elements_below": n_elem_neg,
            "n_points_below": n_points_neg,
            "negative_mass": mass,
            "worst": worst_at,
            "worst_year": worst_year,
            "lowest": lows[:8],
        }
        out[base] = rec
        print(
            f"  {base}: n={n_elem} min={worst:.6g} elem<0={n_elem_neg} "
            f"({time.perf_counter() - t0:.1f}s)",
            flush=True,
        )
    return out


def main() -> None:
    print("carico", VPMX, flush=True)
    model = VensimModel(VPMX, work_dir=VPMX.parent)
    dll = model.dll
    dll.vensim_be_quiet.argtypes = [__import__("ctypes").c_int]
    dll.vensim_be_quiet.restype = __import__("ctypes").c_int
    print("quiet", dll.vensim_be_quiet(1), flush=True)
    probes = {}
    for name in PROBES:
        names = expand(model, name)
        probes[name] = 0 if not names else len(names)
        print(f"probe {name}: {probes[name]}", flush=True)
    model.set_time(2011, 2050, 1)
    results = {"probes": probes, "cases": {}}
    for case, params in CASES:
        print(f"RUN {case} {params}", flush=True)
        t0 = time.perf_counter()
        model.run(case, params)
        print(f"  simulazione {time.perf_counter() - t0:.1f}s", flush=True)
        readback = {}
        for key in params:
            try:
                readback[key] = model.get_val(key)
            except Exception as exc:
                readback[key] = str(exc)
        print("  readback", readback, flush=True)
        stocks = scan(model, case, STOCKS)
        flows = scan(model, case, FLOWS)
        results["cases"][case] = {
            "params": params,
            "readback": readback,
            "stocks": stocks,
            "flows": flows,
        }
        try:
            model.clear_runs()
        except Exception as exc:
            print(f"  clear_runs: {exc}", flush=True)
        vdf = VPMX.parent / f"{case}.vdfx"
        try:
            if vdf.exists():
                vdf.unlink()
        except OSError as exc:
            print(f"  vdf tenuto aperto: {exc}", flush=True)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"  scritto {OUT}", flush=True)
    print("FATTO", flush=True)


if __name__ == "__main__":
    sys.exit(main())
