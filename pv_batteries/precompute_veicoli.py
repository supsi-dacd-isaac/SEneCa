"""Pre-calcolo 576 combinazioni "Veicoli" col modello nativo Vensim."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
for p in (str(ROOT), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

import veicoli_config as cfg  # noqa: E402
from section_engine import run_cli  # noqa: E402

if __name__ == "__main__":
    run_cli(cfg)
