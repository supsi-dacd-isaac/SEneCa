"""need di import (centrale piu' care piene) contro quanto Vensim assegna all'import."""
import ctypes
import os
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT / "Vensim")
DLL = ctypes.WinDLL(r"C:\Windows\System32\vendll64.dll")
DLL.vensim_command.argtypes = [ctypes.c_char_p]
DLL.vensim_command.restype = ctypes.c_int
DLL.vensim_get_data.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
    ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_float), ctypes.c_int]
DLL.vensim_get_data.restype = ctypes.c_int
DLL.vensim_be_quiet(1)
assert DLL.vensim_command(b"SPECIAL>LOADMODEL|SURE.vpmx") == 1
VV = (ctypes.c_float * 64)()
TT = (ctypes.c_float * 64)()
MONTHS = [f"M{i}" for i in range(1, 13)]
HOURS = [f"H{i}" for i in range(1, 25)]
OTHERS = ["Solar", "Wind", "Nuclear", "RoR", "Hydro", "PHS", "Coal", "Waste"]

def series(run, label):
    n = DLL.vensim_get_data(run.encode(), label.encode(), b"Time", VV, TT, 64)
    if n <= 0:
        raise RuntimeError(label)
    return np.asarray(VV[:n], dtype=float).copy()

for run in ("gap_high",):
    rows = []
    for m in MONTHS:
        dem = {h: series(run, f"Hourly demand and PHS[{m},{h}]") for h in HOURS}
        imp = {h: series(run, f"Electricity dispatched[{m},{h},Import]") for h in HOURS}
        cap = {h: np.zeros_like(dem[h]) for h in HOURS}
        coal = {h: series(run, f"Hourly available supply by Supplier[{m},{h},Coal]") for h in HOURS}
        for s in OTHERS:
            for h in HOURS:
                cap[h] += np.maximum(series(run, f"Hourly available supply by Supplier[{m},{h},{s}]"), 0)
        for h in HOURS:
            need = dem[h] - cap[h]
            for i, year in enumerate(range(2011, 2011 + len(need))):
                if year < 2027 or not (0.0002 < need[i] < 0.006):
                    continue
                rows.append((float(need[i]), float(imp[h][i]), float(coal[h][i]), year, m, h))
    rows.sort()
    print(run, "ore con need import in (0.0002, 0.006):", len(rows))
    for need, got, coal, year, m, h in rows:
        print(f"  need={need:.5f} import={got:.5f} coal={coal:.5f} {year} {m} {h}")
