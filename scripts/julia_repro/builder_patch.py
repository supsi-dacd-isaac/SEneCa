"""Experiment-only patches for the pinned Julia builder.

No installed application package is edited. Fail on unresolved semantics rather
than accepting the upstream broadcast/zero fallbacks.
"""
from __future__ import annotations

from collections import defaultdict
import itertools
import re


def component_cells(specs, excluded, dimensions, ranges):
    """Resolve labelled N-D domains and subtract complete exclusion tuples."""
    def resolve(spec, dim):
        labels = ranges.get(spec, [spec]) if spec is not None else dimensions[dim]
        allowed = set(labels)
        if not allowed <= set(dimensions[dim]):
            raise ValueError(f"Subscript {spec!r} contains labels outside {dim}")
        values = [i + 1 for i, value in enumerate(dimensions[dim]) if value in allowed]
        if not values:
            raise ValueError(f"Empty/unknown subscript {spec!r} in {dim}")
        return values
    names = list(dimensions)
    if len(specs) != len(names):
        raise ValueError("Subscript rank mismatch")
    covered = set(itertools.product(*(resolve(s, d) for s, d in zip(specs, names))))
    for clause in excluded:
        if len(clause) != len(names):
            raise ValueError("EXCEPT rank mismatch")
        covered.difference_update(itertools.product(*(resolve(s, d) for s, d in zip(clause, names))))
    return sorted(covered)


def _rectangles(cells):
    """Compress an exact set into disjoint Cartesian products; no bounding boxes."""
    if not cells:
        return []
    if len(cells[0]) == 1:
        return [(tuple(c[0] for c in cells),)]
    tails = defaultdict(list)
    for cell in cells:
        tails[cell[0]].append(cell[1:])
    groups = defaultdict(list)
    for head, tail in tails.items():
        groups[tuple(tail)].append(head)
    return [(tuple(heads), *rectangle) for tail, heads in groups.items()
            for rectangle in _rectangles(list(tail))]


def _except_nd(self, elem, identifier, is_control):
    from pysd.builders.julia.julia_model_builder import _STATEFUL_STRUCTURES
    dims = self._element_dims(elem)
    if not dims:
        raise ValueError(f"Scalar multi-component element: {elem.name}")
    if any(isinstance(c.ast, _STATEFUL_STRUCTURES) for c in elem.components):
        raise ValueError(f"Multi-component stateful requires explicit implementation: {elem.name}")
    coordinates = {d: self._subs_elems[d] for d, _ in dims}
    all_cells = set(itertools.product(*(range(1, n+1) for _, n in dims)))
    seen, equations = set(), []
    for comp in elem.components:
        cells = component_cells(comp.subscripts[0], comp.subscripts[1], coordinates, self._subs_elems)
        overlap = seen.intersection(cells)
        if overlap:
            raise ValueError(f"Overlapping definitions in {elem.name}: {next(iter(overlap))}")
        seen.update(cells)
        idx_vars = self._idx_vars(len(dims))
        def component_visitor(indices):
            visitor = self._nd_visitor(dims, indices)
            for spec, (dim, _), index in zip(comp.subscripts[0], dims, indices):
                if spec in self._subs_elems and spec != dim:
                    visitor.active_subs[spec] = index
                    visitor._clean_active_subs[re.sub(r"[^a-z0-9_]", "_", spec.lower())] = index
            return visitor
        visitor = component_visitor(idx_vars)
        expression = visitor.visit(comp.ast)
        # Self references need cell-level dependency resolution; keep literal indices.
        if re.search(rf"\b{re.escape(identifier)}\b", expression):
            for cell in cells:
                rhs = component_visitor(list(map(str, cell))).visit(comp.ast)
                equations.append(f"{identifier}[{', '.join(map(str, cell))}] ~ {rhs}")
        else:
            for rectangle in _rectangles(cells):
                for_clause = ", ".join(f"{iv} in [{', '.join(map(str, indices))}]"
                                       for iv, indices in zip(idx_vars, rectangle))
                equations.append(f"[{identifier}[{', '.join(idx_vars)}] ~ {expression} for {for_clause}]...")
    if seen != all_cells:
        raise ValueError(f"Unassigned cells in {elem.name}: {len(all_cells-seen)}")
    if not is_control:
        self.aux_decls.append(f"@variables {identifier}(t)[{self._range_str(dims)}]")
    return equations


def _sort_equations(self, equations, stock_names):
    """Dependencies target *all* assignments of a variable, not only its first."""
    groups = defaultdict(list)
    for equation in equations:
        name = self._extract_lhs_name(equation)
        if name is None:
            raise ValueError(f"Unrecognised algebraic equation: {equation[:200]}")
        groups[name].append(equation)
    deps = {name: set().union(*(self._extract_rhs_identifiers(e) for e in eqs)) & groups.keys() - {name}
            for name, eqs in groups.items()}
    result, remaining = [], dict(groups)
    while remaining:
        ready = [name for name in remaining if not deps[name].intersection(remaining)]
        if not ready:
            raise ValueError(f"Algebraic dependency cycle: {sorted(remaining)[:20]}")
        for name in ready:
            rows = remaining.pop(name)
            plain, selfrefs = [], []
            for row in rows:
                (selfrefs if name in self._extract_rhs_identifiers(row) else plain).append(row)
            result.extend(plain)
            # Full coverage is checked above. Self-reference chains are resolved
            # by exact indexed LHS; a genuine cycle must not read zero-filled memory.
            written = set()
            for row in plain:
                if row.startswith("["):
                    # A covered non-self component can be a rectangular loop.
                    match = re.match(r"\[(\w+)\[([^]]+)\]", row)
                    ranges = re.findall(r"_i\d+ in \[([^]]+)\]", row)
                    if match and ranges:
                        for cell in itertools.product(*([int(x) for x in r.split(",")] for r in ranges)):
                            written.add(tuple(cell))
                else:
                    m = re.match(r"\w+\[([\d, ]+)\]", row)
                    if m:
                        written.add(tuple(map(int, m[1].split(","))))
            while selfrefs:
                progress = False
                for row in list(selfrefs):
                    rhs = row.split(" ~ ", 1)[1]
                    matches = re.findall(rf"\b{re.escape(name)}\[([^]]+)\]", rhs)
                    if not matches or any(not re.fullmatch(r"[\d, ]+", m) for m in matches):
                        raise ValueError(f"Unresolved self-reference: {row[:200]}")
                    needed = {tuple(map(int, m.split(","))) for m in matches}
                    if needed <= written:
                        lhs = re.match(r"\w+\[([\d, ]+)\]", row)
                        if not lhs:
                            raise ValueError(f"Unresolved self-reference LHS: {row[:200]}")
                        written.add(tuple(map(int, lhs[1].split(","))))
                        result.append(row)
                        selfrefs.remove(row)
                        progress = True
                if not progress:
                    raise ValueError(f"Self-reference cycle or uncovered source in {name}: {selfrefs[0][:600]}; written={len(written)}")
    return result


def apply():
    from pysd.builders.julia.julia_model_builder import JuliaSectionBuilder
    from pysd.translators.structures.abstract_expressions import GetDataStructure, GetConstantsStructure, GetLookupsStructure, LookupsStructure
    from pysd.builders.julia.julia_model_builder import _STATEFUL_STRUCTURES
    if not hasattr(JuliaSectionBuilder, "_repro_original_process"):
        JuliaSectionBuilder._repro_original_process = JuliaSectionBuilder._process_element
        JuliaSectionBuilder._repro_original_write_json = JuliaSectionBuilder._write_data_json
        JuliaSectionBuilder._repro_original_allocate = JuliaSectionBuilder._expand_allocate
        JuliaSectionBuilder._repro_original_content = JuliaSectionBuilder._full_file_content
        JuliaSectionBuilder._repro_original_u0 = JuliaSectionBuilder._u0_block
        JuliaSectionBuilder._repro_original_lookup = JuliaSectionBuilder._lookup_block

    def lookup(self):
        value = self._repro_original_lookup()
        # Scalar JSON time series must clamp to endpoint values like ExtData.
        # Subscript dispatch is still checked by full-model translation gates.
        value = re.sub(r'(Float64\.\(_model_data\["data"\]\["[^"\n]+"\]\["time"\]\))\)',
                       r'\1; extrapolation_left=ExtrapolationType.Constant, extrapolation_right=ExtrapolationType.Constant)', value)
        return value

    def u0(self):
        # The upstream emitter enumerates Python products (last axis fastest),
        # but unpacks the ODE vector using Julia reshape (first axis fastest).
        groups = defaultdict(list)
        for entry in self.u0_entries:
            lhs = entry.split("=>", 1)[0].strip()
            name = lhs.split("[")[0]
            match = re.search(r"\[([\d, ]+)\]", lhs)
            indices = tuple(map(int, match[1].split(","))) if match else ()
            groups[name].append((indices, entry))
        self.u0_entries = [entry for items in groups.values()
                           for _, entry in sorted(items, key=lambda x: tuple(reversed(x[0])))]
        return self._repro_original_u0()

    def allocate(self, identifier, ast, visitor):
        from pysd.translators.structures.abstract_expressions import AllocateAvailableStructure
        if not isinstance(ast, AllocateAvailableStructure):
            raise ValueError("ALLOCATE BY PRIORITY is outside the verified SURE profile")
        pp_name = self.namespace.get(ast.pp.reference)
        if pp_name is None:
            raise ValueError("Unresolved allocation profile")
        request, available = visitor.visit(ast.request), visitor.visit(ast.avail)
        return [f"{identifier} ~ seneca_allocate_available({request}, {pp_name}, {available})"]

    def content(self, equations):
        from .common import CONFIG
        value = self._repro_original_content(equations)
        # SafeArray silently returns zero for out-of-bounds reads and drops writes.
        # Such behaviour is incompatible with an equivalence test.
        value = value.replace("pysd_safe(", "identity(")
        # Missing initial auxiliaries must not silently become zero.
        value = re.sub(r'get\(_obs_init, "([^"\n]+)", 0\.0\)', r'_obs_init["\1"]', value)
        helper = (CONFIG / "allocation.jl").read_text()
        return helper + "\n" + value

    def write_data(self):
        import numpy as np
        def plain(value):
            if isinstance(value, np.ndarray):
                return plain(value.tolist())
            if isinstance(value, np.generic):
                return value.item()
            if isinstance(value, dict):
                return {k: plain(v) for k, v in value.items()}
            if isinstance(value, (tuple, list)):
                return [plain(v) for v in value]
            return value
        self._json_data = plain(self._json_data)
        return self._repro_original_write_json()

    def infer(self, elements, exclude=None):
        labels = set().union(*(set(self._subs_elems.get(e, [e])) for e in elements))
        candidates = [(len(values), name) for name, values in self._subs_elems.items()
                      if name not in (exclude or set()) and labels <= set(values)]
        return min(candidates)[1] if candidates else None

    def process(self, elem, identifier, is_control=False):
        excluded_types = (GetDataStructure, GetConstantsStructure, GetLookupsStructure, LookupsStructure, *_STATEFUL_STRUCTURES)
        if len(elem.components) > 1 and not any(isinstance(c.ast, excluded_types) for c in elem.components):
            return self._process_except_element(elem, identifier, is_control)
        return self._repro_original_process(elem, identifier, is_control)

    JuliaSectionBuilder._infer_parent_range = infer
    JuliaSectionBuilder._infer_parent_range_not_in = infer
    JuliaSectionBuilder._process_element = process
    JuliaSectionBuilder._write_data_json = write_data
    JuliaSectionBuilder._expand_allocate = allocate
    JuliaSectionBuilder._full_file_content = content
    JuliaSectionBuilder._u0_block = u0
    JuliaSectionBuilder._lookup_block = lookup
    JuliaSectionBuilder._process_except_element = _except_nd
    JuliaSectionBuilder._topo_sort_equations = _sort_equations
    # The experiment explicitly invokes run_model; including a generated file
    # must not launch an unmeasured simulation or write unsolicited results.
    JuliaSectionBuilder._entrypoint_block = lambda self: ""
