"""Shared live-simulation interface; engine choice never changes implicitly."""
import os
from pathlib import Path

from sure_julia.common import ROOT, MODEL_PY, CALIBRATION, model_sources, digest, identity, read
from sure_pysd import LIVE_OUTPUTS as OUTPUTS


def backend_name():
    name = os.environ.get("SURE_BACKEND", "julia").lower()
    if name not in {"julia", "python"}:
        raise ValueError("SURE_BACKEND must be julia or python")
    return name


def engine_identity():
    name = backend_name()
    directory = Path(os.environ.get("SURE_JULIA_MODEL", ROOT / "sure_julia/generated")).resolve()
    model = directory / "build.json" if name == "julia" else MODEL_PY
    return identity({"backend": name, "model": digest(model), "data": read(ROOT / "data-release.json"),
                     "live_outputs": OUTPUTS,
                     "model_path": str(model), "julia_command": os.environ.get("SURE_JULIA_BIN", "julia") if name == "julia" else None,
                     "calibration": digest(CALIBRATION), "python_sources": model_sources() if name == "python" else None,
                     "runtime": {p.name: digest(p) for p in (ROOT / "sure_julia").glob("*.py")}})


def load_model():
    if backend_name() == "julia":
        from sure_julia.runtime import JuliaBackend
        return JuliaBackend()
    from sure_julia.python_backend import PythonBackend
    return PythonBackend(outputs=OUTPUTS)
