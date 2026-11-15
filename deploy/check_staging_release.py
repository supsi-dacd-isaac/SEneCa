"""Controlli del pacchetto di staging nativo (eseguito durante la build dell'immagine).

- il build nativo è completo e le sue impronte corrispondono ai file;
- gli scenari precalcolati sono stati generati da quel build (provenance/build.json);
- i file dati attesi dalle pagine sono presenti; campioni e KPI esplorativi validi.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.data_release import DATA_PATHS, PROVENANCE_PATHS  # noqa: E402
from sure_julia.common import NATIVE_REVISION, digest  # noqa: E402


def fail(message):
    raise SystemExit(f"Pacchetto di staging non valido: {message}")


build = json.loads((ROOT / "sure_native/generated/build.json").read_text())
if not build.get("complete") or build.get("worker") != "native" or build.get("model_revision") != NATIVE_REVISION:
    fail("build nativo incompleto o di un'altra revisione")
for name, expected in build["artifacts"].items():
    if digest(ROOT / "sure_native/generated" / name) != expected:
        fail(f"impronta diversa: sure_native/generated/{name}")
missing = [p for p in (*DATA_PATHS, *PROVENANCE_PATHS) if not p.endswith(".vpmx") and not (ROOT / p).is_file()]
if missing:
    fail(f"file mancanti {missing}")
provenance = json.loads((ROOT / "provenance/build.json").read_text())
if provenance["model"]["artifacts"] != build["artifacts"]:
    fail("gli scenari precalcolati non sono stati generati con questo build")
if provenance["scenarios_sha256"] != digest(ROOT / "provenance/scenarios.parquet"):
    fail("provenance/scenarios.parquet modificato")

import pandas as pd  # noqa: E402
from pv_batteries.exploratory import validate_kpi_store  # noqa: E402
from pv_batteries.exploratory_config import validate_samples  # noqa: E402

validate_samples(pd.read_parquet(ROOT / "precomputed/exploratory/uncertainty_samples.parquet"))
validate_kpi_store(pd.read_parquet(ROOT / "precomputed/exploratory_kpis.parquet"))
print(f"staging ok: build {NATIVE_REVISION}, {len(build['artifacts'])} file, "
      f"{len(pd.read_parquet(ROOT / 'provenance/scenarios.parquet'))} scenari")
