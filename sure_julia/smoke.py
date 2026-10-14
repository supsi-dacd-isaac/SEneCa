"""Numerical and UI smoke check executed inside each released architecture."""
import argparse
import os
from pathlib import Path

from .catalog import defaults, parameters
from .batch import configs, gmd, exploratory_indicators
from .common import ROOT, dump, read
from .python_backend import PythonBackend
from .runtime import JuliaBackend
from .validation import compare, energy, warning_review, negative_stock_regression


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--ui", action="store_true")
    args = parser.parse_args()
    from pysd_explore_config import ALL_INPUTS
    py, jl = PythonBackend(), JuliaBackend(timeout=900)
    cases = {"base": defaults(), "high": parameters({i.name: float(max(i.values)) for i in ALL_INPUTS}),
             "regression_negative_stock": negative_stock_regression()}
    reports = {}
    try:
        for name, params in cases.items():
            a, b = py.run_arrays(params), jl.run_arrays(params)
            reports[name] = {"comparison": compare(a, b, jl.export), "python_energy": energy(a), "julia_energy": energy(b),
                             "python_physical": py.last_physical, "julia_physical": jl.last_physical,
                             "warnings": warning_review(py.warnings, read(jl.directory / "warnings.json"), py.variables),
                             "timing": jl.last_timing}
            metrics = []
            export = {v["name"]: v for v in jl.export}
            for section, cfg in configs().items():
                if not getattr(cfg, "GMD_SPEC", None):
                    continue
                audit_a, audit_b = [], []
                left, right = gmd(a, cfg.GMD_SPEC, export, audit_a), gmd(b, cfg.GMD_SPEC, export, audit_b)
                metrics.append({"section": section, "python": left, "julia": right,
                                "python_weight_audit": audit_a, "julia_weight_audit": audit_b,
                                "pass": all(abs(left[k]-right[k]) <= 1e-10*max(1, abs(left[k]))+1e-8*abs(left[k]) for k in left)})
            reports[name]["gmd"] = {"pass": all(r["pass"] for r in metrics), "rows": metrics}
            left, right = exploratory_indicators(a, export), exploratory_indicators(b, export)
            reports[name]["exploratory_kpis"] = {"python": left, "julia": right,
                "pass": all(abs(left[k]-right[k]) <= 1e-10*max(1, abs(left[k]))+1e-8*abs(left[k]) for k in left)}
            dump(args.directory / f"{name}.json", reports[name])
            if not all(reports[name][key]["pass"] for key in ("comparison", "python_energy", "julia_energy", "python_physical", "julia_physical", "warnings", "gmd", "exploratory_kpis")):
                raise RuntimeError(f"Numerical smoke failed: {name}")
    finally:
        py.close()
        jl.close()
    if args.ui:
        from streamlit.testing.v1 import AppTest
        os.environ["SURE_BACKEND"] = "julia"
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=900).run()
        app.switch_page("pages/5_Analisi_Esplorativa.py").run()
        if app.exception or app.error or len(app.dataframe[0].value) != 9:
            raise RuntimeError(f"Policy mix UI failed: {app.exception}; {app.error}")
        app.session_state['expl_subpage'] = 'Migliori policy mix'
        app.run()
        if app.exception or app.error or len(app.slider) != 9:
            raise RuntimeError(f"Policy mix ranking failed: {app.exception}; {app.error}")
        app.switch_page("pages/9_Esplora_SURE_PySD.py").run()
        if app.exception:
            raise RuntimeError(str(app.exception))
        button = next(b for b in app.button if "Simula e confronta" in b.label)
        button.click().run(timeout=900)
        if app.exception or "exp_user_df" not in app.session_state:
            raise RuntimeError(f"Live UI failed: {app.exception}")
        import streamlit as st
        st.cache_resource.clear()
    dump(args.directory / "summary.json", {"pass": True, "cases": list(cases), "ui": args.ui,
                                         "model": jl.metadata})


if __name__ == "__main__":
    main()
