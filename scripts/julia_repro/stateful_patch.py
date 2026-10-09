"""Exact stateful expression lowering for the isolated Julia experiment.

Nested stateful calls become named, independently initialized ODE states.
The lowering preserves the component's labelled domain; it does not fold a
stateful expression into an instantaneous value or approximate its delay.
"""
from __future__ import annotations

from dataclasses import fields, is_dataclass, replace
import itertools
import math


def configure_delay_update_policy(updated_reads):
    """Set only audited direct nested-SMOOTH reads that use the new state.

    Ordinary fixtures default to simultaneous old-state inputs. The real
    pruned Python model may update a nested SMOOTH first; its observed policy
    is passed explicitly by the full-model translator and reset afterwards.
    """
    from pysd.builders.julia.julia_model_builder import JuliaSectionBuilder
    checked = {}
    for delay, states in updated_reads.items():
        if not delay.startswith("_delayfixed_") or states != ["_smooth_" + delay.removeprefix("_delayfixed_")]:
            raise ValueError(f"Unsupported sequential delay update: {delay} -> {states}")
        checked[delay] = list(states)
    JuliaSectionBuilder._seneca_reference_delay_updates = checked


def _smooth_nd(self, identifier, ast, visitor, order, dims=None):
    dims = dims or []
    if order < 1 or int(order) != order:
        raise ValueError(f"Invalid SMOOTH order for {identifier}: {order}")
    indices = self._idx_vars(len(dims))
    visit = self._nd_visitor(dims, indices) if dims else visitor
    input_expr = visit.visit(ast.input)
    smooth_time = visit.visit(ast.smooth_time)
    initial_expr = visit.visit(ast.initial)
    equations = []
    idx = ", ".join(indices)
    suffix = f"[{idx}]" if dims else ""
    declaration = f"[{self._range_str(dims)}]" if dims else ""
    cells = itertools.product(*(range(1, size + 1) for _, size in dims))
    cells = list(cells) if dims else [()]

    def equation(lhs, rhs):
        value = f"{lhs} ~ {rhs}"
        return f"[{value} for {self._for_clause(dims, indices)}]..." if dims else value

    previous = input_expr
    if not hasattr(self, "_seneca_smooth_states"):
        self._seneca_smooth_states = {}
    self._seneca_smooth_states[identifier] = []
    for level in range(1, order + 1):
        name = f"_lv{level}_{identifier}"
        self._seneca_smooth_states[identifier].append(name)
        self.namespace.namespace[f"__internal_lv{level}_{identifier}"] = name
        self._var_dims[name] = [dim for dim, _ in dims]
        self.stock_decls.append(f"@variables {name}(t){declaration}")
        for cell in cells:
            value = initial_expr
            for variable, position in zip(indices, cell):
                value = value.replace(variable, str(position))
            entry_suffix = f"[{', '.join(map(str, cell))}]" if dims else ""
            self.u0_entries.append(f"{name}{entry_suffix} => {value}")
        current = name + suffix
        equations.append(equation(f"D({current})", f"({previous} - {current}) / ({smooth_time} / {order})"))
        previous = current
    self._var_dims[identifier] = [dim for dim, _ in dims]
    self.aux_decls.append(f"@variables {identifier}(t){declaration}")
    equations.append(equation(identifier + suffix, previous))
    return equations


def _delay_fixed_nd(self, identifier, ast, visitor, dims=None):
    """Use the reference's fixed-step ring-buffer semantics, in every axis."""
    if self.backend != "ode":
        raise ValueError("The reproducibility patch supports only the ODE backend")
    dims = dims or []
    indices = self._idx_vars(len(dims))
    visit = self._nd_visitor(dims, indices) if dims else visitor
    delay_expr = visit.visit(ast.delay_time)
    delay = self._try_eval_as_float(delay_expr)
    step = self._try_eval_as_float(self.control_vals.get("time_step") or "1.0")
    if delay is None or step is None or not math.isfinite(delay) or step <= 0:
        raise ValueError(f"Unresolved fixed delay for {identifier}: {delay_expr}")
    # PySD 3.14.3 DelayFixed.initialize uses max(delay / dt, 1), with
    # SMALL_VENSIM = 1e-6 before rounding ties. No continuous-delay fallback.
    count = round(max(delay / step, 1) + 1e-6)
    result = self._expand_delay_fixed_pipeline(
        identifier, visit.visit(ast.input), visit.visit(ast.initial), count, dims
    )
    # Keep discrete copy targets separate from the ODE derivatives. Computing
    # old + (input-old) is not a Float64 copy (small values can disappear).
    # PySD DelayFixed.update writes the input directly into its ring buffer.
    if not hasattr(self, "_seneca_fixed_delays"):
        self._seneca_fixed_delays = {}
    suffix = f"[{', '.join(indices)}]" if dims else ""
    previous = visit.visit(ast.input)
    for level in range(1, count + 1):
        name = f"_df_pipe_{level}_{identifier}"
        equation = f"D({name}{suffix}) ~ {previous}"
        if dims:
            equation = f"[{equation} for {self._for_clause(dims, indices)}]..."
        self._seneca_fixed_delays[name] = equation
        previous = name + suffix
    policy_name = "_delayfixed_" + identifier
    if policy_name in getattr(self, "_seneca_reference_delay_updates", {}):
        from pysd.translators.structures.abstract_expressions import ReferenceStructure
        states = (getattr(self, "_seneca_smooth_states", {}).get(ast.input.reference)
                  if isinstance(ast.input, ReferenceStructure) else None)
        if not states or not ast.input.reference.startswith("_nested_"):
            raise ValueError(f"Audited new-state delay input is not a direct nested SMOOTH: {identifier}")
        if not hasattr(self, "_seneca_delay_new_state_sources"):
            self._seneca_delay_new_state_sources = {}
            self._seneca_delay_update_policy_used = {}
        self._seneca_delay_new_state_sources[f"_df_pipe_1_{identifier}"] = states.copy()
        self._seneca_delay_update_policy_used[policy_name] = states.copy()
    self._var_dims[identifier] = [dim for dim, _ in dims]
    for level in range(1, count + 1):
        self._var_dims[f"_df_pipe_{level}_{identifier}"] = [dim for dim, _ in dims]
    return result


def apply():
    from pysd.builders.julia.julia_model_builder import JuliaSectionBuilder, _STATEFUL_STRUCTURES
    from pysd.translators.structures.abstract_model import AbstractComponent, AbstractData
    from pysd.translators.structures.abstract_expressions import (
        AbstractSyntax, DataStructure, GetDataStructure, ReferenceStructure,
        SubscriptsReferenceStructure, InitialStructure,
    )
    current = JuliaSectionBuilder._process_element
    if getattr(current, "_seneca_stateful_lowering", False):
        return

    def process(self, elem, identifier, is_control=False):
        equations, components = [], []
        dims = self._element_dims(elem)
        full_domain = [dim for dim, _ in dims]
        for comp_index, component in enumerate(elem.components):
            memo = {}

            def lower(node, *, root=False):
                if not isinstance(node, AbstractSyntax) or not is_dataclass(node):
                    if isinstance(node, tuple):
                        return tuple(lower(value) for value in node)
                    if isinstance(node, list):
                        return [lower(value) for value in node]
                    return node
                if not root and isinstance(node, InitialStructure):
                    raise ValueError(f"Nested INITIAL requires explicit lowering: {elem.name}")
                if not root and isinstance(node, _STATEFUL_STRUCTURES) and id(node) in memo:
                    return memo[id(node)]
                updated = replace(node, **{field.name: lower(getattr(node, field.name)) for field in fields(node)})
                if root or not isinstance(node, _STATEFUL_STRUCTURES):
                    return updated
                if component.subscripts[1] or list(component.subscripts[0]) != full_domain:
                    raise ValueError(f"Nested state on a partial component domain requires explicit lowering: {elem.name}")
                number = len(memo)
                name = f"_nested_{identifier}_{comp_index}_{number}"
                while name in self.namespace.namespace.values():
                    number += 1
                    name = f"_nested_{identifier}_{comp_index}_{number}"
                self.namespace.namespace[name] = name
                self._var_dims[name] = full_domain.copy()
                inner = replace(elem, name=name, components=[AbstractComponent(
                    subscripts=(full_domain.copy(), []), ast=updated,
                )])
                equations.extend(current(self, inner, name, False))
                reference = ReferenceStructure(name, SubscriptsReferenceStructure(full_domain.copy()) if dims else None)
                memo[id(node)] = reference
                return reference

            ast = lower(component.ast, root=True)
            if isinstance(component, AbstractData) and not isinstance(ast, (GetDataStructure, DataStructure)):
                # Python 3.14.3 emits this equation as an ordinary function.
                # :INTERPOLATE: affects actual external/tab data only. Explicit
                # scenario replacements are handled before this lowering step.
                normalized = AbstractComponent(component.subscripts, ast)
                if not hasattr(self, "_seneca_data_expressions"):
                    self._seneca_data_expressions = []
                self._seneca_data_expressions.append({"name": elem.name, "semantics": "ordinary_expression"})
            else:
                normalized = replace(component, ast=ast)
            components.append(normalized)
        equations.extend(current(self, replace(elem, components=components), identifier, is_control))
        return equations

    process._seneca_stateful_lowering = True
    JuliaSectionBuilder._process_element = process
    JuliaSectionBuilder._expand_smooth = _smooth_nd
    JuliaSectionBuilder._expand_delay_fixed = _delay_fixed_nd
