"""Python-oracle checks for numerical and initialization helper semantics."""
from __future__ import annotations

from pathlib import Path

from .common import CONFIG, RUNTIME, read, run_logged


def model_cases():
    expressions = {
        "Negative base": "-2",
        "Negative even power": "Negative base^2",
        "Negative odd power": "Negative base^3",
        "Zero power zero": "0^0",
        "Xidz below": "XIDZ(4,0.000000999,11)",
        "Xidz boundary": "XIDZ(4,0.000001,11)",
        "Xidz negative": "XIDZ(4,-0.000001,11)",
        "Zidz below": "ZIDZ(4,0.000000999)",
        "Zidz boundary": "ZIDZ(4,0.000001)",
        "Step boundary": "STEP(4,1.5)",
        "Ramp boundary": "RAMP(3,2.0000005,4)",
        "Ramp finish zero": "RAMP(3,2,0)",
        "Ramp finish before start": "RAMP(3,2,1)",
        "Ramp negative slope": "RAMP(-3,2,4)",
        "Log small value": "LOG(0.0001,10)",
        "Log near boundary": "LOG(0.001,10)",
        "Natural log": "LN(1+Time/10)",
        "Exponential": "EXP(-Time/10)",
        "Pulse boundary": "PULSE(2.0000005,1)",
        "Pulse train end": "PULSE TRAIN(0,1,2,4)",
        "And negative": "(-1) :AND: 1",
        "And fraction": "0.1 :AND: 1",
        "Or negative": "(-1) :OR: 0",
        "Not negative": ":NOT: (-1)",
        "If numeric": "IF THEN ELSE(-1,5,6)",
        "Lazy branch": "IF THEN ELSE(Time>=0,5,1/(Time-Time))",
        "Negative modulo": "MODULO(-5,3)",
        "Quantum boundary": "QUANTUM(-5,3)",
    }
    body = "\n".join(f"{name}={expression} ~~|" for name, expression in expressions.items())
    body += "\nStock=INTEG(1,0) ~~|"
    return [
        ("numerical_helpers", body, [*expressions, "Stock"]),
        ("active_initial", "Input=ACTIVE INITIAL(Output+Time,7) ~~|\nOutput=INTEG(1,Input) ~~|", ["Input", "Output"]),
        ("lazy_initialization", "Input=IF THEN ELSE(Time>=0,7,1/(Time-Time)) ~~|\nOutput=INTEG(1,Input) ~~|", ["Input", "Output"]),
        ("frozen_initial", "Input=Time+7 ~~|\nFrozen=INITIAL(Input) ~~|\nOutput=INTEG(Frozen,0) ~~|", ["Input", "Frozen", "Output"]),
        ("truth_array", "D: neg,small,zero,one ~~|\nMask[neg]=-1 ~~|\nMask[small]=0.1 ~~|\nMask[zero]=0 ~~|\nMask[one]=1 ~~|\nInput[D]=IF THEN ELSE(Mask[D],5,6) ~~|\nOutput[D]=INTEG(Input[D],0) ~~|", ["Input", "Output"]),
    ]


def prepare(target, reference=False):
    from .stateful_fixtures import prepare as prepare_models
    prepare_models(target, reference, model_cases())


def run(directory):
    from .execution import julia_command
    target = Path(directory) / "semantic-fixtures"
    target.mkdir(parents=True, exist_ok=True)
    for reference in (True, False):
        interpreter = RUNTIME / ("python-reference" if reference else "python-julia") / "bin/python"
        command = [interpreter, "-B", "-c", "from scripts.julia_repro.semantic_fixtures import prepare; prepare(" + repr(str(target)) + ", reference=" + repr(reference) + ")"]
        run_logged(command, target / ("python.log" if reference else "translation.log"))
    run_logged([*julia_command(), CONFIG / "test_stateful_models.jl", target / "models.json", target / "julia-results.json"], target / "julia.log")
    return read(target / "julia-results.json")
