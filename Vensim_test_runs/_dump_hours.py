"""Confronta offerta e dispacciamento Vensim su ore rappresentative."""
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


def series(run, label):
    n = DLL.vensim_get_data(run.encode(), label.encode(), b"Time", VV, TT, 64)
    if n <= 0:
        raise RuntimeError(label)
    years = np.asarray(TT[:n], dtype=float)
    vals = np.asarray(VV[:n], dtype=float)
    return years, vals


def at(run, label, year):
    years, vals = series(run, label)
    i = int(np.argmin(np.abs(years - year)))
    return float(vals[i]), float(years[i])


HOURS = [
    ("gap_base", 2043, "M3", "H18"),
    ("gap_base", 2036, "M10", "H7"),
    ("gap_base", 2027, "M4", "H2"),
    ("gap_base", 2039, "M4", "H23"),
    ("gap_base", 2035, "M10", "H3"),
    ("gap_base", 2034, "M11", "H18"),
    ("gap_high", 2038, "M12", "H21"),
    ("gap_high", 2027, "M4", "H7"),
]

for run, year, month, hour in HOURS:
    dem, y = at(run, f"Hourly demand and PHS[{month},{hour}]", year)
    price, _ = at(run, f"Electricity market price[{month},{hour}]", year)
    print(f"\n{run} {year} {month} {hour}  demand={dem:.8f} price={price:.4f} time={y}")
    total_sup = 0.0
    total_dis = 0.0
    for s in SUPPLIERS:
        sup, _ = at(run, f"Hourly available supply by Supplier[{month},{hour},{s}]", year)
        dis, _ = at(run, f"Electricity dispatched[{month},{hour},{s}]", year)
        cost, _ = at(run, f"Marginal cost by supplier[{s}]", year)
        total_sup += max(sup, 0.0)
        total_dis += dis
        print(f"  {s:8} cost={cost:8.3f} supply={sup: .8f} dispatch={dis: .8f} gap={sup - dis: .8f}")
    print(f"  sum disp={total_dis:.8f}  unmet={dem - total_dis:.8f}  sum pos supply={total_sup:.8f}")
