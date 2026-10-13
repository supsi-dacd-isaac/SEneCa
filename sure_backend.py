"""Shared live-simulation interface; engine choice never changes implicitly."""
import os

from sure_julia.common import ROOT, digest, identity, read
from sure_pysd import OUTPUTS


def backend_name():
    name = os.environ.get("SURE_BACKEND", "julia").lower()
    if name not in {"julia", "python"}:
        raise ValueError("SURE_BACKEND must be julia or python")
    return name


def engine_identity():
    name = backend_name()
    model = ROOT / "sure_julia/generated/build.json" if name == "julia" else ROOT / "Vensim/SURE_pysd_v4.py"
    return identity({"backend": name, "model": digest(model), "data": read(ROOT / "data-release.json"),
                     "calibration": digest(ROOT / "constants_ref_v4.pkl"),
                     "runtime": {p.name: digest(p) for p in (ROOT / "sure_julia").glob("*.py")}})


def load_model():
    if backend_name() == "julia":
        from sure_julia.runtime import JuliaBackend
        return JuliaBackend()
    from sure_julia.python_backend import PythonBackend
    return PythonBackend(outputs=OUTPUTS)
