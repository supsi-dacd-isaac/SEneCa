"""Turn the certified Vensim-derived Julia model into one parameterized module.

Only parameter reads and runtime plumbing change. Equations, array layout,
calibration, delay policy and mathematical compatibility remain frozen.
The source contract is checked before transformation; unexpected forms fail.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from scripts.julia_repro.common import digest, dump, read
from scripts.julia_repro.execution import verify_translation

CONTROLS = tuple(f"Provvedimento 1.{n}" for n in (2, 3, 4, 7))


def resolve_name(name, namespace):
    """Resolve exact names first, then unambiguous Vensim enclosing quotes."""
    if name in namespace:
        return name
    matches = [key for key in namespace if key.strip('"').casefold() == name.strip('"').casefold()]
    if len(matches) != 1:
        raise ValueError(f"Unknown or ambiguous scenario parameter: {name!r}: {matches}")
    return matches[0]


def rewrite_identifiers(source, replacements):
    # Generated Julia contains ordinary strings and line comments. Keep them
    # intact, particularly the observable-name keys and diagnostic messages.
    token = re.compile(r'"(?:\\.|[^"\\])*"|\#.*?$|\b[A-Za-z_]\w*\b', re.M)
    return token.sub(lambda m: replacements.get(m[0], m[0]), source)


def replace_once(source, before, after):
    if source.count(before) != 1:
        raise ValueError(f"Unexpected generated source contract: {before[:90]!r}")
    return source.replace(before, after, 1)


def transform(source, names, defaults):
    fields = {name: re.sub(r"\W+", "_", name.lower()).strip("_") for name in names}
    if len(set(fields.values())) != len(fields):
        raise ValueError("Parameter identifier collision")
    parameter_block, remaining = source.split("# Simulation control\n", 1)
    for name, field in fields.items():
        if name in CONTROLS:
            remaining = replace_once(remaining, f"    {field} = 0.0\n", f"    {field} = c.parameters.{field}\n")
        else:
            parameter_block, count = re.subn(r"(?m)^const " + re.escape(field) + r" = [^\n]+\n", "", parameter_block)
            if count != 1:
                raise ValueError(f"Expected one scalar scenario declaration: {name}")
    prefix, kernels = remaining.split("@noinline function ", 1)
    # Include only the equation/getter/initialization section in the identifier
    # rewrite. Function locals for the four control getters stay local.
    kernels, tail = ("@noinline function " + kernels).split("const _initial_state_build = let\n", 1)
    kernels = rewrite_identifiers(kernels, {field: f"c.parameters.{field}" for name, field in fields.items() if name not in CONTROLS})
    declarations = ["struct SUREParameters"]
    declarations += [f"    {field}::Float64" for field in fields.values()]
    declarations += ["end", "const PARAMETER_NAMES = " + repr(list(names)).replace("'", '"'),
                     "function parameters_from_dict(values)",
                     "    Set(String.(keys(values))) == Set(PARAMETER_NAMES) || error(\"Unknown or missing scenario parameters\")",
                     "    numbers = Float64[values[name] for name in PARAMETER_NAMES]",
                     "    all(isfinite, numbers) || error(\"Nonfinite scenario parameter\")"]
    for index, name in enumerate(names, 1):
        if name in CONTROLS:
            declarations.append(f'    numbers[{index}] in (0.0, 1.0) || error("Binary control requires 0 or 1: {name}")')
    declarations += ["    return SUREParameters(numbers...)", "end",
                     "const DEFAULT_PARAMETERS = SUREParameters(" + ", ".join(repr(float(defaults[name])) for name in names) + ")",
                     "struct SUREExecution", "    parameters::SUREParameters", "    pending::Vector{Float64}", "end", ""]
    prefix = replace_once(prefix, "mutable struct SenecaContext\n", "\n".join(declarations) + "\nmutable struct SenecaContext\n    parameters::SUREParameters\n")
    prefix = replace_once(prefix,
        "SenecaContext(state, time, initializing, n) = SenecaContext(state, Float64(time), initializing, Vector{Any}(undef, n), zeros(UInt8, n))",
        "SenecaContext(state, time, initializing, n, parameters::SUREParameters) = SenecaContext(parameters, state, Float64(time), initializing, Vector{Any}(undef, n), zeros(UInt8, n))")
    kernels = replace_once(kernels, "function rhs!(du, u, p, t)", "function rhs!(du, u, p::SUREExecution, t)\n    parameters = p.parameters")
    kernels = replace_once(kernels, "function _prepare_fixed_delays!(pending, u, t, new_state)", "function _prepare_fixed_delays!(pending, u, t, new_state, parameters::SUREParameters)")
    kernels = replace_once(kernels,
        "_prepare_fixed_delays!(integrator.p, integrator.uprev, integrator.tprev, integrator.u)",
        "_prepare_fixed_delays!(integrator.p.pending, integrator.uprev, integrator.tprev, integrator.u, integrator.p.parameters)")
    kernels = kernels.replace(", integrator.p, ", ", integrator.p.pending, ")
    kernels = replace_once(kernels, "function observe(u, t, requested=nothing)", "function observe(u, t, requested=nothing; parameters::SUREParameters=DEFAULT_PARAMETERS)")
    kernels = replace_once(kernels, "function initial_state()", "function initial_state(parameters::SUREParameters=DEFAULT_PARAMETERS)")
    kernels, count = re.subn(r"SenecaContext\((u|Float64\[\]), (t|initial_time), (false|true), (\d+)\)",
                             r"SenecaContext(\1, \2, \3, \4, parameters)", kernels)
    if count != 5:
        raise ValueError(f"Unexpected context construction count: {count}")
    # Remove eager base initialization and the global ODEProblem. Every call
    # owns its initial state, scratch delay buffer, caches and ODEProblem.
    _, metadata = tail.split("const _dim_labels = ", 1)
    run = '''
function run_model(parameters::SUREParameters=DEFAULT_PARAMETERS; u0=initial_state(parameters), tspan=tspan, dt=time_step, solver=Euler())
    dt == time_step || error("DELAY FIXED requires the declared fixed time step")
    solver isa Euler || error("Reference semantics require fixed-step Euler")
    state = copy(u0)
    execution = SUREExecution(parameters, similar(state))
    problem = ODEProblem(rhs!, state, tspan, execution)
    callback = DiscreteCallback((u, t, integrator) -> true, _copy_fixed_delays!; save_positions=(false, true))
    solve(problem, solver; dt=dt, saveat=Float64[], save_start=true,
          save_end=false, save_everystep=false, adaptive=false, callback=callback)
end
'''
    return parameter_block + "# Simulation control\n" + prefix + kernels + run + "const _dim_labels = " + metadata, fields


def build(reference, target):
    reference, target = Path(reference).resolve(), Path(target).resolve()
    source_dir, certificate = verify_translation(reference, "base")
    manifest = read(reference / "manifest.json")
    names = list(manifest["scenarios"]["base"])
    target.mkdir(parents=True, exist_ok=True)
    source = source_dir / certificate["model"]
    generated, fields = transform(source.read_text(), names, manifest["scenarios"]["base"])
    model = target / "SURE_parametric.jl"
    model.write_text(generated)
    for p in source_dir.glob("*_data.json"):
        shutil.copy2(p, target / p.name)
    for filename in ("export.json", "export-app.json"):
        shutil.copy2(source_dir / filename, target / filename)
    metadata = {"pass": True, "source": str(source), "source_sha256": digest(source),
                "source_certificate_sha256": digest(source_dir / "translation.json"),
                "model": model.name, "model_sha256": digest(model), "parameters": fields,
                "defaults": manifest["scenarios"]["base"], "source_experiment": certificate["experiment"],
                "implementation_sha256": digest(Path(__file__))}
    metadata["artifacts"] = {p.name: digest(p) for p in sorted(target.iterdir())
                             if p.is_file() and p.name != "model.json"}
    dump(target / "model.json", metadata)
    return metadata
