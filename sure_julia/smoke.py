"""Numerical and UI smoke check executed inside each released architecture."""
import argparse
import os
from pathlib import Path

from .catalog import defaults, parameters
from .common import ROOT, dump, read
from .python_backend import PythonBackend
from .runtime import JuliaBackend
from .validation import compare, energy, warning_review


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--ui", action="store_true")
    args = parser.parse_args()
    from pysd_explore_config import ALL_INPUTS
    py, jl = PythonBackend(), JuliaBackend(timeout=900)
    cases = {"base": defaults(), "high": parameters({i.name: float(max(i.values)) for i in ALL_INPUTS})}
    reports = {}
    try:
        for name, params in cases.items():
            a, b = py.run_arrays(params), jl.run_arrays(params)
            reports[name] = {"comparison": compare(a, b, jl.export), "python_energy": energy(a), "julia_energy": energy(b),
                             "warnings": warning_review(py.warnings, read(jl.directory / "warnings.json"), py.variables),
                             "timing": jl.last_timing}
            dump(args.directory / f"{name}.json", reports[name])
            if not all(reports[name][key]["pass"] for key in ("comparison", "python_energy", "julia_energy", "warnings")):
                raise RuntimeError(f"Numerical smoke failed: {name}")
    finally:
        py.close()
        jl.close()
    if args.ui:
        from streamlit.testing.v1 import AppTest
        os.environ["SURE_BACKEND"] = "julia"
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=900).run()
        app.switch_page("pages/9_Esplora_SURE_PySD.py").run()
        if app.exception:
            raise RuntimeError(str(app.exception))
        button = next(b for b in app.button if "Simula e confronta" in b.label)
        button.click().run(timeout=900)
        if app.exception or "exp_user_df" not in app.session_state:
            raise RuntimeError(f"Live UI failed: {app.exception}")
        import streamlit as st
        st.cache_resource.clear()
    dump(args.directory / "summary.json", {"pass": True, "cases": list(cases), "ui": args.ui})


if __name__ == "__main__":
    main()
