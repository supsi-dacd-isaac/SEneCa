"""Fase 5 - Estrae le costanti calibrate da SURE.vpmx.

Molte costanti in SURE.mdl sono scritte come 0 (o NaN) ma portano un valore
calibrato nel modello pubblicato SURE.vpmx. pysd traduce lo 0 -> la traiettoria
diverge nel tempo. Questo script:

  1. enumera le costanti del modello pysd tradotto (dipendenze vuote) e ne legge
     il valore "da .mdl";
  2. carica SURE.vpmx via DLL ctypes (come app.py), fissa i 3 input scenario a 0
     e lancia un run 2011-2050;
  3. legge da Vensim il valore di ogni costante (scalare o per-elemento);
  4. registra in constants_ref.pkl SOLO le costanti il cui valore vpmx differisce
     da quello del .mdl (le calibrate), piu' un report dei mismatch.

Uso:
    .\\.venv\\Scripts\\python.exe extract_constants_sure.py
"""
import ctypes
import itertools
import pickle
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import sure_paths as paths  # noqa: E402
import sure_pysd as sp  # noqa: E402

VENSIM = paths.VENSIM
MODEL_VPMX = paths.MODEL_VPMX
DLL_PATH = paths.DLL_PATH

CONTROL = {"INITIAL TIME", "FINAL TIME", "TIME STEP", "SAVEPER", "TIME",
           "FINAL TIME STEP"}
REL_TOL, ABS_TOL = 1e-4, 1e-9


def _enc(text):
    return text.encode("mbcs")


def cmd(dll, command):
    rc = dll.vensim_command(_enc(command))
    if rc != 1:
        raise RuntimeError(f"Comando Vensim fallito (rc={rc}): {command}")


def get_value(dll, run, varname):
    """Legge il valore (costante -> serie piatta) di varname; ritorna float o None."""
    maxn = 4096
    vval = (ctypes.c_float * maxn)()
    tval = (ctypes.c_float * maxn)()
    n = dll.vensim_get_data(_enc(run), _enc(varname), b"Time", vval, tval, maxn)
    if n <= 0:
        return None
    return float(vval[0])


def enumerate_constants(model):
    """real_name -> {'py','dims','coords','mdl'} per le costanti (deps vuote)."""
    ns = model._namespace
    deps = model.dependencies
    sd = model.components._subscript_dict
    out = {}
    for real, py in ns.items():
        if real in CONTROL or real in sp.SCENARIO_INPUTS:
            continue
        if py not in deps:
            continue
        d = deps[py]
        # Costante = nessuna dipendenza, oppure solo auto-riferimento (es. Coeff
        # VeryLow[DFH]=Coeff VeryLow[SFH], calibrata ma azzerata nel .mdl).
        # Esclude stock (deps con 'step'/'initial') e variabili calcolate.
        if not isinstance(d, dict):
            continue
        if set(d.keys()) - {py}:
            continue
        comp = getattr(model.components, py, None)
        if comp is None:
            continue
        try:
            val = comp()
        except Exception:
            continue
        dims = list(getattr(val, "dims", []))
        coords = {d: list(sd[d]) for d in dims} if dims else {}
        out[real] = {"py": py, "dims": dims, "coords": coords, "mdl": val}
    return out


def main():
    out_pkl = paths.const_pkl()
    report_csv = paths.const_report()
    print(paths.describe())
    print("Caricamento modello pysd (non potato) per enumerare le costanti ...")
    model = sp.load_model(prune=False)
    consts = enumerate_constants(model)
    print(f"Costanti candidate: {len(consts)}")

    dll = ctypes.WinDLL(DLL_PATH)
    dll.vensim_command.argtypes = [ctypes.c_char_p]
    dll.vensim_command.restype = ctypes.c_int
    dll.vensim_get_data.argtypes = [
        ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_float), ctypes.c_int]
    dll.vensim_get_data.restype = ctypes.c_int

    import os
    os.chdir(VENSIM)
    cmd(dll, f"SPECIAL>LOADMODEL|{MODEL_VPMX}")
    run = "const_extract"
    cmd(dll, f"SIMULATE>RUNNAME|{run}")
    # Stesso protocollo della ref Vensim (python_runs): azzera solo le 3 leve
    # dello scenario s1. Le altre costanti restano ai default del .vpmx.
    extract_setval = [
        "PV rebate cantonal",
        "FiT",
        "Energy Community scenario",
    ]
    for name in extract_setval:
        rc = dll.vensim_command(_enc(f"SIMULATE>SETVAL|{name}=0"))
        if rc != 1:
            print(f"  skip SETVAL (non nel vpmx): {name}")
    cmd(dll, "MENU>RUN|O")
    print("Run vpmx completato. Lettura costanti dalla DLL ...")

    def read_elem(real, combo):
        key = real if not combo else f"{real}[{','.join(combo)}]"
        v = get_value(dll, run, key)
        if v is not None or not combo:
            return v
        # fallback self-reference DFH->SFH
        combo2 = tuple("SFH" if c == "DFH" else c for c in combo)
        if combo2 != combo:
            return get_value(dll, run, f"{real}[{','.join(combo2)}]")
        return None

    out = {}
    rows = []
    not_read = 0
    for real, m in consts.items():
        dims, coords, mdl = m["dims"], m["coords"], m["mdl"]
        if not dims:
            v = read_elem(real, ())
            if v is None:
                not_read += 1
                continue
            mdl_v = float(mdl)
            if abs(v - mdl_v) > max(ABS_TOL, REL_TOL * abs(v)):
                out[real] = {"dims": [], "values": v}
                rows.append((real, "", mdl_v, v, abs(v - mdl_v)))
            continue

        coord_lists = [coords[d] for d in dims]
        shape = [len(c) for c in coord_lists]
        arr = np.array(mdl.values, dtype=float).reshape(shape)
        vpm = np.array(arr, dtype=float)
        changed = False
        for idx in itertools.product(*[range(s) for s in shape]):
            combo = tuple(coord_lists[k][idx[k]] for k in range(len(dims)))
            v = read_elem(real, combo)
            if v is None:
                continue
            if abs(v - arr[idx]) > max(ABS_TOL, REL_TOL * abs(v)):
                vpm[idx] = v
                changed = True
        if changed:
            out[real] = {"dims": dims, "coords": coords, "values": vpm}
            n_diff = int(np.sum(np.abs(vpm - arr) > ABS_TOL))
            rows.append((real, ",".join(dims), float(np.abs(arr).sum()),
                         float(np.abs(vpm).sum()), n_diff))

    with open(out_pkl, "wb") as f:
        pickle.dump(out, f)
    if rows:
        pd.DataFrame(rows, columns=["real", "dims", "mdl", "vpmx", "n_diff/abs"]).to_csv(
            report_csv, index=False)

    print(f"\nCostanti non leggibili dalla DLL: {not_read}")
    print(f"Costanti calibrate (mdl != vpmx): {len(out)} -> {out_pkl}")
    for real in list(out)[:30]:
        print("  -", real)
    if len(out) > 30:
        print(f"  ... e altre {len(out) - 30}")


if __name__ == "__main__":
    main()
