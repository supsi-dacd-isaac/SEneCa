"""Pre-calcolo delle 1215 combinazioni "Riscaldamento e Risanamento".

Wrapper sottile sul motore generico section_engine, con la config della sezione.

Esempi:
    # test veloce (2 combo)
    .\\.venv\\Scripts\\python.exe pv_batteries\\precompute_risanamento.py --limit 2
    # batch completo
    .\\.venv\\Scripts\\python.exe pv_batteries\\precompute_risanamento.py
    # solo consolidamento
    .\\.venv\\Scripts\\python.exe pv_batteries\\precompute_risanamento.py --consolidate-only
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
for p in (str(ROOT), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

import risanamento_config as cfg  # noqa: E402
from section_engine import run_cli  # noqa: E402

if __name__ == "__main__":
    run_cli(cfg)
