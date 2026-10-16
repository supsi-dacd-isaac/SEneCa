"""Offerta e dispacciamento sulle ore in cui import e residuo divergono."""
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


def at(run, label, year):
    n = DLL.vensim_get_data(run.encode(), label.encode(), b"Time", VV, TT, 64)
    years = np.asarray(TT[:n], dtype=float)
    vals = np.asarray(VV[:n], dtype=float)
    i = int(np.argmin(np.abs(years - year)))
    return float(vals[i])


HOURS = [
    ("gap_base", 2043, "M11", "H1"),
    ("gap_base", 2046, "M2", "H14"),
    ("gap_base", 2040, "M10", "H1"),
    ("gap_base", 2038, "M4", "H2"),
    ("gap_base", 2039, "M10", "H2"),
]
for run, year, month, hour in HOURS:
    dem = at(run, f"Hourly demand and PHS[{month},{hour}]", year)
    print(f"\n{year} {month} {hour} demand={dem:.8f}")
    total = 0.0
    for s in SUPPLIERS:
        sup = at(run, f"Hourly available supply by Supplier[{month},{hour},{s}]", year)
        dis = at(run, f"Electricity dispatched[{month},{hour},{s}]", year)
        total += dis
        flag = "" if abs(sup - dis) < 1e-6 or s == "Import" else " PARTIAL"
        print(f"  {s:8} sup={sup: .8f} dis={dis: .8f}{flag}")
    print(f"  sumdis={total:.8f} unmet={dem-total:.8f}")
