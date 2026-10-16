"""Fase 4b - Compatibility fixes for translated SURE allocation.

The corrected native source uses ALLOCATE BY PRIORITY and clips negative
capacity itself. Only the Float64 full-capacity endpoint guard is then needed.
The older ALLOCATE AVAILABLE wrapper below remains for historical sources.

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

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import sure_paths as paths  # noqa: E402

PY = paths.pysd_py()

IMPORT_LINE = "from pysd.py_backend.allocation import allocate_available\n"
MARKER = "# allocate_nonneg:"
PRIORITY_IMPORT = "from pysd.py_backend.allocation import allocate_by_priority\n"
PRIORITY_MARKER = "# allocate_priority_endpoint:"
PRIORITY_WRAPPER = f'''from pysd.py_backend.allocation import allocate_by_priority as _pysd_allocate_by_priority


def allocate_by_priority(request, priority, width, supply):  {PRIORITY_MARKER}
    """Guard PySD 3.14.3's empty active set within roundoff of full capacity.

    The allocator can exhaust its active suppliers while a sub-ULP residue
    remains. Snap only supply within four Float64 ULPs of total capacity.
    This does not discard small positive import residuals.
    """
    total = request.sum(dim=request.dims[-1])
    near_full = (supply < total) & ((total - supply) <= 4 * np.spacing(total))
    if bool(near_full.any()):
        supply = xr.where(near_full, total, supply)
        if supply.ndim == 0:
            supply = float(supply)
    return _pysd_allocate_by_priority(request, priority, width, supply)
'''

WRAPPER = f'''from pysd.py_backend.allocation import (
    allocate_available as _pysd_allocate_available,
    allocate_by_priority as _pysd_allocate_by_priority,
)


def allocate_available(request, pp, avail):  {MARKER} wrapper
    """ALLOCATE AVAILABLE allineato a Vensim.

    Le richieste negative sono azzerate: Vensim non le dispaccia e non
    segnala errore, PySD invece solleva ValueError.

    Con profilo rettangolare e una sola ampiezza, l'ordine di merito e'
    esatto e coincide con il profilo rettangolare stretto di Vensim.
    """
    if np.any(np.asanyarray(request) < 0):
        request = request.clip(min=0.0)
    pdim = pp.dims[-1]
    ptype = np.asanyarray(pp.isel({{pdim: 0}}))
    width = np.asanyarray(pp.isel({{pdim: 2}}), dtype=float)
    widths = np.unique(np.round(width[np.isfinite(width)], 6))
    if not (ptype.size and np.all(ptype == 1) and widths.size == 1):
        return _pysd_allocate_available(request, pp, avail)
    priority = pp.isel({{pdim: 1}})
    w = float(widths[0])
    width_b = (xr.zeros_like(avail) + w) if hasattr(avail, "dims") else w
    return _pysd_allocate_by_priority(request, priority, width_b, avail)
'''


def main():
    src = PY.read_text(encoding="utf-8")
    if MARKER in src or PRIORITY_MARKER in src:
        print(f"{PY.name}: wrapper gia' presente, nessuna modifica.")
        return
    if IMPORT_LINE not in src:
        tree = ast.parse(src)
        direct = any(
            isinstance(node, ast.ImportFrom)
            and node.module == "pysd.py_backend.allocation"
            and any(item.name == "allocate_by_priority" for item in node.names)
            for node in tree.body
        )
        if direct and not any(
            isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "allocate_available" for node in ast.walk(tree)
        ):
            if PRIORITY_IMPORT not in src:
                raise SystemExit("Unexpected ALLOCATE BY PRIORITY import layout")
            PY.write_text(src.replace(PRIORITY_IMPORT, PRIORITY_WRAPPER, 1), encoding="utf-8")
            print(f"{PY.name}: ALLOCATE BY PRIORITY nativo + guardia arrotondamento a piena capacita'.")
            return
        raise SystemExit(f"Import di allocate_available non trovato in {PY.name}")
    PY.write_text(src.replace(IMPORT_LINE, WRAPPER, 1), encoding="utf-8")
    print(f"{PY.name}: ALLOCATE AVAILABLE allineato a Vensim (clip + merito rettangolare).")


if __name__ == "__main__":
    main()
