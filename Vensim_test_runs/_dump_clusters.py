"""Dispatch completo, inclusi i valori negativi, su tre ore rappresentative."""
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

def at(label, year):
    n = DLL.vensim_get_data(b"gap_base", label.encode(), b"Time", VV, TT, 64)
    years = np.asarray(TT[:n], dtype=float)
    vals = np.asarray(VV[:n], dtype=float)
    i = int(np.argmin(np.abs(years - year)))
    return float(vals[i])

for year, month, hour in ((2038, "M1", "H5"), (2046, "M11", "H2"), (2027, "M4", "H12")):
    dem = at(f"Hourly demand and PHS[{month},{hour}]", year)
    print(f"\n{year} {month} {hour} demand={dem:.8f}")
    for s in SUPPLIERS:
        sup = at(f"Hourly available supply by Supplier[{month},{hour},{s}]", year)
        dis = at(f"Electricity dispatched[{month},{hour},{s}]", year)
        print(f"  {s:8} sup={sup: .8f} dis={dis: .8f} d={dis-sup: .8f}")
