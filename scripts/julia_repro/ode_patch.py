"""Strict ODE emission with dependency-driven initialisation and typed caching.

The upstream emitter allocates arrays seen only on RHS (shadowing constants),
guesses unknown dimensions as 100, and initialises through observe(zeros).
Generate small per-variable functions from the same translated equations instead.
Every stock initialiser evaluates its actual dependencies, never dummy states.
"""
from __future__ import annotations

from collections import defaultdict
import math
import re


def _entries(self):
    result = defaultdict(list)
    for entry in self.u0_entries:
        lhs, rhs = entry.split("=>", 1)
        match = re.fullmatch(r"\s*(\w+)(?:\[([\d, ]+)\])?\s*", lhs)
        if not match:
            raise ValueError(f"Unrecognised stock initialiser: {entry}")
        indices = tuple(map(int, match[2].split(","))) if match[2] else ()
        result[match[1]].append((indices, rhs.strip()))
    for name in result:
        result[name].sort(key=lambda x: tuple(reversed(x[0])))
    self.u0_entries = [f"{name}" + ("[" + ", ".join(map(str, cell)) + "]" if cell else "") + f" => {expr}"
                       for name, entries in result.items() for cell, expr in entries]
    return result


def _shape(self, name, entries=None):
    if entries is not None:
        rank = len(entries[0][0])
        if any(len(cell) != rank for cell, _ in entries):
            raise ValueError(f"Mixed rank stock {name}")
        shape = tuple(max(cell[i] for cell, _ in entries) for i in range(rank))
        if (math.prod(shape) if shape else 1) != len(entries) or len({cell for cell, _ in entries}) != len(entries):
            raise ValueError(f"Incomplete stock initialisation: {name}")
        return shape
    dims = self._var_dims.get(name)
    if dims is None:
        if any(re.fullmatch(r"@variables\s+" + re.escape(name) + r"\(t\)", declaration.strip())
               for declaration in self.aux_decls):
            return ()
        raise ValueError(f"Missing dimension declaration: {name}")
    return tuple(len(self._subs_elems[d]) for d in dims)


def _typed(name, shape):
    return f"convert(Array{{Float64,{len(shape)}}}, {name})" if shape else f"Float64({name})"


def _rewrite(expression, names, own=None):
    # Replace references at their point of use, preserving lazy conditional
    # branches during initialisation. Each getter caches once per evaluation.
    return re.sub(r"\b[a-zA-Z_]\w*\b", lambda m: f"_get_{m[0]}(c)"
                  if m[0] in names and m[0] != own else m[0], expression)


_INITIAL_INTEGER = re.compile(r"(?<![A-Za-z0-9_.])\d+(?![A-Za-z0-9_.])")


def _initial_template(entries):
    """Infer a coordinate template only if expanding it reproduces every RHS.

    Integer tokens may represent coordinates only when their values match that
    axis across *every* cell. All other syntax and constants remain identical.
    The final exhaustive textual round trip guards even degenerate dimensions.
    """
    skeletons = [_INITIAL_INTEGER.split(expression) for _, expression in entries]
    if any(parts != skeletons[0] for parts in skeletons[1:]):
        return None
    tokens = [_INITIAL_INTEGER.findall(expression) for _, expression in entries]
    if any(len(values) != len(tokens[0]) for values in tokens[1:]):
        return None
    rank = len(entries[0][0])
    replacements = []
    for position in range(len(tokens[0])):
        values = [row[position] for row in tokens]
        if all(value == values[0] for value in values):
            replacements.append(values[0])
            continue
        axis = next((axis for axis in range(rank)
                     if all(value == str(cell[axis]) for value, (cell, _) in zip(values, entries))), None)
        if axis is None:
            return None
        replacements.append(f"__seneca_init_i{axis}")
    parts = [skeletons[0][0]]
    for token, suffix in zip(replacements, skeletons[0][1:]):
        parts.extend((token, suffix))
    template = "".join(parts)
    for cell, expression in entries:
        expanded = template
        for axis, index in enumerate(cell):
            expanded = expanded.replace(f"__seneca_init_i{axis}", str(index))
        if expanded != expression:
            return None
    return template


def _stock_initializer(name, entries, shape, dynamic):
    """Emit compact exact loops, or bounded kernels for irregular initializers."""
    dimensions = ", ".join(map(str, shape))
    statements = [f"{name} = Array{{Float64}}(undef, {dimensions})"]
    expressions = [expression for _, expression in entries]
    if len(set(expressions)) == 1:
        try:
            numeric = float(expressions[0])
        except ValueError:
            pass
        else:
            if math.isfinite(numeric):
                return statements + [f"fill!({name}, {expressions[0]})"], []
    template = _initial_template(entries)
    if template is not None:
        indices = [f"__seneca_init_i{axis}" for axis in range(len(shape))]
        # Original entries use Julia/Fortran order; preserve evaluation order.
        domain = ", ".join(f"{indices[axis]} in 1:{shape[axis]}" for axis in reversed(range(len(shape))))
        statements += [f"for {domain}", f"    {name}[{', '.join(indices)}] = {_rewrite(template, dynamic)}", "end"]
        return statements, []
    helpers = []
    for start in range(0, len(entries), 64):
        helper = f"_initialize_{name}_{start // 64}!"
        helpers += [f"@noinline function {helper}(target::Array{{Float64,{len(shape)}}}, c::SenecaContext)", "    t = c.time"]
        for cell, expression in entries[start:start + 64]:
            helpers.append(f"    target[{', '.join(map(str, cell))}] = {_rewrite(expression, dynamic)}")
        helpers += ["    return nothing", "end", ""]
        statements.append(f"{helper}({name}, c)")
    return statements, helpers


def _equations(self, equations):
    from .common import CONFIG
    stocks = _entries(self)
    discrete = getattr(self, "_seneca_fixed_delays", {})
    ode, algebraic = defaultdict(list), []
    for equation in equations:
        equation = equation.strip().rstrip(",")
        if not equation or equation.startswith("#"):
            continue
        match = re.match(r"\[?D\((\w+)", equation)
        if match:
            ode[match[1]].append(equation)
        else:
            algebraic.append(equation)
    if set(stocks) != set(ode):
        raise ValueError(f"Stock/derivative mismatch: {set(stocks) ^ set(ode)}")
    groups = defaultdict(list)
    for equation in self._topo_sort_equations(algebraic, set(stocks)):
        groups[self._extract_lhs_name(equation)].append(equation)
    overlap = set(stocks) & set(groups)
    if overlap:
        raise ValueError(f"Both stock and auxiliary assignments: {overlap}")
    names = list(stocks) + list(groups)
    dynamic = set(names)
    shapes = {name: _shape(self, name, entries) for name, entries in stocks.items()}
    shapes.update({name: _shape(self, name) for name in groups})
    self._seneca_shapes = shapes
    positions, count = {}, 0
    for name, entries in stocks.items():
        positions[name] = count + 1
        count += len(entries)
    self._seneca_states = count
    lines = [(CONFIG / "ode_runtime.jl").read_text()]
    initialization_helpers = []
    for index, name in enumerate(names, 1):
        shape = shapes[name]
        dtype = f"Array{{Float64,{len(shape)}}}" if shape else "Float64"
        lines += [f"@noinline function _get_{name}(c::SenecaContext)::{dtype}",
                  f"    c.status[{index}] == 2 && return c.values[{index}]::{dtype}",
                  f'    c.status[{index}] == 1 && error("Initialisation dependency cycle at {name}")',
                  f"    c.status[{index}] = 1", "    t = c.time"]
        if name in stocks:
            entries = stocks[name]
            lines.append("    if c.initializing")
            if shape:
                statements, helpers = _stock_initializer(name, entries, shape, dynamic)
                lines.extend("        " + statement for statement in statements)
                initialization_helpers.extend(helpers)
            else:
                lines.append(f"        {name} = {_rewrite(entries[0][1], dynamic)}")
            lines.append("    else")
            start = positions[name]
            if shape:
                lines.append(f"        {name} = reshape(copy(c.state[{start}:{start+len(entries)-1}]), {', '.join(map(str, shape))})")
            else:
                lines.append(f"        {name} = c.state[{start}]")
            lines.append("    end")
        else:
            # Allocate only an explicitly declared LHS that is assigned by cells.
            indexed = any(re.match(r"\[?" + re.escape(name) + r"\[", eq) for eq in groups[name])
            if indexed:
                if not shape:
                    raise ValueError(f"Indexed scalar auxiliary {name}")
                lines.append(f"    {name} = fill(NaN, {', '.join(map(str, shape))})")
            for equation in groups[name]:
                for statement in self._convert_eq_to_assignment(equation):
                    lines.append("    " + _rewrite(statement, dynamic, own=name))
        lines += [f"    value = {_typed(name, shape)}", f"    c.values[{index}] = value",
                  f"    c.status[{index}] = 2", "    return value", "end", ""]
    lines.extend(initialization_helpers)
    # Separate derivative kernels avoid one enormous LLVM compilation unit.
    for name, equations_for_stock in ode.items():
        lines += [f"@noinline function _derivative_{name}!(du, c::SenecaContext)", "    t = c.time"]
        shape, start = shapes[name], positions[name]
        if len(shape) > 1:
            lines.append(f"    du_{name} = reshape(@view(du[{start}:{start+len(stocks[name])-1}]), {', '.join(map(str, shape))})")
        for equation in [discrete[name]] if name in discrete else equations_for_stock:
            for statement in self._convert_ode_to_du(equation, positions):
                lines.append("    " + _rewrite(statement, dynamic))
        lines += ["    return nothing", "end", ""]
    lines += ["function rhs!(du, u, p, t)", f"    c = SenecaContext(u, t, false, {len(names)})"]
    lines += [f"    _derivative_{name}!(du, c)" for name in stocks if name not in discrete]
    for name in discrete:
        start, size = positions[name], len(stocks[name])
        lines += [f"    fill!(@view(du[{start}:{start+size-1}]), 0.0)"]
    lines += ["    return nothing", "end", ""]
    if discrete:
        new_sources = getattr(self, "_seneca_delay_new_state_sources", {})
        lines += ["function _prepare_fixed_delays!(pending, u, t, new_state)",
                  f"    c = SenecaContext(u, t, false, {len(names)})"]
        for name in discrete:
            if name not in new_sources:
                lines.append(f"    _derivative_{name}!(pending, c)")
                continue
            lines.append(f"    updated = SenecaContext(u, t, false, {len(names)})")
            for source in new_sources[name]:
                index, start = names.index(source) + 1, positions[source]
                value = f"new_state[{start}]"
                if shapes[source]:
                    value = f"reshape(copy(new_state[{start}:{start+len(stocks[source])-1}]), {', '.join(map(str, shapes[source]))})"
                lines += [f"    updated.values[{index}] = {value}",
                          f"    updated.status[{index}] = 2"]
            lines.append(f"    _derivative_{name}!(pending, updated)")
        lines += ["    return nothing", "end", "", "function _copy_fixed_delays!(integrator)",
                  "    _prepare_fixed_delays!(integrator.p, integrator.uprev, integrator.tprev, integrator.u)"]
        for name in discrete:
            start, size = positions[name], len(stocks[name])
            lines.append(f"    copyto!(integrator.u, {start}, integrator.p, {start}, {size})")
        lines += ["    return nothing", "end", ""]
    lines += [
              "const _observed_getters = Dict{String,Function}("]
    lines += [f'    "{name}" => _get_{name},' for name in names]
    lines += [f'    "{name}" => c -> {name},' for name in self._const_names_for_observe(dynamic)]
    lines += [")", "function observe(u, t, requested=nothing)",
              f"    c = SenecaContext(u, t, false, {len(names)})",
              "    selected = isnothing(requested) ? keys(_observed_getters) : requested",
              "    return Dict{String,Any}(name => _observed_getters[name](c) for name in selected)",
              "end", "", "function initial_state()",
              f"    c = SenecaContext(Float64[], initial_time, true, {len(names)})",
              f"    state = Vector{{Float64}}(undef, {count})"]
    for name, entries in stocks.items():
        start = positions[name]
        if shapes[name]:
            lines.append(f"    state[{start}:{start+len(entries)-1}] .= vec(_get_{name}(c))")
        else:
            lines.append(f"    state[{start}] = _get_{name}(c)")
    lines += ["    all(isfinite, state) || error(\"Nonfinite initial state\")", "    return state", "end", ""]
    return "\n".join(lines)


def _run_function(self):
    """Euler updates real stocks; fixed delays copy the preceding-step input."""
    if not getattr(self, "_seneca_fixed_delays", {}):
        return self._seneca_original_run_function()
    has_tab = bool(self._tab_data_entries)
    tab_args = ", tab_data_files=String[], nc_data_files=String[]" if has_tab else ""
    tab_load = ("\n    isempty(tab_data_files) || _load_tab_data!(tab_data_files)"
                "\n    isempty(nc_data_files) || _load_nc_data!(nc_data_files)") if has_tab else ""
    return f'''prob = ODEProblem(rhs!, u0, tspan)

function run_model(; u0=u0, tspan=tspan, dt=time_step, solver=Euler(){tab_args}){tab_load}
    dt == time_step || error("DELAY FIXED requires the declared fixed time step")
    solver isa Euler || error("Reference semantics require fixed-step Euler")
    # A private buffer stores inputs evaluated on the preceding step state.
    # rhs! may also be called at the new endpoint before the callback, so its
    # last evaluation cannot supply the discrete copy targets.
    # No delay is updated during initialization or before the first step.
    pending = similar(u0)
    prob_local = remake(prob; u0=u0, tspan=tspan, p=pending)
    callback = DiscreteCallback((u, t, integrator) -> true, _copy_fixed_delays!;
                                save_positions=(false, true))
    # saveat would capture the pre-callback delay values. Save the initial
    # state once, then each annual post-copy state via the callback instead.
    solve(prob_local, solver; dt=dt, saveat=Float64[], save_start=true,
          save_end=false, save_everystep=false, adaptive=false, callback=callback)
end
'''


def apply():
    from pysd.builders.julia.julia_model_builder import JuliaSectionBuilder
    if getattr(JuliaSectionBuilder, "_seneca_ode_applied", False):
        return
    JuliaSectionBuilder._seneca_ode_applied = True
    from pysd.builders.julia.julia_expressions_builder import JuliaASTVisitor, format_number
    from pysd.translators.structures.abstract_expressions import LogicStructure
    if not hasattr(JuliaASTVisitor, "_seneca_original_call"):
        JuliaASTVisitor._seneca_original_call = JuliaASTVisitor._call
    def call(self, node):
        name = node.function.reference.upper().replace(" ", "_")
        if name == "IF_THEN_ELSE":
            condition, yes, no = map(self.visit, node.arguments)
            if not isinstance(node.arguments[0], LogicStructure):
                condition = f"({condition} != 0)"
            return f"(({condition}) ? ({yes}) : ({no}))"
        if name == "ACTIVE_INITIAL":
            expression, initial = map(self.visit, node.arguments)
            return f"(c.initializing ? ({initial}) : ({expression}))"
        if name == "MODULO":
            return f"seneca_modulo({', '.join(self.visit(argument) for argument in node.arguments)})"
        value = self._seneca_original_call(node)
        for source, target in (("pysd_xidz", "seneca_xidz"), ("pysd_zidz", "seneca_zidz"),
                               ("pysd_step", "seneca_step"), ("pysd_ramp", "seneca_ramp"),
                               ("pysd_power", "seneca_power"), ("pysd_pulse", "seneca_pulse"),
                               ("pysd_pulse_train", "seneca_pulse_train")):
            value = value.replace(source + "(", target + "(")
        return value
    JuliaASTVisitor._call = call
    if not hasattr(JuliaASTVisitor, "_seneca_original_arithmetic"):
        JuliaASTVisitor._seneca_original_arithmetic = JuliaASTVisitor._arithmetic
    JuliaASTVisitor._arithmetic = lambda self, node: self._seneca_original_arithmetic(node).replace("pysd_power(", "seneca_power(")
    if not hasattr(JuliaASTVisitor, "_seneca_original_logic"):
        JuliaASTVisitor._seneca_original_logic = JuliaASTVisitor._logic
    def logic(self, node):
        value = self._seneca_original_logic(node)
        for operation in ("and", "or", "not"):
            value = value.replace(f"pysd_logical_{operation}(", f"seneca_logical_{operation}(")
        return value
    JuliaASTVisitor._logic = logic
    JuliaSectionBuilder._equations_block = _equations
    if not hasattr(JuliaSectionBuilder, "_seneca_original_run_function"):
        JuliaSectionBuilder._seneca_original_run_function = JuliaSectionBuilder._run_function
    JuliaSectionBuilder._run_function = _run_function
    JuliaSectionBuilder._u0_block = lambda self: '''const _initial_state_build = let
    started = time_ns()
    compilation = first(Base.cumulative_compile_time_ns())
    state = initial_state()
    (state, (time_ns()-started)/1e9,
     (first(Base.cumulative_compile_time_ns())-compilation)/1e9)
end
u0 = _initial_state_build[1]
const _included_initialization_seconds = _initial_state_build[2]
const _included_initialization_compilation_seconds = _initial_state_build[3]
'''
    # Dynamic INITIAL expressions must be frozen via an actual initial state,
    # not guessed by shallow textual substitution of another variable's source.
    JuliaSectionBuilder._resolve_initial_value = lambda self, ast: format_number(ast) if isinstance(ast, (int, float)) else None
