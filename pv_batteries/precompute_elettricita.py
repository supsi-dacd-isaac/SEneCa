"""Pre-calcolo 144 combinazioni "Elettricità" (output orari)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
for p in (str(ROOT), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

import elettricita_config as cfg  # noqa: E402
from section_engine_hourly import run_cli  # noqa: E402

if __name__ == "__main__":
    run_cli(cfg)
