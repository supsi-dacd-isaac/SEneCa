"""Python-oracle checks for numerical and initialization helper semantics."""
from __future__ import annotations




def model_cases():
    expressions = {
        "Negative base": "-2",
        "Negative even power": "Negative base^2",
        "Negative odd power": "Negative base^3",
        "Bounded base power": "MAX(0.2,MIN(1,Time/3))^2.5",
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
        ("bounded_array_power", "D: a,b ~~|\nX[a]=0.2 ~~|\nX[b]=0.8 ~~|\nInput[D]=(1-MIN(0.9,MAX(0.1,X[D]+Time/10)))^2.5 ~~|\nOutput[D]=INTEG(Input[D],0) ~~|", ["Input", "Output"]),
        ("lookup_power", "Curve([(0,0)-(8,2)],(0,0),(8,2)) ~~|\nD: a,b ~~|\nX[a]=0.2 ~~|\nX[b]=0.8 ~~|\nScalar=1.03^(-MIN(16,Curve(Time))) ~~|\nInput[D]=1.03^(-MIN(16,Curve(X[D]+Time))) ~~|\nOutput[D]=INTEG(Input[D],0) ~~|", ["Scalar", "Input", "Output"]),
        ("pv_numerical_zero", "D: zero,residue,boundary,positive ~~|\nBuildings[zero]=0 ~~|\nBuildings[residue]=1e-19 ~~|\nBuildings[boundary]=1e-10 ~~|\nBuildings[positive]=1e-9 ~~|\nRemoval[D]=IF THEN ELSE(Buildings[D]>1e-10,MIN(1,Buildings[D]*0.02/IF THEN ELSE(Buildings[D]>1e-10,Buildings[D],1)),0) ~~|\nLoss[D]=INTEG(-Loss[D]*Removal[D],7000) ~~|", ["Removal", "Loss"]),
    ]


def prepare(target, reference=False):
    from .stateful_fixtures import prepare as prepare_models
    prepare_models(target, reference, model_cases())
