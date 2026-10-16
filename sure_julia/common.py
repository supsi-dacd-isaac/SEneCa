"""Artifact identity and numerical contract shared by build and runtime."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = Path(__file__).resolve().parent / "julia"
YEARS = list(range(2011, 2051))
MODEL_VARIANT = "v7"
MODEL_REVISION = "sure-v7-dispatch-1"
MODEL_PY = ROOT / "Vensim/SURE_pysd_v7.py"
MODEL_MDL = ROOT / "Vensim/SURE_pysd_v7.mdl"
CALIBRATION = ROOT / f"constants_ref_{MODEL_VARIANT}.pkl"


def model_sources():
    return {str(p.relative_to(ROOT)): digest(p) for p in
            [MODEL_PY, MODEL_MDL, CALIBRATION, ROOT / "Vensim/SURE.mdl",
             ROOT / "Vensim/calibration/manifest.json",
             *sorted((ROOT / "Vensim/calibration").glob("*.out")),
             ROOT / "sure_julia/pv_budget.py", ROOT / "sure_julia/pv-budget.json",
             ROOT / "fix_selfref_sure.py", ROOT / "fix_allocate_sure.py",
             *sorted((ROOT / "Vensim").glob(f"*_pysd_{MODEL_VARIANT}.csv"))]}


def read(path):
    return json.loads(Path(path).read_text())


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    temporary.replace(path)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
