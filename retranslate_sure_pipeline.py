"""Pipeline per (ri)tradurre SURE -> PySD a partire da Vensim/SURE.mdl + SURE.vpmx.

Varianti
--------
Tutti gli artefatti generati sono suffissati dalla variante scelta (vedi
`sure_paths.py`), cosi' una nuova traduzione non sovrascrive quella esistente:

    --variant ""    -> Vensim/SURE_pysd.mdl,    SURE_pysd.py,    constants_ref.pkl
    --variant v2    -> Vensim/SURE_pysd_v2.mdl, SURE_pysd_v2.py, constants_ref_v2.pkl

Passi (ordine obbligatorio)
---------------------------
  1. pysd_export_vdf.py        # .vdfx -> .csv  (serve vendll64.dll)
  2. patch_model_sure.py       # SURE.mdl -> SURE_pysd<sfx>.mdl + *_pysd<sfx>.csv
  3. _translate.py             # pysd.read_vensim -> SURE_pysd<sfx>.py
  4. fix_selfref_sure.py       # fix self-ref array
  4b. fix_allocate_sure.py     # ALLOCATE AVAILABLE: richieste negative -> 0
  5. extract_constants_sure.py # costanti calibrate da SURE.vpmx -> constants_ref<sfx>.pkl
  6. (opz.) patch_hotpaths_sure.py
  7. validate_coherence_sure.py --variant <sfx>

Uso
---
  # Diagnosi / presenza delle leve nei file di una variante
  .\\.venv\\Scripts\\python.exe retranslate_sure_pipeline.py --check --variant v2

  # Ritraduzione completa in una nuova variante (non tocca i file esistenti)
  .\\.venv\\Scripts\\python.exe retranslate_sure_pipeline.py --run --variant v2
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import sure_paths as paths  # noqa: E402

VENSIM = paths.VENSIM
SRC_MDL = paths.SRC_MDL
PY = paths.VENV_PY

# Input usati dalle pagine Risultati (union delle INPUT_GRID)
RESULTS_INPUTS = [
    # PV e Batterie
    "PV rebate cantonal",
    "FiT",
    "Battery Rebate",
    "PV rebate federal",
    "PV reg scenario",
    "Energy Community scenario",
    # Risanamento
    "Grant share HP",
    "Grant share PelletBoiler",
    "Grant share DH",
    "Retrofit incentive input",
    "CO2 tax",
    "MuKEn scenario",
    # Veicoli
    "EV charger incentive input",
    "CO2 coefficient ICE",
    "ICE ban year",
    "EV annual cost reduction input",
    "ICE fuel price input",
    # Elettricità (oltre overlap PV)
    "Seasonal PHS annual production 2050",
    "Additional annual inflow for Ticino",
]

STEPS = [
    ("pysd_export_vdf.py", "Export .vdfx -> .csv via DLL"),
    ("patch_model_sure.py", "SURE.mdl -> SURE_pysd.mdl + *_pysd.csv"),
    ("_translate.py", "pysd.read_vensim -> SURE_pysd.py"),
    ("fix_selfref_sure.py", "Fix self-referential array eqs"),
    ("fix_allocate_sure.py", "ALLOCATE AVAILABLE: richieste negative -> 0 (come Vensim)"),
    ("extract_constants_sure.py", "Costanti calibrate da SURE.vpmx -> constants_ref.pkl"),
]


def _eq_present(text: str, name: str) -> bool:
    return bool(re.search(r"(?m)^" + re.escape(name) + r"\s*=", text))


def _py_present(text: str, name: str) -> bool:
    return f'name="{name}"' in text


def check_file(path: Path, kind: str) -> dict[str, bool]:
    if not path.exists():
        return {n: False for n in RESULTS_INPUTS}
    enc = "latin-1" if path.suffix.lower() == ".mdl" else "utf-8"
    text = path.read_text(encoding=enc, errors="replace")
    pred = _eq_present if kind == "mdl" else _py_present
    return {n: pred(text, n) for n in RESULTS_INPUTS}


def print_check():
    pysd_mdl, pysd_py = paths.pysd_mdl(), paths.pysd_py()
    print(f"=== Presenza input Risultati ({paths.variant() or 'default'}) ===\n")
    rows = {
        "src": check_file(SRC_MDL, "mdl"),
        "mdl": check_file(pysd_mdl, "mdl"),
        "py": check_file(pysd_py, "py"),
    }
    hdr = f"{'input':42} {'SURE.mdl':10} {pysd_mdl.name:22} {pysd_py.name:22}"
    print(hdr)
    print("-" * len(hdr))
    n_ok_py = 0
    for name in RESULTS_INPUTS:
        a, b, c = rows["src"][name], rows["mdl"][name], rows["py"][name]
        if c:
            n_ok_py += 1
        print(f"{name:42} {'YES' if a else 'no':10} "
              f"{'YES' if b else 'no':22} {'YES' if c else 'no':22}")
    print(f"\nIn {pysd_py.name}: {n_ok_py}/{len(RESULTS_INPUTS)}.")
    missing_src = [n for n in RESULTS_INPUTS if not rows["src"][n]]
    if missing_src:
        print("\nNON presenti in SURE.mdl (leva rimossa dal modello Vensim):")
        for n in missing_src:
            print("  -", n)
    stale = [n for n in RESULTS_INPUTS if rows["src"][n] and not rows["mdl"][n]]
    if stale:
        print(f"\nIn SURE.mdl ma NON in {pysd_mdl.name} -> traduzione obsoleta: {stale}")


def backup():
    """Copia gli artefatti della variante corrente (se esistono) in uno snapshot."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sfx = paths.variant() or "default"
    bak_dir = VENSIM / f"_backup_retranslate_{sfx}_{stamp}"
    targets = [paths.pysd_mdl(), paths.pysd_py(), paths.const_pkl()]
    existing = [p for p in targets if p.exists()]
    if not existing:
        print(f"Nessun artefatto preesistente per la variante '{sfx}': niente backup.")
        return None
    bak_dir.mkdir(parents=True, exist_ok=True)
    for p in existing:
        shutil.copy2(p, bak_dir / p.name)
        print(f"backup {p.name} -> {bak_dir.name}")
    return bak_dir


def run_steps(skip_export=False):
    if not PY.exists():
        raise SystemExit(f"Python venv non trovato: {PY}")
    print(paths.describe(), "\n")
    bak = backup()
    steps = [s for s in STEPS if not (skip_export and s[0] == "pysd_export_vdf.py")]
    for script, desc in steps:
        path = ROOT / script
        if not path.exists():
            raise SystemExit(f"Manca {script}")
        print("=" * 70)
        print(f"STEP: {script} - {desc}")
        print("=" * 70)
        rc = subprocess.call([str(PY), "-u", str(path)], cwd=str(ROOT))
        if rc != 0:
            raise SystemExit(f"Fallito {script} (exit {rc})."
                             + (f" Ripristina da {bak}" if bak else ""))
    print("\n=== Pipeline completata. Controllo namespace: ===\n")
    print_check()
    print(f"\nProssimo passo: python validate_coherence_sure.py "
          f"--variant {paths.variant() or ''}".rstrip())


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="Tabella presenza input in mdl/py")
    g.add_argument("--prepare", action="store_true", help="Backup + check (nessuna ritraduzione)")
    g.add_argument("--run", action="store_true", help="Esegue export->patch->translate->fix->extract")
    ap.add_argument("--variant", default=None,
                    help="Suffisso degli artefatti generati (es. v2). Default: SURE_VARIANT")
    ap.add_argument("--skip-export", action="store_true",
                    help="Salta l'export .vdfx -> .csv (riusa i CSV gia' presenti)")
    args = ap.parse_args()
    if args.variant is not None:
        paths.set_variant(args.variant)

    if args.check:
        print_check()
    elif args.prepare:
        backup()
        print()
        print_check()
    else:
        run_steps(skip_export=args.skip_export)


if __name__ == "__main__":
    main()
