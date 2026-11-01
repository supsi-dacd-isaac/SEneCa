"""Fase 4c - Implementa le funzioni Vensim non supportate da PySD 3.14.3.

PySD traduce ``GAMMA LN(x)`` in ``not_implemented_function("gamma_ln", x)``,
che solleva un errore alla valutazione. In SURE compare solo nella
log-verosimiglianza NR (obiettivo di calibrazione, non nella dinamica), ma il
modello completo deve restare eseguibile. ``scipy.special.gammaln`` e' il
logaritmo naturale di |Gamma(x)|, la stessa definizione di Vensim per x > 0,
e conserva le coordinate degli xarray.

Idempotente: eseguirlo due volte e' un no-op.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import sure_paths as paths  # noqa: E402

PY = paths.pysd_py()
IMPORT_LINE = "from scipy.special import gammaln  # fix_functions: GAMMA LN\n"
CALL = re.compile(r'not_implemented_function\(\s*"gamma_ln",\s*')


def main():
    src = PY.read_text(encoding="utf-8")
    src, n = CALL.subn("gammaln(", src)
    if n and IMPORT_LINE not in src:
        src = src.replace("import xarray as xr\n", "import xarray as xr\n" + IMPORT_LINE, 1)
    if "not_implemented_function(" in src.split("from pysd.py_backend.functions import", 1)[-1].split(")", 1)[1]:
        raise SystemExit("Restano funzioni Vensim non implementate nel modello tradotto")
    PY.write_text(src, encoding="utf-8")
    print(f"{PY.name}: GAMMA LN -> scipy.special.gammaln ({n} chiamate)")


if __name__ == "__main__":
    main()
