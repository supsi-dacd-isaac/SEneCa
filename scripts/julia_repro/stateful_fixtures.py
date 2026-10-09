"""Python-oracle fixtures for nested states and plain-expression DATA."""
from __future__ import annotations

import itertools
from pathlib import Path
import warnings

from .common import CONFIG, RUNTIME, dump, read, run_logged

CONTROL = "\nINITIAL TIME=0 ~~|\nFINAL TIME=6 ~~|\nTIME STEP=1 ~~|\nSAVEPER=TIME STEP ~~|\n"


def model_cases():
    cases = []
    for rank in range(1, 7):
        dims = [f"D{axis}" for axis in range(rank)]
        domain = ",".join(dims)
        text = "\n".join(f"{dim}: a{axis},b{axis} ~~|" for axis, dim in enumerate(dims))
        for cell in itertools.product((0, 1), repeat=rank):
            labels = ",".join(f"{'b' if value else 'a'}{axis}" for axis, value in enumerate(cell))
            text += f"\nX[{labels}]={sum((value+1)*10**axis for axis, value in enumerate(cell))} ~~|"
        text += f"\nInput[{domain}]=X[{domain}]+Time*3 ~~|"
        text += f"\nOutput[{domain}]=DELAY FIXED(SMOOTH(Input[{domain}],2),0.1,-5) ~~|"
        cases.append((f"nested_rank_{rank}", text, ["Input", "Output"]))
    cases.extend([
        ("nested_scalar", "Input=Time+7 ~~|\nOutput=3+SMOOTH(Input,2) ~~|", ["Input", "Output"]),
        ("smooth_nested_smooth", "Input=Time+7 ~~|\nOutput=SMOOTH(SMOOTH(Input,2),4) ~~|", ["Input", "Output"]),
        ("delay_nested_smooth", "Input=Time+7 ~~|\nOutput=DELAY FIXED(SMOOTH(Input,2),4,-5) ~~|", ["Input", "Output"]),
        ("data_constant", "Input:INTERPOLATE::=136.543 ~~|\nOutput=INTEG(Input,0) ~~|", ["Input", "Output"]),
        ("data_expression", "Input:INTERPOLATE::=Time+5 ~~|\nOutput=INTEG(Input,0) ~~|", ["Input", "Output"]),
        ("parameter_before_initialization", "Input=136.543 ~~|\nOutput=INTEG(Input,Input) ~~|", ["Input", "Output"]),
        ("smooth_initial_stock", "Input=INTEG(2,7) ~~|\nOutput=SMOOTH(Input,2) ~~|", ["Input", "Output"]),
        ("fixed_copy_floats", "Input=IF THEN ELSE(Time<1,1e16,IF THEN ELSE(Time<2,0.1,IF THEN ELSE(Time<3,0,IF THEN ELSE(Time<4,1e-16,IF THEN ELSE(Time<5,-1e16,0.25))))) ~~|\n"
         "One=DELAY FIXED(Input,0.1,0.3) ~~|\nTwo=DELAY FIXED(Input,2,0.3) ~~|\nFour=DELAY FIXED(Input,4,0.3) ~~|", ["Input", "One", "Two", "Four"]),
        ("fixed_copy_stock", "Input=INTEG(0.1,0.1) ~~|\nOutput=DELAY FIXED(Input,0.1,0.3) ~~|", ["Input", "Output"]),
        ("fixed_copy_array", "Axis: a,b ~~|\nInput[a]=IF THEN ELSE(Time<1,1e16,IF THEN ELSE(Time<2,0.1,0)) ~~|\n"
         "Input[b]=IF THEN ELSE(Time<1,0.1,IF THEN ELSE(Time<2,1e16,0)) ~~|\n"
         "Output[Axis]=DELAY FIXED(Input[Axis],1,0.3) ~~|", ["Input", "Output"]),
        ("sequential_nested_smooth", "Input=Time+7 ~~|\nOutput=DELAY FIXED(SMOOTH(Input,2),0.1,-5) ~~|", ["Input", "Output"]),
    ])
    return cases


def prepare(target, reference=False, cases=None):
    import numpy as np
    import pysd
    from . import builder_patch, stateful_patch, ode_patch
    target = Path(target).resolve()
    target.mkdir(parents=True, exist_ok=True)
    if not reference:
        builder_patch.apply()
        stateful_patch.apply()
        ode_patch.apply()
    result, compiled = {}, []
    for name, body, outputs in model_cases() if cases is None else cases:
        directory = target / ("python" if reference else "julia")
        directory.mkdir(exist_ok=True)
        source = directory / f"{name}.mdl"
        source.write_text("{UTF-8}\n" + body + CONTROL)
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            if reference:
                model = pysd.read_vensim(source, initialize=False)
                if name == "parameter_before_initialization":
                    model.set_components({"Input": 17.25})
                if name == "sequential_nested_smooth":
                    # select_submodel in the real reference yields this order.
                    # Reproduce it explicitly, independently of hash randomization.
                    model._dynamicstateful_elements.sort(key=lambda obj: (not obj.py_name.startswith("_smooth_"), obj.py_name))
                model.initialize()
                frame = model.run(return_columns=outputs, return_timestamps=list(range(7)), flatten_output=False)
                result[name] = {"years": list(map(float, frame.index)), "exact": name.startswith("fixed_copy_") or name == "sequential_nested_smooth", "variables": {
                    variable.lower().replace(" ", "_"): [np.asarray(value).ravel(order="C").tolist() for value in frame[variable]]
                    for variable in outputs}}
            else:
                from pysd.builders.julia.julia_model_builder import JuliaSectionBuilder
                original = JuliaSectionBuilder._process_element

                def process(self, elem, identifier, is_control=False):
                    if name == "parameter_before_initialization" and elem.name == "Input":
                        self.param_decls.append(f"@parameters {identifier} = 17.25")
                        return []
                    return original(self, elem, identifier, is_control)

                JuliaSectionBuilder._process_element = process
                stateful_patch.configure_delay_update_policy(
                    {"_delayfixed_output": ["_smooth_output"]} if name == "sequential_nested_smooth" else {})
                try:
                    path = pysd.translate_to_julia(source, backend="ode", data_format="json")
                finally:
                    JuliaSectionBuilder._process_element = original
                    stateful_patch.configure_delay_update_policy({})
                compiled.append({"name": name, "path": str(path)})
            if captured:
                raise RuntimeError(f"Unexpected fixture warnings in {name}: {[str(item.message) for item in captured]}")
    dump(target / ("python-oracles.json" if reference else "models.json"), result if reference else compiled)
    if not reference:
        source = target / "julia/nested_initial_unsupported.mdl"
        source.parent.mkdir(exist_ok=True)
        source.write_text("{UTF-8}\nY=1+INITIAL(Time) ~~|\n" + CONTROL)
        try:
            pysd.translate_to_julia(source, backend="ode", data_format="json")
        except ValueError as exc:
            if "Nested INITIAL requires explicit lowering" not in str(exc):
                raise
            dump(target / "rejections.json", {"pass": True, "cases": ["nested_initial"], "message": str(exc)})
        else:
            raise RuntimeError("Unsupported nested INITIAL was silently translated")


def run(directory):
    from .execution import julia_command
    target = Path(directory).resolve() / "stateful-fixtures"
    target.mkdir(parents=True, exist_ok=True)
    for reference in (True, False):
        interpreter = RUNTIME / ("python-reference" if reference else "python-julia") / "bin/python"
        command = [interpreter, "-B", "-c", "from scripts.julia_repro.stateful_fixtures import prepare; prepare(" + repr(str(target)) + ", reference=" + repr(reference) + ")"]
        run_logged(command, target / ("python.log" if reference else "translation.log"))
    run_logged([*julia_command(), CONFIG / "test_stateful_models.jl", target / "models.json", target / "julia-results.json"], target / "julia.log")
    result = read(target / "julia-results.json")
    result["unsupported_rejections"] = read(target / "rejections.json")
    result["pass"] = result["pass"] and result["unsupported_rejections"]["pass"]
    return result
