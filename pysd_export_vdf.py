"""Fase 1 - Export dei dati esterni.

Il modello SURE.mdl legge i suoi input tramite GET VDF DATA(...) da file .vdfx
binari, che PySD non sa leggere. Questo script esporta ogni .vdfx referenziato
in un file .tab (tab-delimited) tramite il comando VDF2TAB della DLL Vensim.

Formato prodotto (per <nome>.tab):
    Time<TAB>2011<TAB>2012<TAB>...
    Serie[elem]<TAB>v1<TAB>v2<TAB>...
    ...

Questi .tab sono poi la sorgente per patch_model_sure.py, che riscrive le
equazioni in GET DIRECT DATA leggendo CSV riordinati.

Esecuzione:
    .\\.venv\\Scripts\\python.exe pysd_export_vdf.py
"""
import csv
import ctypes
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))  # root in PYTHONPATH (regola utente)

VENSIM = ROOT / "Vensim"
SRC_MDL = VENSIM / "SURE.mdl"
MODEL_VPMX = VENSIM / "SURE.vpmx"
DLL_PATH = r"C:\Windows\System32\vendll64.dll"
ENC = "latin-1"


def _enc(text):
    return text.encode("mbcs")


def cmd(dll, command):
    rc = dll.vensim_command(_enc(command))
    if rc != 1:
        raise RuntimeError(f"Comando Vensim fallito (rc={rc}): {command}")


def find_vdfx_files(mdl_text):
    """Nomi distinti dei file .vdfx referenziati dai GET VDF DATA."""
    files = re.findall(r"GET VDF DATA\(\s*'([^']+\.vdfx)'", mdl_text)
    # preserva l'ordine di prima apparizione
    seen, out = set(), []
    for f in files:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def main():
    text = SRC_MDL.read_text(encoding=ENC)
    vdfx_files = find_vdfx_files(text)
    print(f"File .vdfx referenziati ({len(vdfx_files)}):")
    for f in vdfx_files:
        print("  -", f)

    dll = ctypes.WinDLL(DLL_PATH)
    dll.vensim_command.argtypes = [ctypes.c_char_p]
    dll.vensim_command.restype = ctypes.c_int

    os.chdir(VENSIM)
    cmd(dll, f"SPECIAL>LOADMODEL|{MODEL_VPMX}")
    print("Modello caricato.")

    for vdfx in vdfx_files:
        stem = vdfx[:-5]
        tab = stem + ".tab"
        out_csv = stem + ".csv"
        if Path(tab).exists():
            Path(tab).unlink()
        rc = dll.vensim_command(_enc(f"MENU>VDF2TAB|{vdfx}|{tab}||"))
        if rc != 1 or not Path(tab).exists():
            print(f"  !! export fallito per {vdfx} (rc={rc})")
            continue
        # Converte il .tab (tab-delimited, non quotato) nel formato di riferimento:
        # CSV comma-delimited con etichette quotate, header "Time",anni...
        n_rows = tab_to_csv(tab, out_csv)
        Path(tab).unlink()
        print(f"  OK {vdfx} -> {out_csv}  ({n_rows} righe dati, {Path(out_csv).stat().st_size} byte)")


def tab_to_csv(tab_path, csv_path):
    """Riscrive un file VDF2TAB (tab-delimited) come CSV comma-delimited.

    csv.writer quota automaticamente le etichette che contengono virgole
    (es. 'Serie[a,b,c]'), replicando il formato dei sorgenti di riferimento.
    """
    n_data = 0
    with open(tab_path, encoding="utf-8", errors="replace", newline="") as fin, \
            open(csv_path, "w", encoding="utf-8", newline="") as fout:
        writer = csv.writer(fout)
        for line in fin:
            line = line.rstrip("\r\n")
            if not line:
                continue
            fields = line.split("\t")
            writer.writerow(fields)
            if fields and fields[0].strip().lower() != "time":
                n_data += 1
    return n_data


if __name__ == "__main__":
    main()
