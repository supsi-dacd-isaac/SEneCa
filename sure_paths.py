"""Percorsi degli artefatti della traduzione SURE -> PySD, con supporto varianti.

Una "variante" e' un suffisso applicato a tutti i file generati dalla pipeline di
ritraduzione, cosi' che piu' traduzioni possano convivere nella stessa cartella:

    variante ""   (default)  -> Vensim/SURE_pysd.mdl,    SURE_pysd.py,    constants_ref.pkl
    variante "v6"            -> Vensim/SURE_pysd_v6.mdl, SURE_pysd_v6.py, constants_ref_v6.pkl

La variante si sceglie con la variabile d'ambiente ``SURE_VARIANT`` (oppure con
``--variant`` negli script che la espongono). Senza indicazioni si usa v6,
la base supportata dal modello corretto.
Le varianti sperimentali non vengono selezionate automaticamente.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENSIM = ROOT / "Vensim"

SRC_MDL = VENSIM / "SURE.mdl"
MODEL_VPMX = VENSIM / "SURE.vpmx"
DLL_PATH = r"C:\Windows\System32\vendll64.dll"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"

_ENV_VAR = "SURE_VARIANT"


def available_variants() -> list[str]:
    """Traduzioni complete in Vensim/: '' = SURE_pysd.py, 'v6' = SURE_pysd_v6.py, ..."""
    found = []
    for p in sorted(VENSIM.glob("SURE_pysd*.py")):
        v = p.stem[len("SURE_pysd"):].lstrip("_")
        if (ROOT / f"constants_ref{'_' + v if v else ''}.pkl").is_file():
            found.append(v)
    return found


def variant() -> str:
    """Variante esplicita di preparazione, oppure la base supportata v6."""
    name = os.environ.get(_ENV_VAR, "").strip().strip("_")
    if name:
        return name
    return "v6"


def set_variant(name: str | None) -> str:
    """Imposta la variante corrente (anche per i sottoprocessi via os.environ)."""
    os.environ[_ENV_VAR] = (name or "").strip().strip("_")
    return variant()


def suffix() -> str:
    v = variant()
    return f"_{v}" if v else ""


def pysd_mdl() -> Path:
    return VENSIM / f"SURE_pysd{suffix()}.mdl"


def pysd_py() -> Path:
    return VENSIM / f"SURE_pysd{suffix()}.py"


def const_pkl() -> Path:
    return ROOT / f"constants_ref{suffix()}.pkl"


def const_report() -> Path:
    return ROOT / f"constants_mismatch{suffix()}.csv"


def data_csv(vdfx_name: str) -> str:
    """Nome del CSV riordinato letto da GET DIRECT DATA per un dato .vdfx."""
    stem = vdfx_name[:-5] if vdfx_name.lower().endswith(".vdfx") else vdfx_name
    return f"{stem}_pysd{suffix()}.csv"


def describe() -> str:
    v = variant() or "(default)"
    return (f"variante={v}\n"
            f"  mdl  : {pysd_mdl().name}\n"
            f"  py   : {pysd_py().name}\n"
            f"  const: {const_pkl().name}")
