"""Fase 4b - Allinea ALLOCATE AVAILABLE al comportamento di Vensim.

Dal 2030 il modello produce `Hourly available supply by Supplier[Summer,Hour,Hydro]`
negativa (Hydro decrese hourly supply summer supera l'inflow estivo). Vensim
accetta la richiesta negativa e dispaccia 0 per quell'elemento; PySD invece
solleva::

    ValueError: There are some negative request values.

Verificato sul .vpmx pubblicato (scenario Base, M7/H21):

    Hourly available supply by Supplier[M7,H21,Hydro]  2050 = -1.0858
    Electricity dispatched[M7,H21,Hydro]               2050 = +0.0000

Questo script inserisce nel modello tradotto un wrapper che azzera le richieste
negative prima di delegare a PySD, riproducendo il risultato del .vpmx.

Idempotente: eseguirlo due volte e' un no-op.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import sure_paths as paths  # noqa: E402

PY = paths.pysd_py()

IMPORT_LINE = "from pysd.py_backend.allocation import allocate_available\n"
MARKER = "# allocate_nonneg:"

WRAPPER = f'''from pysd.py_backend.allocation import (
    allocate_available as _pysd_allocate_available,
)


def allocate_available(request, pp, avail):  {MARKER} wrapper
    """ALLOCATE AVAILABLE con richieste negative trattate come 0, come Vensim.

    Vensim non dispaccia nulla per un'offerta negativa (e non segnala errore),
    mentre PySD solleva ValueError. Il clip riproduce il .vpmx pubblicato.
    """
    if np.any(request < 0):
        request = request.clip(min=0.0)
    return _pysd_allocate_available(request, pp, avail)
'''


def main():
    src = PY.read_text(encoding="utf-8")
    if MARKER in src:
        print(f"{PY.name}: wrapper gia' presente, nessuna modifica.")
        return
    if IMPORT_LINE not in src:
        raise SystemExit(f"Import di allocate_available non trovato in {PY.name}")
    PY.write_text(src.replace(IMPORT_LINE, WRAPPER, 1), encoding="utf-8")
    print(f"{PY.name}: ALLOCATE AVAILABLE ora azzera le richieste negative.")


if __name__ == "__main__":
    main()
