"""Tabella residuo domestico contro importazione assegnata da Vensim."""
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

VV = (ctypes.c_float * 64)()
TT = (ctypes.c_float * 64)()
OTHERS = ["Solar", "Wind", "Nuclear", "RoR", "Hydro", "PHS", "Coal", "Waste"]
MONTHS = [f"M{i}" for i in range(1, 13)]
HOURS = [f"H{i}" for i in range(1, 25)]


def series(run, label):
    n = DLL.vensim_get_data(run.encode(), label.encode(), b"Time", VV, TT, 64)
    if n <= 0:
        raise RuntimeError(label)
    return np.asarray(TT[:n], dtype=np.float64).copy(), np.asarray(VV[:n], dtype=np.float64).copy()


for run in ("gap_base", "gap_high"):
    cost_t, cost = series(run, "Marginal cost by supplier[Import]")
    rows = []
    for m in MONTHS:
        dem = {h: series(run, f"Hourly demand and PHS[{m},{h}]")[1] for h in HOURS}
        imp = {h: series(run, f"Electricity dispatched[{m},{h},Import]")[1] for h in HOURS}
        cap = {h: np.zeros_like(dem[h]) for h in HOURS}
        for s in OTHERS:
            for h in HOURS:
                cap[h] += np.maximum(series(run, f"Hourly available supply by Supplier[{m},{h},{s}]")[1], 0)
        for hi, h in enumerate(HOURS):
            residual = dem[h] - cap[h]
            for i, year in enumerate(cost_t):
                if year < 2027:
                    continue
                r = float(residual[i])
                g = float(imp[h][i])
                if r <= 0 and g <= 0:
                    continue
                rows.append((float(year), hi + 1, int(m[1:]), r, g, float(cost[i])))
    arr = np.array(rows, dtype=np.float64)
    out = ROOT / "Vensim_test_runs" / f"{run}_import_residual.npy"
    np.save(out, arr)
    err = arr[:, 4] - np.maximum(arr[:, 3], 0)
    print(run, "rows", len(arr), "max |import-residual|", float(np.max(np.abs(err))),
          "hours import>0", int(np.sum(arr[:, 4] > 0)))
