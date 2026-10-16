"""Salva i vettori di offerta delle ore in cui Vensim non chiude il residuo."""
import ctypes
import os
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT / "Vensim")
DLL = ctypes.WinDLL(r"C:\Windows\System32\vendll64.dll")
DLL.vensim_command.argtypes = [ctypes.c_char_p]
DLL.vensim_command.restype = ctypes.c_int
DLL.vensim_get_data.argtypes = [
    ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
    ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_float), ctypes.c_int,
]
DLL.vensim_get_data.restype = ctypes.c_int
DLL.vensim_be_quiet(1)
assert DLL.vensim_command(b"SPECIAL>LOADMODEL|SURE.vpmx") == 1

SUPPLIERS = ["Solar", "Wind", "Nuclear", "RoR", "Hydro", "Import", "PHS", "Coal", "Waste"]
VV = (ctypes.c_float * 64)()
TT = (ctypes.c_float * 64)()
cache = {}


def series(run, label):
    key = (run, label)
    if key not in cache:
        n = DLL.vensim_get_data(run.encode(), label.encode(), b"Time", VV, TT, 64)
        years = np.asarray(TT[:n], dtype=np.float64).copy()
        vals = np.asarray(VV[:n], dtype=np.float64).copy()
        cache[key] = (years, vals)
    return cache[key]


def at(run, label, year):
    years, vals = series(run, label)
    i = int(np.argmin(np.abs(years - year)))
    return float(vals[i])


a = np.load(ROOT / "Vensim_test_runs" / "gap_base_import_residual.npy")
err = np.abs(a[:, 4] - a[:, 3])
# tutte le ore non esatte, piu' un campione di ore esatte
bad = np.flatnonzero(err > 1e-4)
rng = np.random.default_rng(1)
good = rng.choice(np.flatnonzero(err <= 1e-4), size=30, replace=False)
pick = np.concatenate([bad, good])

rows = []
for row in a[pick]:
    year, hour, month, residual, imported, cost = row
    month_s = f"M{int(month)}"
    hour_s = f"H{int(hour)}"
    q = [at("gap_base", f"Hourly available supply by Supplier[{month_s},{hour_s},{s}]", year) for s in SUPPLIERS]
    dem = at("gap_base", f"Hourly demand and PHS[{month_s},{hour_s}]", year)
    rows.append([year, hour, month, residual, imported, cost, dem, *q])

out = np.array(rows, dtype=np.float64)
np.save(ROOT / "Vensim_test_runs" / "gap_base_vectors.npy", out)
print("saved", out.shape, "bad", len(bad))
