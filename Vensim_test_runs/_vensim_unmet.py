"""Quanto resta scoperto in Vensim quando l'importazione non viene usata."""
import ctypes
import os
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
VENSIM = ROOT / "Vensim"
DLL = ctypes.WinDLL(r"C:\Windows\System32\vendll64.dll")
DLL.vensim_command.argtypes = [ctypes.c_char_p]
DLL.vensim_command.restype = ctypes.c_int
DLL.vensim_get_data.argtypes = [
    ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
    ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_float), ctypes.c_int]
DLL.vensim_get_data.restype = ctypes.c_int
DLL.vensim_be_quiet.argtypes = [ctypes.c_int]
DLL.vensim_be_quiet(1)
os.chdir(VENSIM)
assert DLL.vensim_command(b"SPECIAL>LOADMODEL|SURE.vpmx") == 1

MONTHS = [f"M{i}" for i in range(1, 13)]
HOURS = [f"H{i}" for i in range(1, 25)]
SUPPLIERS = ["Solar", "Wind", "Nuclear", "RoR", "Hydro", "Import", "PHS", "Coal", "Waste"]
VV = (ctypes.c_float * 64)()
TT = (ctypes.c_float * 64)()


def series(run, label):
    n = DLL.vensim_get_data(run.encode(), label.encode(), b"Time", VV, TT, 64)
    if n <= 0:
        raise RuntimeError(label)
    return np.asarray(VV[:n], dtype=float)


def summarize(run):
    unmet = []
    used_import_short = []
    zero_import_short = []
    for m in MONTHS:
        dem = {h: series(run, f"Hourly demand and PHS[{m},{h}]") for h in HOURS}
        disp = {
            (h, s): series(run, f"Electricity dispatched[{m},{h},{s}]")
            for h in HOURS for s in SUPPLIERS
        }
        sup = {
            (h, s): series(run, f"Hourly available supply by Supplier[{m},{h},{s}]")
            for h in HOURS for s in ("Hydro", "Import")
        }
        for h in HOURS:
            demand = dem[h]
            total = sum(disp[(h, s)] for s in SUPPLIERS)
            gap = demand - total
            domestic = demand * 0
            for s in SUPPLIERS:
                if s == "Import":
                    continue
                domestic = domestic + np.maximum(sup[(h, "Hydro")] * 0 + disp[(h, s)], 0)
            # capacita' nazionale = somma dispacciata degli altri, perche' in merito stretto sono pieni
            short = demand - (total - disp[(h, "Import")])
            for i, year in enumerate(range(2011, 2011 + len(gap))):
                if year < 2027:
                    continue
                unmet.append(float(gap[i]))
                rel = float(short[i] / demand[i]) if demand[i] else np.nan
                if disp[(h, "Import")][i] > 1e-6:
                    used_import_short.append((float(short[i]), rel, float(demand[i]), year, m, h))
                elif short[i] > 1e-4:
                    zero_import_short.append((year, m, h, float(short[i]), rel, float(demand[i])))
    unmet = np.array(unmet)
    print(f"\n{run}: ore dal 2027 {unmet.size}")
    print(f"  non coperto  max={unmet.max():.4e}  p99={np.quantile(unmet, 0.99):.4e}  medio={unmet.mean():.4e}")
    if used_import_short:
        shorts = np.array([r[0] for r in used_import_short])
        rels = np.array([r[1] for r in used_import_short])
        print(f"  ore con import>0: {len(shorts)}  residuo min={shorts.min():.4e}  rel min={rels.min():.4e} med={np.median(rels):.4e}")
        small = sorted(used_import_short, key=lambda r: r[1])[:1]
        print("  import usato, relativa piu' piccola:", small[0])
        examples.append((run, "used", small[0][3], small[0][4], small[0][5]))
    zero_import_short.sort(key=lambda r: -r[4])
    print(f"  ore con import=0 ma residuo>1e-4: {len(zero_import_short)}")
    for row in zero_import_short[:8]:
        print("   ", row)
    if zero_import_short:
        examples.append((run, "miss", zero_import_short[0][0], zero_import_short[0][1], zero_import_short[0][2]))


examples = []
for run in ("gap_base", "gap_high"):
    summarize(run)

    # Per i residui piccoli: Vensim assegna l'import o si ferma prima?
    band = []
    for m in MONTHS:
        for h in HOURS:
            demand = series(run, f"Hourly demand and PHS[{m},{h}]")
            total = sum(series(run, f"Electricity dispatched[{m},{h},{s}]") for s in SUPPLIERS)
            imp = series(run, f"Electricity dispatched[{m},{h},Import]")
            coal = series(run, f"Hourly available supply by Supplier[{m},{h},Coal]")
            for i, year in enumerate(range(2011, 2011 + len(demand))):
                if year < 2027:
                    continue
                domestic = total[i] - imp[i]
                short = demand[i] - domestic
                if 0 < short < 0.02:
                    band.append((float(short), float(imp[i]), float(coal[i]), float(demand[i])))
    band = np.array(band)
    missed = band[band[:, 1] <= 1e-8]
    hit = band[band[:, 1] > 1e-8]
    print(f"  residuo in (0, 0.02): {len(band)}  di cui import=0: {len(missed)}  import>0: {len(hit)}")
    if len(missed):
        print(f"    miss residuo min/max {missed[:,0].min():.4e}/{missed[:,0].max():.4e}  carbone>0 {(missed[:,2] > 1e-8).sum()}")
    tiny = band[(band[:, 1] > 1e-8) & (band[:, 1] <= 0.0035)]
    print(f"    hit con import<=0.0035: {len(tiny)}  carbone>0 {(tiny[:,2] > 1e-8).sum() if len(tiny) else 0}")
